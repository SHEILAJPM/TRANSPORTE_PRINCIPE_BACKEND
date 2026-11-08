import uuid
from datetime import date, datetime

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPKMixin
from app.models.enums import DepositanteDetraccion, EstadoSunat, TipoDocumentoVenta


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

    # Destinatario de la carga (quien la recibe). Puede diferir del cliente/remitente
    # que contrata el flete; si no se registró, se usa al cliente del viaje.
    destinatario_tipo_documento: Mapped[str | None] = mapped_column(String(1))  # Catálogo 06: "6" RUC, "1" DNI
    destinatario_numero_documento: Mapped[str | None] = mapped_column(String(15))
    destinatario_razon_social: Mapped[str | None] = mapped_column(String(250))
    # Bienes transportados: [{"descripcion", "cantidad", "unidad", "codigo"}], normalmente
    # copiados de la guía de remitente del cliente.
    bienes: Mapped[list[dict] | None] = mapped_column(JSONB)

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

    # Envío directo a la API REST de GRE de SUNAT (GRE_PROVEEDOR=sunat_directo). El XML
    # firmado y el CDR se guardan en almacenamiento privado (no en /static): solo se
    # descargan por endpoints autenticados.
    sunat_ticket: Mapped[str | None] = mapped_column(String(60))
    sunat_codigo_respuesta: Mapped[str | None] = mapped_column(String(10))
    enviado_sunat_en: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    xml_clave: Mapped[str | None] = mapped_column(String(300))
    cdr_clave: Mapped[str | None] = mapped_column(String(300))

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
    # Cómo se ingresó el precio al emitir: True = el monto escrito ya incluía IGV.
    precio_incluye_igv: Mapped[bool | None] = mapped_column(Boolean)
    # Detracción (SPOT) calculada al emitir; None si no aplica (boleta o total <= S/ 400).
    # El neto que paga el cliente directamente es total − detraccion_monto.
    detraccion_porcentaje: Mapped[float | None] = mapped_column(Numeric(5, 2))
    detraccion_monto: Mapped[float | None] = mapped_column(Numeric(12, 2))
    # Cuenta del Banco de la Nación vigente al emitir (copia de Empresa.cuenta_detracciones).
    detraccion_cuenta: Mapped[str | None] = mapped_column(String(20))
    # Depósito de la detracción (constancia del Banco de la Nación). Sin registrar = pendiente.
    detraccion_depositada_por: Mapped[DepositanteDetraccion | None] = mapped_column(
        Enum(DepositanteDetraccion, name="depositante_detraccion")
    )
    detraccion_fecha_deposito: Mapped[date | None]
    detraccion_constancia: Mapped[str | None] = mapped_column(String(30))
    detraccion_monto_depositado: Mapped[float | None] = mapped_column(Numeric(12, 2))

    # Snapshot del receptor tal como se envió a SUNAT. Puede diferir del cliente del
    # viaje (p.ej. boleta "CLIENTES VARIOS" sin documento por un monto menor a S/ 700).
    receptor_tipo_documento: Mapped[str | None] = mapped_column(String(1))  # Catálogo 06
    receptor_numero_documento: Mapped[str | None] = mapped_column(String(15))
    receptor_razon_social: Mapped[str | None] = mapped_column(String(255))
    descripcion: Mapped[str | None] = mapped_column(Text)

    estado_sunat: Mapped[EstadoSunat] = mapped_column(
        Enum(EstadoSunat, name="estado_sunat"), default=EstadoSunat.PENDIENTE, nullable=False
    )
    hash_cpe: Mapped[str | None] = mapped_column(String(255))
    xml_url: Mapped[str | None] = mapped_column(String(500))
    cdr_url: Mapped[str | None] = mapped_column(String(500))
    pdf_url: Mapped[str | None] = mapped_column(String(500))
    mensaje_sunat: Mapped[str | None] = mapped_column(String(500))
    # Se marca justo antes de llamar a apisunat.pe: un comprobante con esta marca pudo
    # haber llegado a SUNAT y ya no puede descartarse ni renumerarse.
    enviado_en: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (UniqueConstraint("serie", "numero", name="uq_factura_serie_numero"),)
