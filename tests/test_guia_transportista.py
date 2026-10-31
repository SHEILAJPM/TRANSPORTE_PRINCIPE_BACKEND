"""Guía de Remisión Transportista directa a SUNAT: XML UBL 2.1, firma, lectura de la
guía de remitente del cliente y flujo de emisión contra una API de SUNAT simulada.
No hace llamadas reales a SUNAT ni necesita base de datos."""

import asyncio
import base64
import io
import json
import uuid
import zipfile
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace

import httpx
import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import Encoding
from cryptography.x509.oid import NameOID
from lxml import etree
from pydantic import SecretStr
from signxml import XMLVerifier

from app.core.config import settings
from app.models.chofer import Chofer
from app.models.cliente import Cliente
from app.models.comprobante import GuiaRemision
from app.models.empresa import Empresa
from app.models.enums import EstadoSunat, TipoDocumentoIdentidad
from app.models.flota import Carreta, Tracto
from app.models.viaje import Viaje
from app.services import gre_ubl_service as ubl
from app.services import guia_transportista_service as servicio
from app.services import sunat_gre_api_service as api
from app.services.guia_remitente_service import GuiaRemitenteInvalidaError, leer_guia_remitente
from app.services.sunat_certificado_service import CertificadoSunat
from app.services.sunat_firma_service import firmar_xml
from app.utils.fechas import ZONA_PERU
from app.utils.xml_seguro import XmlInvalidoError

NS = {"ds": ubl.NS_DS, "ext": ubl.NS_EXT, "cac": ubl.NS_CAC, "cbc": ubl.NS_CBC}
RUC_EMPRESA = "20123456789"


@pytest.fixture(scope="module")
def certificado() -> CertificadoSunat:
    clave = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    nombre = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "EMPRESA PRUEBA")])
    ahora = datetime.now(timezone.utc)
    cert = (
        x509.CertificateBuilder().subject_name(nombre).issuer_name(nombre).public_key(clave.public_key())
        .serial_number(1).not_valid_before(ahora - timedelta(days=1)).not_valid_after(ahora + timedelta(days=30))
        .sign(clave, hashes.SHA256())
    )
    return CertificadoSunat(clave_privada=clave, certificado=cert, cadena=())


def _datos(**cambios) -> ubl.DatosGuiaTransportista:
    base = dict(
        serie="V001",
        numero="00000001",
        transportista=ubl.Parte("6", RUC_EMPRESA, "TRANSPORTE PRINCIPE S.A.C."),
        registro_mtc="1234567CNG",
        remitente=ubl.Parte("6", "20999999999", "CLIENTE SAC"),
        destinatario=ubl.Parte("1", "12345678", "JUAN PEREZ"),
        partida=ubl.Direccion("150101", "Av. Lima 123"),
        llegada=ubl.Direccion("040101", "Calle Arequipa 456"),
        fecha_inicio_traslado=date(2026, 10, 31),
        peso_bruto_kg=Decimal("28500.5"),
        vehiculo_principal=ubl.Vehiculo("ABC123", "15M21000123"),
        conductor=ubl.Conductor("87654321", "PEDRO", "QUISPE ROJAS", "Q87654321"),
        bienes=(ubl.Bien("Cemento portland tipo I", Decimal("570"), "NIU", "CEM01"),),
        documentos_relacionados=(ubl.DocumentoRelacionado("09", "EG01", "00000123", "20999999999"),),
    )
    base.update(cambios)
    return ubl.DatosGuiaTransportista(**base)


# --- XML UBL 2.1 y firma -------------------------------------------------------


