import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, Field, computed_field

from app.models.enums import DepositanteDetraccion, EstadoSunat, ReceptorComprobante, TipoDocumentoVenta
from app.schemas.cliente import ClienteResponse


class BienGuia(BaseModel):
    descripcion: str = Field(min_length=1, max_length=500)
    cantidad: float = Field(default=1, gt=0)
    unidad: str = Field(default="NIU", max_length=3)  # Catálogo 03: NIU, KGM, TNE, ...
    codigo: str | None = Field(default=None, max_length=30)


class GuiaRemisionResponse(BaseModel):
    id: uuid.UUID
    viaje_id: uuid.UUID
    cliente_id: uuid.UUID
    serie: str
    numero: str
    fecha_emision: date
    motivo_traslado: str
    peso_bruto_total_kg: float
    numero_bultos: int | None
    modalidad_transporte: str
    remitente_guia_ruc_emisor: str | None
    remitente_guia_serie: str | None
    remitente_guia_numero: str | None
    destinatario_tipo_documento: str | None = None
    destinatario_numero_documento: str | None = None
    destinatario_razon_social: str | None = None
    bienes: list[BienGuia] | None = None
    estado_sunat: EstadoSunat
    hash_cpe: str | None
    xml_url: str | None
    cdr_url: str | None
    pdf_url: str | None
    mensaje_sunat: str | None
    sunat_ticket: str | None = None
    sunat_codigo_respuesta: str | None = None
    enviado_sunat_en: datetime | None = None
    xml_clave: str | None = Field(default=None, exclude=True)
    cdr_clave: str | None = Field(default=None, exclude=True)

    @computed_field
    @property
    def xml_firmado_disponible(self) -> bool:
        return self.xml_clave is not None

    @computed_field
    @property
    def cdr_disponible(self) -> bool:
        return self.cdr_clave is not None

    model_config = {"from_attributes": True}


class GuiaVistaPreviaResponse(BaseModel):
    """Lo que se enviará a SUNAT. `huella` debe devolverse al emitir: si los datos
    cambian después de esta revisión, el envío se rechaza."""

    huella: str
    proveedor: str
    puede_emitir: bool
    errores: list[str]
    advertencias: list[str]
    datos: dict[str, Any]
    xml: str | None


class EmitirGuiaRequest(BaseModel):
    huella_vista_previa: str = Field(min_length=64, max_length=64)


class GuiaRemisionListItemResponse(BaseModel):
    id: uuid.UUID
    viaje_id: uuid.UUID
    viaje_numero: str
    serie: str
    numero: str
    cliente_id: uuid.UUID
    cliente_razon_social: str
    destinatario_razon_social: str | None
    tracto_placa: str | None
    carreta_placa: str | None
    chofer_nombre: str | None
    fecha_emision: date
    peso_bruto_total_kg: float
    estado_sunat: EstadoSunat
    mensaje_sunat: str | None
    pdf_url: str | None
    xml_firmado_disponible: bool
    cdr_disponible: bool


class FacturaListItemResponse(BaseModel):
    id: uuid.UUID
    viaje_id: uuid.UUID | None
    viaje_numero: str | None
    documento_afectado_id: uuid.UUID | None
    tipo_documento: TipoDocumentoVenta
    serie: str
    numero: str
    cliente_razon_social: str
    tracto_placa: str | None
    chofer_nombre: str | None
    guia_remision: str | None
    fecha_emision: date
    moneda: str
    subtotal: float
    igv: float
    total: float
    detraccion_monto: float | None
    detraccion_estado: str | None  # None (no aplica) | PENDIENTE | DEPOSITADA
    detraccion_depositada_por: DepositanteDetraccion | None
    detraccion_fecha_deposito: date | None
    detraccion_constancia: str | None
    estado_sunat: EstadoSunat
    mensaje_sunat: str | None
    pdf_url: str | None
    xml_url: str | None
    cdr_url: str | None


class RegistrarDepositoDetraccionRequest(BaseModel):
    """Constancia de depósito de la detracción en el Banco de la Nación."""

    depositada_por: DepositanteDetraccion
    fecha_deposito: date
    numero_constancia: str = Field(min_length=1, max_length=30)
    monto: float | None = Field(default=None, gt=0)  # por defecto, el de la factura


class TotalesFacturacionResponse(BaseModel):
    """Solo comprobantes aceptados por SUNAT; las notas de crédito restan."""

    cantidad: int
    base: float
    igv: float
    total: float
    detracciones: float
    detracciones_depositadas: float
    detracciones_pendientes: float


