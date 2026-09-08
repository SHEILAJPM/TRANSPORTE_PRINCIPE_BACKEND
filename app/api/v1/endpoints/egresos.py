import uuid
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, require_roles
from app.core.database import get_db
from app.models.enums import CategoriaGastoGeneral, RolUsuario
from app.models.gasto_general import GastoGeneral
from app.models.usuario import Usuario
from app.schemas.gasto_general import GastoGeneralCreateRequest, GastoGeneralResponse, GastoGeneralUpdateRequest

router = APIRouter(prefix="/egresos-generales", tags=["Egresos Generales"])

# Contabilidad puede registrar/editar egresos además de Admin/Operador: es justamente
# el rol pensado para llevar este tipo de registro.
_ROLES_ESCRITURA = (RolUsuario.ADMIN, RolUsuario.OPERADOR, RolUsuario.CONTABILIDAD)


async def _obtener_o_404(db: AsyncSession, gasto_id: uuid.UUID, empresa_id: uuid.UUID) -> GastoGeneral:
    gasto = await db.get(GastoGeneral, gasto_id)
    if gasto is None or gasto.empresa_id != empresa_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Egreso no encontrado")
    return gasto


@router.post("", response_model=GastoGeneralResponse, status_code=status.HTTP_201_CREATED)
async def crear(
    body: GastoGeneralCreateRequest,
    db: AsyncSession = Depends(get_db),
    usuario_actual: Usuario = Depends(require_roles(*_ROLES_ESCRITURA)),
):
    gasto = GastoGeneral(
        empresa_id=usuario_actual.empresa_id,
        registrado_por_usuario_id=usuario_actual.id,
        **body.model_dump(),
    )
    db.add(gasto)
    await db.commit()
    await db.refresh(gasto)
    return gasto


@router.get("", response_model=list[GastoGeneralResponse])
async def listar(
    categoria: CategoriaGastoGeneral | None = None,
    fecha_desde: date | None = None,
    fecha_hasta: date | None = None,
    db: AsyncSession = Depends(get_db),
    usuario_actual: Usuario = Depends(get_current_user),
):
    stmt = select(GastoGeneral).where(GastoGeneral.empresa_id == usuario_actual.empresa_id)
    if categoria is not None:
        stmt = stmt.where(GastoGeneral.categoria == categoria)
    if fecha_desde is not None:
        stmt = stmt.where(GastoGeneral.fecha >= fecha_desde)
    if fecha_hasta is not None:
        stmt = stmt.where(GastoGeneral.fecha <= fecha_hasta)
    stmt = stmt.order_by(GastoGeneral.fecha.desc())
    return (await db.execute(stmt)).scalars().all()


@router.patch("/{gasto_id}", response_model=GastoGeneralResponse)
async def actualizar(
    gasto_id: uuid.UUID,
    body: GastoGeneralUpdateRequest,
    db: AsyncSession = Depends(get_db),
    usuario_actual: Usuario = Depends(require_roles(*_ROLES_ESCRITURA)),
):
    gasto = await _obtener_o_404(db, gasto_id, usuario_actual.empresa_id)
    for campo, valor in body.model_dump(exclude_unset=True).items():
        setattr(gasto, campo, valor)
    await db.commit()
    await db.refresh(gasto)
    return gasto


@router.delete("/{gasto_id}", status_code=status.HTTP_204_NO_CONTENT)
async def eliminar(
    gasto_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    usuario_actual: Usuario = Depends(require_roles(*_ROLES_ESCRITURA)),
):
    gasto = await _obtener_o_404(db, gasto_id, usuario_actual.empresa_id)
    await db.delete(gasto)
    await db.commit()
