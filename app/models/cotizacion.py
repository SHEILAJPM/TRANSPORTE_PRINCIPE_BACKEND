import uuid
from datetime import date, datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPKMixin
from app.models.enums import EstadoCotizacion

CONDICIONES_COMERCIALES_DEFAULT = (
    "1. El cliente deberá realizar un adelanto del 50% del valor total del servicio antes de la "
    "salida de la unidad.\n"
    "2. El 50% restante deberá ser cancelado antes de proceder con la descarga en el punto de destino."
)


class Cotizacion(Base, UUIDPKMixin, TimestampMixin):
    __tablename__ = "cotizaciones"

    numero: Mapped[str] = mapped_column(String(20), unique=True, nullable=False, index=True)  # COT-000123

    empresa_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("empresas.id", ondelete="RESTRICT"), nullable=False
    )
    cliente_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("clientes.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    usuario_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("usuarios.id", ondelete="RESTRICT"), nullable=False
    )

    descripcion_servicio: Mapped[str] = mapped_column(Text, nullable=False)

    origen_direccion: Mapped[str] = mapped_column(String(255), nullable=False)
    origen_distrito: Mapped[str] = mapped_column(String(100), nullable=False)
    origen_provincia: Mapped[str] = mapped_column(String(100), nullable=False)
    origen_departamento: Mapped[str] = mapped_column(String(100), nullable=False)

    destino_direccion: Mapped[str] = mapped_column(String(255), nullable=False)
    destino_distrito: Mapped[str] = mapped_column(String(100), nullable=False)
    destino_provincia: Mapped[str] = mapped_column(String(100), nullable=False)
    destino_departamento: Mapped[str] = mapped_column(String(100), nullable=False)

    cantidad_camiones: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    peso_tm: Mapped[float] = mapped_column(Numeric(10, 3), nullable=False)

    precio_base: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    porcentaje_igv: Mapped[float] = mapped_column(Numeric(5, 2), default=18.00, nullable=False)
    monto_igv: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    precio_total: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)

    condiciones_comerciales: Mapped[str] = mapped_column(Text, default=CONDICIONES_COMERCIALES_DEFAULT, nullable=False)
    validez_dias: Mapped[int] = mapped_column(Integer, default=7, nullable=False)

    estado: Mapped[EstadoCotizacion] = mapped_column(
        Enum(EstadoCotizacion, name="estado_cotizacion"), default=EstadoCotizacion.BORRADOR, nullable=False
    )
    fecha_emision: Mapped[date] = mapped_column(nullable=False)
    convertida_en: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    viajes: Mapped[list["Viaje"]] = relationship(back_populates="cotizacion")
    cliente: Mapped["Cliente"] = relationship(foreign_keys=[cliente_id])
