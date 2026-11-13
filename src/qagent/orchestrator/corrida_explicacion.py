"""Explicaciones del Agente Explicador dentro de una corrida (EP-10, ADR-008)."""

from __future__ import annotations

import json
from typing import Any

from qagent.agents.explicador import RedactorIA
from qagent.llm import TokenTracker
from qagent.llm.fabrica import ConfiguracionLLMIncompleta
from qagent.orchestrator.corrida_modelo import (
    ResumenCorrida,
    _ContextoIA,
    _registro,
)
from qagent.storage.registro import (
    PERFIL_HUMO,
    RutasCorrida,
    actualizar_consumo,
)


def _modulo_corrida():
    """Módulo principal, donde las pruebas reemplazan `escribir_corrida` y otras."""
    from qagent.orchestrator import corrida

    return corrida


def _docstrings(
    modulos: list[dict[str, Any]],
) -> dict[tuple[str, str], str | None]:
    """Docstring de cada función y endpoint analizado, por `(modulo, objetivo)`."""
    docstrings: dict[tuple[str, str], str | None] = {}
    for modulo in modulos:
        for funcion in modulo.get("funciones") or []:
            docstrings[(modulo["ruta"], funcion["nombre"])] = funcion.get("docstring")
        for endpoint in modulo.get("endpoints") or []:
            docstrings[(modulo["ruta"], endpoint["objetivo"])] = endpoint.get(
                "docstring"
            )
    return docstrings


def _explicar(
    rutas: RutasCorrida,
    resumen: ResumenCorrida,
    perfil: str,
    configuracion: Any,
    tracker: TokenTracker | None = None,
    ia: _ContextoIA | None = None,
) -> None:
    """Explicaciones de los hallazgos en `explicaciones.json` (HU-32, ADR-008).

    Lee los results.json y detalle.json ya escritos y no toca nada más: si el
    Explicador falla, se registra en el log y la corrida termina igual. Se omite en
    una corrida cancelada, en el perfil Humo o si está desactivado en `config.toml`.
    Con `modo = "ia"` (#166) cada explicación la redacta el LLM, la plantilla queda
    de respaldo y sus tokens se suman a log.json, results.json y el resumen.
    """
    explicador = getattr(configuracion, "explicador", None)
    if (
        resumen.cancelada
        or perfil == PERFIL_HUMO
        or (explicador is not None and not explicador.activo)
    ):
        return
    try:
        results = json.loads(rutas.results.read_text(encoding="utf-8"))
        detalle = None
        if rutas.detalle is not None and rutas.detalle.is_file():
            detalle = json.loads(rutas.detalle.read_text(encoding="utf-8"))
        llamadas_antes = len(tracker.llamadas) if tracker is not None else 0
        redactor = _redactor_ia(explicador, configuracion, tracker, ia, resumen)
        resultado = _modulo_corrida().explicar_corrida(
            results, detalle, redactor, ia.docstrings if ia is not None else None
        )
        for motivo in resultado.respaldos:
            _registro.warning(
                "Explicación con plantilla en la corrida %s: %s", resumen.run_id, motivo
            )
        for motivo in resultado.descartadas:
            _registro.warning(
                "Explicación descartada en la corrida %s: %s", resumen.run_id, motivo
            )
        _modulo_corrida().escribir_explicaciones(rutas.carpeta, resultado.datos)
        if tracker is not None and len(tracker.llamadas) > llamadas_antes:
            actualizar_consumo(rutas, tracker)
            resumen.tokens = tracker.total_tokens
            resumen.tokens_reales = tracker.total_tokens_reales
            resumen.tokens_estimados = tracker.total_tokens_estimados
            resumen.costo_usd = round(tracker.total_costo_usd, 8)
    except Exception as error:  # noqa: BLE001 — el Explicador nunca tumba la corrida
        _registro.warning(
            "El Explicador falló en la corrida %s: %s", resumen.run_id, error
        )


def _redactor_ia(
    explicador: Any,
    configuracion: Any,
    tracker: TokenTracker | None,
    ia: _ContextoIA | None,
    resumen: ResumenCorrida,
) -> RedactorIA | None:
    """El redactor con IA si `modo = "ia"`; None (plantillas) si no se puede usar.

    Sin clave o sin URL del proveedor se usa la plantilla y el motivo va al log.
    """
    if (
        explicador is None
        or explicador.modo != "ia"
        or explicador.precio is None
        or tracker is None
        or ia is None
    ):
        return None
    try:
        cliente = _modulo_corrida().crear_cliente(
            explicador.precio,
            ia.claves,
            simulado=ia.simulado,
            timeout_s=explicador.tiempo_maximo_s,
        )
    except ConfiguracionLLMIncompleta as error:
        _registro.warning(
            "El Explicador usa la plantilla en la corrida %s: %s",
            resumen.run_id,
            error,
        )
        return None
    presupuesto = configuracion.presupuesto
    return RedactorIA(
        cliente,
        tracker,
        explicador.precio,
        tiempo_maximo_s=explicador.tiempo_maximo_s,
        max_tokens=getattr(presupuesto, "max_tokens_por_corrida", None),
        tope_usd=getattr(presupuesto, "tope_por_corrida_usd", None),
        es_simulado=ia.simulado,
        cancelado=ia.cancelado,
    )
