import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import get_current_user, require_roles
from app.core.database import get_db
from app.models.enums import EstadoViaje, RolUsuario
from app.models.novedad_viaje import NovedadViaje
from app.models.usuario import Usuario
from app.models.viaje import Viaje
from app.schemas.cotizacion import DocumentoGeneradoResponse
from app.schemas.novedad import NovedadViajeCreateRequest, NovedadViajeResponse
from app.schemas.viaje import ActivarViajeRequest, CambiarEstadoViajeRequest, ResultadoActivacionResponse, ViajeResponse
from app.services.viaje_service import ActivacionViaje, ModalidadInconsistenteError, activar_viaje

router = APIRouter(prefix="/viajes", tags=["Viajes"])

_ROLES_ESCRITURA = (RolUsuario.ADMIN, RolUsuario.OPERADOR)

_RELACIONES_VIAJE = (
    selectinload(Viaje.cliente),
    selectinload(Viaje.tracto),
    selectinload(Viaje.carreta),
    selectinload(Viaje.chofer),
)


async def _obtener_viaje_o_404(db: AsyncSession, viaje_id: uuid.UUID) -> Viaje:
    viaje = await db.get(Viaje, viaje_id)
    if viaje is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Viaje no encontrado")
    return viaje


async def _obtener_viaje_completo_o_404(db: AsyncSession, viaje_id: uuid.UUID) -> Viaje:
    stmt = select(Viaje).options(*_RELACIONES_VIAJE).where(Viaje.id == viaje_id)
    viaje = (await db.execute(stmt)).scalar_one_or_none()
    if viaje is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Viaje no encontrado")
    return viaje


@router.post("/activar", response_model=ResultadoActivacionResponse, status_code=status.HTTP_201_CREATED)
async def activar(
    body: ActivarViajeRequest,
    db: AsyncSession = Depends(get_db),
    usuario_actual: Usuario = Depends(require_roles(*_ROLES_ESCRITURA)),
):
    """Activación de Viaje por el Propietario: asigna tracto, carreta, chofer y
    cliente, y emite de inmediato la Guía de Remisión y la Constancia de Pesos y
    Medidas (más la Factura si la modalidad es CON_RUC)."""
    try:
        resultado = await activar_viaje(
            db,
            ActivacionViaje(
                empresa_id=usuario_actual.empresa_id,
                propietario_usuario_id=usuario_actual.id,
                **body.model_dump(),
            ),
        )
        await db.commit()
    except ModalidadInconsistenteError as error:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error))
    except ValueError as error:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error))

    return ResultadoActivacionResponse(
        viaje=DocumentoGeneradoResponse(id=resultado.viaje.id, numero=resultado.viaje.numero),
        guia_remision=DocumentoGeneradoResponse(id=resultado.guia_remision.id, numero=resultado.guia_remision.numero),
        factura=(
            DocumentoGeneradoResponse(id=resultado.factura.id, numero=resultado.factura.numero)
            if resultado.factura
            else None
        ),
        constancia_pesos_medidas=DocumentoGeneradoResponse(
            id=resultado.constancia_pesos_medidas.id, numero=resultado.constancia_pesos_medidas.numero
        ),
    )


@router.get("", response_model=list[ViajeResponse])
async def listar_viajes(
    estado: EstadoViaje | None = None,
    chofer_id: uuid.UUID | None = None,
    tracto_id: uuid.UUID | None = None,
    cotizacion_id: uuid.UUID | None = None,
    db: AsyncSession = Depends(get_db),
    usuario_actual: Usuario = Depends(get_current_user),
):
    stmt = select(Viaje).options(*_RELACIONES_VIAJE).where(Viaje.empresa_id == usuario_actual.empresa_id)
    if estado is not None:
        stmt = stmt.where(Viaje.estado == estado)
    if chofer_id is not None:
        stmt = stmt.where(Viaje.chofer_id == chofer_id)
    if tracto_id is not None:
        stmt = stmt.where(Viaje.tracto_id == tracto_id)
    if cotizacion_id is not None:
        stmt = stmt.where(Viaje.cotizacion_id == cotizacion_id)
    stmt = stmt.order_by(Viaje.fecha_salida_programada.desc())
    return (await db.execute(stmt)).scalars().all()


@router.get("/{viaje_id}", response_model=ViajeResponse)
async def obtener_viaje(
    viaje_id: uuid.UUID, db: AsyncSession = Depends(get_db), usuario_actual: Usuario = Depends(get_current_user)
):
    return await _obtener_viaje_completo_o_404(db, viaje_id)


@router.patch("/{viaje_id}/estado", response_model=ViajeResponse)
async def cambiar_estado(
    viaje_id: uuid.UUID,
    body: CambiarEstadoViajeRequest,
    db: AsyncSession = Depends(get_db),
    usuario_actual: Usuario = Depends(get_current_user),
):
    """Transiciones operativas del viaje (PROGRAMADO -> EN_RUTA -> FINALIZADO) y
    registro de las fechas reales de salida/llegada usadas para liquidar dietas."""
    viaje = await _obtener_viaje_o_404(db, viaje_id)
    if usuario_actual.rol == RolUsuario.CHOFER and usuario_actual.chofer_id != viaje.chofer_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Este viaje no está asignado a su usuario")

    viaje.estado = body.estado
    if body.fecha_salida_real is not None:
        viaje.fecha_salida_real = body.fecha_salida_real
    if body.fecha_llegada_real is not None:
        viaje.fecha_llegada_real = body.fecha_llegada_real
    if body.observaciones is not None:
        viaje.observaciones = body.observaciones

    await db.commit()
    return await _obtener_viaje_completo_o_404(db, viaje_id)


# --- Novedades en ruta -------------------------------------------------------


@router.post("/{viaje_id}/novedades", response_model=NovedadViajeResponse, status_code=status.HTTP_201_CREATED)
async def reportar_novedad(
    viaje_id: uuid.UUID,
    body: NovedadViajeCreateRequest,
    db: AsyncSession = Depends(get_db),
    usuario_actual: Usuario = Depends(get_current_user),
):
    viaje = await _obtener_viaje_o_404(db, viaje_id)
    if usuario_actual.rol == RolUsuario.CHOFER and usuario_actual.chofer_id != viaje.chofer_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Este viaje no está asignado a su usuario")

    # Idempotente por uuid_dispositivo: un reintento de sincronización offline no
    # debe crear una novedad duplicada.
    if body.uuid_dispositivo is not None:
        existente = (
            await db.execute(select(NovedadViaje).where(NovedadViaje.uuid_dispositivo == body.uuid_dispositivo))
        ).scalar_one_or_none()
        if existente is not None:
            return existente

    novedad = NovedadViaje(viaje_id=viaje_id, **body.model_dump())
    db.add(novedad)
    await db.commit()
    await db.refresh(novedad)
    return novedad


@router.get("/{viaje_id}/novedades", response_model=list[NovedadViajeResponse])
async def listar_novedades(
    viaje_id: uuid.UUID, db: AsyncSession = Depends(get_db), usuario_actual: Usuario = Depends(get_current_user)
):
    stmt = select(NovedadViaje).where(NovedadViaje.viaje_id == viaje_id).order_by(NovedadViaje.fecha.desc())
    return (await db.execute(stmt)).scalars().all()
