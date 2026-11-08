"""Consulta de DNI/RUC: exige sesión de ADMIN u OPERADOR (cada consulta se cobra)."""

import uuid

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_current_user
from app.api.v1.endpoints import sunat as endpoints_sunat
from app.main import app
from app.models.enums import RolUsuario
from app.models.usuario import Usuario
from app.schemas.sunat import DniConsultaResponse
from app.services.sunat_service import ApiSunatDocumentoInvalidoError, ApiSunatNotFoundError


class _ServicioFalso:
    async def consultar_dni(self, dni):
        if len(dni) != 8:
            raise ApiSunatDocumentoInvalidoError("El DNI debe tener 8 dígitos numéricos")
        if dni == "00000000":
            raise ApiSunatNotFoundError(dni)
        return DniConsultaResponse(numero_documento=dni, nombres="PEDRO", apellido_paterno="QUISPE", apellido_materno="ROJAS")

    async def cerrar(self):
        pass


@pytest.fixture
def cliente_http():
    def usar(rol: RolUsuario | None):
        app.dependency_overrides[endpoints_sunat.get_apisunat_service] = lambda: _ServicioFalso()
        if rol is not None:
            usuario = Usuario(id=uuid.uuid4(), empresa_id=uuid.uuid4(), email="u@x.pe", nombres="U", apellidos="X", rol=rol, activo=True)
            app.dependency_overrides[get_current_user] = lambda: usuario
        return TestClient(app)

    yield usar
    app.dependency_overrides.clear()


def test_sin_sesion_no_se_puede_consultar(cliente_http):
    assert cliente_http(None).get("/api/v1/sunat/dni/87654321").status_code == 401
    assert cliente_http(None).get("/api/v1/sunat/ruc/20999999999").status_code == 401


def test_chofer_no_puede_consultar(cliente_http):
    assert cliente_http(RolUsuario.CHOFER).get("/api/v1/sunat/dni/87654321").status_code == 403


def test_operador_consulta_dni(cliente_http):
    http = cliente_http(RolUsuario.OPERADOR)
    r = http.get("/api/v1/sunat/dni/87654321")
    assert r.status_code == 200 and r.json()["apellido_paterno"] == "QUISPE"
    assert http.get("/api/v1/sunat/dni/123").status_code == 400
    assert http.get("/api/v1/sunat/dni/00000000").status_code == 404
