"""Convierte un informe de resolución de pip en restricciones completas para Windows."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def escribir_lock(informe: Path, salida: Path) -> None:
    """Fija todas las versiones resueltas, sin añadir URLs ni credenciales del reporte."""
    datos = json.loads(informe.read_text(encoding="utf-8"))
    versiones = {}
    for paquete in datos["install"]:
        meta = paquete["metadata"]
        if meta["name"] != "qagent-pytest":
            versiones[meta["name"]] = meta["version"]
    if not {"pywebview", "docker", "pyinstaller"} <= {n.lower() for n in versiones}:
        raise ValueError(
            "El informe no contiene las dependencias completas del instalador."
        )
    contenido = "# Windows x64 / CPython 3.13. Dependencias y transitivas fijadas.\n"
    contenido += "# Generado por scripts/actualizar_lock.py a partir de pip --report.\n"
    contenido += (
        "\n".join(
            f"{n}=={v}"
            for n, v in sorted(versiones.items(), key=lambda p: p[0].lower())
        )
        + "\n"
    )
    salida.write_text(contenido, encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("informe", type=Path)
    parser.add_argument(
        "--salida",
        type=Path,
        default=Path(__file__).resolve().parents[1]
        / "packaging/runtime-windows-py313.lock.txt",
    )
    argumentos = parser.parse_args()
    escribir_lock(argumentos.informe, argumentos.salida)
