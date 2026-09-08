import uuid
from datetime import date

from pydantic import BaseModel, Field

from app.models.enums import CategoriaGastoGeneral


class GastoGeneralCreateRequest(BaseModel):
    categoria: CategoriaGastoGeneral
    descripcion: str = Field(min_length=3)
    monto: float = Field(gt=0)
    fecha: date
    proveedor: str | None = None
    comprobante_url: str | None = None


class GastoGeneralUpdateRequest(BaseModel):
    categoria: CategoriaGastoGeneral | None = None
    descripcion: str | None = None
    monto: float | None = Field(default=None, gt=0)
    fecha: date | None = None
    proveedor: str | None = None
    comprobante_url: str | None = None


class GastoGeneralResponse(BaseModel):
    id: uuid.UUID
    categoria: CategoriaGastoGeneral
    descripcion: str
    monto: float
    fecha: date
    proveedor: str | None
    comprobante_url: str | None
    registrado_por_usuario_id: uuid.UUID

    model_config = {"from_attributes": True}
