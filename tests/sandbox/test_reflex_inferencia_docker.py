"""La lógica de un proyecto con Reflex se infiere y se prueba en Docker, sin Reflex."""

from pathlib import Path

import pytest

from qagent.agents.planner import PlannerAgent
from qagent.agents.reviewer import ReviewerAgent
from qagent.lenguajes import PythonAdapter
from qagent.llm import TokenTracker
from qagent.llm.fake import generar_test_desde_contrato
from tests.agents.test_planner_inferencia import ClienteSecuencia, _caso


@pytest.mark.docker
def test_logica_appkit_sin_docstring_se_prueba_sin_importar_la_interfaz(
    imagen_base,
) -> None:
    proyecto = Path(__file__).parents[1] / "fixtures/appkit_inferencia"
    adaptador = PythonAdapter()
    analisis = adaptador.analizar(proyecto)
    modulo = next(m for m in analisis["modulos"] if m["ruta"] == "app/logica.py")
    cliente = ClienteSecuencia(
        [], [{"objetivo": "producto", "casos": [_caso(evidencia=["cuerpo"])]}]
    )
    tracker = TokenTracker()
    planner = PlannerAgent(
        cliente,
        tracker,
        es_simulado=True,
        proveedor_inferencia=adaptador.proveedor_inferencia(proyecto, analisis, 6000),
    )
    [contrato] = planner.planificar(modulo)
    generado = {
        "version": "2",
        "lenguaje": "python",
        "framework_pruebas": "pytest",
        "objetivo": contrato["objetivo"],
        "intento": 1,
        "archivo": "test_producto.py",
        "codigo": generar_test_desde_contrato(contrato),
        "casos_cubiertos": ["producto_basico"],
    }
    revision = ReviewerAgent(tracker, proyecto, imagen_base, es_simulado=True).revisar(
        contrato, generado, None
    )
    assert contrato["casos"][0]["origen"] == "inferido"
    assert revision["decision"] == "accept", revision
    assert revision["estado_sandbox"] == "ok"
    assert not revision["laundering_detectado"]
    assert revision["ejecucion"]["casos"][0]["resultado"] == "paso"
