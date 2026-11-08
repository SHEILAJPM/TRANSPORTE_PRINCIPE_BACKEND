"""Certificado digital (.p12) con el que se firman los documentos enviados directo
a SUNAT. La ruta y la contraseña llegan solo por variables de entorno
(SUNAT_CERT_PATH / SUNAT_CERT_PASSWORD); en Render la ruta apunta al Secret File
montado en /etc/secrets/."""

import base64
import binascii
import re
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


_RE_BASE64 = re.compile(r"[A-Za-z0-9+/]+=*")


def _desde_base64(contenido: bytes) -> bytes | None:
    """Devuelve el binario si `contenido` es un .p12 en base64; None si ya es binario."""
    try:
        texto = "".join(contenido.decode("ascii").split())
    except UnicodeDecodeError:
        return None  # un .p12 binario casi nunca es ASCII puro
    if not texto or not _RE_BASE64.fullmatch(texto):
        return None
    # Si se pegó cortado, se decodifica lo que llegó para poder avisar que está incompleto.
    texto = texto.rstrip("=")
    texto = texto[: len(texto) - len(texto) % 4] if len(texto) % 4 == 1 else texto
    try:
        return base64.b64decode(texto + "=" * (-len(texto) % 4))
    except (binascii.Error, ValueError):
        return None


def _diagnosticar_der(contenido: bytes) -> str | None:
    """Un .p12 es una estructura DER: empieza con 0x30 y declara su propio largo. Así
    se distingue un archivo pegado a medias (o que no es un certificado) de una
    contraseña equivocada."""
    if len(contenido) < 4 or contenido[0] != 0x30:
        return (
            "El Secret File del certificado no es un .p12 ni su texto en base64. Vuelve a generarlo con "
            "el comando de PowerShell y pégalo completo en Render (Secret Files → certificado.p12)."
        )
    if contenido[1] & 0x80:
        bytes_largo = contenido[1] & 0x7F
        esperado = 2 + bytes_largo + int.from_bytes(contenido[2 : 2 + bytes_largo], "big")
    else:
        esperado = 2 + contenido[1]
    if len(contenido) < esperado:
        return (
            f"El certificado está incompleto: se recibieron {len(contenido):,} de {esperado:,} bytes. "
            "Probablemente el texto se pegó a medias en el Secret File; vuelve a pegarlo completo."
        )
    return None


@lru_cache(maxsize=4)
def _abrir_p12(ruta: Path, modificado_ns: int, contrasena: str) -> CertificadoSunat:
    # `modificado_ns` forma parte de la clave de caché: si se reemplaza el archivo
    # (p.ej. renovación del certificado) se vuelve a leer sin reiniciar el backend.
    try:
        contenido = ruta.read_bytes()
    except OSError as error:
        raise CertificadoSunatError(f"No se pudo leer el certificado digital en {ruta}: {error.strerror}") from error

    # Los Secret Files de Render solo guardan texto: el .p12 (binario) se sube convertido
    # a base64 y aquí se decodifica. Un .p12 binario (uso local) se lee tal cual.
    decodificado = _desde_base64(contenido)
    if decodificado is not None:
        contenido = decodificado

    problema_archivo = _diagnosticar_der(contenido)
    if problema_archivo:
        raise CertificadoSunatError(problema_archivo)

    # Al copiar la contraseña en Render es fácil arrastrar espacios o comillas.
    candidatas = dict.fromkeys([contrasena, contrasena.strip(), contrasena.strip().strip("\"'")])
    for candidata in candidatas:
        try:
            clave_privada, certificado, cadena = pkcs12.load_key_and_certificates(contenido, candidata.encode())
            break
        except ValueError:
            continue
    else:
        raise CertificadoSunatError(
            f"El archivo del certificado está completo ({len(contenido):,} bytes), pero la contraseña "
            "(SUNAT_CERT_PASSWORD) no lo abre. Revisa que sea la contraseña de ESTE .p12 y que en Render "
            "no haya dos variables SUNAT_CERT_PASSWORD."
        )

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
