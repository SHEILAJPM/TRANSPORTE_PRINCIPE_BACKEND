from datetime import date

from sqlalchemy import Enum, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPKMixin
from app.models.enums import EstadoVehiculo, TipoCarreta


class DimensionesVehicularesMixin:
    """Dimensiones físicas y peso bruto vehicular según Anexo IV del RNV (DS 058-2003-MTC).

    Valores predeterminados por configuración vehicular pero editables por unidad,
    ya que cada fabricante/modelo puede variar dentro del límite normativo.
    """

    largo_m: Mapped[float] = mapped_column(Numeric(5, 2), nullable=False)
    ancho_m: Mapped[float] = mapped_column(Numeric(5, 2), nullable=False)
    alto_m: Mapped[float] = mapped_column(Numeric(5, 2), nullable=False)
    # Configuración vehicular normativa: C-2, C-3, C-4, T2S1, T2S2, T2S3, T3S1, T3S2, T3S3, etc.
    configuracion_vehicular: Mapped[str] = mapped_column(String(10), nullable=False)
    numero_ejes: Mapped[int | None] = mapped_column(Integer)
    tara_kg: Mapped[float | None] = mapped_column(Numeric(10, 2))
    # Peso Bruto Vehicular máximo permitido para la configuración (Anexo IV RNV).
    peso_bruto_max_kg: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    # Tarjeta Única de Circulación (TUC) del MTC — se envía en cada Guía de Remisión
    # Transportista a apisunat.pe/SUNAT.
    tarjeta_unica_circulacion: Mapped[str | None] = mapped_column(String(30))


class Tracto(Base, UUIDPKMixin, TimestampMixin, DimensionesVehicularesMixin):
    __tablename__ = "tractos"

    placa: Mapped[str] = mapped_column(String(10), unique=True, nullable=False, index=True)
    marca: Mapped[str] = mapped_column(String(100), nullable=False)
    modelo: Mapped[str | None] = mapped_column(String(100))
    anio_fabricacion: Mapped[int | None] = mapped_column(Integer)
    numero_motor: Mapped[str | None] = mapped_column(String(50))
    numero_chasis: Mapped[str | None] = mapped_column(String(50))

    kilometraje_actual: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    estado: Mapped[EstadoVehiculo] = mapped_column(
        Enum(EstadoVehiculo, name="estado_vehiculo"), default=EstadoVehiculo.OPERATIVO, nullable=False
    )

    soat_vencimiento: Mapped[date | None]
    citv_vencimiento: Mapped[date | None]  # Revisión Técnica (CITV)
    mtc_habilitacion_vencimiento: Mapped[date | None]  # Certificado de Habilitación Vehicular MTC

    tarjeta_propiedad_url: Mapped[str | None] = mapped_column(String(500))


class Carreta(Base, UUIDPKMixin, TimestampMixin, DimensionesVehicularesMixin):
    __tablename__ = "carretas"

    placa: Mapped[str] = mapped_column(String(10), unique=True, nullable=False, index=True)
    tipo_carreta: Mapped[TipoCarreta] = mapped_column(Enum(TipoCarreta, name="tipo_carreta"), nullable=False)
    marca: Mapped[str | None] = mapped_column(String(100))
    modelo: Mapped[str | None] = mapped_column(String(100))
    anio_fabricacion: Mapped[int | None] = mapped_column(Integer)

    kilometraje_actual: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    estado: Mapped[EstadoVehiculo] = mapped_column(
        Enum(EstadoVehiculo, name="estado_vehiculo"), default=EstadoVehiculo.OPERATIVO, nullable=False
    )

    soat_vencimiento: Mapped[date | None]
    citv_vencimiento: Mapped[date | None]
    mtc_habilitacion_vencimiento: Mapped[date | None]

    tarjeta_propiedad_url: Mapped[str | None] = mapped_column(String(500))
