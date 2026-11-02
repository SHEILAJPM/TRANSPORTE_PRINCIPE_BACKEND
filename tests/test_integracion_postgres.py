"""Flujo real contra PostgreSQL (temporal, con `pgserver`): todas las migraciones +
activar un viaje SIN cotización, iniciarlo, registrar un gasto, finalizarlo y preparar
la factura con precio a mano. También la conversión desde cotización.

Reproduce el bloqueo de producción: el frontend envía fechas ISO con "Z" y las columnas
`timestamp` sin zona las rechazaban (error 500 en Activar viaje). Se omite si `pgserver`
no está instalado (`pip install pgserver`).
"""

import asyncio
import tempfile
import uuid
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

pgserver = pytest.importorskip("pgserver")

from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.core.database import get_db  # noqa: E402
from app.main import app  # noqa: E402
from app.models.chofer import Chofer  # noqa: E402
from app.models.cliente import Cliente  # noqa: E402
from app.models.cotizacion import Cotizacion  # noqa: E402
from app.models.enums import EstadoCotizacion, TipoDocumentoIdentidad  # noqa: E402
from app.models.flota import Tracto  # noqa: E402
from app.services.auth_service import crear_o_restablecer_admin  # noqa: E402

BACKEND = Path(__file__).resolve().parent.parent
EMAIL, PASSWORD = "admin@prueba.pe", "clave-segura-123"


@pytest.fixture(scope="module")
def entorno():
    directorio = tempfile.mkdtemp()
    servidor = pgserver.get_server(directorio, cleanup_mode="delete")
    uri = servidor.get_uri()  # postgresql://...
    url_sync = uri.replace("postgresql://", "postgresql+psycopg2://", 1)
    url_async = uri.replace("postgresql://", "postgresql+asyncpg://", 1)

    original_sync = settings.DATABASE_URL_SYNC
    settings.DATABASE_URL_SYNC = url_sync
    configuracion = Config(str(BACKEND / "alembic.ini"))
    configuracion.set_main_option("script_location", str(BACKEND / "alembic"))
    command.upgrade(configuracion, "head")
    settings.DATABASE_URL_SYNC = original_sync

    motor = create_async_engine(url_async, poolclass=__import__("sqlalchemy.pool", fromlist=["NullPool"]).NullPool)
    Sesion = async_sessionmaker(motor, expire_on_commit=False, autoflush=False)

    async def sembrar():
        async with Sesion() as db:
            resultado = await crear_o_restablecer_admin(
                db, email=EMAIL, password=PASSWORD, nombres="Sheila", apellidos="Principe",
                ruc="10106693451", razon_social="TRANSPORTE PRINCIPE",
            )
            cliente = Cliente(tipo_documento=TipoDocumentoIdentidad.RUC, numero_documento="20999999999",
                              razon_social="CLIENTE SAC")
            tracto = Tracto(placa="ABC123", marca="Volvo", largo_m=Decimal("6.5"), ancho_m=Decimal("2.6"),
                            alto_m=Decimal("4.1"), configuracion_vehicular="T3S3", peso_bruto_max_kg=Decimal("48000"),
                            tarjeta_unica_circulacion="15M21000123")
            chofer = Chofer(dni="87654321", nombres="PEDRO", apellidos="QUISPE", licencia_numero="Q87654321",
                            licencia_vencimiento=date(2030, 1, 1))
            db.add_all([cliente, tracto, chofer])
            await db.flush()
            cotizacion = Cotizacion(
                numero="COT-000001", empresa_id=resultado.empresa.id, cliente_id=cliente.id,
                usuario_id=resultado.admin.id, descripcion_servicio="Flete Lima - Arequipa",
                origen_direccion="Av. Lima 1", origen_distrito="Lima", origen_provincia="Lima", origen_departamento="Lima",
                destino_direccion="Calle 2", destino_distrito="Arequipa", destino_provincia="Arequipa",
                destino_departamento="Arequipa", cantidad_camiones=1, peso_tm=Decimal("28.5"),
                precio_base=Decimal("2000"), monto_igv=Decimal("360"), precio_total=Decimal("2360"),
                estado=EstadoCotizacion.APROBADA, fecha_emision=date(2026, 11, 1),
            )
            db.add(cotizacion)
            await db.commit()
            return {"cliente": str(cliente.id), "tracto": str(tracto.id), "chofer": str(chofer.id),
                    "cotizacion": str(cotizacion.id)}

    ids = asyncio.run(sembrar())

    async def db_de_prueba():
        async with Sesion() as sesion:
            yield sesion

    app.dependency_overrides[get_db] = db_de_prueba
    http = TestClient(app)
    token = http.post("/api/v1/auth/login", data={"username": EMAIL, "password": PASSWORD}).json()["access_token"]
    http.headers["Authorization"] = f"Bearer {token}"

    yield http, ids

    app.dependency_overrides.clear()
    asyncio.run(motor.dispose())
    servidor.cleanup()


