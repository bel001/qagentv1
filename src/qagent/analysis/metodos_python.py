"""Métodos públicos de las clases Python como objetivos (backlog 11, ADR-017).

Lectura estática con tree-sitter: nunca se importa ni se ejecuta el código.

Cada método público (sin ``_`` inicial) de una clase de nivel superior se describe
como una función más, con ``nombre`` ``Clase.metodo``, ``tipo_metodo``
(``instancia``, ``estatico`` o ``clase``) y los parámetros sin ``self`` ni
``cls``. Los de instancia llevan además ``constructor``: cómo construir la clase.

Una clase se construye solo si su constructor recibe **datos** (números, textos,
booleanos, ``None``, colecciones y sus ``Optional``) o tiene valores por defecto. Si
no, el método queda con ``no_soportada`` y el nombre y tipo del parámetro que QAgent
no sabe construir: no se adivina cómo crear un repositorio, un cliente o una sesión.
"""

from __future__ import annotations

import re
from typing import Any

from tree_sitter import Node, Tree

from qagent.analysis import arbol_ts, texto_ts
from qagent.analysis.analyzer import _extraer_funcion
from qagent.analysis.rutas import sentencias_modulo

#: Tipos que son datos: se pueden escribir como literales en el contrato.
TIPOS_DATOS = frozenset(
    {
        "int",
        "float",
        "complex",
        "str",
        "bytes",
        "bool",
        "None",
        "list",
        "dict",
        "tuple",
        "set",
        "frozenset",
        "List",
        "Dict",
        "Tuple",
        "Set",
        "FrozenSet",
        "Optional",
        "Union",
        "Literal",
        "Sequence",
        "Mapping",
        "typing",
    }
)
#: Decoradores con los que un método no se ofrece todavía, con su motivo.
_DECORADORES_FUERA = {
    "property": "es una propiedad: se lee como atributo, no se llama como método",
    "cached_property": "es una propiedad: se lee como atributo, no se llama como método",
    "setter": "es el setter de una propiedad",
    "deleter": "es el deleter de una propiedad",
    "abstractmethod": "es abstracto: no tiene una implementación que probar",
    "overload": "es una declaración @overload, sin implementación",
}
#: Bases cuyos campos anotados son los argumentos del constructor.
_BASES_CON_CAMPOS = frozenset({"BaseModel", "NamedTuple", "TypedDict"})
#: Bases que no aportan constructor.
_BASES_NEUTRAS = frozenset({"object", "ABC", "Generic", "Protocol"})
_IDENTIFICADOR = re.compile(r"[A-Za-z_]\w*")


def _ultimo(nombre: str) -> str:
    return nombre.rsplit(".", 1)[-1]


def _nombres_decoradores(nodo: Node) -> list[str]:
    """``@functools.cached_property`` -> ``cached_property``; ``@x.setter`` -> ``setter``."""
    nombres = []
    for decorador in arbol_ts.decoradores(arbol_ts.definicion(nodo)):
        expresion = arbol_ts.sin_envoltura(decorador)
        if expresion is not None and expresion.type == "call":
            expresion = expresion.child_by_field_name("function")
        if expresion is not None:
            nombres.append(_ultimo(arbol_ts.texto(expresion)))
    return nombres


def _bases(clase: Node) -> list[str]:
    argumentos = clase.child_by_field_name("superclasses")
    if argumentos is None:
        return []
    return [
        _ultimo(re.sub(r"\[.*\]", "", arbol_ts.texto(a)))
        for a in arbol_ts.nombrados(argumentos)
        if a.type != "keyword_argument"
    ]


def es_tipo_dato(anotacion: str | None) -> bool:
    """Si la anotación solo usa tipos de datos (``Optional[list[int]]`` sí; ``Repo`` no)."""
    if not anotacion:
        return False
    sin_literales = re.sub(r"(['\"]).*?\1", "", anotacion)
    nombres = set(_IDENTIFICADOR.findall(sin_literales))
    return bool(nombres) and nombres <= TIPOS_DATOS


