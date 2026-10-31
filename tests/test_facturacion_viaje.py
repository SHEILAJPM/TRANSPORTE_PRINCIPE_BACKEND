"""Factura/Boleta al terminar el viaje: cálculo de IGV, reglas de factura vs boleta,
vista previa con huella y payload hacia apisunat.pe. Sin base de datos ni red."""

import asyncio
import uuid
from decimal import Decimal

import pytest

from app.models.cliente import Cliente
from app.models.comprobante import Factura, GuiaRemision
from app.models.cotizacion import Cotizacion
from app.models.empresa import Empresa
from app.models.enums import EstadoSunat, EstadoViaje, ReceptorComprobante, TipoDocumentoIdentidad, TipoDocumentoVenta
from app.models.viaje import Viaje
from app.services import apisunat_facturacion_service as apisunat
from app.services import facturacion_viaje_service as fv

D = Decimal


# --- Cálculo de montos ---------------------------------------------------------


@pytest.mark.parametrize(
    "precio, incluye, base, igv, total",
    [
        ("1180", True, "1000.00", "180.00", "1180.00"),
        ("1000", False, "1000.00", "180.00", "1180.00"),
        ("1500", True, "1271.19", "228.81", "1500.00"),  # el total es exactamente lo escrito
        ("99.99", True, "84.74", "15.25", "99.99"),
        ("333.33", False, "333.33", "60.00", "393.33"),
        ("0.05", False, "0.05", "0.01", "0.06"),  # ROUND_HALF_UP: 0.009 -> 0.01
    ],
)
def test_calcular_montos(precio, incluye, base, igv, total):
    m = fv.calcular_montos(D(precio), incluye)
    assert (m.base, m.igv, m.total) == (D(base), D(igv), D(total))
    assert m.base + m.igv == m.total


# --- Detracción -----------------------------------------------------------------


@pytest.mark.parametrize(
    "tipo, total, aplica, monto, neto",
    [
        (TipoDocumentoVenta.FACTURA, "2360.00", True, "94", "2266.00"),  # 94.40 -> 94 (soles enteros)
        (TipoDocumentoVenta.FACTURA, "1012.50", True, "41", "971.50"),  # 40.50 -> 41 (ROUND_HALF_UP)
        (TipoDocumentoVenta.FACTURA, "400.01", True, "16", "384.01"),
        (TipoDocumentoVenta.FACTURA, "400.00", False, "0.00", "400.00"),  # debe superar S/ 400
        (TipoDocumentoVenta.BOLETA, "2360.00", False, "0.00", "2360.00"),
    ],
)
def test_calcular_detraccion(tipo, total, aplica, monto, neto):
    d = fv.calcular_detraccion(tipo, D(total))
    assert (d.aplica, d.monto, d.neto_a_cobrar) == (aplica, D(monto), D(neto))
    assert d.monto + d.neto_a_cobrar == D(total)


# --- Reglas de la propuesta ----------------------------------------------------


def _ctx(tipo_cliente=TipoDocumentoIdentidad.RUC, estado=EstadoViaje.FINALIZADO, comprobantes=(), cotizacion=True,
         guia_aceptada=True, cuenta_detracciones="00-101-123456"):
    empresa = Empresa(id=uuid.uuid4(), ruc="20123456789", razon_social="TP SAC", serie_factura_default="F002",
                      cuenta_detracciones=cuenta_detracciones)
    cliente = Cliente(
        id=uuid.uuid4(),
        tipo_documento=tipo_cliente,
        numero_documento="20999999999" if tipo_cliente == TipoDocumentoIdentidad.RUC else "12345678",
        razon_social="CLIENTE SAC" if tipo_cliente == TipoDocumentoIdentidad.RUC else "JUAN PEREZ",
        direccion="Av. Siempre Viva 123",
    )
    cot = (
        Cotizacion(id=uuid.uuid4(), descripcion_servicio="Flete Lima - Arequipa", cantidad_camiones=2,
                   precio_total=D("4720.00"))
        if cotizacion else None
    )
    viaje = Viaje(id=uuid.uuid4(), numero="VJ-000010", empresa_id=empresa.id, cliente_id=cliente.id,
                  cotizacion_id=cot.id if cot else None, estado=estado, origen_distrito="Lurin",
                  destino_distrito="Arequipa", ingreso_flete_neto=D("0"))
    guia = GuiaRemision(id=uuid.uuid4(), serie="V001", numero="00000007",
                        estado_sunat=EstadoSunat.ACEPTADO if guia_aceptada else EstadoSunat.PENDIENTE)
    return fv._Contexto(viaje=viaje, cliente=cliente, empresa=empresa, cotizacion=cot, guia=guia, comprobantes=list(comprobantes))


def _entrada(tipo=TipoDocumentoVenta.FACTURA, precio="2360", incluye=True, receptor=ReceptorComprobante.CLIENTE, descripcion=None):
    return fv.EntradaComprobante(tipo, D(precio), incluye, receptor, descripcion)


