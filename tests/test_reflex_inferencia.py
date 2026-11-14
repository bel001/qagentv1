"""Regresiones de omisiones precisas y componentes Reflex, sin ejecutar el proyecto."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import Mock

import pytest

from qagent import contracts
from qagent.agents.planner import PlannerAgent
from qagent.analysis import analizar_proyecto
from qagent.config import cargar_configuracion
from qagent.lenguajes import PythonAdapter
from qagent.llm import RespuestaLLM, TokenTracker
from qagent.orchestrator import corrida
from qagent.proyectos.vista_previa import generar_vista_previa
from tests.agents.test_planner_inferencia import (
    MODULO,
    ClienteSecuencia,
    _caso,
    _planner,
)

FIXTURE = Path(__file__).parent / "fixtures/appkit_inferencia"


@pytest.mark.parametrize(
    ("importacion", "retorno"),
    [
        ("import reflex as rx", "rx.Component"),
        ("import reflex as vista", '"vista.Component"'),
        ("from reflex import Component as C", "C"),
        ("from reflex.components.component import BaseComponent", "BaseComponent"),
    ],
)
def test_componente_confirmado_es_visible_pero_no_gasta_tokens(
    tmp_path: Path, importacion: str, retorno: str
) -> None:
    (tmp_path / "navbar.py").write_text(
        f"{importacion}\ndef sidebar() -> {retorno}:\n    return None\n"
        'raise RuntimeError("Este módulo no debe importarse en el host")\n',
        encoding="utf-8",
    )
    [modulo] = analizar_proyecto(tmp_path)["modulos"]
    cliente = Mock()
    proveedor = Mock()
    tracker = TokenTracker()
    planner = PlannerAgent(cliente, tracker, proveedor_inferencia=proveedor)
    assert planner.planificar(modulo) == []
    assert "Reflex" in planner.omitidas["sidebar"]
    cliente.generar.assert_not_called()
    proveedor.assert_not_called()
    assert tracker.total_tokens == 0
    vista = generar_vista_previa(tmp_path, ia=False)
    [funcion] = vista["modulos"][0]["funciones"]
    assert funcion["nombre"] == "sidebar"
    assert funcion["no_soportada"]
    assert not funcion["inferible"]
    assert funcion["aviso_inferencia"] is None
    assert vista["resumen"]["total_funciones_publicas"] == 1
    assert vista["recomendacion"]["recomendaciones"] == []


@pytest.mark.parametrize(
    "codigo",
    [
        "import otra as rx\ndef f() -> rx.Component: return None",
        "class Component: pass\ndef f() -> Component: return None",
        "import reflex as rx\ndef f(x: int) -> int: return x * 2",
        "import reflex as rx\nrx = objeto\ndef f() -> rx.Component: return None",
        "import reflex as rx\nrx, otro = valores\ndef f() -> rx.Component: return None",
        "from reflex import Component\nclass Component: pass\ndef f() -> Component: return None",
        "if condicion:\n    import reflex as rx\ndef f() -> rx.Component: return None",
        "import reflex as rx\nfor rx in valores: pass\ndef f() -> rx.Component: return None",
    ],
)
def test_no_excluye_funciones_por_nombre_o_alias_ambiguos(
    tmp_path: Path, codigo: str
) -> None:
    (tmp_path / "logica.py").write_text(codigo, encoding="utf-8")
    funciones = analizar_proyecto(tmp_path)["modulos"][0]["funciones"]
    assert funciones
    assert not any(f.get("no_soportada") for f in funciones)


def test_modulo_mixto_solo_envia_logica_al_llm(tmp_path: Path) -> None:
    (tmp_path / "mixto.py").write_text(
        "import reflex as rx\ndef sidebar() -> rx.Component: return rx.link('Inicio')\n"
        'def doble(x: int) -> int:\n    """Devuelve el doble de x."""\n    return x * 2\n',
        encoding="utf-8",
    )
    modulo = analizar_proyecto(tmp_path)["modulos"][0]
    cliente = ClienteSecuencia(
        [
            {
                "objetivo": "doble",
                "casos": [
                    {
                        "id": "normal",
                        "entrada": {"x": 3},
                        "valor_esperado": 6,
                        "origen": "docstring",
                        "categoria": "normal",
                    }
                ],
            }
        ]
    )
    planner = PlannerAgent(cliente, TokenTracker())
    plan = planner.planificar(modulo)
    assert [c["objetivo"] for c in plan] == ["doble"]
    assert len(cliente.prompts) == 1
    assert "sidebar" not in cliente.prompts[0]
    assert "Reflex" in planner.omitidas["sidebar"]


@pytest.mark.parametrize("prefijo", ["", "src"])
def test_no_confunde_un_modulo_local_llamado_reflex_con_el_framework(
    tmp_path: Path, prefijo: str
) -> None:
    local = tmp_path / prefijo / "reflex.py"
    local.parent.mkdir(exist_ok=True)
    local.write_text("class Component: pass", encoding="utf-8")
    (tmp_path / "logica.py").write_text(
        "import reflex as rx\ndef f() -> rx.Component: return rx.Component()",
        encoding="utf-8",
    )
    modulo = next(
        m for m in analizar_proyecto(tmp_path)["modulos"] if m["ruta"] == "logica.py"
    )
    assert "no_soportada" not in modulo["funciones"][0]


def test_inferencia_distingue_sin_propuestas_y_evidencia_invalida() -> None:
    vacio = _planner(ClienteSecuencia([], []))
    assert vacio.planificar(MODULO) == []
    assert "no propuso casos" in vacio.omitidas["producto"]
    rechazado = _planner(
        ClienteSecuencia(
            [], [{"objetivo": "producto", "casos": [_caso(evidencia=["inventada"])]}]
        )
    )
    assert rechazado.planificar(MODULO) == []
    assert "propuso casos, pero se descartaron" in rechazado.omitidas["producto"]
    assert "inventada" in rechazado.omitidas["producto"]


def test_contexto_de_fixture_appkit_infiere_logica_sin_ejecutarla() -> None:
    adaptador = PythonAdapter()
    analisis = adaptador.analizar(FIXTURE)
    assert not any(m.get("integraciones") for m in analisis["modulos"])
    assert "admin_sidebar_item" not in {
        o["objetivo"] for o in adaptador.objetivos(analisis)
    }
    modulo = next(m for m in analisis["modulos"] if m["ruta"] == "app/logica.py")
    cliente = ClienteSecuencia(
        [], [{"objetivo": "producto", "casos": [_caso(evidencia=["cuerpo"])]}]
    )
    planner = PlannerAgent(
        cliente,
        TokenTracker(),
        proveedor_inferencia=adaptador.proveedor_inferencia(FIXTURE, analisis, 6000),
    )
    [contrato] = planner.planificar(modulo)
    assert contrato["objetivo"] == "producto"
    assert contrato["casos"][0]["origen"] == "inferido"
    assert "cuerpo" in contrato["casos"][0]["evidencia"]


def test_88_funciones_sin_casos_conservan_todo_el_balance(
    tmp_path: Path, monkeypatch
) -> None:
    (tmp_path / "logica.py").write_text(
        "\n".join(f"def funcion{i}(x: int) -> int: return x + {i}" for i in range(88)),
        encoding="utf-8",
    )
    cliente = Mock()
    cliente.generar.return_value = RespuestaLLM("[]", 0, 0, 0.0, "simulado")
    monkeypatch.setattr(corrida, "crear_cliente", lambda *a, **k: cliente)
    resumen = corrida.ejecutar_corrida(
        tmp_path,
        "humo",
        cargar_configuracion(simulado=True).config,
        None,
        simulado=True,
        preparar_imagen=lambda _: "imagen-simulada",
    )
    assert resumen.total_descubiertos == resumen.total_seleccionados == 88
    assert resumen.total_procesados == resumen.total_pendientes == 0
    assert resumen.objetivos_omitidos == 88
    results = json.loads((Path(resumen.carpeta) / "results.json").read_text("utf-8"))
    assert results["total_descubiertos"] == 88
    assert len(results["omitidos"]) == 88
    assert all(o["motivo"] for o in results["omitidos"])
    assert not results["objetivos"]
    from qagent.storage.vista_reporte import vista_reporte

    assert vista_reporte(results, None)["total_descubiertos"] == 88
    historico = {k: v for k, v in results.items() if k != "total_descubiertos"}
    assert vista_reporte(historico, None)["total_descubiertos"] is None
    results["total_descubiertos"] = -1
    assert not contracts.es_valido(contracts.RUN_LOG, results)


def test_un_plan_guardado_no_habilita_un_componente_reflex() -> None:
    from qagent.analysis.interfaz_python import MOTIVO_REFLEX
    from qagent.orchestrator import Orquestador

    cliente = ClienteSecuencia(
        [{"objetivo": "producto", "casos": [_caso(evidencia=["cuerpo"])]}]
    )
    # Contrato histórico válido; el análisis actual reconoce su framework no soportado.
    [contrato] = _planner(ClienteSecuencia([], cliente.respuestas[0])).planificar(
        MODULO
    )
    modulo = {
        **MODULO,
        "funciones": [{**MODULO["funciones"][0], "no_soportada": MOTIVO_REFLEX}],
    }
    prohibido = Mock()
    orquestador = Orquestador(PlannerAgent(prohibido, TokenTracker()), Mock(), Mock())
    plan = orquestador.planificar(modulo, plan_reutilizado=[contrato])
    assert plan.contratos == []
    assert "Reflex" in plan.motivos_omision["producto"]
    prohibido.generar.assert_not_called()


@pytest.mark.parametrize("extension", [".txt", ".rb", ".go"])
def test_proyecto_sin_soporte_devuelve_diagnostico(
    tmp_path: Path, extension: str
) -> None:
    from qagent.proyectos.proyecto_local import inspeccionar_carpeta

    (tmp_path / ("main" + extension)).write_text(
        "contenido no ejecutable", encoding="utf-8"
    )
    respuesta = inspeccionar_carpeta(tmp_path)
    assert respuesta["ok"] is False
    assert respuesta["error"]
