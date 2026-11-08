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
from datetime import date, datetime, timedelta
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
from app.utils.fechas import ZONA_PERU  # noqa: E402

BACKEND = Path(__file__).resolve().parent.parent

# Salida mañana a las 08:00 de Lima (13:00 UTC): una fecha pasada se reemplaza por hoy.
MANANA = (datetime.now(ZONA_PERU) + timedelta(days=1)).date()
SALIDA_ISO = f"{MANANA.isoformat()}T13:00:00.000Z"
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
        "peso_tm": 28.5, "numero_bultos": None, "fecha_salida_programada": SALIDA_ISO,
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
    assert viaje["fecha_salida_programada"].startswith(f"{MANANA.isoformat()}T13:00:00")  # se conserva el instante

    r = http.post(f"/api/v1/viajes/{viaje_id}/guia-remision/vista-previa")
    assert r.status_code == 200, r.text
    assert r.json()["datos"]["fecha_inicio_traslado"] == MANANA.isoformat()  # día en Perú, no en UTC

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


# --- Emisión completa de guía y factura (SUNAT y apisunat.pe simulados, BD real) ---

from tests.test_guia_transportista import _cdr_zip, certificado, sunat_simulada  # noqa: E402,F401  (fixtures)


def _viaje_finalizado(http, ids, salida=SALIDA_ISO):
    payload = _payload_activar(ids) | {"fecha_salida_programada": salida}
    r = http.post("/api/v1/viajes/activar", json=payload)
    assert r.status_code == 201, r.text
    return r.json()["viaje"]["id"]


def test_emision_de_guia_con_sunat_simulada(entorno, sunat_simulada):
    http, ids = entorno
    viaje_id = _viaje_finalizado(http, ids)

    vista = http.post(f"/api/v1/viajes/{viaje_id}/guia-remision/vista-previa").json()
    # La placa del tracto de prueba no tiene guion y el chofer tiene licencia: sin errores bloqueantes.
    assert vista["puede_emitir"], vista["errores"]

    r = http.post(f"/api/v1/viajes/{viaje_id}/guia-remision/emitir-sunat", json={"huella_vista_previa": vista["huella"]})
    assert r.status_code == 200, r.text
    guia = r.json()
    assert guia["estado_sunat"] == "ACEPTADO", guia
    assert guia["xml_firmado_disponible"] and guia["cdr_disponible"]

    xml = http.get(f"/api/v1/viajes/{viaje_id}/guia-remision/xml")
    assert xml.status_code == 200 and xml.content.startswith(b"<?xml")
    cdr = http.get(f"/api/v1/viajes/{viaje_id}/guia-remision/cdr")
    assert cdr.status_code == 200 and cdr.content[:2] == b"PK"

    # Ya aceptada: un segundo envío se rechaza sin contactar a SUNAT.
    r = http.post(f"/api/v1/viajes/{viaje_id}/guia-remision/emitir-sunat", json={"huella_vista_previa": vista["huella"]})
    assert r.status_code == 409


