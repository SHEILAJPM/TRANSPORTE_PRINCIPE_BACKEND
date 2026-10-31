from pydantic import BaseModel

from app.schemas.usuario import UsuarioResponse


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    usuario: UsuarioResponse
