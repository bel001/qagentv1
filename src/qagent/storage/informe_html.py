"""Informe en HTML de una corrida (HU-22)."""

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
from qagent.storage.informe_ejecucion import _html_comparacion, _html_ejecucion
from qagent.storage.informe_html_estilos import CSS_INFORME
from qagent.storage.informe_pdf import BANDEJA, ETAPAS, _explicacion
from qagent.storage.informe_salud import _salud_proyecto
from qagent.storage.vista_ejecucion import corrida_incompleta, respuesta_principal
from qagent.storage.vista_reporte import etiqueta_ia


def construir_html_informe(
    datos: dict[str, Any],
    opciones: Mapping[str, Any] | None = None,
    claves: Claves | None = None,
) -> str:
    """Construye un informe HTML interactivo con la identidad del rediseño."""
    import html as html_mod

    opts = normalizar_opciones(opciones)

    def esc(val: Any) -> str:
        return html_mod.escape(sanitizar_secretos(str(val or ""), claves))

    run_id = esc(datos["run_id"])
    proyecto = esc(datos["proyecto"])
    rama = esc(datos.get("rama") or "sin repositorio Git")
    fecha = esc(str(datos.get("fecha") or "")[:16].replace("T", " "))
    duracion = (
        f" · Duración: <b>{esc(_fmt_duracion(datos['duracion_total_s']))}</b>"
        if datos.get("duracion_total_s") is not None
        else ""
    )
    perfil = esc(datos["perfil"])
    total_fn = int(datos["total_funciones"])
    criticas = int(datos["criticas"])
    specs = (datos.get("specs") or {}).get("texto") or ""
    specs_txt = esc(specs.split(" · guardados en")[0])
    metricas = datos["metricas"]
    contadores = esc(
        (
            f"{datos['total_descubiertos']} descubiertos · "
            if datos.get("total_descubiertos") is not None
            else ""
        )
        + f"{datos.get('total_seleccionados', total_fn)} seleccionados · "
        f"{datos.get('total_elegibles', total_fn)} elegibles · "
        f"{datos.get('total_procesados', total_fn)} procesados · "
        f"{datos.get('total_omitidos', 0)} omitidos · "
        f"{datos.get('total_pendientes', 0)} pendientes"
    )
    fuera_html = "".join(
        f'\n    <p class="header-meta"><small><span class="badge-aviso">Aviso</span> '
        f"{esc(aviso)}</small></p>"
        for aviso in avisos_fuera_de_la_corrida(datos)
    )

    funciones = sorted(
        datos.get("funciones") or [],
        key=lambda f: (
            BANDEJA.get(str(f.get("estado")), BANDEJA["sin_veredicto"])[3],
            not f.get("critical"),
        ),
    )
    bugs = [
        f
        for f in funciones
        if BANDEJA.get(str(f.get("estado")), BANDEJA["sin_veredicto"])[0] == "bug"
    ]
    sin = [
        f
        for f in funciones
        if BANDEJA.get(str(f.get("estado")), BANDEJA["sin_veredicto"])[0]
        in ("sin", "repetir")
    ]
    total = len(funciones)
    respuesta = respuesta_principal(
        bugs=len(bugs),
        primer_bug=(
            str(bugs[0].get("identificador") or bugs[0].get("funcion") or "Función")
            if bugs
            else None
        ),
        sin_prueba=len(sin),
        total=total,
        omitidos=len(datos.get("omitidos") or []),
        incompleta=corrida_incompleta(datos),
    )
    respuesta = esc(respuesta)  # lleva el nombre de una función del proyecto

    m_dict = {x["clave"]: x for x in metricas}
    pasaron = sum(
        1
        for f in funciones
        if BANDEJA.get(str(f.get("estado")), BANDEJA["sin_veredicto"])[0] == "paso"
    )
    cob = m_dict.get("cobertura", {})
    tokens_val = (m_dict.get("costo") or {}).get("tokens_total")
    tokens_str = "—" if tokens_val is None else f"{int(tokens_val):,}".replace(",", ".")
    sub_cob = (
        "Ramas no exigidas en Humo"
        if datos.get("perfil") == "Humo"
        else f"{_fmt_pct(cob.get('ramas'))} de las ramas"
    )

    filas_metricas = []
    for m in metricas:
        if m.get("clave") == "costo":
            pill = '<span class="pill info">ℹ Informativo</span>'
        elif m["cumple"]:
            pill = '<span class="pill pass">✓ Cumple</span>'
        else:
            pill = '<span class="pill fail">✗ No cumple</span>'
        filas_metricas.append(
            f"<tr><td><b>{esc(m['nombre'])}</b></td><td>{esc(m['resultado'])}</td>"
            f"<td>{esc(m['meta'])}</td><td>{pill}</td></tr>"
        )

    salud = _salud_proyecto(datos)
    filas_puntos = []
    for inc in salud["incidentes"]:
        esp_obt = (
            f"Esperado: <code>{esc(inc['esperado'])}</code> | Obtenido: <code>{esc(inc['obtenido'])}</code>"
            if inc["esperado"] is not None and inc["obtenido"] is not None
            else "—"
        )
        accion_txt = (
            f"<br><small style='color:#388bfd'><b>Acción sugerida:</b> {esc(inc['accion_sugerida'])}</small>"
            if inc.get("accion_sugerida")
            else ""
        )
        filas_puntos.append(
            f"<tr><td><b>{esc(inc['funcion'])}</b></td>"
            f"<td><code>{esc(inc['ubicacion'])}</code></td>"
            f"<td>{esc(inc['causa'])}{accion_txt}</td>"
            f"<td><small>{esp_obt}</small></td></tr>"
        )
    tabla_puntos_html = (
        f"<h3 style='margin:18px 0 8px 0;font-size:14px;color:#f0f6fc'>Puntos de atención que requieren corrección en el código</h3>"
        f"<table><thead><tr><th>Función</th><th>Ubicación (archivo:línea)</th><th>Causa del fallo y sugerencia</th><th>Esperado vs Obtenido</th></tr></thead>"
        f"<tbody>{''.join(filas_puntos)}</tbody></table>"
        if filas_puntos
        else ""
    )

    fortalezas_items = "".join(
        f"<li style='margin-bottom:6px'><b>✅</b> {esc(f)}</li>"
        for f in salud["fortalezas"]
    )
    deficiencias_items = "".join(
        f"<li style='margin-bottom:6px'><b>⚠️</b> {esc(d)}</li>"
        for d in salud["deficiencias"]
    )
    recomendaciones_items = "".join(
        f"<li style='margin-bottom:6px'><b>👉</b> {esc(r)}</li>"
        for r in salud["recomendaciones"]
    )
    color_score = (
        "#3fb950"
        if salud["indice_salud"] >= 75
        else ("#d29922" if salud["indice_salud"] >= 50 else "#f85149")
    )

    salud_html = (
        f"<div class='salud-card'>"
        f"<div style='display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:12px;margin-bottom:12px'>"
        f"<div>"
        f"<h3 style='margin:0 0 4px 0;font-size:16px;color:#f0f6fc'>🏥 Estado de Salud del Proyecto</h3>"
        f"<p style='margin:0;font-size:13px;color:#8b949e'>Evaluación técnica para desarrolladores y auditoría de calidad</p>"
        f"</div>"
        f"<div style='text-align:right'>"
        f"<div style='font-size:26px;font-weight:800;color:{color_score}'>{salud['indice_salud']}/100</div>"
        f"<small style='color:#8b949e;font-weight:600'>{esc(salud['nivel_madurez'])}</small>"
        f"</div>"
        f"</div>"
        f"<p style='margin:0 0 12px 0;font-size:13px;line-height:1.5'>{esc(salud['diagnostico'])}</p>"
        f"<div style='display:flex;gap:10px;flex-wrap:wrap;margin-bottom:14px'>"
        f"<span class='pill pass'>✓ {salud['aprobadas']} aprobadas ({salud['pct_aprobadas']:.1f}%)</span>"
        f"<span class='pill fail'>🐛 {salud['bugs']} defectos en código</span>"
        f"<span class='pill fail'>🛡️ {salud['laundering']} pruebas debilitadas bloqueadas</span>"
        f"<span class='pill' style='color:#d29922;font-weight:700'>⏳ {salud['estancadas']} estancadas</span>"
        f"</div>"
        f"<div style='display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:14px;margin-top:14px'>"
        f"<div class='salud-col'>"
        f"<h4 style='margin:0 0 8px 0;font-size:13px;color:#3fb950'>🛡️ Fortalezas del Proyecto</h4>"
        f"<ul style='margin:0;padding-left:16px;font-size:12.5px;color:#8b949e;line-height:1.45'>{fortalezas_items}</ul>"
        f"</div>"
        f"<div class='salud-col'>"
        f"<h4 style='margin:0 0 8px 0;font-size:13px;color:#f85149'>⚠️ Deficiencias Detectadas</h4>"
        f"<ul style='margin:0;padding-left:16px;font-size:12.5px;color:#8b949e;line-height:1.45'>{deficiencias_items}</ul>"
        f"</div>"
        f"<div class='salud-col'>"
        f"<h4 style='margin:0 0 8px 0;font-size:13px;color:#388bfd'>🚀 Plan de Mejora Accionable</h4>"
        f"<ul style='margin:0;padding-left:16px;font-size:12.5px;color:#8b949e;line-height:1.45'>{recomendaciones_items}</ul>"
        f"</div>"
        f"</div>"
        f"{tabla_puntos_html}"
        f"</div>"
    )

    tarjetas_fn = []
    for f in funciones:
        _, etiqueta, clase, _ = BANDEJA.get(
            str(f.get("estado")), BANDEJA["sin_veredicto"]
        )
        ms_lbl = (
            "—"
            if not f.get("critical")
            else (
                "Pendiente"
                if f.get("mutation_score") is None
                else f"{f['mutation_score']:g}%"
            )
        )
        contrato = f.get("contrato") or {}
        casos_plan = _resumen_casos_planner(contrato)
        firma = (
            f.get("firma")
            or contrato.get("firma")
            or f.get("manejador")
            or f["funcion"]
        )
        nom = str(f.get("identificador") or f.get("funcion") or "Función")
        casos_plan_txt = "".join(
            f"<li><b>[{esc(cp['id'])}]</b> {esc(cp['descripcion'])}"
            + (
                f" · Entrada: <code>{esc(cp['entrada'])}</code>"
                if cp.get("entrada") is not None
                else ""
            )
            + (
                f" · Esperado: <code>{esc(cp['esperado'])}</code>"
                if cp.get("esperado") is not None
                else ""
            )
            + (
                f" · Excepción: <code>{esc(cp['excepcion'])}</code>"
                if cp.get("excepcion")
                else ""
            )
            + "</li>"
            for cp in casos_plan
        )
        casos_plan_html = (
            f"<ul>{casos_plan_txt}</ul>"
            if casos_plan_txt
            else "<p><i>Sin casos planificados.</i></p>"
        )

        intentos_items = []
        for it in f.get("intentos") or []:
            dec = _ETIQUETA_DECISION.get(str(it.get("decision")), it.get("decision"))
            fb = it.get("feedback")
            fb_txt = f" — <i>{esc(fb)}</i>" if fb else ""
            intentos_items.append(
                f"<li>Intento {it.get('intento')}: {esc(dec)}{fb_txt}</li>"
            )
        intentos_html = (
            f"<ul>{''.join(intentos_items)}</ul>"
            if intentos_items
            else "<p><i>1 intento registrado.</i></p>"
        )

        laund_txt = (
            "<span class='pill fail'>Se bloqueó debilitar prueba</span>"
            if f.get("laundering_detectado")
            else "<span class='pill pass'>Criterio conservado</span>"
        )
        llama_a = contrato.get("llama_a")
        llama_html = (
            f"<p><small><b>Dependencias simuladas:</b> {', '.join(f'<code>{esc(m)}</code>' for m in llama_a)}</small></p>"
            if llama_a
            else ""
        )

        badge_class = f"badge-{clase}"
        tarjetas_fn.append(
            f"<div class='fn-card'>"
            f"<div style='display:flex;justify-content:space-between;align-items:center;margin-bottom:8px'>"
            f"<b><code>{esc(nom)}</code></b> <span>({esc(f['modulo'])})</span> — <span class='badge {badge_class}'>{esc(etiqueta)}</span>"
            f"</div>"
            f"<small>Lenguaje: {esc(f.get('lenguaje', 'python'))} · Intentos: {f.get('iteraciones', 1)}/3 · Cob. líneas: {_fmt_pct(f.get('cobertura_lineas'))} · "
            f"Cob. ramas: {_fmt_pct(f.get('cobertura_ramas'))} · Fortaleza: {esc(ms_lbl)} · "
            f"Tokens: {f.get('tokens', 0)}</small>"
            f"<div class='agent-grid'>"
            f"<div class='agent-box'><h4>📋 Análisis (AST)</h4>"
            f"<p><small><b>Firma:</b> <code>{esc(firma)}</code> | <b>Criticidad:</b> {'Crítica' if f.get('critical') else 'Estándar'}</small></p>"
            f"{llama_html}"
            f"<details><summary>Casos deducidos ({len(casos_plan)})</summary>{casos_plan_html}</details>"
            f"</div>"
            f"<div class='agent-box'><h4>⚙️ Suite {esc(f.get('framework_pruebas', 'pytest'))}</h4>"
            f"<p><small><b>Prueba generada para:</b> <code>{esc(f['funcion'])}</code></small></p>"
            f"<p><small><b>Iteraciones:</b> {f.get('iteraciones', 1)}/3 | <b>Aislamiento:</b> Sandbox Docker hermético</small></p>"
            f"</div>"
            f"<div class='agent-box'><h4>🛡️ Verificación</h4>"
            f"<p><small><b>Veredicto:</b> {esc(etiqueta)} | <b>Integridad:</b> {laund_txt}</small></p>"
            f"<details><summary>Historial de intentos y diagnósticos</summary>{intentos_html}</details>"
            f"</div>"
            f"</div>"
            f"</div>"
        )

    tarjetas_inc = []
    incidentes = [f for f in funciones if not f.get("verde", True) or f.get("traza")]
    if not incidentes:
        tarjetas_inc.append(
            "<p>No se registraron incidentes ni trazas de fallo en esta corrida.</p>"
        )
    else:
        for f in incidentes:
            _, etiqueta, clase, _ = BANDEJA.get(
                str(f.get("estado")), BANDEJA["sin_veredicto"]
            )
            nom = str(f.get("identificador") or f.get("funcion") or "Función")
            motivo = f.get("motivo_fallo") or (
                "Se bloqueó un intento de debilitar pruebas (aserciones relajadas)"
                if f.get("laundering_detectado")
                else (
                    "Defecto confirmado en código"
                    if f.get("estado") == "bug_detectado"
                    else "Error detectado durante la validación"
                )
            )
            ejec_f = f.get("ejecucion") or {}
            casos_fallidos = [
                c
                for c in ejec_f.get("casos", [])
                if c.get("resultado") in ("fallo", "error")
            ]
            filas_cf = []
            for cf in casos_fallidos:
                donde = f"{cf['archivo']}:{cf['linea']}" if cf.get("archivo") else "—"
                esp_obt = ""
                if cf.get("esperado") is not None or cf.get("obtenido") is not None:
                    esp_obt = (
                        f" · Esperado: <code>{esc(cf.get('esperado'))}</code> | "
                        f"Obtenido: <code>{esc(cf.get('obtenido'))}</code>"
                    )
                filas_cf.append(
                    f"<li><b>{esc(cf['nombre'])}</b> (en <code>{esc(donde)}</code>){esp_obt}</li>"
                )
            casos_fallidos_html = (
                f"<ul style='margin:6px 0 10px 18px'>{''.join(filas_cf)}</ul>"
                if filas_cf
                else ""
            )

            laund_alerta = (
                "<div class='alerta-laundering'>"
                "<b>🛡️ Alerta de integridad:</b> Criterio original conservado "
                "(se bloqueó un intento de relajar o debilitar las aserciones)."
                "</div>"
                if f.get("laundering_detectado")
                else ""
            )

            fb_list = "".join(
                f"<li><b>Intento {it.get('intento')}:</b> {esc(it.get('feedback') or 'Sin diagnóstico')}</li>"
                for it in (f.get("intentos") or [])
                if it.get("feedback")
            )
            fb_html = (
                f"<details style='margin:8px 0'><summary style='cursor:pointer;color:#388bfd;font-size:12px'>"
                f"Diagnósticos por intento ({len(f.get('intentos') or [])})</summary>"
                f"<ul>{fb_list}</ul></details>"
                if fb_list
                else ""
            )
            traza_html = (
                f"<details open style='margin-top:8px'><summary style='cursor:pointer;color:#f85149;font-size:12px'>Traza del error en pytest</summary>"
                f"<pre class='fallo'>{esc(f['traza'])}</pre></details>"
                if f.get("traza")
                else "<p><i>Sin traza registrada.</i></p>"
            )
            tarjetas_inc.append(
                f"<div class='fn-card'>"
                f"<div style='display:flex;justify-content:space-between;align-items:center;margin-bottom:8px'>"
                f"<h3><code>{esc(nom)}</code> <span style='font-weight:400;color:#8b949e'>({esc(f['modulo'])})</span></h3>"
                f"<span class='badge badge-{clase}'>{esc(etiqueta)}</span>"
                f"</div>"
                f"<p style='margin:4px 0;font-size:13px'><b>Parte del código afectada:</b> <code>{esc(f['modulo'])}::{esc(f['funcion'])}</code></p>"
                f"<p style='margin:4px 0;font-size:13px'><b>¿Por qué falló?:</b> {esc(motivo)}</p>"
                f"{laund_alerta}"
                f"{casos_fallidos_html}"
                f"{fb_html}"
                f"{traza_html}"
                f"</div>"
            )

    tarjetas_cod = []
    for f in funciones:
        cod = f.get("codigo")
        cod_html = (
            f"<pre><code>{esc(cod)}</code></pre>"
            if cod
            else "<p><i>Sin código registrado.</i></p>"
        )
        tarjetas_cod.append(
            f"<div class='fn-card'><b>tests/test_{esc(f['funcion'])}.py</b> ({esc(f['modulo'])})<br>{cod_html}</div>"
        )

    tarjetas_con = []
    for f in funciones:
        con = f.get("contrato")
        con_str = json.dumps(con, indent=2, ensure_ascii=False) if con else None
        con_html = (
            f"<pre><code>{esc(con_str)}</code></pre>"
            if con_str
            else "<p><i>Sin contrato registrado.</i></p>"
        )
        tarjetas_con.append(
            f"<div class='fn-card'><b>{esc(f['funcion'])}</b> ({esc(f['modulo'])})<br>{con_html}</div>"
        )

    modelos_str = " · ".join(
        f"{esc(etapa)}: {esc(datos['modelos'][ag]['modelo'])}"
        for ag, etapa in ETAPAS
        if ag in datos.get("modelos", {})
    )

    prioridades_items = []
    if bugs:
        for n, f in enumerate(bugs[:3], start=1):
            nom = str(f.get("identificador") or f.get("funcion") or "Función")
            exp = _explicacion(f)
            exp_txt = (
                f"<p style='margin:4px 0 0 0;font-size:13px;color:#8b949e'>"
                f"{esc(exp.splitlines()[0])}</p>"
                if exp
                else ""
            )
            etiqueta = etiqueta_ia(f.get("explicacion"))  # #166
            if etiqueta:
                exp_txt += (
                    "<p style='margin:2px 0 0 0;font-size:11px;font-style:italic;"
                    f"color:#8b949e'>{esc(etiqueta)}</p>"
                )
            prioridades_items.append(
                f"<div class='prioridad-card'>"
                f"<div style='font-size:11px;font-weight:700;color:#388bfd;text-transform:uppercase'>Prioridad {n}</div>"
                f"<div style='font-size:15px;font-weight:700;margin-top:2px'>Corrige <code>{esc(nom)}</code> · {esc(f.get('modulo', ''))}</div>"
                f"{exp_txt}"
                f"</div>"
            )
    prioridades_html = (
        "".join(prioridades_items)
        if prioridades_items
        else "<p>No hay posibles bugs que requieran acción prioritaria.</p>"
    )

    filas_entorno_html = "".join(
        f"<tr><th>{esc(k)}</th><td><code>{esc(v)}</code></td></tr>"
        for k, v in _filas_entorno(datos)
        if k != "Comando" or opts["trazas"]
    )

    return f"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<title>Informe QAgent — Corrida #{run_id}</title>
