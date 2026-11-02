import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPKMixin
from app.models.enums import EstadoViaje, ModalidadViaje


class Viaje(Base, UUIDPKMixin, TimestampMixin):
    __tablename__ = "viajes"

    numero: Mapped[str] = mapped_column(String(20), unique=True, nullable=False, index=True)  # VJ-000123

    empresa_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("empresas.id", ondelete="RESTRICT"), nullable=False
    )
    cotizacion_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("cotizaciones.id", ondelete="SET NULL"), nullable=True, index=True
    )
    cliente_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("clientes.id", ondelete="RESTRICT"), nullable=False, index=True
    )

    modalidad: Mapped[ModalidadViaje] = mapped_column(Enum(ModalidadViaje, name="modalidad_viaje"), nullable=False)

    tracto_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tractos.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    carreta_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("carretas.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    chofer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("choferes.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    propietario_usuario_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("usuarios.id", ondelete="RESTRICT"), nullable=False
    )

    origen_direccion: Mapped[str] = mapped_column(String(255), nullable=False)
    origen_distrito: Mapped[str] = mapped_column(String(100), nullable=False)
    origen_provincia: Mapped[str] = mapped_column(String(100), nullable=False)
    origen_departamento: Mapped[str] = mapped_column(String(100), nullable=False)
    # Código UBIGEO (INEI, 6 dígitos) del punto de partida — requerido por SUNAT/apisunat.pe
    # para emitir la Guía de Remisión Transportista.
    origen_ubigeo: Mapped[str | None] = mapped_column(String(6))

    destino_direccion: Mapped[str] = mapped_column(String(255), nullable=False)
    destino_distrito: Mapped[str] = mapped_column(String(100), nullable=False)
    destino_provincia: Mapped[str] = mapped_column(String(100), nullable=False)
    destino_departamento: Mapped[str] = mapped_column(String(100), nullable=False)
    destino_ubigeo: Mapped[str | None] = mapped_column(String(6))

    peso_tm: Mapped[float] = mapped_column(Numeric(10, 3), nullable=False)

    fecha_salida_programada: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    fecha_salida_real: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    fecha_llegada_real: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    dias_viaje: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    noches_viaje: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    tarifa_diaria_chofer: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    bono_nocturno_chofer: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)

    # Ingreso neto del flete asignado a este viaje (proviene de la cotización si existe).
    ingreso_flete_neto: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)

    estado: Mapped[EstadoViaje] = mapped_column(
        Enum(EstadoViaje, name="estado_viaje"), default=EstadoViaje.PROGRAMADO, nullable=False
    )
    observaciones: Mapped[str | None] = mapped_column(Text)

    cotizacion: Mapped["Cotizacion | None"] = relationship(back_populates="viajes")
    gastos: Mapped[list["GastoViaje"]] = relationship(back_populates="viaje", cascade="all, delete-orphan")
    novedades: Mapped[list["NovedadViaje"]] = relationship(back_populates="viaje", cascade="all, delete-orphan")

    cliente: Mapped["Cliente"] = relationship(foreign_keys=[cliente_id])
    tracto: Mapped["Tracto"] = relationship(foreign_keys=[tracto_id])
    carreta: Mapped["Carreta | None"] = relationship(foreign_keys=[carreta_id])
    chofer: Mapped["Chofer"] = relationship(foreign_keys=[chofer_id])
