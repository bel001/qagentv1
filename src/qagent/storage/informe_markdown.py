"""Informe en Markdown (.md) de una corrida (HU-22)."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from qagent.storage.informe_comun import (
    _ETIQUETA_DECISION,
    Claves,
    _fmt_duracion,
    _fmt_pct,
    normalizar_opciones,
    sanitizar_secretos,
)
from qagent.storage.informe_datos import (
    _filas_entorno,
    _resumen_casos_planner,
    avisos_fuera_de_la_corrida,
)
from qagent.storage.informe_ejecucion import (
    _markdown_categorias,
    _markdown_comparacion,
    _markdown_ejecucion,
)
from qagent.storage.informe_pdf import BANDEJA, ETAPAS, METRICA, _explicacion
from qagent.storage.informe_salud import _salud_proyecto
from qagent.storage.vista_ejecucion import corrida_incompleta, respuesta_principal
from qagent.storage.vista_reporte import etiqueta_ia


def construir_markdown_informe(
    datos: dict[str, Any],
    opciones: Mapping[str, Any] | None = None,
    claves: Claves | None = None,
) -> str:
    """Construye el informe en formato Markdown (.md) según las opciones elegidas."""
    opts = normalizar_opciones(opciones)
    funciones = _funciones_ordenadas(datos)
    bugs = [f for f in funciones if _bandeja(f)[0] == "bug"]
    sin = [f for f in funciones if _bandeja(f)[0] in ("sin", "repetir")]
    respuesta = respuesta_principal(
        bugs=len(bugs),
        primer_bug=(
            str(bugs[0].get("identificador") or bugs[0].get("funcion") or "Función")
            if bugs
            else None
        ),
        sin_prueba=len(sin),
        total=len(funciones),
        omitidos=len(datos.get("omitidos") or []),
        incompleta=corrida_incompleta(datos),
    )
    lineas = _md_cabecera(datos, funciones, bugs, sin, respuesta)
    lineas.extend(_md_metas(datos))
    lineas.extend(_md_salud(datos))
    lineas.extend(_md_prioridades(bugs))
    lineas.extend(_md_datos_corrida(datos))
    if opts["detalle"]:
        lineas.extend(_md_tabla_funciones(funciones))
        lineas.extend(_markdown_categorias(datos))
        lineas.extend(_markdown_ejecucion(datos, opts["trazas"]))
    if opts["trazas"]:
        lineas.extend(_md_trazas(funciones))
    if opts["codigo"]:
        lineas.extend(_md_codigo(funciones))
    if opts["contratos"]:
        lineas.extend(_md_contratos(funciones))
    lineas.extend(_md_entorno(datos, opts))
    return sanitizar_secretos("\n".join(lineas), claves)


def _bandeja(funcion: dict[str, Any]) -> tuple:
    """Fila de la bandeja del estado; sin veredicto si no se reconoce."""
    return BANDEJA.get(str(funcion.get("estado")), BANDEJA["sin_veredicto"])


def _funciones_ordenadas(datos: dict[str, Any]) -> list[dict[str, Any]]:
    """Ordena las funciones por bandeja y criticidad, como en el resto del informe."""
    return sorted(
        datos.get("funciones") or [],
        key=lambda f: (_bandeja(f)[3], not f.get("critical")),
    )


def _md_cabecera(
    datos: dict[str, Any],
    funciones: list[dict[str, Any]],
    bugs: list[dict[str, Any]],
    sin: list[dict[str, Any]],
    respuesta: str,
) -> list[str]:
    """Cabecera con metadatos, cifras principales y comparación de corridas."""
    rama = datos.get("rama") or "sin repositorio Git"
    meta_parts = [
        f"**Proyecto:** {datos['proyecto']}",
        f"**Rama:** {rama}",
        f"**Fecha:** {datos['fecha']}",
        f"**Perfil:** {datos['perfil']}",
        f"**Funciones evaluadas:** {datos['total_funciones']} ({datos['criticas']} críticas)",
        (
            f"**Duración total medida:** {_fmt_duracion(datos.get('duracion_total_s'))}"
            if datos.get("duracion_total_s") is not None
            else None
        ),
        "**Generado por:** QAgent",
    ]
    meta_parts = [parte for parte in meta_parts if parte is not None]
    if datos.get("es_simulado"):
        meta_parts.append("**Modo:** IA simulada")
    total = len(funciones)
    pasaron = sum(1 for f in funciones if _bandeja(f)[0] == "paso")
    cob = {x["clave"]: x for x in datos.get("metricas") or []}.get("cobertura", {})
    tokens_val = {x["clave"]: x for x in datos.get("metricas") or []}.get(
        "costo", {}
    ).get("tokens_total")
    tokens_str = "—" if tokens_val is None else f"{int(tokens_val):,}".replace(",", ".")
    sub_cob = (
        "Ramas no exigidas en Humo"
        if datos.get("perfil") == "Humo"
        else f"{_fmt_pct(cob.get('ramas'))} de las ramas"
    )
    lineas = [
        f"# Informe de pruebas — Corrida #{datos['run_id']}",
        "",
        f"> **{respuesta}**",
        "",
        "- " + " · ".join(meta_parts),
    ]
    if datos.get("motivo_fallo"):
        lineas.append(f"- **La corrida se detuvo:** {datos['motivo_fallo']}")
    lineas.append(
        "- **Objetivos:** "
        + (
            f"{datos['total_descubiertos']} descubiertos · "
            if datos.get("total_descubiertos") is not None
            else ""
        )
        + f"{datos.get('total_seleccionados', total)} seleccionados · "
        f"{datos.get('total_elegibles', total)} elegibles · "
        f"{datos.get('total_procesados', total)} procesados · "
        f"{datos.get('total_omitidos', 0)} omitidos · "
        f"{datos.get('total_pendientes', 0)} pendientes"
    )
    lineas.extend(
        f"- **Aviso:** {aviso}" for aviso in avisos_fuera_de_la_corrida(datos)
    )
    lineas.extend(["", *_markdown_comparacion(datos)])
    lineas.extend(
        [
            "",
            "| Pasaron | Posibles bugs | Cobertura | Tokens de la corrida |",
            "|---|---|---|---|",
            f"| {pasaron} / {total} | {len(bugs)} | {_fmt_pct(cob.get('lineas'))} | {tokens_str} |",
            f"| {total - pasaron} con algo por revisar | En {len(bugs)} de {total} | {sub_cob} | Sumando las tres etapas |",
            "",
            "## Metas de calidad",
            "",
            "| Métrica | Resultado | Meta | Estado |",
            "|---|---|---|---|",
        ]
    )
    return lineas


def _md_metas(datos: dict[str, Any]) -> list[str]:
    """Tabla de metas de calidad; el costo se muestra como informativo."""
    lineas = []
    for metrica in datos["metricas"]:
        nombre = METRICA.get(metrica.get("clave"), metrica.get("nombre", ""))
        if (
            metrica.get("clave") == "mutation_score"
            and metrica.get("criticas") is not None
        ):
            nombre = f"{nombre} ({metrica['criticas']} críticas)"
        es_tokens = metrica.get("clave") == "costo"
        resultado = (
            f"{int(metrica.get('tokens_total') or 0):,} tokens".replace(",", ".")
            if es_tokens
            else str(metrica.get("resultado", ""))
        )
        meta = "Informativo" if es_tokens else str(metrica.get("meta", ""))
        estado, icono = _estado_meta(metrica, es_tokens)
        lineas.append(f"| {nombre} | {resultado} | {meta} | {icono} {estado} |")
    lineas.append("")
    return lineas


def _estado_meta(metrica: dict[str, Any], es_tokens: bool) -> tuple[str, str]:
    """Estado e icono de una meta; el costo no se evalúa como cumplida."""
    if es_tokens:
        return "Informativo", "ℹ️"
    return ("Cumple", "✅") if metrica.get("cumple") else ("No cumple", "❌")


def _md_salud(datos: dict[str, Any]) -> list[str]:
    """Sección de salud del proyecto con fortalezas, riesgos y plan de acción."""
    salud = _salud_proyecto(datos)
    lineas = [
        "### 1.1 Estado de salud del proyecto",
        "",
        f"- **Índice de salud del código:** {salud['indice_salud']}/100 — **Nivel:** {salud['nivel_madurez']}",
        f"- **Progreso del proyecto:** {salud['aprobadas']}/{salud['total']} funciones aprobadas ({salud['pct_aprobadas']:.1f}%)",
        f"- **Diagnóstico global:** {salud['diagnostico']}",
        (
            f"- **Balance de calidad:** ✅ {salud['aprobadas']} aprobadas · "
            f"🐛 {salud['bugs']} defectos en código · "
            f"🛡️ {salud['laundering']} pruebas debilitadas bloqueadas · "
            f"⏳ {salud['estancadas']} estancadas (de {salud['total']} evaluadas)"
        ),
        "",
        "#### Fortalezas del proyecto",
    ]
    lineas.extend(f"- ✅ {fort}" for fort in salud["fortalezas"])
    lineas.extend(["", "#### Deficiencias detectadas (áreas de riesgo)"])
    lineas.extend(f"- ⚠️ {defic}" for defic in salud["deficiencias"])
    lineas.extend(["", "#### Cómo mejorar su proyecto (Plan de acción recomendado)"])
    lineas.extend(
        f"{indice}. {recomendacion}"
        for indice, recomendacion in enumerate(salud["recomendaciones"], start=1)
    )
    lineas.append("")
    if salud["incidentes"]:
        lineas.append("- **Puntos de atención que requieren corrección en el código:**")
        lineas.extend(_md_incidente(incidente) for incidente in salud["incidentes"])
        lineas.append("")
    return lineas


def _md_incidente(incidente: dict[str, Any]) -> str:
    """Línea de un incidente de salud con esperado, obtenido y sugerencia."""
    detalle = f"  - `{incidente['funcion']}` en `{incidente['ubicacion']}`: {incidente['causa']}"
    if incidente["esperado"] is not None and incidente["obtenido"] is not None:
        detalle += f" (Esperado: `{incidente['esperado']}` | Obtenido: `{incidente['obtenido']}`)"
    if incidente.get("accion_sugerida"):
        detalle += f" — *Sugerencia:* {incidente['accion_sugerida']}"
    return detalle


def _md_prioridades(bugs: list[dict[str, Any]]) -> list[str]:
    """Tres primeros bugs con su explicación y etiqueta de IA."""
    if not bugs:
        return []
    lineas = ["## Por dónde empezar", ""]
    for numero, funcion in enumerate(bugs[:3], start=1):
        nombre = str(
            funcion.get("identificador") or funcion.get("funcion") or "Función"
        )
        lineas.append(
            f"### Prioridad {numero}: Corrige `{nombre}` · {funcion.get('modulo', '')}"
        )
        lineas.append("")
        explicacion = _explicacion(funcion)
        if explicacion:
            lineas.append(explicacion.split("\n")[0])
            lineas.append("")
        etiqueta = etiqueta_ia(funcion.get("explicacion"))  # #166
        if etiqueta:
            lineas.append(f"_{etiqueta}._")
            lineas.append("")
    return lineas


def _md_datos_corrida(datos: dict[str, Any]) -> list[str]:
    """Modelos, specs, categorías, etapas y cifras de la corrida."""
    lineas = ["## Datos de la corrida", ""]
    modelos = datos.get("modelos") or {}
    for clave, etapa in ETAPAS:
        info = modelos.get(clave) or {}
        if info.get("modelo"):
            lineas.append(
                f"- **{etapa}:** {info['modelo']} ({info.get('proveedor', '')})"
            )
    specs_sin_ruta = (datos.get("specs") or {}).get("texto") or ""
    specs_sin_ruta = specs_sin_ruta.split(" · guardados en")[0]
    if specs_sin_ruta:
        lineas.append(f"- **Trabajo del análisis:** {specs_sin_ruta}")
    if datos.get("texto_categorias"):
        lineas.append(f"- **Casos planificados:** {datos['texto_categorias']}")
    etapas = datos.get("duracion_etapas") or {}
    if etapas:
        nombres = {
            "planner": "Planner",
            "generator": "Generator",
            "reviewer": "Reviewer (incluye sandbox)",
            "sandbox": "Sandbox",
            "pytest": "pytest",
            "entorno": "Entorno aislado (en paralelo)",
            "espera_entorno": "Espera del entorno",
        }
        detalle = " · ".join(
            f"{nombres.get(clave, clave)} {_fmt_duracion(valor)}"
            for clave, valor in etapas.items()
        )
        lineas.append(f"- **Tiempo medido por etapa:** {detalle}")
    lineas.append(
        f"- **Funciones y endpoints:** {datos.get('total_funciones', 0)} revisados · {datos.get('criticas', 0)} críticos"
    )
    lineas.append("")
    return lineas


def _md_tabla_funciones(funciones: list[dict[str, Any]]) -> list[str]:
    """Tabla de resultado por función con cobertura, fortaleza y tokens."""
    lineas = [
        "## Resultado por función",
        "",
        "| Función | Módulo | Lenguaje | Estado | Intentos | Cob. líneas | Cob. ramas | Fortaleza | Tokens |",
        "|---|---|---|---|---|---|---|---|---|\n".rstrip("\n"),
    ]
    for funcion in funciones:
        etiqueta = _bandeja(funcion)[1]
        mutation = (
            "—"
            if not funcion.get("critical")
            else (
                "Pendiente"
                if funcion.get("mutation_score") is None
                else f"{funcion['mutation_score']:g}%"
            )
        )
        nombre = str(
            funcion.get("identificador") or funcion.get("funcion") or "Función"
        )
        lineas.append(
            f"| `{nombre}` | {funcion.get('modulo', '')} | {funcion.get('lenguaje', 'python')} | {etiqueta} | {funcion.get('iteraciones', 1)}/3 | "
            f"{_fmt_pct(funcion.get('cobertura_lineas'))} | {_fmt_pct(funcion.get('cobertura_ramas'))} | "
            f"{mutation} | {funcion.get('tokens', 0)} |"
        )
    lineas.append("")
    return lineas


def _md_trazas(funciones: list[dict[str, Any]]) -> list[str]:
    """Trazas de los incidentes, intentos y casos fallidos."""
    lineas = ["## Trazas de los incidentes", ""]
    incidentes = [f for f in funciones if not f.get("verde", True) or f.get("traza")]
    if not incidentes:
        lineas.extend(
            ["No se registraron incidentes ni trazas de fallo en esta corrida.", ""]
        )
        return lineas
    for funcion in incidentes:
        lineas.extend(_md_traza_funcion(funcion))
    return lineas


def _md_traza_funcion(funcion: dict[str, Any]) -> list[str]:
    """Detalle de un incidente: causa, intentos, casos fallidos y traza."""
    etiqueta = _bandeja(funcion)[1]
    nombre = str(funcion.get("identificador") or funcion.get("funcion") or "Función")
    lineas = [
        f"### {nombre} ({funcion['modulo']}) — {etiqueta}",
        "",
        f"- **Parte del código afectada:** `{funcion['modulo']}::{funcion['funcion']}`",
        f"- **Resultado:** {etiqueta}",
        f"- **¿Por qué falló?:** {_causa_incidente(funcion)}",
    ]
    if funcion.get("laundering_detectado"):
        lineas.append(
            "- **Incidente de integridad:** Criterio original conservado (se bloqueó un intento de relajar aserciones)."
        )
    intentos = funcion.get("intentos") or []
    if intentos:
        lineas.append(f"- **Historial de intentos ({len(intentos)}/3):**")
        lineas.extend(_md_intento(intento) for intento in intentos)
    ejecucion = funcion.get("ejecucion")
    if ejecucion and ejecucion.get("casos"):
        fallos = [
            caso
            for caso in ejecucion["casos"]
            if caso.get("resultado") in ("fallo", "error")
        ]
        if fallos:
            lineas.append("- **Casos fallidos en pytest:**")
            lineas.extend(f"  - {_texto_caso_fallido(caso)}" for caso in fallos)
    lineas.append("")
    if funcion.get("traza"):
        lineas.extend(["```text", str(funcion["traza"]), "```"])
    else:
        lineas.append("_Sin traza registrada en este incidente._")
    lineas.append("")
    return lineas


def _causa_incidente(funcion: dict[str, Any]) -> str:
    """Motivo del incidente, con respaldo según el estado de la función."""
    if funcion.get("motivo_fallo"):
        return str(funcion["motivo_fallo"])
    if funcion.get("laundering_detectado"):
        return "Se bloqueó un intento de debilitar pruebas (aserciones relajadas)."
    if funcion.get("estado") == "bug_detectado":
        return "Defecto confirmado en código (el test detectó una discrepancia frente a la especificación esperada)."
    return "Ejecución estancada o fallo durante la validación en el sandbox."


def _md_intento(intento: dict[str, Any]) -> str:
    """Línea de un intento del historial de la función."""
    decision = _ETIQUETA_DECISION.get(
        str(intento.get("decision")), intento.get("decision")
    )
    feedback = intento.get("feedback") or "Sin diagnóstico adicional."
    return f"  - *Intento {intento.get('intento')}:* Decisión `{decision}` · Diagnóstico: {feedback}"


def _texto_caso_fallido(caso: dict[str, Any]) -> str:
    """Partes legibles de un caso fallido de pytest."""
    partes = [f"`{caso['nombre']}`"]
    if caso.get("linea"):
        partes.append(f"Línea: {caso['linea']}")
    if caso.get("esperado") is not None or caso.get("obtenido") is not None:
        partes.append(
            f"Esperado: `{caso.get('esperado')}` | Obtenido: `{caso.get('obtenido')}`"
        )
    return " — ".join(partes)


def _md_codigo(funciones: list[dict[str, Any]]) -> list[str]:
    """Anexo con el código de las suites generadas."""
    lineas = [
        "## Código de las pruebas generadas",
        "",
        "_Anexo de referencia: suites de prueba generadas._",
        "",
    ]
    for funcion in funciones:
        etiqueta = _bandeja(funcion)[1]
        lineas.append(f"### Prueba de {funcion['funcion']} ({funcion['modulo']})")
        lineas.append("")
        lineas.append(
            f"- **Suite de pruebas:** {funcion.get('framework_pruebas', 'pytest')} en sandbox · **Estado:** {etiqueta} · "
            f"**Iteraciones:** {funcion.get('iteraciones', 1)}/3"
        )
        lineas.append(
            "- **Entorno de prueba:** Ejecución hermética en sandbox Docker sin acceso a red"
        )
        lineas.append("")
        if funcion.get("codigo"):
            lineas.extend(
                [
                    "```" + funcion.get("lenguaje", "python"),
                    str(funcion["codigo"]).rstrip(),
                    "```",
                ]
            )
        else:
            lineas.append("_Sin código registrado para esta función._")
        lineas.append("")
    return lineas


def _md_contratos(funciones: list[dict[str, Any]]) -> list[str]:
    """Anexo con los contratos JSON del análisis."""
    lineas = [
        "## Contratos JSON del análisis",
        "",
        "_Anexo técnico secundario: especificaciones y contratos formales para auditoría._",
        "",
    ]
    for funcion in funciones:
        casos = _resumen_casos_planner(funcion.get("contrato") or {})
        critica = (
            "Sí (crítica, evaluada con mutation testing)"
            if funcion.get("critical")
            else "No (función estándar)"
        )
        nombre = str(
            funcion.get("identificador") or funcion.get("funcion") or "Función"
        )
        lineas.extend(
            [
                f"### {nombre} ({funcion['modulo']})",
                "",
                f"- **Análisis:** Casos deducidos mediante análisis estático AST · **Criticidad:** {critica}",
                f"- **Casos planificados:** {len(casos)} casos deducidos formalmente",
                "",
            ]
        )
        if funcion.get("contrato") is not None:
            lineas.extend(
                [
                    "```json",
                    json.dumps(funcion["contrato"], indent=2, ensure_ascii=False),
                    "```",
                ]
            )
        else:
            lineas.append("_Sin contrato registrado para esta función._")
        lineas.append("")
    return lineas


def _md_entorno(datos: dict[str, Any], opts: dict[str, Any]) -> list[str]:
    """Anexo técnico con los datos de la ejecución."""
    entorno = _filas_entorno(datos)
    if not entorno:
        return []
    lineas = [
        "## Datos de la ejecución (anexo técnico)",
        "",
        "| Dato | Valor |",
        "|---|---|",
    ]
    for etiqueta, valor in entorno:
        if etiqueta == "Comando" and not opts["trazas"]:
            continue
        lineas.append(f"| {etiqueta} | `{valor}` |")
    lineas.append("")
    return lineas
