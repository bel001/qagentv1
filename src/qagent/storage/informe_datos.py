"""Datos y métricas que alimentan los informes exportados (HU-22)."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

from qagent.config.carga import Claves
from qagent.storage.informe_comun import _fmt_pct, _sanitizar_estructura
from qagent.storage.informe_pdf import METRICA
from qagent.storage.registro import CARPETA_RUNS, nombre_perfil
from qagent.storage.vista_ejecucion import leer_results, vista_ejecucion
from qagent.storage.vista_reporte import (
    MUTATION_SCORE_MIN,
    leer_detalle,
    leer_explicaciones,
    vista_reporte,
)


def resumen_specs_corrida(raiz_proyecto: str | Path, run_id: str) -> dict[str, Any]:
    """Obtiene los specs reutilizados, regenerados y generados en la corrida (Criterio 3)."""
    from qagent.almacenamiento.proyecto import AlmacenProyecto, ErrorAlmacen

    almacen = AlmacenProyecto(raiz_proyecto)
    registros: list[dict[str, Any]] = []
    try:
        run = almacen.leer_run(run_id)
        if isinstance(run.get("specs"), list):
            registros = list(run["specs"])
    except ErrorAlmacen:
        ruta_run = Path(raiz_proyecto) / CARPETA_RUNS / Path(run_id).name / "run.json"
        try:
            datos_run = json.loads(ruta_run.read_text(encoding="utf-8"))
            if isinstance(datos_run.get("specs"), list):
                registros = list(datos_run["specs"])
        except (OSError, json.JSONDecodeError):
            registros = []

    if not registros and almacen.existe():
        planes = almacen.listar_planes_modulo()
        de_corrida = [p for p in planes if p.get("ultima_corrida") == run_id]
        fuente = de_corrida or planes
        registros = [
            {
                "modulo": p["modulo"],
                "huella": p["huella"],
                "run_origen": p["run_origen"],
                "estado": p["ultima_accion"],
            }
            for p in fuente
        ]

    por_estado: dict[str, list[str]] = {
        "reutilizado": [],
        "regenerado": [],
        "generado": [],
    }
    for reg in registros:
        estado = reg.get("estado")
        modulo = reg.get("modulo")
        if estado in por_estado and isinstance(modulo, str):
            por_estado[estado].append(modulo)

    reutilizados = len(por_estado["reutilizado"])
    regenerados = len(por_estado["regenerado"])
    generados = len(por_estado["generado"])

    partes: list[str] = []
    if reutilizados or not (regenerados or generados):
        mods = (
            f" ({', '.join(por_estado['reutilizado'])})"
            if por_estado["reutilizado"]
            else ""
        )
        partes.append(f"{reutilizados} reutilizados{mods}")
    if regenerados:
        mods = f" ({', '.join(por_estado['regenerado'])})"
        partes.append(f"{regenerados} regenerados{mods}")
    if generados:
        mods = f" ({', '.join(por_estado['generado'])})"
        partes.append(f"{generados} generados{mods}")
    texto = " · ".join(partes) + " · guardados en `.qagent/specs/`"

    return {
        "reutilizados": reutilizados,
        "regenerados": regenerados,
        "generados": generados,
        "modulos_reutilizados": por_estado["reutilizado"],
        "modulos_regenerados": por_estado["regenerado"],
        "modulos_generados": por_estado["generado"],
        "registros": registros,
        "texto": texto,
    }


def construir_cinco_metricas(results: dict[str, Any]) -> list[dict[str, Any]]:
    """Calcula las 5 métricas con su meta y estado (Cumple / No cumple) desde results.json."""
    ejec = vista_ejecucion(results)
    ind = ejec["indicadores"]
    resumen = results["resumen"]
    metas = resumen.get("metas") or {}
    objetivos = results["objetivos"]

    # 1. Pass Rate
    pr = ind["pass_rate"]
    pr_meta = pr["meta"] if pr["meta"] is not None else metas.get("pass_rate_min", 70)
    pr_cumple = bool(pr["valor"] >= pr_meta)

    # 2. Cobertura de líneas / ramas
    cv = ind["cobertura"]
    cv_meta = (
        cv["meta_lineas"]
        if cv["meta_lineas"] is not None
        else metas.get("cobertura_lineas_min", 60)
    )
    cv_cumple = bool(cv["lineas"] is not None and cv["lineas"] >= cv_meta)

    # 3. Iteraciones promedio
    it = ind["iteraciones"]
    it_meta = (
        it["meta_max"]
        if it["meta_max"] is not None
        else metas.get("iteraciones_promedio_max", 2.0)
    )
    it_cumple = bool(it["valor"] is not None and it["valor"] <= it_meta)

    # 4. Tokens de la corrida
    cs = ind["costo"]

    # 5. Mutation Score
    criticas = [o for o in objetivos if o.get("critical")]
    fuente_ms = criticas if criticas else objetivos
    valores_ms = [
        o["metricas"]["mutation_score"]
        for o in fuente_ms
        if o["metricas"].get("mutation_score") is not None
    ]
    ms_valor = round(sum(valores_ms) / len(valores_ms), 1) if valores_ms else None
    ms_meta = float(MUTATION_SCORE_MIN)
    ms_cumple = bool(ms_valor is not None and ms_valor >= ms_meta)
    if ms_valor is not None:
        ms_resultado = f"{ms_valor:.1f}% ({len(criticas)} críticas)"
        ms_estado = "Cumple" if ms_cumple else "No cumple"
    else:
        ms_resultado = f"N/A ({len(criticas)} críticas)"
        ms_estado = "No cumple (sin medición)"

    tokens_total = cs.get("tokens_total") or 0
    por_agente_tok = {
        ag: {"tokens": (cs.get("por_agente") or {}).get(ag, {}).get("tokens", 0)}
        for ag in ("planner", "generator", "reviewer")
    }

    return [
        {
            "clave": "pass_rate",
            "nombre": METRICA["pass_rate"],
            "valor": pr["valor"],
            "pasaron": pr["pasaron"],
            "total": pr["total"],
            "resultado": f"{pr['valor']:.1f}% ({pr['pasaron']}/{pr['total']})",
            "meta_valor": pr_meta,
            "meta": f"≥ {pr_meta:g}%",
            "cumple": pr_cumple,
            "estado": "Cumple" if pr_cumple else "No cumple",
        },
        {
            "clave": "cobertura",
            "nombre": METRICA["cobertura"],
            "lineas": cv["lineas"],
            "ramas": cv["ramas"],
            "resultado": f"{_fmt_pct(cv['lineas'])} / {_fmt_pct(cv['ramas'])}",
            "meta_valor": cv_meta,
            "meta": f"≥ {cv_meta:g}% líneas",
            "cumple": cv_cumple,
            "estado": "Cumple" if cv_cumple else "No cumple",
        },
        {
            "clave": "iteraciones",
            "nombre": METRICA["iteraciones"],
            "valor": it["valor"],
            "tope": it["tope"],
            "resultado": "—" if it["valor"] is None else f"{it['valor']:.2f}",
            "meta_valor": it_meta,
            "meta": f"≤ {it_meta:g} (máx. {it['tope']})",
            "cumple": it_cumple,
            "estado": "Cumple" if it_cumple else "No cumple",
        },
        {
            "clave": "costo",
            "nombre": METRICA["costo"],
            "tokens_total": tokens_total,
            "por_agente": por_agente_tok,
            "resultado": f"{int(tokens_total):,} tokens".replace(",", "."),
            "meta_valor": None,
            "meta": "Informativo",
            "cumple": True,
            "estado": "Informativo",
        },
        {
            "clave": "mutation_score",
            "nombre": (
                f"{METRICA['mutation_score']} ({len(criticas)} críticas)"
                if criticas
                else METRICA["mutation_score"]
            ),
            "valor": ms_valor,
            "criticas": len(criticas),
            "resultado": ms_resultado,
            "meta_valor": ms_meta,
            "meta": f"≥ {ms_meta:g}%",
            "cumple": ms_cumple,
            "estado": ms_estado,
        },
    ]


def _resumen_casos_planner(contrato: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Extrae los casos planificados por el Planner de forma estructurada."""
    if not isinstance(contrato, dict):
        return []
    casos = []
    if isinstance(contrato.get("casos"), list):
        for idx, c in enumerate(contrato["casos"]):
            if not isinstance(c, dict):
                continue
            casos.append(
                {
                    "id": c.get("id") or f"caso_{idx + 1}",
                    "descripcion": c.get("descripcion") or f"Caso {idx + 1}",
                    "tipo": c.get("tipo", "normal"),
                    "entrada": c.get("entrada") or c.get("entradas"),
                    "esperado": c.get("valor_esperado") or c.get("esperado"),
                    "excepcion": c.get("excepcion"),
                    "origen": c.get("origen"),
                }
            )
    elif isinstance(contrato.get("comportamiento_esperado"), list):
        for idx, comp in enumerate(contrato["comportamiento_esperado"]):
            casos.append(
                {
                    "id": f"regla_{idx + 1}",
                    "descripcion": str(comp),
                    "tipo": "especificacion",
                    "entrada": None,
                    "esperado": str(comp),
                    "excepcion": None,
                    "origen": "docstring / especificación",
                }
            )
    return casos


