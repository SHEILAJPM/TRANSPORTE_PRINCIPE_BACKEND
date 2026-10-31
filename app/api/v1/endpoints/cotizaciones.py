import uuid

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import get_current_user, require_roles
from app.core.database import get_db
from app.models.cotizacion import Cotizacion
from app.models.enums import EstadoCotizacion, RolUsuario
from app.models.usuario import Usuario
from app.schemas.cotizacion import (
    AsignacionUnidadRequest,
    CambiarEstadoCotizacionRequest,
    ConvertirCotizacionRequest,
    CotizacionCreateRequest,
    CotizacionResponse,
    DocumentoGeneradoResponse,
    ResultadoConversionResponse,
)
from app.services.cotizacion_service import (
    AsignacionIncompletaError,
    AsignacionUnidad,
    CotizacionNoAprobadaError,
    CotizacionYaConvertidaError,
    DatosCotizacion,
    ModalidadInconsistenteError,
    TransicionEstadoInvalidaError,
    cambiar_estado_cotizacion,
    convertir_cotizacion_a_viajes,
    crear_cotizacion,
)
from app.services.documentos_pdf_service import DocumentoNoEncontradoError, generar_pdf_cotizacion

router = APIRouter(prefix="/cotizaciones", tags=["Cotizaciones"])

_ROLES_ESCRITURA = (RolUsuario.ADMIN, RolUsuario.OPERADOR)


async def _obtener_cotizacion_o_404(db: AsyncSession, cotizacion_id: uuid.UUID) -> Cotizacion:
    stmt = select(Cotizacion).options(selectinload(Cotizacion.cliente)).where(Cotizacion.id == cotizacion_id)
    cotizacion = (await db.execute(stmt)).scalar_one_or_none()
    if cotizacion is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Cotización no encontrada")
    return cotizacion


@router.post("", response_model=CotizacionResponse, status_code=status.HTTP_201_CREATED)
async def crear(
    body: CotizacionCreateRequest,
    db: AsyncSession = Depends(get_db),
    usuario_actual: Usuario = Depends(require_roles(*_ROLES_ESCRITURA)),
):
    cotizacion = await crear_cotizacion(
        db,
        DatosCotizacion(**body.model_dump()),
        empresa_id=usuario_actual.empresa_id,
        usuario_id=usuario_actual.id,
    )
    await db.commit()
    return await _obtener_cotizacion_o_404(db, cotizacion.id)


@router.get("", response_model=list[CotizacionResponse])
async def listar(
    estado: EstadoCotizacion | None = None,
    cliente_id: uuid.UUID | None = None,
    db: AsyncSession = Depends(get_db),
    usuario_actual: Usuario = Depends(get_current_user),
):
    stmt = (
        select(Cotizacion)
        .options(selectinload(Cotizacion.cliente))
        .where(Cotizacion.empresa_id == usuario_actual.empresa_id)
    )
    if estado is not None:
        stmt = stmt.where(Cotizacion.estado == estado)
    if cliente_id is not None:
        stmt = stmt.where(Cotizacion.cliente_id == cliente_id)
    stmt = stmt.order_by(Cotizacion.fecha_emision.desc())
    return (await db.execute(stmt)).scalars().all()


@router.get("/{cotizacion_id}", response_model=CotizacionResponse)
async def obtener(
    cotizacion_id: uuid.UUID, db: AsyncSession = Depends(get_db), usuario_actual: Usuario = Depends(get_current_user)
):
    return await _obtener_cotizacion_o_404(db, cotizacion_id)


@router.get("/{cotizacion_id}/pdf")
async def descargar_pdf(
    cotizacion_id: uuid.UUID, db: AsyncSession = Depends(get_db), usuario_actual: Usuario = Depends(get_current_user)
):
    """PDF de la cotización con el logotipo dinámico de la empresa en la cabecera."""
    cotizacion = await _obtener_cotizacion_o_404(db, cotizacion_id)
    try:
        pdf = await generar_pdf_cotizacion(db, cotizacion.id)
    except DocumentoNoEncontradoError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error))
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="COTIZACION-{cotizacion.numero}.pdf"'},
    )


@router.patch("/{cotizacion_id}/estado", response_model=CotizacionResponse)
async def cambiar_estado(
    cotizacion_id: uuid.UUID,
    body: CambiarEstadoCotizacionRequest,
    db: AsyncSession = Depends(get_db),
    usuario_actual: Usuario = Depends(require_roles(*_ROLES_ESCRITURA)),
):
    cotizacion = await _obtener_cotizacion_o_404(db, cotizacion_id)
    try:
        await cambiar_estado_cotizacion(db, cotizacion, body.estado)
        await db.commit()
    except TransicionEstadoInvalidaError as error:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error))
    return await _obtener_cotizacion_o_404(db, cotizacion_id)


@router.post(
    "/{cotizacion_id}/convertir-a-viaje",
    response_model=list[ResultadoConversionResponse],
    summary="Conversión de 1 clic: Cotización -> Viaje + Guía de Remisión + Factura + Constancia de Pesos y Medidas",
)
async def convertir_cotizacion(
    cotizacion_id: uuid.UUID,
    body: ConvertirCotizacionRequest,
    db: AsyncSession = Depends(get_db),
    usuario_actual: Usuario = Depends(get_current_user),
):
    asignaciones = [
        AsignacionUnidad(
            tracto_id=a.tracto_id,
            chofer_id=a.chofer_id,
            fecha_salida_programada=a.fecha_salida_programada,
            carreta_id=a.carreta_id,
            tarifa_diaria_chofer=a.tarifa_diaria_chofer,
            bono_nocturno_chofer=a.bono_nocturno_chofer,
            precinto_seguridad=a.precinto_seguridad,
            lugar_verificacion_pesos=a.lugar_verificacion_pesos,
            origen_ubigeo=a.origen_ubigeo,
            destino_ubigeo=a.destino_ubigeo,
        )
        for a in body.asignaciones
    ]

    try:
        resultados = await convertir_cotizacion_a_viajes(
            db=db,
            cotizacion_id=cotizacion_id,
            asignaciones=asignaciones,
            empresa_id=usuario_actual.empresa_id,
            propietario_usuario_id=usuario_actual.id,
            modalidad=body.modalidad,
        )
        await db.commit()
    except (
        CotizacionYaConvertidaError,
        CotizacionNoAprobadaError,
        AsignacionIncompletaError,
        ModalidadInconsistenteError,
    ) as error:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error))
    except ValueError as error:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error))

    return [
        ResultadoConversionResponse(
            viaje=DocumentoGeneradoResponse(id=r.viaje.id, numero=r.viaje.numero),
            guia_remision=DocumentoGeneradoResponse(id=r.guia_remision.id, numero=r.guia_remision.numero),
            constancia_pesos_medidas=DocumentoGeneradoResponse(
                id=r.constancia_pesos_medidas.id, numero=r.constancia_pesos_medidas.numero
            ),
        )
        for r in resultados
    ]
