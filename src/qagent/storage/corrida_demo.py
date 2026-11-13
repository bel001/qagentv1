"""Datos simulados de la corrida #8841-B para demostración y exportación en escritorio (HU-22).

Cuando la aplicación de escritorio corre en modo demostración (sin Docker activo),
materializa `.qagent/runs/8841-B/results.json`, `detalle.json` y `run.json` con los
mismos datos que muestra la pantalla para que `exportar_informe` genere archivos reales
(`.pdf`, `.md` y `.json`) a partir de `results.json`.
"""

from __future__ import annotations

import copy
import json
import os
import tempfile
from pathlib import Path
from typing import Any

from qagent import contracts
from qagent.contracts import ContratoInvalido
from qagent.storage.registro import ARCHIVO_DETALLE, CARPETA_RUNS
from qagent.storage.vista_ejecucion import ARCHIVO, ResultadosNoDisponibles

CORRIDA_DEMO_ID = "8841-B"
_RUN_ID_VALIDACION = "20260925-143200-8841"
_FECHA_DEMO = "2026-09-25T14:32:00-05:00"

_RUTA_DATOS = Path(__file__).with_name("datos_demo.json")
with _RUTA_DATOS.open(encoding="utf-8") as _archivo:
    _DATOS_DEMO: dict[str, Any] = json.load(_archivo)

_FUNCIONES_DEMO: tuple[dict[str, Any], ...] = tuple(_DATOS_DEMO["funciones"])
_SPECS_DEMO: tuple[dict[str, Any], ...] = tuple(_DATOS_DEMO["specs"])
_ENTORNO_DEMO: dict[str, Any] = _DATOS_DEMO["entorno"]
_INTENTOS_DEMO: dict[str, list[dict[str, Any]]] = _DATOS_DEMO["intentos"]


def _construir_intentos_demo(
    f: dict[str, Any], entorno: dict[str, Any]
) -> list[dict[str, Any]]:
    """Copia los intentos guardados y fija el entorno indicado."""
    intentos = copy.deepcopy(_INTENTOS_DEMO.get(f["funcion"], []))
    for intento in intentos:
        ejecucion = intento.get("ejecucion")
        if ejecucion is not None:
            ejecucion["entorno"] = copy.deepcopy(entorno)
    return intentos