def _payload_activar(ids):
    """Exactamente lo que envía Viajes → Activar viaje (modo "No", sin cotización)."""
    return {
        "cliente_id": ids["cliente"], "tracto_id": ids["tracto"], "chofer_id": ids["chofer"], "carreta_id": None,
        "origen_direccion": "Av. Lima 1", "origen_distrito": "Lima", "origen_provincia": "Lima",
        "origen_departamento": "Lima", "origen_ubigeo": "150101",
        "destino_direccion": "Calle 2", "destino_distrito": "Arequipa", "destino_provincia": "Arequipa",
        "destino_departamento": "Arequipa", "destino_ubigeo": "040101",
        "peso_tm": 28.5, "numero_bultos": None, "fecha_salida_programada": "2026-11-03T13:00:00.000Z",
        "precinto_seguridad": None, "lugar_verificacion_pesos": None, "motivo_traslado": None,
        "remitente_guia_ruc_emisor": None, "remitente_guia_serie": None, "remitente_guia_numero": None,
        "bienes": [{"descripcion": "Cemento", "cantidad": 1, "unidad": "NIU", "codigo": None}],
        "destinatario_tipo_documento": "6", "destinatario_numero_documento": "20999999999",
        "destinatario_razon_social": "CLIENTE SAC",
    }


def test_viaje_sin_cotizacion_de_principio_a_fin(entorno):
    http, ids = entorno

    r = http.post("/api/v1/viajes/activar", json=_payload_activar(ids))
    assert r.status_code == 201, r.text
    viaje_id = r.json()["viaje"]["id"]

    viaje = http.get(f"/api/v1/viajes/{viaje_id}").json()
    assert viaje["fecha_salida_programada"].startswith("2026-11-03T13:00:00")  # se conserva el instante exacto

    r = http.post(f"/api/v1/viajes/{viaje_id}/guia-remision/vista-previa")
    assert r.status_code == 200, r.text
    assert r.json()["datos"]["fecha_inicio_traslado"] == "2026-11-03"  # día en Perú, no en UTC

    r = http.patch(f"/api/v1/viajes/{viaje_id}/estado", json={"estado": "EN_RUTA", "fecha_salida_real": "2026-11-03T13:10:00.000Z"})
    assert r.status_code == 200, r.text
    r = http.post(f"/api/v1/viajes/{viaje_id}/gastos",
                  json={"tipo_gasto": "PEAJE", "monto": 25.5, "fecha": "2026-11-03T15:00:00.000Z"})
    assert r.status_code == 201, r.text
    r = http.patch(f"/api/v1/viajes/{viaje_id}/estado", json={"estado": "FINALIZADO", "fecha_llegada_real": "2026-11-04T20:00:00.000Z"})
    assert r.status_code == 200, r.text

    borrador = http.get(f"/api/v1/viajes/{viaje_id}/comprobante/borrador").json()
    assert borrador["puede_emitir"], borrador["bloqueos"]
    assert borrador["precio_sugerido"] is None  # sin cotización: el precio se escribe a mano

    r = http.post(f"/api/v1/viajes/{viaje_id}/comprobante/vista-previa",
                  json={"tipo_documento": "FACTURA", "precio": 2360, "precio_incluye_igv": True})
    assert r.status_code == 200, r.text
    vista = r.json()
    assert vista["puede_emitir"], vista["errores"]
    assert (vista["subtotal"], vista["igv"], vista["total"], vista["detraccion_monto"]) == (2000.0, 360.0, 2360.0, 94.0)


def test_conversion_desde_cotizacion_sigue_funcionando(entorno):
    http, ids = entorno
    r = http.post(
        f"/api/v1/cotizaciones/{ids['cotizacion']}/convertir-a-viaje",
        json={"modalidad": "CON_RUC", "asignaciones": [
            {"tracto_id": ids["tracto"], "chofer_id": ids["chofer"], "fecha_salida_programada": "2026-11-05T13:00:00.000Z",
             "origen_ubigeo": "150101", "destino_ubigeo": "040101"}
        ]},
    )
    assert r.status_code == 200, r.text
