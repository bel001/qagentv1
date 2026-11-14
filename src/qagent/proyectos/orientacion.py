"""Orientación local por objetivo, independiente de modelos y credenciales."""

from __future__ import annotations

from typing import Any


def orientar_funcion(
    funcion: dict[str, Any], no_soportada: str | None
) -> dict[str, Any]:
    """Explica prioridades sin cambiar selección ni asegurar que un test pueda generarse."""
    if no_soportada:
        dato = {"categoria": "no_soportada", "motivo": no_soportada}
    elif funcion.get("aptitud_pruebas"):
        dato = dict(funcion["aptitud_pruebas"])
    elif funcion.get("docstring") and funcion.get("tipada"):
        dato = {
            "categoria": "recomendada",
            "motivo": "Tiene tipos y documentación; revisa que describan un resultado esperado verificable.",
        }
    else:
        dato = {
            "categoria": "revisar",
            "motivo": "No hay suficiente información estática para priorizarla; puede requerir contrato o preparación adicional.",
        }
    return {**dato, "origen": "reglas", "tokens": 0}


def resumir_orientacion(modulos: list[dict[str, Any]]) -> dict[str, Any]:
    """Agrupa las sugerencias y conserva la ubicación de lógica no seleccionable."""
    resumen = {"recomendada": 0, "revisar": 0, "no_soportada": 0}
    metodos = []
    for modulo in modulos:
        for funcion in modulo.get("funciones", []):
            resumen[funcion["orientacion_prueba"]["categoria"]] += 1
        metodos.extend(
            {"modulo": modulo["ruta"], **metodo}
            for metodo in modulo.get("metodos_no_seleccionables", [])
        )
    return {
        "origen": "reglas",
        "tokens": 0,
        "resumen": resumen,
        "metodos_no_seleccionables": metodos,
    }
