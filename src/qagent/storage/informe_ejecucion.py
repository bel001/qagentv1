"""Bloques de ejecución en Markdown, HTML y JSON del informe (HU-22)."""

from __future__ import annotations

import copy
from typing import Any

from qagent.storage.informe_comun import (
    _ETIQUETA_CASO,
    ETIQUETAS_ESTADO,
    _fmt_pct,
)
from qagent.storage.informe_datos import _filas_entorno, _resumen_casos_planner
from qagent.storage.informe_detalle import (
    _funciones_con_casos,
    _historial_intentos,
    _lineas_caso,
    _sin_cubrir_texto,
)
from qagent.storage.informe_pdf import _envolver_linea


def _markdown_categorias(datos: dict[str, Any]) -> list[str]:
    """Casos por categoría (normal / límite / error) de la corrida y de cada objetivo (#76).

    El aviso de «sin casos límite» es informativo: no cuenta como fallo.
    """
    if not datos.get("texto_categorias"):
        return []  # corrida anterior al conteo por categoría
    lineas = [
        "### Casos por categoría",
        "",
        f"**Corrida:** {datos['texto_categorias']}",
        "",
    ]
    for f in datos["funciones"]:
        if not f.get("texto_categorias"):
            continue
        aviso = f" — ⚠ {f['aviso_limites']}" if f.get("aviso_limites") else ""
        lineas.append(f"- **{f['funcion']}**: {f['texto_categorias']}{aviso}")
    lineas.append("")
    return lineas


def _markdown_comparacion(datos: dict[str, Any]) -> list[str]:
    """Comparación persistida de una verificación, sin recalcular resultados."""
    comparacion = datos.get("comparacion")
    if not comparacion:
        return []
    lineas = ["## Comparación con la corrida original", ""]
    if not comparacion.get("disponible"):
        lineas.extend(
            [
                f"_Comparación no disponible: {comparacion.get('motivo', 'sin datos almacenados')}._",
                "",
            ]
        )
        return lineas
    resumen = comparacion["resumen"]
    lineas.extend(
        [
            f"- **Corrida original:** `{comparacion['run_origen_id']}`",
            f"- **Corrida de verificación:** `{comparacion['run_verificacion_id']}`",
            f"- **Comparación registrada:** {comparacion['creado']}",
            (
                f"- **Antes ({resumen['total_original']} resultados):** "
                f"{resumen['aprobadas_original']} aprobadas y "
                f"{resumen['fallidas_original']} con bug reproducible."
            ),
            (
                f"- **Ahora ({resumen['total_actual']} resultados):** "
                f"{resumen['aprobadas_actual']} aprobadas y "
                f"{resumen['fallidas_actual']} con bug reproducible "
                f"({resumen['total_ejecutadas']} ejecutadas)."
            ),
            (
                f"- **Cambio:** {resumen['corregidos']} corregidos · "
                f"{resumen['siguen_fallando']} siguen fallando · "
                f"{resumen['regresiones']} regresiones · "
                f"{resumen['no_comparables']} no comparables."
            ),
            "",
            "| Objetivo | Antes | Ahora | Resultado | Motivo |",
            "|---|---|---|---|---|",
        ]
    )
    for item in comparacion["comparaciones"]:
        motivo = item.get("explicacion") or item.get("motivo") or "—"
        valores = (
            item["objetivo"],
            item["estado_anterior"]["etiqueta"],
            item["estado_posterior"]["etiqueta"],
            item["etiqueta"],
            motivo,
        )
        seguros = [
            str(valor).replace("|", "\\|").replace("\n", " ") for valor in valores
        ]
        lineas.append("| " + " | ".join(seguros) + " |")
    lineas.extend(["", comparacion["politica_agregacion"], ""])
    return lineas


