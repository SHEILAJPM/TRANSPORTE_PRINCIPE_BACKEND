import uuid
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.models.chofer import Chofer
from app.models.cliente import Cliente
from app.models.comprobante import Factura, GuiaRemision
from app.models.enums import EstadoSunat, EstadoViaje, TipoDocumentoVenta
from app.models.flota import Carreta, Tracto
from app.models.viaje import Viaje
from app.services.facturacion_viaje_service import ESTADOS_VIAJE_FACTURABLES, comprobante_bloquea_nueva_emision


@dataclass
class FiltrosComprobantes:
    """Filtros comunes de los listados de Guías y de Facturas/Boletas."""

    desde: date | None = None
    hasta: date | None = None
    cliente_id: uuid.UUID | None = None
    placa: str | None = None
    chofer_id: uuid.UUID | None = None
    estado_sunat: EstadoSunat | None = None
    tipo_documento: TipoDocumentoVenta | None = None
    q: str | None = None


@dataclass
class GuiaRemisionListItem:
    id: uuid.UUID
    viaje_id: uuid.UUID
    viaje_numero: str
    serie: str
    numero: str
    cliente_id: uuid.UUID
    cliente_razon_social: str
    destinatario_razon_social: str | None
    tracto_placa: str | None
    carreta_placa: str | None
    chofer_nombre: str | None
    fecha_emision: date
    peso_bruto_total_kg: float
    estado_sunat: EstadoSunat
    mensaje_sunat: str | None
    pdf_url: str | None
    xml_firmado_disponible: bool
    cdr_disponible: bool


@dataclass
class FacturaListItem:
    id: uuid.UUID
    viaje_id: uuid.UUID | None
    viaje_numero: str | None
    documento_afectado_id: uuid.UUID | None
    tipo_documento: TipoDocumentoVenta
    serie: str
    numero: str
    cliente_razon_social: str
    tracto_placa: str | None
    chofer_nombre: str | None
    guia_remision: str | None
    fecha_emision: date
    moneda: str
    subtotal: float
    igv: float
    total: float
    detraccion_monto: float | None
    estado_sunat: EstadoSunat
    mensaje_sunat: str | None
    pdf_url: str | None
    xml_url: str | None
    cdr_url: str | None


@dataclass
class TotalesFacturacion:
    """Solo comprobantes ACEPTADOS por SUNAT; las Notas de Crédito restan."""

    cantidad: int
    base: float
    igv: float
    total: float
    detracciones: float


@dataclass
class ViajeFacturable:
    viaje_id: uuid.UUID
    viaje_numero: str
    cliente_razon_social: str
    origen_distrito: str
    destino_distrito: str
    fecha_salida_programada: datetime
    estado_viaje: EstadoViaje
    guia_remision: str | None
    guia_estado_sunat: EstadoSunat | None


def _nombre_chofer(chofer: Chofer | None) -> str | None:
    return f"{chofer.nombres} {chofer.apellidos}" if chofer else None


def _filtrar(stmt, filtros: FiltrosComprobantes, *, fecha, cliente_id, tracto, carreta):
    if filtros.desde:
        stmt = stmt.where(fecha >= filtros.desde)
    if filtros.hasta:
        stmt = stmt.where(fecha <= filtros.hasta)
    if filtros.cliente_id:
        stmt = stmt.where(cliente_id == filtros.cliente_id)
    if filtros.chofer_id:
        stmt = stmt.where(Viaje.chofer_id == filtros.chofer_id)
    if filtros.placa and filtros.placa.strip():
        patron = f"%{filtros.placa.strip()}%"
        stmt = stmt.where(or_(tracto.placa.ilike(patron), carreta.placa.ilike(patron)))
    return stmt


