"""Filas de detalle por función usadas por los informes (HU-22)."""

from __future__ import annotations

from typing import Any

from qagent.storage.informe_comun import (
    _ETIQUETA_CASO,
    _ETIQUETA_DECISION,
    _MOTIVO_FALLO,
)


def _simple(f: dict[str, Any], campo: str) -> str | None:
    """Un campo de la explicación del Explicador (HU-32), o None si no hay."""
    explicacion = f.get("explicacion")
    if not isinstance(explicacion, dict):
        return None
    return explicacion.get(campo) or None


def _funciones_con_casos(datos: dict[str, Any]) -> list[dict[str, Any]]:
    return [f for f in datos["funciones"] if f.get("ejecucion")]


def _historial_intentos(f: dict[str, Any]) -> list[str]:
    """Una línea por intento: decisión del Reviewer y causa."""
    lineas = []
    for i in f.get("intentos") or []:
        decision = _ETIQUETA_DECISION.get(
            str(i.get("decision")), str(i.get("decision"))
        )
        extra = []
        causa = _MOTIVO_FALLO.get(str(i.get("tipo_fallo")), "")
        if causa:
            extra.append(causa)
        if i.get("laundering_detectado"):
            extra.append("aserciones relajadas")
        if not i.get("ejecucion"):
            extra.append("no llegó al sandbox")
        sufijo = f" ({'; '.join(extra)})" if extra else ""
        lineas.append(f"Intento {i.get('intento')}: {decision}{sufijo}")
    return lineas


def _lineas_caso(caso: dict[str, Any], con_traza: bool = True) -> list[str]:
    """Texto plano de un caso: resultado y, si falló, dónde, qué y esperado/obtenido."""
    etiqueta = _ETIQUETA_CASO.get(caso["resultado"], str(caso["resultado"]).upper())
    duracion = float(caso.get("duracion_s") or 0)
    lineas = [f"[{etiqueta}] {caso['nombre']} ({duracion:.2f} s)"]
    if caso["resultado"] in ("fallo", "error"):
        if caso.get("archivo"):
            lineas.append(f"  Dónde: {caso['archivo']}:{caso.get('linea')}")
        if caso.get("codigo"):
            lineas.append(f"  Línea: {caso['codigo']}")
        mensaje = str(caso.get("mensaje") or "").splitlines()
        partes = (caso.get("tipo_error"), mensaje[0] if mensaje else "")
        error = " — ".join(p for p in partes if p)
        if error:
            lineas.append(f"  Qué falló: {error}")
        if caso.get("esperado") is not None or caso.get("obtenido") is not None:
            lineas.append(f"  Esperado: {caso.get('esperado')}")
            lineas.append(f"  Obtenido: {caso.get('obtenido')}")
        if con_traza and caso.get("pila"):
            lineas.append("  Pila de llamadas:")
            for marco in caso["pila"]:
                detalle = " ".join(
                    p for p in (marco.get("detalle"), marco.get("codigo")) if p
                )
                lineas.append(
                    f"    {marco['archivo']}:{marco['linea']} {detalle}".rstrip()
                )
    elif caso["resultado"] == "omitido" and caso.get("mensaje"):
        lineas.append(f"  Motivo: {caso['mensaje']}")
    return lineas


def _sin_cubrir_texto(ejecucion: dict[str, Any]) -> str | None:
    sin_cubrir = ejecucion.get("lineas_sin_cubrir")
    if sin_cubrir is None:
        return None
    return "Líneas de la función sin cubrir: " + (
        ", ".join(str(n) for n in sin_cubrir) if sin_cubrir else "ninguna"
    )