def _html_comparacion(datos: dict[str, Any], esc: Any) -> str:
    """Tarjeta HTML de comparación con todo texto externo escapado."""
    comparacion = datos.get("comparacion")
    if not comparacion:
        return ""
    if not comparacion.get("disponible"):
        return (
            "<section class='comparison-card'><h2>Comparación con la corrida original</h2>"
            f"<p>Comparación no disponible: {esc(comparacion.get('motivo') or 'sin datos almacenados')}.</p></section>"
        )
    resumen = comparacion["resumen"]
    filas = []
    for item in comparacion["comparaciones"]:
        motivo = item.get("explicacion") or item.get("motivo") or "—"
        filas.append(
            "<tr>"
            f"<td><b>{esc(item['objetivo'])}</b><br><small>{esc(item['modulo'])}</small></td>"
            f"<td>{esc(item['estado_anterior']['etiqueta'])}</td>"
            f"<td>{esc(item['estado_posterior']['etiqueta'])}</td>"
            f"<td><span class='pill'>{esc(item['etiqueta'])}</span></td>"
            f"<td>{esc(motivo)}</td></tr>"
        )
    return (
        "<section class='comparison-card'><h2>Comparación con la corrida original</h2>"
        f"<p><b>Original:</b> <code>{esc(comparacion['run_origen_id'])}</code> · "
        f"<b>Verificación:</b> <code>{esc(comparacion['run_verificacion_id'])}</code> · "
        f"<b>Fecha:</b> {esc(comparacion['creado'])}</p>"
        "<div class='comparison-summary'>"
        f"<div><b>{resumen['total_original']}</b><span>Resultados originales</span></div>"
        f"<div><b>{resumen['total_actual']}</b><span>Resultados actuales</span></div>"
        f"<div><b>{resumen['aprobadas_original']}</b><span>Aprobadas antes</span></div>"
        f"<div><b>{resumen['aprobadas_actual']}</b><span>Aprobadas ahora</span></div>"
        f"<div><b>{resumen['fallidas_original']}</b><span>Errores anteriores</span></div>"
        f"<div><b>{resumen['fallidas_actual']}</b><span>Errores actuales</span></div>"
        f"<div><b>{resumen['corregidos']}</b><span>Corregidos</span></div>"
        f"<div><b>{resumen['siguen_fallando']}</b><span>Siguen fallando</span></div>"
        f"<div><b>{resumen['regresiones']}</b><span>Regresiones</span></div>"
        f"<div><b>{resumen['no_comparables']}</b><span>No comparables</span></div>"
        "</div><table><thead><tr><th>Objetivo</th><th>Antes</th><th>Ahora</th>"
        f"<th>Resultado</th><th>Motivo</th></tr></thead><tbody>{''.join(filas)}</tbody></table>"
        f"<p><small>{esc(comparacion['politica_agregacion'])}</small></p></section>"
    )


