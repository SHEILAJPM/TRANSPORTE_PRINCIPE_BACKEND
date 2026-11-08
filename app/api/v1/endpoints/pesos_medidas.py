import uuid

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, require_roles
from app.core.database import get_db
from app.models.chofer import Chofer
from app.models.enums import RolUsuario
from app.models.flota import Carreta, Tracto
from app.models.pesos_medidas import ConstanciaPesosMedidas
from app.models.usuario import Usuario
from app.schemas.pesos_medidas import (
    AutocompletarVehiculoResponse,
    ConstanciaListItemResponse,
    ConstanciaPesosMedidasCreateRequest,
    ConstanciaPesosMedidasResponse,
    ConstanciaPesosMedidasUpdateRequest,
)
from app.services.documentos_pdf_service import DocumentoNoEncontradoError, generar_pdf_constancia_pesos_medidas
from app.services.pesos_medidas_service import (
    VehiculoNoEncontradoError,
    autocompletar_datos_vehiculo,
    construir_constancia_pesos_medidas,
    listar_constancias,
)

router = APIRouter(prefix="/pesos-medidas", tags=["Constancia de Pesos y Medidas (DS 058-2003-MTC)"])

_ROLES_ESCRITURA = (RolUsuario.ADMIN, RolUsuario.OPERADOR)


@router.get("", response_model=list[ConstanciaListItemResponse])
async def listar(
    q: str | None = None,
    db: AsyncSession = Depends(get_db),
    usuario_actual: Usuario = Depends(get_current_user),
):
    """Buscador del módulo de Pesos y Medidas: por número de constancia, placa o
    número de serie de la Guía de Remisión vinculada."""
    return await listar_constancias(db, empresa_id=usuario_actual.empresa_id, q=q)


@router.get("/autocompletar-vehiculo/{placa}", response_model=AutocompletarVehiculoResponse)
async def autocompletar_vehiculo(
    placa: str, db: AsyncSession = Depends(get_db), usuario_actual: Usuario = Depends(get_current_user)
):
    """Al seleccionar la placa, autocompleta dimensiones, configuración vehicular
    y peso bruto máximo del tracto o carreta correspondiente."""
    try:
        datos = await autocompletar_datos_vehiculo(db, placa)
    except VehiculoNoEncontradoError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error))
    return AutocompletarVehiculoResponse(**datos.__dict__)


@router.post("", response_model=ConstanciaPesosMedidasResponse, status_code=status.HTTP_201_CREATED)
async def crear_constancia(
    body: ConstanciaPesosMedidasCreateRequest,
    db: AsyncSession = Depends(get_db),
    usuario_actual: Usuario = Depends(require_roles(*_ROLES_ESCRITURA)),
):
    """Emite manualmente una Constancia para un viaje que aún no tiene una (p.ej.
    activado sin cotización previa a esta versión, o requiere una constancia adicional)."""
    tracto = await db.get(Tracto, body.tracto_id)
    chofer = await db.get(Chofer, body.chofer_id)
    carreta = await db.get(Carreta, body.carreta_id) if body.carreta_id else None
    if tracto is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Camión no encontrado")
    if chofer is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Chofer no encontrado")

    constancia = await construir_constancia_pesos_medidas(
        db,
        empresa_id=usuario_actual.empresa_id,
        guia_remision_id=body.guia_remision_id,
        viaje_id=body.viaje_id,
        tracto=tracto,
        carreta=carreta,
        chofer=chofer,
        generador_carga_cliente_id=body.generador_carga_cliente_id,
        fecha_verificacion=body.fecha_verificacion,
        tipo_control=body.tipo_control,
        lugar_verificacion=body.lugar_verificacion,
        precinto_seguridad=body.precinto_seguridad,
        peso_bruto_kg=body.peso_bruto_kg,
        tara_kg=body.tara_kg,
    )
    db.add(constancia)
    await db.commit()
    await db.refresh(constancia)
    return constancia


@router.get("/por-viaje/{viaje_id}", response_model=ConstanciaPesosMedidasResponse)
async def obtener_por_viaje(
    viaje_id: uuid.UUID, db: AsyncSession = Depends(get_db), usuario_actual: Usuario = Depends(get_current_user)
):
    stmt = select(ConstanciaPesosMedidas).where(ConstanciaPesosMedidas.viaje_id == viaje_id)
    constancia = (await db.execute(stmt)).scalar_one_or_none()
    if constancia is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Este viaje no tiene constancia emitida")
    return constancia


@router.get("/por-guia-remision/{guia_remision_id}", response_model=ConstanciaPesosMedidasResponse)
async def obtener_por_guia_remision(
    guia_remision_id: uuid.UUID, db: AsyncSession = Depends(get_db), usuario_actual: Usuario = Depends(get_current_user)
):
    """Búsqueda por el número de serie de la Guía de Remisión a la que está vinculada."""
    stmt = select(ConstanciaPesosMedidas).where(ConstanciaPesosMedidas.guia_remision_id == guia_remision_id)
    constancia = (await db.execute(stmt)).scalar_one_or_none()
    if constancia is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Esta guía de remisión no tiene constancia emitida")
    return constancia


@router.get("/{constancia_id}", response_model=ConstanciaPesosMedidasResponse)
async def obtener(
    constancia_id: uuid.UUID, db: AsyncSession = Depends(get_db), usuario_actual: Usuario = Depends(get_current_user)
):
    constancia = await db.get(ConstanciaPesosMedidas, constancia_id)
    if constancia is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Constancia no encontrada")
    return constancia


@router.get("/{constancia_id}/pdf")
async def descargar_pdf(
    constancia_id: uuid.UUID, db: AsyncSession = Depends(get_db), usuario_actual: Usuario = Depends(get_current_user)
):
    """PDF oficial de la Constancia de Verificación de Pesos y Medidas (DS N.° 058-2003-MTC)."""
    try:
        pdf = await generar_pdf_constancia_pesos_medidas(db, constancia_id)
    except DocumentoNoEncontradoError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error))
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="CONSTANCIA-{constancia_id}.pdf"'},
    )


@router.patch("/{constancia_id}", response_model=ConstanciaPesosMedidasResponse)
async def editar_constancia(
    constancia_id: uuid.UUID,
    body: ConstanciaPesosMedidasUpdateRequest,
    db: AsyncSession = Depends(get_db),
    usuario_actual: Usuario = Depends(get_current_user),
):
    """Edición manual (balanza real, precinto, o corrección de dimensiones) —
    módulo 4: todo campo autocompletado queda editable si fuera necesario."""
    constancia = await db.get(ConstanciaPesosMedidas, constancia_id)
    if constancia is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Constancia no encontrada")

    datos = body.model_dump(exclude_unset=True)
    for campo, valor in datos.items():
        setattr(constancia, campo, valor)

    if "peso_bruto_kg" in datos or "tara_kg" in datos:
        constancia.peso_neto_kg = max(float(constancia.peso_bruto_kg) - float(constancia.tara_kg), 0)

    await db.commit()
    await db.refresh(constancia)
    return constancia
