import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.models.enums import EstadoViaje, ModalidadViaje
from app.schemas.chofer import ChoferResponse
from app.schemas.cliente import ClienteResponse
from app.schemas.comprobante import BienGuia
from app.schemas.cotizacion import DocumentoGeneradoResponse
from app.schemas.flota import CarretaResponse, TractoResponse


class ActivarViajeRequest(BaseModel):
    cliente_id: uuid.UUID
    # Si no se envía, se deduce del documento del cliente (RUC -> CON_RUC, DNI -> SIN_RUC).
    modalidad: ModalidadViaje | None = None
    tracto_id: uuid.UUID
    chofer_id: uuid.UUID
    carreta_id: uuid.UUID | None = None
    origen_direccion: str
    origen_distrito: str
    origen_provincia: str
    origen_departamento: str
    origen_ubigeo: str | None = None
    destino_direccion: str
    destino_distrito: str
    destino_provincia: str
    destino_departamento: str
    destino_ubigeo: str | None = None
    peso_tm: float = Field(gt=0)
    # Flete estimado (opcional). La Factura/Boleta se emite al terminar el viaje.
    ingreso_flete_neto: float | None = None
    fecha_salida_programada: datetime
    tarifa_diaria_chofer: float | None = None
    bono_nocturno_chofer: float | None = None
    precinto_seguridad: str | None = None
    lugar_verificacion_pesos: str | None = None

    # Datos para la Guía de Remisión Transportista (normalmente vienen de la guía de
    # remitente del cliente importada con POST /sunat/guia-remitente/importar).
    numero_bultos: int | None = Field(default=None, ge=1)
    motivo_traslado: str | None = Field(default=None, max_length=100)
    destinatario_tipo_documento: str | None = Field(default=None, pattern=r"^[0-9A-Z]$")
    destinatario_numero_documento: str | None = Field(default=None, max_length=15)
    destinatario_razon_social: str | None = Field(default=None, max_length=250)
    remitente_guia_ruc_emisor: str | None = Field(default=None, pattern=r"^\d{11}$")
    remitente_guia_serie: str | None = Field(default=None, max_length=4)
    remitente_guia_numero: str | None = Field(default=None, max_length=8)
    bienes: list[BienGuia] | None = None


class ResultadoActivacionResponse(BaseModel):
    viaje: DocumentoGeneradoResponse
    guia_remision: DocumentoGeneradoResponse
    constancia_pesos_medidas: DocumentoGeneradoResponse


class ViajeResponse(BaseModel):
    id: uuid.UUID
    numero: str
    cliente_id: uuid.UUID
    modalidad: ModalidadViaje
    tracto_id: uuid.UUID
    carreta_id: uuid.UUID | None
    chofer_id: uuid.UUID
    origen_direccion: str
    origen_distrito: str
    origen_provincia: str
    origen_departamento: str
    origen_ubigeo: str | None
    destino_direccion: str
    destino_distrito: str
    destino_provincia: str
    destino_departamento: str
    destino_ubigeo: str | None
    peso_tm: float
    fecha_salida_programada: datetime
    fecha_salida_real: datetime | None
    fecha_llegada_real: datetime | None
    dias_viaje: int
    noches_viaje: int
    tarifa_diaria_chofer: float
    bono_nocturno_chofer: float
    ingreso_flete_neto: float
    estado: EstadoViaje
    observaciones: str | None
    cliente: ClienteResponse | None = None
    tracto: TractoResponse | None = None
    carreta: CarretaResponse | None = None
    chofer: ChoferResponse | None = None

    model_config = {"from_attributes": True}


class CambiarEstadoViajeRequest(BaseModel):
    estado: EstadoViaje
    fecha_salida_real: datetime | None = None
    fecha_llegada_real: datetime | None = None
    observaciones: str | None = None
