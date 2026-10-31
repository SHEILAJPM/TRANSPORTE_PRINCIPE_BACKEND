"""Lectura del XML de la Guía de Remisión Remitente (tipo 09) que entrega el cliente,
para prellenar el viaje y la guía transportista que la referencia."""

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation

from lxml import etree
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.cliente import Cliente
from app.models.enums import TipoDocumentoIdentidad
from app.services.gre_ubl_service import NS_CAC, NS_CBC, TIPO_DOC_DNI, TIPO_DOC_RUC
from app.utils.xml_seguro import parsear_xml

TAMANO_MAXIMO_BYTES = 2 * 1024 * 1024

_NS = {"cac": NS_CAC, "cbc": NS_CBC}

# Catálogo 20 (motivo de traslado)
MOTIVOS_TRASLADO = {
    "01": "Venta",
    "02": "Compra",
    "03": "Venta con entrega a terceros",
    "04": "Traslado entre establecimientos de la misma empresa",
    "05": "Consignación",
    "06": "Devolución",
    "07": "Recojo de bienes transformados",
    "08": "Importación",
    "09": "Exportación",
    "13": "Otros",
    "14": "Venta sujeta a confirmación del comprador",
    "17": "Traslado de bienes para transformación",
    "18": "Traslado emisor itinerante CP",
}

_TIPO_DOCUMENTO_CLIENTE = {TIPO_DOC_RUC: TipoDocumentoIdentidad.RUC, TIPO_DOC_DNI: TipoDocumentoIdentidad.DNI}


class GuiaRemitenteInvalidaError(Exception):
    """El archivo no es una guía de remitente que se pueda usar para el viaje."""


@dataclass
class ParteLeida:
    tipo_documento: str  # Catálogo 06
    numero_documento: str
    razon_social: str


@dataclass
class DireccionLeida:
    ubigeo: str | None
    direccion: str | None


@dataclass
class BienLeido:
    descripcion: str
    cantidad: Decimal
    unidad: str
    codigo: str | None


@dataclass
class GuiaRemitenteLeida:
    serie: str
    numero: str
    fecha_emision: date | None
    remitente: ParteLeida
    destinatario: ParteLeida | None
    partida: DireccionLeida
    llegada: DireccionLeida
    peso_bruto_kg: Decimal | None
    numero_bultos: int | None
    fecha_inicio_traslado: date | None
    motivo_codigo: str | None
    motivo_descripcion: str | None
    modalidad_codigo: str | None  # Catálogo 18: "01" público, "02" privado
    transportista_ruc: str | None
    bienes: list[BienLeido] = field(default_factory=list)
    advertencias: list[str] = field(default_factory=list)


def _texto(nodo: etree._Element, ruta: str) -> str | None:
    valor = nodo.xpath(f"string({ruta})", namespaces=_NS).strip()
    return valor or None


def _fecha(valor: str | None) -> date | None:
    try:
        return date.fromisoformat(valor) if valor else None
    except ValueError:
        return None


def _parte(raiz: etree._Element, ruta_party: str) -> ParteLeida | None:
    numero = _texto(raiz, f"{ruta_party}/cac:PartyIdentification/cbc:ID")
    if not numero:
        return None
    return ParteLeida(
        tipo_documento=_texto(raiz, f"{ruta_party}/cac:PartyIdentification/cbc:ID/@schemeID") or "",
        numero_documento=numero,
        razon_social=_texto(raiz, f"{ruta_party}/cac:PartyLegalEntity/cbc:RegistrationName") or "",
    )


