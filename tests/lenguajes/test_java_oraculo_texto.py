"""Generador y validador Java aceptan las mismas comparaciones de texto (backlog 3).

Caso observado: `CharSequenceUtils.subSequence` devuelve CharSequence. La prueba
generada comparaba con `.toString()` y el guardrail la rechazaba sin ejecutarla. Y el
rechazo no decía qué corregir (backlog 6): se repetía igual en cada intento.
"""

from __future__ import annotations

import pytest

from qagent.lenguajes import JavaAdapter
from qagent.lenguajes.java_oraculo import TIPOS_TEXTO, validar_java

LLAMADA = 'CharSequenceUtils.subSequence("abc", 1)'
FIRMA = "public static CharSequence subSequence(final CharSequence cs, final int start)"


@pytest.fixture
def proyecto(tmp_path):
    """Un proyecto con la fuente real: el prompt Java lee su contexto estático."""
    fuente = [
        "public class CharSequenceUtils {",
        f"  {FIRMA} {{ return cs.subSequence(start, cs.length()); }}",
        "}",
    ]
    (tmp_path / "CharSequenceUtils.java").write_text(
        "\n".join(fuente) + "\n", encoding="utf-8"
    )
    return tmp_path


def _con_modulo(contrato: dict) -> dict:
    return {**contrato, "modulo": "CharSequenceUtils.java", "firma": FIRMA}


def _contrato(retorno: str = "CharSequence", esperado: object = "bc") -> dict:
    return {
        "objetivo": "CharSequenceUtils.subSequence",
        "firma": f"public static {retorno} subSequence(final CharSequence cs, final int start)",
        "casos": [
            {
                "id": "normal",
                "entrada": {"cs": "abc", "start": 1},
                "valor_esperado": esperado,
            }
        ],
    }


def _prueba(cuerpo: str) -> str:
    return (
        "import static org.junit.jupiter.api.Assertions.*;\n"
        "import org.junit.jupiter.api.Test;\n"
        "class CharSequenceUtilsTest {\n"
        "  @Test void test_normal() {\n" + cuerpo + "\n  }\n}\n"
    )


# --- se acepta lo que pide el prompt --------------------------------------------------


@pytest.mark.parametrize("retorno", sorted(TIPOS_TEXTO))
def test_un_tipo_de_texto_se_compara_con_to_string(retorno) -> None:
    codigo = _prueba(f'    assertEquals("bc", {LLAMADA}.toString());')
    assert validar_java(_contrato(retorno), codigo) is None


def test_to_string_sobre_una_variable_local_tambien_vale() -> None:
    codigo = _prueba(
        f'    CharSequence r = {LLAMADA};\n    assertEquals("bc", r.toString());'
    )
    assert validar_java(_contrato(), codigo) is None


def test_string_se_sigue_comparando_directamente() -> None:
    codigo = _prueba(f'    assertEquals("bc", {LLAMADA});')
    assert validar_java(_contrato("String"), codigo) is None


def test_el_prompt_del_generator_pide_la_misma_comparacion(proyecto) -> None:
    prompt = JavaAdapter().prompt_generator(_con_modulo(_contrato()), 1, None, proyecto)
    assert "CharSequence" in prompt
    assert 'assertEquals("esperado", llamada.toString())' in prompt
    assert "trim" in prompt  # y prohíbe las demás transformaciones


# --- y nada más: casos negativos -----------------------------------------------------


