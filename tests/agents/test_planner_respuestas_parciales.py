"""Una respuesta parcialmente inválida del Planner no descarta los objetivos válidos.

Se repara sin IA lo que es solo forma (el id de un caso, cómo se nombró el
objetivo) y nunca se inventa una entrada ni un resultado esperado. Lo que no sirve
queda fuera con su motivo exacto.
"""

from __future__ import annotations

import pytest

from qagent.agents.planner import (
    MOTIVO_RESPUESTA_INVALIDA,
    id_de_caso_normalizado,
)
from qagent.analysis import analizar_proyecto
from qagent.llm import TokenTracker
from qagent.orchestrator import Orquestador
from tests.agents.test_planner_endpoints import BANCO_API, RAIZ_REPO, caso, planner
from tests.orchestrator.fakes import ReviewerGuionado


@pytest.fixture(scope="module")
def modulo_api() -> dict:
    return analizar_proyecto(BANCO_API)["modulos"][0]


@pytest.fixture(scope="module")
def modulo_funciones() -> dict:
    return next(
        m
        for m in analizar_proyecto(RAIZ_REPO / "bench")["modulos"]
        if m["ruta"] == "banco_mvp.py"
    )


# --- id de caso --------------------------------------------------------------------


@pytest.mark.parametrize(
    ("valor", "esperado"),
    [
        ("ya_valido_1", "ya_valido_1"),
        ("404-no-encontrado", "404_no_encontrado"),
        ("Caso Normal", "caso_normal"),
        ("válido: límite", "valido_limite"),
        ("--raro--", "raro"),
        (7, "7"),
        ("---", None),
        (None, None),
        (True, None),
        (["a"], None),
    ],
)
def test_id_de_caso_normalizado(valor, esperado) -> None:
    assert id_de_caso_normalizado(valor) == esperado


def test_un_id_con_guiones_no_descarta_el_caso_del_endpoint(modulo_api) -> None:
    agente, _, _ = planner(
        [
            {
                "objetivo": "GET /salud",
                "casos": [caso("Salud-OK", "GET", "/salud", 200)],
            }
        ]
    )

    [contrato] = agente.planificar_endpoints(modulo_api)

    [guardado] = contrato["casos"]
    assert guardado["id"] == "salud_ok"
    # Solo cambia la etiqueta: la petición y el resultado esperado son los del modelo.
    assert guardado["entrada"] == {"metodo": "GET", "ruta": "/salud"}
    assert guardado["valor_esperado"] == {"status_code": 200}
    assert any(
        "'Salud-OK'" in aviso and "'salud_ok'" in aviso for aviso in agente.avisos
    )
    assert agente.descartados == []


def test_dos_ids_que_quedan_iguales_no_se_duplican(modulo_api) -> None:
    agente, _, _ = planner(
        [
            {
                "objetivo": "GET /salud",
                "casos": [
                    caso("salud-ok", "GET", "/salud", 200),
                    caso("salud ok", "GET", "/salud", 200),
                ],
            }
        ]
    )

    [contrato] = agente.planificar_endpoints(modulo_api)

    assert [c["id"] for c in contrato["casos"]] == ["salud_ok"]
    assert "GET /salud: caso repetido 'salud_ok'" in agente.descartados


# --- nombre del objetivo -------------------------------------------------------------


@pytest.mark.parametrize(
    "nombrado", ["get /salud", "GET  /salud", "GET /salud/", "salud", "salud()"]
)
def test_un_endpoint_nombrado_de_otra_forma_inequivoca_se_reconoce(
    modulo_api, nombrado
) -> None:
    agente, _, _ = planner(
        [{"objetivo": nombrado, "casos": [caso("ok", "GET", "/salud", 200)]}]
    )

    [contrato] = agente.planificar_endpoints(modulo_api)

    assert contrato["objetivo"] == "GET /salud"
    assert any(repr(nombrado) in aviso for aviso in agente.avisos)


def test_un_nombre_ambiguo_no_se_adivina(modulo_api) -> None:
    """`/items` lo atienden GET y POST: sin método no se elige ninguno."""
    salud = {"objetivo": "GET /salud", "casos": [caso("ok", "GET", "/salud", 200)]}
    agente, _, _ = planner(
        [{"objetivo": "/items", "casos": [caso("a", "GET", "/items", 200)]}, salud]
    )

    plan = agente.planificar_endpoints(modulo_api)

    assert [c["objetivo"] for c in plan] == ["GET /salud"]
    assert "endpoint desconocido: '/items'" in agente.descartados


