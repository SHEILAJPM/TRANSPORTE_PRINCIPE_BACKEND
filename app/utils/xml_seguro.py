from lxml import etree


class XmlInvalidoError(Exception):
    """El contenido no es un XML bien formado."""


def parsear_xml(contenido: bytes) -> etree._Element:
    """Parsea XML que viene de terceros (guías de clientes, CDR de SUNAT) sin
    resolver entidades, sin DTD y sin acceso a red (evita XXE y "billion laughs")."""
    parser = etree.XMLParser(resolve_entities=False, no_network=True, load_dtd=False, huge_tree=False)
    try:
        return etree.fromstring(contenido, parser=parser)
    except etree.XMLSyntaxError as error:
        raise XmlInvalidoError(f"El archivo no es un XML válido: {error}") from error
