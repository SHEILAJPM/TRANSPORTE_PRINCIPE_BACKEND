from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.database import get_db
from app.core.security import crear_access_token
from app.models.usuario import Usuario
from app.schemas.auth import TokenResponse
from app.schemas.usuario import UsuarioResponse
from app.services.auth_service import CredencialesInvalidasError, autenticar_usuario

# Sin registro público: es un sistema de una sola empresa. El primer administrador se
# crea con `python -m app.crear_admin` y él crea los demás usuarios desde /usuarios.
router = APIRouter(prefix="/auth", tags=["Autenticación"])


@router.post("/login", response_model=TokenResponse)
async def login(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: AsyncSession = Depends(get_db),
):
    try:
        usuario = await autenticar_usuario(db, email=form_data.username, password=form_data.password)
    except CredencialesInvalidasError as error:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail=str(error), headers={"WWW-Authenticate": "Bearer"}
        )

    token = crear_access_token(subject=str(usuario.id))
    return TokenResponse(access_token=token, usuario=UsuarioResponse.model_validate(usuario))


@router.get("/me", response_model=UsuarioResponse)
async def obtener_perfil(usuario_actual: Usuario = Depends(get_current_user)):
    return usuario_actual
