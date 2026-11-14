"""Reconoce componentes Reflex por anotaciones importadas, sin ejecutar el proyecto."""

from __future__ import annotations

from typing import Any

from tree_sitter import Tree

from qagent.analysis import arbol_ts
from qagent.analysis.rutas import sentencias_modulo

MOTIVO_REFLEX = (
    "Componente de interfaz Reflex: QAgent no tiene un ejecutor de componentes "
    "Reflex. Se conserva en la exploración, pero no se generan pruebas ni se "
    "infiere su contrato. Agregar un docstring no habilita ese soporte. "
    "Puedes probar por separado la lógica Python que utiliza."
)


def marcar_componentes_reflex(modulo: dict[str, Any], arbol: Tree) -> None:
    """Marca solo retornos Component/BaseComponent con procedencia Reflex comprobada.

    No basta el nombre ``rx``, un nombre de función o importar Reflex en el archivo.
    Las anotaciones ambiguas y los alias reasignados se conservan como funciones.
    """
    enlaces: dict[str, str] = {}
    nodos = list(sentencias_modulo(arbol.root_node))
    for nodo in nodos:
        importado = arbol_ts.importacion(nodo)
        if importado is not None:
            for nombre, alias in importado.nombres:
                if nombre == "*":
                    continue
                if importado.desde:
                    if importado.nivel:
                        continue
                    completo = f"{importado.modulo}.{nombre}"
                    local = alias or nombre
                else:
                    completo = nombre if alias else nombre.split(".")[0]
                    local = alias or nombre.split(".")[0]
                if nodo.parent is not None and nodo.parent.type != "module":
                    enlaces.pop(local, None)
                    continue
                enlaces[local] = completo
        elif nodo.type == "expression_statement":
            for hijo in nodo.named_children:
                if hijo.type in {"assignment", "augmented_assignment"}:
                    izquierda = hijo.child_by_field_name("left")
                    if izquierda is not None:
                        for identificador in arbol_ts.recorrer(izquierda):
                            if identificador.type == "identifier":
                                enlaces.pop(arbol_ts.texto(identificador), None)
        elif arbol_ts.es_funcion(nodo) or nodo.type == "class_definition":
            enlaces.pop(arbol_ts.nombre(nodo), None)
        elif nodo.type in {"for_statement", "with_statement"}:
            destino = nodo.child_by_field_name("left")
            if destino is None:
                destino = nodo.child_by_field_name("clause")
            if destino is not None:
                for identificador in arbol_ts.recorrer(destino):
                    if identificador.type == "identifier":
                        enlaces.pop(arbol_ts.texto(identificador), None)

    por_nombre = {f["nombre"]: f for f in modulo.get("funciones", [])}
    for nodo in nodos:
        if not arbol_ts.es_funcion(nodo):
            continue
        funcion = arbol_ts.definicion(nodo)
        retorno = funcion.child_by_field_name("return_type")
        if retorno is None:
            continue
        anotacion = arbol_ts.texto(retorno).strip().strip("\"'")
        partes = anotacion.split(".")
        origen = enlaces.get(partes[0])
        if origen is None:
            continue
        completo = ".".join([origen, *partes[1:]])
        if completo not in {
            "reflex.Component",
            "reflex.BaseComponent",
            "reflex.components.component.Component",
            "reflex.components.component.BaseComponent",
        }:
            continue
        info = por_nombre.get(arbol_ts.nombre(funcion))
        if info is not None:
            info["no_soportada"] = MOTIVO_REFLEX
            info["framework_ui"] = "reflex"
