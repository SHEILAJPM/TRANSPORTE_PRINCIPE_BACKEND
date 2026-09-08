from pydantic import BaseModel, Field

from app.schemas.usuario import UsuarioResponse


class RegistroEmpresaRequest(BaseModel):
    ruc: str = Field(min_length=11, max_length=11, pattern=r"^\d{11}$")
    razon_social: str = Field(min_length=3, max_length=255)
    admin_nombres: str = Field(min_length=2, max_length=150)
    admin_apellidos: str = Field(min_length=2, max_length=150)
    admin_email: str = Field(min_length=5, max_length=150)
    admin_password: str = Field(min_length=8, max_length=100)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    usuario: UsuarioResponse
