import uuid
from datetime import datetime

from pydantic import BaseModel


class EmpresaResponse(BaseModel):
    id: uuid.UUID
    ruc: str
    razon_social: str
    nombre_comercial: str | None
    direccion_fiscal: str | None
    distrito: str | None
    provincia: str | None
    departamento: str | None
    telefono: str | None
    email: str | None
    logo_url: str | None
    logo_actualizado_en: datetime | None
    serie_factura_default: str | None
    serie_guia_remision_default: str | None
    numero_registro_mtc: str | None

    model_config = {"from_attributes": True}


class EmpresaUpdateRequest(BaseModel):
    razon_social: str | None = None
    nombre_comercial: str | None = None
    direccion_fiscal: str | None = None
    distrito: str | None = None
    provincia: str | None = None
    departamento: str | None = None
    telefono: str | None = None
    email: str | None = None
    serie_factura_default: str | None = None
    serie_guia_remision_default: str | None = None
    numero_registro_mtc: str | None = None
    apisunat_token: str | None = None
