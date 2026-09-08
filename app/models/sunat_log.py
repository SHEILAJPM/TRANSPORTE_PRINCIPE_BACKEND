import uuid

from sqlalchemy import Boolean, Enum, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPKMixin
from app.models.enums import TipoDocumentoIdentidad


class ConsultaSunatLog(Base, UUIDPKMixin, TimestampMixin):
    """Auditoría de cada consulta a apisunat.pe (éxito/error, payload de respuesta)."""

    __tablename__ = "consultas_sunat_log"

    usuario_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("usuarios.id", ondelete="SET NULL"), nullable=True
    )
    tipo_documento: Mapped[TipoDocumentoIdentidad] = mapped_column(
        Enum(TipoDocumentoIdentidad, name="tipo_documento_identidad"), nullable=False
    )
    numero_documento: Mapped[str] = mapped_column(String(11), nullable=False, index=True)
    exitosa: Mapped[bool] = mapped_column(Boolean, nullable=False)
    respuesta_json: Mapped[dict | None] = mapped_column(JSONB)
    mensaje_error: Mapped[str | None] = mapped_column(Text)