def test_factura_a_cliente_con_ruc_usa_cotizacion_y_guia():
    p = fv._proponer(_ctx(), _entrada())
    # 4720 / 2 camiones = 2360, igual a lo escrito: solo queda el aviso de detracción.
    assert p.errores == [] and len(p.advertencias) == 1 and "detracción" in p.advertencias[0]
    assert (p.serie, p.receptor_tipo_documento, p.receptor_numero_documento) == ("F002", "6", "20999999999")
    assert (p.montos.base, p.montos.igv, p.montos.total) == (D("2000.00"), D("360.00"), D("2360.00"))
    assert p.descripcion == "Flete Lima - Arequipa — GRE V001-00000007"
    assert p.guia_remision == "V001-00000007"


def test_detraccion_toma_la_cuenta_de_la_empresa_o_avisa_si_falta():
    con_cuenta = fv._proponer(_ctx(), _entrada())
    assert con_cuenta.detraccion.cuenta == "00-101-123456"
    assert "00-101-123456" in con_cuenta.detraccion.motivo
    assert not any("no registraste" in a for a in con_cuenta.advertencias)

    sin_cuenta = fv._proponer(_ctx(cuenta_detracciones=None), _entrada())
    assert sin_cuenta.errores == []  # avisa, no bloquea
    assert any("no registraste la cuenta de detracciones" in a for a in sin_cuenta.advertencias)

    # Sin detracción (boleta) no hace falta la cuenta.
    boleta = fv._proponer(_ctx(TipoDocumentoIdentidad.DNI, cuenta_detracciones=None), _entrada(TipoDocumentoVenta.BOLETA))
    assert not any("cuenta de detracciones" in a for a in boleta.advertencias)


def test_cuenta_de_detracciones_en_configuracion_de_empresa():
    from pydantic import ValidationError

    from app.schemas.empresa import EmpresaUpdateRequest

    assert EmpresaUpdateRequest(cuenta_detracciones=" 00-101-123456 ").cuenta_detracciones == "00-101-123456"
    assert EmpresaUpdateRequest(cuenta_detracciones="").cuenta_detracciones is None
    with pytest.raises(ValidationError):
        EmpresaUpdateRequest(cuenta_detracciones="BN-ABC")


def test_no_permite_factura_a_cliente_con_dni():
    p = fv._proponer(_ctx(TipoDocumentoIdentidad.DNI), _entrada())
    assert any("DNI" in e for e in p.errores)


def test_boleta_a_dni_y_advertencia_si_monto_difiere_de_cotizacion():
    p = fv._proponer(_ctx(TipoDocumentoIdentidad.DNI), _entrada(TipoDocumentoVenta.BOLETA, "2000", True))
    assert p.errores == []
    assert (p.serie, p.receptor_tipo_documento) == ("B001", "1")
    assert any("difiere de la cotización" in a for a in p.advertencias)


def test_boleta_sin_documento_solo_menor_a_700():
    ctx = _ctx(TipoDocumentoIdentidad.DNI, cotizacion=False)
    ok = fv._proponer(ctx, _entrada(TipoDocumentoVenta.BOLETA, "699.99", True, ReceptorComprobante.SIN_DOCUMENTO))
    assert ok.errores == []
    assert (ok.receptor_tipo_documento, ok.receptor_numero_documento, ok.receptor_razon_social) == (
        fv.RECEPTOR_VARIOS_TIPO, fv.RECEPTOR_VARIOS_NUMERO, fv.RECEPTOR_VARIOS_NOMBRE)

    # 600 + 18% = 708: el total supera el límite aunque el precio escrito no.
    no = fv._proponer(ctx, _entrada(TipoDocumentoVenta.BOLETA, "600", False, ReceptorComprobante.SIN_DOCUMENTO))
    assert any("identificar al comprador" in e for e in no.errores)

    factura_sin_doc = fv._proponer(_ctx(), _entrada(receptor=ReceptorComprobante.SIN_DOCUMENTO))
    assert any("RUC del cliente" in e for e in factura_sin_doc.errores)


def test_bloqueos_por_estado_y_comprobantes_previos():
    assert any("FINALIZADO" in b for b in fv._bloqueos(_ctx(estado=EstadoViaje.EN_RUTA)))

    aceptada = Factura(tipo_documento=TipoDocumentoVenta.FACTURA, serie="F001", numero="00000001", estado_sunat=EstadoSunat.ACEPTADO)
    assert any("ya fue aceptada" in b for b in fv._bloqueos(_ctx(comprobantes=[aceptada])))

    enviada = Factura(tipo_documento=TipoDocumentoVenta.FACTURA, serie="F001", numero="00000002",
                      estado_sunat=EstadoSunat.PENDIENTE, xml_url="https://apisunat/x.xml")
    assert any("reintenta su envío" in b for b in fv._bloqueos(_ctx(comprobantes=[enviada])))

    rechazada = Factura(tipo_documento=TipoDocumentoVenta.FACTURA, serie="F001", numero="00000003", estado_sunat=EstadoSunat.RECHAZADO)
    borrador_viejo = Factura(tipo_documento=TipoDocumentoVenta.FACTURA, serie="F001", numero="00000004", estado_sunat=EstadoSunat.PENDIENTE)
    assert fv._bloqueos(_ctx(comprobantes=[rechazada, borrador_viejo])) == []


