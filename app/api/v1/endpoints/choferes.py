import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, require_roles
from app.core.database import get_db
from app.models.chofer import Chofer
from app.models.enums import RolUsuario
from app.models.usuario import Usuario
from app.schemas.chofer import ChoferCreateRequest, ChoferResponse, ChoferUpdateRequest

router = APIRouter(prefix="/choferes", tags=["Choferes"])

_ROLES_ESCRITURA = (RolUsuario.ADMIN, RolUsuario.OPERADOR)


@router.post("", response_model=ChoferResponse, status_code=status.HTTP_201_CREATED)
async def crear_chofer(
    body: ChoferCreateRequest,
    db: AsyncSession = Depends(get_db),
    usuario_actual: Usuario = Depends(require_roles(*_ROLES_ESCRITURA)),
):
    if (await db.execute(select(Chofer).where(Chofer.dni == body.dni))).scalar_one_or_none() is not None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Ya existe un chofer con DNI {body.dni}")
    if (
        await db.execute(select(Chofer).where(Chofer.licencia_numero == body.licencia_numero))
    ).scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=f"Ya existe un chofer con licencia {body.licencia_numero}"
        )

    chofer = Chofer(**body.model_dump())
    db.add(chofer)
    await db.commit()
    await db.refresh(chofer)
    return chofer


@router.get("", response_model=list[ChoferResponse])
async def listar_choferes(
    solo_activos: bool = True,
    db: AsyncSession = Depends(get_db),
    usuario_actual: Usuario = Depends(get_current_user),
):
    stmt = select(Chofer).order_by(Chofer.nombres)
    if solo_activos:
        stmt = stmt.where(Chofer.activo.is_(True))
    return (await db.execute(stmt)).scalars().all()


@router.get("/{chofer_id}", response_model=ChoferResponse)
async def obtener_chofer(
    chofer_id: uuid.UUID, db: AsyncSession = Depends(get_db), usuario_actual: Usuario = Depends(get_current_user)
):
    chofer = await db.get(Chofer, chofer_id)
    if chofer is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Chofer no encontrado")
    return chofer


@router.patch("/{chofer_id}", response_model=ChoferResponse)
async def actualizar_chofer(
    chofer_id: uuid.UUID,
    body: ChoferUpdateRequest,
    db: AsyncSession = Depends(get_db),
    usuario_actual: Usuario = Depends(require_roles(*_ROLES_ESCRITURA)),
):
    chofer = await db.get(Chofer, chofer_id)
    if chofer is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Chofer no encontrado")
    for campo, valor in body.model_dump(exclude_unset=True).items():
        setattr(chofer, campo, valor)
    await db.commit()
    await db.refresh(chofer)
    return chofer
