import uuid
from datetime import date, datetime

from pydantic import BaseModel, Field

from app.models.cotizacion import CONDICIONES_COMERCIALES_DEFAULT
from app.models.enums import EstadoCotizacion, ModalidadViaje
from app.schemas.cliente import ClienteResponse


class CotizacionCreateRequest(BaseModel):
    cliente_id: uuid.UUID
    descripcion_servicio: str
    origen_direccion: str
    origen_distrito: str
    origen_provincia: str
    origen_departamento: str
    destino_direccion: str
    destino_distrito: str
    destino_provincia: str
    destino_departamento: str
    cantidad_camiones: int = Field(default=1, ge=1)
    peso_tm: float = Field(gt=0)
    precio_base: float = Field(gt=0)
    porcentaje_igv: float = 18.00
    condiciones_comerciales: str = CONDICIONES_COMERCIALES_DEFAULT
    validez_dias: int = 7
    fecha_emision: date | None = None


class CambiarEstadoCotizacionRequest(BaseModel):
    estado: EstadoCotizacion


class CotizacionResponse(BaseModel):
    id: uuid.UUID
    numero: str
    cliente_id: uuid.UUID
    usuario_id: uuid.UUID
    descripcion_servicio: str
    origen_direccion: str
    origen_distrito: str
    origen_provincia: str
    origen_departamento: str
    destino_direccion: str
    destino_distrito: str
    destino_provincia: str
    destino_departamento: str
    cantidad_camiones: int
    peso_tm: float
    precio_base: float
    porcentaje_igv: float
    monto_igv: float
    precio_total: float
    condiciones_comerciales: str
    validez_dias: int
    estado: EstadoCotizacion
    fecha_emision: date
    convertida_en: datetime | None
    cliente: ClienteResponse | None = None

    model_config = {"from_attributes": True}


class AsignacionUnidadRequest(BaseModel):
    tracto_id: uuid.UUID
    chofer_id: uuid.UUID
    fecha_salida_programada: datetime
    carreta_id: uuid.UUID | None = None
    tarifa_diaria_chofer: float | None = None
    bono_nocturno_chofer: float | None = None
    precinto_seguridad: str | None = None
    lugar_verificacion_pesos: str | None = None
    origen_ubigeo: str | None = None
    destino_ubigeo: str | None = None


class ConvertirCotizacionRequest(BaseModel):
    modalidad: ModalidadViaje
    asignaciones: list[AsignacionUnidadRequest]


class DocumentoGeneradoResponse(BaseModel):
    id: uuid.UUID
    numero: str


class ResultadoConversionResponse(BaseModel):
    viaje: DocumentoGeneradoResponse
    guia_remision: DocumentoGeneradoResponse
    constancia_pesos_medidas: DocumentoGeneradoResponse
