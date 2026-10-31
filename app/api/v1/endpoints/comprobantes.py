import uuid
from dataclasses import asdict

from fastapi import APIRouter, Depends, HTTPException, Response, status
from fastapi.encoders import jsonable_encoder
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, require_roles
from app.core.database import get_db
from app.models.comprobante import Factura, GuiaRemision
from app.models.enums import EstadoSunat, RolUsuario, TipoDocumentoVenta
from app.models.usuario import Usuario
from app.schemas.cliente import ClienteResponse
from app.schemas.comprobante import (
    AnularComprobanteRequest,
    ComprobanteBorradorResponse,
    ComprobanteVistaPreviaResponse,
    EmitirComprobanteRequest,
    EmitirGuiaRequest,
    EntradaComprobanteRequest,
    FacturaListItemResponse,
    FacturaResponse,
    GuiaRemisionActualizarRequest,
    GuiaRemisionListItemResponse,
    GuiaRemisionResponse,
    GuiaVistaPreviaResponse,
)
from app.services import facturacion_viaje_service, guia_transportista_service
from app.services.apisunat_facturacion_service import (
    AnulacionNoSoportadaError,
    ApiSunatFacturacionError,
    ComprobanteNoAceptadoError,
    DatosIncompletosError,
    anular_comprobante,
    emitir_factura,
)
from app.services.guia_transportista_service import GuiaNoEmitibleError, HuellaNoCoincideError
from app.services.storage_service import ArchivoPrivadoNoEncontradoError, StorageService
from app.services.sunat_gre_api_service import SunatGreError
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
    # El más reciente: si uno fue rechazado y se emitió otro, este es el vigente.
    return (
        select(Factura)
        .where(Factura.viaje_id == viaje_id, Factura.tipo_documento.in_(_TIPOS_DOCUMENTO_VENTA_VIAJE))
        .order_by(Factura.creado_en.desc())
        .limit(1)
    )


def _entrada_comprobante(body: EntradaComprobanteRequest) -> facturacion_viaje_service.EntradaComprobante:
    return facturacion_viaje_service.EntradaComprobante(
        tipo_documento=body.tipo_documento,
        precio=body.precio,
        precio_incluye_igv=body.precio_incluye_igv,
        receptor=body.receptor,
        descripcion=body.descripcion,
    )


@router.get("/{viaje_id}/comprobante/borrador", response_model=ComprobanteBorradorResponse)
async def borrador_comprobante(
    viaje_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    usuario_actual: Usuario = Depends(require_roles(*_ROLES_ESCRITURA)),
):
    """Datos para el botón "Emitir factura": tipo sugerido (RUC → factura, DNI →
    boleta), precio de la cotización si existe y motivos que impiden emitir."""
    try:
        b = await facturacion_viaje_service.borrador(db, viaje_id, usuario_actual.empresa_id)
    except facturacion_viaje_service.ViajeNoEncontradoError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error))
    except facturacion_viaje_service.ComprobanteNoEmitibleError as error:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error))
    return ComprobanteBorradorResponse(
        tipo_sugerido=b.tipo_sugerido,
        cliente=ClienteResponse.model_validate(b.cliente),
        precio_sugerido=float(b.precio_sugerido) if b.precio_sugerido is not None else None,
        precio_incluye_igv=b.precio_incluye_igv,
        origen_precio=b.origen_precio,
        descripcion_sugerida=b.descripcion_sugerida,
        guia_remision=f"{b.guia_remision.serie}-{b.guia_remision.numero}" if b.guia_remision else None,
        guia_estado_sunat=b.guia_remision.estado_sunat if b.guia_remision else None,
        porcentaje_igv=float(facturacion_viaje_service.PORCENTAJE_IGV),
        limite_boleta_sin_documento=float(facturacion_viaje_service.LIMITE_BOLETA_SIN_DOCUMENTO),
        porcentaje_detraccion=float(facturacion_viaje_service.PORCENTAJE_DETRACCION),
        monto_minimo_detraccion=float(facturacion_viaje_service.MONTO_MINIMO_DETRACCION),
        cuenta_detracciones=b.cuenta_detracciones,
        puede_emitir=not b.bloqueos,
        bloqueos=b.bloqueos,
    )


