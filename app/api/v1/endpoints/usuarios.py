import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_roles
from app.core.database import get_db
from app.core.security import generar_password_hash
from app.models.enums import RolUsuario
from app.models.usuario import Usuario
from app.schemas.usuario import UsuarioCreateRequest, UsuarioResponse, UsuarioUpdateRequest

router = APIRouter(prefix="/usuarios", tags=["Usuarios"])


@router.post("", response_model=UsuarioResponse, status_code=status.HTTP_201_CREATED)
async def crear_usuario(
    body: UsuarioCreateRequest,
    db: AsyncSession = Depends(get_db),
    usuario_actual: Usuario = Depends(require_roles(RolUsuario.ADMIN)),
):
    ya_existe = (await db.execute(select(Usuario).where(Usuario.email == body.email))).scalar_one_or_none()
    if ya_existe is not None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"El correo {body.email} ya está registrado")

    usuario = Usuario(
        empresa_id=usuario_actual.empresa_id,
        nombres=body.nombres,
        apellidos=body.apellidos,
        email=body.email,
        hashed_password=generar_password_hash(body.password),
        rol=body.rol,
        chofer_id=body.chofer_id,
    )
    db.add(usuario)
    await db.commit()
    await db.refresh(usuario)
    return usuario


@router.get("", response_model=list[UsuarioResponse])
async def listar_usuarios(
    db: AsyncSession = Depends(get_db),
    usuario_actual: Usuario = Depends(require_roles(RolUsuario.ADMIN)),
):
    stmt = select(Usuario).where(Usuario.empresa_id == usuario_actual.empresa_id).order_by(Usuario.nombres)
    return (await db.execute(stmt)).scalars().all()


@router.get("/{usuario_id}", response_model=UsuarioResponse)
async def obtener_usuario(
    usuario_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    usuario_actual: Usuario = Depends(require_roles(RolUsuario.ADMIN)),
):
    usuario = await db.get(Usuario, usuario_id)
    if usuario is None or usuario.empresa_id != usuario_actual.empresa_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Usuario no encontrado")
    return usuario


@router.patch("/{usuario_id}", response_model=UsuarioResponse)
async def actualizar_usuario(
    usuario_id: uuid.UUID,
    body: UsuarioUpdateRequest,
    db: AsyncSession = Depends(get_db),
    usuario_actual: Usuario = Depends(require_roles(RolUsuario.ADMIN)),
):
    usuario = await db.get(Usuario, usuario_id)
    if usuario is None or usuario.empresa_id != usuario_actual.empresa_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Usuario no encontrado")

    for campo, valor in body.model_dump(exclude_unset=True).items():
        setattr(usuario, campo, valor)

    await db.commit()
    await db.refresh(usuario)
    return usuario
