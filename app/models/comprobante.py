import uuid
from datetime import date

from sqlalchemy import Enum, ForeignKey, Integer, Numeric, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPKMixin
from app.models.enums import EstadoSunat, TipoDocumentoVenta


class GuiaRemision(Base, UUIDPKMixin, TimestampMixin):
    """Guía de Remisión Electrónica (GRE) del remitente/transportista."""

    __tablename__ = "guias_remision"

    empresa_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("empresas.id", ondelete="RESTRICT"), nullable=False
    )
    viaje_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("viajes.id", ondelete="RESTRICT"), nullable=False, unique=True, index=True
    )
    cotizacion_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("cotizaciones.id", ondelete="SET NULL"), nullable=True
    )
    cliente_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("clientes.id", ondelete="RESTRICT"), nullable=False
    )

    serie: Mapped[str] = mapped_column(String(4), nullable=False)
    numero: Mapped[str] = mapped_column(String(8), nullable=False)
    fecha_emision: Mapped[date] = mapped_column(nullable=False)
    motivo_traslado: Mapped[str] = mapped_column(String(100), default="VENTA", nullable=False)
    peso_bruto_total_kg: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    numero_bultos: Mapped[int | None] = mapped_column(Integer)
    modalidad_transporte: Mapped[str] = mapped_column(String(50), default="TRANSPORTE_PUBLICO", nullable=False)

    # Referencia opcional a la Guía de Remisión Remitente que el propio cliente (dueño
    # de la carga) ya generó por su cuenta en SUNAT antes del viaje. Cuando el cliente
    # la provee, se envía en "documentos_relacionados" al emitir esta guía transportista.
    remitente_guia_ruc_emisor: Mapped[str | None] = mapped_column(String(11))
    remitente_guia_serie: Mapped[str | None] = mapped_column(String(4))
    remitente_guia_numero: Mapped[str | None] = mapped_column(String(8))

    estado_sunat: Mapped[EstadoSunat] = mapped_column(
        Enum(EstadoSunat, name="estado_sunat"), default=EstadoSunat.PENDIENTE, nullable=False
    )
    hash_cpe: Mapped[str | None] = mapped_column(String(255))
    xml_url: Mapped[str | None] = mapped_column(String(500))
    cdr_url: Mapped[str | None] = mapped_column(String(500))
    # PDF oficial (A4) generado por apisunat.pe/SUNAT al emitir — distinto del PDF
    # interno que genera el propio sistema con el logo de la empresa.
    pdf_url: Mapped[str | None] = mapped_column(String(500))
    mensaje_sunat: Mapped[str | None] = mapped_column(String(500))

    constancia_pesos_medidas: Mapped["ConstanciaPesosMedidas | None"] = relationship(
        back_populates="guia_remision", uselist=False
    )

    __table_args__ = (UniqueConstraint("serie", "numero", name="uq_guia_remision_serie_numero"),)


class Factura(Base, UUIDPKMixin, TimestampMixin):
    __tablename__ = "facturas"

    empresa_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("empresas.id", ondelete="RESTRICT"), nullable=False
    )
    viaje_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("viajes.id", ondelete="SET NULL"), nullable=True, index=True
    )
    cotizacion_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("cotizaciones.id", ondelete="SET NULL"), nullable=True
    )
    cliente_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("clientes.id", ondelete="RESTRICT"), nullable=False
    )
    guia_remision_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("guias_remision.id", ondelete="SET NULL"), nullable=True
    )
    # Solo aplica cuando tipo_documento es NOTA_CREDITO: la Factura/Boleta que esta
    # nota anula (SUNAT exige que la nota de crédito referencie el documento original).
    documento_afectado_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("facturas.id", ondelete="SET NULL"), nullable=True
    )

    tipo_documento: Mapped[TipoDocumentoVenta] = mapped_column(
        Enum(TipoDocumentoVenta, name="tipo_documento_venta"), default=TipoDocumentoVenta.FACTURA, nullable=False
    )
    serie: Mapped[str] = mapped_column(String(4), nullable=False)
    numero: Mapped[str] = mapped_column(String(8), nullable=False)
    fecha_emision: Mapped[date] = mapped_column(nullable=False)
    moneda: Mapped[str] = mapped_column(String(3), default="PEN", nullable=False)

    subtotal: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    igv: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    total: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)

    estado_sunat: Mapped[EstadoSunat] = mapped_column(
        Enum(EstadoSunat, name="estado_sunat"), default=EstadoSunat.PENDIENTE, nullable=False
    )
    hash_cpe: Mapped[str | None] = mapped_column(String(255))
    xml_url: Mapped[str | None] = mapped_column(String(500))
    cdr_url: Mapped[str | None] = mapped_column(String(500))
    pdf_url: Mapped[str | None] = mapped_column(String(500))
    mensaje_sunat: Mapped[str | None] = mapped_column(String(500))

    __table_args__ = (UniqueConstraint("serie", "numero", name="uq_factura_serie_numero"),)
