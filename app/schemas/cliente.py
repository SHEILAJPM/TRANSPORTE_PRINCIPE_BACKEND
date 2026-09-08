import uuid

from pydantic import BaseModel

from app.models.enums import TipoDocumentoIdentidad


class ClienteResponse(BaseModel):
    id: uuid.UUID
    tipo_documento: TipoDocumentoIdentidad
    numero_documento: str
    razon_social: str
    nombre_comercial: str | None
    direccion: str | None
    distrito: str | None
    provincia: str | None
    departamento: str | None
    fuente_datos: str

    model_config = {"from_attributes": True}
