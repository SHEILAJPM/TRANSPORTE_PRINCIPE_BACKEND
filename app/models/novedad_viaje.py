import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Numeric, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPKMixin


class NovedadViaje(Base, UUIDPKMixin, TimestampMixin):
    """Incidencias reportadas por el chofer en ruta (avería, demora, siniestro, etc.)."""

    __tablename__ = "novedades_viaje"

    viaje_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("viajes.id", ondelete="CASCADE"), nullable=False, index=True
    )

    tipo_novedad: Mapped[str] = mapped_column(String(50), nullable=False)
    descripcion: Mapped[str] = mapped_column(Text, nullable=False)
    fecha: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    latitud: Mapped[float | None] = mapped_column(Numeric(9, 6))
    longitud: Mapped[float | None] = mapped_column(Numeric(9, 6))
    foto_url: Mapped[str | None] = mapped_column(String(500))
    resuelto: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    uuid_dispositivo: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    sincronizado: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    viaje: Mapped["Viaje"] = relationship(back_populates="novedades")

    __table_args__ = (UniqueConstraint("uuid_dispositivo", name="uq_novedad_uuid_dispositivo"),)