async def listar_guias_remision(
    db: AsyncSession, *, empresa_id: uuid.UUID, filtros: FiltrosComprobantes | None = None
) -> list[GuiaRemisionListItem]:
    filtros = filtros or FiltrosComprobantes()
    tracto, carreta = aliased(Tracto), aliased(Carreta)
    stmt = (
        select(GuiaRemision, Viaje, Cliente, tracto, carreta, Chofer)
        .join(Viaje, Viaje.id == GuiaRemision.viaje_id)
        .join(Cliente, Cliente.id == GuiaRemision.cliente_id)
        .outerjoin(tracto, tracto.id == Viaje.tracto_id)
        .outerjoin(carreta, carreta.id == Viaje.carreta_id)
        .outerjoin(Chofer, Chofer.id == Viaje.chofer_id)
        .where(GuiaRemision.empresa_id == empresa_id)
        .order_by(GuiaRemision.fecha_emision.desc(), GuiaRemision.numero.desc())
    )
    stmt = _filtrar(stmt, filtros, fecha=GuiaRemision.fecha_emision, cliente_id=GuiaRemision.cliente_id, tracto=tracto, carreta=carreta)
    if filtros.estado_sunat is not None:
        stmt = stmt.where(GuiaRemision.estado_sunat == filtros.estado_sunat)
    if filtros.q:
        patron = f"%{filtros.q.strip()}%"
        stmt = stmt.where(
            or_(
                GuiaRemision.numero.ilike(patron),
                GuiaRemision.serie.ilike(patron),
                Viaje.numero.ilike(patron),
                Cliente.razon_social.ilike(patron),
            )
        )

    filas = (await db.execute(stmt)).all()
    return [
        GuiaRemisionListItem(
            id=guia.id,
            viaje_id=guia.viaje_id,
            viaje_numero=viaje.numero,
            serie=guia.serie,
            numero=guia.numero,
            cliente_id=cliente.id,
            cliente_razon_social=cliente.razon_social,
            destinatario_razon_social=guia.destinatario_razon_social,
            tracto_placa=t.placa if t else None,
            carreta_placa=c.placa if c else None,
            chofer_nombre=_nombre_chofer(chofer),
            fecha_emision=guia.fecha_emision,
            peso_bruto_total_kg=float(guia.peso_bruto_total_kg),
            estado_sunat=guia.estado_sunat,
            mensaje_sunat=guia.mensaje_sunat,
            pdf_url=guia.pdf_url,
            xml_firmado_disponible=guia.xml_clave is not None,
            cdr_disponible=guia.cdr_clave is not None,
        )
        for guia, viaje, cliente, t, c, chofer in filas
    ]


async def listar_facturas(
    db: AsyncSession, *, empresa_id: uuid.UUID, filtros: FiltrosComprobantes | None = None
) -> list[FacturaListItem]:
    filtros = filtros or FiltrosComprobantes()
    tracto, carreta = aliased(Tracto), aliased(Carreta)
    stmt = (
        select(Factura, Viaje, Cliente, tracto, carreta, Chofer, GuiaRemision)
        .outerjoin(Viaje, Viaje.id == Factura.viaje_id)
        .join(Cliente, Cliente.id == Factura.cliente_id)
        .outerjoin(tracto, tracto.id == Viaje.tracto_id)
        .outerjoin(carreta, carreta.id == Viaje.carreta_id)
        .outerjoin(Chofer, Chofer.id == Viaje.chofer_id)
        .outerjoin(GuiaRemision, GuiaRemision.id == Factura.guia_remision_id)
        .where(Factura.empresa_id == empresa_id)
        .order_by(Factura.fecha_emision.desc(), Factura.numero.desc())
    )
    stmt = _filtrar(stmt, filtros, fecha=Factura.fecha_emision, cliente_id=Factura.cliente_id, tracto=tracto, carreta=carreta)
    if filtros.estado_sunat is not None:
        stmt = stmt.where(Factura.estado_sunat == filtros.estado_sunat)
    if filtros.tipo_documento is not None:
        stmt = stmt.where(Factura.tipo_documento == filtros.tipo_documento)
    if filtros.q:
        patron = f"%{filtros.q.strip()}%"
        stmt = stmt.where(
            or_(
                Factura.numero.ilike(patron),
                Factura.serie.ilike(patron),
                Viaje.numero.ilike(patron),
                Cliente.razon_social.ilike(patron),
                Factura.receptor_razon_social.ilike(patron),
            )
        )

    filas = (await db.execute(stmt)).all()
    return [
        FacturaListItem(
            id=factura.id,
            viaje_id=factura.viaje_id,
            viaje_numero=viaje.numero if viaje else None,
            documento_afectado_id=factura.documento_afectado_id,
            tipo_documento=factura.tipo_documento,
            serie=factura.serie,
            numero=factura.numero,
            cliente_razon_social=factura.receptor_razon_social or cliente.razon_social,
            tracto_placa=t.placa if t else None,
            chofer_nombre=_nombre_chofer(chofer),
            guia_remision=f"{guia.serie}-{guia.numero}" if guia else None,
            fecha_emision=factura.fecha_emision,
            moneda=factura.moneda,
            subtotal=float(factura.subtotal),
            igv=float(factura.igv),
            total=float(factura.total),
            detraccion_monto=float(factura.detraccion_monto) if factura.detraccion_monto is not None else None,
            estado_sunat=factura.estado_sunat,
            mensaje_sunat=factura.mensaje_sunat,
            pdf_url=factura.pdf_url,
            xml_url=factura.xml_url,
            cdr_url=factura.cdr_url,
        )
        for factura, viaje, cliente, t, c, chofer, guia in filas
    ]