def test_huella_cambia_con_el_precio_o_el_tipo():
    ctx = _ctx()
    h = fv._proponer(ctx, _entrada()).huella()
    assert h == fv._proponer(ctx, _entrada()).huella()
    assert h != fv._proponer(ctx, _entrada(precio="2361")).huella()
    assert h != fv._proponer(ctx, _entrada(incluye=False)).huella()


# --- Registro del comprobante confirmado ----------------------------------------


class _SesionFalsa:
    def __init__(self):
        self.agregados, self.borrados = [], []

    def add(self, objeto):
        self.agregados.append(objeto)

    async def delete(self, objeto):
        self.borrados.append(objeto)

    async def flush(self):
        pass


@pytest.fixture
def registro(monkeypatch):
    borrador_viejo = Factura(tipo_documento=TipoDocumentoVenta.FACTURA, serie="F001", numero="00000004", estado_sunat=EstadoSunat.PENDIENTE)
    ctx = _ctx(comprobantes=[borrador_viejo])

    async def contexto_falso(db, viaje_id, empresa_id, bloquear=False):
        assert bloquear, "el registro debe bloquear el viaje (doble clic)"
        return ctx

    async def numero_falso(db, tipo, serie):
        return "00000123"

    monkeypatch.setattr(fv, "_contexto", contexto_falso)
    monkeypatch.setattr(fv, "generar_numero_serie_sunat", numero_falso)
    return ctx, borrador_viejo


def test_registrar_numera_relaciona_guia_y_actualiza_flete(registro):
    ctx, borrador_viejo = registro
    db = _SesionFalsa()
    huella = fv._proponer(ctx, _entrada()).huella()

    factura = asyncio.run(fv.registrar(db, ctx.viaje.id, ctx.viaje.empresa_id, _entrada(), huella))

    assert (factura.serie, factura.numero, factura.tipo_documento) == ("F002", "00000123", TipoDocumentoVenta.FACTURA)
    assert factura.guia_remision_id == ctx.guia.id
    assert (factura.subtotal, factura.igv, factura.total, factura.precio_incluye_igv) == (D("2000.00"), D("360.00"), D("2360.00"), True)
    assert factura.enviado_en is not None and factura.estado_sunat == EstadoSunat.PENDIENTE
    assert (factura.detraccion_porcentaje, factura.detraccion_monto, factura.detraccion_cuenta) == (D("4.00"), D("94"), "00-101-123456")
    assert ctx.viaje.ingreso_flete_neto == D("2000.00")
    assert db.borrados == [borrador_viejo]  # el PENDIENTE del flujo anterior, nunca enviado


def test_registrar_rechaza_si_cambio_algo_tras_la_vista_previa(registro):
    ctx, _ = registro
    huella = fv._proponer(ctx, _entrada()).huella()
    with pytest.raises(fv.HuellaComprobanteNoCoincideError):
        asyncio.run(fv.registrar(_SesionFalsa(), ctx.viaje.id, ctx.viaje.empresa_id, _entrada(precio="2400"), huella))


# --- Payload hacia apisunat.pe ---------------------------------------------------


class _SesionGet:
    def __init__(self, *objetos):
        self._objetos = {(type(o), o.id): o for o in objetos}

    async def get(self, modelo, ident, **_):
        return self._objetos.get((modelo, ident))


def test_payload_boleta_sin_documento_usa_receptor_confirmado():
    ctx = _ctx(TipoDocumentoIdentidad.DNI, cotizacion=False)
    factura = Factura(
        id=uuid.uuid4(), cliente_id=ctx.cliente.id, viaje_id=ctx.viaje.id, tipo_documento=TipoDocumentoVenta.BOLETA,
        serie="B001", numero="00000009", moneda="PEN", subtotal=D("500.00"), igv=D("90.00"), total=D("590.00"),
        receptor_tipo_documento=fv.RECEPTOR_VARIOS_TIPO, receptor_numero_documento=fv.RECEPTOR_VARIOS_NUMERO,
        receptor_razon_social=fv.RECEPTOR_VARIOS_NOMBRE, descripcion="Flete corto — GRE V001-00000007",
    )
    payload = asyncio.run(apisunat.construir_payload_factura(_SesionGet(ctx.cliente, ctx.viaje), factura))
    assert payload["documento"] == "boleta"
    assert (payload["cliente_tipo_de_documento"], payload["cliente_numero_de_documento"], payload["cliente_denominacion"]) == (
        "0", "00000000", "CLIENTES VARIOS")
    assert payload["cliente_direccion"] == ""
    assert payload["items"][0]["descripcion"] == "Flete corto — GRE V001-00000007"
    assert (payload["gravadas"], payload["igv"], payload["total"]) == ("500.00", "90.00", "590.00")