def _markdown_ejecucion(datos: dict[str, Any], con_traza: bool) -> list[str]:
    """Secciones 2.1 y 2.2 del Markdown: datos de la ejecución y casos por función."""
    lineas = ["## 2.1 Datos de la ejecución", ""]
    filas = _filas_entorno(datos)
    if not filas:
        lineas.append(
            "_Esta corrida no guardó datos de ejecución (IA simulada sin sandbox o "
            "corrida anterior al informe detallado)._"
        )
        lineas.append("")
        return lineas
    lineas.extend(["| Dato | Valor |", "|---|---|"])
    lineas.extend(f"| {k} | `{v}` |" for k, v in filas)
    lineas.extend(["", "## 2.2 Casos de prueba por función", ""])
    for f in _funciones_con_casos(datos):
        estado_lbl = ETIQUETAS_ESTADO.get(f["estado"], f["estado"])
        lineas.extend([f"### {f['funcion']} ({f['modulo']}) — {estado_lbl}", ""])
        historial = _historial_intentos(f)
        if historial:
            lineas.extend(f"- {h}" for h in historial)
            lineas.append("")

        # Documentación concisa orientada al usuario
        contrato = f.get("contrato") or {}
        casos_plan = _resumen_casos_planner(contrato)
        firma = (
            f.get("firma")
            or contrato.get("firma")
            or f.get("manejador")
            or f["funcion"]
        )
        crit_txt = "Crítica" if f["critical"] else "Estándar"
        lineas.append(
            f"- **Objetivo analizado:** `{firma}` ({len(casos_plan)} casos deducidos del AST · {crit_txt})"
        )
        lineas.append(
            f"- **Suite {f.get('framework_pruebas', 'pytest')}:** prueba generada ({f['iteraciones']}/3 iteraciones en sandbox hermético)"
        )
        laund_txt = (
            "Se bloqueó intento de debilitar pruebas"
            if f.get("laundering_detectado")
            else "Criterio estricto conservado"
        )
        lineas.append(
            f"- **Evaluación:** {estado_lbl} · Cobertura: {_fmt_pct(f['cobertura_lineas'])} líneas / {_fmt_pct(f['cobertura_ramas'])} ramas · Integridad: {laund_txt}"
        )
        for it in f.get("intentos") or []:
            fb = it.get("feedback")
            if fb:
                lineas.append(f"  - *Diagnóstico (Intento {it.get('intento')}):* {fb}")
        lineas.append("")

        ejecucion = f["ejecucion"]
        lineas.extend(["| Resultado | Caso | Duración | Dónde |", "|---|---|---|---|"])
        for c in ejecucion["casos"]:
            donde = f"{c['archivo']}:{c['linea']}" if c.get("archivo") else "—"
            icono = {"paso": "✅", "omitido": "⏭️"}.get(c["resultado"], "❌")
            etiqueta = _ETIQUETA_CASO.get(c["resultado"], c["resultado"])
            duracion = float(c.get("duracion_s") or 0)
            lineas.append(
                f"| {icono} {etiqueta} | {c['nombre']} | {duracion:.2f} s | {donde} |"
            )
        lineas.append("")
        fallos = [c for c in ejecucion["casos"] if c["resultado"] in ("fallo", "error")]
        if fallos:
            lineas.append("```text")
            for c in fallos:
                lineas.extend(_lineas_caso(c, con_traza))
                lineas.append("")
            lineas.extend(["```", ""])
        cubierta = _sin_cubrir_texto(ejecucion)
        if cubierta:
            lineas.extend([cubierta, ""])
        if con_traza and ejecucion.get("salida"):
            lineas.extend(
                ["<details><summary>Salida completa de pytest</summary>", "", "```text"]
            )
            lineas.append(str(ejecucion["salida"]))
            lineas.extend(["```", "", "</details>", ""])
    return lineas


def _json_ejecucion(datos: dict[str, Any], con_traza: bool) -> dict[str, Any]:
    """Bloque `ejecucion` del JSON exportado: entorno, totales y casos por función."""
    funciones = []
    for f in _funciones_con_casos(datos):
        intentos = []
        for i in f["intentos"]:
            item = {k: v for k, v in i.items() if k != "ejecucion"}
            ejecucion = copy.deepcopy(i.get("ejecucion"))
            if ejecucion is not None and not con_traza:
                ejecucion.pop("salida", None)
                for caso in ejecucion.get("casos", []):
                    caso.pop("traza", None)
                    caso["pila"] = []
            item["ejecucion"] = ejecucion
            intentos.append(item)
        funciones.append(
            {
                "modulo": f["modulo"],
                "funcion": f["funcion"],
                "estado": f["estado"],
                "intentos": intentos,
            }
        )
    return {
        "entorno": copy.deepcopy(datos.get("entorno")),
        "totales_casos": copy.deepcopy(datos.get("totales_casos")),
        "funciones": funciones,
    }


