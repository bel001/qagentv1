"""Compatibilidad antes de iniciar una corrida (backlog 17).

Sin Docker, sin red y sin IA: Docker se simula en `estado_preparacion`.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from qagent.lenguajes import JavaAdapter, PythonAdapter
from qagent.proyectos import compatibilidad
from qagent.proyectos.compatibilidad import (
    COMPATIBLE,
    MOTIVO_INFERIDO,
    NO_SOPORTADO,
    REQUIERE_CONFIGURACION,
    compatibilidad_endpoint,
    estado_preparacion,
    evaluar,
)
from qagent.proyectos.vista_previa import generar_vista_previa

PYTHON = (
    "def documentada(a: int) -> int:\n"
    '    """Devuelve el doble. documentada(2) == 4."""\n'
    "    return a * 2\n\n\n"
    "def sin_doc_uno(a: int) -> int:\n    return a + 1\n\n\n"
    "def sin_doc_dos(a: int) -> int:\n    return a + 2\n"
)


def _python(tmp_path: Path, codigo: str = PYTHON) -> Path:
    (tmp_path / "calc.py").write_text(codigo, encoding="utf-8")
    return tmp_path


def _evaluar(raiz: Path, adaptador, **opciones):
    analisis = adaptador.analizar(raiz)
    resultado = evaluar(
        raiz,
        adaptador,
        analisis["modulos"],
        analisis["errores"],
        inferencia_activa=opciones.get("inferencia_activa", True),
        limite_inferencia=opciones.get("limite_inferencia"),
    )
    funciones = {
        f["nombre"]: f["compatibilidad"]
        for m in analisis["modulos"]
        for f in m.get("funciones", [])
    }
    return resultado, funciones


# --- objetivos Python ----------------------------------------------------------------


def test_documentada_e_inferida_son_compatibles(tmp_path) -> None:
    resultado, funciones = _evaluar(_python(tmp_path), PythonAdapter())

    assert funciones["documentada"]["estado"] == COMPATIBLE
    assert funciones["sin_doc_uno"] == {"estado": COMPATIBLE, "motivo": MOTIVO_INFERIDO}
    assert resultado["estado"] == COMPATIBLE
    assert resultado["objetivos"] == {
        COMPATIBLE: 3,
        REQUIERE_CONFIGURACION: 0,
        NO_SOPORTADO: 0,
    }
    assert resultado["tokens"] == 0


def test_sin_docstring_y_sin_inferencia_requiere_configuracion(tmp_path) -> None:
    resultado, funciones = _evaluar(
        _python(tmp_path), PythonAdapter(), inferencia_activa=False
    )

    assert funciones["documentada"]["estado"] == COMPATIBLE
    assert funciones["sin_doc_uno"]["estado"] == REQUIERE_CONFIGURACION
    assert (
        "activa «Inferir funciones sin docstring»" in funciones["sin_doc_uno"]["motivo"]
    )
    assert resultado["objetivos"][REQUIERE_CONFIGURACION] == 2


def test_el_limite_de_inferencia_por_modulo_se_respeta(tmp_path) -> None:
    _, funciones = _evaluar(_python(tmp_path), PythonAdapter(), limite_inferencia=1)

    assert funciones["sin_doc_uno"]["estado"] == COMPATIBLE
    assert funciones["sin_doc_dos"]["estado"] == REQUIERE_CONFIGURACION
    assert "máximo de 1 funciones" in funciones["sin_doc_dos"]["motivo"]


def test_un_archivo_que_no_se_puede_analizar_es_no_soportado(tmp_path) -> None:
    _python(tmp_path)
    (tmp_path / "roto.py").write_text("def f(:\n", encoding="utf-8")

    resultado, _ = _evaluar(tmp_path, PythonAdapter())

    assert resultado["modulos"]["roto.py"]["estado"] == NO_SOPORTADO
    assert "No se pudo analizar" in resultado["modulos"]["roto.py"]["motivo"]
    assert resultado["modulos"]["calc.py"]["estado"] == COMPATIBLE


# --- requisitos del proyecto ---------------------------------------------------------


def test_un_requirements_inseguro_requiere_configuracion(tmp_path) -> None:
    _python(tmp_path)
    (tmp_path / "requirements.txt").write_text(
        "requests==2.31.0\n--index-url https://otro.example/simple\n", encoding="utf-8"
    )

    resultado, _ = _evaluar(tmp_path, PythonAdapter())

    assert resultado["estado"] == REQUIERE_CONFIGURACION
    [requisito] = resultado["requisitos"]
    assert requisito["estado"] == REQUIERE_CONFIGURACION
    assert "línea 2" in requisito["motivo"]


def test_una_version_de_python_fuera_del_rango_no_es_soportada(tmp_path) -> None:
    _python(tmp_path)
    (tmp_path / ".python-version").write_text("3.8\n", encoding="utf-8")

    resultado, _ = _evaluar(tmp_path, PythonAdapter())

    assert resultado["estado"] == NO_SOPORTADO
    assert any(r["estado"] == NO_SOPORTADO for r in resultado["requisitos"])


# --- Java --------------------------------------------------------------------------


JAVA = """
public class Util {
  /** Suma. @return la suma */
  public static int sumar(int a, int b) { return a + b; }
  public static int sinDoc(int a) { return a; }
  /** Varargs. @return el total */
  public static int total(int... xs) { return 0; }
  /** Uno. @return a */
  public static int largo(String a) { return a.length(); }
  /** Dos. @return a */
  public static int largo(String a, int b) { return b; }
}
"""


def test_java_cada_objetivo_tiene_su_estado(tmp_path) -> None:
    (tmp_path / "Util.java").write_text(JAVA, encoding="utf-8")

    resultado, funciones = _evaluar(tmp_path, JavaAdapter())

    assert funciones["Util.sumar"]["estado"] == COMPATIBLE
    assert funciones["Util.sinDoc"]["estado"] == REQUIERE_CONFIGURACION
    assert "Javadoc" in funciones["Util.sinDoc"]["motivo"]
    assert funciones["Util.total"]["estado"] == NO_SOPORTADO
    assert "varargs" in funciones["Util.total"]["motivo"]
    # Backlog 2: cada sobrecarga es un objetivo propio y compatible.
    assert funciones["Util.largo(String)"]["estado"] == COMPATIBLE
    assert funciones["Util.largo(String,int)"]["estado"] == COMPATIBLE
    assert resultado["modulos"]["Util.java"]["fuera"] == []
    assert resultado["objetivos"] == {
        COMPATIBLE: 3,
        REQUIERE_CONFIGURACION: 1,
        NO_SOPORTADO: 1,
    }


def test_java_varargs_no_se_ofrece_en_la_vista_previa(tmp_path) -> None:
    (tmp_path / "Util.java").write_text(JAVA, encoding="utf-8")

    vista = generar_vista_previa(tmp_path)

    funciones = {f["nombre"]: f for m in vista["modulos"] for f in m["funciones"]}
    assert "varargs" in funciones["Util.total"]["no_soportada"]
    assert funciones["Util.sumar"]["no_soportada"] is None
    assert vista["compatibilidad"]["objetivos"][NO_SOPORTADO] == 1


# --- endpoints ---------------------------------------------------------------------


def test_un_endpoint_sin_ruta_resuelta_no_es_soportado() -> None:
    estado = compatibilidad_endpoint(
        {"manejador": "f", "resuelta": False}, PythonAdapter()
    )
    assert estado["estado"] == NO_SOPORTADO


def test_un_endpoint_declarado_es_compatible() -> None:
    estado = compatibilidad_endpoint(
        {"objetivo": "GET /salud", "manejador": "salud"}, PythonAdapter()
    )
    assert estado["estado"] == COMPATIBLE


# --- preparación del entorno ---------------------------------------------------------


@pytest.fixture
def docker_simulado(monkeypatch):
    """Docker responde y la imagen está o no está construida, según cada prueba."""
    from qagent.sandbox import cliente, estado, imagen

    situacion = {"docker": "ok", "pendiente": False}
    monkeypatch.setattr(
        estado,
        "estado_docker",
        lambda: {"estado": situacion["docker"], "mensaje": "Docker no responde"},
    )
    monkeypatch.setattr(cliente, "obtener_cliente", lambda: object())
    monkeypatch.setattr(
        imagen, "construccion_pendiente", lambda *_a, **_k: situacion["pendiente"]
    )
    return situacion


def test_preparacion_validada_si_la_imagen_ya_existe(tmp_path, docker_simulado) -> None:
    resultado = estado_preparacion(_python(tmp_path))
    assert resultado["estado"] == compatibilidad.PREPARACION_VALIDADA
    assert "se reutilizará" in resultado["mensaje"]


def test_preparacion_pendiente_si_falta_construirla(tmp_path, docker_simulado) -> None:
    docker_simulado["pendiente"] = True
    resultado = estado_preparacion(_python(tmp_path))
    assert resultado["estado"] == compatibilidad.PREPARACION_PENDIENTE
    assert "no se sabe si todas las dependencias se instalan" in resultado["mensaje"]


@pytest.mark.parametrize("docker", ["no_iniciado", "no_instalado"])
def test_preparacion_sin_docker(tmp_path, docker_simulado, docker) -> None:
    docker_simulado["docker"] = docker
    resultado = estado_preparacion(_python(tmp_path))
    assert resultado == {
        "estado": compatibilidad.PREPARACION_NO_DISPONIBLE,
        "mensaje": "Docker no responde",
    }


def test_preparacion_bloqueada_con_una_version_no_soportada(
    tmp_path, docker_simulado
) -> None:
    _python(tmp_path)
    (tmp_path / ".python-version").write_text("3.8\n", encoding="utf-8")
    assert (
        estado_preparacion(tmp_path)["estado"] == compatibilidad.PREPARACION_BLOQUEADA
    )


def test_preparacion_bloqueada_si_la_carpeta_no_existe(
    tmp_path, docker_simulado
) -> None:
    resultado = estado_preparacion(tmp_path / "no-existe")
    assert resultado["estado"] == compatibilidad.PREPARACION_BLOQUEADA


def test_preparacion_que_falla_al_consultar_es_desconocida(
    tmp_path, docker_simulado, monkeypatch
) -> None:
    from qagent.sandbox import imagen

    def fallar(*_a, **_k):
        raise RuntimeError("socket cerrado")

    monkeypatch.setattr(imagen, "construccion_pendiente", fallar)
    resultado = estado_preparacion(_python(tmp_path))
    assert resultado["estado"] == compatibilidad.PREPARACION_DESCONOCIDA
    assert "socket cerrado" in resultado["mensaje"]


# --- manifiestos (backlog 10) ------------------------------------------------------


def test_una_dependencia_local_en_pyproject_requiere_configuracion(tmp_path) -> None:
    _python(tmp_path)
    (tmp_path / "pyproject.toml").write_text(
        '[tool.poetry.dependencies]\nmilib = { path = "../milib" }\n', encoding="utf-8"
    )

    resultado, _ = _evaluar(tmp_path, PythonAdapter())

    assert resultado["estado"] == REQUIERE_CONFIGURACION
    assert any("«milib»" in r["motivo"] for r in resultado["requisitos"])


def test_solo_setup_py_requiere_configuracion(tmp_path) -> None:
    _python(tmp_path)
    (tmp_path / "setup.py").write_text(
        "from setuptools import setup\n", encoding="utf-8"
    )

    resultado, _ = _evaluar(tmp_path, PythonAdapter())

    assert resultado["estado"] == REQUIERE_CONFIGURACION


def test_un_lockfile_es_un_aviso_que_no_cambia_el_estado(tmp_path) -> None:
    _python(tmp_path)
    (tmp_path / "uv.lock").write_text("# lock\n", encoding="utf-8")

    resultado, _ = _evaluar(tmp_path, PythonAdapter())

    assert resultado["estado"] == COMPATIBLE
    assert [r["estado"] for r in resultado["requisitos"]] == [compatibilidad.AVISO]


def test_un_init_vacio_no_cuenta_como_no_soportado(tmp_path) -> None:
    """Un `__init__.py` sin nada que probar no es «no soportado» (revisión visual)."""
    _python(tmp_path)
    (tmp_path / "__init__.py").write_text("", encoding="utf-8")

    resultado, _ = _evaluar(tmp_path, PythonAdapter())

    assert resultado["modulos"]["__init__.py"]["estado"] == compatibilidad.SIN_OBJETIVOS
    assert resultado["objetivos"][NO_SOPORTADO] == 0
    assert resultado["estado"] == COMPATIBLE
