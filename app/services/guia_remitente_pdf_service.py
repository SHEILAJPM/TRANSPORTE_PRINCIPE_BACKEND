"""Lectura del PDF (representación impresa) de la Guía de Remisión Remitente del cliente,
o del texto del "Detalle de GRE" copiado desde SUNAT SOL (Consulta de GRE).

A diferencia del XML, el PDF no tiene una estructura fija: cada sistema de facturación
lo diseña distinto. Se buscan los datos por los rótulos que SUNAT exige imprimir y lo que
no se encuentre queda para completar a mano. Los nombres del remitente y destinatario no
se toman del PDF sino de su RUC/DNI (RENIEC/SUNAT), que es más confiable.
"""

import html
import io
import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from pypdf import PdfReader
from pypdf.errors import PdfReadError

from app.services.gre_ubl_service import TIPO_DOC_DNI, TIPO_DOC_RUC
from app.utils.ubigeo import separar_ubigeo_de_direccion
from app.services.guia_remitente_service import (
    MOTIVOS_TRASLADO,
    DireccionLeida,
    BienLeido,
    GuiaRemitenteInvalidaError,
    GuiaRemitenteLeida,
    ParteLeida,
)

_PAGINAS_MAXIMAS = 3
_RE_RUC = r"(?:10|15|16|17|20)\d{9}"
_RE_SERIE_NUMERO = re.compile(r"\b([A-Z][A-Z0-9]{3})\s*[-–]\s*(\d{1,8})\b")
_RE_RUC_EMISOR = re.compile(rf"R\.?\s*U\.?\s*C\.?\s*(?:N\s*[°º.o]?)?\s*:?\s*({_RE_RUC})")
_RE_FECHA = r"(\d{2}[/-]\d{2}[/-]\d{4}|\d{4}-\d{2}-\d{2})"


def es_pdf(contenido: bytes) -> bool:
    return contenido[:5] == b"%PDF-"


def _texto_pdf(contenido: bytes) -> str:
    try:
        lector = PdfReader(io.BytesIO(contenido))
        paginas = [p.extract_text() or "" for p in lector.pages[:_PAGINAS_MAXIMAS]]
    except (PdfReadError, ValueError, KeyError) as error:
        raise GuiaRemitenteInvalidaError(f"No se pudo leer el PDF: {error}") from error
    texto = "\n".join(paginas)
    if len(re.sub(r"\s", "", texto)) < 40:
        raise GuiaRemitenteInvalidaError(
            "El PDF no tiene texto (parece una imagen escaneada). Sube el XML de la guía o escribe el RUC y la serie-número."
        )
    return texto