def _html_ejecucion(datos: dict[str, Any], con_traza: bool, esc: Any) -> str:
    """Contenido de la pestaña «Casos y ejecución» del HTML."""
    filas = _filas_entorno(datos)
    if not filas:
        return (
            "<p>Esta corrida no guardó datos de ejecución (IA simulada sin sandbox o "
            "corrida anterior al informe detallado).</p>"
        )
    entorno = "".join(
        f"<tr><th>{esc(k)}</th><td><code>{esc(v)}</code></td></tr>" for k, v in filas
    )
    partes = [f"<table><tbody>{entorno}</tbody></table>"]
    for f in _funciones_con_casos(datos):
        estado_lbl = ETIQUETAS_ESTADO.get(f["estado"], f["estado"])
        ejecucion = f["ejecucion"]
        historial = "".join(f"<li>{esc(h)}</li>" for h in _historial_intentos(f))
        casos = []
        for c in ejecucion["casos"]:
            falla = c["resultado"] in ("fallo", "error")
            clase = {"paso": "paso", "omitido": "omitido"}.get(c["resultado"], "fallo")
            detalle = ""
            if falla:
                texto = "\n".join(_lineas_caso(c, con_traza)[1:])
                traza = ""
                if con_traza and c.get("traza"):
                    traza = (
                        "<details><summary>Traza completa</summary>"
                        f"<pre>{esc(c['traza'])}</pre></details>"
                    )
                detalle = f"<pre class='fallo'>{esc(texto)}</pre>{traza}"
            etiqueta = _ETIQUETA_CASO.get(c["resultado"], c["resultado"])
            duracion = float(c.get("duracion_s") or 0)
            casos.append(
                f"<div class='caso {clase}'><b>{esc(etiqueta)}</b> {esc(c['nombre'])} "
                f"<small>{duracion:.2f} s</small>{detalle}</div>"
            )
        cubierta = _sin_cubrir_texto(ejecucion)
        cubierta_html = f"<p><small>{esc(cubierta)}</small></p>" if cubierta else ""
        salida = (
            "<details><summary>Salida completa de pytest</summary>"
            f"<pre>{esc(ejecucion['salida'])}</pre></details>"
            if con_traza and ejecucion.get("salida")
            else ""
        )
        partes.append(
            f"<div class='fn-card'><b>{esc(f['funcion'])}</b> "
            f"<span>({esc(f['modulo'])})</span> — <span class='badge'>{esc(estado_lbl)}</span>"
            f"<ul>{historial}</ul>{''.join(casos)}{cubierta_html}{salida}</div>"
        )
    return "".join(partes)


def _bloques_ejecucion(
    datos: dict[str, Any], con_traza: bool, limpiar: Any
) -> list[dict[str, Any]]:
    """Bloques del PDF (sección «Detalle»): datos de la ejecución y casos por función."""
    filas = _filas_entorno(datos)
    bloques: list[dict[str, Any]] = [
        {"tipo": "h2", "seccion": 3, "texto": "2.1 Datos de la ejecución"}
    ]
    if not filas:
        bloques.append(
            {
                "tipo": "texto",
                "seccion": 3,
                "texto": "Esta corrida no guardó datos de ejecución (IA simulada o anterior).",
            }
        )
        return bloques
    meta: list[tuple[str, str]] = []
    for etiqueta, valor in filas:
        for idx, linea in enumerate(_envolver_linea(limpiar(valor), 82)):
            meta.append((etiqueta + ":" if idx == 0 else "", linea))
    bloques.append({"tipo": "ficha_meta", "seccion": 3, "filas": meta})
    bloques.append(
        {"tipo": "h2", "seccion": 3, "texto": "2.2 Casos de prueba por función"}
    )
    for f in _funciones_con_casos(datos):
        ejecucion = f["ejecucion"]
        hay_fallo = any(
            c["resultado"] in ("fallo", "error") for c in ejecucion["casos"]
        )
        acento = "incidente" if hay_fallo else "codigo"
        bloques.append(
            {
                "tipo": "encabezado_bloque",
                "seccion": 3,
                "titulo": limpiar(f"{f['funcion']} ({f['modulo']})"),
                "etiqueta": "CASOS DE PYTEST",
                "acento": acento,
            }
        )
        lineas: list[str] = list(_historial_intentos(f))
        for caso in ejecucion["casos"]:
            lineas.extend(_lineas_caso(caso, con_traza))
        cubierta = _sin_cubrir_texto(ejecucion)
        if cubierta:
            lineas.append(cubierta)
        envueltas: list[str] = []
        for linea in lineas:
            envueltas.extend(_envolver_linea(limpiar(linea), 84) or [""])
        for idx, linea in enumerate(envueltas):
            bloques.append(
                {
                    "tipo": "linea_codigo",
                    "seccion": 3,
                    "texto": linea,
                    "acento": acento,
                    "primera": idx == 0,
                    "ultima": idx == len(envueltas) - 1,
                }
            )
        bloques.append({"tipo": "espacio", "seccion": 3, "alto": 6})
    return bloques
