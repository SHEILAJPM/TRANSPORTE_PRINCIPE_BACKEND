import uuid
from datetime import datetime

from pydantic import BaseModel


class NovedadViajeCreateRequest(BaseModel):
    tipo_novedad: str
    descripcion: str
    fecha: datetime
    latitud: float | None = None
    longitud: float | None = None
    foto_url: str | None = None
    uuid_dispositivo: uuid.UUID | None = None


class NovedadViajeResponse(BaseModel):
    id: uuid.UUID
    viaje_id: uuid.UUID
    tipo_novedad: str
    descripcion: str
    fecha: datetime
    latitud: float | None
    longitud: float | None
    foto_url: str | None
    resuelto: bool
    uuid_dispositivo: uuid.UUID | None

    model_config = {"from_attributes": True}
