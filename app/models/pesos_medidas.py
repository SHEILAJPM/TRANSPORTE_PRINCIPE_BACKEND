import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Numeric, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPKMixin


class ConstanciaPesosMedidas(Base, UUIDPKMixin, TimestampMixin):
    """Constancia de Verificación de Pesos y Medidas (DS N.º 058-2003-MTC).

    Vinculada 1:1 al número de serie de la Guía de Remisión. Las dimensiones y el peso
    bruto máximo se copian (snapshot) del tracto/carreta asignados al momento de emitir
    la constancia, ya que la unidad podría cambiar sus datos técnicos más adelante; el
    peso bruto y la tara reales se llenan en balanza y quedan editables manualmente.
    """

    __tablename__ = "constancias_pesos_medidas"

    numero: Mapped[str] = mapped_column(String(20), unique=True, nullable=False, index=True)  # CPM-000123

    empresa_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("empresas.id", ondelete="RESTRICT"), nullable=False
    )
    guia_remision_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("guias_remision.id", ondelete="RESTRICT"), nullable=False, unique=True
    )
    viaje_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("viajes.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    tracto_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tractos.id", ondelete="RESTRICT"), nullable=False
    )
    carreta_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("carretas.id", ondelete="RESTRICT"), nullable=True
    )
    chofer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("choferes.id", ondelete="RESTRICT"), nullable=False
    )
    generador_carga_cliente_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("clientes.id", ondelete="RESTRICT"), nullable=False
    )

    tipo_control: Mapped[str] = mapped_column(String(30), default="BALANZA", nullable=False)
    lugar_verificacion: Mapped[str | None] = mapped_column(String(150))
    fecha_verificacion: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    peso_bruto_kg: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    tara_kg: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    peso_neto_kg: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)  # peso_bruto_kg - tara_kg

    precinto_seguridad: Mapped[str | None] = mapped_column(String(50))
    numero_licencia_chofer: Mapped[str] = mapped_column(String(20), nullable=False)

    # Snapshot editable de las dimensiones/configuración del tracto+carreta al momento de emitir.
    largo_m: Mapped[float] = mapped_column(Numeric(5, 2), nullable=False)
    ancho_m: Mapped[float] = mapped_column(Numeric(5, 2), nullable=False)
    alto_m: Mapped[float] = mapped_column(Numeric(5, 2), nullable=False)
    configuracion_vehicular: Mapped[str] = mapped_column(String(10), nullable=False)
    peso_bruto_max_kg: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)

    observaciones: Mapped[str | None] = mapped_column(Text)

    guia_remision: Mapped["GuiaRemision"] = relationship(back_populates="constancia_pesos_medidas")
