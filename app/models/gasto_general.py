import uuid
from datetime import date

from sqlalchemy import Enum, ForeignKey, Numeric, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPKMixin
from app.models.enums import CategoriaGastoGeneral


class GastoGeneral(Base, UUIDPKMixin, TimestampMixin):
    """Egresos de la empresa que no están atados a un viaje (gastos_viaje) ni a un
    vehículo (mantenimientos_vehiculo): alquiler, seguros, sueldos administrativos,
    servicios, impuestos, etc. Alimenta el resumen financiero general de Reportes.
    """

    __tablename__ = "gastos_generales"

    empresa_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("empresas.id", ondelete="CASCADE"), nullable=False, index=True
    )
    registrado_por_usuario_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("usuarios.id", ondelete="RESTRICT"), nullable=False
    )

    categoria: Mapped[CategoriaGastoGeneral] = mapped_column(
        Enum(CategoriaGastoGeneral, name="categoria_gasto_general"), nullable=False
    )
    descripcion: Mapped[str] = mapped_column(Text, nullable=False)
    monto: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    fecha: Mapped[date] = mapped_column(nullable=False, index=True)
    proveedor: Mapped[str | None] = mapped_column(String(150))
    comprobante_url: Mapped[str | None] = mapped_column(String(500))
