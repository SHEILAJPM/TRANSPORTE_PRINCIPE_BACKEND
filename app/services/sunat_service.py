import re
from datetime import datetime, timezone
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from app.core.config import settings
from app.models.cliente import Cliente
from app.models.enums import TipoDocumentoIdentidad
from app.models.sunat_log import ConsultaSunatLog
from app.schemas.sunat import DniConsultaResponse, RucConsultaResponse

_RUC_REGEX = re.compile(r"^\d{11}$")
_DNI_REGEX = re.compile(r"^\d{8}$")


class ApiSunatError(Exception):
    """Error genérico al comunicarse con apisunat.pe."""


class ApiSunatNotFoundError(ApiSunatError):
    """El RUC/DNI no existe en apisunat.pe (HTTP 404)."""


class ApiSunatDocumentoInvalidoError(ApiSunatError):
    """El número de documento no tiene el formato esperado (11 dígitos RUC / 8 dígitos DNI)."""


class ApiSunatService:
    """Cliente HTTP para Decolecta (consulta de RUC/DNI vía RENIEC/SUNAT, Bearer
    Token). Es un proveedor distinto de apisunat.pe: apisunat.pe solo emite
    comprobantes electrónicos (guías, facturas), no ofrece consulta de RUC/DNI."""

    def __init__(self, http_client: httpx.AsyncClient | None = None) -> None:
        self._client = http_client or httpx.AsyncClient(
            base_url=settings.DECOLECTA_BASE_URL,
            headers={
                "Authorization": f"Bearer {settings.DECOLECTA_TOKEN}",
                "Referer": "transporte-principe",
                "Accept": "application/json",
            },
            timeout=settings.DECOLECTA_TIMEOUT_SECONDS,
        )

    async def cerrar(self) -> None:
        await self._client.aclose()

    @retry(
        reraise=True,
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=0.5, max=4),
        retry=retry_if_exception_type(httpx.TransportError),
    )
    async def _get(self, path: str, params: dict[str, str]) -> dict[str, Any]:
        response = await self._client.get(path, params=params)

        if response.status_code in (404, 422):
            raise ApiSunatNotFoundError(f"No se encontró información para {params}")
        if response.status_code == 401:
            raise ApiSunatError("Token de Decolecta inválido o vencido")
        if response.status_code == 403:
            raise ApiSunatError("Acceso denegado por Decolecta (IP bloqueada)")
        if response.status_code == 429:
            raise ApiSunatError("Límite de consultas a Decolecta excedido, intente nuevamente")
        response.raise_for_status()

        return response.json()

    async def consultar_ruc(self, ruc: str) -> RucConsultaResponse:
        if not _RUC_REGEX.fullmatch(ruc):
            raise ApiSunatDocumentoInvalidoError("El RUC debe tener 11 dígitos numéricos")

        data = await self._get("/v1/sunat/ruc", params={"numero": ruc})

        return RucConsultaResponse(
            numero_documento=data["numero_documento"],
            razon_social=data["razon_social"],
            nombre_comercial=data.get("nombre_comercial"),
            estado=data.get("estado"),
            condicion=data.get("condicion"),
            direccion=data.get("direccion"),
            distrito=data.get("distrito"),
            provincia=data.get("provincia"),
            departamento=data.get("departamento"),
            ubigeo=data.get("ubigeo"),
        )

    async def consultar_dni(self, dni: str) -> DniConsultaResponse:
        if not _DNI_REGEX.fullmatch(dni):
            raise ApiSunatDocumentoInvalidoError("El DNI debe tener 8 dígitos numéricos")

        data = await self._get("/v1/reniec/dni", params={"numero": dni})

        return DniConsultaResponse(
            numero_documento=data["document_number"],
            nombres=data["first_name"],
            apellido_paterno=data["first_last_name"],
            apellido_materno=data["second_last_name"],
        )


async def obtener_o_crear_cliente(
    db: AsyncSession,
    apisunat: ApiSunatService,
    tipo_documento: TipoDocumentoIdentidad,
    numero_documento: str,
    usuario_id,
    forzar_actualizacion: bool = False,
) -> Cliente:
    """Autocompleta un Cliente desde apisunat.pe. Si el documento ya está registrado
    localmente y no se pide forzar_actualizacion, evita una llamada innecesaria a la API.
    """
    cliente_existente = (
        await db.execute(select(Cliente).where(Cliente.numero_documento == numero_documento))
    ).scalar_one_or_none()
    if cliente_existente is not None and not forzar_actualizacion:
        return cliente_existente

    exitosa = True
    mensaje_error: str | None = None
    respuesta_json: dict[str, Any] | None = None

    try:
        if tipo_documento == TipoDocumentoIdentidad.RUC:
            resultado = await apisunat.consultar_ruc(numero_documento)
            respuesta_json = resultado.model_dump()
            datos_cliente = {
                "razon_social": resultado.razon_social,
                "nombre_comercial": resultado.nombre_comercial,
                "direccion": resultado.direccion,
                "distrito": resultado.distrito,
                "provincia": resultado.provincia,
                "departamento": resultado.departamento,
                "ubigeo": resultado.ubigeo,
                "estado_sunat": resultado.estado,
                "condicion_sunat": resultado.condicion,
            }
        else:
            resultado = await apisunat.consultar_dni(numero_documento)
            respuesta_json = resultado.model_dump()
            datos_cliente = {"razon_social": resultado.nombre_completo}
    except ApiSunatError as error:
        exitosa = False
        mensaje_error = str(error)
        raise
    finally:
        db.add(
            ConsultaSunatLog(
                usuario_id=usuario_id,
                tipo_documento=tipo_documento,
                numero_documento=numero_documento,
                exitosa=exitosa,
                respuesta_json=respuesta_json,
                mensaje_error=mensaje_error,
            )
        )

    if cliente_existente is not None:
        for campo, valor in datos_cliente.items():
            if valor is not None:
                setattr(cliente_existente, campo, valor)
        cliente_existente.fuente_datos = "apisunat.pe"
        cliente = cliente_existente
    else:
        cliente = Cliente(
            tipo_documento=tipo_documento,
            numero_documento=numero_documento,
            fuente_datos="apisunat.pe",
            **datos_cliente,
        )
        db.add(cliente)

    cliente.consultado_en = datetime.now(timezone.utc)

    await db.flush()
    return cliente