def test_una_funcion_nombrada_con_parentesis_o_modulo_se_reconoce(
    modulo_funciones,
) -> None:
    caso_funcion = {
        "id": "normal",
        "entrada": {"precio": 100.0, "porcentaje": 20.0},
        "valor_esperado": 80.0,
        "origen": "docstring",
    }
    agente, _, _ = planner(
        [
            {"objetivo": "calcular_descuento()", "casos": [caso_funcion]},
            {"objetivo": "banco_mvp.es_palindromo", "casos": []},
        ]
    )
    solo = {
        **modulo_funciones,
        "funciones": [
            f
            for f in modulo_funciones["funciones"]
            if f["nombre"] in ("calcular_descuento", "es_palindromo")
        ],
    }

    plan = agente.planificar(solo)

    assert [c["objetivo"] for c in plan] == ["calcular_descuento"]
    assert "objetivo desconocido: 'calcular_descuento()'" not in agente.descartados
    assert "objetivo desconocido: 'banco_mvp.es_palindromo'" not in agente.descartados


# --- un objetivo inválido no descarta los válidos ------------------------------------


def test_un_endpoint_con_casos_malformados_no_descarta_a_los_demas(modulo_api) -> None:
    agente, _, _ = planner(
        [
            {
                "objetivo": "GET /salud",
                "casos": [caso("ok", "GET", "/salud", 200)],
            },
            {
                "objetivo": "GET /items",
                # contrato incompleto: sin `valor_esperado` y un caso que no es objeto
                "casos": [
                    {"id": "roto", "entrada": {"metodo": "GET", "ruta": "/items"}},
                    "esto no es un caso",
                ],
            },
        ]
    )

    plan = agente.planificar_endpoints(modulo_api)

    assert [c["objetivo"] for c in plan] == ["GET /salud"]
    motivo = agente.rechazadas["GET /items"]
    assert motivo.startswith(MOTIVO_RESPUESTA_INVALIDA)
    assert "caso 'roto'" in motivo  # dice qué caso y por qué, no un texto genérico
    assert "GET /salud" not in agente.rechazadas
    # No es falta de especificación: no entra en `omitidas`.
    assert "GET /items" not in agente.omitidas


def test_no_se_inventa_un_resultado_para_el_objetivo_invalido(modulo_api) -> None:
    agente, _, _ = planner(
        [
            {"objetivo": "GET /salud", "casos": [caso("ok", "GET", "/salud", 200)]},
            {
                "objetivo": "GET /items",
                "casos": [
                    {"id": "roto", "entrada": {"metodo": "GET", "ruta": "/items"}}
                ],
            },
        ]
    )

    plan = agente.planificar_endpoints(modulo_api)

    assert all(c["objetivo"] != "GET /items" for c in plan)


def test_el_orquestador_informa_el_motivo_exacto_del_objetivo_rechazado(
    modulo_api,
) -> None:
    agente, _, tracker = planner(
        [
            {"objetivo": "GET /salud", "casos": [caso("ok", "GET", "/salud", 200)]},
            {
                "objetivo": "GET /items",
                "casos": [
                    {"id": "roto", "entrada": {"metodo": "GET", "ruta": "/items"}}
                ],
            },
        ]
    )
    solo = {
        **modulo_api,
        "funciones": [],
        "endpoints": [
            e
            for e in modulo_api["endpoints"]
            if e["objetivo"] in ("GET /salud", "GET /items")
        ],
    }
    orquestador = Orquestador(
        agente, None, ReviewerGuionado(TokenTracker(), []), tracker=tracker
    )

    plan = orquestador.planificar(solo)

    assert plan.error is None
    assert [c["objetivo"] for c in plan.contratos] == ["GET /salud"]
    assert plan.motivos_omision["GET /items"].startswith(MOTIVO_RESPUESTA_INVALIDA)
    assert "caso 'roto'" in plan.motivos_omision["GET /items"]


def test_planificar_funciones_reinicia_los_rechazos(
    modulo_api, modulo_funciones
) -> None:
    agente, _, _ = planner(
        [
            {
                "objetivo": "GET /items",
                "casos": [
                    {"id": "roto", "entrada": {"metodo": "GET", "ruta": "/items"}}
                ],
            },
            {"objetivo": "GET /salud", "casos": [caso("ok", "GET", "/salud", 200)]},
        ]
    )
    agente.planificar_endpoints(modulo_api)
    assert agente.rechazadas

    agente.planificar({**modulo_funciones, "funciones": []})

    assert agente.rechazadas == {}