class ViajeFacturableResponse(BaseModel):
    viaje_id: uuid.UUID
    viaje_numero: str
    cliente_razon_social: str
    origen_distrito: str
    destino_distrito: str
    fecha_salida_programada: datetime
    estado_viaje: str
    guia_remision: str | None
    guia_estado_sunat: EstadoSunat | None


class GuiaRemisionActualizarRequest(BaseModel):
    """Datos de la Guía de Remisión Remitente que el cliente ya generó por su cuenta
    (opcional). Solo se puede editar mientras la guía transportista no haya sido
    aceptada por SUNAT."""

    remitente_guia_ruc_emisor: str | None = None
    remitente_guia_serie: str | None = None
    remitente_guia_numero: str | None = None
    destinatario_tipo_documento: str | None = Field(default=None, pattern=r"^[0-9A-Z]$")
    destinatario_numero_documento: str | None = Field(default=None, max_length=15)
    destinatario_razon_social: str | None = Field(default=None, max_length=250)


class FacturaResponse(BaseModel):
    id: uuid.UUID
    viaje_id: uuid.UUID | None
    cliente_id: uuid.UUID
    guia_remision_id: uuid.UUID | None
    documento_afectado_id: uuid.UUID | None
    tipo_documento: TipoDocumentoVenta
    serie: str
    numero: str
    fecha_emision: date
    moneda: str
    subtotal: float
    igv: float
    total: float
    precio_incluye_igv: bool | None = None
    detraccion_porcentaje: float | None = None
    detraccion_monto: float | None = None
    detraccion_cuenta: str | None = None
    detraccion_depositada_por: DepositanteDetraccion | None = None
    detraccion_fecha_deposito: date | None = None
    detraccion_constancia: str | None = None
    detraccion_monto_depositado: float | None = None
    receptor_tipo_documento: str | None = None
    receptor_numero_documento: str | None = None
    receptor_razon_social: str | None = None
    descripcion: str | None = None
    estado_sunat: EstadoSunat
    hash_cpe: str | None
    xml_url: str | None
    cdr_url: str | None
    pdf_url: str | None
    mensaje_sunat: str | None
    enviado_en: datetime | None = None

    model_config = {"from_attributes": True}


class AnularComprobanteRequest(BaseModel):
    motivo: str | None = None


class EntradaComprobanteRequest(BaseModel):
    """Lo que el usuario elige al emitir la Factura/Boleta del viaje."""

    tipo_documento: Literal[TipoDocumentoVenta.FACTURA, TipoDocumentoVenta.BOLETA]
    precio: Decimal = Field(gt=0, max_digits=12, decimal_places=2)
    precio_incluye_igv: bool
    receptor: ReceptorComprobante = ReceptorComprobante.CLIENTE
    descripcion: str | None = Field(default=None, max_length=500)


class EmitirComprobanteRequest(EntradaComprobanteRequest):
    huella_vista_previa: str = Field(min_length=64, max_length=64)


class ComprobanteBorradorResponse(BaseModel):
    tipo_sugerido: TipoDocumentoVenta
    cliente: ClienteResponse
    precio_sugerido: float | None
    precio_incluye_igv: bool
    origen_precio: str | None  # "COTIZACION" | "FLETE_ESTIMADO"
    descripcion_sugerida: str
    guia_remision: str | None
    guia_estado_sunat: EstadoSunat | None
    porcentaje_igv: float
    limite_boleta_sin_documento: float
    porcentaje_detraccion: float
    monto_minimo_detraccion: float
    cuenta_detracciones: str | None
    puede_emitir: bool
    bloqueos: list[str]


class ComprobanteVistaPreviaResponse(BaseModel):
    """Comprobante tal como se enviará. `huella` debe devolverse al emitir; la serie se
    conoce ahora, el número correlativo se asigna recién al confirmar."""

    huella: str
    puede_emitir: bool
    errores: list[str]
    advertencias: list[str]
    tipo_documento: TipoDocumentoVenta
    serie: str
    receptor_tipo_documento: str
    receptor_numero_documento: str
    receptor_razon_social: str
    descripcion: str
    precio_incluye_igv: bool
    subtotal: float
    igv: float
    total: float
    porcentaje_igv: float
    detraccion_aplica: bool
    detraccion_porcentaje: float
    detraccion_monto: float
    neto_a_cobrar: float  # lo que el cliente paga directamente (total − detracción)
    detraccion_nota: str
    detraccion_cuenta: str | None
    guia_remision: str | None
