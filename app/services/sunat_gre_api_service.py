"""Cliente de la API REST de Guías de Remisión Electrónicas (GRE) de SUNAT.

Flujo: token OAuth2 (password grant con credenciales "API SUNAT" + usuario SOL) ->
POST del ZIP con el XML firmado (responde un ticket) -> GET del ticket hasta obtener
el CDR. Códigos del ticket: "0" procesado, "98" en proceso, "99" procesado con error.
SUNAT no tiene entorno beta para GRE: cada envío es real.
"""

import asyncio
import base64
import hashlib
import io
import time
import zipfile
from dataclasses import dataclass
from typing import Any

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from app.core.config import settings

CODIGO_TICKET_PROCESADO = "0"
CODIGO_TICKET_EN_PROCESO = "98"
CODIGO_TICKET_CON_ERROR = "99"

_SCOPE = "https://api-cpe.sunat.gob.pe"
_MARGEN_RENOVACION_TOKEN_SEGUNDOS = 60

_tokens: dict[str, tuple[str, float]] = {}
_tokens_lock = asyncio.Lock()


class SunatGreError(Exception):
    """Error de configuración, red o respuesta inesperada de la API de GRE (no un
    rechazo del documento por parte de SUNAT, que llega en el ticket)."""


@dataclass(frozen=True)
class RespuestaTicket:
    codigo: str
    cdr_zip: bytes | None
    error_codigo: str | None = None
    error_mensaje: str | None = None


def credenciales_faltantes() -> list[str]:
    nombres = ("SUNAT_GRE_CLIENT_ID", "SUNAT_GRE_CLIENT_SECRET", "SUNAT_SOL_USUARIO", "SUNAT_SOL_CLAVE")
    return [nombre for nombre in nombres if not getattr(settings, nombre)]


def empaquetar_zip(nombre_archivo: str, xml: bytes) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zip_:
        zip_.writestr(f"{nombre_archivo}.xml", xml)
    return buffer.getvalue()


def _mensaje_error(response: httpx.Response) -> str:
    """SUNAT responde errores con formas distintas según el servicio:
    {"cod","msg"}, {"errors":[{"cod","msg"}]} o {"error","error_description"}."""
    try:
        cuerpo = response.json()
    except ValueError:
        return f"HTTP {response.status_code}"
    if isinstance(cuerpo, dict):
        if cuerpo.get("errors"):
            return "; ".join(f"{e.get('cod', '')} {e.get('msg', '')}".strip() for e in cuerpo["errors"])
        if cuerpo.get("msg"):
            return f"{cuerpo.get('cod', '')} {cuerpo['msg']}".strip()
        if cuerpo.get("error_description") or cuerpo.get("error"):
            return str(cuerpo.get("error_description") or cuerpo.get("error"))
    return f"HTTP {response.status_code}"