<style>
{CSS_INFORME}
</style>
</head>
<body>
<div class="wrap">
  <div class="header">
    <div class="header-top">
      <svg width="28" height="28" viewBox="0 0 100 100" fill="none" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="QAgent">
        <path d="M70.4002 9.46875H25.8076L8.17798 27.3188V65.1188L25.8076 82.9688H62.1039L69.2248 74.9349M69.2248 74.9349L81.6039 60.9688M69.2248 74.9349L61 67M69.2248 74.9349L85.3909 90.5312M40 46L55.8909 62L91.8219 24.5" stroke-width="7.6" stroke-linecap="square" stroke="#F1F3F6"/>
      </svg>
      <h1 class="header-title">QAgent · Informe de pruebas — Corrida #{run_id}</h1>
    </div>
    <div class="respuesta">{respuesta}</div>
    <p class="header-meta">Proyecto: <b>{proyecto}</b> · Rama: <b>{rama}</b> · Fecha: <b>{fecha}</b> · Perfil: <b>{perfil}</b> · Funciones: <b>{total_fn}</b> ({criticas} críticas){duracion}</p>
    <p class="header-meta"><small>Objetivos: {contadores}</small></p>{fuera_html}
    <p class="header-meta"><small>Etapas: {modelos_str} · Specs: {specs_txt}</small></p>
    <div class="cifras-grid">
      <div class="cifra-card">
        <div class="cifra-etq">Pasaron</div>
        <div class="cifra-val">{pasaron} / {total}</div>
        <div class="cifra-sub">{total - pasaron} con algo por revisar</div>
      </div>
      <div class="cifra-card">
        <div class="cifra-etq">Posibles bugs</div>
        <div class="cifra-val{" val-bug" if bugs else ""}">{len(bugs)}</div>
        <div class="cifra-sub">En {len(bugs)} de {total}</div>
      </div>
      <div class="cifra-card">
        <div class="cifra-etq">Cobertura</div>
        <div class="cifra-val">{_fmt_pct(cob.get("lineas"))}</div>
        <div class="cifra-sub">{sub_cob}</div>
      </div>
      <div class="cifra-card">
        <div class="cifra-etq">Tokens de la corrida</div>
        <div class="cifra-val">{tokens_str}</div>
        <div class="cifra-sub">Sumando las tres etapas</div>
      </div>
    </div>
  </div>
  {_html_comparacion(datos, esc)}
  <div class="tabs">
    <button class="tab active" onclick="verTab('t1',this)">1. Resumen y Metas</button>
    <button class="tab" onclick="verTab('t2',this)">2. Detalle por Función</button>
    <button class="tab" onclick="verTab('t3',this)">3. Casos y ejecución</button>
    <button class="tab" onclick="verTab('t4',this)">4. Dónde falló el código (Incidentes)</button>
    <button class="tab" onclick="verTab('t5',this)">5. Suites Generadas (Anexo)</button>
    <button class="tab" onclick="verTab('t6',this)">6. Contratos del análisis (Anexo Secundario)</button>
    <button class="tab" onclick="verTab('t7',this)">7. Datos de la ejecución (Anexo Técnico)</button>
  </div>
  <div id="t1" class="panel active">
    <h2>1. Metas de calidad y Por dónde empezar</h2>
    {prioridades_html}
    {salud_html}
    <table><thead><tr><th>Métrica</th><th>Resultado</th><th>Meta</th><th>Estado</th></tr></thead>
    <tbody>{"".join(filas_metricas)}</tbody></table>
  </div>
  <div id="t2" class="panel">
    <h2>2. Resultado por función</h2>
    {"".join(tarjetas_fn) if opts["detalle"] else "<p>Sección opcional desactivada.</p>"}
  </div>
  <div id="t3" class="panel">
    <h2>3. Casos y ejecución</h2>
    {_html_ejecucion(datos, opts["trazas"], esc) if opts["detalle"] else "<p>Sección opcional desactivada.</p>"}
  </div>
  <div id="t4" class="panel">
    <h2>4. Dónde falló el código (Incidentes y Errores)</h2>
    {"".join(tarjetas_inc) if opts["trazas"] else "<p>Sección opcional desactivada.</p>"}
  </div>
  <div id="t5" class="panel">
    <h2>5. Código de las pruebas generadas (Anexo)</h2>
    {"".join(tarjetas_cod) if opts["codigo"] else "<p>Sección opcional desactivada.</p>"}
  </div>
  <div id="t6" class="panel">
    <h2>6. Contratos JSON del análisis (Anexo Secundario)</h2>
    {"".join(tarjetas_con) if opts["contratos"] else "<p>Sección opcional desactivada.</p>"}
  </div>
  <div id="t7" class="panel">
    <h2>7. Datos de la ejecución (Anexo Técnico)</h2>
    <table><tbody>{filas_entorno_html}</tbody></table>
  </div>
</div>
<script>
function verTab(id,btn){{
  document.querySelectorAll('.panel').forEach(p=>p.classList.remove('active'));
  document.querySelectorAll('.tab').forEach(b=>b.classList.remove('active'));
  document.getElementById(id).classList.add('active');
  btn.classList.add('active');
}}
</script>
</body>
</html>"""
