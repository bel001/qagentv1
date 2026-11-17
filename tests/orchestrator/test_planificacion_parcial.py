"""La spec vigente se completa con lo que falta, sin volver a planificar el módulo."""

from __future__ import annotations

from qagent.orchestrator.corrida_registro import _objetivos_de
from qagent.orchestrator.orquestador import modulo_con_faltantes

MODULO = {
    "ruta": "src/panel.tsx",
    "huella": "h",
    "funciones": [
        {"nombre": "sumar"},
        {"nombre": "restar"},
        {"nombre": "raiz_interna", "solo_integracion": True},
        {"nombre": "otra_interna", "solo_integracion": True},
    ],
    "endpoints": [
        {"objetivo": "GET /a", "manejador": "a"},
        {"objetivo": "GET /b", "manejador": "b"},
        {"manejador": "sin_ruta", "resuelta": False},
    ],
    "componentes": [{"nombre": "Boton"}, {"nombre": "Panel"}],
    "integraciones": [
        {"objetivo": "integracion_raiz_interna", "nombre": "raiz_interna"},
        {"objetivo": "integracion_otra_interna", "nombre": "otra_interna"},
    ],
}


def test_los_componentes_cuentan_como_objetivos_de_la_spec() -> None:
    assert _objetivos_de(MODULO) == {
        "sumar",
        "restar",
        "GET /a",
        "GET /b",
        "Boton",
        "Panel",
        "integracion_raiz_interna",
        "integracion_otra_interna",
    }


def test_el_modulo_parcial_solo_lleva_lo_que_falta() -> None:
    parcial = modulo_con_faltantes(MODULO, {"restar", "GET /b", "Panel"})

    assert [f["nombre"] for f in parcial["funciones"]] == ["restar"]
    assert [e["objetivo"] for e in parcial["endpoints"]] == ["GET /b"]
    assert [c["nombre"] for c in parcial["componentes"]] == ["Panel"]
    assert parcial["integraciones"] == []
    assert parcial["ruta"] == MODULO["ruta"]
    assert parcial["huella"] == MODULO["huella"]


def test_una_integracion_que_falta_trae_su_raiz_para_derivarla() -> None:
    parcial = modulo_con_faltantes(MODULO, {"integracion_raiz_interna"})

    assert [f["nombre"] for f in parcial["funciones"]] == ["raiz_interna"]
    assert [i["objetivo"] for i in parcial["integraciones"]] == [
        "integracion_raiz_interna"
    ]
    assert parcial["endpoints"] == []
    assert parcial["componentes"] == []


def test_el_modulo_original_no_se_modifica() -> None:
    antes = {clave: list(valor) for clave, valor in MODULO.items() if clave != "ruta"}
    modulo_con_faltantes(MODULO, {"sumar"})
    assert {c: list(v) for c, v in MODULO.items() if c != "ruta"} == antes
