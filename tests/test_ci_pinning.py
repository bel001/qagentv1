"""La CI, las imágenes base y el empaquetado quedan fijados por versión (B6, B7, B8).

- Toda acción de GitHub se referencia por SHA: una etiqueta puede cambiar de código.
- Las imágenes base fijas de Docker van por digest: la etiqueta puede cambiar de contenido.
- Las herramientas de empaquetado tienen un archivo de restricciones: sin él, el
  ejecutable de Windows puede dejar de construirse sin que nadie toque el código.
"""

from __future__ import annotations

import re
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
WORKFLOWS = RAIZ / ".github" / "workflows"
SANDBOX = RAIZ / "src" / "qagent" / "sandbox"

SHA = re.compile(r"^[0-9a-f]{40}$")
DIGEST = re.compile(r"@sha256:[0-9a-f]{64}$")


def _usos() -> list[str]:
    usos: list[str] = []
    for archivo in sorted(WORKFLOWS.glob("*.yml")):
        for linea in archivo.read_text(encoding="utf-8").splitlines():
            limpio = linea.strip().lstrip("-").strip()
            if limpio.startswith("uses:"):
                uso = limpio.removeprefix("uses:").split("#")[0].strip()
                usos.append(uso)
    return usos


def test_las_acciones_de_github_estan_fijadas_por_sha() -> None:
    usos = _usos()
    assert usos, "No se encontró ninguna acción en los workflows"
    for uso in usos:
        if uso.startswith("./"):
            continue  # acción local del repositorio
        accion, _, referencia = uso.partition("@")
        if accion.startswith("docker://"):
            assert DIGEST.match(referencia), f"{uso} debe fijarse por digest (B6)"
            continue
        assert "/" in accion, uso
        assert SHA.match(referencia), (
            f"{uso} debe fijarse por SHA, no por etiqueta (B6)"
        )


def test_las_imagenes_base_fijas_van_por_digest() -> None:
    for nombre in ("Dockerfile.java", "Dockerfile.node", "Dockerfile.navegador"):
        texto = (SANDBOX / nombre).read_text(encoding="utf-8")
        lineas = [linea for linea in texto.splitlines() if linea.startswith("FROM ")]
        assert lineas, nombre
        for linea in lineas:
            assert DIGEST.search(linea), (
                f"{nombre}: la imagen base debe fijarse por digest (B7): {linea}"
            )


def test_la_imagen_de_python_documenta_que_va_por_etiqueta() -> None:
    """La versión de Python se elige al construir (ADR-013), así que va por etiqueta."""
    texto = (SANDBOX / "Dockerfile").read_text(encoding="utf-8")
    assert "FROM python:${PYTHON_VERSION}-slim" in texto
    assert "digest" in texto, "el motivo de usar etiqueta debe quedar escrito"


def test_las_herramientas_de_empaquetado_estan_fijadas() -> None:
    restricciones = RAIZ / "packaging" / "constraints.txt"
    assert restricciones.is_file(), "Falta packaging/constraints.txt (B8)"
    texto = restricciones.read_text(encoding="utf-8")
    fijadas = {
        linea.split("==")[0].strip().lower()
        for linea in texto.splitlines()
        if "==" in linea and not linea.strip().startswith("#")
    }
    assert {"pyinstaller", "build", "twine"} <= fijadas