def test_xml_tiene_estructura_de_guia_transportista():
    raiz = ubl.construir_xml(_datos(), datetime(2026, 10, 31, 10, 30, tzinfo=ZONA_PERU))

    def texto(ruta):
        return raiz.xpath(f"string({ruta})", namespaces=NS)

    assert texto("/*/cbc:UBLVersionID") == "2.1"
    assert texto("/*/cbc:CustomizationID") == "2.0"
    assert texto("/*/cbc:ID") == "V001-00000001"
    assert texto("/*/cbc:IssueDate") == "2026-10-31"
    assert texto("/*/cbc:IssueTime") == "10:30:00"
    assert texto("/*/cbc:DespatchAdviceTypeCode") == "31"
    assert texto("/*/cac:DespatchSupplierParty/cac:Party/cac:PartyIdentification/cbc:ID") == RUC_EMPRESA
    assert texto("/*/cac:Shipment/cac:Delivery/cac:Despatch/cac:DespatchParty/cac:PartyIdentification/cbc:ID") == "20999999999"
    assert texto("/*/cac:DeliveryCustomerParty/cac:Party/cac:PartyIdentification/cbc:ID/@schemeID") == "1"
    assert texto("/*/cac:Shipment/cbc:GrossWeightMeasure") == "28500.500"
    assert texto("/*/cac:Shipment/cac:ShipmentStage/cac:CarrierParty/cac:PartyLegalEntity/cbc:CompanyID") == "1234567CNG"
    assert texto("/*/cac:Shipment/cac:ShipmentStage/cac:DriverPerson/cbc:JobTitle") == "Principal"
    assert texto("/*/cac:Shipment/cac:TransportHandlingUnit/cac:TransportEquipment/cbc:ID") == "ABC123"
    assert texto("/*/cac:AdditionalDocumentReference/cbc:ID") == "EG01-00000123"
    assert texto("/*/cac:AdditionalDocumentReference/cbc:DocumentTypeCode") == "09"
    assert texto("/*/cac:DespatchLine/cbc:DeliveredQuantity") == "570"


def test_firma_queda_en_extension_content_y_es_verificable(certificado):
    raiz = ubl.construir_xml(_datos(), datetime(2026, 10, 31, 10, 30, tzinfo=ZONA_PERU))
    firmado = firmar_xml(raiz, certificado, ubl.ID_FIRMA)
    doc = etree.fromstring(firmado.contenido)

    firma = doc.xpath("/*/ext:UBLExtensions/ext:UBLExtension/ext:ExtensionContent/ds:Signature", namespaces=NS)
    assert len(firma) == 1 and firma[0].get("Id") == ubl.ID_FIRMA
    assert doc.xpath("string(/*/cac:Signature/cac:DigitalSignatureAttachment/cac:ExternalReference/cbc:URI)", namespaces=NS) == f"#{ubl.ID_FIRMA}"
    assert firmado.digest

    cert_pem = certificado.certificado.public_bytes(Encoding.PEM).decode()
    XMLVerifier().verify(firmado.contenido, x509_cert=cert_pem)
    with pytest.raises(Exception):
        XMLVerifier().verify(firmado.contenido.replace(b"28500.500", b"18500.500"), x509_cert=cert_pem)


def test_validacion_detecta_errores_bloqueantes():
    datos = _datos(
        serie="T001",
        partida=ubl.Direccion("", "Av. Lima"),
        vehiculo_principal=ubl.Vehiculo("AB-1", None),
        conductor=ubl.Conductor("123", "PEDRO", "QUISPE", ""),
        bienes=(),
        documentos_relacionados=(),
    )
    errores = " | ".join(ubl.validar(datos).errores)
    for esperado in ("serie", "UBIGEO", "placa", "DNI del chofer", "licencia", "bien transportado"):
        assert esperado in errores
    assert not ubl.validar(_datos()).errores


def test_huella_cambia_si_cambia_un_dato():
    assert _datos().huella() == _datos().huella()
    assert _datos().huella() != _datos(peso_bruto_kg=Decimal("28500.6")).huella()
    assert _datos().huella() != _datos(conductor=ubl.Conductor("87654321", "PEDRO", "QUISPE ROJAS", "Q00000000")).huella()


# --- Guía de remitente del cliente ---------------------------------------------

