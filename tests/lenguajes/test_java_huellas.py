"""Huellas Java para caché de mutación: solo análisis estático (#180)."""

from pathlib import Path

import pytest

from qagent.lenguajes import JavaAdapter
from qagent.orchestrator.regresion import huellas_de_objetivos

MODULO = "src/main/java/ejemplo/Banco.java"
FUENTE = """package ejemplo;
public class Banco {
    private static int factor = 2;
    /** Multiplica por el factor configurado. */
    public static int calcular(int valor) { return valor * factor; }
    private static int auxiliar() { return 1; }
}
"""


def test_huellas_disponibles_con_corrida_java_integrada(tmp_path: Path) -> None:
    """Las huellas y PIT conservan el adaptador completo integrado por #182."""
    archivo = tmp_path / MODULO
    archivo.parent.mkdir(parents=True)
    archivo.write_text(FUENTE, encoding="utf-8")
    adaptador = JavaAdapter()
    huellas = adaptador.huellas_de_archivo(FUENTE, MODULO)
    assert adaptador.completo is True
    assert adaptador.motor_mutacion == "PIT"
    assert set(huellas) == {"Banco.calcular"}
    assert len(huellas["Banco.calcular"]) == 64
    assert huellas_de_objetivos(tmp_path) == {
        (MODULO, "Banco.calcular"): huellas["Banco.calcular"]
    }
    assert adaptador.funciones_de_modulo(tmp_path, MODULO) == [
        {"nombre": "Banco.calcular", "linea": 5}
    ]


@pytest.mark.parametrize(
    ("anterior", "nuevo"),
    [
        ("valor * factor", "valor + factor"),
        ("factor = 2", "factor = 3"),
        ("return 1", "return 2"),
        ("Multiplica", "Calcula"),
    ],
)
def test_cambios_de_metodo_o_contexto_invalidan_huella(
    anterior: str, nuevo: str
) -> None:
    """Cambiar cuerpo, campo, auxiliar o documentación fuerza recalcular el score."""
    adaptador = JavaAdapter()
    original = adaptador.huellas_de_archivo(FUENTE, MODULO)
    assert original == adaptador.huellas_de_archivo(FUENTE, MODULO)
    assert original != adaptador.huellas_de_archivo(
        FUENTE.replace(anterior, nuevo), MODULO
    )


def test_fuentes_invalidas_no_se_reutilizan(tmp_path: Path) -> None:
    """Sintaxis inválida da None y ninguna ubicación de método."""
    fuente = "public class Rota {"
    archivo = tmp_path / "Banco.java"
    archivo.write_text(fuente, encoding="utf-8")
    adaptador = JavaAdapter()
    assert adaptador.huellas_de_archivo(fuente, "Banco.java") is None
    assert adaptador.funciones_de_modulo(tmp_path, "Banco.java") == []
    assert adaptador.funciones_de_modulo(tmp_path, "no-existe.java") == []


def test_cada_sobrecarga_tiene_su_huella_y_su_linea(tmp_path: Path) -> None:
    """Backlog 2: la regresión distingue las versiones de un método."""
    fuente = (
        "public class Banco {\n  public int x() { return 1; }\n"
        "  public int x(int a) { return a; }\n}\n"
    )
    (tmp_path / "Banco.java").write_text(fuente, encoding="utf-8")
    adaptador = JavaAdapter()
    huellas = adaptador.huellas_de_archivo(fuente, "Banco.java")
    assert list(huellas) == ["Banco.x()", "Banco.x(int)"]
    assert huellas["Banco.x()"] != huellas["Banco.x(int)"]
    assert adaptador.funciones_de_modulo(tmp_path, "Banco.java") == [
        {"nombre": "Banco.x()", "linea": 2},
        {"nombre": "Banco.x(int)", "linea": 3},
    ]


def test_ruta_externa_no_se_lee(tmp_path: Path) -> None:
    """La consulta de líneas rechaza una ruta que sale de la raíz del proyecto."""
    raiz = tmp_path / "proyecto"
    raiz.mkdir()
    (tmp_path / "Banco.java").write_text(FUENTE, encoding="utf-8")
    assert JavaAdapter().funciones_de_modulo(raiz, "../Banco.java") == []


def test_una_sobrecarga_no_cambia_la_huella_de_los_demas_metodos() -> None:
    """`Banco.y` conserva su identidad de siempre: su resultado guardado se reutiliza."""
    fuente = (
        "public class Banco { public int x() { return 1; } "
        "public int x(int a) { return a; } public int y() { return 2; } }"
    )
    assert list(JavaAdapter().huellas_de_archivo(fuente, "Banco.java")) == [
        "Banco.x()",
        "Banco.x(int)",
        "Banco.y",
    ]
