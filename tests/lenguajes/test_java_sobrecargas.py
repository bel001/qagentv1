"""Identidad de las sobrecargas Java en todo el recorrido (backlog 2).

Cada sobrecarga se identifica como `Clase.metodo(T1,T2)` en la selección, el
contrato, el validador, la cobertura, la ubicación del método y la regresión. Un
método sin sobrecargas conserva `Clase.metodo`, así los datos guardados valen.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from qagent import contracts
from qagent.agents.planner import PlannerAgent
from qagent.contracts import ContratoInvalido
from qagent.lenguajes import JavaAdapter
from qagent.lenguajes.java_cobertura import cobertura_de_metodo
from qagent.lenguajes.java_identidad import (
    base_de,
    es_sobrecarga,
    identidad,
    metodo_de,
    separar,
    tipo_simple,
    tipos_de_descriptor,
)
from qagent.lenguajes.java_oraculo import validar_java
from qagent.llm import TokenTracker
from qagent.llm.fake import FakeLLMClient
from qagent.sandbox.pit_comando import comando_pit

FUENTE = """public class Calc {
  /** Devuelve a + 1. @return a + 1 */
  public static int sumar(int a) { return a + 1; }
  /** Devuelve a + 2. @return a + 2 */
  public static long sumar(long a) { return a + 2; }
  /** Devuelve a + b. @return a + b */
  public static int sumar(int a, int b) { return a + b; }
  /** Devuelve x. @return x */
  public static int otro(int x) { return x; }
}
"""


# --- identidad ---------------------------------------------------------------------


@pytest.mark.parametrize(
    ("tipo", "simple"),
    [
        ("int", "int"),
        ("final String", "String"),
        ("java.util.List<String>", "List"),
        ("Map<String, List<Integer>>", "Map"),
        ("int[]", "int[]"),
        ("String...", "String[]"),
        ("char[]...", "char[][]"),
        ("@NonNull String", "String"),
        ("java.util.Map.Entry<K, V>", "Entry"),
    ],
)
def test_tipo_simple(tipo, simple) -> None:
    assert tipo_simple(tipo) == simple


def test_identidad_y_su_lectura() -> None:
    objetivo = identidad("a.B.f", [{"tipo": "String"}, {"tipo": "int[]"}])
    assert objetivo == "a.B.f(String,int[])"
    assert separar(objetivo) == ("a.B.f", ["String", "int[]"])
    assert base_de(objetivo) == "a.B.f"
    assert metodo_de(objetivo) == "f"
    assert es_sobrecarga(objetivo)
    assert separar("a.B.f") == ("a.B.f", None)
    assert not es_sobrecarga("a.B.f")
    assert separar(identidad("B.f", [])) == ("B.f", [])


@pytest.mark.parametrize(
    ("descriptor", "tipos"),
    [
        ("(Ljava/lang/String;I)I", ["String", "int"]),
        ("([I[[Ljava/lang/String;)V", ["int[]", "String[][]"]),
        ("(JDFZCBS)V", ["long", "double", "float", "boolean", "char", "byte", "short"]),
        ("(Lpaquete/Externa$Interna;)V", ["Interna"]),
        ("()V", []),
        ("no es un descriptor", None),
    ],
)
def test_tipos_de_descriptor(descriptor, tipos) -> None:
    assert tipos_de_descriptor(descriptor) == tipos


# --- contrato ----------------------------------------------------------------------


def _contrato(objetivo: str, firma: str, entrada: dict, esperado) -> dict:
    return {
        "version": "3",
        "lenguaje": "java",
        "framework_pruebas": "junit5",
        "modulo": "Calc.java",
        "huella": "a" * 64,
        "tipo": "funcion",
        "objetivo": objetivo,
        "firma": firma,
        "critical": False,
        "llama_a": [],
        "casos": [
            {
                "id": "normal",
                "entrada": entrada,
                "valor_esperado": esperado,
                "origen": "docstring",
            }
        ],
    }


@pytest.mark.parametrize(
    "objetivo", ["Calc.sumar", "Calc.sumar(int)", "Calc.sumar(int,long[])", "Calc.f()"]
)
def test_el_contrato_admite_la_identidad_con_firma(objetivo) -> None:
    contracts.validar(
        contracts.PLANNER_V3,
        _contrato(objetivo, "public static int sumar(int a)", {"a": 1}, 2),
    )


@pytest.mark.parametrize(
    "objetivo", ["Calc.sumar(int", "Calc.sumar(int, long)", "Calc.sumar(List<String>)"]
)
def test_el_contrato_rechaza_una_identidad_mal_formada(objetivo) -> None:
    with pytest.raises(ContratoInvalido):
        contracts.validar(
            contracts.PLANNER_V3,
            _contrato(objetivo, "public static int sumar(int a)", {"a": 1}, 2),
        )


# --- Planner: cada sobrecarga con su contrato --------------------------------------


def test_el_planner_produce_un_contrato_por_sobrecarga(tmp_path: Path) -> None:
    (tmp_path / "Calc.java").write_text(FUENTE, encoding="utf-8")
    [modulo] = JavaAdapter().analizar(tmp_path)["modulos"]
    caso = {"id": "normal", "valor_esperado": 2, "origen": "docstring"}
    grabaciones = {
        "Calc.java::Calc.sumar(int)": [{**caso, "entrada": {"a": 1}}],
        "Calc.java::Calc.sumar(long)": [{**caso, "entrada": {"a": 0}}],
        "Calc.java::Calc.sumar(int,int)": [{**caso, "entrada": {"a": 1, "b": 1}}],
    }
    planner = PlannerAgent(
        FakeLLMClient(grabaciones=grabaciones),
        TokenTracker(),
        es_simulado=True,
        adaptador=JavaAdapter(),
    )

    plan = planner.planificar(
        {
            **modulo,
            "funciones": [
                f for f in modulo["funciones"] if f["nombre"].startswith("Calc.sumar")
            ],
        }
    )

    assert {c["objetivo"]: c["firma"] for c in plan} == {
        "Calc.sumar(int)": "public static int sumar(int a)",
        "Calc.sumar(long)": "public static long sumar(long a)",
        "Calc.sumar(int,int)": "public static int sumar(int a, int b)",
    }


# --- validador y Generator ---------------------------------------------------------


def _prueba(cuerpo: str) -> str:
    return (
        "import static org.junit.jupiter.api.Assertions.*;\n"
        "import org.junit.jupiter.api.Test;\n"
        "class CalcTest {\n  @Test void test_normal() {\n" + cuerpo + "\n  }\n}\n"
    )


def test_la_sobrecarga_long_exige_el_literal_long() -> None:
    """Con `sumar(int)` y `sumar(long)`, `sumar(1)` llamaría a la versión int."""
    contrato = _contrato(
        "Calc.sumar(long)", "public static long sumar(long a)", {"a": 1}, 3
    )

    problema = validar_java(contrato, _prueba("    assertEquals(3L, Calc.sumar(1));"))
    assert problema is not None
    assert "sumar está sobrecargado" in problema
    assert "con sufijo L (1L)" in problema
    assert "versión con long" in problema

    assert (
        validar_java(contrato, _prueba("    assertEquals(3L, Calc.sumar(1L));")) is None
    )


def test_la_sobrecarga_int_rechaza_el_literal_long() -> None:
    contrato = _contrato(
        "Calc.sumar(int)", "public static int sumar(int a)", {"a": 1}, 2
    )
    assert validar_java(contrato, _prueba("    assertEquals(2, Calc.sumar(1L));"))
    assert (
        validar_java(contrato, _prueba("    assertEquals(2, Calc.sumar(1));")) is None
    )


def test_un_metodo_sin_sobrecarga_no_exige_literales_exactos() -> None:
    """Sin sobrecargas no hay ambigüedad: el comportamiento anterior se mantiene."""
    contrato = _contrato("Calc.otro", "public static long otro(long x)", {"x": 1}, 1)
    assert (
        validar_java(contrato, _prueba("    assertEquals(1L, Calc.otro(1));")) is None
    )


def test_el_generator_recibe_la_clase_y_el_aviso_de_sobrecarga(tmp_path: Path) -> None:
    (tmp_path / "Calc.java").write_text(FUENTE, encoding="utf-8")
    adaptador = JavaAdapter()
    contrato = _contrato(
        "Calc.sumar(long)", "public static long sumar(long a)", {"a": 1}, 3
    )

    prompt = adaptador.prompt_generator(contrato, 1, None, tmp_path)

    assert '"metodo": "sumar"' in prompt
    assert '"sobrecargado": true' in prompt
    assert "1L para long" in prompt
    assert adaptador.archivo_para_contrato(contrato, tmp_path) == (
        "src/test/java/CalcTest.java"
    )


def test_el_generator_rechaza_una_sobrecarga_que_ya_no_existe(tmp_path: Path) -> None:
    (tmp_path / "Calc.java").write_text(FUENTE, encoding="utf-8")
    contrato = _contrato(
        "Calc.sumar(double)", "public static double sumar(double a)", {"a": 1.0}, 2.0
    )
    with pytest.raises(ValueError, match="no existe"):
        JavaAdapter().archivo_para_contrato(contrato, tmp_path)


# --- ubicación del método, cobertura y regresión ------------------------------------


def test_el_rango_de_cada_sobrecarga_es_el_suyo(tmp_path: Path) -> None:
    (tmp_path / "Calc.java").write_text(FUENTE, encoding="utf-8")
    reglas = JavaAdapter().reglas_revision()

    assert reglas.rango_de_objetivo(tmp_path, "Calc.java", "Calc.sumar(int)") == (3, 3)
    assert reglas.rango_de_objetivo(tmp_path, "Calc.java", "Calc.sumar(long)") == (5, 5)
    assert reglas.rango_de_objetivo(tmp_path, "Calc.java", "Calc.sumar(int,int)") == (
        7,
        7,
    )
    # Sin firma y con varias versiones no se elige al azar.
    assert reglas.rango_de_objetivo(tmp_path, "Calc.java", "Calc.sumar") is None
    assert reglas.rango_de_objetivo(tmp_path, "Calc.java", "Calc.otro") == (9, 9)


def _cobertura(funciones: dict) -> dict:
    return {"files": {"Calc.java": {"functions": funciones}}}


def _metodo(lineas: float) -> dict:
    return {"summary": {"percent_covered": lineas, "percent_branches_covered": None}}


def test_la_cobertura_de_cada_sobrecarga_sale_de_su_descriptor() -> None:
    cobertura = _cobertura(
        {
            "Calc.sumar(I)I": _metodo(100.0),
            "Calc.sumar(J)J": _metodo(50.0),
            "Calc.sumar(II)I": _metodo(25.0),
            "Calc.otro": _metodo(80.0),
        }
    )

    assert cobertura_de_metodo(cobertura, "Calc.java", "Calc.sumar(long)") == {
        "lineas": 50.0,
        "ramas": None,
    }
    assert (
        cobertura_de_metodo(cobertura, "Calc.java", "Calc.sumar(int,int)")["lineas"]
        == 25.0
    )
    assert cobertura_de_metodo(cobertura, "Calc.java", "Calc.otro")["lineas"] == 80.0
    assert cobertura_de_metodo(cobertura, "Calc.java", "Calc.sumar(String)") is None


def test_un_generico_se_ubica_por_cantidad_de_parametros_si_no_hay_dudas() -> None:
    """`T` aparece en el descriptor como Object: solo se acepta si no hay ambigüedad."""
    unica = _cobertura(
        {"Calc.f(Ljava/lang/Object;)V": _metodo(70.0), "Calc.f()V": _metodo(10.0)}
    )
    assert cobertura_de_metodo(unica, "Calc.java", "Calc.f(T)")["lineas"] == 70.0

    dudosa = _cobertura(
        {
            "Calc.f(Ljava/lang/Object;)V": _metodo(70.0),
            "Calc.f(Ljava/lang/Number;)V": _metodo(10.0),
        }
    )
    assert cobertura_de_metodo(dudosa, "Calc.java", "Calc.f(T)") is None


def test_un_metodo_que_pasa_a_estar_sobrecargado_no_reutiliza_su_resultado() -> None:
    """La prueba guardada de `Calc.x` era de la única versión: ya no se sabe de cuál."""
    antes = "public class Calc { public int x() { return 1; } }"
    despues = (
        "public class Calc { public int x() { return 1; } "
        "public int x(int a) { return a; } }"
    )
    adaptador = JavaAdapter()

    assert "Calc.x" in adaptador.huellas_de_archivo(antes, "Calc.java")
    assert "Calc.x" not in adaptador.huellas_de_archivo(despues, "Calc.java")


# --- mutación ------------------------------------------------------------------------


def test_pit_explica_que_no_puede_mutar_una_sola_sobrecarga() -> None:
    with pytest.raises(ValueError, match="no puede mutar una sola versión"):
        comando_pit("src/main/java/Calc.java", ["Calc.sumar(long)"])


def test_pit_sigue_aceptando_metodos_sin_sobrecarga() -> None:
    assert comando_pit("src/main/java/Calc.java", ["Calc.otro"]).comando


# --- almacenamiento ---------------------------------------------------------------


def test_cada_sobrecarga_tiene_su_propio_archivo_de_spec_y_prueba() -> None:
    from qagent.almacenamiento.proyecto import PATRON_ID, id_de_spec, nombre_prueba

    ids = [
        id_de_spec("Calc.java", objetivo)
        for objetivo in ("Calc.sumar(int)", "Calc.sumar(long)", "Calc.sumar_int")
    ]

    assert len(set(ids)) == 3  # `sumar(int)` no pisa a un método `sumar_int`
    assert all(PATRON_ID.match(i) for i in ids)
    assert len({nombre_prueba(i) for i in ids}) == 3


def test_un_objetivo_sin_firma_conserva_su_identificador_de_siempre() -> None:
    from qagent.almacenamiento.proyecto import id_de_spec

    assert id_de_spec("Calc.java", "Calc.otro") == "Calc_java__Calc_otro"