@pytest.mark.parametrize(
    ("retorno", "cuerpo", "pista"),
    [
        (
            "CharSequence",
            f'    assertEquals("bc", {LLAMADA});',
            "<llamada>.toString()",
        ),
        (
            "CharSequence",
            f'    assertEquals("bc", {LLAMADA}.toString().trim());',
            "dentro de otra operación",
        ),
        (
            "CharSequence",
            f'    assertEquals("bc", String.valueOf({LLAMADA}));',
            "dentro de otra operación",
        ),
        (
            "CharSequence",
            f'    assertEquals("xx", {LLAMADA}.toString());',
            'el contrato pide "bc"; no cambies el valor esperado',
        ),
        (
            "CharSequence",
            '    assertEquals("bc", CharSequenceUtils.subSequence("abc", 2).toString());',
            "el argumento 2 es `2` y el caso 'normal' pide 1",
        ),
        (
            "String",
            f'    assertEquals("bc", {LLAMADA}.toString());',
            "quita `.toString()`",
        ),
        (
            "Integer",
            f'    assertEquals("5", {LLAMADA}.toString());',
            "quita `.toString()`",
        ),
    ],
)
def test_transformaciones_incorrectas_se_rechazan_con_su_pista(
    retorno, cuerpo, pista
) -> None:
    esperado = 5 if retorno == "Integer" else "bc"
    problema = validar_java(_contrato(retorno, esperado), _prueba(cuerpo))
    assert problema is not None
    assert problema.startswith("Oráculo inválido: el caso 'normal'")
    assert "Corrige esto:" in problema
    assert pista in problema


def test_to_string_con_argumentos_no_cuenta_como_to_string() -> None:
    codigo = _prueba(f'    assertEquals("bc", {LLAMADA}.toString(1));')
    assert validar_java(_contrato(), codigo) is not None


# --- diagnóstico de otras causas (backlog 6) ---------------------------------------


def _contrato_instancia(**caso) -> dict:
    return {
        "objetivo": "Calculadora.sumar",
        "firma": "public int sumar(int a, int b)",
        "casos": [
            {"id": "normal", "entrada": {"a": 1, "b": 2}, "valor_esperado": 3, **caso}
        ],
    }


def _prueba_calc(cuerpo: str) -> str:
    return (
        "import static org.junit.jupiter.api.Assertions.*;\n"
        "import org.junit.jupiter.api.Test;\n"
        "class CalculadoraTest {\n"
        "  @Test void test_normal() {\n" + cuerpo + "\n  }\n}\n"
    )


@pytest.mark.parametrize(
    ("cuerpo", "caso", "pista"),
    [
        (
            "    assertEquals(3, Calculadora.sumar(1, 2));",
            {},
            "no llama a sumar sobre un objeto construido",
        ),
        (
            "    assertEquals(3, new Calculadora().sumar(1));",
            {},
            "pasa 1 argumento(s) y el caso 'normal' define 2",
        ),
        (
            "    assertEquals(3.0, new Calculadora().sumar(1, 2), 0.0);",
            {},
            "literal entero, sin decimales ni delta",
        ),
        (
            "    assertEquals(3, new Calculadora().sumar(1, 2));",
            {"valor_esperado": None, "excepcion": "IllegalArgumentException"},
            "assertThrows(IllegalArgumentException.class",
        ),
    ],
)
def test_cada_rechazo_dice_que_argumento_llamada_tipo_o_asercion_corregir(
    cuerpo, caso, pista
) -> None:
    contrato = _contrato_instancia(**caso)
    if caso.get("valor_esperado", 0) is None:
        del contrato["casos"][0]["valor_esperado"]
    problema = validar_java(contrato, _prueba_calc(cuerpo))
    assert problema is not None
    assert pista in problema


def test_el_intento_que_sigue_la_pista_queda_aceptado(proyecto) -> None:
    """Regresión del ciclo: rechazo → feedback con la pista → corrección aceptada."""
    contrato = _con_modulo(_contrato())
    primero = _prueba(f'    assertEquals("bc", {LLAMADA}.toString().trim());')

    rechazo = validar_java(contrato, primero)

    assert rechazo is not None
    prompt = JavaAdapter().prompt_generator(contrato, 2, rechazo, proyecto)
    assert "Para comparar el texto solo se admite `.toString()`" in prompt
    corregido = _prueba(f'    assertEquals("bc", {LLAMADA}.toString());')
    assert validar_java(contrato, corregido) is None
