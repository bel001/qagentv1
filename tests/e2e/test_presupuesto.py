"""Presupuesto de tiempo del humo E2E: entre 5 y 10 segundos, y que se pueda explicar.

El humo E2E no es una carga pesada: es «levanta la app, abre un par de rutas y mira
si hay contenido». Con la imagen ya construida, el tiempo se reparte entre arrancar
la aplicación del usuario, lanzar Chromium y visitar las rutas. Aquí se fija el
presupuesto (10 s por defecto), se registra el desglose y se falla rápido en vez de
esperar.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from qagent import contracts
from qagent.e2e import ejecucion
from qagent.e2e.deteccion import configuracion_declarada
from qagent.e2e.ejecucion import _complete_result, _run_container
from qagent.e2e.modelos import ConfiguracionE2E

RAIZ = Path(__file__).parents[2]
RUNNER = RAIZ / "src" / "qagent" / "sandbox" / "navegador" / "runner.mjs"


def _plan() -> dict[str, Any]:
    return {
        "version": "1",
        "language": "javascript",
        "framework": "express",
        "adapter": "JavaScriptAdapter",
        "start_command": ["node", "server.js"],
        "port": 4173,
        "routes": [
            {
                "path": "/",
                "source": "server.js:1",
                "route_type": "page",
                "eligible": True,
                "reason": None,
            }
        ],
    }


def test_el_presupuesto_por_defecto_cabe_en_diez_segundos() -> None:
    config = ConfiguracionE2E()

    assert config.budget_s == 10
    assert config.max_routes == 10
    assert config.settle_ms == 150
    assert config.startup_timeout_s == 10
    assert config.route_timeout_s == 5
    config.validate()


@pytest.mark.parametrize("valor", [0, -1, 901])
def test_un_presupuesto_absurdo_se_rechaza(valor: int) -> None:
    with pytest.raises(ValueError, match="presupuesto"):
        ConfiguracionE2E(budget_s=valor).validate()


def test_el_proyecto_puede_declarar_su_presupuesto(tmp_path: Path) -> None:
    (tmp_path / ".qagent").mkdir()
    (tmp_path / ".qagent" / "e2e.json").write_text(
        json.dumps({"limits": {"budget_s": 20, "max_routes": 5}}), encoding="utf-8"
    )

    config = configuracion_declarada(tmp_path)

    assert config.budget_s == 20
    assert config.max_routes == 5


def test_el_contenedor_se_limita_al_presupuesto(tmp_path: Path, monkeypatch) -> None:
    """El límite duro del contenedor es el menor entre el tope y el presupuesto."""
    vistos: list[Any] = []

    def falso_ejecutar(imagen, comando, proyecto, tests, limites, **opciones):
        vistos.append(limites)
        raise RuntimeError("no se ejecuta nada en esta prueba")

    monkeypatch.setattr(ejecucion, "ejecutar_en_sandbox", falso_ejecutar)

    with pytest.raises(RuntimeError):
        _run_container(
            tmp_path,
            tmp_path,
            _plan(),
            ConfiguracionE2E(budget_s=8, total_timeout_s=60),
            "qagent-sandbox:navegador",
            None,
        )

    assert vistos[0].timeout_s == 8

    vistos.clear()
    with pytest.raises(RuntimeError):
        _run_container(
            tmp_path,
            tmp_path,
            _plan(),
            ConfiguracionE2E(budget_s=30, total_timeout_s=12),
            "qagent-sandbox:navegador",
            None,
        )

    assert vistos[0].timeout_s == 12


def test_el_resultado_lleva_el_presupuesto_y_el_desglose() -> None:
    raw = {
        "version": "1",
        "status": "cumple",
        "startup": {
            "ready": True,
            "exit_code": None,
            "port": 4173,
            "timeout_ms": 10000,
            "log": "",
            "reason": None,
        },
        "routes": [],
        "timing": {
            "startup_ms": 300,
            "browser_ms": 400,
            "routes_ms": 500,
            "total_ms": 1200,
        },
        "duration_s": 1.2,
    }

    resultado = _complete_result(
        "20261111-120000-abcd",
        _plan(),
        ConfiguracionE2E(),
        "qagent-sandbox:navegador",
        raw,
        None,
        1.5,
    )

    assert resultado["limits"]["budget_s"] == 10
    assert resultado["timing"] == {
        "startup_ms": 300,
        "browser_ms": 400,
        "routes_ms": 500,
        "total_ms": 1200,
    }
    contracts.validar_versionado(contracts.FAMILIA_E2E_RESULT, resultado)


def test_el_runner_arranca_rapido_y_respeta_el_presupuesto() -> None:
    runner = RUNNER.read_text(encoding="utf-8")

    # Chromium sin sandbox (el contenedor va con cap_drop=ALL) y con menos procesos.
    assert "'--no-sandbox'" in runner
    assert "'--disable-dev-shm-usage'" in runner
    assert "'--disable-background-networking'" in runner
    # La espera es activa (contenido), no una espera fija por ruta.
    assert "esperarContenido" in runner
    assert "page.waitForTimeout(plan.settle_ms)" not in runner
    # Si se agota el presupuesto, se dice y se sigue.
    assert "budget_ms" in runner
    assert "Se agotó el presupuesto" in runner
    # El desglose del tiempo se devuelve.
    assert "startup_ms" in runner and "browser_ms" in runner
