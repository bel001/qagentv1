"""La Vista previa no llama a IA sin solicitud; la consulta explícita es asíncrona.

Con DeepSeek la recomendación tardaba ~25 s y la Vista previa no aparecía hasta que
respondía. Ahora se devuelve al momento con las reglas y la IA llega con un evento.
"""

from __future__ import annotations

import threading
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

pytest.importorskip("webview")

from qagent.app.desktop import DesktopAPI
from qagent.proyectos import vista_previa


def _proyecto(tmp_path: Path) -> Path:
    (tmp_path / "calc.py").write_text(
        'def sumar(a: int, b: int) -> int:\n    """Suma."""\n    return a + b\n',
        encoding="utf-8",
    )
    return tmp_path


def _api_con_eventos() -> tuple[DesktopAPI, list[tuple[str, dict]], threading.Event]:
    api = DesktopAPI()
    api.set_window(MagicMock())
    eventos: list[tuple[str, dict]] = []
    llego = threading.Event()

    def emitir(tipo: str, datos: dict) -> None:
        eventos.append((tipo, datos))
        llego.set()

    api.emit_event = emitir  # type: ignore[method-assign]
    return api, eventos, llego


def test_sin_ia_configurada_no_hay_hilo_ni_evento(tmp_path: Path) -> None:
    api, eventos, _ = _api_con_eventos()
    with patch.object(vista_previa, "recomendador_ia_configurado", return_value=None):
        res = api.obtener_vista_previa(str(_proyecto(tmp_path)))
    assert res["ok"]
    assert res["recomendacion"]["origen"] == "reglas"
    assert "recomendacion_ia_pendiente" not in res
    assert eventos == []


def test_con_ia_responde_con_reglas_y_la_ia_llega_por_evento(tmp_path: Path) -> None:
    api, eventos, llego = _api_con_eventos()
    soltar = threading.Event()
    ia = {"version": "1", "origen": "ia", "recomendaciones": []}

    def recomendar_lento(vista, raiz, recomendador):
        soltar.wait(5)  # la IA aún no respondió cuando vuelve obtener_vista_previa
        return {"recomendacion": ia, "proximamente": []}

    with (
        patch.object(
            vista_previa, "recomendador_ia_configurado", return_value=object()
        ),
        patch.object(vista_previa, "recomendar_con_ia_para_vista", recomendar_lento),
    ):
        res = api.obtener_vista_previa(str(_proyecto(tmp_path)), usar_ia=True)
        assert res["ok"]
        assert res["recomendacion"]["origen"] == "reglas"
        assert res["recomendacion_ia_pendiente"] is True
        assert eventos == []  # no se esperó a la IA
        soltar.set()
        assert llego.wait(5)

    tipo, datos = eventos[0]
    assert tipo == "recomendacion_ia"
    assert datos["ruta"] == res["ruta"]
    assert datos["recomendacion"] == ia


def test_si_la_ia_falla_el_evento_llega_igual_sin_recomendacion(tmp_path: Path) -> None:
    api, eventos, llego = _api_con_eventos()

    def falla(vista, raiz, recomendador):
        raise RuntimeError("sin red")

    with (
        patch.object(
            vista_previa, "recomendador_ia_configurado", return_value=object()
        ),
        patch.object(vista_previa, "recomendar_con_ia_para_vista", falla),
    ):
        res = api.obtener_vista_previa(str(_proyecto(tmp_path)), usar_ia=True)
        assert llego.wait(5)
    assert res["recomendacion"]["origen"] == "reglas"
    assert eventos[0][0] == "recomendacion_ia"
    assert "recomendacion" not in eventos[0][1]  # la interfaz se queda con las reglas


@pytest.mark.parametrize("opcion", [False, "true", None])
def test_abrir_proyecto_no_gasta_tokens_sin_solicitud_explicita(tmp_path, opcion):
    api, eventos, _ = _api_con_eventos()
    with patch.object(vista_previa, "recomendador_ia_configurado") as crear:
        crear.side_effect = AssertionError("No debe cargar ni llamar al cliente IA")
        res = api.obtener_vista_previa(str(_proyecto(tmp_path)), usar_ia=opcion)
    assert res["ok"]
    assert res["orientacion_pruebas"]["tokens"] == 0
    assert res["recomendacion"]["origen"] == "reglas"
    assert not eventos
    crear.assert_not_called()