def _filas_entorno(datos: dict[str, Any]) -> list[tuple[str, str]]:
    """Pares (etiqueta, valor) con los datos de la ejecución; vacío si no los hay."""
    entorno = datos.get("entorno")
    if not entorno:
        return []
    limites = entorno.get("limites") or {}
    totales = datos.get("totales_casos") or {}

    def valor(dato: Any) -> str:
        return "—" if dato in (None, "") else str(dato)

    texto_limites = (
        f"{valor(limites.get('cpus'))} CPU · {valor(limites.get('memoria'))} · "
        f"{valor(limites.get('timeout_s'))} s"
    )
    filas = [
        ("Imagen del sandbox", valor(entorno.get("imagen"))),
        ("Python", valor(entorno.get("python"))),
        ("pytest", valor(entorno.get("pytest"))),
        ("Plataforma", valor(entorno.get("plataforma"))),
        ("Límites", texto_limites),
        ("Red", "desactivada (--network none)"),
        ("Comando", valor(entorno.get("comando"))),
    ]
    if totales:
        resumen = (
            f"{totales.get('total', 0)} ({totales.get('pasaron', 0)} pasaron · "
            f"{totales.get('fallaron', 0)} fallaron · {totales.get('errores', 0)} "
            f"errores · {totales.get('omitidos', 0)} omitidos)"
        )
        filas.append(("Casos ejecutados", resumen))
    return filas


