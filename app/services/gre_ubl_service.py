"""XML UBL 2.1 de la Guía de Remisión Electrónica Transportista (tipo 31).

Estructura según el Anexo VII de la R.S. N.° 000123-2022/SUNAT ("Estándar UBL 2.1 -
Guía de remisión - Transportista"). Los datos se reúnen primero en
`DatosGuiaTransportista` (sin fecha/hora de emisión) para poder validarlos, mostrarlos
en la vista previa y calcular una huella que el usuario confirma antes del envío.
"""

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from decimal import Decimal

from lxml import etree

NS_DESPATCH = "urn:oasis:names:specification:ubl:schema:xsd:DespatchAdvice-2"
NS_CAC = "urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2"
NS_CBC = "urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2"
NS_EXT = "urn:oasis:names:specification:ubl:schema:xsd:CommonExtensionComponents-2"
NS_DS = "http://www.w3.org/2000/09/xmldsig#"
_NSMAP = {None: NS_DESPATCH, "cac": NS_CAC, "cbc": NS_CBC, "ext": NS_EXT, "ds": NS_DS}

TIPO_DOCUMENTO_GRE_TRANSPORTISTA = "31"
ID_FIRMA = "SignatureTP"

# Catálogo 06 (tipo de documento de identidad)
TIPO_DOC_RUC = "6"
TIPO_DOC_DNI = "1"

# Catálogo 61 (documento relacionado al transporte)
DOCUMENTO_RELACIONADO_DESCRIPCION = {"09": "Guía de remisión remitente"}

_ATRIB_DOC_IDENTIDAD = {
    "schemeName": "Documento de Identidad",
    "schemeAgencyName": "PE:SUNAT",
    "schemeURI": "urn:pe:gob:sunat:cpe:see:gem:catalogos:catalogo06",
}

_RE_SERIE_GRE_T = re.compile(r"^V[A-Z0-9]{3}$")
_RE_NUMERO = re.compile(r"^\d{1,8}$")
_RE_RUC = re.compile(r"^\d{11}$")
_RE_DNI = re.compile(r"^\d{8}$")
_RE_UBIGEO = re.compile(r"^\d{6}$")
_RE_PLACA = re.compile(r"^[A-Z0-9]{6,8}$")
_RE_LICENCIA = re.compile(r"^[A-Z0-9]{9,10}$")


@dataclass(frozen=True)
class Parte:
    tipo_documento: str  # Catálogo 06
    numero_documento: str
    razon_social: str


@dataclass(frozen=True)
class Direccion:
    ubigeo: str
    direccion: str


@dataclass(frozen=True)
class Vehiculo:
    placa: str
    tarjeta_unica_circulacion: str | None = None


@dataclass(frozen=True)
class Conductor:
    dni: str
    nombres: str
    apellidos: str
    licencia: str


@dataclass(frozen=True)
class Bien:
    descripcion: str
    cantidad: Decimal
    unidad: str  # Catálogo 03 (UN/ECE rec 20): NIU, KGM, TNE, ...
    codigo: str | None = None


@dataclass(frozen=True)
class DocumentoRelacionado:
    tipo: str  # Catálogo 61
    serie: str
    numero: str
    ruc_emisor: str


@dataclass(frozen=True)
class DatosGuiaTransportista:
    serie: str
    numero: str
    transportista: Parte
    registro_mtc: str | None
    remitente: Parte
    destinatario: Parte
    partida: Direccion
    llegada: Direccion
    fecha_inicio_traslado: date
    peso_bruto_kg: Decimal
    vehiculo_principal: Vehiculo
    conductor: Conductor
    vehiculos_secundarios: tuple[Vehiculo, ...] = ()
    bienes: tuple[Bien, ...] = ()
    documentos_relacionados: tuple[DocumentoRelacionado, ...] = ()
    observaciones: str | None = None

    @property
    def nombre_archivo(self) -> str:
        """`RUC-31-SERIE-NUMERO`, nombre exigido por SUNAT para el XML y el ZIP."""
        return f"{self.transportista.numero_documento}-{TIPO_DOCUMENTO_GRE_TRANSPORTISTA}-{self.serie}-{self.numero}"

    def huella(self) -> str:
        """Hash de todos los datos que van a SUNAT (excepto la fecha/hora de emisión,
        que se fija al momento del envío). La vista previa la devuelve y el envío la
        exige: si algún dato cambió desde que el usuario revisó, no se envía."""
        contenido = json.dumps(asdict(self), sort_keys=True, default=str, ensure_ascii=False)
        return hashlib.sha256(contenido.encode()).hexdigest()


