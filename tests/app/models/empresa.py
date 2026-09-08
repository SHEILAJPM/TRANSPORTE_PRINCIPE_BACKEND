import uuid
from datetime import datetime

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from TRANSPORTE_PRINCIPE_BACKEND.tests.app.models.base import Base, TimestampMixin, UUIDPKMixin


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
    logo_actualizado_en: Mapped[datetime | None]

    serie_factura_default: Mapped[str | None] = mapped_column(String(4))
    serie_guia_remision_default: Mapped[str | None] = mapped_column(String(4))

    # Token bearer de apisunat.pe asociado a esta empresa (se recomienda cifrar en reposo).
    apisunat_token: Mapped[str | None] = mapped_column(String(500))

    usuarios: Mapped[list["Usuario"]] = relationship(back_populates="empresa")