class ClienteSunatGre:
    def __init__(self, http_client: httpx.AsyncClient | None = None) -> None:
        faltantes = credenciales_faltantes()
        if faltantes:
            raise SunatGreError("Faltan credenciales de la API de GRE de SUNAT: " + ", ".join(faltantes))
        self._client = http_client or httpx.AsyncClient(timeout=settings.SUNAT_GRE_TIMEOUT_SECONDS)

    async def cerrar(self) -> None:
        await self._client.aclose()

    @property
    def _clave_cache(self) -> str:
        return f"{settings.SUNAT_GRE_CLIENT_ID}:{settings.SUNAT_SOL_USUARIO}"

    @retry(
        reraise=True,
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=0.5, max=4),
        retry=retry_if_exception_type(httpx.TransportError),
    )
    async def _pedir_token(self) -> tuple[str, float]:
        response = await self._client.post(
            f"{settings.SUNAT_GRE_TOKEN_URL}/{settings.SUNAT_GRE_CLIENT_ID}/oauth2/token/",
            data={
                "grant_type": "password",
                "scope": _SCOPE,
                "client_id": settings.SUNAT_GRE_CLIENT_ID,
                "client_secret": settings.SUNAT_GRE_CLIENT_SECRET.get_secret_value(),
                "username": settings.SUNAT_SOL_USUARIO,
                "password": settings.SUNAT_SOL_CLAVE.get_secret_value(),
            },
        )
        if response.status_code != 200:
            raise SunatGreError(
                "SUNAT rechazó las credenciales de la API de GRE (revise SUNAT_GRE_CLIENT_ID/SECRET y el "
                f"usuario/clave SOL): {_mensaje_error(response)}"
            )
        datos = response.json()
        return datos["access_token"], time.monotonic() + int(datos.get("expires_in", 3600))

    async def _token(self, renovar: bool = False) -> str:
        async with _tokens_lock:
            guardado = _tokens.get(self._clave_cache)
            if not renovar and guardado and guardado[1] - _MARGEN_RENOVACION_TOKEN_SEGUNDOS > time.monotonic():
                return guardado[0]
            try:
                token, vence = await self._pedir_token()
            except httpx.TransportError as error:
                raise SunatGreError(f"No se pudo conectar con el servicio de autenticación de SUNAT: {error}") from error
            _tokens[self._clave_cache] = (token, vence)
            return token

    async def enviar(self, nombre_archivo: str, zip_bytes: bytes) -> str:
        """Envía el ZIP y devuelve el número de ticket. No reintenta ante errores de
        red: un reintento ciego podría duplicar el envío de un documento real."""
        cuerpo = {
            "archivo": {
                "nomArchivo": f"{nombre_archivo}.zip",
                "arcGreZip": base64.b64encode(zip_bytes).decode(),
                "hashZip": hashlib.sha256(zip_bytes).hexdigest(),
            }
        }
        url = f"{settings.SUNAT_GRE_API_URL}/contribuyente/gem/comprobantes/{nombre_archivo}"
        for intento in range(2):
            token = await self._token(renovar=intento > 0)
            try:
                response = await self._client.post(url, json=cuerpo, headers={"Authorization": f"Bearer {token}"})
            except httpx.TransportError as error:
                raise SunatGreError(f"No se pudo conectar con SUNAT para enviar la guía: {error}") from error
            if response.status_code == 401 and intento == 0:
                continue  # token vencido o revocado: se renueva una vez
            break

        if response.status_code not in (200, 201):
            raise SunatGreError(f"SUNAT no recibió la guía: {_mensaje_error(response)}")
        ticket = response.json().get("numTicket")
        if not ticket:
            raise SunatGreError("SUNAT recibió la guía pero no devolvió número de ticket")
        return str(ticket)

    @retry(
        reraise=True,
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=0.5, max=4),
        retry=retry_if_exception_type(httpx.TransportError),
    )
    async def _get_ticket(self, ticket: str, token: str) -> httpx.Response:
        return await self._client.get(
            f"{settings.SUNAT_GRE_API_URL}/contribuyente/gem/comprobantes/envios/{ticket}",
            headers={"Authorization": f"Bearer {token}"},
        )

    async def consultar_ticket(self, ticket: str) -> RespuestaTicket:
        for intento in range(2):
            token = await self._token(renovar=intento > 0)
            try:
                response = await self._get_ticket(ticket, token)
            except httpx.TransportError as error:
                raise SunatGreError(f"No se pudo conectar con SUNAT para consultar el ticket: {error}") from error
            if response.status_code == 401 and intento == 0:
                continue
            break

        if response.status_code != 200:
            raise SunatGreError(f"No se pudo consultar el ticket {ticket}: {_mensaje_error(response)}")

        datos: dict[str, Any] = response.json()
        error = datos.get("error") or {}
        cdr = datos.get("arcCdr")
        return RespuestaTicket(
            codigo=str(datos.get("codRespuesta", "")),
            cdr_zip=base64.b64decode(cdr) if cdr else None,
            error_codigo=str(error["numError"]) if error.get("numError") is not None else None,
            error_mensaje=error.get("desError"),
        )
