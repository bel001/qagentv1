"""Dependencias de proyectos Python desde sus manifiestos (backlog 10, ADR-017).

Sin Docker ni red: se prueba qué lista de dependencias se arma y qué imagen tocaría.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from qagent.sandbox import imagen
from qagent.sandbox.manifiestos_python import (
    ManifiestoNoSoportado,
    avisos_de_manifiesto,
    dependencias_del_manifiesto,
)
from qagent.sandbox.modelos import ErrorConstruccionImagen


def _escribir(raiz: Path, nombre: str, texto: str) -> Path:
    """Con saltos LF también en Windows: la etiqueta de la imagen hashea los bytes."""
    (raiz / nombre).write_bytes(texto.encode("utf-8"))
    return raiz


# --- PEP 621 -----------------------------------------------------------------------


def test_pep621_lee_dependencias_con_extras_y_marcadores(tmp_path) -> None:
    _escribir(
        tmp_path,
        "pyproject.toml",
        '[project]\nname = "app"\ndependencies = [\n'
        '  "requests[socks]>=2.31",\n  "pydantic==2.*",\n'
        '  "tomli; python_version < \'3.11\'",\n  "requests[socks]>=2.31",\n]\n'
        '[project.optional-dependencies]\ntest = ["pytest"]\n',
    )

    encontradas = dependencias_del_manifiesto(tmp_path)

    assert encontradas.origen == "pyproject.toml ([project].dependencies)"
    assert encontradas.requisitos == (
        "requests[socks]>=2.31",
        "pydantic==2.*",
        'tomli; python_version < "3.11"',
    )
    # Los grupos opcionales no se instalan.
    assert "pytest" not in encontradas.como_requirements().decode()


def test_pep621_dinamico_lee_el_archivo_que_indica_setuptools(tmp_path) -> None:
    _escribir(tmp_path, "reqs.in", "httpx>=0.27  # cliente\n\n# comentario\nrich\n")
    _escribir(
        tmp_path,
        "pyproject.toml",
        '[project]\nname = "app"\ndynamic = ["dependencies"]\n'
        '[tool.setuptools.dynamic]\ndependencies = { file = ["reqs.in"] }\n',
    )

    encontradas = dependencias_del_manifiesto(tmp_path)

    assert encontradas.requisitos == ("httpx>=0.27", "rich")
    assert "reqs.in" in encontradas.origen


def test_pep621_dinamico_fuera_del_proyecto_se_rechaza(tmp_path) -> None:
    _escribir(
        tmp_path,
        "pyproject.toml",
        '[project]\nname = "app"\ndynamic = ["dependencies"]\n'
        '[tool.setuptools.dynamic]\ndependencies = { file = ["../otro.txt"] }\n',
    )
    with pytest.raises(ManifiestoNoSoportado, match="no está en el proyecto"):
        dependencias_del_manifiesto(tmp_path)


@pytest.mark.parametrize(
    "dependencia",
    [
        "milib @ file:///home/yo/milib",
        "milib @ git+https://github.com/yo/milib.git",
        "milib @ https://ejemplo.com/milib-1.0.tar.gz",
    ],
)
def test_una_dependencia_local_o_externa_se_rechaza_con_su_nombre(
    tmp_path, dependencia
) -> None:
    _escribir(
        tmp_path,
        "pyproject.toml",
        f'[project]\nname = "app"\ndependencies = ["{dependencia}"]\n',
    )
    with pytest.raises(ManifiestoNoSoportado, match="«milib»"):
        dependencias_del_manifiesto(tmp_path)


# --- Poetry ------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("version", "esperado"),
    [
        ('"^1.2.3"', "a<2.0.0,>=1.2.3"),
        ('"^0.2.3"', "a<0.3.0,>=0.2.3"),
        ('"^0.0.3"', "a<0.0.4,>=0.0.3"),
        ('"^1.2"', "a<2.0,>=1.2"),
        ('"~1.2.3"', "a<1.3.0,>=1.2.3"),
        ('"~1"', "a<2,>=1"),
        ('"1.4.0"', "a==1.4.0"),
        ('">=1,<3"', "a<3,>=1"),
        ('"*"', "a"),
        ('{ version = "^2", extras = ["x"] }', "a[x]<3,>=2"),
    ],
)
def test_poetry_traduce_las_versiones(tmp_path, version, esperado) -> None:
    _escribir(
        tmp_path,
        "pyproject.toml",
        f'[tool.poetry.dependencies]\npython = "^3.11"\na = {version}\n',
    )
    assert dependencias_del_manifiesto(tmp_path).requisitos == (esperado,)


def test_poetry_omite_python_y_las_opcionales(tmp_path) -> None:
    _escribir(
        tmp_path,
        "pyproject.toml",
        "[tool.poetry.dependencies]\n"
        'python = "^3.11"\n'
        'requests = "^2.31"\n'
        'redis = { version = "^5", optional = true }\n'
        "[tool.poetry.group.dev.dependencies]\n"
        'pytest = "^8"\n',
    )
    assert dependencias_del_manifiesto(tmp_path).requisitos == ("requests<3.0,>=2.31",)


@pytest.mark.parametrize(
    "valor",
    [
        '{ path = "../milib", develop = true }',
        '{ git = "https://github.com/yo/milib.git" }',
        '{ url = "https://ejemplo.com/milib.whl" }',
    ],
)
def test_poetry_rechaza_dependencias_locales_o_externas(tmp_path, valor) -> None:
    _escribir(
        tmp_path, "pyproject.toml", f"[tool.poetry.dependencies]\nmilib = {valor}\n"
    )
    with pytest.raises(ManifiestoNoSoportado, match="«milib»"):
        dependencias_del_manifiesto(tmp_path)


def test_poetry_con_varias_restricciones_no_se_adivina(tmp_path) -> None:
    _escribir(
        tmp_path,
        "pyproject.toml",
        "[tool.poetry.dependencies]\nnumpy = [\n"
        '  { version = "^1.26", python = "<3.12" },\n'
        '  { version = "^2.0", python = ">=3.12" },\n]\n',
    )
    with pytest.raises(ManifiestoNoSoportado, match="varias restricciones"):
        dependencias_del_manifiesto(tmp_path)


# --- setup.cfg y setup.py ----------------------------------------------------------


def test_setup_cfg_lee_install_requires(tmp_path) -> None:
    _escribir(
        tmp_path,
        "setup.cfg",
        "[metadata]\nname = app\n[options]\ninstall_requires =\n"
        "    click>=8\n    # comentario\n    attrs\n",
    )
    assert dependencias_del_manifiesto(tmp_path).requisitos == ("click>=8", "attrs")


def test_un_pyproject_sin_dependencias_cae_a_setup_cfg(tmp_path) -> None:
    _escribir(tmp_path, "pyproject.toml", "[tool.ruff]\nline-length = 100\n")
    _escribir(tmp_path, "setup.cfg", "[options]\ninstall_requires =\n    click\n")
    assert dependencias_del_manifiesto(tmp_path).requisitos == ("click",)


def test_setup_py_no_se_lee_y_se_avisa(tmp_path) -> None:
    _escribir(tmp_path, "setup.py", "from setuptools import setup\nsetup()\n")

    assert dependencias_del_manifiesto(tmp_path) is None
    [aviso] = avisos_de_manifiesto(tmp_path)
    assert "setup.py" in aviso and "leerlo es ejecutarlo" in aviso


def test_los_lockfiles_se_avisan(tmp_path) -> None:
    _escribir(tmp_path, "pyproject.toml", '[project]\nname = "a"\ndependencies = []\n')
    _escribir(tmp_path, "poetry.lock", "# lock\n")
    [aviso] = avisos_de_manifiesto(tmp_path)
    assert "poetry.lock no se usa" in aviso


# --- receta de la imagen ------------------------------------------------------------


def _receta():
    return imagen.receta_de(imagen.IMAGEN_BASE)


def test_requirements_tiene_prioridad_sobre_el_manifiesto(tmp_path) -> None:
    _escribir(tmp_path, "requirements.txt", "requests==2.31.0\n")
    _escribir(
        tmp_path, "pyproject.toml", '[project]\nname = "a"\ndependencies = ["x"]\n'
    )

    forma, archivos = imagen._buscar_dependencias(tmp_path, _receta())

    assert forma.nombre == "requirements.txt"
    assert archivos == {"requirements.txt": b"requests==2.31.0\n"}


def test_sin_requirements_se_usa_el_pyproject(tmp_path) -> None:
    _escribir(
        tmp_path, "pyproject.toml", '[project]\nname = "a"\ndependencies = ["rich"]\n'
    )

    forma, archivos = imagen._buscar_dependencias(tmp_path, _receta())

    assert forma.nombre == "pyproject.toml"
    assert archivos == {"requirements.txt": b"rich\n"}


def test_un_manifiesto_sin_dependencias_usa_la_imagen_base(tmp_path) -> None:
    _escribir(tmp_path, "pyproject.toml", '[project]\nname = "a"\ndependencies = []\n')
    assert imagen._buscar_dependencias(tmp_path, _receta()) is None


def test_mismas_dependencias_misma_imagen(tmp_path) -> None:
    """Un pyproject y un requirements con la misma lista comparten imagen."""
    con_req = tmp_path / "req"
    con_toml = tmp_path / "toml"
    con_req.mkdir()
    con_toml.mkdir()
    _escribir(con_req, "requirements.txt", "rich\n")
    _escribir(
        con_toml, "pyproject.toml", '[project]\nname = "a"\ndependencies = ["rich"]\n'
    )

    etiquetas = {
        imagen.etiqueta_para_dependencias(
            "req-", imagen._buscar_dependencias(raiz, _receta())[1]
        )
        for raiz in (con_req, con_toml)
    }

    assert len(etiquetas) == 1


def test_un_manifiesto_inseguro_detiene_la_receta_con_su_motivo(tmp_path) -> None:
    _escribir(
        tmp_path,
        "pyproject.toml",
        '[project]\nname = "a"\ndependencies = ["milib @ file:///x"]\n',
    )
    with pytest.raises(ErrorConstruccionImagen, match="«milib»"):
        imagen._buscar_dependencias(tmp_path, _receta())


def test_el_fallo_de_pip_nombra_el_manifiesto() -> None:
    explicar = imagen._explicar_fallo_pip_de("pyproject.toml")
    mensaje = explicar({}, "ERROR: No matching distribution found for nada")
    assert "pyproject.toml" in mensaje
    assert "requirements.txt" not in mensaje


# --- estructura src/ -----------------------------------------------------------------


def test_el_sandbox_python_importa_tambien_desde_src() -> None:
    from qagent.lenguajes import PythonAdapter

    variables = PythonAdapter().variables_pruebas()
    assert variables["PYTHONPATH"].split(":") == [
        "/work/proyecto",
        "/work/proyecto/src",
    ]
