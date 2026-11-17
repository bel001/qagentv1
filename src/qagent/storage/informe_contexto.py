"""Procedencia legible del contexto documental para todos los informes."""

from typing import Any


def lineas_contexto(datos: dict[str, Any]) -> list[str]:
    """Describe las fuentes recuperadas y los objetivos que siguen sin contrato."""
    lineas = []
    for objetivo in datos.get("contexto_automatico") or []:
        contexto = objetivo["contexto"]
        lineas.append(
            f"{objetivo['objetivo']} · {objetivo['modulo']}: {contexto['estado'].replace('_', ' ')}."
        )
        lineas.append(contexto["motivo"])
        vistos = set()
        for fuente in contexto.get("fuentes", []):
            clave = (fuente["archivo"], fuente["linea_inicio"], fuente["fragmento"])
            if clave in vistos:
                continue
            vistos.add(clave)
            lineas.append(
                f"Fuente: {fuente['archivo']}:{fuente['linea_inicio']} — {fuente['fragmento']}"
            )
        if not vistos:
            archivos = contexto.get("archivos_revisados", [])
            lineas.append(
                "Archivos revisados: " + (", ".join(archivos) or "ninguno legible")
            )
    return lineas