GRR_XML = """<?xml version="1.0" encoding="UTF-8"?>
<DespatchAdvice xmlns="urn:oasis:names:specification:ubl:schema:xsd:DespatchAdvice-2"
  xmlns:cac="urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2"
  xmlns:cbc="urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2">
  <cbc:UBLVersionID>2.1</cbc:UBLVersionID>
  <cbc:ID>EG01-00000123</cbc:ID>
  <cbc:IssueDate>2026-10-30</cbc:IssueDate>
  <cbc:DespatchAdviceTypeCode>09</cbc:DespatchAdviceTypeCode>
  <cac:DespatchSupplierParty><cac:Party>
    <cac:PartyIdentification><cbc:ID schemeID="6">20999999999</cbc:ID></cac:PartyIdentification>
    <cac:PartyLegalEntity><cbc:RegistrationName>CEMENTOS DEL SUR S.A.</cbc:RegistrationName></cac:PartyLegalEntity>
  </cac:Party></cac:DespatchSupplierParty>
  <cac:DeliveryCustomerParty><cac:Party>
    <cac:PartyIdentification><cbc:ID schemeID="6">20555555555</cbc:ID></cac:PartyIdentification>
    <cac:PartyLegalEntity><cbc:RegistrationName>FERRETERIA AREQUIPA EIRL</cbc:RegistrationName></cac:PartyLegalEntity>
  </cac:Party></cac:DeliveryCustomerParty>
  <cac:Shipment>
    <cbc:ID>SUNAT_Envio</cbc:ID>
    <cbc:HandlingCode>01</cbc:HandlingCode>
    <cbc:GrossWeightMeasure unitCode="TNE">28.5</cbc:GrossWeightMeasure>
    <cbc:TotalTransportHandlingUnitQuantity>570</cbc:TotalTransportHandlingUnitQuantity>
    <cac:ShipmentStage>
      <cbc:TransportModeCode>01</cbc:TransportModeCode>
      <cac:TransitPeriod><cbc:StartDate>2026-11-02</cbc:StartDate></cac:TransitPeriod>
      <cac:CarrierParty><cac:PartyIdentification><cbc:ID schemeID="6">20123456789</cbc:ID></cac:PartyIdentification></cac:CarrierParty>
    </cac:ShipmentStage>
    <cac:Delivery>
      <cac:DeliveryAddress><cbc:ID>040101</cbc:ID><cac:AddressLine><cbc:Line>Av. Ejercito 100</cbc:Line></cac:AddressLine></cac:DeliveryAddress>
      <cac:Despatch><cac:DespatchAddress><cbc:ID>150101</cbc:ID><cac:AddressLine><cbc:Line>Planta Lurin km 30</cbc:Line></cac:AddressLine></cac:DespatchAddress></cac:Despatch>
    </cac:Delivery>
  </cac:Shipment>
  <cac:DespatchLine>
    <cbc:ID>1</cbc:ID>
    <cbc:DeliveredQuantity unitCode="BG">570</cbc:DeliveredQuantity>
    <cac:Item><cbc:Description>Cemento tipo I x 42.5 kg</cbc:Description><cac:SellersItemIdentification><cbc:ID>CEM-I</cbc:ID></cac:SellersItemIdentification></cac:Item>
  </cac:DespatchLine>
</DespatchAdvice>""".encode()


def test_lee_guia_de_remitente_del_cliente():
    leida = leer_guia_remitente(GRR_XML, ruc_transportista=RUC_EMPRESA)
    assert (leida.serie, leida.numero) == ("EG01", "00000123")
    assert leida.remitente.numero_documento == "20999999999"
    assert leida.destinatario.razon_social == "FERRETERIA AREQUIPA EIRL"
    assert (leida.partida.ubigeo, leida.llegada.ubigeo) == ("150101", "040101")
    assert leida.peso_bruto_kg == Decimal("28500.0")  # TNE convertido a kg
    assert leida.numero_bultos == 570
    assert leida.fecha_inicio_traslado == date(2026, 11, 2)
    assert leida.motivo_descripcion == "Venta"
    assert leida.bienes[0].unidad == "BG" and leida.bienes[0].codigo == "CEM-I"
    assert leida.advertencias == []


