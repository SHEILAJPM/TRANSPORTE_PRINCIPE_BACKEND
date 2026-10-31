import uuid
from datetime import datetime

from pydantic import BaseModel, Field, field_validator


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
    cuenta_detracciones: str | None = None

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
    # Cuenta de detracciones del Banco de la Nación, p.ej. 00-101-123456 (vacío = quitarla).
    cuenta_detracciones: str | None = Field(default=None, max_length=20)
    apisunat_token: str | None = None

    @field_validator("cuenta_detracciones")
    @classmethod
    def validar_cuenta_detracciones(cls, valor: str | None) -> str | None:
        if valor is None or not valor.strip():
            return None
        valor = valor.strip()
        digitos = valor.replace("-", "")
        if not digitos.isdigit() or not 8 <= len(digitos) <= 15:
            raise ValueError("La cuenta de detracciones solo lleva números (y guiones), p.ej. 00-101-123456")
        return valor
