import uuid
from datetime import datetime

from pydantic import BaseModel


class AutocompletarVehiculoResponse(BaseModel):
    tipo: str
    id: uuid.UUID
    placa: str
    largo_m: float
    ancho_m: float
    alto_m: float
    configuracion_vehicular: str
    tara_kg: float
    peso_bruto_max_kg: float


class ConstanciaPesosMedidasCreateRequest(BaseModel):
    viaje_id: uuid.UUID
    guia_remision_id: uuid.UUID
    tracto_id: uuid.UUID
    carreta_id: uuid.UUID | None = None
    chofer_id: uuid.UUID
    generador_carga_cliente_id: uuid.UUID
    tipo_control: str = "BALANZA"
    lugar_verificacion: str | None = None
    fecha_verificacion: datetime
    precinto_seguridad: str | None = None
    peso_bruto_kg: float | None = None
    tara_kg: float | None = None


class ConstanciaPesosMedidasUpdateRequest(BaseModel):
    tipo_control: str | None = None
    lugar_verificacion: str | None = None
    fecha_verificacion: datetime | None = None
    peso_bruto_kg: float | None = None
    tara_kg: float | None = None
    precinto_seguridad: str | None = None
    numero_licencia_chofer: str | None = None
    largo_m: float | None = None
    ancho_m: float | None = None
    alto_m: float | None = None
    configuracion_vehicular: str | None = None
    peso_bruto_max_kg: float | None = None
    observaciones: str | None = None


class ConstanciaListItemResponse(BaseModel):
    id: uuid.UUID
    numero: str
    viaje_id: uuid.UUID
    fecha_verificacion: datetime
    tracto_placa: str
    carreta_placa: str | None
    chofer_nombre: str
    generador_carga: str
    guia_remision_numero: str
    peso_bruto_kg: float
    peso_neto_kg: float
    peso_bruto_max_kg: float
    excede_limite: bool


class ConstanciaPesosMedidasResponse(BaseModel):
    id: uuid.UUID
    numero: str
    guia_remision_id: uuid.UUID
    viaje_id: uuid.UUID
    tracto_id: uuid.UUID
    carreta_id: uuid.UUID | None
    chofer_id: uuid.UUID
    generador_carga_cliente_id: uuid.UUID
    tipo_control: str
    lugar_verificacion: str | None
    fecha_verificacion: datetime
    peso_bruto_kg: float
    tara_kg: float
    peso_neto_kg: float
    precinto_seguridad: str | None
    numero_licencia_chofer: str
    largo_m: float
    ancho_m: float
    alto_m: float
    configuracion_vehicular: str
    peso_bruto_max_kg: float
    observaciones: str | None

    model_config = {"from_attributes": True}