def test_advierte_transporte_privado_y_otro_transportista():
    xml = GRR_XML.replace(b"<cbc:TransportModeCode>01", b"<cbc:TransportModeCode>02").replace(
        b">20123456789<", b">20111111111<"
    )
    advertencias = " ".join(leer_guia_remitente(xml, ruc_transportista=RUC_EMPRESA).advertencias)
    assert "PRIVADO" in advertencias and "20111111111" in advertencias


def test_rechaza_guia_que_no_es_de_remitente():
    with pytest.raises(GuiaRemitenteInvalidaError, match="tipo 31"):
        leer_guia_remitente(GRR_XML.replace(b">09<", b">31<"), ruc_transportista=RUC_EMPRESA)
    with pytest.raises(XmlInvalidoError):
        leer_guia_remitente(b"esto no es xml", ruc_transportista=RUC_EMPRESA)


def test_no_resuelve_entidades_externas(tmp_path):
    secreto = tmp_path / "secreto.txt"
    secreto.write_text("CLAVE-SECRETA")
    xxe = GRR_XML.replace(
        b'<?xml version="1.0" encoding="UTF-8"?>',
        f'<?xml version="1.0" encoding="UTF-8"?><!DOCTYPE d [<!ENTITY x SYSTEM "file:///{secreto.as_posix()}">]>'.encode(),
    ).replace(b"CEMENTOS DEL SUR S.A.", b"&x;")
    try:
        leida = leer_guia_remitente(xxe, ruc_transportista=RUC_EMPRESA)
    except (XmlInvalidoError, GuiaRemitenteInvalidaError):
        return
    assert "CLAVE-SECRETA" not in leida.remitente.razon_social


# --- Flujo de emisión contra SUNAT simulada ------------------------------------


class _SesionFalsa:
    """Lo mínimo de AsyncSession que usa el servicio de emisión."""

    def __init__(self, objetos):
        self._objetos = objetos
        self.flushes = 0

    async def get(self, modelo, ident, with_for_update=False):
        return self._objetos.get((modelo, ident))

    async def execute(self, _stmt):
        return SimpleNamespace(scalar_one_or_none=lambda: None)

    async def flush(self):
        self.flushes += 1


def _escenario():
    ids = {k: uuid.uuid4() for k in ("empresa", "viaje", "tracto", "chofer", "cliente", "guia", "carreta")}
    empresa = Empresa(id=ids["empresa"], ruc=RUC_EMPRESA, razon_social="TRANSPORTE PRINCIPE S.A.C.", numero_registro_mtc="1234567CNG")
    cliente = Cliente(id=ids["cliente"], tipo_documento=TipoDocumentoIdentidad.RUC, numero_documento="20999999999", razon_social="CLIENTE SAC")
    tracto = Tracto(id=ids["tracto"], placa="ABC-123", tarjeta_unica_circulacion="15M21000123")
    carreta = Carreta(id=ids["carreta"], placa="XYZ-987", tarjeta_unica_circulacion="15M21000999")
    chofer = Chofer(id=ids["chofer"], dni="87654321", nombres="PEDRO", apellidos="QUISPE ROJAS", licencia_numero="q87654321")
    viaje = Viaje(
        id=ids["viaje"], cliente_id=cliente.id, tracto_id=tracto.id, carreta_id=carreta.id, chofer_id=chofer.id,
        origen_direccion="Planta Lurin km 30", origen_ubigeo="150101", destino_direccion="Av. Ejercito 100",
        destino_ubigeo="040101", peso_tm=Decimal("28.5"), fecha_salida_programada=datetime.now() + timedelta(days=1),
    )
    guia = GuiaRemision(
        id=ids["guia"], empresa_id=empresa.id, viaje_id=viaje.id, cliente_id=cliente.id, serie="V001", numero="00000007",
        peso_bruto_total_kg=Decimal("28500"), estado_sunat=EstadoSunat.PENDIENTE,
        destinatario_tipo_documento="6", destinatario_numero_documento="20555555555",
        destinatario_razon_social="FERRETERIA AREQUIPA EIRL",
        remitente_guia_ruc_emisor="20999999999", remitente_guia_serie="EG01", remitente_guia_numero="00000123",
        bienes=[{"descripcion": "Cemento tipo I", "cantidad": 570, "unidad": "BG", "codigo": "CEM-I"}],
    )
    objetos = {
        (Empresa, empresa.id): empresa, (Cliente, cliente.id): cliente, (Tracto, tracto.id): tracto,
        (Carreta, carreta.id): carreta, (Chofer, chofer.id): chofer, (Viaje, viaje.id): viaje, (GuiaRemision, guia.id): guia,
    }
    return _SesionFalsa(objetos), guia


