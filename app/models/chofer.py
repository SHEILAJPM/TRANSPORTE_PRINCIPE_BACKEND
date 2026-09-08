from datetime import date

from sqlalchemy import Boolean, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPKMixin


class Chofer(Base, UUIDPKMixin, TimestampMixin):
    __tablename__ = "choferes"

    dni: Mapped[str] = mapped_column(String(8), unique=True, nullable=False, index=True)
    nombres: Mapped[str] = mapped_column(String(150), nullable=False)
    apellidos: Mapped[str] = mapped_column(String(150), nullable=False)
    telefono: Mapped[str | None] = mapped_column(String(20))
    direccion: Mapped[str | None] = mapped_column(String(255))

    licencia_numero: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
    licencia_categoria: Mapped[str] = mapped_column(String(10), default="A-III-C", nullable=False)
    licencia_vencimiento: Mapped[date] = mapped_column(nullable=False)

    examen_medico_fecha: Mapped[date | None]
    examen_medico_vencimiento: Mapped[date | None]

    fecha_ingreso: Mapped[date | None]
    activo: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # Tarifas por defecto para la liquidación de dietas/nocturnidad (editables por viaje).
    tarifa_diaria_default: Mapped[float] = mapped_column(Numeric(10, 2), default=0, nullable=False)
    bono_nocturno_default: Mapped[float] = mapped_column(Numeric(10, 2), default=0, nullable=False)
