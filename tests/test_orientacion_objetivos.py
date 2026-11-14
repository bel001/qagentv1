"""Orientación previa por reglas: criterios observables y ningún cliente de IA."""

from pathlib import Path
from unittest.mock import Mock

import pytest

from qagent.proyectos import vista_previa


@pytest.mark.parametrize(
    ("fuente", "categoria"),
    [
        ("def sumar(a,b): return a+b", "recomendada"),
        ("def get_total(x: int) -> int: return x*2", "recomendada"),
        ("def validar(x): return 0 < x <= 100", "recomendada"),
        ("def sumar(xs): return sum(xs)", "recomendada"),
        (
            "def fabrica() -> FileValidationService: return FileValidationService()",
            "revisar",
        ),
        ("def fabrica(): return FileValidationService()", "revisar"),
        ("def get_servicio(): return _servicio", "revisar"),
        ("def leer(ruta): return open(ruta).read()", "revisar"),
        ("import requests as red\ndef consulta(url): return red.get(url)", "revisar"),
        ("import time as reloj\ndef ahora(): return reloj.time()", "revisar"),
        ("import os\ndef config(): return os.environ['SECCION']", "revisar"),
        ("def transformar(x): return dependencia(x)", "revisar"),
        (
            "import reflex as rx\ndef vista() -> rx.Component: return rx.link('x')",
            "no_soportada",
        ),
    ],
)
def test_orientacion_explica_riesgos_sin_ejecutar_el_proyecto(
    tmp_path: Path, monkeypatch, fuente: str, categoria: str
) -> None:
    (tmp_path / "modulo.py").write_text(
        fuente + '\nraise RuntimeError("No ejecutar este módulo en el host")\n',
        encoding="utf-8",
    )
    crear = Mock(side_effect=AssertionError("La orientación no usa IA"))
    monkeypatch.setattr(vista_previa, "_recomendador_configurado", crear)
    vista = vista_previa.generar_vista_previa(tmp_path)
    funcion = vista["modulos"][0]["funciones"][0]
    orientacion = funcion["orientacion_prueba"]
    assert orientacion["categoria"] == categoria
    assert orientacion["motivo"]
    assert orientacion["origen"] == "reglas"
    assert orientacion["tokens"] == 0
    assert vista["orientacion_pruebas"]["tokens"] == 0
    crear.assert_not_called()
    if categoria == "revisar":
        assert not funcion.get("no_soportada")  # Es seleccionable, no se bloquea.


def test_explica_que_la_logica_puede_estar_en_metodos_no_seleccionables(tmp_path):
    (tmp_path / "file_validation.py").write_text(
        "class FileValidationService:\n"
        "    def validar(self, size): return size < 100\n"
        "    def _interno(self): return 0\n"
        "def get_file_validation_service() -> FileValidationService:\n"
        "    return FileValidationService()\n",
        encoding="utf-8",
    )
    vista = vista_previa.generar_vista_previa(tmp_path)
    [fabrica] = vista["modulos"][0]["funciones"]
    assert fabrica["orientacion_prueba"]["categoria"] == "revisar"
    [metodo] = vista["orientacion_pruebas"]["metodos_no_seleccionables"]
    assert metodo["modulo"] == "file_validation.py"
    assert metodo["clase"] == "FileValidationService"
    assert metodo["nombre"] == "validar"
    assert vista["orientacion_pruebas"]["resumen"] == {
        "recomendada": 0,
        "revisar": 1,
        "no_soportada": 0,
    }


def test_orientar_no_modifica_el_analisis_que_recibe_el_planner(tmp_path):
    from copy import deepcopy

    from qagent.lenguajes import PythonAdapter

    (tmp_path / "servicio.py").write_text(
        "def obtener() -> Servicio: return Servicio()", encoding="utf-8"
    )
    adaptador = PythonAdapter()
    [modulo] = adaptador.analizar(tmp_path)["modulos"]
    original = deepcopy(modulo)
    orientado = adaptador.orientar_modulo(tmp_path, modulo)
    assert modulo == original
    assert "aptitud_pruebas" not in modulo["funciones"][0]
    assert orientado["funciones"][0]["aptitud_pruebas"]["categoria"] == "revisar"