def _cdr_zip(codigo: str, descripcion: str) -> bytes:
    xml = f"""<ApplicationResponse xmlns="urn:oasis:names:specification:ubl:schema:xsd:ApplicationResponse-2"
      xmlns:cac="{ubl.NS_CAC}" xmlns:cbc="{ubl.NS_CBC}">
      <cac:DocumentResponse><cac:Response><cbc:ResponseCode>{codigo}</cbc:ResponseCode>
      <cbc:Description>{descripcion}</cbc:Description></cac:Response>
      <cac:DocumentReference><cbc:DocumentDescription>https://e-factura.sunat.gob.pe/v1/contribuyente/gre/comprobantes/descargaqr?hashqr=abc</cbc:DocumentDescription></cac:DocumentReference>
      </cac:DocumentResponse></ApplicationResponse>"""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as z:
        z.writestr("R-20123456789-31-V001-00000007.xml", xml)
    return buffer.getvalue()


@pytest.fixture
def sunat_simulada(monkeypatch, tmp_path, certificado):
    """Configura credenciales de prueba, almacenamiento temporal y una API de SUNAT
    falsa. Devuelve el registro de peticiones y un dict para fijar las respuestas."""
    monkeypatch.setattr(settings, "GRE_PROVEEDOR", "sunat_directo")
    monkeypatch.setattr(settings, "SUNAT_GRE_CLIENT_ID", "cliente-prueba")
    monkeypatch.setattr(settings, "SUNAT_GRE_CLIENT_SECRET", SecretStr("secreto"))
    monkeypatch.setattr(settings, "SUNAT_SOL_USUARIO", f"{RUC_EMPRESA}MODDATOS")
    monkeypatch.setattr(settings, "SUNAT_SOL_CLAVE", SecretStr("clave"))
    monkeypatch.setattr(settings, "STORAGE_BACKEND", "local")
    monkeypatch.setattr(settings, "STORAGE_PRIVADO_LOCAL_PATH", str(tmp_path))
    monkeypatch.setattr(servicio, "cargar_certificado", lambda: certificado)
    monkeypatch.setattr(servicio, "_ESPERA_ENTRE_CONSULTAS_SEGUNDOS", 0)
    api._tokens.clear()

    peticiones: list[httpx.Request] = []
    respuestas = {"tickets": [{"codRespuesta": "0", "arcCdr": base64.b64encode(_cdr_zip("0", "La Guia ha sido aceptada")).decode(), "indCdrGenerado": "1"}]}

    def manejar(request: httpx.Request) -> httpx.Response:
        peticiones.append(request)
        if "oauth2/token" in request.url.path:
            return httpx.Response(200, json={"access_token": "tok", "token_type": "JWT", "expires_in": 3600})
        if request.method == "POST":
            return httpx.Response(200, json={"numTicket": "TICKET-1", "fecRecepcion": "2026-10-31T10:30:00"})
        return httpx.Response(200, json=respuestas["tickets"].pop(0))

    transporte = httpx.MockTransport(manejar)
    monkeypatch.setattr(
        servicio, "ClienteSunatGre", lambda: api.ClienteSunatGre(http_client=httpx.AsyncClient(transport=transporte))
    )
    return peticiones, respuestas