@router.post("/{viaje_id}/comprobante/vista-previa", response_model=ComprobanteVistaPreviaResponse)
async def vista_previa_comprobante(
    viaje_id: uuid.UUID,
    body: EntradaComprobanteRequest,
    db: AsyncSession = Depends(get_db),
    usuario_actual: Usuario = Depends(require_roles(*_ROLES_ESCRITURA)),
):
    """Calcula base, IGV y total y muestra el comprobante tal como se enviará. No
    numera ni envía nada."""
    try:
        p = await facturacion_viaje_service.vista_previa(db, viaje_id, usuario_actual.empresa_id, _entrada_comprobante(body))
    except facturacion_viaje_service.ViajeNoEncontradoError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error))
    except facturacion_viaje_service.ComprobanteNoEmitibleError as error:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error))
    return ComprobanteVistaPreviaResponse(
        huella=p.huella(),
        puede_emitir=not p.errores,
        errores=p.errores,
        advertencias=p.advertencias,
        tipo_documento=p.tipo_documento,
        serie=p.serie,
        receptor_tipo_documento=p.receptor_tipo_documento,
        receptor_numero_documento=p.receptor_numero_documento,
        receptor_razon_social=p.receptor_razon_social,
        descripcion=p.descripcion,
        precio_incluye_igv=p.precio_incluye_igv,
        subtotal=float(p.montos.base),
        igv=float(p.montos.igv),
        total=float(p.montos.total),
        porcentaje_igv=float(p.montos.porcentaje_igv),
        detraccion_aplica=p.detraccion.aplica,
        detraccion_porcentaje=float(p.detraccion.porcentaje),
        detraccion_monto=float(p.detraccion.monto),
        neto_a_cobrar=float(p.detraccion.neto_a_cobrar),
        detraccion_nota=p.detraccion.motivo,
        detraccion_cuenta=p.detraccion.cuenta,
        guia_remision=p.guia_remision,
    )


@router.post("/{viaje_id}/comprobante/emitir", response_model=FacturaResponse)
async def emitir_comprobante(
    viaje_id: uuid.UUID,
    body: EmitirComprobanteRequest,
    db: AsyncSession = Depends(get_db),
    usuario_actual: Usuario = Depends(require_roles(*_ROLES_ESCRITURA)),
):
    """Emite la Factura/Boleta que el usuario confirmó en la vista previa (exige su
    `huella`) y la envía a SUNAT vía apisunat.pe. El comprobante se numera y se guarda
    ANTES de enviarlo: si el envío falla, queda registrado y se reintenta con
    POST /viajes/{id}/factura/emitir-sunat, nunca se emite otro número."""
    try:
        factura = await facturacion_viaje_service.registrar(
            db, viaje_id, usuario_actual.empresa_id, _entrada_comprobante(body), body.huella_vista_previa
        )
        await db.commit()
    except facturacion_viaje_service.ViajeNoEncontradoError as error:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error))
    except facturacion_viaje_service.HuellaComprobanteNoCoincideError as error:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error))
    except facturacion_viaje_service.ComprobanteNoEmitibleError as error:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error))

    etiqueta = f"{factura.serie}-{factura.numero}"
    try:
        factura = await emitir_factura(db, factura.id)
        await db.commit()
    except (DatosIncompletosError, ApiSunatFacturacionError) as error:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"El comprobante {etiqueta} quedó registrado pero no se pudo enviar a SUNAT: {error}. "
            "Reintenta el envío desde el viaje.",
        )
    await db.refresh(factura)
    return factura


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
    """Corrige los datos propios de la guía antes de emitirla: la Guía de Remisión
    Remitente del cliente (opcional) y el destinatario de la carga."""
    guia = (await db.execute(select(GuiaRemision).where(GuiaRemision.viaje_id == viaje_id))).scalar_one_or_none()
    if guia is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Este viaje no tiene guía de remisión emitida")
    if guia.estado_sunat == EstadoSunat.ACEPTADO:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="La guía ya fue aceptada por SUNAT, no se puede modificar",
        )
    if guia.estado_sunat == EstadoSunat.PENDIENTE and guia.sunat_ticket:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="La guía ya fue enviada a SUNAT y está en proceso, no se puede modificar",
        )
    for campo, valor in datos.model_dump(exclude_unset=True).items():
        setattr(guia, campo, valor or None)
    await db.commit()
    await db.refresh(guia)
    return guia


async def _guia_del_viaje_o_404(db: AsyncSession, viaje_id: uuid.UUID, empresa_id: uuid.UUID) -> GuiaRemision:
    guia = (
        await db.execute(
            select(GuiaRemision).where(GuiaRemision.viaje_id == viaje_id, GuiaRemision.empresa_id == empresa_id)
        )
    ).scalar_one_or_none()
    if guia is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Este viaje no tiene guía de remisión emitida")
    return guia