def test_emision_de_factura_con_apisunat_simulado(entorno, monkeypatch):
    from app.services import apisunat_facturacion_service as apisunat

    enviados = []

    async def emitir_falso(self, ruta, payload):
        enviados.append((ruta, payload))
        return {"success": True, "message": "Aceptado", "payload": {
            "estado": "ACEPTADO", "hash": "abc123", "xml": "https://x/f.xml", "cdr": "https://x/r.zip", "pdf": {"a4": "https://x/f.pdf"}}}

    monkeypatch.setattr(apisunat._ClienteApiSunatFacturacion, "emitir", emitir_falso)

    http, ids = entorno
    viaje_id = _viaje_finalizado(http, ids)
    for estado in ("EN_RUTA", "FINALIZADO"):
        assert http.patch(f"/api/v1/viajes/{viaje_id}/estado", json={"estado": estado}).status_code == 200

    entrada = {"tipo_documento": "FACTURA", "precio": 1500, "precio_incluye_igv": False}
    vista = http.post(f"/api/v1/viajes/{viaje_id}/comprobante/vista-previa", json=entrada).json()
    assert vista["puede_emitir"], vista["errores"]
    assert (vista["subtotal"], vista["igv"], vista["total"], vista["detraccion_monto"]) == (1500.0, 270.0, 1770.0, 71.0)

    r = http.post(f"/api/v1/viajes/{viaje_id}/comprobante/emitir", json=entrada | {"huella_vista_previa": vista["huella"]})
    assert r.status_code == 200, r.text
    factura = r.json()
    assert factura["estado_sunat"] == "ACEPTADO" and factura["serie"].startswith("F")
    assert factura["detraccion_monto"] == 71.0 and factura["guia_remision_id"]

    ruta, payload = enviados[0]
    assert ruta == "/api/v3/documents" and payload["documento"] == "factura"
    assert (payload["gravadas"], payload["igv"], payload["total"]) == ("1500.00", "270.00", "1770.00")

    assert http.get(f"/api/v1/viajes/{viaje_id}/factura").json()["id"] == factura["id"]
    listado = http.get("/api/v1/comprobantes/facturas").json()
    assert any(f["id"] == factura["id"] for f in listado)
    # Con la factura aceptada ya no se puede emitir otra para el mismo viaje.
    assert not http.get(f"/api/v1/viajes/{viaje_id}/comprobante/borrador").json()["puede_emitir"]


def test_listados_de_guias_y_facturas_con_filtros_y_totales(entorno, monkeypatch):
    from app.services import apisunat_facturacion_service as apisunat

    async def emitir_falso(self, ruta, payload):
        return {"success": True, "message": "Aceptado", "payload": {"estado": "ACEPTADO", "hash": "h", "xml": "https://x/f.xml"}}

    monkeypatch.setattr(apisunat._ClienteApiSunatFacturacion, "emitir", emitir_falso)
    http, ids = entorno

    # Un viaje en ruta (sin guía aceptada) no se puede facturar; uno finalizado sí.
    en_ruta = _viaje_finalizado(http, ids)
    http.patch(f"/api/v1/viajes/{en_ruta}/estado", json={"estado": "EN_RUTA"})
    terminado = _viaje_finalizado(http, ids)
    for estado in ("EN_RUTA", "FINALIZADO"):
        http.patch(f"/api/v1/viajes/{terminado}/estado", json={"estado": estado})
    facturables = {v["viaje_id"] for v in http.get("/api/v1/comprobantes/facturables").json()}
    assert terminado in facturables and en_ruta not in facturables

    entrada = {"tipo_documento": "FACTURA", "precio": 1180, "precio_incluye_igv": True}
    vista = http.post(f"/api/v1/viajes/{terminado}/comprobante/vista-previa", json=entrada).json()
    assert http.post(f"/api/v1/viajes/{terminado}/comprobante/emitir", json=entrada | {"huella_vista_previa": vista["huella"]}).status_code == 200
    assert terminado not in {v["viaje_id"] for v in http.get("/api/v1/comprobantes/facturables").json()}

    guias = http.get("/api/v1/comprobantes/guias-remision", params={"placa": "abc", "chofer_id": ids["chofer"]}).json()
    assert guias and all(g["tracto_placa"] == "ABC123" and g["chofer_nombre"] == "PEDRO QUISPE" for g in guias)
    assert http.get("/api/v1/comprobantes/guias-remision", params={"placa": "ZZZ999"}).json() == []
    assert http.get("/api/v1/comprobantes/guias-remision", params={"desde": "2020-01-01", "hasta": "2020-01-31"}).json() == []

    hoy = datetime.now(ZONA_PERU).date().isoformat()
    filtros = {"desde": hoy, "hasta": hoy, "cliente_id": ids["cliente"], "tipo_documento": "FACTURA"}
    facturas = http.get("/api/v1/comprobantes/facturas", params=filtros).json()
    assert facturas and all(f["tipo_documento"] == "FACTURA" for f in facturas)
    assert any(f["subtotal"] == 1000.0 and f["igv"] == 180.0 and f["detraccion_monto"] == 47.0 for f in facturas)

    totales = http.get("/api/v1/comprobantes/facturas/totales", params=filtros).json()
    assert totales["cantidad"] == len([f for f in facturas if f["estado_sunat"] == "ACEPTADO"])
    assert totales["total"] == sum(f["total"] for f in facturas if f["estado_sunat"] == "ACEPTADO")
    assert totales["detracciones"] == sum(f["detraccion_monto"] or 0 for f in facturas if f["estado_sunat"] == "ACEPTADO")


