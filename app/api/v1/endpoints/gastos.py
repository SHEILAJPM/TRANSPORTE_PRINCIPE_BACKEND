import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.database import get_db
from app.models.enums import RolUsuario
from app.models.gasto_viaje import GastoViaje
from app.models.usuario import Usuario
from app.models.viaje import Viaje
from app.schemas.gasto import GastoViajeCreateRequest, GastoViajeResponse

router = APIRouter(prefix="/viajes", tags=["Gastos de Viaje (App del Chofer)"])


@router.post("/{viaje_id}/gastos", response_model=GastoViajeResponse, status_code=status.HTTP_201_CREATED)
async def registrar_gasto(
    viaje_id: uuid.UUID,
    body: GastoViajeCreateRequest,
    db: AsyncSession = Depends(get_db),
    usuario_actual: Usuario = Depends(get_current_user),
):
    """Combustible, peajes, viáticos y adelantos reportados desde la app del chofer.

    Idempotente por `uuid_dispositivo`: si el dispositivo generó el registro sin
    conexión y reintenta la sincronización, el mismo `uuid_dispositivo` devuelve el
    gasto ya creado en vez de duplicarlo.
    """
    viaje = await db.get(Viaje, viaje_id)
    if viaje is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Viaje no encontrado")
    if usuario_actual.rol == RolUsuario.CHOFER and usuario_actual.chofer_id != viaje.chofer_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Este viaje no está asignado a su usuario")

    if body.uuid_dispositivo is not None:
        existente = (
            await db.execute(select(GastoViaje).where(GastoViaje.uuid_dispositivo == body.uuid_dispositivo))
        ).scalar_one_or_none()
        if existente is not None:
            return existente

    gasto = GastoViaje(
        viaje_id=viaje_id,
        registrado_por_chofer_id=usuario_actual.chofer_id,
        **body.model_dump(),
    )
    db.add(gasto)
    await db.commit()
    await db.refresh(gasto)
    return gasto


@router.get("/{viaje_id}/gastos", response_model=list[GastoViajeResponse])
async def listar_gastos(
    viaje_id: uuid.UUID, db: AsyncSession = Depends(get_db), usuario_actual: Usuario = Depends(get_current_user)
):
    stmt = select(GastoViaje).where(GastoViaje.viaje_id == viaje_id).order_by(GastoViaje.fecha.desc())
    return (await db.execute(stmt)).scalars().all()
