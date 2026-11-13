"""Escritura y verificación de los archivos de informe exportados (HU-22)."""

from __future__ import annotations

import contextlib
import os
import re
import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from qagent.config.auditoria import PATRONES, Hallazgo
from qagent.config.carga import Claves
from qagent.storage.informe_comun import (
    FORMATOS,
    FormatoInvalido,
    normalizar_opciones,
    sanitizar_secretos,
)
from qagent.storage.informe_datos import datos_informe
from qagent.storage.informe_html import construir_html_informe
from qagent.storage.informe_json import construir_json_informe
from qagent.storage.informe_markdown import construir_markdown_informe
from qagent.storage.informe_pdf import _decodificar_literal_pdf
from qagent.storage.registro import CARPETA_RUNS


def nombre_archivo_informe(run_id: str, formato: str) -> str:
    """Nombre estándar del archivo exportado según el formato (Criterio 2)."""
    fmt = (formato or "").strip().lower()
    nombre_run = Path(run_id).name
    if fmt == "pdf":
        return f"informe_{nombre_run}.pdf"
    if fmt == "md":
        return f"informe_{nombre_run}.md"
    if fmt == "json":
        return f"results_{nombre_run}.json"
    if fmt == "html":
        return f"informe_{nombre_run}.html"
    raise FormatoInvalido(
        f"Formato de exportación no válido: {formato!r} (se espera pdf, md, json o html)."
    )


def carpeta_por_defecto(raiz_proyecto: str | Path, run_id: str) -> Path:
    """Carpeta por defecto donde se guarda el informe: `<proyecto>/.qagent/runs/<run_id>/`."""
    return Path(raiz_proyecto) / CARPETA_RUNS / Path(run_id).name


def construir_pdf_informe(
    datos: dict[str, Any],
    opciones: Mapping[str, Any] | None = None,
    claves: Claves | None = None,
) -> bytes:
    """Construye un documento PDF-1.4 válido y multipágina sin dependencias externas.

    El diseño (estructura, textos y colores) es el del rediseño de la interfaz: ver
    `qagent.storage.informe_pdf`.
    """
    from qagent.storage.informe_pdf import construir_pdf

    opts = normalizar_opciones(opciones)
    return construir_pdf(
        datos, opts, lambda texto: sanitizar_secretos(str(texto), claves)
    )


def exportar_informe(
    raiz_proyecto: str | Path,
    run_id: str | None = None,
    formato: str = "pdf",
    opciones: Mapping[str, Any] | None = None,
    carpeta_destino: str | Path | None = None,
    claves: Claves | None = None,
) -> dict[str, Any]:
    """Exporta el informe de la corrida en el formato e ubicación indicados (HU-22).

    Returns:
        dict con `ok`, `run_id`, `formato`, `nombre`, `ruta`, `carpeta` y `opciones`.
    """
    fmt = (formato or "").strip().lower()
    if fmt not in FORMATOS:
        raise FormatoInvalido(
            f"Formato de exportación no válido: {formato!r} (se espera pdf, md, json o html)."
        )

    datos = datos_informe(raiz_proyecto, run_id=run_id, claves=claves)
    run_actual = datos["run_id"]
    opts = normalizar_opciones(opciones)
    nombre = nombre_archivo_informe(run_actual, fmt)

    if carpeta_destino is not None and str(carpeta_destino).strip():
        carpeta = Path(carpeta_destino)
    else:
        carpeta = carpeta_por_defecto(raiz_proyecto, run_actual)

    carpeta.mkdir(parents=True, exist_ok=True)
    ruta_archivo = carpeta / nombre

    if fmt == "md":
        contenido_md = construir_markdown_informe(datos, opts, claves)
        _escribir_bytes_atomico(ruta_archivo, contenido_md.encode("utf-8"))
    elif fmt == "json":
        contenido_json = construir_json_informe(datos, opts, claves)
        _escribir_bytes_atomico(ruta_archivo, contenido_json.encode("utf-8"))
    elif fmt == "html":
        contenido_html = construir_html_informe(datos, opts, claves)
        _escribir_bytes_atomico(ruta_archivo, contenido_html.encode("utf-8"))
    else:
        contenido_pdf = construir_pdf_informe(datos, opts, claves)
        _escribir_bytes_atomico(ruta_archivo, contenido_pdf)

    return {
        "ok": True,
        "run_id": run_actual,
        "formato": fmt,
        "nombre": nombre,
        "ruta": str(ruta_archivo),
        "carpeta": str(carpeta),
        "opciones": opts,
    }


def extraer_texto_pdf(origen: str | Path | bytes) -> str:
    """Extrae el texto legible de un PDF generado por QAgent para verificación y auditoría."""
    datos = (
        origen.read_bytes()
        if isinstance(origen, Path)
        else (Path(origen).read_bytes() if isinstance(origen, str) else bytes(origen))
    )
    texto_raw = datos.decode("latin-1", errors="replace")
    fragmentos: list[str] = []
    for coincidencia in re.finditer(r"\((?:\\.|[^\\()])*\)\s*Tj", texto_raw):
        literal = coincidencia.group(0)
        inicio = literal.find("(")
        fin = literal.rfind(")")
        cuerpo = literal[inicio + 1 : fin]
        fragmentos.append(_decodificar_literal_pdf(cuerpo))
    return "\n".join(fragmentos)


def verificar_archivo_sin_claves(ruta: str | Path) -> list[Hallazgo]:
    """Verifica que un archivo exportado (.pdf, .md o .json) no contenga claves (RN-07)."""
    ruta_path = Path(ruta)
    textos: list[str] = []
    try:
        textos.append(ruta_path.read_text(encoding="utf-8", errors="replace"))
    except OSError:
        return []
    if ruta_path.suffix.lower() == ".pdf":
        with contextlib.suppress(OSError):
            textos.append(extraer_texto_pdf(ruta_path))

    hallazgos: list[Hallazgo] = []
    for texto in textos:
        for num, linea in enumerate(texto.splitlines(), start=1):
            if "base64," in linea:
                continue
            for nombre, patron in PATRONES.items():
                if patron.search(linea):
                    hallazgos.append(Hallazgo(ruta_path.name, num, nombre))
                    break
        if hallazgos:
            break
    return hallazgos


def _escribir_bytes_atomico(ruta: Path, datos: bytes) -> None:
    """Escribe un archivo de forma atómica en la carpeta destino."""
    descriptor, temporal = tempfile.mkstemp(
        prefix=f".{ruta.name}.", suffix=".tmp", dir=ruta.parent
    )
    try:
        with os.fdopen(descriptor, "wb") as archivo:
            archivo.write(datos)
        os.replace(temporal, ruta)
    except BaseException:
        Path(temporal).unlink(missing_ok=True)
        raise