@router.post("/{viaje_id}/guia-remision/vista-previa", response_model=GuiaVistaPreviaResponse)
async def vista_previa_guia_remision(
    viaje_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    usuario_actual: Usuario = Depends(require_roles(*_ROLES_ESCRITURA)),
):
    """Muestra exactamente lo que se enviará a SUNAT (datos, validaciones y XML), sin
    enviar nada. SUNAT no tiene entorno de pruebas para GRE: esta revisión es obligatoria
    y su `huella` se exige al emitir."""
    guia = await _guia_del_viaje_o_404(db, viaje_id, usuario_actual.empresa_id)
    try:
        vista = await guia_transportista_service.vista_previa(db, guia)
    except DatosIncompletosError as error:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error))
    return GuiaVistaPreviaResponse(
        huella=vista.huella,
        proveedor=vista.proveedor,
        puede_emitir=not vista.errores,
        errores=vista.errores,
        advertencias=vista.advertencias,
        datos=jsonable_encoder(asdict(vista.datos)),
        xml=vista.xml,
    )


@router.post("/{viaje_id}/guia-remision/emitir-sunat", response_model=GuiaRemisionResponse)
async def emitir_guia_remision_a_sunat(
    viaje_id: uuid.UUID,
    body: EmitirGuiaRequest,
    db: AsyncSession = Depends(get_db),
    usuario_actual: Usuario = Depends(require_roles(*_ROLES_ESCRITURA)),
):
    """Envía a SUNAT la Guía de Remisión Transportista que el usuario revisó en la
    vista previa (exige su `huella`). Con GRE_PROVEEDOR=sunat_directo firma el XML con
    el certificado .p12 y lo envía a la API REST de GRE; con "apisunat", vía apisunat.pe."""
    guia = await _guia_del_viaje_o_404(db, viaje_id, usuario_actual.empresa_id)
    try:
        guia = await guia_transportista_service.emitir(db, guia.id, body.huella_vista_previa)
        await db.commit()
    except DatosIncompletosError as error:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error))
    except (HuellaNoCoincideError, GuiaNoEmitibleError) as error:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error))
    except (ApiSunatFacturacionError, SunatGreError) as error:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(error))
    await db.refresh(guia)
    return guia


@router.post("/{viaje_id}/guia-remision/consultar-sunat", response_model=GuiaRemisionResponse)
async def consultar_guia_remision_en_sunat(
    viaje_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    usuario_actual: Usuario = Depends(require_roles(*_ROLES_ESCRITURA)),
):
    """Consulta el ticket de una guía que quedó "en proceso" en SUNAT. Nunca reenvía."""
    guia = await _guia_del_viaje_o_404(db, viaje_id, usuario_actual.empresa_id)
    try:
        guia = await guia_transportista_service.consultar_ticket(db, guia.id)
        await db.commit()
    except GuiaNoEmitibleError as error:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error))
    except SunatGreError as error:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(error))
    await db.refresh(guia)
    return guia


@router.get("/{viaje_id}/guia-remision/xml")
async def descargar_guia_remision_xml(
    viaje_id: uuid.UUID, db: AsyncSession = Depends(get_db), usuario_actual: Usuario = Depends(get_current_user)
):
    """XML firmado tal como se envió a SUNAT (solo emisión directa)."""
    guia = await _guia_del_viaje_o_404(db, viaje_id, usuario_actual.empresa_id)
    if not guia.xml_clave:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Esta guía no tiene XML firmado guardado")
    try:
        contenido = StorageService().leer_privado(guia.xml_clave)
    except ArchivoPrivadoNoEncontradoError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No se encontró el XML firmado en el almacenamiento")
    nombre = guia.xml_clave.rsplit("/", 1)[-1]
    return Response(
        content=contenido, media_type="application/xml", headers={"Content-Disposition": f'attachment; filename="{nombre}"'}
    )


@router.get("/{viaje_id}/guia-remision/cdr")
async def descargar_guia_remision_cdr(
    viaje_id: uuid.UUID, db: AsyncSession = Depends(get_db), usuario_actual: Usuario = Depends(get_current_user)
):
    """Constancia de Recepción (CDR) que devolvió SUNAT, en el ZIP original."""
    guia = await _guia_del_viaje_o_404(db, viaje_id, usuario_actual.empresa_id)
    if not guia.cdr_clave:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Esta guía todavía no tiene CDR de SUNAT")
    try:
        contenido = StorageService().leer_privado(guia.cdr_clave)
    except ArchivoPrivadoNoEncontradoError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No se encontró el CDR en el almacenamiento")
    nombre = guia.cdr_clave.rsplit("/", 1)[-1]
    return Response(
        content=contenido, media_type="application/zip", headers={"Content-Disposition": f'attachment; filename="{nombre}"'}
    )


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
