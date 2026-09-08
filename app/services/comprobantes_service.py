import uuid
from dataclasses import dataclass
from datetime import date

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.cliente import Cliente
from app.models.comprobante import Factura, GuiaRemision
from app.models.enums import EstadoSunat, TipoDocumentoVenta
from app.models.viaje import Viaje


@dataclass
class GuiaRemisionListItem:
    id: uuid.UUID
    viaje_id: uuid.UUID
    viaje_numero: str
    serie: str
    numero: str
    cliente_razon_social: str
    fecha_emision: date
    peso_bruto_total_kg: float
    estado_sunat: EstadoSunat
    mensaje_sunat: str | None
    pdf_url: str | None


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
    fecha_emision: date
    moneda: str
    total: float
    estado_sunat: EstadoSunat
    mensaje_sunat: str | None
    pdf_url: str | None


async def listar_guias_remision(
    db: AsyncSession, *, empresa_id: uuid.UUID, estado_sunat: EstadoSunat | None = None, q: str | None = None
) -> list[GuiaRemisionListItem]:
    stmt = (
        select(GuiaRemision, Viaje, Cliente)
        .join(Viaje, Viaje.id == GuiaRemision.viaje_id)
        .join(Cliente, Cliente.id == GuiaRemision.cliente_id)
        .where(GuiaRemision.empresa_id == empresa_id)
        .order_by(GuiaRemision.fecha_emision.desc(), GuiaRemision.numero.desc())
    )
    if estado_sunat is not None:
        stmt = stmt.where(GuiaRemision.estado_sunat == estado_sunat)
    if q:
        patron = f"%{q.strip()}%"
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
            cliente_razon_social=cliente.razon_social,
            fecha_emision=guia.fecha_emision,
            peso_bruto_total_kg=float(guia.peso_bruto_total_kg),
            estado_sunat=guia.estado_sunat,
            mensaje_sunat=guia.mensaje_sunat,
            pdf_url=guia.pdf_url,
        )
        for guia, viaje, cliente in filas
    ]


async def listar_facturas(
    db: AsyncSession, *, empresa_id: uuid.UUID, estado_sunat: EstadoSunat | None = None, q: str | None = None
) -> list[FacturaListItem]:
    stmt = (
        select(Factura, Viaje, Cliente)
        .outerjoin(Viaje, Viaje.id == Factura.viaje_id)
        .join(Cliente, Cliente.id == Factura.cliente_id)
        .where(Factura.empresa_id == empresa_id)
        .order_by(Factura.fecha_emision.desc(), Factura.numero.desc())
    )
    if estado_sunat is not None:
        stmt = stmt.where(Factura.estado_sunat == estado_sunat)
    if q:
        patron = f"%{q.strip()}%"
        stmt = stmt.where(
            or_(
                Factura.numero.ilike(patron),
                Factura.serie.ilike(patron),
                Viaje.numero.ilike(patron),
                Cliente.razon_social.ilike(patron),
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
            cliente_razon_social=cliente.razon_social,
            fecha_emision=factura.fecha_emision,
            moneda=factura.moneda,
            total=float(factura.total),
            estado_sunat=factura.estado_sunat,
            mensaje_sunat=factura.mensaje_sunat,
            pdf_url=factura.pdf_url,
        )
        for factura, viaje, cliente in filas
    ]
