"""Índice de salud del proyecto para los informes (HU-22)."""

from __future__ import annotations

from typing import Any

from qagent.storage.informe_detalle import _simple


def _salud_proyecto(datos: dict[str, Any]) -> dict[str, Any]:
    """Sintetiza métricas prácticas, fortalezas, deficiencias y plan de mejora del proyecto."""
    funciones = datos.get("funciones") or []
    total = len(funciones)
    aprobadas = sum(1 for f in funciones if f.get("estado") == "aprobado")
    bugs = sum(1 for f in funciones if f.get("estado") == "bug_detectado")
    laundering = sum(
        1
        for f in funciones
        if f.get("estado") == "rechazado_laundering" or f.get("laundering_detectado")
    )
    estancadas = sum(1 for f in funciones if f.get("estado") == "estancado")

    lineas_vals = [float(f.get("cobertura_lineas") or 0.0) for f in funciones]
    ramas_vals = [float(f.get("cobertura_ramas") or 0.0) for f in funciones]
    prom_lineas = round(sum(lineas_vals) / len(lineas_vals), 1) if lineas_vals else 0.0
    prom_ramas = round(sum(ramas_vals) / len(ramas_vals), 1) if ramas_vals else 0.0

    criticas_fns = [f for f in funciones if f.get("critical")]
    ms_vals = [
        float(f["mutation_score"])
        for f in criticas_fns
        if f.get("mutation_score") is not None
    ]
    prom_ms = round(sum(ms_vals) / len(ms_vals), 1) if ms_vals else None

    pct_aprobadas = (aprobadas / total * 100.0) if total else 0.0
    pts_pass = (aprobadas / total * 45.0) if total else 0.0
    pts_lin = (min(100.0, prom_lineas) / 100.0) * 25.0
    pts_ram = (min(100.0, prom_ramas) / 100.0) * 15.0
    pts_ms = ((prom_ms / 100.0) * 15.0) if prom_ms is not None else 12.0
    penalizacion_laund = laundering * 8.0
    penalizacion_bugs = bugs * 5.0
    indice_salud = max(
        0,
        min(
            100,
            round(
                pts_pass
                + pts_lin
                + pts_ram
                + pts_ms
                - penalizacion_laund
                - penalizacion_bugs
            ),
        ),
    )

    if indice_salud >= 90:
        nivel_madurez = "Excelente (Listo para producción)"
        estado_salud = "excelente"
    elif indice_salud >= 75:
        nivel_madurez = "Estable (Observaciones menores)"
        estado_salud = "estable"
    elif indice_salud >= 50:
        nivel_madurez = "En Riesgo (Requiere correcciones prioritarias)"
        estado_salud = "riesgo"
    else:
        nivel_madurez = "Crítico (Defectos estructurales detectados)"
        estado_salud = "critico"

    fortalezas: list[str] = []
    fns_alta_cob = [
        f
        for f in funciones
        if (f.get("cobertura_lineas") or 0.0) >= 90.0 and f.get("verde", True)
    ]
    if fns_alta_cob:
        nombres = ", ".join(
            f"`{f['funcion']}` ({f['modulo']})" for f in fns_alta_cob[:3]
        )
        if len(fns_alta_cob) > 3:
            nombres += f" y {len(fns_alta_cob) - 3} más"
        fortalezas.append(
            f"Alta cobertura de código: {len(fns_alta_cob)}/{total} funciones ({nombres}) "
            f"alcanzan >= 90% de cobertura en líneas con pruebas unitarias sólidas."
        )
    fns_ms_ok = [f for f in criticas_fns if (f.get("mutation_score") or 0.0) >= 60.0]
    if fns_ms_ok:
        crit_nombres = ", ".join(f"`{f['funcion']}`" for f in fns_ms_ok)
        fortalezas.append(
            f"Resistencia frente a mutaciones: Funciones críticas ({crit_nombres}) superan "
            f"el 60% de Mutation Score, garantizando aserciones sensibles a cambios de lógica."
        )
    fns_sin_laund = [
        f
        for f in funciones
        if not f.get("laundering_detectado") and f.get("verde", True)
    ]
    if fns_sin_laund:
        fortalezas.append(
            f"Integridad de pruebas: {len(fns_sin_laund)}/{total} funciones mantuvieron "
            f"criterios estrictos sin debilitar ni relajar aserciones."
        )
    if prom_lineas >= 80.0:
        fortalezas.append(
            f"Promedio general de cobertura saludable: {prom_lineas:.1f}% en líneas y {prom_ramas:.1f}% en ramas evaluadas."
        )

    deficiencias: list[str] = []
    fns_bugs = [f for f in funciones if f.get("estado") == "bug_detectado"]
    for fb in fns_bugs:
        ejec = fb.get("ejecucion") or {}
        casos_f = [
            c for c in ejec.get("casos", []) if c.get("resultado") in ("fallo", "error")
        ]
        prim = casos_f[0] if casos_f else None
        ubicacion = (
            f"{prim['archivo']}:{prim.get('linea')}"
            if prim and prim.get("archivo")
            else f"{fb['modulo']}::{fb['funcion']}"
        )
        esp_obt = (
            f" (esperado: {prim.get('esperado')}, obtenido: {prim.get('obtenido')})"
            if prim and prim.get("esperado") is not None
            else ""
        )
        simple = _simple(fb, "que_paso")
        if simple:
            deficiencias.append(
                f"Posible error en `{fb['modulo']}::{fb['funcion']}`: {simple}"
            )
            continue
        deficiencias.append(
            f"Defecto de lógica detectado en `{fb['modulo']}::{fb['funcion']}`: "
            f"Fallo en aserción en `{ubicacion}`{esp_obt}. El código de producción no cumple el contrato esperado."
        )
    fns_laund = [
        f
        for f in funciones
        if f.get("laundering_detectado") or f.get("estado") == "rechazado_laundering"
    ]
    for fl in fns_laund:
        simple = _simple(fl, "que_paso")
        if simple:
            deficiencias.append(
                f"Prueba debilitada en `{fl['modulo']}::{fl['funcion']}`: {simple}"
            )
            continue
        deficiencias.append(
            f"Intento de debilitar pruebas en `{fl['modulo']}::{fl['funcion']}`: "
            f"Se intentó relajar el criterio esperado para ocultar un fallo, lo cual fue bloqueado durante la verificación."
        )
    fns_bajas_ramas = [
        f for f in funciones if (f.get("cobertura_ramas") or 100.0) < 85.0
    ]
    if fns_bajas_ramas:
        bajas_txt = ", ".join(
            f"`{f['funcion']}` ({f.get('cobertura_ramas', 0):g}% ramas)"
            for f in fns_bajas_ramas[:3]
        )
        deficiencias.append(
            f"Ramas condicionales sin evaluar: {bajas_txt} dejan bifurcaciones (`if/else`) sin probar."
        )
    if not deficiencias:
        deficiencias.append(
            "No se detectaron deficiencias críticas ni anomalías en la lógica analizada."
        )

    recomendaciones: list[str] = []
    if fns_bugs:
        for fb in fns_bugs:
            simple = _simple(fb, "que_hacer")
            if simple:
                recomendaciones.append(
                    f"Prioridad 1 — `{fb['modulo']}::{fb['funcion']}`: {simple}"
                )
                continue
            recomendaciones.append(
                f"Prioridad 1 — Corregir la lógica de `{fb['modulo']}::{fb['funcion']}`: "
                f"Modificar el cálculo o condición en el código de producción para que retorne el valor esperado según la especificación del negocio."
            )
    if fns_bajas_ramas:
        bajas_nom = ", ".join(f"`{f['funcion']}`" for f in fns_bajas_ramas[:2])
        recomendaciones.append(
            f"Prioridad 2 — Agregar casos límite para ramas en {bajas_nom}: "
            f"Probar entradas vacías, bordes numéricos o condiciones alternas para alcanzar 100% de cobertura de ramas."
        )
    if fns_laund:
        recomendaciones.append(
            "Prioridad 3 — Auditar criterios de prueba: Evitar modificar los valores esperados de las aserciones para forzar el paso de los tests; resolver siempre el defecto en el código fuente."
        )
    if not recomendaciones:
        recomendaciones.append(
            "Mantener la ejecución automatizada de esta suite en el pipeline de Integración Continua (CI) para prevenir regresiones."
        )

    incidentes_detallados = []
    for f in funciones:
        if not f.get("verde", True) or f.get("traza"):
            ejec = f.get("ejecucion") or {}
            fallos_casos = [
                c
                for c in ejec.get("casos", [])
                if c.get("resultado") in ("fallo", "error")
            ]
            primer_fallo = fallos_casos[0] if fallos_casos else None
            donde = (
                f"{primer_fallo['archivo']}:{primer_fallo['linea']}"
                if primer_fallo and primer_fallo.get("archivo")
                else f"{f['modulo']}::{f['funcion']}"
            )
            motivo = f.get("motivo_fallo") or (
                primer_fallo.get("mensaje")
                if primer_fallo
                else "Discrepancia detectada en aserción de prueba"
            )
            accion = _simple(f, "que_hacer") or (
                f"Corregir cálculo/retorno en `{f['modulo']}::{f['funcion']}`"
                if f.get("estado") == "bug_detectado"
                else (
                    f"Restaurar aserción estricta en suite de tests de `{f['funcion']}`"
                    if f.get("laundering_detectado")
                    else "Revisar traza de ejecución en el sandbox"
                )
            )
            incidentes_detallados.append(
                {
                    "funcion": f["funcion"],
                    "modulo": f["modulo"],
                    "estado": f.get("estado"),
                    "ubicacion": donde,
                    "causa": motivo,
                    "tipo_error": (
                        primer_fallo.get("tipo_error")
                        if primer_fallo
                        else "AssertionError"
                    ),
                    "esperado": primer_fallo.get("esperado") if primer_fallo else None,
                    "obtenido": primer_fallo.get("obtenido") if primer_fallo else None,
                    "laundering": bool(f.get("laundering_detectado")),
                    "accion_sugerida": accion,
                }
            )

    if bugs == 0 and laundering == 0 and estancadas == 0:
        diagnostico = (
            f"El proyecto supera con éxito las pruebas unitarias ({aprobadas}/{total} funciones aprobadas, "
            f"{pct_aprobadas:.1f}%). No se detectaron defectos en la lógica evaluada."
        )
    else:
        partes = [f"{aprobadas}/{total} aprobadas ({pct_aprobadas:.1f}%)"]
        if bugs:
            partes.append(f"{bugs} con defecto confirmado en código (bug detectado)")
        if laundering:
            partes.append(f"{laundering} con aserciones relajadas rechazadas")
        if estancadas:
            partes.append(f"{estancadas} estancadas")
        diagnostico = (
            f"El proyecto presenta observaciones de calidad: {', '.join(partes)}. "
            "Consulte las deficiencias y el plan de mejora para corregir las líneas afectadas en su código."
        )

    return {
        "total": total,
        "aprobadas": aprobadas,
        "bugs": bugs,
        "laundering": laundering,
        "estancadas": estancadas,
        "pct_aprobadas": pct_aprobadas,
        "indice_salud": indice_salud,
        "nivel_madurez": nivel_madurez,
        "estado_salud": estado_salud,
        "diagnostico": diagnostico,
        "fortalezas": fortalezas,
        "deficiencias": deficiencias,
        "recomendaciones": recomendaciones,
        "incidentes": incidentes_detallados,
    }
