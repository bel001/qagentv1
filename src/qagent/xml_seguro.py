"""XML acotado, sin DTD ni entidades, usando únicamente la biblioteca estándar."""

import xml.etree.ElementTree as ET


def parsear_xml(texto: str) -> ET.Element:
    """Rechaza expansiones y documentos excesivos antes de construir el árbol."""
    if len(texto.encode("utf-8")) > 10_000_000:
        raise ET.ParseError("El XML supera el tamaño máximo permitido.")
    if "<!DOCTYPE" in texto or "<!ENTITY" in texto:
        raise ET.ParseError("No se admiten DTD ni entidades XML.")
    return ET.fromstring(texto)  # noqa: S314 -- tamaño y declaraciones validados arriba
