import uuid
from datetime import date

from sqlalchemy import Enum, ForeignKey, Integer, Numeric, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPKMixin
from app.models.enums import EstadoLiquidacion


class LiquidacionChofer(Base, UUIDPKMixin, TimestampMixin):
    """Liquidación de dietas/nocturnidad y rendición de gastos de un viaje.

    Ver app/services/liquidacion_service.py para la fórmula exacta de cálculo.
    """

    __tablename__ = "liquidaciones_chofer"

    viaje_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("viajes.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    chofer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("choferes.id", ondelete="RESTRICT"), nullable=False, index=True
    )

    dias_viaje: Mapped[int] = mapped_column(Integer, nullable=False)
    noches_viaje: Mapped[int] = mapped_column(Integer, nullable=False)
    tarifa_diaria: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    bono_nocturno: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    monto_dietas: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)

    total_adelantos_recibidos: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    total_gastos_operativos: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    saldo_rendicion_cuentas: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    neto_a_pagar_chofer: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)

    estado: Mapped[EstadoLiquidacion] = mapped_column(
        Enum(EstadoLiquidacion, name="estado_liquidacion"), default=EstadoLiquidacion.PENDIENTE, nullable=False
    )
    fecha_liquidacion: Mapped[date | None]
    observaciones: Mapped[str | None] = mapped_column(Text)
