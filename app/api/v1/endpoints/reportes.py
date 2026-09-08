import uuid
from datetime import date

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.database import get_db
from app.models.usuario import Usuario
from app.schemas.reportes import ResumenFinancieroResponse, ViajeRentabilidadItemResponse
from app.services.reportes_service import buscar_viajes_rentabilidad, calcular_resumen_financiero

router = APIRouter(prefix="/reportes", tags=["Reportes y Rentabilidad"])


@router.get("/resumen-financiero", response_model=ResumenFinancieroResponse)
async def resumen_financiero(
    fecha_desde: date | None = None,
    fecha_hasta: date | None = None,
    db: AsyncSession = Depends(get_db),
    usuario_actual: Usuario = Depends(get_current_user),
):
    """P&L general de la empresa: ingresos de todos los viajes menos gastos
    operativos de viaje, dietas, mantenimiento de flota y egresos generales."""
    return await calcular_resumen_financiero(
        db, empresa_id=usuario_actual.empresa_id, fecha_desde=fecha_desde, fecha_hasta=fecha_hasta
    )


@router.get("/viajes", response_model=list[ViajeRentabilidadItemResponse])
async def buscar_viajes(
    cliente_id: uuid.UUID | None = None,
    placa: str | None = None,
    ciudad: str | None = None,
    fecha_desde: date | None = None,
    fecha_hasta: date | None = None,
    db: AsyncSession = Depends(get_db),
    usuario_actual: Usuario = Depends(get_current_user),
):
    """Buscador avanzado de cobros/rentabilidad (módulo 6): filtra por cliente,
    placa (tracto o carreta), ciudad de origen o destino y rango de fechas, devolviendo
    el consolidado financiero [Ingresos - Egresos = Ganancia Neta] por viaje."""
    return await buscar_viajes_rentabilidad(
        db,
        empresa_id=usuario_actual.empresa_id,
        cliente_id=cliente_id,
        placa=placa,
        ciudad=ciudad,
        fecha_desde=fecha_desde,
        fecha_hasta=fecha_hasta,
    )
