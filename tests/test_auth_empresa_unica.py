"""Sistema de una sola empresa: sin registro público; el administrador se crea o
recupera con `python -m app.crear_admin`."""

import asyncio
import uuid
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.core.security import verificar_password
from app.main import app
from app.models.empresa import Empresa
from app.models.enums import RolUsuario
from app.models.usuario import Usuario
from app.services.auth_service import DatosEmpresaFaltantesError, crear_o_restablecer_admin


def test_no_existe_registro_publico():
    http = TestClient(app)
    respuesta = http.post("/api/v1/auth/registro-empresa", json={"ruc": "10106693451"})
    assert respuesta.status_code == 404
    rutas = app.openapi()["paths"]
    assert not any("registro" in ruta for ruta in rutas)
    assert "/api/v1/auth/login" in rutas


class _SesionFalsa:
    """Devuelve, en orden, la empresa existente y el usuario con ese correo."""

    def __init__(self, empresa=None, usuario=None):
        self._resultados = [empresa, usuario]
        self.agregados = []

    async def execute(self, _stmt):
        valor = self._resultados.pop(0)
        return SimpleNamespace(scalar_one_or_none=lambda: valor)

    def add(self, objeto):
        if getattr(objeto, "id", None) is None:
            objeto.id = uuid.uuid4()
        self.agregados.append(objeto)

    async def flush(self):
        pass


def test_primer_uso_crea_empresa_y_administrador():
    db = _SesionFalsa()
    r = asyncio.run(
        crear_o_restablecer_admin(
            db, email="admin@tp.pe", password="clave-segura-1", nombres="Sheila", apellidos="Principe",
            ruc="10106693451", razon_social="TRANSPORTE PRINCIPE",
        )
    )
    assert r.empresa_creada and r.admin_creado
    assert r.admin.rol == RolUsuario.ADMIN and r.admin.activo and r.admin.empresa_id == r.empresa.id
    assert verificar_password("clave-segura-1", r.admin.hashed_password)


def test_sin_empresa_exige_ruc_y_razon_social():
    with pytest.raises(DatosEmpresaFaltantesError):
        asyncio.run(crear_o_restablecer_admin(_SesionFalsa(), email="admin@tp.pe", password="clave-segura-1"))


def test_correo_existente_recupera_el_acceso():
    empresa = Empresa(id=uuid.uuid4(), ruc="10106693451", razon_social="TRANSPORTE PRINCIPE")
    usuario = Usuario(
        id=uuid.uuid4(), empresa_id=empresa.id, email="admin@tp.pe", nombres="Sheila", apellidos="Principe",
        hashed_password="hash-viejo", rol=RolUsuario.OPERADOR, activo=False,
    )
    db = _SesionFalsa(empresa=empresa, usuario=usuario)
    r = asyncio.run(crear_o_restablecer_admin(db, email="admin@tp.pe", password="nueva-clave-99"))

    assert not r.empresa_creada and not r.admin_creado and db.agregados == []
    assert r.admin is usuario and usuario.rol == RolUsuario.ADMIN and usuario.activo
    assert verificar_password("nueva-clave-99", usuario.hashed_password)