def _motivo_parametro(nombre: str, tipo: str | None) -> str:
    descripcion = f"`{nombre}: {tipo}`" if tipo else f"`{nombre}` sin tipo"
    return (
        f"el constructor recibe {descripcion}, que no es un dato simple: QAgent no "
        "construye esa dependencia sin adivinar cómo. Dale un valor por defecto o "
        "anótalo con un tipo de datos (int, str, list...)"
    )


def _construibles(parametros: list[dict[str, Any]]) -> str | None:
    """Motivo por el que no se puede construir con esos parámetros, o None."""
    for parametro in parametros:
        nombre = parametro["nombre"]
        if nombre.startswith("*"):
            continue  # *args y **kwargs son opcionales
        if parametro.get("por_defecto") is not None:
            continue
        if not es_tipo_dato(parametro.get("tipo")):
            return _motivo_parametro(nombre, parametro.get("tipo"))
    return None


def _campos_anotados(cuerpo: Node | None) -> list[dict[str, Any]]:
    """Campos ``x: int`` y ``x: int = 0`` del cuerpo (dataclass, BaseModel...)."""
    campos = []
    for sentencia in arbol_ts.sentencias(cuerpo):
        if sentencia.type != "expression_statement":
            continue
        asignacion = next(iter(arbol_ts.nombrados(sentencia)), None)
        if asignacion is None or asignacion.type != "assignment":
            continue
        izquierda = asignacion.child_by_field_name("left")
        tipo = asignacion.child_by_field_name("type")
        if izquierda is None or tipo is None or izquierda.type != "identifier":
            continue
        tipo_texto = texto_ts.expresion(tipo) or arbol_ts.texto(tipo)
        if "ClassVar" in tipo_texto:
            continue
        valor = asignacion.child_by_field_name("right")
        campos.append(
            {
                "nombre": arbol_ts.texto(izquierda),
                "tipo": tipo_texto,
                "por_defecto": texto_ts.expresion(valor) if valor is not None else None,
            }
        )
    return campos


def _firma_de_campos(clase: str, campos: list[dict[str, Any]]) -> str:
    partes = []
    for campo in campos:
        parte = f"{campo['nombre']}: {campo['tipo']}"
        if campo.get("por_defecto") is not None:
            parte += f" = {campo['por_defecto']}"
        partes.append(parte)
    return f"{clase}({', '.join(partes)})"


def constructor_de_clase(nodo: Node) -> dict[str, Any]:
    """Cómo construir la clase: firma, parámetros, docstring y motivo si no se puede."""
    clase = arbol_ts.definicion(nodo)
    nombre = arbol_ts.nombre(clase)
    cuerpo = arbol_ts.cuerpo(clase)
    docstring = texto_ts.docstring(cuerpo)
    init = next(
        (
            s
            for s in arbol_ts.sentencias(cuerpo)
            if arbol_ts.es_funcion(s)
            and arbol_ts.nombre(arbol_ts.definicion(s)) == "__init__"
        ),
        None,
    )
    bases = _bases(clase)
    if init is not None:
        datos = _extraer_funcion(init)
        parametros = datos["parametros"][1:]  # sin self
        return {
            "firma": f"{nombre}{datos['firma'].replace('(self, ', '(').replace('(self)', '()')}",
            "parametros": parametros,
            "docstring": datos["docstring"] or docstring,
            "motivo": _construibles(parametros),
        }
    if "dataclass" in _nombres_decoradores(nodo) or set(bases) & _BASES_CON_CAMPOS:
        campos = _campos_anotados(cuerpo)
        return {
            "firma": _firma_de_campos(nombre, campos),
            "parametros": campos,
            "docstring": docstring,
            "motivo": _construibles(campos),
        }
    if any(b.endswith("Enum") or b in ("Flag", "IntFlag") for b in bases):
        return {
            "firma": nombre,
            "parametros": [],
            "docstring": docstring,
            "motivo": "es un Enum: sus valores no se construyen con argumentos",
        }
    heredadas = [b for b in bases if b not in _BASES_NEUTRAS]
    if heredadas:
        return {
            "firma": nombre,
            "parametros": [],
            "docstring": docstring,
            "motivo": (
                f"hereda el constructor de {heredadas[0]}, que QAgent no lee para "
                "saber con qué argumentos construir la clase"
            ),
        }
    return {
        "firma": f"{nombre}()",
        "parametros": [],
        "docstring": docstring,
        "motivo": None,
    }


