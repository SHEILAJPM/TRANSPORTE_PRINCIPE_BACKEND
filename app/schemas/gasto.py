import uuid
from datetime import datetime

from pydantic import BaseModel

from app.models.enums import TipoGastoViaje


class GastoViajeCreateRequest(BaseModel):
    tipo_gasto: TipoGastoViaje
    monto: float
    fecha: datetime
    galones: float | None = None
    grifo_nombre: str | None = None
    numero_ticket: str | None = None
    descripcion: str | None = None
    comprobante_url: str | None = None
    # Identificador generado por la app móvil del chofer al registrar el gasto offline;
    # si ya existe, el POST es idempotente y no crea un duplicado al reintentar la sincronización.
    uuid_dispositivo: uuid.UUID | None = None


class GastoViajeResponse(BaseModel):
    id: uuid.UUID
    viaje_id: uuid.UUID
    tipo_gasto: TipoGastoViaje
    monto: float
    fecha: datetime
    galones: float | None
    grifo_nombre: str | None
    numero_ticket: str | None
    descripcion: str | None
    comprobante_url: str | None
    uuid_dispositivo: uuid.UUID | None
    sincronizado: bool

    model_config = {"from_attributes": True}
