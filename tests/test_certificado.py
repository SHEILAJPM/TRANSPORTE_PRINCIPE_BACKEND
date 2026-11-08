"""Carga del certificado .p12: binario (uso local) o en base64 (Secret File de Render)."""

import base64
from datetime import datetime, timedelta, timezone

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import BestAvailableEncryption, pkcs12
from cryptography.x509.oid import NameOID
from pydantic import SecretStr

from app.core.config import settings
from app.services import sunat_certificado_service as svc


@pytest.fixture
def p12() -> bytes:
    clave = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    nombre = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "EMPRESA PRUEBA")])
    ahora = datetime.now(timezone.utc)
    cert = (
        x509.CertificateBuilder().subject_name(nombre).issuer_name(nombre).public_key(clave.public_key())
        .serial_number(1).not_valid_before(ahora - timedelta(days=1)).not_valid_after(ahora + timedelta(days=30))
        .sign(clave, hashes.SHA256())
    )
    return pkcs12.serialize_key_and_certificates(b"x", clave, cert, None, BestAvailableEncryption(b"clave123"))


def _configurar(monkeypatch, ruta, contrasena="clave123"):
    monkeypatch.setattr(settings, "SUNAT_CERT_PATH", str(ruta))
    monkeypatch.setattr(settings, "SUNAT_CERT_PASSWORD", SecretStr(contrasena))
    svc._abrir_p12.cache_clear()


def test_carga_p12_binario(monkeypatch, tmp_path, p12):
    ruta = tmp_path / "certificado.p12"
    ruta.write_bytes(p12)
    _configurar(monkeypatch, ruta)
    assert "EMPRESA PRUEBA" in svc.cargar_certificado().titular


def test_carga_p12_en_base64_con_saltos_de_linea(monkeypatch, tmp_path, p12):
    texto = base64.b64encode(p12).decode()
    ruta = tmp_path / "certificado.p12"
    # Pegado en un textarea puede llegar partido en líneas y con salto final.
    ruta.write_text("\n".join(texto[i : i + 76] for i in range(0, len(texto), 76)) + "\n")
    _configurar(monkeypatch, ruta)
    assert "EMPRESA PRUEBA" in svc.cargar_certificado().titular


def test_base64_con_contrasena_incorrecta_da_error_claro(monkeypatch, tmp_path, p12):
    ruta = tmp_path / "certificado.p12"
    ruta.write_text(base64.b64encode(p12).decode())
    _configurar(monkeypatch, ruta, contrasena="otra")
    with pytest.raises(svc.CertificadoSunatError, match="contraseña"):
        svc.cargar_certificado()


def test_falta_la_ruta(monkeypatch):
    monkeypatch.setattr(settings, "SUNAT_CERT_PATH", None)
    with pytest.raises(svc.CertificadoSunatError, match="SUNAT_CERT_PATH"):
        svc.cargar_certificado()


def test_distingue_archivo_incompleto_de_contrasena_incorrecta(monkeypatch, tmp_path, p12):
    texto = base64.b64encode(p12).decode()
    ruta = tmp_path / "certificado.p12"

    ruta.write_text(texto[: len(texto) // 2])  # pegado a medias
    _configurar(monkeypatch, ruta)
    with pytest.raises(svc.CertificadoSunatError, match="incompleto"):
        svc.cargar_certificado()

    ruta.write_text("esto no es un certificado")
    _configurar(monkeypatch, ruta)
    with pytest.raises(svc.CertificadoSunatError, match="no es un .p12"):
        svc.cargar_certificado()

    ruta.write_text(texto)
    _configurar(monkeypatch, ruta, contrasena="otra")
    with pytest.raises(svc.CertificadoSunatError, match="está completo"):
        svc.cargar_certificado()


def test_tolera_espacios_o_comillas_en_la_contrasena(monkeypatch, tmp_path, p12):
    ruta = tmp_path / "certificado.p12"
    ruta.write_text(base64.b64encode(p12).decode())
    for contrasena in (" clave123 ", '"clave123"', "clave123\n"):
        _configurar(monkeypatch, ruta, contrasena=contrasena)
        assert "EMPRESA PRUEBA" in svc.cargar_certificado().titular
