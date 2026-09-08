from datetime import datetime

from sqlalchemy import DateTime, Enum, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPKMixin
from app.models.enums import TipoDocumentoIdentidad


class Cliente(Base, UUIDPKMixin, TimestampMixin):
    """Cliente/generador de carga. Se autocompleta vía apisunat.pe (RUC/DNI)."""

    __tablename__ = "clientes"

    tipo_documento: Mapped[TipoDocumentoIdentidad] = mapped_column(
        Enum(TipoDocumentoIdentidad, name="tipo_documento_identidad"), nullable=False
    )
    numero_documento: Mapped[str] = mapped_column(String(11), unique=True, nullable=False, index=True)
    razon_social: Mapped[str] = mapped_column(String(255), nullable=False)
    nombre_comercial: Mapped[str | None] = mapped_column(String(255))

    direccion: Mapped[str | None] = mapped_column(String(255))
    distrito: Mapped[str | None] = mapped_column(String(100))
    provincia: Mapped[str | None] = mapped_column(String(100))
    departamento: Mapped[str | None] = mapped_column(String(100))
    ubigeo: Mapped[str | None] = mapped_column(String(6))

    estado_sunat: Mapped[str | None] = mapped_column(String(50))
    condicion_sunat: Mapped[str | None] = mapped_column(String(50))

    contacto_nombre: Mapped[str | None] = mapped_column(String(150))
    contacto_telefono: Mapped[str | None] = mapped_column(String(20))
    contacto_email: Mapped[str | None] = mapped_column(String(150))

    # "apisunat.pe" cuando los datos vinieron de la API; "MANUAL" si se digitó a mano.
    fuente_datos: Mapped[str] = mapped_column(String(20), default="MANUAL", nullable=False)
    consultado_en: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
