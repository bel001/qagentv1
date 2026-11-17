"""Montaje FastAPI, Depends importado y mocks async con Docker real y sin LLM real."""

import pytest

from qagent import contracts
from qagent.agents.generator import GeneratorAgent
from qagent.agents.reviewer import ReviewerAgent
from qagent.lenguajes.python_endpoints import montaje_endpoint
from qagent.llm import TokenTracker
from qagent.sandbox import preparar_imagen
from tests.lenguajes.test_python_endpoints_preparacion import ClienteGrabado
from tests.soporte_fastapi import PRUEBAS, codigo, contrato, crear_proyecto

pytestmark = pytest.mark.docker


@pytest.mark.parametrize("montaje", ["router", "app", "src_guion"])
def test_router_con_sesion_y_servicios_async_funciona_offline(
    imagen_base, tmp_path, montaje
):
    proyecto = crear_proyecto(tmp_path / "proyecto")
    plan = contrato()
    pruebas = PRUEBAS
    if montaje == "app":
        with (proyecto / "api.py").open("a", encoding="utf-8") as archivo:
            archivo.write(
                "\nfrom fastapi import FastAPI\napp = FastAPI()\n"
                "app.include_router(router, prefix='/externo')\n"
            )
        plan["aplicacion"] = "app"
    if montaje == "src_guion":
        relativa = "components/demo-api/src/demo_api"
        paquete = proyecto / relativa
        paquete.mkdir(parents=True)
        for nombre in ("api.py", "auth.py", "main.py"):
            original = proyecto / nombre
            contenido = (
                original.read_text(encoding="utf-8")
                .replace("from auth import", "from demo_api.auth import")
                .replace("from api import", "from demo_api.api import")
            )
            (paquete / nombre).write_text(contenido, encoding="utf-8")
            original.unlink()
        plan["modulo"] = f"{relativa}/api.py"
        plan["dependencias_detectadas"][0]["en_proyecto"] = (
            f"{relativa}/auth.py::require_session"
        )
        pruebas = pruebas.replace("import api\n", "api = _qagent_modulo\n").replace(
            "from auth import", "from demo_api.auth import"
        )
    imagen = preparar_imagen(proyecto)
    test = GeneratorAgent(
        ClienteGrabado(montaje_endpoint(plan) + "\n" + pruebas),
        TokenTracker(),
        ruta_proyecto=proyecto,
    ).generar(plan, 1, None)
    revision = ReviewerAgent(TokenTracker(), proyecto, imagen).revisar(plan, test, None)
    contracts.validar(contracts.REVIEW_RESULT, revision)
    assert revision["decision"] == "accept", revision["feedback"]
    assert revision["ejecucion"]["totales"]["pasaron"] == 2
    assert revision["cobertura"]["lineas"] == 100.0


def test_un_bug_real_no_se_oculta_al_arreglar_la_preparacion(imagen_base, tmp_path):
    proyecto = crear_proyecto(tmp_path / "proyecto")
    api = proyecto / "api.py"
    api.write_text(
        api.read_text(encoding="utf-8").replace(
            "return await _get_service().discover(server, user.user_id)",
            "return [{'error': 'respuesta incorrecta'}]",
        ),
        encoding="utf-8",
    )
    imagen = preparar_imagen(proyecto)
    test = contracts.generated_test_para(contrato(), 1, codigo(), "test_generado.py")
    revision = ReviewerAgent(TokenTracker(), proyecto, imagen).revisar(
        contrato(), test, None
    )
    assert revision["decision"] == "bug_detectado", revision["feedback"]
    assert revision["ejecucion"]["totales"]["fallaron"] == 1
