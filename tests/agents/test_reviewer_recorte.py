"""El Reviewer no envía al LLM la salida completa del runner para clasificar un fallo."""

from __future__ import annotations

from qagent.agents.reviewer import (
    LARGO_INICIO_SALIDA_CLASIFICACION,
    LARGO_MAXIMO_SALIDA_CLASIFICACION,
    ReviewerAgent,
    recortar_salida,
)
from qagent.llm import TokenTracker
from qagent.llm.modelos import RespuestaLLM


def test_una_salida_corta_no_se_toca() -> None:
    assert recortar_salida("E   assert 1 == 2") == "E   assert 1 == 2"


def test_una_salida_enorme_conserva_el_inicio_y_el_final() -> None:
    salida = "INICIO" + "x" * 500_000 + "FINAL"

    recortada = recortar_salida(salida)

    assert recortada.startswith("INICIO")
    assert recortada.endswith("FINAL")
    assert "[…recortado…]" in recortada
    assert len(recortada) <= LARGO_MAXIMO_SALIDA_CLASIFICACION + 20
    assert recortada.index("[…recortado…]") == LARGO_INICIO_SALIDA_CLASIFICACION + 1


class _ClienteEspia:
    def __init__(self) -> None:
        self.prompts: list[str] = []

    def generar(self, prompt: str, rol: str = "reviewer", **_opciones) -> RespuestaLLM:
        self.prompts.append(prompt)
        return RespuestaLLM("error_test", 10, 1, 0.0, "modelo-falso")


def test_el_prompt_de_clasificacion_queda_acotado(tmp_path) -> None:
    cliente = _ClienteEspia()
    reviewer = ReviewerAgent(TokenTracker(), tmp_path, "imagen", cliente=cliente)
    contrato = {"objetivo": "sumar", "modulo": "calc.py", "casos": [{"id": "uno"}]}

    decision = reviewer._clasificar_con_llm("y" * 2_000_000, contrato, "pytest")

    assert decision == "error_test"
    [prompt] = cliente.prompts
    assert len(prompt) < LARGO_MAXIMO_SALIDA_CLASIFICACION + 1000
    # El contrato va en una sola línea: sin sangría que solo gasta tokens.
    assert '{"objetivo": "sumar", "modulo": "calc.py", "casos": [{"id": "uno"}]}' in (
        prompt
    )
