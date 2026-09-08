import uuid
from datetime import datetime

from sqlalchemy import Boolean, Enum, ForeignKey, Numeric, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPKMixin
from app.models.enums import TipoGastoViaje


class GastoViaje(Base, UUIDPKMixin, TimestampMixin):
    """Combustible, peajes, viáticos y adelantos registrados por el chofer (con soporte offline)."""

    __tablename__ = "gastos_viaje"

    viaje_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("viajes.id", ondelete="CASCADE"), nullable=False, index=True
    )
    registrado_por_chofer_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("choferes.id", ondelete="SET NULL"), nullable=True
    )

    tipo_gasto: Mapped[TipoGastoViaje] = mapped_column(Enum(TipoGastoViaje, name="tipo_gasto_viaje"), nullable=False)
    monto: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    fecha: Mapped[datetime] = mapped_column(nullable=False)

    # Campos específicos de combustible.
    galones: Mapped[float | None] = mapped_column(Numeric(8, 3))
    grifo_nombre: Mapped[str | None] = mapped_column(String(150))
    numero_ticket: Mapped[str | None] = mapped_column(String(50))

    descripcion: Mapped[str | None] = mapped_column(Text)
    comprobante_url: Mapped[str | None] = mapped_column(String(500))

    # Sincronización offline desde la app móvil del chofer.
    uuid_dispositivo: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    sincronizado: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    fecha_sincronizacion: Mapped[datetime | None]

    viaje: Mapped["Viaje"] = relationship(back_populates="gastos")

    __table_args__ = (UniqueConstraint("uuid_dispositivo", name="uq_gasto_uuid_dispositivo"),)
