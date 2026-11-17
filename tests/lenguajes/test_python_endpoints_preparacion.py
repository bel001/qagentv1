"""Regresiones del montaje de endpoints; las fuentes y los tests solo se leen."""

import ast
import copy

import pytest

from qagent import contracts
from qagent.agents.generator import GeneratorAgent
from qagent.agents.planner import PlannerAgent
from qagent.agents.reviewer import ReviewerAgent
from qagent.analysis import analizar_proyecto
from qagent.lenguajes.python_generacion import prompt_generator
from qagent.lenguajes.python_revision import ReglasRevisionPython
from qagent.llm import RespuestaLLM, TokenTracker
from qagent.sandbox import ResultadoSandbox
from tests.soporte_fastapi import codigo, contrato, crear_proyecto


class ClienteGrabado:
    def __init__(self, respuesta: str) -> None:
        self.respuesta = respuesta
        self.prompts: list[str] = []

    def generar(self, prompt: str, rol: str = "generator") -> RespuestaLLM:
        self.prompts.append(prompt)
        return RespuestaLLM(self.respuesta, 1, 1, 0.0, "grabado")


def test_alias_importado_resuelve_callable_y_no_se_ofrece_como_query(tmp_path):
    proyecto = crear_proyecto(tmp_path)
    modulo = next(
        m for m in analizar_proyecto(proyecto)["modulos"] if m["ruta"] == "api.py"
    )
    [endpoint] = modulo["endpoints"]
    assert endpoint["dependencias"] == contrato()["dependencias_detectadas"]
    assert endpoint["parametros_consulta"] == []


def test_planner_conserva_depends_sin_reemplazo_en_el_contrato(tmp_path):
    import json

    proyecto = crear_proyecto(tmp_path)
    modulo = next(
        m for m in analizar_proyecto(proyecto)["modulos"] if m["ruta"] == "api.py"
    )
    propuesto = [{"objetivo": contrato()["objetivo"], "casos": contrato()["casos"]}]
    cliente = ClienteGrabado(json.dumps(propuesto))
    [plan] = PlannerAgent(cliente, TokenTracker()).planificar_endpoints(modulo)
    contracts.validar(contracts.PLANNER_V3, plan)
    assert plan["dependencias"] == []
    assert plan["dependencias_detectadas"] == contrato()["dependencias_detectadas"]


def test_generator_recibe_manejador_depends_y_montaje_con_prefijo(tmp_path):
    proyecto = crear_proyecto(tmp_path)
    cliente = ClienteGrabado(codigo())
    resultado = GeneratorAgent(cliente, TokenTracker(), ruta_proyecto=proyecto).generar(
        contrato(), 1, None
    )
    ast.parse(resultado["codigo"])
    [prompt] = cliente.prompts
    assert "await _get_service().discover(server, user.user_id)" in prompt
    assert "auth.py::require_session" in prompt
    assert "Callable de override: auth.require_session" in prompt
    assert "raise_server_exceptions=True" in prompt
    assert "AsyncMock" in prompt
    assert "no declara Depends" not in prompt
    assert "app_pruebas.include_router(router, prefix=" in prompt


@pytest.mark.parametrize("reexportar", [False, True])
def test_alias_anotado_local_o_reexportado_no_se_ejecuta(tmp_path, reexportar):
    crear_proyecto(tmp_path)
    if reexportar:
        (tmp_path / "exportado.py").write_text(
            "from auth import RequiredSession as Sesion\n", encoding="utf-8"
        )
        ruta = tmp_path / "api.py"
        ruta.write_text(
            ruta.read_text(encoding="utf-8").replace(
                "from auth import RequiredSession",
                "from exportado import Sesion as RequiredSession",
            ),
            encoding="utf-8",
        )
    else:
        ruta = tmp_path / "api.py"
        ruta.write_text(
            ruta.read_text(encoding="utf-8").replace(
                "from auth import RequiredSession",
                "from typing import Annotated\nfrom fastapi import Depends\n"
                "from auth import require_session\n"
                "RequiredSession = Annotated[object, Depends(require_session)]",
            ),
            encoding="utf-8",
        )
    # Un ciclo no debe colgar el analizador; el alias válido sigue resolviéndose.
    with (tmp_path / "auth.py").open("a", encoding="utf-8") as archivo:
        archivo.write("\nA = B\nB = A\nraise RuntimeError('No importar en el host')\n")
    modulo = next(
        m for m in analizar_proyecto(tmp_path)["modulos"] if m["ruta"] == "api.py"
    )
    assert (
        modulo["endpoints"][0]["dependencias"] == contrato()["dependencias_detectadas"]
    )


