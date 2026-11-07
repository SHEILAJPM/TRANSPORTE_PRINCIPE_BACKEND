"""Diagnóstico y "Probar conexión con SUNAT" (solo pide el token, no envía nada)."""

import asyncio

import httpx
import pytest
from pydantic import SecretStr

from app.core.config import settings
from app.models.empresa import Empresa
from app.services import sunat_conexion_service as conexion
from app.services import sunat_gre_api_service as api
from tests.test_guia_transportista import certificado  # noqa: F401  (fixture)

EMPRESA = Empresa(ruc="10106693451", razon_social="TRANSPORTE PRINCIPE")


@pytest.fixture
def configurado(monkeypatch, certificado):
    monkeypatch.setattr(conexion, "cargar_certificado", lambda: certificado)
    monkeypatch.setattr(settings, "SUNAT_GRE_CLIENT_ID", "cliente-id")
    monkeypatch.setattr(settings, "SUNAT_GRE_CLIENT_SECRET", SecretStr("secreto"))
    monkeypatch.setattr(settings, "SUNAT_SOL_USUARIO", "10106693451NSATESIS")
    monkeypatch.setattr(settings, "SUNAT_SOL_CLAVE", SecretStr("clave"))
    monkeypatch.setattr(settings, "APISUNAT_TOKEN", "token-real-123")
    api._tokens.clear()


def _por_clave(empresa=EMPRESA):
    return {c.clave: c for c in conexion.estado_conexiones(empresa)}


def test_todo_configurado(configurado):
    estado = _por_clave()
    assert all(c.lista for c in estado.values()), estado
    assert "NSATESIS" in estado["credenciales_sol"].detalle


def test_detecta_lo_que_falta(configurado, monkeypatch):
    monkeypatch.setattr(settings, "SUNAT_GRE_CLIENT_SECRET", None)
    monkeypatch.setattr(settings, "SUNAT_SOL_USUARIO", "10106693451+NSATESIS")
    monkeypatch.setattr(settings, "APISUNAT_TOKEN", "Bearer_token_de_apisunat_pe")
    estado = _por_clave()
    assert not estado["credenciales_gre"].lista and "SUNAT_GRE_CLIENT_SECRET" in estado["credenciales_gre"].detalle
    assert not estado["credenciales_sol"].lista and "sin espacios ni '+'" in estado["credenciales_sol"].detalle
    assert not estado["facturas"].lista


def test_usuario_sol_de_otro_ruc(configurado, monkeypatch):
    monkeypatch.setattr(settings, "SUNAT_SOL_USUARIO", "20123456789NSATESIS")
    assert "RUC 10106693451" in _por_clave()["credenciales_sol"].detalle


def _transporte(respuesta: httpx.Response, peticiones: list):
    def manejar(request: httpx.Request) -> httpx.Response:
        peticiones.append(request)
        return respuesta

    return httpx.MockTransport(manejar)


@pytest.mark.parametrize(
    "respuesta, ok, texto",
    [
        (httpx.Response(200, json={"access_token": "t", "expires_in": 3600}), True, "Conexión con SUNAT correcta"),
        (httpx.Response(401, json={"error": "invalid_client", "error_description": "cliente no autorizado"}), False, "cliente no autorizado"),
    ],
)
def test_probar_conexion_solo_pide_token(configurado, monkeypatch, respuesta, ok, texto):
    peticiones: list[httpx.Request] = []
    monkeypatch.setattr(
        conexion, "ClienteSunatGre",
        lambda: api.ClienteSunatGre(http_client=httpx.AsyncClient(transport=_transporte(respuesta, peticiones))),
    )
    resultado, mensaje = asyncio.run(conexion.probar_conexion_gre(EMPRESA))
    assert resultado is ok and texto in mensaje
    assert len(peticiones) == 1 and peticiones[0].url.path.endswith("/oauth2/token/")  # nada más que el token


def test_no_prueba_si_falta_configuracion(configurado, monkeypatch):
    monkeypatch.setattr(settings, "SUNAT_SOL_CLAVE", None)
    ok, mensaje = asyncio.run(conexion.probar_conexion_gre(EMPRESA))
    assert not ok and "SUNAT_SOL_CLAVE" in mensaje
