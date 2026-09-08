import uuid
from datetime import date

from pydantic import BaseModel, Field


class ChoferCreateRequest(BaseModel):
    dni: str = Field(min_length=8, max_length=8, pattern=r"^\d{8}$")
    nombres: str
    apellidos: str
    telefono: str | None = None
    direccion: str | None = None
    licencia_numero: str
    licencia_categoria: str = "A-III-C"
    licencia_vencimiento: date
    examen_medico_fecha: date | None = None
    examen_medico_vencimiento: date | None = None
    fecha_ingreso: date | None = None
    tarifa_diaria_default: float = 0
    bono_nocturno_default: float = 0


class ChoferUpdateRequest(BaseModel):
    nombres: str | None = None
    apellidos: str | None = None
    telefono: str | None = None
    direccion: str | None = None
    licencia_numero: str | None = None
    licencia_categoria: str | None = None
    licencia_vencimiento: date | None = None
    examen_medico_fecha: date | None = None
    examen_medico_vencimiento: date | None = None
    tarifa_diaria_default: float | None = None
    bono_nocturno_default: float | None = None
    activo: bool | None = None


class ChoferResponse(BaseModel):
    id: uuid.UUID
    dni: str
    nombres: str
    apellidos: str
    telefono: str | None
    direccion: str | None
    licencia_numero: str
    licencia_categoria: str
    licencia_vencimiento: date
    examen_medico_fecha: date | None
    examen_medico_vencimiento: date | None
    fecha_ingreso: date | None
    activo: bool
    tarifa_diaria_default: float
    bono_nocturno_default: float

    model_config = {"from_attributes": True}
