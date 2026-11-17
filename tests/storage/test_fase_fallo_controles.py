"""Los informes dicen en qué fase se detuvo un objetivo y qué controles no corrieron.

Una prueba rechazada antes de ejecutarse no «incumple» el sandbox ni el
anti-laundering: esos controles no se ejecutaron.
"""

from __future__ import annotations

import pytest

from qagent import contracts
from qagent.orchestrator.orquestador import ResultadoObjetivo
from qagent.storage import registro
from qagent.storage.registro import (
    controles,
    controles_no_ejecutados,
    fase_del_fallo,
)
from qagent.storage.vista_reporte import (
    NO_EJECUTADO,
    TEXTO_FASE_FALLO,
    _controles,
)

CODIGO = "def test_uno():\n    assert True\n"


def _revision(**cambios) -> dict:
    base = {
        "objetivo": "sumar",
        "intento": 1,
        "estado_sandbox": "fallo",
        "cobertura": None,
        "laundering_detectado": False,
        "tipo_fallo": "error_test",
        "hash_error": "h",
        "decision": "stalled",
        "feedback": "detalle",
    }
    return {**base, **cambios}


def _objetivo(revisiones=(), **cambios) -> ResultadoObjetivo:
    datos = {"objetivo": "sumar", "critical": False, "codigo": CODIGO}
    return ResultadoObjetivo(**{**datos, **cambios}, revisiones=list(revisiones))


EJECUTADA = {"casos": []}  # el Reviewer agrega `ejecucion` solo si hubo sandbox


@pytest.mark.parametrize(
    ("objetivo", "fase"),
    [
        (_objetivo(decision="accept", revisiones=[_revision(decision="accept")]), None),
        (_objetivo(codigo=None, motivo_sin_veredicto="error_planner"), "planificacion"),
        (
            _objetivo(codigo=None, motivo_sin_veredicto="error_contrato_planner"),
            "planificacion",
        ),
        (_objetivo(codigo=None, motivo_sin_veredicto="tiempo_agotado"), "generacion"),
        (_objetivo(motivo_sin_veredicto="tiempo_agotado"), "entorno"),
        (
            _objetivo(
                decision="stalled",
                revisiones=[_revision(feedback="Oráculo inválido: falta un caso")],
            ),
            "validacion",
        ),
        (
            _objetivo(
                decision="stalled",
                revisiones=[_revision(ejecucion=EJECUTADA, feedback="ImportError")],
            ),
            "ejecucion",
        ),
        (
            _objetivo(
                decision="stalled",
                revisiones=[
                    _revision(
                        ejecucion=EJECUTADA,
                        tipo_fallo=None,
                        feedback="Error de entorno: falta libpq. Reintentar no lo corrige.",
                    )
                ],
            ),
            "entorno",
        ),
        (
            _objetivo(
                decision="stalled",
                revisiones=[
                    _revision(
                        ejecucion=EJECUTADA, tipo_fallo=None, estado_sandbox="oom"
                    )
                ],
            ),
            "entorno",
        ),
        (
            _objetivo(
                decision="bug_detectado",
                revisiones=[
                    _revision(
                        ejecucion=EJECUTADA,
                        tipo_fallo="bug_codigo",
                        decision="bug_detectado",
                    )
                ],
            ),
            "proyecto",
        ),
        (
            _objetivo(
                motivo_sin_veredicto="error_compilacion_proyecto",
                revisiones=[_revision(ejecucion=EJECUTADA, tipo_fallo=None)],
            ),
            "proyecto",
        ),
        (_objetivo(codigo=None), None),  # no se llegó a procesar
    ],
)
def test_fase_del_fallo(objetivo, fase) -> None:
    assert fase_del_fallo(objetivo) == fase


def test_cada_fase_tiene_su_texto_para_la_persona() -> None:
    fases = {
        registro.FASE_PLANIFICACION,
        registro.FASE_GENERACION,
        registro.FASE_VALIDACION,
        registro.FASE_EJECUCION,
        registro.FASE_ENTORNO,
        registro.FASE_PROYECTO,
    }
    assert set(TEXTO_FASE_FALLO) == fases
    # Solo «proyecto» atribuye el fallo al código del usuario.
    assert "No es un error de tu código" not in TEXTO_FASE_FALLO["proyecto"]
    for fase in ("planificacion", "generacion", "validacion", "entorno"):
        assert "No es un error de tu código" in TEXTO_FASE_FALLO[fase]


def test_rechazo_por_oraculo_no_marca_el_sandbox_como_incumplido() -> None:
    """El caso observado: oráculo rechazado y la app decía «sandbox: no cumple»."""
    objetivo = _objetivo(
        decision="stalled",
        revisiones=[_revision(feedback="Oráculo inválido: compara con otro valor")],
    )

    resultado = controles(objetivo, None)

    assert resultado["sandbox"] is None  # no corrió: ni cumple ni incumple
    assert resultado["aserciones"] is False  # esto sí se comprobó, y falló
    assert controles_no_ejecutados(objetivo) == ["sandbox"]