def leer_guia_remitente(contenido: bytes, ruc_transportista: str) -> GuiaRemitenteLeida:
    if len(contenido) > TAMANO_MAXIMO_BYTES:
        raise GuiaRemitenteInvalidaError("El archivo es demasiado grande para ser una guía de remisión (máx. 2 MB)")

    raiz = parsear_xml(contenido)
    if etree.QName(raiz).localname != "DespatchAdvice":
        raise GuiaRemitenteInvalidaError("El XML no es una guía de remisión electrónica (DespatchAdvice)")
    tipo = _texto(raiz, "/*/cbc:DespatchAdviceTypeCode")
    if tipo != "09":
        raise GuiaRemitenteInvalidaError(
            f"El XML es una guía tipo {tipo or 'desconocido'}; se esperaba una guía de remisión remitente (tipo 09)"
        )

    identificador = _texto(raiz, "/*/cbc:ID") or ""
    if "-" not in identificador:
        raise GuiaRemitenteInvalidaError(f"La numeración de la guía ({identificador!r}) no tiene el formato SERIE-NÚMERO")
    serie, numero = identificador.split("-", 1)

    remitente = _parte(raiz, "/*/cac:DespatchSupplierParty/cac:Party")
    if remitente is None:
        raise GuiaRemitenteInvalidaError("La guía no indica el documento del remitente")

    envio = "/*/cac:Shipment"
    advertencias: list[str] = []

    peso: Decimal | None = None
    peso_texto = _texto(raiz, f"{envio}/cbc:GrossWeightMeasure")
    if peso_texto:
        try:
            peso = Decimal(peso_texto)
            if _texto(raiz, f"{envio}/cbc:GrossWeightMeasure/@unitCode") == "TNE":
                peso *= 1000
        except InvalidOperation:
            advertencias.append(f"No se pudo leer el peso bruto ({peso_texto!r})")

    bultos_texto = _texto(raiz, f"{envio}/cbc:TotalTransportHandlingUnitQuantity")
    motivo = _texto(raiz, f"{envio}/cbc:HandlingCode")
    modalidad = _texto(raiz, f"{envio}/cac:ShipmentStage/cbc:TransportModeCode")
    transportista_ruc = _texto(raiz, f"{envio}/cac:ShipmentStage/cac:CarrierParty/cac:PartyIdentification/cbc:ID")

    if modalidad == "02":
        advertencias.append(
            "La guía del cliente indica transporte PRIVADO (02): si te contrata como transportista debería indicar "
            "transporte público (01). Confírmalo con el cliente."
        )
    if transportista_ruc and transportista_ruc != ruc_transportista:
        advertencias.append(
            f"La guía del cliente indica como transportista el RUC {transportista_ruc}, que no es el de tu empresa"
        )

    bienes = []
    for linea in raiz.xpath("/*/cac:DespatchLine", namespaces=_NS):
        cantidad_texto = _texto(linea, "cbc:DeliveredQuantity") or "1"
        try:
            cantidad = Decimal(cantidad_texto)
        except InvalidOperation:
            cantidad = Decimal(1)
        bienes.append(
            BienLeido(
                descripcion=_texto(linea, "cac:Item/cbc:Description") or "Sin descripción",
                cantidad=cantidad,
                unidad=_texto(linea, "cbc:DeliveredQuantity/@unitCode") or "NIU",
                codigo=_texto(linea, "cac:Item/cac:SellersItemIdentification/cbc:ID"),
            )
        )

    leida = GuiaRemitenteLeida(
        serie=serie,
        numero=numero,
        fecha_emision=_fecha(_texto(raiz, "/*/cbc:IssueDate")),
        remitente=remitente,
        destinatario=_parte(raiz, "/*/cac:DeliveryCustomerParty/cac:Party"),
        partida=DireccionLeida(
            ubigeo=_texto(raiz, f"{envio}/cac:Delivery/cac:Despatch/cac:DespatchAddress/cbc:ID"),
            direccion=_texto(raiz, f"{envio}/cac:Delivery/cac:Despatch/cac:DespatchAddress/cac:AddressLine/cbc:Line"),
        ),
        llegada=DireccionLeida(
            ubigeo=_texto(raiz, f"{envio}/cac:Delivery/cac:DeliveryAddress/cbc:ID"),
            direccion=_texto(raiz, f"{envio}/cac:Delivery/cac:DeliveryAddress/cac:AddressLine/cbc:Line"),
        ),
        peso_bruto_kg=peso,
        numero_bultos=int(bultos_texto) if bultos_texto and bultos_texto.isdigit() else None,
        fecha_inicio_traslado=_fecha(_texto(raiz, f"{envio}/cac:ShipmentStage/cac:TransitPeriod/cbc:StartDate")),
        motivo_codigo=motivo,
        motivo_descripcion=MOTIVOS_TRASLADO.get(motivo or "") or _texto(raiz, f"{envio}/cbc:HandlingInstructions"),
        modalidad_codigo=modalidad,
        transportista_ruc=transportista_ruc,
        bienes=bienes,
        advertencias=advertencias,
    )

    if leida.destinatario is None:
        advertencias.append("La guía no indica destinatario: complétalo antes de emitir")
    for nombre, direccion in (("partida", leida.partida), ("llegada", leida.llegada)):
        if not direccion.ubigeo or not direccion.direccion:
            advertencias.append(f"La guía no trae completo el punto de {nombre} (UBIGEO y dirección)")
    if peso is None:
        advertencias.append("La guía no indica el peso bruto total")

    return leida


async def obtener_o_crear_cliente_remitente(db: AsyncSession, remitente: ParteLeida) -> Cliente:
    """El remitente de la guía es quien contrata el flete: si no está registrado como
    cliente, se crea con los datos que trae la propia guía (sin consultar a terceros)."""
    tipo = _TIPO_DOCUMENTO_CLIENTE.get(remitente.tipo_documento)
    if tipo is None:
        raise GuiaRemitenteInvalidaError(
            f"El remitente tiene un tipo de documento ({remitente.tipo_documento!r}) que no se puede registrar como cliente"
        )

    existente = (
        await db.execute(select(Cliente).where(Cliente.numero_documento == remitente.numero_documento))
    ).scalar_one_or_none()
    if existente is not None:
        return existente

    cliente = Cliente(
        tipo_documento=tipo,
        numero_documento=remitente.numero_documento,
        razon_social=remitente.razon_social[:255] or remitente.numero_documento,
        fuente_datos="GUIA_REMITENTE",
    )
    db.add(cliente)
    await db.flush()
    return cliente