def totalizar(facturas: list[FacturaListItem]) -> TotalesFacturacion:
    base = igv = total = detracciones = Decimal(0)
    cantidad = 0
    for f in facturas:
        if f.estado_sunat != EstadoSunat.ACEPTADO:
            continue
        signo = -1 if f.tipo_documento == TipoDocumentoVenta.NOTA_CREDITO else 1
        base += signo * Decimal(str(f.subtotal))
        igv += signo * Decimal(str(f.igv))
        total += signo * Decimal(str(f.total))
        detracciones += signo * Decimal(str(f.detraccion_monto or 0))
        cantidad += 1
    return TotalesFacturacion(
        cantidad=cantidad, base=float(base), igv=float(igv), total=float(total), detracciones=float(detracciones)
    )


async def listar_facturables(db: AsyncSession, *, empresa_id: uuid.UUID) -> list[ViajeFacturable]:
    """Viajes listos para emitir su Factura/Boleta ("Nueva factura"): terminados o con
    la guía ya aceptada por SUNAT, y sin un comprobante aceptado o enviado en proceso."""
    stmt = (
        select(Viaje, Cliente, GuiaRemision)
        .join(Cliente, Cliente.id == Viaje.cliente_id)
        .outerjoin(GuiaRemision, GuiaRemision.viaje_id == Viaje.id)
        .where(
            Viaje.empresa_id == empresa_id,
            Viaje.estado != EstadoViaje.CANCELADO,
            or_(Viaje.estado.in_(ESTADOS_VIAJE_FACTURABLES), GuiaRemision.estado_sunat == EstadoSunat.ACEPTADO),
        )
        .order_by(Viaje.fecha_salida_programada.desc())
    )
    filas = (await db.execute(stmt)).all()
    if not filas:
        return []

    comprobantes = (
        await db.execute(
            select(Factura).where(
                Factura.viaje_id.in_([v.id for v, _, _ in filas]),
                Factura.tipo_documento.in_((TipoDocumentoVenta.FACTURA, TipoDocumentoVenta.BOLETA)),
            )
        )
    ).scalars()
    bloqueados = {f.viaje_id for f in comprobantes if comprobante_bloquea_nueva_emision(f)}

    return [
        ViajeFacturable(
            viaje_id=viaje.id,
            viaje_numero=viaje.numero,
            cliente_razon_social=cliente.razon_social,
            origen_distrito=viaje.origen_distrito,
            destino_distrito=viaje.destino_distrito,
            fecha_salida_programada=viaje.fecha_salida_programada,
            estado_viaje=viaje.estado,
            guia_remision=f"{guia.serie}-{guia.numero}" if guia else None,
            guia_estado_sunat=guia.estado_sunat if guia else None,
        )
        for viaje, cliente, guia in filas
        if viaje.id not in bloqueados
    ]
