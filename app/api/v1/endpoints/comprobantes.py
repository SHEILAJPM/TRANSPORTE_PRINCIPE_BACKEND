import uuid

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, require_roles
from app.core.database import get_db
from app.models.comprobante import Factura, GuiaRemision
from app.models.enums import EstadoSunat, RolUsuario, TipoDocumentoVenta
from app.models.usuario import Usuario
from app.schemas.comprobante import (
    AnularComprobanteRequest,
    FacturaListItemResponse,
    FacturaResponse,
    GuiaRemisionActualizarRequest,
    GuiaRemisionListItemResponse,
    GuiaRemisionResponse,
)
from app.services.apisunat_facturacion_service import (
    AnulacionNoSoportadaError,
    ApiSunatFacturacionError,
    ComprobanteNoAceptadoError,
    DatosIncompletosError,
    anular_comprobante,
    emitir_factura,
    emitir_guia_remision_transportista,
)
from app.services.comprobantes_service import listar_facturas, listar_guias_remision
from app.services.documentos_pdf_service import (
    DocumentoNoEncontradoError,
    generar_pdf_factura,
    generar_pdf_guia_remision,
)

router = APIRouter(prefix="/viajes", tags=["Guía de Remisión y Factura"])

router_listado = APIRouter(prefix="/comprobantes", tags=["Guía de Remisión y Factura"])

_ROLES_ESCRITURA = (RolUsuario.ADMIN, RolUsuario.OPERADOR)

# Un viaje solo tiene UN documento de venta "propio" (Factura o Boleta); una eventual
# Nota de Crédito comparte el mismo viaje_id pero no es "la" factura del viaje.
_TIPOS_DOCUMENTO_VENTA_VIAJE = (TipoDocumentoVenta.FACTURA, TipoDocumentoVenta.BOLETA)


def _stmt_factura_del_viaje(viaje_id: uuid.UUID):
    return select(Factura).where(
        Factura.viaje_id == viaje_id, Factura.tipo_documento.in_(_TIPOS_DOCUMENTO_VENTA_VIAJE)
    )


@router_listado.get("/guias-remision", response_model=list[GuiaRemisionListItemResponse])
async def listar_guias_remision_endpoint(
    estado_sunat: EstadoSunat | None = None,
    q: str | None = None,
    db: AsyncSession = Depends(get_db),
    usuario_actual: Usuario = Depends(get_current_user),
):
    """Listado de todas las Guías de Remisión de la empresa, con su estado SUNAT."""
    return await listar_guias_remision(db, empresa_id=usuario_actual.empresa_id, estado_sunat=estado_sunat, q=q)


@router_listado.get("/facturas", response_model=list[FacturaListItemResponse])
async def listar_facturas_endpoint(
    estado_sunat: EstadoSunat | None = None,
    q: str | None = None,
    db: AsyncSession = Depends(get_db),
    usuario_actual: Usuario = Depends(get_current_user),
):
    """Listado de todas las Facturas y Boletas de la empresa, con su estado SUNAT."""
    return await listar_facturas(db, empresa_id=usuario_actual.empresa_id, estado_sunat=estado_sunat, q=q)


@router.get("/{viaje_id}/guia-remision", response_model=GuiaRemisionResponse)
async def obtener_guia_remision(
    viaje_id: uuid.UUID, db: AsyncSession = Depends(get_db), usuario_actual: Usuario = Depends(get_current_user)
):
    guia = (await db.execute(select(GuiaRemision).where(GuiaRemision.viaje_id == viaje_id))).scalar_one_or_none()
    if guia is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Este viaje no tiene guía de remisión emitida")
    return guia


@router.get("/{viaje_id}/guia-remision/pdf")
async def descargar_guia_remision_pdf(
    viaje_id: uuid.UUID, db: AsyncSession = Depends(get_db), usuario_actual: Usuario = Depends(get_current_user)
):
    guia = (await db.execute(select(GuiaRemision).where(GuiaRemision.viaje_id == viaje_id))).scalar_one_or_none()
    if guia is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Este viaje no tiene guía de remisión emitida")
    try:
        pdf = await generar_pdf_guia_remision(db, guia.id)
    except DocumentoNoEncontradoError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error))
    nombre_archivo = f"GRE-{guia.serie}-{guia.numero}.pdf"
    return Response(
        content=pdf, media_type="application/pdf", headers={"Content-Disposition": f'inline; filename="{nombre_archivo}"'}
    )