def construir_archivos_demo(
    raiz_proyecto: str | Path, run_id: str = CORRIDA_DEMO_ID
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Construye los diccionarios `results.json`, `detalle.json` y `run.json` de la demo."""
    proyecto = str(Path(raiz_proyecto).resolve())
    objetivos = []
    funciones_detalle = []
    totales_casos = {
        "total": 0,
        "pasaron": 0,
        "fallaron": 0,
        "errores": 0,
        "omitidos": 0,
    }

    for f in _FUNCIONES_DEMO:
        tok_p, tok_g, tok_r = f["tokens"]
        ms = f["mutation_score"]
        objetivos.append(
            {
                "modulo": f["modulo"],
                "funcion": f["funcion"],
                "critical": f["critical"],
                "decision": f["decision"],
                "motivo_estancado": f["motivo_estancado"],
                "laundering_detectado": f["laundering_detectado"],
                "duracion_s": f["duracion_s"],
                "controles": {
                    "sintaxis": True,
                    "sandbox": not (
                        f["decision"] == "stalled" and not f["laundering_detectado"]
                    ),
                    "aserciones": not f["laundering_detectado"]
                    and f["decision"] != "bug_detectado",
                    "cobertura": f["lineas"] >= 60.0 and f["ramas"] >= 60.0,
                    "mutation": (ms >= 60.0)
                    if (f["critical"] and ms is not None)
                    else None,
                },
                "metricas": {
                    "paso": f["paso"],
                    "cobertura_lineas": f["lineas"],
                    "cobertura_ramas": f["ramas"],
                    "iteraciones": f["iteraciones"],
                    "tokens_por_agente": {
                        "planner": {"prompt_tokens": tok_p, "completion_tokens": 0},
                        "generator": {"prompt_tokens": tok_g, "completion_tokens": 0},
                        "reviewer": {"prompt_tokens": tok_r, "completion_tokens": 0},
                    },
                    "mutation_score": ms,
                },
            }
        )
        intentos = _construir_intentos_demo(f, _ENTORNO_DEMO)
        for i in intentos:
            ej = i.get("ejecucion")
            if ej and ej.get("totales"):
                t = ej["totales"]
                for k in totales_casos:
                    totales_casos[k] += t.get(k, 0)
                break
        funciones_detalle.append(
            {
                "modulo": f["modulo"],
                "funcion": f["funcion"],
                "contrato": copy.deepcopy(f["contrato"]),
                "codigo": f["codigo"],
                "traza": f["traza"],
                "intentos": intentos,
            }
        )

    results: dict[str, Any] = {
        "version": "1",
        "tipo": "results",
        "run_id": run_id,
        "fecha": _FECHA_DEMO,
        "proyecto": proyecto,
        "perfil": "deep",
        "rama": "main",
        "modelos": {
            "planner": {
                "proveedor": "Anthropic",
                "modelo": "Modelo de contexto amplio",
                "precio_entrada_usd_m": 5.0,
                "precio_salida_usd_m": 5.0,
            },
            "generator": {
                "proveedor": "Xiaomi",
                "modelo": "Modelo económico",
                "precio_entrada_usd_m": 0.6,
                "precio_salida_usd_m": 0.6,
            },
            "reviewer": {
                "proveedor": "OpenAI",
                "modelo": "Modelo económico",
                "precio_entrada_usd_m": 0.6,
                "precio_salida_usd_m": 0.6,
            },
        },
        "estado_final": "fin",
        "motivo_fallo": None,
        "es_simulado": True,
        "objetivos": objetivos,
        "resumen": {
            "total_funciones": 9,
            "aceptadas": 6,
            "bugs_detectados": 1,
            "stalled": 2,
            "sin_veredicto": 0,
            "pass_rate": 66.7,
            "cobertura_lineas_promedio": 88.9,
            "cobertura_ramas_promedio": 82.1,
            "iteraciones_promedio": 1.67,
            "costo_total_usd": 0.14193,
            "por_agente": {
                "planner": {
                    "prompt_tokens": 12825,
                    "completion_tokens": 0,
                    "costo_usd": 0.064125,
                    "llamadas": 2,
                },
                "generator": {
                    "prompt_tokens": 94050,
                    "completion_tokens": 0,
                    "costo_usd": 0.05643,
                    "llamadas": 15,
                },
                "reviewer": {
                    "prompt_tokens": 35625,
                    "completion_tokens": 0,
                    "costo_usd": 0.021375,
                    "llamadas": 15,
                },
            },
            "metas": {
                "pass_rate_min": 70.0,
                "cobertura_lineas_min": 60.0,
                "iteraciones_promedio_max": 2.0,
                "tope_por_corrida_usd": 1.48,
            },
        },
    }

    copia_validacion = {**results, "run_id": _RUN_ID_VALIDACION}
    contracts.validar(contracts.RUN_LOG, copia_validacion)

    detalle: dict[str, Any] = {
        "version": "1",
        "tipo": "detalle",
        "run_id": run_id,
        "entorno": copy.deepcopy(_ENTORNO_DEMO),
        "totales_casos": totales_casos,
        "funciones": funciones_detalle,
    }
    contracts.validar(contracts.DETALLE, detalle)
    run_meta: dict[str, Any] = {
        "run_id": run_id,
        "inicio": _FECHA_DEMO,
        "fin": _FECHA_DEMO,
        "tipos_prueba": ["funcion"],
        "imagen_docker": None,
        "estado": "fin",
        "resumen": {"pasaron": 6, "fallaron": 3},
        "specs": [dict(s) for s in _SPECS_DEMO],
    }
    return results, detalle, run_meta


def asegurar_corrida_demo(
    raiz_proyecto: str | Path, run_id: str = CORRIDA_DEMO_ID
) -> Path:
    """Garantiza que exista `.qagent/runs/<run_id>/results.json` y `detalle.json`."""
    carpeta = Path(raiz_proyecto) / CARPETA_RUNS / Path(run_id).name
    carpeta.mkdir(parents=True, exist_ok=True)
    ruta_results = carpeta / ARCHIVO
    ruta_detalle = carpeta / ARCHIVO_DETALLE
    ruta_run = carpeta / "run.json"

    results, detalle, run_meta = construir_archivos_demo(raiz_proyecto, run_id=run_id)

    necesita_detalle = not ruta_detalle.is_file()
    if not necesita_detalle:
        try:
            d_existente = json.loads(ruta_detalle.read_text(encoding="utf-8"))
            if not d_existente.get("entorno") or not d_existente.get("totales_casos"):
                necesita_detalle = True
        except (OSError, json.JSONDecodeError):
            necesita_detalle = True

    if not ruta_results.is_file():
        _escribir_json_atomico(ruta_results, results)
    if necesita_detalle:
        _escribir_json_atomico(ruta_detalle, detalle)
    if not ruta_run.is_file():
        _escribir_json_atomico(ruta_run, run_meta)
    return carpeta


def leer_results_demo(
    raiz_proyecto: str | Path, run_id: str = CORRIDA_DEMO_ID
) -> dict[str, Any]:
    """Asegura y lee el `results.json` de la corrida de demostración `#8841-B`."""
    carpeta = asegurar_corrida_demo(raiz_proyecto, run_id=run_id)
    ruta = carpeta / ARCHIVO
    try:
        datos = json.loads(ruta.read_text(encoding="utf-8"))
        copia = {**datos, "run_id": _RUN_ID_VALIDACION}
        contracts.validar(contracts.RUN_LOG, copia)
    except (OSError, json.JSONDecodeError, ContratoInvalido) as error:
        raise ResultadosNoDisponibles(f"{ruta} no es válido: {error}") from error
    if datos.get("tipo") != "results":
        raise ResultadosNoDisponibles(f"{ruta} no es un archivo de resultados.")
    return datos


def _escribir_json_atomico(ruta: Path, datos: dict[str, Any]) -> None:
    descriptor, temporal = tempfile.mkstemp(
        prefix=f".{ruta.name}.", suffix=".tmp", dir=ruta.parent
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as archivo:
            json.dump(datos, archivo, indent=2, ensure_ascii=False)
        os.replace(temporal, ruta)
    except BaseException:
        Path(temporal).unlink(missing_ok=True)
        raise
