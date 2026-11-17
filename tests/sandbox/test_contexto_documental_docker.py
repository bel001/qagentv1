"""El contexto recuperado genera Vitest ejecutable y conserva la detección de bugs."""

import pytest

from qagent.agents.generator import GeneratorAgent
from qagent.agents.reviewer import ReviewerAgent
from qagent.llm import TokenTracker
from qagent.llm.fake import FakeLLMClient
from qagent.sandbox import LimitesSandbox
from qagent.sandbox.imagen import _imagen_existe
from qagent.sandbox.modelos import IMAGEN_NODE
from tests.lenguajes.test_javascript_contexto import FUENTE, planificar, preparar

pytestmark = pytest.mark.docker


@pytest.mark.parametrize("bug", [False, True])
def test_documentacion_recuperada_pasa_o_detecta_bug_sin_cambiar_aserciones(
    cliente_docker, tmp_path, bug
):
    if not _imagen_existe(cliente_docker, IMAGEN_NODE):
        pytest.skip("Falta la imagen qagent-sandbox:node.")
    fuente = FUENTE.replace("? 1 :", "? n - 1 :") if bug else FUENTE
    adaptador, _, modulo = preparar(tmp_path, fuente)
    (tmp_path / "package.json").write_text('{"type":"module"}', encoding="utf-8")
    _, [contrato] = planificar(adaptador, modulo)
    tracker = TokenTracker()
    generado = GeneratorAgent(
        FakeLLMClient(grabaciones={}), tracker, es_simulado=True, ruta_proyecto=tmp_path
    ).generar(contrato, 1, None)
    revision = ReviewerAgent(
        tracker,
        tmp_path,
        IMAGEN_NODE,
        limites=LimitesSandbox(cpus=2.0, memoria="2g", timeout_s=120),
    ).revisar(contrato, generado, None)
    assert revision["decision"] == ("bug_detectado" if bug else "accept"), revision[
        "feedback"
    ]
    assert revision["ejecucion"]["totales"]["total"] == 2
    assert revision["ejecucion"]["totales"]["fallaron"] == (2 if bug else 0)