@router.patch("/{viaje_id}/guia-remision", response_model=GuiaRemisionResponse)
async def actualizar_guia_remision(
    viaje_id: uuid.UUID,
    datos: GuiaRemisionActualizarRequest,
    db: AsyncSession = Depends(get_db),
    usuario_actual: Usuario = Depends(require_roles(*_ROLES_ESCRITURA)),
):
    """Registra la Guía de Remisión Remitente que el cliente ya generó por su cuenta
    (opcional), para referenciarla al emitir la guía transportista a SUNAT."""
    guia = (await db.execute(select(GuiaRemision).where(GuiaRemision.viaje_id == viaje_id))).scalar_one_or_none()
    if guia is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Este viaje no tiene guía de remisión emitida")
    if guia.estado_sunat == "ACEPTADO":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="La guía ya fue aceptada por SUNAT, no se puede modificar",
        )
    for campo, valor in datos.model_dump(exclude_unset=True).items():
        setattr(guia, campo, valor or None)
    await db.commit()
    await db.refresh(guia)
    return guia


@router.post("/{viaje_id}/guia-remision/emitir-sunat", response_model=GuiaRemisionResponse)
async def emitir_guia_remision_a_sunat(
    viaje_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    usuario_actual: Usuario = Depends(require_roles(*_ROLES_ESCRITURA)),
):
    """Envía la Guía de Remisión Transportista a SUNAT vía apisunat.pe. Puede
    reintentarse: si ya fue aceptada, apisunat.pe devuelve el mismo resultado."""
    guia = (await db.execute(select(GuiaRemision).where(GuiaRemision.viaje_id == viaje_id))).scalar_one_or_none()
    if guia is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Este viaje no tiene guía de remisión emitida")
    try:
        guia = await emitir_guia_remision_transportista(db, guia.id)
        await db.commit()
    except DatosIncompletosError as error:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error))
    except ApiSunatFacturacionError as error:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(error))
    return guia


@router.get("/{viaje_id}/factura", response_model=FacturaResponse)
async def obtener_factura(
    viaje_id: uuid.UUID, db: AsyncSession = Depends(get_db), usuario_actual: Usuario = Depends(get_current_user)
):
    factura = (await db.execute(_stmt_factura_del_viaje(viaje_id))).scalar_one_or_none()
    if factura is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Este viaje no tiene factura emitida")
    return factura


@router.post("/{viaje_id}/factura/emitir-sunat", response_model=FacturaResponse)
async def emitir_factura_a_sunat(
    viaje_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    usuario_actual: Usuario = Depends(require_roles(*_ROLES_ESCRITURA)),
):
    """Envía la Factura a SUNAT vía apisunat.pe. Puede reintentarse: si ya fue
    aceptada, apisunat.pe devuelve el mismo resultado."""
    factura = (await db.execute(_stmt_factura_del_viaje(viaje_id))).scalar_one_or_none()
    if factura is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Este viaje no tiene factura emitida")
    try:
        factura = await emitir_factura(db, factura.id)
        await db.commit()
    except DatosIncompletosError as error:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error))
    except ApiSunatFacturacionError as error:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(error))
    return factura


@router.post("/{viaje_id}/factura/anular-sunat", response_model=FacturaResponse)
async def anular_factura_a_sunat(
    viaje_id: uuid.UUID,
    datos: AnularComprobanteRequest,
    db: AsyncSession = Depends(get_db),
    usuario_actual: Usuario = Depends(require_roles(*_ROLES_ESCRITURA)),
):
    """Anula la Factura o Boleta del viaje ante SUNAT. Dentro de plazo usa la vía
    directa (comunicación de baja / resumen diario); fuera de plazo, emite una Nota
    de Crédito de anulación total (que puede consultarse en /comprobantes/facturas)."""
    factura = (await db.execute(_stmt_factura_del_viaje(viaje_id))).scalar_one_or_none()
    if factura is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Este viaje no tiene factura emitida")
    try:
        factura = await anular_comprobante(db, factura.id, motivo=datos.motivo)
        await db.commit()
    except (ComprobanteNoAceptadoError, AnulacionNoSoportadaError) as error:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error))
    except DatosIncompletosError as error:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error))
    except ApiSunatFacturacionError as error:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(error))
    return factura


@router.get("/{viaje_id}/factura/pdf")
async def descargar_factura_pdf(
    viaje_id: uuid.UUID, db: AsyncSession = Depends(get_db), usuario_actual: Usuario = Depends(get_current_user)
):
    factura = (await db.execute(_stmt_factura_del_viaje(viaje_id))).scalar_one_or_none()
    if factura is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Este viaje no tiene factura emitida")
    try:
        pdf = await generar_pdf_factura(db, factura.id)
    except DocumentoNoEncontradoError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error))
    nombre_archivo = f"{factura.tipo_documento.value}-{factura.serie}-{factura.numero}.pdf"
    return Response(
        content=pdf, media_type="application/pdf", headers={"Content-Disposition": f'inline; filename="{nombre_archivo}"'}
    )
