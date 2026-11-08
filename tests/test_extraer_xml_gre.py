"""SUNAT puede devolver la GRE consultada como XML, ZIP o JSON con base64."""

import base64
import json

from app.services.sunat_gre_api_service import empaquetar_zip, extraer_xml

XML = b'<?xml version="1.0"?><DespatchAdvice>x</DespatchAdvice>'


def test_xml_directo_y_zip():
    assert extraer_xml(XML) == XML
    assert extraer_xml(empaquetar_zip("20123456789-09-T001-1", XML)) == XML


def test_json_con_zip_o_xml_en_base64():
    zip_b64 = base64.b64encode(empaquetar_zip("g", XML)).decode()
    assert extraer_xml(json.dumps({"archivo": {"arcGreZip": zip_b64}}).encode()) == XML
    xml_b64 = base64.b64encode(XML * 3).decode()
    assert extraer_xml(json.dumps({"data": xml_b64}).encode()) == XML * 3


def test_respuesta_sin_xml():
    assert extraer_xml(b'{"cod":"404","msg":"no existe"}') is None
    assert extraer_xml(b"") is None
