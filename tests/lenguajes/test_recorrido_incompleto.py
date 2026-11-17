"""Un proyecto con más archivos que el tope no se presenta como explorado entero."""

from __future__ import annotations

from pathlib import Path

import pytest

from qagent.lenguajes import registro
from qagent.lenguajes.registro import aviso_recorrido_incompleto, listar_archivos
from qagent.proyectos.vista_previa import generar_vista_previa


@pytest.fixture
def proyecto(tmp_path: Path) -> Path:
    for carpeta in ("zeta", "alfa", "medio"):
        (tmp_path / carpeta).mkdir()
        for nombre in ("c.py", "a.py", "b.py"):
            (tmp_path / carpeta / nombre).write_text(
                'def f() -> None:\n    """Nada."""\n', encoding="utf-8"
            )
    return tmp_path


def test_un_proyecto_dentro_del_tope_no_esta_truncado(proyecto) -> None:
    archivos = listar_archivos(proyecto)

    assert len(archivos) == 9
    assert archivos.truncada is False
    assert aviso_recorrido_incompleto(proyecto) is None
    assert generar_vista_previa(proyecto)["recorrido_incompleto"] is None


def test_al_superar_el_tope_se_marca_y_se_avisa(proyecto, monkeypatch) -> None:
    monkeypatch.setattr(registro, "MAX_ARCHIVOS_DETECCION", 4)

    archivos = listar_archivos(proyecto)

    assert archivos.truncada is True
    assert len(archivos) == 4
    aviso = aviso_recorrido_incompleto(proyecto)
    assert aviso is not None
    assert "más de 4 archivos" in aviso
    assert "parcial" in aviso
    assert generar_vista_previa(proyecto)["recorrido_incompleto"] == aviso


def test_el_corte_es_determinista_y_alfabetico(proyecto, monkeypatch) -> None:
    monkeypatch.setattr(registro, "MAX_ARCHIVOS_DETECCION", 4)

    assert listar_archivos(proyecto) == [
        "alfa/a.py",
        "alfa/b.py",
        "alfa/c.py",
        "medio/a.py",
    ]


def test_justo_en_el_tope_no_se_considera_truncado(proyecto, monkeypatch) -> None:
    monkeypatch.setattr(registro, "MAX_ARCHIVOS_DETECCION", 9)

    assert listar_archivos(proyecto).truncada is False


def test_el_aviso_escribe_el_tope_real_con_separador_de_miles(
    proyecto, monkeypatch
) -> None:
    monkeypatch.setattr(registro, "MAX_ARCHIVOS_DETECCION", 5000)
    monkeypatch.setattr(
        registro,
        "listar_archivos",
        lambda _raiz: _truncada(),
    )

    assert "más de 5.000 archivos" in aviso_recorrido_incompleto(proyecto)


def _truncada() -> registro.ListaArchivos:
    lista = registro.ListaArchivos()
    lista.truncada = True
    return lista
