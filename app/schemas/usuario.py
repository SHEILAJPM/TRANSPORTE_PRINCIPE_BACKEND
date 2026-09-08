import uuid

from pydantic import BaseModel, Field

from app.models.enums import RolUsuario


class UsuarioResponse(BaseModel):
    id: uuid.UUID
    empresa_id: uuid.UUID
    nombres: str
    apellidos: str
    email: str
    rol: RolUsuario
    chofer_id: uuid.UUID | None
    activo: bool

    model_config = {"from_attributes": True}


class UsuarioCreateRequest(BaseModel):
    nombres: str = Field(min_length=2, max_length=150)
    apellidos: str = Field(min_length=2, max_length=150)
    email: str = Field(min_length=5, max_length=150)
    password: str = Field(min_length=8, max_length=100)
    rol: RolUsuario = RolUsuario.OPERADOR
    chofer_id: uuid.UUID | None = None


class UsuarioUpdateRequest(BaseModel):
    nombres: str | None = Field(default=None, min_length=2, max_length=150)
    apellidos: str | None = Field(default=None, min_length=2, max_length=150)
    rol: RolUsuario | None = None
    chofer_id: uuid.UUID | None = None
    activo: bool | None = None
