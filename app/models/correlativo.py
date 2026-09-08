from sqlalchemy import Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPKMixin


class Correlativo(Base, UUIDPKMixin, TimestampMixin):
    """Contador atómico por tipo de documento (+ serie opcional) para numerar
    cotizaciones, viajes, guías, facturas y constancias sin colisiones concurrentes.
    """

    __tablename__ = "correlativos"

    tipo: Mapped[str] = mapped_column(String(30), nullable=False)
    serie: Mapped[str | None] = mapped_column(String(4), nullable=True)
    ultimo_numero: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    __table_args__ = (UniqueConstraint("tipo", "serie", name="uq_correlativo_tipo_serie"),)