def _fecha(valor: str | None) -> date | None:
    if not valor:
        return None
    for formato in ("%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(valor, formato).date()
        except ValueError:
            continue
    return None


def _buscar(patron: str, texto: str) -> re.Match | None:
    return re.search(patron, texto, re.IGNORECASE | re.DOTALL)


def _linea_despues(rotulo: str, texto: str) -> str | None:
    """Texto que sigue a un rótulo en la misma línea (o en la siguiente si quedó vacío)."""
    coincidencia = _buscar(rf"{rotulo}\s*:?\s*([^\n]*)(?:\n([^\n]*))?", texto)
    if not coincidencia:
        return None
    valor = (coincidencia.group(1) or "").strip() or (coincidencia.group(2) or "").strip()
    return valor or None


def _numero_documento_tras(rotulo: str, texto: str, excluir: set[str]) -> tuple[str, str] | None:
    """Primer RUC (11) o DNI (8) que aparece después del rótulo y no está excluido."""
    inicio = _buscar(rotulo, texto)
    if not inicio:
        return None
    for coincidencia in re.finditer(rf"\b({_RE_RUC}|\d{{8}})\b", texto[inicio.end() : inicio.end() + 600]):
        numero = coincidencia.group(1)
        if numero not in excluir:
            return (TIPO_DOC_RUC if len(numero) == 11 else TIPO_DOC_DNI), numero
    return None


def _a_decimal(numero: str) -> Decimal | None:
    """28,500.00 / 28.500,00 / 5,308 (miles) / 28.5 -> Decimal."""
    if "," in numero and "." in numero:
        numero = numero.replace(",", "") if numero.rfind(".") > numero.rfind(",") else numero.replace(".", "").replace(",", ".")
    elif re.fullmatch(r"\d{1,3}(,\d{3})+", numero):
        numero = numero.replace(",", "")
    else:
        numero = numero.replace(",", ".")
    try:
        return Decimal(numero)
    except InvalidOperation:
        return None


def _peso_kg(texto: str) -> Decimal | None:
    # La unidad puede ir antes ("PESO BRUTO (TNE): 28.5"), después ("28,500.00 KGM") o en
    # su propio rótulo ("Unidad de medida del peso bruto: KGM", en el detalle de SOL).
    coincidencia = _buscar(
        r"peso\s+bruto(?:\s+total)?(?:\s+de\s+la\s+carga)?([^\d]{0,60}?)([\d.,]+)\s*(KGM|KG|KILOS?|TNE|TN|TONELADAS?|T)?\b",
        texto,
    )
    if not coincidencia:
        return None
    unidad_antes = re.search(r"\b(KGM|KG|KILOS?|TNE|TN|TONELADAS?)\b", coincidencia.group(1), re.IGNORECASE)
    unidad_rotulo = _buscar(r"unidad\s+de\s+medida\s+del\s+peso\s+bruto\s*:?\s*(KGM|TNE)", texto)
    unidad = (
        coincidencia.group(3)
        or (unidad_antes.group(1) if unidad_antes else None)
        or (unidad_rotulo.group(1) if unidad_rotulo else "KGM")
    ).upper()
    peso = _a_decimal(coincidencia.group(2))
    if peso is None:
        return None
    return peso * 1000 if unidad.startswith("T") else peso


def _direccion(rotulo: str, texto: str) -> DireccionLeida:
    linea = _linea_despues(rotulo, texto)
    if not linea:
        return DireccionLeida(ubigeo=None, direccion=None)
    ubigeo = re.search(r"\b(\d{6})\b", linea)
    if ubigeo:
        direccion = re.sub(r"\(?\s*\b\d{6}\b\s*\)?", "", linea).strip(" -–,")
        return DireccionLeida(ubigeo=ubigeo.group(1), direccion=direccion[:250] or None)
    # Sin código: se deduce de "... DEPARTAMENTO - PROVINCIA - DISTRITO" al final.
    direccion, codigo = separar_ubigeo_de_direccion(linea)
    return DireccionLeida(ubigeo=codigo, direccion=direccion[:250] or None)


_UNIDADES = r"NIU|KGM|TNE|ZZ|BX|PK|MTR|LTR|GLL|BG|BLL|SET|DZN|MIL|KT|PR|CEN|UND|UNI"


def _bienes(texto: str) -> list[BienLeido]:
    """Filas de la tabla "Bienes por transportar" del detalle de SOL: N.º, columnas de
    códigos (a menudo vacías), descripción, unidad y cantidad, separadas por tabulador."""
    bienes = []
    for linea in texto.splitlines():
        columnas = [c.strip() for c in linea.split("\t")]
        if len(columnas) >= 4 and columnas[0].isdigit():
            utiles = [c for c in columnas[1:] if c]
            if len(utiles) >= 3 and re.fullmatch(_UNIDADES, utiles[-2], re.IGNORECASE):
                cantidad = _a_decimal(utiles[-1])
                if cantidad is not None:
                    bienes.append(BienLeido(descripcion=utiles[-3][:250], cantidad=cantidad, unidad=utiles[-2].upper(), codigo=None))
                    continue
        fila = re.match(rf"^\s*\d{{1,3}}\s+(?:SI|NO)\s+(.+?)\s+({_UNIDADES})\s+([\d.,]+)\s*$", linea, re.IGNORECASE)
        if fila:
            cantidad = _a_decimal(fila.group(3))
            if cantidad is not None:
                bienes.append(BienLeido(descripcion=fila.group(1).strip()[:250], cantidad=cantidad, unidad=fila.group(2).upper(), codigo=None))
    return bienes


def _parte_con_nombre(rotulo: str, texto: str) -> tuple[str, str, str] | None:
    """'Datos del destinatario:\nCONSORCIO X - RUC N° 20616380002' -> (tipo, número, nombre)."""
    coincidencia = _buscar(
        rf"{rotulo}\s*:?\s*\n?\s*([^\n]+?)\s+[-–]\s+(RUC|DNI)\s*(?:N\s*[°º.o]?)?\s*:?\s*(\d{{11}}|\d{{8}})", texto
    )
    if not coincidencia:
        return None
    tipo = TIPO_DOC_RUC if coincidencia.group(2).upper() == "RUC" else TIPO_DOC_DNI
    return tipo, coincidencia.group(3), coincidencia.group(1).strip()


def leer_guia_remitente_pdf(contenido: bytes, ruc_transportista: str) -> GuiaRemitenteLeida:
    return leer_guia_remitente_texto(_texto_pdf(contenido), ruc_transportista, fuente="de un PDF")


def leer_guia_remitente_texto(
    texto: str, ruc_transportista: str, fuente: str = "del detalle copiado de SUNAT"
) -> GuiaRemitenteLeida:
    texto = html.unescape(texto).replace("\r\n", "\n")
    if len(re.sub(r"\s", "", texto)) < 40:
        raise GuiaRemitenteInvalidaError("El texto está vacío o incompleto: copia todo el Detalle de GRE desde SOL.")
    advertencias = [f"Datos leídos {fuente}: revisa cada campo antes de activar el viaje."]

    if _buscar(r"TRANSPORTISTA", texto) and not _buscar(r"REMITENTE", texto):
        raise GuiaRemitenteInvalidaError("Parece una guía transportista; se esperaba la guía de remisión remitente del cliente")

    series = [m for m in _RE_SERIE_NUMERO.finditer(texto) if not m.group(1).startswith("V")]
    preferidas = [m for m in series if m.group(1)[0] in "TE"]
    serie_numero = (preferidas or series or [None])[0]
    if serie_numero is None:
        raise GuiaRemitenteInvalidaError(
            "No se encontró la serie-número de la guía. Escribe el RUC y la serie-número a mano."
        )

    ruc_emisor = _RE_RUC_EMISOR.search(texto) or re.search(rf"\b({_RE_RUC})\b", texto)
    if ruc_emisor is None:
        raise GuiaRemitenteInvalidaError("No se encontró el RUC del remitente. Escribe el RUC y la serie-número a mano.")
    ruc = ruc_emisor.group(1)

    destinatario = None
    con_nombre = _parte_con_nombre(r"datos\s+del\s+destinatario", texto)
    documento_destinatario = con_nombre or _numero_documento_tras(r"destinatario", texto, excluir={ruc, ruc_transportista})
    if documento_destinatario:
        destinatario = ParteLeida(
            tipo_documento=documento_destinatario[0],
            numero_documento=documento_destinatario[1],
            razon_social=con_nombre[2] if con_nombre else "",
        )
    else:
        advertencias.append("No se encontró el documento del destinatario: complétalo a mano.")

    partida = _direccion(r"punto\s+de\s+partida", texto)
    llegada = _direccion(r"punto\s+de\s+llegada", texto)
    for nombre, punto in (("partida", partida), ("llegada", llegada)):
        if not punto.direccion:
            advertencias.append(f"No se encontró el punto de {nombre}: complétalo a mano.")
        elif not punto.ubigeo:
            advertencias.append(f"El PDF no trae el UBIGEO del punto de {nombre}: elige departamento, provincia y distrito.")

    peso = _peso_kg(texto)
    if peso is None:
        advertencias.append("No se encontró el peso bruto: complétalo a mano.")

    inicio = _buscar(rf"inicio\s+de(?:l)?\s+traslado[^\d\n]{{0,30}}{_RE_FECHA}", texto) or _buscar(
        rf"entrega\s+de\s+bienes\s+al\s+transportista[^\d\n]{{0,30}}{_RE_FECHA}", texto
    )
    emision = _buscar(rf"(?:fecha\s+(?:y\s+hora\s+)?de\s+emisi[oó]n)[^\d\n]{{0,30}}{_RE_FECHA}", texto)

    motivo_texto = _linea_despues(r"motivo\s+de(?:l)?\s+traslado", texto)
    # El más largo que calce: "Venta con entrega a terceros" antes que "Venta".
    motivo_codigo = max(
        (c for c, d in MOTIVOS_TRASLADO.items() if motivo_texto and d.lower() in motivo_texto.lower()),
        key=lambda c: len(MOTIVOS_TRASLADO[c]),
        default=None,
    )
    modalidad = _linea_despues(r"modalidad\s+de\s+traslado", texto) or ""
    modalidad_codigo = "01" if re.search(r"p[uú]blico", modalidad, re.I) else "02" if re.search(r"privado", modalidad, re.I) else None
    transportista = _parte_con_nombre(r"datos\s+del\s+transportista", texto)
    if transportista and ruc_transportista and transportista[1] != ruc_transportista:
        advertencias.append(
            f"La guía del cliente indica otro transportista (RUC {transportista[1]}), no a tu empresa: revisa que sea la guía correcta."
        )

    if _buscar(r"transporte\s+privado", texto) and not _buscar(r"transporte\s+p[uú]blico", texto):
        advertencias.append(
            "La guía del cliente indica transporte PRIVADO: si te contrata como transportista debería indicar transporte público."
        )
    bienes = _bienes(texto)
    if not bienes:
        advertencias.append("Agrega los bienes transportados: no se pudieron leer por ítem.")

    return GuiaRemitenteLeida(
        serie=serie_numero.group(1),
        numero=serie_numero.group(2).zfill(8),
        fecha_emision=_fecha(emision.group(1)) if emision else None,
        remitente=ParteLeida(tipo_documento=TIPO_DOC_RUC, numero_documento=ruc, razon_social=""),
        destinatario=destinatario,
        partida=partida,
        llegada=llegada,
        peso_bruto_kg=peso,
        numero_bultos=None,
        fecha_inicio_traslado=_fecha(inicio.group(1)) if inicio else None,
        motivo_codigo=motivo_codigo,
        motivo_descripcion=MOTIVOS_TRASLADO.get(motivo_codigo) if motivo_codigo else motivo_texto,
        modalidad_codigo=modalidad_codigo,
        transportista_ruc=transportista[1] if transportista else None,
        bienes=bienes,
        advertencias=advertencias,
    )