@dataclass
class ResultadoValidacion:
    errores: list[str] = field(default_factory=list)
    advertencias: list[str] = field(default_factory=list)


def normalizar_placa(placa: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", placa.upper())


def validar(datos: DatosGuiaTransportista) -> ResultadoValidacion:
    """Validaciones locales (formato y obligatoriedad del estándar). No sustituyen a las
    de SUNAT, pero atrapan antes del envío los rechazos más comunes."""
    r = ResultadoValidacion()

    if not _RE_SERIE_GRE_T.fullmatch(datos.serie):
        r.errores.append(f"La serie {datos.serie!r} no es válida: la guía transportista usa el formato V###")
    if not _RE_NUMERO.fullmatch(datos.numero):
        r.errores.append(f"El número {datos.numero!r} debe tener hasta 8 dígitos")

    if not _RE_RUC.fullmatch(datos.transportista.numero_documento):
        r.errores.append("El RUC de la empresa transportista debe tener 11 dígitos (revise los datos de la empresa)")
    if not datos.transportista.razon_social.strip():
        r.errores.append("Falta la razón social de la empresa transportista")
    if not datos.registro_mtc:
        r.advertencias.append("La empresa no tiene registrado su número de Registro MTC")

    for rol, parte in (("remitente", datos.remitente), ("destinatario", datos.destinatario)):
        if parte.tipo_documento == TIPO_DOC_RUC and not _RE_RUC.fullmatch(parte.numero_documento):
            r.errores.append(f"El RUC del {rol} debe tener 11 dígitos")
        elif parte.tipo_documento == TIPO_DOC_DNI and not _RE_DNI.fullmatch(parte.numero_documento):
            r.errores.append(f"El DNI del {rol} debe tener 8 dígitos")
        elif not parte.numero_documento:
            r.errores.append(f"Falta el documento de identidad del {rol}")
        if not parte.razon_social.strip():
            r.errores.append(f"Falta el nombre o razón social del {rol}")

    for rol, direccion in (("partida", datos.partida), ("llegada", datos.llegada)):
        if not _RE_UBIGEO.fullmatch(direccion.ubigeo or ""):
            r.errores.append(f"Falta el UBIGEO (6 dígitos) del punto de {rol}")
        if not direccion.direccion.strip():
            r.errores.append(f"Falta la dirección del punto de {rol}")

    if datos.peso_bruto_kg <= 0:
        r.errores.append("El peso bruto total debe ser mayor a cero")

    for etiqueta, vehiculo in [("del tracto", datos.vehiculo_principal)] + [
        (f"del vehículo secundario {i}", v) for i, v in enumerate(datos.vehiculos_secundarios, start=1)
    ]:
        if not _RE_PLACA.fullmatch(vehiculo.placa):
            r.errores.append(f"La placa {etiqueta} ({vehiculo.placa!r}) debe tener de 6 a 8 letras/números, sin guiones")
        if not vehiculo.tarjeta_unica_circulacion:
            r.advertencias.append(f"No se registró la Tarjeta Única de Circulación (TUC) {etiqueta}")
    if len(datos.vehiculos_secundarios) > 2:
        r.errores.append("SUNAT admite como máximo 2 vehículos secundarios")

    c = datos.conductor
    if not _RE_DNI.fullmatch(c.dni):
        r.errores.append("El DNI del chofer debe tener 8 dígitos")
    if not c.nombres.strip() or not c.apellidos.strip():
        r.errores.append("Faltan los nombres o apellidos del chofer")
    if not c.licencia or len(c.licencia) > 10:
        r.errores.append("La licencia de conducir del chofer es obligatoria y tiene como máximo 10 caracteres")
    elif not _RE_LICENCIA.fullmatch(c.licencia):
        r.advertencias.append(f"La licencia {c.licencia!r} no tiene el formato habitual (letra + 8 dígitos, p.ej. Q12345678)")

    if not datos.bienes and not datos.documentos_relacionados:
        r.errores.append("Indique al menos un bien transportado o la guía de remitente del cliente")

    return r


def _sub(padre: etree._Element, ns: str, tag: str, texto: str | None = None, **atributos: str) -> etree._Element:
    elemento = etree.SubElement(padre, f"{{{ns}}}{tag}", {k: v for k, v in atributos.items()})
    if texto is not None:
        elemento.text = texto
    return elemento


def _cac(padre, tag, **atributos):
    return _sub(padre, NS_CAC, tag, **atributos)


def _cbc(padre, tag, texto=None, **atributos):
    return _sub(padre, NS_CBC, tag, texto, **atributos)


def _parte_legal(padre: etree._Element, parte: Parte) -> None:
    identificacion = _cac(padre, "PartyIdentification")
    _cbc(identificacion, "ID", parte.numero_documento, schemeID=parte.tipo_documento, **_ATRIB_DOC_IDENTIDAD)
    entidad = _cac(padre, "PartyLegalEntity")
    _cbc(entidad, "RegistrationName", parte.razon_social[:250])


def _direccion(padre: etree._Element, tag: str, direccion: Direccion) -> None:
    nodo = _cac(padre, tag)
    _cbc(nodo, "ID", direccion.ubigeo, schemeAgencyName="PE:INEI", schemeName="Ubigeos")
    linea = _cac(nodo, "AddressLine")
    _cbc(linea, "Line", direccion.direccion[:500])


def _vehiculo(padre: etree._Element, tag: str, vehiculo: Vehiculo) -> etree._Element:
    nodo = _cac(padre, tag)
    _cbc(nodo, "ID", vehiculo.placa)
    if vehiculo.tarjeta_unica_circulacion:
        medio = _cac(nodo, "ApplicableTransportMeans")
        _cbc(medio, "RegistrationNationalityID", vehiculo.tarjeta_unica_circulacion[:15])
    return nodo


def _formato_cantidad(cantidad: Decimal) -> str:
    # n(12,10): hasta 10 decimales, sin ceros sobrantes ni notación científica.
    return f"{cantidad.quantize(Decimal('0.0000000001')).normalize():f}"


def construir_xml(datos: DatosGuiaTransportista, emitido_en: datetime) -> etree._Element:
    """Arma el DespatchAdvice sin firmar. Deja en ext:ExtensionContent un
    <ds:Signature Id="placeholder"> que signxml reemplaza por la firma real."""
    raiz = etree.Element(f"{{{NS_DESPATCH}}}DespatchAdvice", nsmap=_NSMAP)

    extensiones = _sub(raiz, NS_EXT, "UBLExtensions")
    extension = _sub(extensiones, NS_EXT, "UBLExtension")
    contenido = _sub(extension, NS_EXT, "ExtensionContent")
    _sub(contenido, NS_DS, "Signature", Id="placeholder")

    _cbc(raiz, "UBLVersionID", "2.1")
    _cbc(raiz, "CustomizationID", "2.0")
    _cbc(raiz, "ID", f"{datos.serie}-{datos.numero}")
    _cbc(raiz, "IssueDate", emitido_en.strftime("%Y-%m-%d"))
    _cbc(raiz, "IssueTime", emitido_en.strftime("%H:%M:%S"))
    _cbc(
        raiz,
        "DespatchAdviceTypeCode",
        TIPO_DOCUMENTO_GRE_TRANSPORTISTA,
        listAgencyName="PE:SUNAT",
        listName="Tipo de Documento",
        listURI="urn:pe:gob:sunat:cpe:see:gem:catalogos:catalogo01",
    )
    if datos.observaciones:
        _cbc(raiz, "Note", datos.observaciones[:250])

    for doc in datos.documentos_relacionados:
        referencia = _cac(raiz, "AdditionalDocumentReference")
        _cbc(referencia, "ID", f"{doc.serie}-{doc.numero}")
        _cbc(
            referencia,
            "DocumentTypeCode",
            doc.tipo,
            listAgencyName="PE:SUNAT",
            listName="Documento relacionado al transporte",
            listURI="urn:pe:gob:sunat:cpe:see:gem:catalogos:catalogo61",
        )
        _cbc(referencia, "DocumentType", DOCUMENTO_RELACIONADO_DESCRIPCION.get(doc.tipo, doc.tipo))
        emisor = _cac(referencia, "IssuerParty")
        identificacion = _cac(emisor, "PartyIdentification")
        _cbc(identificacion, "ID", doc.ruc_emisor, schemeID=TIPO_DOC_RUC, **_ATRIB_DOC_IDENTIDAD)

    firma = _cac(raiz, "Signature")
    _cbc(firma, "ID", ID_FIRMA)
    firmante = _cac(firma, "SignatoryParty")
    _cbc(_cac(firmante, "PartyIdentification"), "ID", datos.transportista.numero_documento)
    _cbc(_cac(firmante, "PartyName"), "Name", datos.transportista.razon_social[:250])
    adjunto = _cac(firma, "DigitalSignatureAttachment")
    _cbc(_cac(adjunto, "ExternalReference"), "URI", f"#{ID_FIRMA}")

    _parte_legal(_cac(_cac(raiz, "DespatchSupplierParty"), "Party"), datos.transportista)
    _parte_legal(_cac(_cac(raiz, "DeliveryCustomerParty"), "Party"), datos.destinatario)

    envio = _cac(raiz, "Shipment")
    _cbc(envio, "ID", "SUNAT_Envio")
    _cbc(envio, "GrossWeightMeasure", f"{datos.peso_bruto_kg:.3f}", unitCode="KGM")

    etapa = _cac(envio, "ShipmentStage")
    _cbc(_cac(etapa, "TransitPeriod"), "StartDate", datos.fecha_inicio_traslado.isoformat())
    if datos.registro_mtc:
        _cbc(_cac(_cac(etapa, "CarrierParty"), "PartyLegalEntity"), "CompanyID", datos.registro_mtc[:20])
    conductor = _cac(etapa, "DriverPerson")
    _cbc(conductor, "ID", datos.conductor.dni, schemeID=TIPO_DOC_DNI, **_ATRIB_DOC_IDENTIDAD)
    _cbc(conductor, "FirstName", datos.conductor.nombres[:250])
    _cbc(conductor, "FamilyName", datos.conductor.apellidos[:250])
    _cbc(conductor, "JobTitle", "Principal")
    _cbc(_cac(conductor, "IdentityDocumentReference"), "ID", datos.conductor.licencia)

    entrega = _cac(envio, "Delivery")
    _direccion(entrega, "DeliveryAddress", datos.llegada)
    despacho = _cac(entrega, "Despatch")
    _direccion(despacho, "DespatchAddress", datos.partida)
    _parte_legal(_cac(despacho, "DespatchParty"), datos.remitente)

    unidad = _cac(envio, "TransportHandlingUnit")
    equipo = _vehiculo(unidad, "TransportEquipment", datos.vehiculo_principal)
    for secundario in datos.vehiculos_secundarios:
        _vehiculo(equipo, "AttachedTransportEquipment", secundario)

    for indice, bien in enumerate(datos.bienes, start=1):
        linea = _cac(raiz, "DespatchLine")
        _cbc(linea, "ID", str(indice))
        _cbc(linea, "DeliveredQuantity", _formato_cantidad(bien.cantidad), unitCode=bien.unidad)
        _cbc(_cac(linea, "OrderLineReference"), "LineID", str(indice))
        item = _cac(linea, "Item")
        _cbc(item, "Description", bien.descripcion[:500])
        if bien.codigo:
            _cbc(_cac(item, "SellersItemIdentification"), "ID", bien.codigo[:30])

    return raiz
