"""Certificado digital (.p12) con el que se firman los documentos enviados directo
a SUNAT. La ruta y la contraseña llegan solo por variables de entorno
(SUNAT_CERT_PATH / SUNAT_CERT_PASSWORD); en Render la ruta apunta al Secret File
montado en /etc/secrets/."""

from dataclasses import dataclass
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives.asymmetric.types import PrivateKeyTypes
from cryptography.hazmat.primitives.serialization import pkcs12

from app.core.config import settings


class CertificadoSunatError(Exception):
    """El certificado no está configurado, no existe, no se puede abrir o está vencido."""


@dataclass(frozen=True)
class CertificadoSunat:
    clave_privada: PrivateKeyTypes
    certificado: x509.Certificate
    cadena: tuple[x509.Certificate, ...]

    @property
    def titular(self) -> str:
        return self.certificado.subject.rfc4514_string()

    @property
    def vence_en(self) -> datetime:
        return self.certificado.not_valid_after_utc


@lru_cache(maxsize=4)
def _abrir_p12(ruta: Path, modificado_ns: int, contrasena: str) -> CertificadoSunat:
    # `modificado_ns` forma parte de la clave de caché: si se reemplaza el archivo
    # (p.ej. renovación del certificado) se vuelve a leer sin reiniciar el backend.
    try:
        contenido = ruta.read_bytes()
    except OSError as error:
        raise CertificadoSunatError(f"No se pudo leer el certificado digital en {ruta}: {error.strerror}") from error

    try:
        clave_privada, certificado, cadena = pkcs12.load_key_and_certificates(contenido, contrasena.encode())
    except ValueError as error:
        raise CertificadoSunatError(
            "No se pudo abrir el certificado digital: la contraseña (SUNAT_CERT_PASSWORD) es incorrecta "
            "o el archivo no es un .p12 válido"
        ) from error

    if clave_privada is None or certificado is None:
        raise CertificadoSunatError(
            "El archivo .p12 no contiene la clave privada y el certificado necesarios para firmar"
        )

    return CertificadoSunat(clave_privada=clave_privada, certificado=certificado, cadena=tuple(cadena))


def cargar_certificado() -> CertificadoSunat:
    """Devuelve el certificado listo para firmar, o lanza CertificadoSunatError con
    un mensaje que indica exactamente qué falta corregir."""
    if not settings.SUNAT_CERT_PATH:
        raise CertificadoSunatError("No se configuró el certificado digital: falta la variable SUNAT_CERT_PATH")
    if settings.SUNAT_CERT_PASSWORD is None:
        raise CertificadoSunatError(
            "No se configuró la contraseña del certificado digital: falta la variable SUNAT_CERT_PASSWORD"
        )

    ruta = Path(settings.SUNAT_CERT_PATH).expanduser()
    if not ruta.is_file():
        raise CertificadoSunatError(f"No se encontró el certificado digital en {ruta} (revise SUNAT_CERT_PATH)")

    certificado = _abrir_p12(ruta, ruta.stat().st_mtime_ns, settings.SUNAT_CERT_PASSWORD.get_secret_value())

    ahora = datetime.now(timezone.utc)
    if certificado.certificado.not_valid_before_utc > ahora:
        raise CertificadoSunatError(
            f"El certificado digital recién es válido desde el {certificado.certificado.not_valid_before_utc:%d/%m/%Y}"
        )
    if certificado.vence_en < ahora:
        raise CertificadoSunatError(f"El certificado digital venció el {certificado.vence_en:%d/%m/%Y}")

    return certificado
