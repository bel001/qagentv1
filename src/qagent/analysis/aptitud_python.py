"""Señales estáticas para orientar la selección; no prometen un oráculo verificable."""

from __future__ import annotations

import re
from typing import Any

from tree_sitter import Node, Tree

from qagent.analysis import arbol_ts as ts
from qagent.analysis.rutas import sentencias_modulo

_TIPOS_DATOS = frozenset(
    [
        "int",
        "float",
        "str",
        "bool",
        "list",
        "dict",
        "tuple",
        "set",
        "frozenset",
        "None",
        "Any",
        "Optional",
        "Union",
        "Literal",
        "Sequence",
        "Mapping",
        "Iterable",
        "Iterator",
        "typing",
        "collections",
        "abc",
    ]
)
_BUILTINS = frozenset(
    [
        "len",
        "str",
        "int",
        "float",
        "bool",
        "dict",
        "list",
        "tuple",
        "set",
        "frozenset",
        "sum",
        "min",
        "max",
        "abs",
        "round",
        "sorted",
        "all",
        "any",
        "enumerate",
        "range",
        "zip",
        "isinstance",
        "issubclass",
        "reversed",
        "Exception",
        "ValueError",
        "TypeError",
        "KeyError",
        "IndexError",
        "RuntimeError",
    ]
)
_EXTERNOS = {
    "requests",
    "httpx",
    "urllib",
    "socket",
    "sqlalchemy",
    "sqlite3",
    "pymongo",
    "psycopg",
    "redis",
    "subprocess",
    "os",
    "pathlib",
    "time",
    "datetime",
    "random",
    "secrets",
    "uuid",
    "shutil",
    "io",
}


def _nodos_propios(nodo: Node):
    """Recorre un cuerpo sin atribuirle el contenido de funciones o clases anidadas."""
    pendientes = list(reversed(nodo.named_children))
    while pendientes:
        hijo = pendientes.pop()
        if ts.es_funcion(hijo) or ts.es_clase(hijo):
            continue
        yield hijo
        pendientes.extend(reversed(hijo.named_children))


def _importaciones(arbol: Tree) -> dict[str, str]:
    enlaces = {}
    for nodo in sentencias_modulo(arbol.root_node):
        dato = ts.importacion(nodo)
        if dato is None:
            continue
        for nombre, alias in dato.nombres:
            if nombre != "*":
                enlaces[alias or nombre.split(".")[0]] = (
                    f"{dato.modulo}.{nombre}" if dato.desde else nombre
                )
    return enlaces


def _motivo(funcion: dict[str, Any], nodo: Node, enlaces: dict[str, str]) -> str | None:
    """Señala preparación necesaria, sin excluir ni ejecutar la función."""
    anotacion = funcion.get("retorno") or ""
    tipos = set(re.findall(r"[A-Za-z_]\w*", anotacion))
    if tipos - _TIPOS_DATOS:
        return (
            f"Devuelve un objeto de tipo {anotacion}. Puede ser una fábrica o un "
            "proveedor de dependencias; obtener el objeto no prueba la lógica del servicio. "
            "Revisa qué resultado verificable esperas antes de usar IA."
        )
    cuerpo = ts.cuerpo(nodo)
    locales = {p["nombre"].lstrip("*") for p in funcion.get("parametros", [])}
    if cuerpo is not None:
        for propio in _nodos_propios(cuerpo):
            if propio.type in {"assignment", "for_statement"}:
                destino = propio.child_by_field_name("left")
                if destino is not None:
                    locales.update(
                        ts.texto(n)
                        for n in ts.recorrer(destino)
                        if n.type == "identifier"
                    )
    for propio in _nodos_propios(cuerpo) if cuerpo is not None else []:
        if propio.type == "return_statement" and propio.named_children:
            valor = propio.named_children[0]
            if valor.type == "identifier" and ts.texto(valor) not in locales:
                return "Devuelve un valor u objeto definido fuera de la función; revisa si entrega un servicio o depende de estado compartido."
        if propio.type in {"yield", "await", "global_statement", "nonlocal_statement"}:
            return "Usa ejecución asíncrona, un generador o estado compartido; puede necesitar preparación adicional."
        if propio.type == "attribute":
            nombre = ts.texto(propio)
            if "environ" in nombre.split("."):
                return "Consulta variables del entorno; prepara sus valores para obtener resultados repetibles."
        if propio.type != "call":
            continue
        destino = propio.child_by_field_name("function")
        llamada = ts.texto(destino) if destino is not None else ""
        raiz = llamada.split(".")[0]
        origen = enlaces.get(raiz, raiz).split(".")[0]
        if llamada in {"open", "input", "print"} or origen in _EXTERNOS:
            return (
                f"Usa {llamada or origen}: puede depender de archivos, red, base de datos, "
                "reloj, azar o estado externo. Revisa qué debe simularse antes de generar pruebas."
            )
        if raiz[:1].isupper() and raiz not in _BUILTINS:
            return (
                f"Construye {llamada}. Puede entregar un servicio u otro objeto; "
                "revisa su contrato y dónde está la lógica que quieres probar."
            )
    return None


def anotar_aptitud(modulo: dict[str, Any], arbol: Tree) -> None:
    """Anota prioridades orientativas y métodos todavía no seleccionables, con cero IA."""
    nodos = list(sentencias_modulo(arbol.root_node))
    funciones = {ts.nombre(n): ts.definicion(n) for n in nodos if ts.es_funcion(n)}
    enlaces = _importaciones(arbol)
    for funcion in modulo.get("funciones", []):
        nodo = funciones.get(funcion["nombre"])
        if nodo is None:
            continue
        motivo = _motivo(funcion, nodo, enlaces)
        cuerpo = ts.cuerpo(nodo)
        llamadas = [
            ts.texto(destino)
            for n in (_nodos_propios(cuerpo) if cuerpo is not None else [])
            if n.type == "call"
            and (destino := n.child_by_field_name("function")) is not None
        ]
        desconocidas = [c for c in llamadas if c not in _BUILTINS]
        if motivo is None and desconocidas:
            motivo = "Llama a otras funciones u objetos; revisa sus dependencias y el contrato del resultado."
        if motivo is None and funcion.get("es_async"):
            motivo = "Es asíncrona; revisa sus dependencias y la preparación del entorno de pruebas."
        funcion["aptitud_pruebas"] = {
            "categoria": "revisar" if motivo else "recomendada",
            "motivo": motivo
            or (
                "Contiene lógica con datos y operaciones simples, sin llamadas externas detectadas. "
                "Es una candidata para empezar; la IA aún debe proponer casos con evidencia válida."
            ),
        }

    # Backlog 11: los métodos que ya son objetivos no se listan como no seleccionables.
    ofrecidos = {f["nombre"] for f in modulo.get("funciones", [])}
    metodos = list(modulo.get("metodos_no_seleccionables") or [])
    listados = {(m["clase"], m["nombre"]) for m in metodos}
    for nodo in nodos:
        if not ts.es_clase(nodo):
            continue
        for miembro in ts.sentencias(ts.cuerpo(nodo)):
            if not ts.es_funcion(miembro) or ts.nombre(miembro).startswith("_"):
                continue
            clave = (ts.nombre(nodo), ts.nombre(miembro))
            if f"{clave[0]}.{clave[1]}" in ofrecidos or clave in listados:
                continue
            metodos.append(
                {"clase": clave[0], "nombre": clave[1], "linea": ts.linea(miembro)}
            )
    if metodos:
        modulo["metodos_no_seleccionables"] = metodos
