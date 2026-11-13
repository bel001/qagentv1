"""Constantes y utilidades compartidas de los informes (HU-22)."""

from __future__ import annotations

import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from qagent.config import carga as config_carga
from qagent.config.auditoria import PATRONES
from qagent.config.carga import Claves, leer_env
from qagent.storage.informe_pdf import BANDEJA, CONTROL, ETAPAS

NOMBRES_ETAPAS = dict(ETAPAS)
NOMBRES_AGENTE = NOMBRES_ETAPAS
ETIQUETAS_ESTADO = {k: v[1] for k, v in BANDEJA.items()}
ETIQUETAS_CONTROL = CONTROL


FORMATOS = ("pdf", "md", "json", "html")


_PATRON_ASIGNACION = re.compile(
    r"""(?ix)(\b[A-Z0-9_]*(?:API_?KEY|SECRET|PASSWORD|(?:ACCESS|AUTH|API)_?TOKEN)\b\s*[=:]\s*["']?)
    (?!os\.|environ|getenv)[A-Za-z0-9_\-/+=]{16,}"""
)


class FormatoInvalido(ValueError):
    """El formato solicitado no es pdf, md, json ni html."""


def normalizar_opciones(opciones: Mapping[str, Any] | None = None) -> dict[str, bool]:
    """Normaliza qué incluir en el informe (el resumen va siempre: Criterio 1)."""
    src = opciones or {}
    return {
        "resumen": True,
        "detalle": bool(src.get("detalle", True)),
        "trazas": bool(src.get("trazas", True)),
        "codigo": bool(src.get("codigo", True)),
        "contratos": bool(src.get("contratos", True)),
    }


def sanitizar_secretos(texto: str, claves: Claves | None = None) -> str:
    """Elimina cualquier clave de IA o patrón de secreto del texto (RN-07, Criterio 5)."""
    if not texto:
        return texto
    if claves is not None:
        texto = claves.redactar(texto)
    try:
        ruta_env = Path(config_carga.RUTA_ENV)
        if ruta_env.is_file():
            texto = Claves(leer_env(ruta_env)).redactar(texto)
    except (OSError, UnicodeDecodeError):
        pass

    texto = _PATRON_ASIGNACION.sub(r"\1***", texto)
    for nombre, patron in PATRONES.items():
        if nombre == "asignación de clave":
            continue
        texto = patron.sub("***", texto)
    return texto


def _sanitizar_estructura(dato: Any, claves: Claves | None = None) -> Any:
    """Aplica `sanitizar_secretos` recursivamente sobre diccionarios y listas."""
    if isinstance(dato, str):
        return sanitizar_secretos(dato, claves)
    if isinstance(dato, list):
        return [_sanitizar_estructura(item, claves) for item in dato]
    if isinstance(dato, dict):
        return {
            sanitizar_secretos(str(k), claves) if isinstance(k, str) else k: (
                _sanitizar_estructura(v, claves)
            )
            for k, v in dato.items()
        }
    return dato


_ETIQUETA_CASO = {
    "paso": "PASÓ",
    "fallo": "FALLÓ",
    "error": "ERROR",
    "omitido": "OMITIDO",
}


_ETIQUETA_DECISION = {
    "accept": "Aceptado",
    "retry": "Reintento",
    "bug_detectado": "Bug detectado",
    "stalled": "Estancado",
}


_MOTIVO_FALLO = {
    "bug_codigo": "el código no cumple el contrato",
    "error_test": "el test estaba mal escrito",
}


def _fmt_pct(valor: float | None) -> str:
    return "—" if valor is None else f"{valor:.1f}%"


def _fmt_duracion(valor: Any) -> str:
    """Duración legible: ms por debajo de 1 s, segundos con un decimal."""
    if isinstance(valor, bool) or not isinstance(valor, (int, float)):
        return "—"
    if valor < 1:
        return f"{round(valor * 1000)} ms"
    return f"{float(valor):.1f} s"
