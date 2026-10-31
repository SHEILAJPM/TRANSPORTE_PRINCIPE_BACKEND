"""Firma XMLDSig (enveloped, RSA-SHA256) de los documentos UBL enviados directo a SUNAT."""

from dataclasses import dataclass

from cryptography.hazmat.primitives.serialization import Encoding
from lxml import etree
from signxml import CanonicalizationMethod, DigestAlgorithm, SignatureMethod, XMLSigner

from app.services.sunat_certificado_service import CertificadoSunat

_NS_DS = "http://www.w3.org/2000/09/xmldsig#"


@dataclass(frozen=True)
class XmlFirmado:
    contenido: bytes
    digest: str  # DigestValue de la firma: el "código hash" del comprobante


def firmar_xml(raiz: etree._Element, certificado: CertificadoSunat, id_firma: str) -> XmlFirmado:
    """Firma el documento completo. `raiz` debe traer un <ds:Signature Id="placeholder">
    dentro de ext:ExtensionContent, que es donde SUNAT exige la firma."""
    firmante = XMLSigner(
        signature_algorithm=SignatureMethod.RSA_SHA256,
        digest_algorithm=DigestAlgorithm.SHA256,
        c14n_algorithm=CanonicalizationMethod.CANONICAL_XML_1_0,
    )
    cadena_pem = [
        c.public_bytes(Encoding.PEM).decode() for c in (certificado.certificado, *certificado.cadena)
    ]
    firmado = firmante.sign(raiz, key=certificado.clave_privada, cert=cadena_pem)

    firma = firmado.find(f".//{{{_NS_DS}}}Signature")
    # El Id de ds:Signature no forma parte de lo firmado (la transformación enveloped
    # excluye todo el nodo), así que asignarlo después no invalida la firma.
    firma.set("Id", id_firma)
    digest = firma.findtext(f".//{{{_NS_DS}}}DigestValue") or ""

    contenido = etree.tostring(firmado, xml_declaration=True, encoding="UTF-8")
    return XmlFirmado(contenido=contenido, digest=digest)
