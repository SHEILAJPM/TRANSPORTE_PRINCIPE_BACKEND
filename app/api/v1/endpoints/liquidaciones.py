import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.database import get_db
from app.models.usuario import Usuario
from app.schemas.liquidacion import LiquidacionResponse, RentabilidadResponse
from app.services.liquidacion_service import ViajeSinFechasError, generar_liquidacion_viaje
from app.services.reportes_service import calcular_rentabilidad_viaje

router = APIRouter(prefix="/viajes", tags=["Liquidaciones y Rentabilidad"])


@router.post("/{viaje_id}/liquidacion/calcular", response_model=LiquidacionResponse)
async def calcular_liquidacion_endpoint(
    viaje_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    usuario_actual: Usuario = Depends(get_current_user),
):
    try:
        liquidacion = await generar_liquidacion_viaje(db, viaje_id)
        await db.commit()
        return liquidacion
    except ViajeSinFechasError as error:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error))
    except ValueError as error:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error))


@router.get("/{viaje_id}/rentabilidad", response_model=RentabilidadResponse)
async def obtener_rentabilidad(
    viaje_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    usuario_actual: Usuario = Depends(get_current_user),
):
    try:
        return await calcular_rentabilidad_viaje(db, viaje_id)
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error))
