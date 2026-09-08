import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, require_roles
from app.core.database import get_db
from app.models.enums import RolUsuario
from app.models.flota import Carreta, Tracto
from app.models.mantenimiento import MantenimientoVehiculo
from app.models.usuario import Usuario
from app.schemas.flota import (
    AlertaVencimientoResponse,
    CarretaCreateRequest,
    CarretaResponse,
    CarretaUpdateRequest,
    MantenimientoCreateRequest,
    MantenimientoResponse,
    TractoCreateRequest,
    TractoResponse,
    TractoUpdateRequest,
)
from app.services.alertas_service import listar_alertas_vencimiento

router = APIRouter(prefix="/flota", tags=["Flota"])

_ROLES_ESCRITURA = (RolUsuario.ADMIN, RolUsuario.OPERADOR)


@router.get("/alertas-vencimiento", response_model=list[AlertaVencimientoResponse])
async def alertas_vencimiento(db: AsyncSession = Depends(get_db), usuario_actual: Usuario = Depends(get_current_user)):
    """SOAT, CITV (revisión técnica), habilitación MTC y licencias/exámenes médicos
    vencidos o próximos a vencer, según los umbrales configurados en Settings."""
    alertas = await listar_alertas_vencimiento(db)
    return [
        AlertaVencimientoResponse(
            entidad_tipo=a.entidad_tipo,
            entidad_id=a.entidad_id,
            identificador=a.identificador,
            concepto=a.concepto,
            fecha_vencimiento=a.fecha_vencimiento,
            dias_restantes=a.dias_restantes,
            vencido=a.vencido,
        )
        for a in alertas
    ]


# --- Tractos ---------------------------------------------------------------


@router.post("/tractos", response_model=TractoResponse, status_code=status.HTTP_201_CREATED)
async def crear_tracto(
    body: TractoCreateRequest,
    db: AsyncSession = Depends(get_db),
    usuario_actual: Usuario = Depends(require_roles(*_ROLES_ESCRITURA)),
):
    ya_existe = (await db.execute(select(Tracto).where(Tracto.placa == body.placa))).scalar_one_or_none()
    if ya_existe is not None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Ya existe un tracto con placa {body.placa}")

    tracto = Tracto(**body.model_dump())
    db.add(tracto)
    await db.commit()
    await db.refresh(tracto)
    return tracto


@router.get("/tractos", response_model=list[TractoResponse])
async def listar_tractos(db: AsyncSession = Depends(get_db), usuario_actual: Usuario = Depends(get_current_user)):
    return (await db.execute(select(Tracto).order_by(Tracto.placa))).scalars().all()


@router.get("/tractos/{tracto_id}", response_model=TractoResponse)
async def obtener_tracto(
    tracto_id: uuid.UUID, db: AsyncSession = Depends(get_db), usuario_actual: Usuario = Depends(get_current_user)
):
    tracto = await db.get(Tracto, tracto_id)
    if tracto is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tracto no encontrado")
    return tracto


@router.patch("/tractos/{tracto_id}", response_model=TractoResponse)
async def actualizar_tracto(
    tracto_id: uuid.UUID,
    body: TractoUpdateRequest,
    db: AsyncSession = Depends(get_db),
    usuario_actual: Usuario = Depends(require_roles(*_ROLES_ESCRITURA)),
):
    tracto = await db.get(Tracto, tracto_id)
    if tracto is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tracto no encontrado")
    for campo, valor in body.model_dump(exclude_unset=True).items():
        setattr(tracto, campo, valor)
    await db.commit()
    await db.refresh(tracto)
    return tracto


@router.post("/tractos/{tracto_id}/mantenimientos", response_model=MantenimientoResponse, status_code=status.HTTP_201_CREATED)
async def registrar_mantenimiento_tracto(
    tracto_id: uuid.UUID,
    body: MantenimientoCreateRequest,
    db: AsyncSession = Depends(get_db),
    usuario_actual: Usuario = Depends(require_roles(*_ROLES_ESCRITURA)),
):
    tracto = await db.get(Tracto, tracto_id)
    if tracto is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tracto no encontrado")

    mantenimiento = MantenimientoVehiculo(tracto_id=tracto_id, **body.model_dump())
    db.add(mantenimiento)
    if body.completado and body.kilometraje_actual_registro > tracto.kilometraje_actual:
        tracto.kilometraje_actual = body.kilometraje_actual_registro
    await db.commit()
    await db.refresh(mantenimiento)
    return mantenimiento