def avisos_fuera_de_la_corrida(datos: dict[str, Any]) -> list[str]:
    """Avisos de los archivos JS o TS que la corrida no probó (EP-11).

    Con ``.js`` y ``.ts`` juntos la corrida usa un solo adaptador; el informe lo dice
    en lugar de omitir esos archivos en silencio. Corridas anteriores no lo traen.
    """
    return [
        str(f["mensaje"])
        for f in datos.get("fuera_de_la_corrida") or []
        if isinstance(f, dict) and f.get("mensaje")
    ]


def datos_informe(
    raiz_proyecto: str | Path,
    run_id: str | None = None,
    claves: Claves | None = None,
) -> dict[str, Any]:
    """Reúne todos los datos del informe desde `results.json`, `detalle.json` y `run.json`."""
    from qagent.storage.corrida_demo import CORRIDA_DEMO_ID, leer_results_demo

    if run_id == CORRIDA_DEMO_ID:
        results = leer_results_demo(raiz_proyecto, run_id)
    else:
        results = leer_results(raiz_proyecto, run_id)
    from qagent.storage.vista_comparacion import cargar_vista_comparacion

    run_actual = results["run_id"]
    comparacion = cargar_vista_comparacion(
        raiz_proyecto, run_actual, results.get("perfil")
    )
    detalle = leer_detalle(raiz_proyecto, run_actual)
    vista = vista_reporte(
        results,
        detalle,
        leer_explicaciones(raiz_proyecto, results),
        comparacion,
    )
    ejec = vista_ejecucion(results, comparacion)
    metricas = construir_cinco_metricas(results)
    specs = resumen_specs_corrida(raiz_proyecto, run_actual)
    por_agente = ejec["indicadores"]["costo"]["por_agente"]

    # Tokens por función y por agente desde results.json
    tokens_funcion: dict[tuple[str, str], int] = {}
    tokens_agente_funcion: dict[tuple[str, str], dict[str, Any]] = {}
    for obj in results["objetivos"]:
        tok_ag = obj["metricas"].get("tokens_por_agente") or {}
        total_fn = sum(
            int(t.get("prompt_tokens", 0)) + int(t.get("completion_tokens", 0))
            for t in tok_ag.values()
        )
        tokens_funcion[(obj["modulo"], obj["funcion"])] = total_fn
        tokens_agente_funcion[(obj["modulo"], obj["funcion"])] = tok_ag

    funciones_enriquecidas = []
    for fn in vista["funciones"]:
        copia = dict(fn)
        copia["tokens"] = tokens_funcion.get((fn["modulo"], fn["funcion"]), 0)
        copia["tokens_por_agente"] = tokens_agente_funcion.get(
            (fn["modulo"], fn["funcion"]), {}
        )
        funciones_enriquecidas.append(copia)

    datos = {
        "contexto_automatico": copy.deepcopy(
            (detalle or {}).get("contexto_automatico", [])
        ),
        "run_id": run_actual,
        "fecha": results["fecha"],
        "proyecto": results["proyecto"],
        "rama": results.get("rama"),
        "perfil": nombre_perfil(results["perfil"]),  # nombre legible (#70)
        "es_simulado": results["es_simulado"],
        "estado_final": results["estado_final"],
        "motivo_fallo": results["motivo_fallo"],
        "inicio": vista.get("inicio"),
        "fin": vista.get("fin"),
        "duracion_total_s": vista.get("duracion_total_s"),
        "duracion_etapas": vista.get("duracion_etapas"),
        "total_funciones": results["resumen"]["total_funciones"],
        "total_seleccionados": vista.get("total_seleccionados"),
        "total_descubiertos": vista.get("total_descubiertos"),
        "total_elegibles": vista.get("total_elegibles"),
        "total_procesados": vista.get("total_procesados"),
        "total_pendientes": vista.get("total_pendientes"),
        "total_omitidos": vista.get("total_omitidos"),
        "tipo_terminacion": vista.get("tipo_terminacion"),
        "es_parcial": vista.get("es_parcial"),
        # Seleccionados que no se probaron, con su motivo.
        "omitidos": copy.deepcopy(vista["omitidos"]),
        # EP-11: archivos JS o TS que esta corrida no prueba.
        "fuera_de_la_corrida": copy.deepcopy(vista.get("fuera_de_la_corrida") or []),
        "criticas": sum(1 for o in results["objetivos"] if o.get("critical")),
        "modelos": copy.deepcopy(results["modelos"]),
        "costo_por_agente": por_agente,
        "specs": specs,
        "metricas": metricas,
        "indicadores": vista["indicadores"],
        "entorno": vista["entorno"],
        "totales_casos": vista["totales_casos"],
        "funciones": funciones_enriquecidas,
        "texto_categorias": vista.get("texto_categorias"),  # #76
        "results": copy.deepcopy(results),
        "comparacion": copy.deepcopy(comparacion),
    }
    return _sanitizar_estructura(datos, claves)
