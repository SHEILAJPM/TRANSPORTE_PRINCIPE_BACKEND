from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.database import get_db
from app.core.security import crear_access_token
from app.models.usuario import Usuario
from app.schemas.auth import RegistroEmpresaRequest, TokenResponse
from app.schemas.usuario import UsuarioResponse
from app.services.auth_service import (
    CredencialesInvalidasError,
    EmailYaRegistradoError,
    RucYaRegistradoError,
    autenticar_usuario,
    registrar_empresa_y_admin,
)

router = APIRouter(prefix="/auth", tags=["Autenticación"])


@router.post("/registro-empresa", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
async def registrar_empresa(body: RegistroEmpresaRequest, db: AsyncSession = Depends(get_db)):
    """Alta inicial del sistema: crea la empresa y su primer usuario ADMIN, y lo
    autentica de inmediato (no requiere token previo)."""
    try:
        _, admin = await registrar_empresa_y_admin(
            db,
            ruc=body.ruc,
            razon_social=body.razon_social,
            admin_nombres=body.admin_nombres,
            admin_apellidos=body.admin_apellidos,
            admin_email=body.admin_email,
            admin_password=body.admin_password,
        )
        await db.commit()
    except (RucYaRegistradoError, EmailYaRegistradoError) as error:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error))

    token = crear_access_token(subject=str(admin.id))
    return TokenResponse(access_token=token, usuario=UsuarioResponse.model_validate(admin))


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
