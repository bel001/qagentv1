"""«Tus proyectos»: la app muestra los proyectos que ya están en tu equipo.

La lista de «Proyectos recientes» solo conoce lo que QAgent registró. Si el proyecto
ya estaba en el disco (clonado antes con git, copiado, o de otra máquina), no
aparecía y no había forma de abrirlo sin buscar la carpeta a mano. Con esta función
la app escanea una carpeta (por defecto, la de proyectos donde clona) y devuelve los
proyectos que puede analizar.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from qagent.app.desktop import DesktopAPI


def _proyecto_python(carpeta: Path, nombre: str = "mi-proyecto") -> Path:
    """Crea una carpeta con un archivo Python (proyecto analizable)."""
    proyecto = carpeta / nombre
    proyecto.mkdir(parents=True)
    (proyecto / "main.py").write_text(
        'def duplicar(x: int) -> int:\n    """Duplica."""\n    return x * 2\n',
        encoding="utf-8",
    )
    return proyecto


def test_lista_los_proyectos_que_ya_estan_en_la_carpeta(tmp_path: Path) -> None:
    _proyecto_python(tmp_path, "uno")
    _proyecto_python(tmp_path, "dos")

    respuesta = DesktopAPI().listar_proyectos_de_carpeta(str(tmp_path))

    assert respuesta["ok"] is True
    assert respuesta["existe"] is True
    assert [p["nombre"] for p in respuesta["proyectos"]] == ["dos", "uno"]
    uno = respuesta["proyectos"][1]
    assert uno["lenguaje"] == "python"
    assert uno["cantidad_fuentes"] == 1
    assert uno["ruta"].endswith("uno")


def test_ignora_lo_que_no_es_un_proyecto(tmp_path: Path) -> None:
    _proyecto_python(tmp_path, "proyecto-real")
    (tmp_path / "no-proyecto").mkdir()
    (tmp_path / "no-proyecto" / "leeme.txt").write_text("hola", encoding="utf-8")
    (tmp_path / ".oculto").mkdir()
    (tmp_path / ".oculto" / "main.py").write_text("x = 1\n", encoding="utf-8")

    respuesta = DesktopAPI().listar_proyectos_de_carpeta(str(tmp_path))

    assert [p["nombre"] for p in respuesta["proyectos"]] == ["proyecto-real"]


def test_una_carpeta_que_no_existe_no_falla(tmp_path: Path) -> None:
    respuesta = DesktopAPI().listar_proyectos_de_carpeta(str(tmp_path / "no-existe"))

    assert respuesta["ok"] is True
    assert respuesta["existe"] is False
    assert respuesta["proyectos"] == []


def test_por_defecto_usa_la_carpeta_de_proyectos(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from qagent.proyectos import clonador

    monkeypatch.setattr(
        clonador, "carpeta_proyectos_por_defecto", lambda: tmp_path / "Proyectos"
    )
    _proyecto_python(tmp_path / "Proyectos", "guardado")

    respuesta = DesktopAPI().listar_proyectos_de_carpeta()

    assert respuesta["carpeta"].endswith("Proyectos")
    assert [p["nombre"] for p in respuesta["proyectos"]] == ["guardado"]


def test_la_interfaz_muestra_y_abre_los_proyectos_de_la_carpeta() -> None:
    """La pantalla de inicio tiene su bloque y su botón para abrirlos."""
    from pathlib import Path

    raiz = Path(__file__).resolve().parents[2]
    inicio = (
        raiz / "src" / "qagent" / "frontend" / "componentes" / "inicio" / "inicio.js"
    ).read_text(encoding="utf-8")

    assert "Tus proyectos" in inicio
    assert "listar_proyectos_de_carpeta" in inicio
    assert "abrirProyectoDeCarpeta" in inicio
    assert "buscarProyectosEnCarpeta" in inicio
