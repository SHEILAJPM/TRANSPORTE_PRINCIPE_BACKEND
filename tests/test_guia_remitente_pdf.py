"""Lectura del PDF de la guía de remitente del cliente (dos formatos de ejemplo)."""

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from app.services.guia_remitente_pdf_service import es_pdf, leer_guia_remitente_pdf
from app.services.guia_remitente_service import GuiaRemitenteInvalidaError

FIXTURES = Path(__file__).parent / "fixtures"
RUC_TRANSPORTISTA = "10106693451"


def _leer(nombre: str):
    return leer_guia_remitente_pdf((FIXTURES / nombre).read_bytes(), RUC_TRANSPORTISTA)


def test_formato_sunat_sol():
    g = _leer("guia_remitente_sol.pdf")
    assert (g.serie, g.numero, g.remitente.numero_documento) == ("EG07", "00000123", "20999999999")
    assert (g.destinatario.tipo_documento, g.destinatario.numero_documento) == ("6", "20555555555")
    assert g.peso_bruto_kg == Decimal("28500.00")
    assert (g.fecha_emision, g.fecha_inicio_traslado) == (date(2026, 11, 5), date(2026, 11, 6))
    assert g.partida.ubigeo == "150119" and g.partida.direccion.startswith("AV. INDUSTRIAL 123")
    # Sin código en el PDF, el UBIGEO sale de "AREQUIPA - AREQUIPA - AREQUIPA".
    assert g.llegada.ubigeo == "040101" and g.llegada.direccion == "AV. EJERCITO 100"
    assert g.motivo_codigo == "01"
    assert not any("UBIGEO del punto de llegada" in a for a in g.advertencias)


def test_formato_privado_con_dni_y_toneladas():
    g = _leer("guia_remitente_privado.pdf")
    assert (g.serie, g.numero, g.remitente.numero_documento) == ("T001", "00000456", "20999999999")
    assert (g.destinatario.tipo_documento, g.destinatario.numero_documento) == ("1", "12345678")
    assert g.peso_bruto_kg == Decimal("28500.0")  # "PESO BRUTO (TNE): 28.5" -> kg
    assert g.llegada.ubigeo == "120101" and g.partida.direccion == "CAL. LOS PINOS 45 - ATE - LIMA"
    assert g.fecha_inicio_traslado == date(2026, 11, 6)


def test_no_confunde_al_transportista_con_el_destinatario():
    g = _leer("guia_remitente_sol.pdf")
    assert g.destinatario.numero_documento != RUC_TRANSPORTISTA


def test_rechaza_pdf_invalido():
    assert es_pdf((FIXTURES / "guia_remitente_sol.pdf").read_bytes())
    assert not es_pdf(b"<?xml version='1.0'?>")
    with pytest.raises(GuiaRemitenteInvalidaError):
        leer_guia_remitente_pdf(b"%PDF-1.4 roto", RUC_TRANSPORTISTA)
