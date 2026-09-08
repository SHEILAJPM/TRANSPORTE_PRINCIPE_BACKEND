import uuid
from datetime import date

from sqlalchemy import Boolean, CheckConstraint, Enum, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPKMixin
from app.models.enums import TipoMantenimiento


class MantenimientoVehiculo(Base, UUIDPKMixin, TimestampMixin):
    """Mantenimiento preventivo/correctivo por kilometraje, para tracto o carreta (nunca ambos)."""

    __tablename__ = "mantenimientos_vehiculo"

    tracto_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tractos.id", ondelete="CASCADE"), nullable=True, index=True
    )
    carreta_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("carretas.id", ondelete="CASCADE"), nullable=True, index=True
    )

    tipo_mantenimiento: Mapped[TipoMantenimiento] = mapped_column(
        Enum(TipoMantenimiento, name="tipo_mantenimiento"), nullable=False
    )
    descripcion: Mapped[str] = mapped_column(Text, nullable=False)
    kilometraje_actual_registro: Mapped[int] = mapped_column(Integer, nullable=False)
    kilometraje_proximo: Mapped[int | None] = mapped_column(Integer)
    fecha_realizado: Mapped[date] = mapped_column(nullable=False)
    costo: Mapped[float | None] = mapped_column(Numeric(10, 2))
    proveedor: Mapped[str | None] = mapped_column(String(150))
    completado: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    __table_args__ = (
        CheckConstraint(
            "(tracto_id IS NOT NULL AND carreta_id IS NULL) OR (tracto_id IS NULL AND carreta_id IS NOT NULL)",
            name="ck_mantenimiento_un_solo_vehiculo",
        ),
    )