def test_rechazo_por_sintaxis_no_da_por_buenas_las_aserciones() -> None:
    objetivo = _objetivo(
        codigo="def test_uno(:\n",
        decision="stalled",
        revisiones=[_revision(feedback="SyntaxError: invalid syntax")],
    )

    resultado = controles(objetivo, None)

    assert resultado["sintaxis"] is False
    assert resultado["sandbox"] is None
    assert resultado["aserciones"] is None  # antes salía True sin haberse revisado
    assert controles_no_ejecutados(objetivo) == ["sandbox", "aserciones"]


def test_laundering_sigue_siendo_un_incumplimiento_de_aserciones() -> None:
    objetivo = _objetivo(
        decision="stalled",
        laundering_detectado=True,
        revisiones=[_revision(laundering_detectado=True, feedback="Se debilitó")],
    )

    resultado = controles(objetivo, None)

    assert resultado["aserciones"] is False
    assert resultado["sandbox"] is None
    assert controles_no_ejecutados(objetivo) == ["sandbox"]


def test_un_error_de_la_prueba_dentro_del_sandbox_si_incumple() -> None:
    """Si llegó a ejecutarse y falló al importar, el control del sandbox sí falla."""
    objetivo = _objetivo(
        decision="stalled",
        revisiones=[_revision(ejecucion=EJECUTADA, feedback="ImportError: x")],
    )

    assert controles(objetivo, None)["sandbox"] is False
    assert controles_no_ejecutados(objetivo) == []


def test_una_prueba_aprobada_no_tiene_controles_sin_ejecutar() -> None:
    objetivo = _objetivo(
        decision="accept",
        revisiones=[
            _revision(
                ejecucion=EJECUTADA,
                tipo_fallo=None,
                estado_sandbox="ok",
                decision="accept",
            )
        ],
    )

    resultado = controles(objetivo, None)

    assert resultado["sandbox"] is True
    assert resultado["aserciones"] is True
    assert controles_no_ejecutados(objetivo) == []


def _guardado(controles_guardados: dict, **cambios) -> dict:
    base = {
        "decision": "stalled",
        "critical": False,
        "controles": controles_guardados,
        "metricas": {
            "cobertura_lineas": None,
            "cobertura_ramas": None,
            "mutation_score": None,
        },
    }
    return {**base, **cambios}


def test_la_vista_distingue_no_ejecutado_de_no_cumple_y_de_sin_dato() -> None:
    objetivo = _guardado(
        {
            "sintaxis": True,
            "sandbox": None,
            "aserciones": False,
            "cobertura": None,
            "mutation": None,
        },
        controles_no_ejecutados=["sandbox"],
    )

    por_clave = {c["clave"]: c for c in _controles(objetivo, {})}

    assert por_clave["sandbox"]["estado"] == NO_EJECUTADO
    assert "antes de llegar al sandbox" in por_clave["sandbox"]["nota"]
    assert por_clave["aserciones"]["estado"] == "falla"
    assert por_clave["cobertura"]["estado"] == "sin_dato"
    # Sin laundering, lo que falló fue el oráculo: no se le llama anti-laundering.
    assert por_clave["aserciones"]["etiqueta"].startswith("Oráculo trazable")


def test_con_laundering_la_etiqueta_sigue_siendo_anti_laundering() -> None:
    objetivo = _guardado(
        {
            "sintaxis": True,
            "sandbox": None,
            "aserciones": False,
            "cobertura": None,
            "mutation": None,
        },
        controles_no_ejecutados=["sandbox"],
        laundering_detectado=True,
    )

    aserciones = _controles(objetivo, {})[2]

    assert aserciones["estado"] == "falla"
    assert "anti-laundering" in aserciones["etiqueta"]


def test_resultados_anteriores_sin_el_campo_siguen_como_sin_dato() -> None:
    objetivo = _guardado(
        {
            "sintaxis": True,
            "sandbox": None,
            "aserciones": None,
            "cobertura": None,
            "mutation": None,
        }
    )

    estados = [c["estado"] for c in _controles(objetivo, {})[:3]]

    assert estados == ["ok", "sin_dato", "sin_dato"]


def test_el_esquema_de_resultados_acepta_los_campos_nuevos() -> None:
    esquema = contracts.cargar_schema(contracts.RUN_LOG)
    propiedades = esquema["$defs"]["objetivo"]["properties"]

    assert set(propiedades["fase_fallo"]["enum"]) == {*TEXTO_FASE_FALLO, None}
    assert propiedades["controles_no_ejecutados"]["items"]["enum"] == [
        "sandbox",
        "aserciones",
    ]
