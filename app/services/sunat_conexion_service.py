"""Diagnóstico de la conexión con SUNAT: qué está listo y qué falta, sin enviar nada."""

import re
from dataclasses import dataclass
from datetime import datetime, timezone

from app.core.config import settings
from app.models.empresa import Empresa
from app.services.sunat_certificado_service import CertificadoSunatError, cargar_certificado
from app.services.sunat_gre_api_service import ClienteSunatGre, SunatGreError

_RE_USUARIO_SOL = re.compile(r"^(\d{11})([A-Z0-9]{3,})$", re.IGNORECASE)
_VALORES_DE_EJEMPLO = {"", "bearer_token_de_apisunat_pe", "token-de-prueba"}


@dataclass
class Conexion:
    clave: str  # certificado | credenciales_gre | credenciales_sol | facturas
    nombre: str
    lista: bool
    detalle: str


def _certificado() -> Conexion:
    nombre = "Certificado digital (.p12)"
    try:
        cert = cargar_certificado()
    except CertificadoSunatError as error:
        return Conexion("certificado", nombre, False, str(error))
    dias = (cert.vence_en - datetime.now(timezone.utc)).days
    aviso = " — renuévalo pronto" if dias <= 30 else ""
    return Conexion("certificado", nombre, True, f"Abre correctamente. Vence el {cert.vence_en:%d/%m/%Y} ({dias} días){aviso}")


def _credenciales_gre() -> Conexion:
    nombre = "Credenciales de API SUNAT (guías)"
    faltan = [n for n in ("SUNAT_GRE_CLIENT_ID", "SUNAT_GRE_CLIENT_SECRET") if not getattr(settings, n)]
    if faltan:
        return Conexion("credenciales_gre", nombre, False, "Falta configurar en Render: " + ", ".join(faltan))
    return Conexion("credenciales_gre", nombre, True, "Client ID y client secret configurados")


def _credenciales_sol(empresa: Empresa | None) -> Conexion:
    nombre = "Usuario y clave SOL"
    faltan = [n for n in ("SUNAT_SOL_USUARIO", "SUNAT_SOL_CLAVE") if not getattr(settings, n)]
    if faltan:
        return Conexion("credenciales_sol", nombre, False, "Falta configurar en Render: " + ", ".join(faltan))
    coincidencia = _RE_USUARIO_SOL.fullmatch(settings.SUNAT_SOL_USUARIO.strip())
    if not coincidencia:
        return Conexion(
            "credenciales_sol", nombre, False,
            "SUNAT_SOL_USUARIO debe ser el RUC (11 dígitos) seguido del usuario SOL, sin espacios ni '+'",
        )
    if empresa is not None and coincidencia.group(1) != empresa.ruc:
        return Conexion(
            "credenciales_sol", nombre, False,
            f"SUNAT_SOL_USUARIO empieza con el RUC {coincidencia.group(1)}, pero la empresa tiene RUC {empresa.ruc}",
        )
    return Conexion("credenciales_sol", nombre, True, f"Usuario {coincidencia.group(2).upper()} del RUC {coincidencia.group(1)}")


def _facturas() -> Conexion:
    nombre = "Facturas y boletas (vía apisunat.pe)"
    token = (settings.APISUNAT_TOKEN or "").strip()
    if token.lower() in _VALORES_DE_EJEMPLO:
        return Conexion("facturas", nombre, False, "Falta configurar APISUNAT_TOKEN en Render")
    return Conexion("facturas", nombre, True, "Token de apisunat.pe configurado")


def estado_conexiones(empresa: Empresa | None) -> list[Conexion]:
    return [_certificado(), _credenciales_gre(), _credenciales_sol(empresa), _facturas()]


async def probar_conexion_gre(empresa: Empresa | None) -> tuple[bool, str]:
    """Pide un token a SUNAT con las credenciales configuradas. No firma ni envía
    ningún documento. Es la prueba que confirma el client ID/secret y la clave SOL."""
    conexiones = {c.clave: c for c in estado_conexiones(empresa)}
    pendientes = [c for k, c in conexiones.items() if k in ("certificado", "credenciales_gre", "credenciales_sol") and not c.lista]
    if pendientes:
        return False, "Antes de probar, completa: " + "; ".join(f"{c.nombre}: {c.detalle}" for c in pendientes)

    try:
        cliente = ClienteSunatGre()
    except SunatGreError as error:
        return False, str(error)
    try:
        vigencia = await cliente.probar_credenciales()
    except SunatGreError as error:
        return False, str(error)
    finally:
        await cliente.cerrar()
    return True, (
        f"Conexión con SUNAT correcta: el token fue emitido (vigente {vigencia // 60} min). "
        "Ya puedes emitir guías. No se envió ningún documento."
    )
