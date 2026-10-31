from sqlalchemy import LargeBinary, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPKMixin


class ArchivoPrivado(Base, UUIDPKMixin, TimestampMixin):
    """XML firmado y CDR de SUNAT. Van en la base de datos y no en el disco del
    servidor: en el plan gratuito de Render el disco se borra en cada despliegue, y
    SUNAT exige conservarlos. Solo se descargan por endpoints autenticados."""

    __tablename__ = "archivos_privados"

    clave: Mapped[str] = mapped_column(String(300), unique=True, nullable=False, index=True)
    contenido: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    content_type: Mapped[str] = mapped_column(String(100), nullable=False)