def test_pdf_de_guia_y_factura_con_los_datos_correctos(entorno, sunat_simulada, monkeypatch, tmp_path):
    """El PDF (representación impresa) debe mostrar las mismas partes que el XML:
    remitente = cliente que envía la carga, destinatario = quien la recibe."""
    from app.services import apisunat_facturacion_service as apisunat
    from app.services import documentos_pdf_service
    from app.services.pdf_service import renderizar_html

    monkeypatch.setattr(documentos_pdf_service, "renderizar_pdf", lambda plantilla, ctx: renderizar_html(plantilla, ctx).encode())

    async def emitir_falso(self, ruta, payload):
        return {"success": True, "message": "Aceptado", "payload": {"estado": "ACEPTADO", "hash": "HASHFACTURA123"}}

    monkeypatch.setattr(apisunat._ClienteApiSunatFacturacion, "emitir", emitir_falso)
    http, ids = entorno

    payload = _payload_activar(ids) | {
        "destinatario_numero_documento": "20555555555", "destinatario_razon_social": "FERRETERIA AREQUIPA EIRL",
        "remitente_guia_ruc_emisor": "20999999999", "remitente_guia_serie": "EG01", "remitente_guia_numero": "00000123",
    }
    viaje_id = http.post("/api/v1/viajes/activar", json=payload).json()["viaje"]["id"]
    vista = http.post(f"/api/v1/viajes/{viaje_id}/guia-remision/vista-previa").json()
    assert http.post(f"/api/v1/viajes/{viaje_id}/guia-remision/emitir-sunat", json={"huella_vista_previa": vista["huella"]}).status_code == 200

    guia_html = http.get(f"/api/v1/viajes/{viaje_id}/guia-remision/pdf").text
    (tmp_path / "guia.html").write_text(guia_html, encoding="utf-8")
    remitente = guia_html.split(">Remitente<")[1].split(">Destinatario<")[0]
    destinatario = guia_html.split(">Destinatario<")[1].split("Traslado")[0]
    assert "CLIENTE SAC" in remitente and "20999999999" in remitente
    assert "TRANSPORTE PRINCIPE" not in remitente  # antes ponía a la transportista como remitente
    assert "FERRETERIA AREQUIPA EIRL" in destinatario and "20555555555" in destinatario
    for esperado in ("TRANSPORTISTA", "15M21000123", "87654321", "Q87654321", "Cemento", "EG01-00000123", "UBIGEO 150101", "data:image/svg+xml"):
        assert esperado in guia_html, esperado

    for estado in ("EN_RUTA", "FINALIZADO"):
        http.patch(f"/api/v1/viajes/{viaje_id}/estado", json={"estado": estado})
    entrada = {"tipo_documento": "FACTURA", "precio": 1770, "precio_incluye_igv": True}
    vista = http.post(f"/api/v1/viajes/{viaje_id}/comprobante/vista-previa", json=entrada).json()
    assert http.post(f"/api/v1/viajes/{viaje_id}/comprobante/emitir", json=entrada | {"huella_vista_previa": vista["huella"]}).status_code == 200

    factura_html = http.get(f"/api/v1/viajes/{viaje_id}/factura/pdf").text
    (tmp_path / "factura.html").write_text(factura_html, encoding="utf-8")
    for esperado in ("FACTURA ELECTRÓNICA", "CLIENTE SAC", "1,500.00", "270.00", "1,770.00",
                     "MIL SETECIENTOS SETENTA CON 00/100 SOLES", "Detracción (4%)", "Contado", "HASHFACTURA123", "data:image/svg+xml"):
        assert esperado in factura_html, esperado
