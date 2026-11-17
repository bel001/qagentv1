"""El rechazo del oráculo Python dice qué aserción escribir (backlog 6)."""

from __future__ import annotations

from qagent.lenguajes.python_revision import ReglasRevisionPython

CONTRATO = {
    "objetivo": "sumar",
    "modulo": "calc.py",
    "casos": [
        {"id": "normal", "entrada": {"a": 1, "b": 2}, "valor_esperado": 3},
        {"id": "error", "entrada": {"a": "x", "b": 2}, "excepcion": "TypeError"},
    ],
}


def test_un_valor_mal_comprobado_recibe_la_asercion_exacta() -> None:
    codigo = (
        "import pytest\nfrom calc import sumar\n\n"
        "def test_normal():\n    assert len(str(sumar(1, 2))) == 1\n\n"
        "def test_error():\n    with pytest.raises(TypeError):\n        sumar('x', 2)\n"
    )

    problema = ReglasRevisionPython.validar_oraculo(CONTRATO, codigo)

    assert problema is not None
    assert "Corrige esto: escribe `assert sumar(a=1, b=2) == 3`" in problema
    assert "sin len()" in problema


def test_una_excepcion_faltante_recibe_la_forma_de_pytest_raises() -> None:
    codigo = (
        "from calc import sumar\n\n"
        "def test_normal():\n    assert sumar(1, 2) == 3\n\n"
        "def test_error():\n    assert sumar(1, 2) == 3\n"
    )

    problema = ReglasRevisionPython.validar_oraculo(CONTRATO, codigo)

    assert problema is not None
    assert "with pytest.raises(TypeError):" in problema
    assert "sumar(a='x', b=2)" in problema


def test_un_test_correcto_sigue_sin_problemas() -> None:
    codigo = (
        "import pytest\nfrom calc import sumar\n\n"
        "def test_normal():\n    assert sumar(a=1, b=2) == 3\n\n"
        "def test_error():\n    with pytest.raises(TypeError):\n        sumar(a='x', b=2)\n"
    )
    assert ReglasRevisionPython.validar_oraculo(CONTRATO, codigo) is None
