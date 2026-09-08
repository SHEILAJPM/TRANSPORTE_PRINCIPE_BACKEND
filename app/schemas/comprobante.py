import uuid
from datetime import date

from pydantic import BaseModel

from app.models.enums import EstadoSunat, TipoDocumentoVenta


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
    estado_sunat: EstadoSunat
    hash_cpe: str | None
    xml_url: str | None
    cdr_url: str | None
    pdf_url: str | None
    mensaje_sunat: str | None

    model_config = {"from_attributes": True}


class GuiaRemisionListItemResponse(BaseModel):
    id: uuid.UUID
    viaje_id: uuid.UUID
    viaje_numero: str
    serie: str
    numero: str
    cliente_razon_social: str
    fecha_emision: date
    peso_bruto_total_kg: float
    estado_sunat: EstadoSunat
    mensaje_sunat: str | None
    pdf_url: str | None


class FacturaListItemResponse(BaseModel):
    id: uuid.UUID
    viaje_id: uuid.UUID | None
    viaje_numero: str | None
    documento_afectado_id: uuid.UUID | None
    tipo_documento: TipoDocumentoVenta
    serie: str
    numero: str
    cliente_razon_social: str
    fecha_emision: date
    moneda: str
    total: float
    estado_sunat: EstadoSunat
    mensaje_sunat: str | None
    pdf_url: str | None


class GuiaRemisionActualizarRequest(BaseModel):
    """Datos de la Guía de Remisión Remitente que el cliente ya generó por su cuenta
    (opcional). Solo se puede editar mientras la guía transportista no haya sido
    aceptada por SUNAT."""

    remitente_guia_ruc_emisor: str | None = None
    remitente_guia_serie: str | None = None
    remitente_guia_numero: str | None = None


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
    estado_sunat: EstadoSunat
    hash_cpe: str | None
    xml_url: str | None
    cdr_url: str | None
    pdf_url: str | None
    mensaje_sunat: str | None

    model_config = {"from_attributes": True}


class AnularComprobanteRequest(BaseModel):
    motivo: str | None = None
