"""Informe en JSON (`results_<run_id>.json`) de una corrida (HU-22)."""

from __future__ import annotations

import copy
import json
from collections.abc import Mapping
from typing import Any

from qagent.storage.informe_comun import (
    Claves,
    _sanitizar_estructura,
    normalizar_opciones,
    sanitizar_secretos,
)
from qagent.storage.informe_datos import _resumen_casos_planner
from qagent.storage.informe_ejecucion import _json_ejecucion
from qagent.storage.informe_pdf import BANDEJA
from qagent.storage.informe_salud import _salud_proyecto


def construir_json_informe(
    datos: dict[str, Any],
    opciones: Mapping[str, Any] | None = None,
    claves: Claves | None = None,
) -> str:
    """Construye el archivo `results_<run_id>.json` con las cifras de `results.json`."""
    opts = normalizar_opciones(opciones)
    base = copy.deepcopy(datos["results"])
    if datos.get("contexto_automatico"):
        base["contexto_automatico"] = copy.deepcopy(datos["contexto_automatico"])

    # Eliminar costos monetarios y precios de tokens de la salida JSON para personas
    if "resumen" in base and isinstance(base["resumen"], dict):
        base["resumen"].pop("costo_total_usd", None)
        base["resumen"].pop("tope_por_corrida_usd", None)
        base["resumen"].pop("precio_entrada_usd_m", None)
        base["resumen"].pop("precio_salida_usd_m", None)

    if "modelos" in base and isinstance(base["modelos"], dict):
        for m in base["modelos"].values():
            if isinstance(m, dict):
                m.pop("precio_entrada_usd_m", None)
                m.pop("precio_salida_usd_m", None)

    specs_clean = copy.deepcopy(datos.get("specs") or {})
    if "texto" in specs_clean:
        specs_clean["texto"] = specs_clean["texto"].split(" · guardados en")[0]
    base["specs"] = specs_clean

    tok_por_etapa = {
        ag: {
            "tokens": (datos.get("costo_por_agente") or {}).get(ag, {}).get("tokens", 0)
        }
        for ag in ("planner", "generator", "reviewer")
    }
    base["costo_por_agente"] = tok_por_etapa
    base["tokens_por_etapa"] = tok_por_etapa
    base["metricas"] = copy.deepcopy(datos["metricas"])
    base["salud_proyecto"] = _salud_proyecto(datos)
    base["etapas"] = {
        "modelos": copy.deepcopy(base.get("modelos", {})),
        "tokens_por_etapa": tok_por_etapa,
        "roles": {
            "analizando": "Analiza el AST del código, firmas, docstrings y dependencias para deducir casos de prueba.",
            "escribiendo_pruebas": "Escribe las suites de pruebas pytest en un sandbox aislado.",
            "verificando": "Ejecuta las pruebas en sandbox Docker y verifica los resultados.",
        },
    }
    base["agentes"] = base["etapas"]
    if datos.get("comparacion") is not None:
        base["comparacion_corridas"] = copy.deepcopy(datos["comparacion"])

    if opts["detalle"]:
        base["ejecucion"] = _json_ejecucion(datos, opts["trazas"])
        detalles_fn = []
        for fn in datos["funciones"]:
            nom = str(fn.get("identificador") or fn.get("funcion") or "Función")
            etiqueta_bandeja = BANDEJA.get(
                str(fn.get("estado")), BANDEJA["sin_veredicto"]
            )[1]
            item: dict[str, Any] = {
                "modulo": fn["modulo"],
                "funcion": fn["funcion"],
                "identificador": nom,
                "estado": fn["estado"],
                "estado_legible": etiqueta_bandeja,
            }
            if opts["trazas"]:
                item["traza"] = fn.get("traza")
            if opts["codigo"]:
                item["codigo"] = fn.get("codigo")
            if opts["contratos"]:
                item["contrato"] = fn.get("contrato")

            contrato_fn = fn.get("contrato") or {}
            casos_plan = _resumen_casos_planner(contrato_fn)
            tok_ag = fn.get("tokens_por_agente") or {}
            info_analisis = {
                "firma": fn.get("firma") or contrato_fn.get("firma") or fn["funcion"],
                "critical": bool(fn.get("critical")),
                "total_casos_planificados": len(casos_plan),
                "casos_planificados": casos_plan,
                "llama_a": contrato_fn.get("llama_a", []),
                "tokens": (
                    (tok_ag.get("planner") or {}).get("tokens", 0)
                    if isinstance(tok_ag.get("planner"), dict)
                    else tok_ag.get("planner", 0)
                ),
            }
            info_pruebas = {
                "archivo_test": f"tests/test_{fn['funcion']}.py",
                "iteraciones": fn.get("iteraciones", 1),
                "aislamiento": "sandbox_docker_sin_red",
                "codigo": fn.get("codigo") if opts["codigo"] else None,
                "tokens": (
                    (tok_ag.get("generator") or {}).get("tokens", 0)
                    if isinstance(tok_ag.get("generator"), dict)
                    else tok_ag.get("generator", 0)
                ),
            }
            info_verificacion = {
                "veredicto": etiqueta_bandeja,
                "criterio_conservado": not bool(fn.get("laundering_detectado")),
                "cobertura_lineas": fn.get("cobertura_lineas"),
                "cobertura_ramas": fn.get("cobertura_ramas"),
                "intentos": fn.get("intentos", []),
                "tokens": (
                    (tok_ag.get("reviewer") or {}).get("tokens", 0)
                    if isinstance(tok_ag.get("reviewer"), dict)
                    else tok_ag.get("reviewer", 0)
                ),
            }
            item["analisis"] = info_analisis
            item["pruebas"] = info_pruebas
            item["verificacion"] = info_verificacion
            item["planner"] = info_analisis
            item["generator"] = info_pruebas
            item["reviewer"] = info_verificacion

            ejecucion_fn = fn.get("ejecucion") or {}
            casos_fallidos = [
                {
                    "nombre": c.get("nombre"),
                    "resultado": c.get("resultado"),
                    "archivo": c.get("archivo"),
                    "linea": c.get("linea"),
                    "esperado": c.get("esperado"),
                    "obtenido": c.get("obtenido"),
                    "mensaje": c.get("mensaje"),
                }
                for c in ejecucion_fn.get("casos", [])
                if c.get("resultado") in ("fallo", "error")
            ]
            item["errores"] = {
                "hay_incidente": not fn.get("verde", True) or bool(fn.get("traza")),
                "estado": fn.get("estado"),
                "motivo_fallo": fn.get("motivo_fallo"),
                "casos_fallidos": casos_fallidos,
                "traza": fn.get("traza") if opts["trazas"] else None,
            }
            ubicacion_fallo = None
            if not fn.get("verde", True):
                for c in ejecucion_fn.get("casos", []):
                    if c.get("archivo"):
                        ubicacion_fallo = f"{c['archivo']}:{c.get('linea')}"
                        break
                if not ubicacion_fallo:
                    ubicacion_fallo = f"{fn['modulo']}::{fn['funcion']}"
            motivo_fallo = fn.get("motivo_fallo") or (
                "Se bloqueó un intento de debilitar pruebas (aserciones relajadas)"
                if fn.get("laundering_detectado")
                else (
                    "Defecto confirmado en código"
                    if fn.get("estado") == "bug_detectado"
                    else (
                        "Fallo detectado durante la validación"
                        if not fn.get("verde", True)
                        else None
                    )
                )
            )
            item["diagnostico"] = {
                "aprobada": bool(fn.get("verde", True)),
                "estado": fn.get("estado"),
                "motivo_fallo": motivo_fallo,
                "ubicacion_fallo": ubicacion_fallo,
            }
            detalles_fn.append(item)
        base["detalle_funciones"] = detalles_fn
    else:
        base["objetivos"] = []

    def _quitar_costos_json(obj: Any) -> Any:
        if isinstance(obj, dict):
            return {
                k: _quitar_costos_json(v)
                for k, v in obj.items()
                if k
                not in (
                    "costo_usd",
                    "costo_total_usd",
                    "tope_por_corrida_usd",
                    "precio_entrada_usd_m",
                    "precio_salida_usd_m",
                    "tope_usd",
                )
            }
        if isinstance(obj, list):
            return [_quitar_costos_json(elem) for elem in obj]
        return obj

    sin_costos = _quitar_costos_json(base)
    limpio = _sanitizar_estructura(sin_costos, claves)
    texto = json.dumps(limpio, indent=2, ensure_ascii=False)
    return sanitizar_secretos(texto, claves)