def _tipo_metodo(decoradores: list[str]) -> str:
    if "staticmethod" in decoradores:
        return "estatico"
    if "classmethod" in decoradores:
        return "clase"
    return "instancia"


def metodos_publicos(
    arbol: Tree,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Métodos públicos de las clases de nivel superior.

    Returns:
        (métodos que son objetivos, métodos que no se ofrecen con su motivo).
    """
    metodos: list[dict[str, Any]] = []
    fuera: list[dict[str, Any]] = []
    for nodo in sentencias_modulo(arbol.root_node):
        if not arbol_ts.es_clase(nodo):
            continue
        clase = arbol_ts.nombre(arbol_ts.definicion(nodo))
        if clase.startswith("_"):
            continue
        constructor = None
        for miembro in arbol_ts.sentencias(arbol_ts.cuerpo(arbol_ts.definicion(nodo))):
            if not arbol_ts.es_funcion(miembro):
                continue
            nombre = arbol_ts.nombre(arbol_ts.definicion(miembro))
            if nombre.startswith("_"):
                continue
            decoradores = _nombres_decoradores(miembro)
            motivo_fuera = next(
                (m for d, m in _DECORADORES_FUERA.items() if d in decoradores), None
            )
            if motivo_fuera is not None:
                fuera.append(
                    {
                        "clase": clase,
                        "nombre": nombre,
                        "linea": arbol_ts.linea(arbol_ts.definicion(miembro)),
                        "motivo": motivo_fuera[0].upper() + motivo_fuera[1:] + ".",
                    }
                )
                continue
            datos = _extraer_funcion(miembro)
            tipo = _tipo_metodo(decoradores)
            parametros = datos["parametros"]
            if tipo != "estatico" and parametros:
                parametros = parametros[1:]  # sin self ni cls
            metodo = {
                **datos,
                "nombre": f"{clase}.{nombre}",
                "clase": clase,
                "metodo": nombre,
                "tipo_metodo": tipo,
                "parametros": parametros,
                "tipada": datos["retorno"] is not None
                and all(p["tipo"] for p in parametros),
            }
            if tipo == "instancia":
                constructor = constructor or constructor_de_clase(nodo)
                metodo["constructor"] = {
                    k: constructor[k] for k in ("firma", "parametros", "docstring")
                }
                if constructor["motivo"]:
                    metodo["no_soportada"] = (
                        f"método de instancia de {clase}: {constructor['motivo']}"
                    )
            metodos.append(metodo)
    return metodos, fuera


def nodo_de_metodo(arbol: Tree, objetivo: str) -> tuple[Node, Node] | None:
    """(clase, método) de ``Clase.metodo`` en el nivel superior del módulo, o None."""
    if objetivo.count(".") != 1:
        return None
    clase_buscada, metodo_buscado = objetivo.split(".")
    for nodo in sentencias_modulo(arbol.root_node):
        if not arbol_ts.es_clase(nodo):
            continue
        clase = arbol_ts.definicion(nodo)
        if arbol_ts.nombre(clase) != clase_buscada:
            continue
        for miembro in arbol_ts.sentencias(arbol_ts.cuerpo(clase)):
            if (
                arbol_ts.es_funcion(miembro)
                and arbol_ts.nombre(arbol_ts.definicion(miembro)) == metodo_buscado
            ):
                return nodo, miembro
    return None
