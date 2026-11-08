"""Texto del "Detalle de GRE" copiado desde SUNAT SOL (Consulta de GRE)."""

from datetime import date
from decimal import Decimal

from app.services.guia_remitente_pdf_service import leer_guia_remitente_texto
from app.utils.ubigeo import separar_ubigeo_de_direccion

DETALLE_SOL = """Detalle de GRE

×
QUIVY PLAST E.I.R.L.
Fecha y hora de emisión: 06/11/2026 03:52 PM
Fecha y hora de CDR: 06/11/2026 04:00 PM
RUC N° 20610407685
GUÍA DE REMISIÓN ELECTRÓNICA REMITENTE
N° T001 - 00000645
Fecha de entrega de bienes al transportista: 06/11/2026
Motivo de traslado: Venta
Punto de partida: CAL.VISCOTIMETROS MZA. F3 LOTE. 5 A.V. PARQUE INDUSTRIAL (ESPALDA UNIVERSIDAD TELESUP) LIMA - LIMA - ANCON
Punto de llegada: NRO. S/N C.P. ANCASH - HUARI - CHAVIN DE HUANTAR
Datos del destinatario:
CONSORCIO EJECUTOR PACCHA - RUC N° 20616380002
Bienes por transportar
Nº\tBien normalizado\tCódigo bien\tCódigo producto SUNAT\tCódigo subpartida nacional\tCódigo GTIN\tDescripción detallada\tUnidad de medida\tCantidad
1\tNO\t\t\t\t\tMANG. HDPE ISO4427 SDR17 PE100 PN10 110MM (4&quot;) X 100 MTS NEGRO\tNIU\t12
2\tNO\t\t\t\t\tMANG. HDPE ISO4427 SDR17 PE100 PN10 90MM (3&quot;) X 100 MTS NEGRO\tNIU\t8
3\tNO\t\t\t\t\tMANG. HDPE ISO4427 SDR17 PE100 PN10 75MM (21/2&quot;) X 100 MTS NEGRO\tNIU\t7
4\tNO\t\t\t\t\tMANG. HDPE ISO4427 SDR17 PE100 PN10 32MM (1&quot;) X 100 MTS NEGRO -\tNIU\t60
5\tNO\t\t\t\t\tMANG. HDPE ISO4427 SDR17 PE100 PN10 25MM (3/4&quot;) X 100 MTS NEGRO\tNIU\t5
Unidad de medida del peso bruto:
KGM
Peso bruto total de la carga:
5,308
Datos del traslado
Modalidad de traslado: Público
Indicador de transbordo programado: No
Datos del Transportista
PRINCIPE MOGOLLON NILTON EDU - RUC N° 10106693451
Número de registro MTC: 15M24056066E
Observaciones
Esta es una representación impresa sin valor tributario de la Guía de Remisión Electrónica, generada en el sistema de la SUNAT. Puede verificarla utilizando su clave SOL
"""


def test_lee_todo_el_detalle_de_sol():
    guia = leer_guia_remitente_texto(DETALLE_SOL, ruc_transportista="10106693451")

    assert (guia.serie, guia.numero) == ("T001", "00000645")
    assert guia.remitente.numero_documento == "20610407685"
    assert guia.fecha_emision == date(2026, 11, 6)
    assert guia.fecha_inicio_traslado == date(2026, 11, 6)
    assert guia.motivo_codigo == "01"
    assert guia.modalidad_codigo == "01"
    assert guia.transportista_ruc == "10106693451"

    assert guia.destinatario.numero_documento == "20616380002"
    assert guia.destinatario.razon_social == "CONSORCIO EJECUTOR PACCHA"

    assert guia.partida.ubigeo == "150102"  # Lima - Lima - Ancón
    assert guia.partida.direccion.endswith("(ESPALDA UNIVERSIDAD TELESUP)")
    assert guia.llegada.ubigeo == "021004"  # Áncash - Huari - Chavín de Huántar

    assert guia.peso_bruto_kg == Decimal("5308")  # "5,308" son miles, no decimales

    assert len(guia.bienes) == 5
    assert guia.bienes[0].descripcion == 'MANG. HDPE ISO4427 SDR17 PE100 PN10 110MM (4") X 100 MTS NEGRO'
    assert (guia.bienes[0].unidad, guia.bienes[0].cantidad) == ("NIU", Decimal("12"))
    assert guia.bienes[3].cantidad == Decimal("60")
    assert not any("otro transportista" in a for a in guia.advertencias)


def test_avisa_si_el_transportista_es_otro():
    guia = leer_guia_remitente_texto(DETALLE_SOL, ruc_transportista="20999999999")
    assert any("otro transportista" in a for a in guia.advertencias)


def test_ubigeo_por_nombres():
    assert separar_ubigeo_de_direccion("AV. X 123 MADRE DE DIOS - TAMBOPATA - TAMBOPATA") == ("AV. X 123", "170101")
    assert separar_ubigeo_de_direccion("JR. SIN DISTRITO 123") == ("JR. SIN DISTRITO 123", None)
