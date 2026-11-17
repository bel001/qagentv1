"""Identidad de un método Java en contratos, selección, pruebas y regresión (backlog 2).

Un método sin sobrecargas se identifica como siempre: ``Clase.metodo``. Así las
specs, las pruebas guardadas y las huellas que ya existen siguen valiendo sin
migrarlas.

Un método sobrecargado se identifica con los tipos de sus parámetros:
``Clase.metodo(String,int)``. Los tipos van con su nombre simple, sin genéricos
(``List<String>`` es ``List``) y con ``[]`` para arrays y varargs, que es como los
distingue la JVM. Si dos sobrecargas quedan con la misma identidad (tipos con el
mismo nombre simple en paquetes distintos), ninguna se ofrece: no se elige por
conjetura.
"""

from __future__ import annotations

import re
from typing import Any

_ANOTACION = re.compile(r"@[\w$.]+(?:\([^()]*\))?\s*")
_GENERICO = re.compile(r"<[^<>]*>")
_OBJETIVO = re.compile(r"^(?P<base>[^()]+?)(?:\((?P<tipos>[^()]*)\))?$")
#: Descriptor JVM de un parámetro: arrays, primitivo o referencia `Lpaquete/Clase;`.
_DESCRIPTOR = re.compile(r"\[*(?:[BCDFIJSZ]|L[^;]+;)")
_PRIMITIVOS_JVM = {
    "B": "byte",
    "C": "char",
    "D": "double",
    "F": "float",
    "I": "int",
    "J": "long",
    "S": "short",
    "Z": "boolean",
}


def tipo_simple(tipo: str) -> str:
    """``final java.util.List<String>...`` -> ``List[]``: nombre simple sin genéricos."""
    texto = _ANOTACION.sub("", str(tipo or "")).replace("final ", "")
    while "<" in texto:
        anterior, texto = texto, _GENERICO.sub("", texto)
        if texto == anterior:
            break
    texto = texto.replace(" ", "")
    dimensiones = 0
    if texto.endswith("..."):
        texto, dimensiones = texto[:-3], 1
    while texto.endswith("[]"):
        texto, dimensiones = texto[:-2], dimensiones + 1
    return texto.rsplit(".", 1)[-1] + "[]" * dimensiones


def identidad(base: str, parametros: list[dict[str, Any]]) -> str:
    """``Clase.metodo(T1,T2)`` a partir de los parámetros del análisis."""
    tipos = ",".join(tipo_simple(p.get("tipo") or "") for p in parametros)
    return f"{base}({tipos})"


def separar(objetivo: str) -> tuple[str, list[str] | None]:
    """``A.f(String,int)`` -> (``A.f``, [``String``, ``int``]); sin firma, (``A.f``, None)."""
    encontrado = _OBJETIVO.fullmatch(str(objetivo).strip())
    if encontrado is None:
        return str(objetivo), None
    tipos = encontrado.group("tipos")
    if tipos is None:
        return encontrado.group("base"), None
    return encontrado.group("base"), [t for t in tipos.split(",") if t]


def base_de(objetivo: str) -> str:
    """``Clase.metodo`` sin la lista de tipos."""
    return separar(objetivo)[0]


def metodo_de(objetivo: str) -> str:
    """Nombre del método, sin clase ni tipos."""
    return base_de(objetivo).rsplit(".", 1)[-1]


def es_sobrecarga(objetivo: str) -> bool:
    """Si el objetivo lleva la lista de tipos: el método está sobrecargado."""
    return separar(objetivo)[1] is not None


def tipos_de_descriptor(descriptor: str) -> list[str] | None:
    """``(Ljava/lang/String;[I)V`` -> [``String``, ``int[]``]; None si no se entiende."""
    encontrado = re.fullmatch(r"\((?P<parametros>[^)]*)\).*", descriptor or "")
    if encontrado is None:
        return None
    tipos = []
    for pieza in _DESCRIPTOR.findall(encontrado.group("parametros")):
        dimensiones = len(pieza) - len(pieza.lstrip("["))
        base = pieza.lstrip("[")
        nombre = (
            _PRIMITIVOS_JVM[base]
            if base in _PRIMITIVOS_JVM
            else base[1:-1].rsplit("/", 1)[-1].rsplit("$", 1)[-1]
        )
        tipos.append(nombre + "[]" * dimensiones)
    if "".join(_DESCRIPTOR.findall(encontrado.group("parametros"))) != encontrado.group(
        "parametros"
    ):
        return None
    return tipos


#: Literal exacto que exige cada tipo en la llamada a una sobrecarga, para que Java
#: elija esa versión y no otra (con `f(int)` y `f(long)`, `f(1)` llama a la primera).
_LITERAL_DE_TIPO = {
    "int": "un entero sin sufijo (1)",
    "Integer": "un entero sin sufijo (1)",
    "short": "un entero sin sufijo (1)",
    "Short": "un entero sin sufijo (1)",
    "byte": "un entero sin sufijo (1)",
    "Byte": "un entero sin sufijo (1)",
    "long": "un entero con sufijo L (1L)",
    "Long": "un entero con sufijo L (1L)",
    "double": "un decimal sin sufijo (1.0)",
    "Double": "un decimal sin sufijo (1.0)",
    "float": "un decimal con sufijo f (1.0f)",
    "Float": "un decimal con sufijo f (1.0f)",
    "boolean": "true o false",
    "Boolean": "true o false",
    "char": "un carácter entre comillas simples ('a')",
    "Character": "un carácter entre comillas simples ('a')",
    "String": 'un texto entre comillas ("a")',
}


def literal_esperado(tipo: str) -> str | None:
    """Cómo debe escribirse un argumento de ese tipo en una sobrecarga; None si da igual."""
    return _LITERAL_DE_TIPO.get(tipo_simple(tipo))


def literal_del_tipo(tipo_nodo: str, texto: str, tipo: str) -> bool:
    """Si el literal (tipo de nodo tree-sitter y texto) es exactamente de ``tipo``.

    Solo se exige para primitivos, sus envoltorios y String; con otros tipos
    devuelve True (el literal ya se comprobó contra la entrada del caso).
    """
    simple = tipo_simple(tipo)
    if simple not in _LITERAL_DE_TIPO:
        return True
    if tipo_nodo.endswith("integer_literal"):
        largo = texto.rstrip().endswith(("l", "L"))
        if simple in ("long", "Long"):
            return largo
        return not largo and simple in (
            "int",
            "Integer",
            "short",
            "Short",
            "byte",
            "Byte",
        )
    if tipo_nodo == "decimal_floating_point_literal":
        flotante = texto.rstrip().endswith(("f", "F"))
        if simple in ("float", "Float"):
            return flotante
        return not flotante and simple in ("double", "Double")
    if tipo_nodo in ("true", "false"):
        return simple in ("boolean", "Boolean")
    if tipo_nodo == "character_literal":
        return simple in ("char", "Character")
    if tipo_nodo == "string_literal":
        return simple == "String"
    return False