@router.get("/tractos/{tracto_id}/mantenimientos", response_model=list[MantenimientoResponse])
async def listar_mantenimientos_tracto(
    tracto_id: uuid.UUID, db: AsyncSession = Depends(get_db), usuario_actual: Usuario = Depends(get_current_user)
):
    stmt = (
        select(MantenimientoVehiculo)
        .where(MantenimientoVehiculo.tracto_id == tracto_id)
        .order_by(MantenimientoVehiculo.fecha_realizado.desc())
    )
    return (await db.execute(stmt)).scalars().all()


# --- Carretas ----------------------------------------------------------------


@router.post("/carretas", response_model=CarretaResponse, status_code=status.HTTP_201_CREATED)
async def crear_carreta(
    body: CarretaCreateRequest,
    db: AsyncSession = Depends(get_db),
    usuario_actual: Usuario = Depends(require_roles(*_ROLES_ESCRITURA)),
):
    ya_existe = (await db.execute(select(Carreta).where(Carreta.placa == body.placa))).scalar_one_or_none()
    if ya_existe is not None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Ya existe una carreta con placa {body.placa}")

    carreta = Carreta(**body.model_dump())
    db.add(carreta)
    await db.commit()
    await db.refresh(carreta)
    return carreta


@router.get("/carretas", response_model=list[CarretaResponse])
async def listar_carretas(db: AsyncSession = Depends(get_db), usuario_actual: Usuario = Depends(get_current_user)):
    return (await db.execute(select(Carreta).order_by(Carreta.placa))).scalars().all()


@router.get("/carretas/{carreta_id}", response_model=CarretaResponse)
async def obtener_carreta(
    carreta_id: uuid.UUID, db: AsyncSession = Depends(get_db), usuario_actual: Usuario = Depends(get_current_user)
):
    carreta = await db.get(Carreta, carreta_id)
    if carreta is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Carreta no encontrada")
    return carreta


@router.patch("/carretas/{carreta_id}", response_model=CarretaResponse)
async def actualizar_carreta(
    carreta_id: uuid.UUID,
    body: CarretaUpdateRequest,
    db: AsyncSession = Depends(get_db),
    usuario_actual: Usuario = Depends(require_roles(*_ROLES_ESCRITURA)),
):
    carreta = await db.get(Carreta, carreta_id)
    if carreta is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Carreta no encontrada")
    for campo, valor in body.model_dump(exclude_unset=True).items():
        setattr(carreta, campo, valor)
    await db.commit()
    await db.refresh(carreta)
    return carreta


@router.post(
    "/carretas/{carreta_id}/mantenimientos", response_model=MantenimientoResponse, status_code=status.HTTP_201_CREATED
)
async def registrar_mantenimiento_carreta(
    carreta_id: uuid.UUID,
    body: MantenimientoCreateRequest,
    db: AsyncSession = Depends(get_db),
    usuario_actual: Usuario = Depends(require_roles(*_ROLES_ESCRITURA)),
):
    carreta = await db.get(Carreta, carreta_id)
    if carreta is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Carreta no encontrada")

    mantenimiento = MantenimientoVehiculo(carreta_id=carreta_id, **body.model_dump())
    db.add(mantenimiento)
    if body.completado and body.kilometraje_actual_registro > carreta.kilometraje_actual:
        carreta.kilometraje_actual = body.kilometraje_actual_registro
    await db.commit()
    await db.refresh(mantenimiento)
    return mantenimiento


@router.get("/carretas/{carreta_id}/mantenimientos", response_model=list[MantenimientoResponse])
async def listar_mantenimientos_carreta(
    carreta_id: uuid.UUID, db: AsyncSession = Depends(get_db), usuario_actual: Usuario = Depends(get_current_user)
):
    stmt = (
        select(MantenimientoVehiculo)
        .where(MantenimientoVehiculo.carreta_id == carreta_id)
        .order_by(MantenimientoVehiculo.fecha_realizado.desc())
    )
    return (await db.execute(stmt)).scalars().all()
