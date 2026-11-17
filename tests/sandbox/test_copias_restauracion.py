"""La copia del proyecto se restaura entre pruebas sin releer lo que no cambió."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from qagent.sandbox import copias
from qagent.sandbox.copias import SesionProyecto


@pytest.fixture
def sesion(tmp_path: Path):
    proyecto = tmp_path / "proyecto"
    (proyecto / "pkg").mkdir(parents=True)
    (proyecto / "calc.py").write_text("original", encoding="utf-8")
    (proyecto / "pkg" / "util.py").write_text("util", encoding="utf-8")
    (proyecto / "pkg" / "datos.txt").write_text("datos", encoding="utf-8")
    sesion = SesionProyecto(proyecto)
    yield sesion
    sesion.cerrar()


def test_solo_se_vuelve_a_copiar_lo_que_la_prueba_modifico(sesion, monkeypatch) -> None:
    with sesion.prestar() as copia:
        (copia / "calc.py").write_text("alterado", encoding="utf-8")
    copiados: list[str] = []
    original = shutil.copy2

    def copiar(origen, destino, **opciones):
        copiados.append(Path(destino).name)
        return original(origen, destino, **opciones)

    monkeypatch.setattr(copias.shutil, "copy2", copiar)

    with sesion.prestar() as copia:
        assert (copia / "calc.py").read_text(encoding="utf-8") == "original"

    assert copiados == ["calc.py"]


def test_sin_cambios_no_se_copia_ni_se_lee_ningun_archivo(sesion, monkeypatch) -> None:
    with sesion.prestar():
        pass
    monkeypatch.setattr(
        copias.shutil, "copy2", lambda *a, **k: pytest.fail("no debía copiar")
    )
    monkeypatch.setattr(
        Path, "open", lambda *a, **k: pytest.fail("no debía leer el contenido")
    )

    with sesion.prestar() as copia:
        assert sorted(p.name for p in copia.rglob("*.py")) == ["calc.py", "util.py"]


def test_se_restauran_borrados_carpetas_y_archivos_sobrantes(sesion) -> None:
    with sesion.prestar() as copia:
        (copia / "pkg" / "util.py").unlink()
        shutil.rmtree(copia / "pkg")
        (copia / "pkg").write_text("ahora es un archivo", encoding="utf-8")
        (copia / "nueva").mkdir()
        (copia / "nueva" / "basura.txt").write_text("x", encoding="utf-8")

    with sesion.prestar() as copia:
        assert (copia / "pkg" / "util.py").read_text(encoding="utf-8") == "util"
        assert (copia / "pkg" / "datos.txt").read_text(encoding="utf-8") == "datos"
        assert not (copia / "nueva").exists()


def test_un_archivo_restaurado_no_se_copia_otra_vez_en_el_prestamo_siguiente(
    sesion, monkeypatch
) -> None:
    with sesion.prestar() as copia:
        (copia / "calc.py").write_text("alterado", encoding="utf-8")
    with sesion.prestar():
        pass
    monkeypatch.setattr(
        copias.shutil, "copy2", lambda *a, **k: pytest.fail("no debía copiar")
    )

    with sesion.prestar() as copia:
        assert (copia / "calc.py").read_text(encoding="utf-8") == "original"
