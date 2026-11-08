"""Lectura del PDF (representación impresa) de la Guía de Remisión Remitente del cliente.

A diferencia del XML, el PDF no tiene una estructura fija: cada sistema de facturación
lo diseña distinto. Se buscan los datos por los rótulos que SUNAT exige imprimir y lo que
no se encuentre queda para completar a mano. Los nombres del remitente y destinatario no
se toman del PDF sino de su RUC/DNI (RENIEC/SUNAT), que es más confiable.
"""

import io
import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from pypdf import PdfReader
from pypdf.errors import PdfReadError

from app.services.gre_ubl_service import TIPO_DOC_DNI, TIPO_DOC_RUC
from app.services.guia_remitente_service import (
    MOTIVOS_TRASLADO,
    DireccionLeida,
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


def _peso_kg(texto: str) -> Decimal | None:
    # La unidad puede ir antes ("PESO BRUTO (TNE): 28.5") o después ("28,500.00 KGM").
    coincidencia = _buscar(r"peso\s+bruto([^\d\n]{0,60}?)([\d.,]+)\s*(KGM|KG|KILOS?|TNE|TN|TONELADAS?|T)?\b", texto)
    if not coincidencia:
        return None
    numero = coincidencia.group(2)
    unidad_antes = re.search(r"\b(KGM|KG|KILOS?|TNE|TN|TONELADAS?)\b", coincidencia.group(1), re.IGNORECASE)
    unidad = (coincidencia.group(3) or (unidad_antes.group(1) if unidad_antes else "KGM")).upper()
    # 28,500.00 / 28.500,00 / 28500.5 -> Decimal
    if "," in numero and "." in numero:
        numero = numero.replace(",", "") if numero.rfind(".") > numero.rfind(",") else numero.replace(".", "").replace(",", ".")
    else:
        numero = numero.replace(",", ".")
    try:
        peso = Decimal(numero)
    except InvalidOperation:
        return None
    return peso * 1000 if unidad.startswith("T") else peso


def _direccion(rotulo: str, texto: str) -> DireccionLeida:
    linea = _linea_despues(rotulo, texto)
    if not linea:
        return DireccionLeida(ubigeo=None, direccion=None)
    ubigeo = re.search(r"\b(\d{6})\b", linea)
    direccion = re.sub(r"\(?\s*\b\d{6}\b\s*\)?", "", linea).strip(" -–,") if ubigeo else linea
    return DireccionLeida(ubigeo=ubigeo.group(1) if ubigeo else None, direccion=direccion[:250] or None)


def leer_guia_remitente_pdf(contenido: bytes, ruc_transportista: str) -> GuiaRemitenteLeida:
    texto = _texto_pdf(contenido)
    advertencias = ["Datos leídos de un PDF: revisa cada campo antes de activar el viaje."]

    if _buscar(r"TRANSPORTISTA", texto) and not _buscar(r"REMITENTE", texto):
        raise GuiaRemitenteInvalidaError("El PDF parece una guía transportista; se esperaba la guía de remisión remitente del cliente")

    series = [m for m in _RE_SERIE_NUMERO.finditer(texto) if not m.group(1).startswith("V")]
    preferidas = [m for m in series if m.group(1)[0] in "TE"]
    serie_numero = (preferidas or series or [None])[0]
    if serie_numero is None:
        raise GuiaRemitenteInvalidaError(
            "No se encontró la serie-número de la guía en el PDF. Escribe el RUC y la serie-número a mano."
        )

    ruc_emisor = _RE_RUC_EMISOR.search(texto) or re.search(rf"\b({_RE_RUC})\b", texto)
    if ruc_emisor is None:
        raise GuiaRemitenteInvalidaError("No se encontró el RUC del remitente en el PDF. Escribe el RUC y la serie-número a mano.")
    ruc = ruc_emisor.group(1)

    destinatario = None
    documento_destinatario = _numero_documento_tras(r"destinatario", texto, excluir={ruc, ruc_transportista})
    if documento_destinatario:
        destinatario = ParteLeida(tipo_documento=documento_destinatario[0], numero_documento=documento_destinatario[1], razon_social="")
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

    inicio = _buscar(rf"inicio\s+de(?:l)?\s+traslado[^\d\n]{{0,30}}{_RE_FECHA}", texto)
    emision = _buscar(rf"(?:fecha\s+(?:y\s+hora\s+)?de\s+emisi[oó]n)[^\d\n]{{0,30}}{_RE_FECHA}", texto)

    motivo_texto = _linea_despues(r"motivo\s+de(?:l)?\s+traslado", texto)
    motivo_codigo = next((c for c, d in MOTIVOS_TRASLADO.items() if motivo_texto and d.lower() in motivo_texto.lower()), None)

    if _buscar(r"transporte\s+privado", texto) and not _buscar(r"transporte\s+p[uú]blico", texto):
        advertencias.append(
            "La guía del cliente indica transporte PRIVADO: si te contrata como transportista debería indicar transporte público."
        )
    advertencias.append("Agrega los bienes transportados (el PDF no se puede leer de forma confiable por ítem).")

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
        modalidad_codigo=None,
        transportista_ruc=None,
        bienes=[],
        advertencias=advertencias,
    )
