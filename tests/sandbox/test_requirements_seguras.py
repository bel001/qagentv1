"""M3: el `requirements.txt` del proyecto no puede cambiar cómo instala QAgent.

Las dependencias se instalan con red (paso 1) y con una sola orden de `pip`, con
`--only-binary=:all:`. Si el archivo del proyecto cambia el índice o permite sdist
(un `setup.py` que se ejecuta al instalar), la construcción ejecutaría código
arbitrario, así que esas opciones se rechazan antes de construir nada.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest
from docker.errors import ImageNotFound

from qagent.sandbox import IMAGEN_BASE, preparar_imagen
from qagent.sandbox.modelos import ErrorConstruccionImagen


def _cliente() -> MagicMock:
    cliente = MagicMock()

    def obtener(etiqueta: str) -> MagicMock:
        if etiqueta != IMAGEN_BASE:
            raise ImageNotFound(etiqueta)
        return MagicMock()

    cliente.images.get.side_effect = obtener
    return cliente


def _proyecto(tmp_path: Path, requisitos: str) -> Path:
    (tmp_path / "requirements.txt").write_text(requisitos, encoding="utf-8")
    return tmp_path


@pytest.mark.parametrize(
    "opcion",
    [
        "--index-url https://ejemplo.interno/simple",
        "--extra-index-url https://ejemplo.interno/simple",
        "--trusted-host ejemplo.interno",
        "--find-links ./paquetes",
        "--no-binary :all:",
        "--pre",
    ],
)
def test_rechaza_las_opciones_de_pip_que_cambian_el_indice(tmp_path: Path, opcion: str):
    proyecto = _proyecto(tmp_path, f"requests==2.31.0\n{opcion}\n")
    cliente = _cliente()

    with pytest.raises(ErrorConstruccionImagen, match="opción de pip no permitida"):
        preparar_imagen(proyecto, cliente)

    cliente.images.build.assert_not_called()


def test_acepta_las_opciones_de_pip_que_no_rompen_la_seguridad(tmp_path: Path):
    """Los hashes y el modo.require-hashes siguen valiendo: no cambian el índice."""
    proyecto = _proyecto(
        tmp_path,
        "requests==2.31.0 \\\n    --hash=sha256:0000\n",
    )
    cliente = _cliente()

    etiqueta = preparar_imagen(proyecto, cliente)

    assert etiqueta.startswith("qagent-sandbox:req-")
    cliente.images.build.assert_called_once()
