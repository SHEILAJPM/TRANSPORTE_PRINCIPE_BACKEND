import uuid
from datetime import datetime

from sqlalchemy import DateTime, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPKMixin


class Empresa(Base, UUIDPKMixin, TimestampMixin):
    """Datos fiscales propios de la empresa de transporte (Transporte Príncipe)."""

    __tablename__ = "empresas"

    ruc: Mapped[str] = mapped_column(String(11), unique=True, nullable=False, index=True)
    razon_social: Mapped[str] = mapped_column(String(255), nullable=False)
    nombre_comercial: Mapped[str | None] = mapped_column(String(255))
    direccion_fiscal: Mapped[str | None] = mapped_column(String(255))
    distrito: Mapped[str | None] = mapped_column(String(100))
    provincia: Mapped[str | None] = mapped_column(String(100))
    departamento: Mapped[str | None] = mapped_column(String(100))
    telefono: Mapped[str | None] = mapped_column(String(20))
    email: Mapped[str | None] = mapped_column(String(150))

    logo_url: Mapped[str | None] = mapped_column(String(500))
    logo_actualizado_en: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    serie_factura_default: Mapped[str | None] = mapped_column(String(4))
    serie_guia_remision_default: Mapped[str | None] = mapped_column(String(4))

    # N.° de Registro/Constancia de Habilitación Vehicular del transportista ante el
    # MTC (se envía en cada Guía de Remisión Transportista a apisunat.pe/SUNAT).
    numero_registro_mtc: Mapped[str | None] = mapped_column(String(30))

    # Cuenta de detracciones (SPOT) en el Banco de la Nación: se imprime en cada factura
    # sujeta a detracción para que el cliente sepa dónde depositar.
    cuenta_detracciones: Mapped[str | None] = mapped_column(String(20))

    # Token bearer de apisunat.pe asociado a esta empresa (se recomienda cifrar en reposo).
    apisunat_token: Mapped[str | None] = mapped_column(String(500))

    usuarios: Mapped[list["Usuario"]] = relationship(back_populates="empresa")