def test_emision_completa_aceptada(sunat_simulada, tmp_path):
    peticiones, _ = sunat_simulada
    db, guia = _escenario()

    vista = asyncio.run(servicio.vista_previa(db, guia))
    assert vista.errores == [] and vista.xml and "V001-00000007" in vista.xml
    assert peticiones == []  # la vista previa nunca contacta a SUNAT

    asyncio.run(servicio.emitir(db, guia.id, vista.huella))

    assert guia.estado_sunat == EstadoSunat.ACEPTADO
    assert guia.sunat_ticket == "TICKET-1" and guia.hash_cpe
    assert "aceptada" in guia.mensaje_sunat
    assert guia.pdf_url.startswith("https://e-factura.sunat.gob.pe")
    assert (tmp_path / guia.xml_clave).is_file() and (tmp_path / guia.cdr_clave).is_file()

    token, envio, ticket = peticiones
    assert token.url.path == "/v1/clientessol/cliente-prueba/oauth2/token/"
    assert envio.url.path == f"/v1/contribuyente/gem/comprobantes/{RUC_EMPRESA}-31-V001-00000007"
    cuerpo = json.loads(envio.content)["archivo"]
    assert cuerpo["nomArchivo"] == f"{RUC_EMPRESA}-31-V001-00000007.zip"
    with zipfile.ZipFile(io.BytesIO(base64.b64decode(cuerpo["arcGreZip"]))) as z:
        xml_enviado = etree.fromstring(z.read(f"{RUC_EMPRESA}-31-V001-00000007.xml"))
    assert xml_enviado.xpath("string(//cac:TransportEquipment/cbc:ID)", namespaces=NS) == "ABC123"  # placa sin guion
    assert xml_enviado.xpath("string(//cac:AttachedTransportEquipment/cbc:ID)", namespaces=NS) == "XYZ987"
    assert xml_enviado.xpath("string(//cac:DriverPerson/cac:IdentityDocumentReference/cbc:ID)", namespaces=NS) == "Q87654321"
    assert ticket.url.path == "/v1/contribuyente/gem/comprobantes/envios/TICKET-1"

    # Ya aceptada: no se puede volver a enviar.
    with pytest.raises(servicio.GuiaNoEmitibleError):
        asyncio.run(servicio.emitir(db, guia.id, vista.huella))


def test_no_envia_si_los_datos_cambiaron_tras_la_vista_previa(sunat_simulada):
    peticiones, _ = sunat_simulada
    db, guia = _escenario()
    vista = asyncio.run(servicio.vista_previa(db, guia))

    guia.peso_bruto_total_kg = Decimal("30000")
    with pytest.raises(servicio.HuellaNoCoincideError):
        asyncio.run(servicio.emitir(db, guia.id, vista.huella))
    assert peticiones == []


def test_ticket_en_proceso_queda_pendiente_y_luego_se_consulta(sunat_simulada):
    peticiones, respuestas = sunat_simulada
    respuestas["tickets"] = [{"codRespuesta": "98"}] * 3 + [
        {"codRespuesta": "99", "indCdrGenerado": "0", "error": {"numError": "2335", "desError": "El documento ya fue informado"}}
    ]
    db, guia = _escenario()
    vista = asyncio.run(servicio.vista_previa(db, guia))
    asyncio.run(servicio.emitir(db, guia.id, vista.huella))
    assert guia.estado_sunat == EstadoSunat.PENDIENTE and guia.sunat_ticket == "TICKET-1"

    # Con un envío en proceso no se permite reenviar, solo consultar.
    with pytest.raises(servicio.GuiaNoEmitibleError, match="no la reenvíe"):
        asyncio.run(servicio.emitir(db, guia.id, vista.huella))
    asyncio.run(servicio.consultar_ticket(db, guia.id))
    assert guia.estado_sunat == EstadoSunat.RECHAZADO
    assert guia.sunat_codigo_respuesta == "2335" and "ya fue informado" in guia.mensaje_sunat
    assert sum(1 for p in peticiones if p.method == "POST" and "comprobantes/" in p.url.path) == 1


def test_vista_previa_avisa_si_faltan_credenciales(monkeypatch, sunat_simulada):
    monkeypatch.setattr(settings, "SUNAT_SOL_CLAVE", None)
    db, guia = _escenario()
    vista = asyncio.run(servicio.vista_previa(db, guia))
    assert any("SUNAT_SOL_CLAVE" in e for e in vista.errores)