def test_import_con_guion_es_python_valido_y_agrega_src_al_path():
    from qagent.lenguajes.python_endpoints import montaje_endpoint

    plan = {**contrato(), "modulo": "components/demo-api/src/demo_api/api.py"}
    plantilla = montaje_endpoint(plan)
    ast.parse(plantilla)
    assert (
        "importlib.import_module('components.demo-api.src.demo_api.api')" in plantilla
    )
    assert "sys.path.insert(0, '/work/proyecto/components/demo-api/src')" in plantilla
    assert "from components.demo-api" not in plantilla


@pytest.mark.parametrize(
    "preparacion",
    [
        "from api import router\nclient = TestClient(router)",
        "from api import router as r\nr.dependency_overrides.clear()",
        "import api\nr = api.router\nr.dependency_overrides.clear()",
    ],
)
def test_router_incorrecto_se_rechaza_antes_del_sandbox(tmp_path, preparacion):
    crear_proyecto(tmp_path)

    def no_ejecutar(*args):
        pytest.fail("El montaje inválido no debe llegar al sandbox")

    test = contracts.generated_test_para(
        contrato(), 1, preparacion + "\n" + codigo(), "test_generado.py"
    )
    revision = ReviewerAgent(
        TokenTracker(), tmp_path, "imagen", ejecutor=no_ejecutar
    ).revisar(contrato(), test, None)
    assert revision["decision"] == "retry"
    assert "Montaje inválido" in revision["feedback"]


@pytest.mark.parametrize("autenticacion", [False, True])
def test_un_500_sin_diagnostico_no_se_convierte_en_bug(tmp_path, autenticacion):
    crear_proyecto(tmp_path)
    salida = (
        "AssertionError: assert 500 == 200\n"
        " + where 500 = <Response [500 Internal Server Error]>.status_code"
    )
    if autenticacion:
        salida += "\nInstance of type AuthenticationConfiguration not found in registry"
    resultado = ResultadoSandbox(exit_code=1, stdout=salida, stderr="")
    test = contracts.generated_test_para(contrato(), 1, codigo(), "test_generado.py")
    revision = ReviewerAgent(
        TokenTracker(), tmp_path, "imagen", ejecutor=lambda *args: resultado
    ).revisar(contrato(), test, None)
    assert revision["decision"] == "retry"
    assert revision["tipo_fallo"] == "error_test"
    assert "Conserva" in revision["feedback"] or "conserva" in revision["feedback"]


def test_un_fallo_de_respuesta_conocido_sigue_siendo_bug(tmp_path):
    clasificacion = ReglasRevisionPython.clasificar_salida(
        "fastapi.exceptions.ResponseValidationError: respuesta inválida",
        contrato(),
        tmp_path,
    )
    assert clasificacion.tipo == "bug_respuesta"


def test_un_valor_json_500_no_se_confunde_con_un_error_http(tmp_path):
    clasificacion = ReglasRevisionPython.clasificar_salida(
        "assert response.status_code == 200\n"
        "> assert response.json()['valor'] == 200\n"
        "E AssertionError: assert 500 == 200",
        contrato(),
        tmp_path,
    )
    assert clasificacion.tipo == "fallo_asercion"


def test_el_contexto_no_lee_dependencias_fuera_del_proyecto(tmp_path):
    crear_proyecto(tmp_path)
    plan = copy.deepcopy(contrato())
    exterior = tmp_path.parent / "externo.py"
    exterior.write_text(
        "def require_session():\n    return 'NO_LEER'\n", encoding="utf-8"
    )
    plan["dependencias_detectadas"][0]["en_proyecto"] = "../externo.py::require_session"
    assert "NO_LEER" not in prompt_generator(plan, 1, None, tmp_path)


def test_schema_dependencias_detectadas_compatible_y_estricto():
    plan = contrato()
    contracts.validar(contracts.PLANNER_V3, plan)
    anterior = {k: v for k, v in plan.items() if k != "dependencias_detectadas"}
    contracts.validar(contracts.PLANNER_V3, anterior)
    plan["dependencias_detectadas"][0]["valor_esperado"] = 200
    assert not contracts.es_valido(contracts.PLANNER_V3, plan)


def test_spec_antigua_recibe_contexto_actual_sin_volver_a_planificar(tmp_path):
    from qagent.orchestrator import Orquestador

    crear_proyecto(tmp_path)
    modulo = next(
        m for m in analizar_proyecto(tmp_path)["modulos"] if m["ruta"] == "api.py"
    )
    anterior = contrato()
    anterior.pop("dependencias_detectadas")
    anterior["huella"] = modulo["huella"]
    tracker = TokenTracker()
    cliente = ClienteGrabado("No se debe llamar al Planner")
    agente = PlannerAgent(cliente, tracker)
    orquestador = Orquestador(agente, None, None, tracker=tracker)
    plan = orquestador.planificar(modulo, plan_reutilizado=[anterior])
    assert plan.error is None
    [actual] = plan.contratos
    assert actual["casos"] == anterior["casos"]
    assert actual["dependencias_detectadas"] == contrato()["dependencias_detectadas"]
    assert cliente.prompts == []
    assert "dependencias_detectadas" not in anterior
