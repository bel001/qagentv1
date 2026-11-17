"""Medición acotada del disco sin seguir enlaces de proyectos no confiables."""

from __future__ import annotations

import os
from pathlib import Path


def tamano_carpeta(raiz: Path, limite: int) -> int:
    """Suma bytes hasta superar el límite; nunca sigue enlaces ni archivos especiales."""
    total = 0
    pendientes = [raiz]
    base = raiz.resolve()
    while pendientes:
        carpeta = pendientes.pop()
        try:
            with os.scandir(carpeta) as entradas:
                for entrada in entradas:
                    if entrada.is_symlink():
                        continue
                    if entrada.is_dir(follow_symlinks=False):
                        if _dentro_de(entrada, base):
                            pendientes.append(Path(entrada.path))
                    elif entrada.is_file(follow_symlinks=False):
                        total += entrada.stat(follow_symlinks=False).st_size
                        if total > limite:
                            return total
        except (OSError, ValueError):
            continue
    return total


def _dentro_de(entrada: os.DirEntry[str], base: Path) -> bool:
    """Si la carpeta sigue dentro de `base` (una unión de Windows puede salir de ella).

    Una carpeta corriente no puede salir; resolver su ruta es costoso en Windows y
    solo hace falta cuando es una unión o no se puede saber (Python < 3.12).
    """
    es_union = getattr(entrada, "is_junction", None)
    if es_union is not None and not es_union():
        return True
    return Path(entrada.path).resolve().is_relative_to(base)
