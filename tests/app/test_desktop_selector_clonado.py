"""Selector nativo usado por el destino del clonado."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

webview = pytest.importorskip("webview")

from qagent.app.desktop import DesktopAPI
from qagent.app.desktop_proyectos import _DIALOGO_CARPETA


def test_select_folder_abre_dialogo_nativo_y_devuelve_la_carpeta(tmp_path) -> None:
    window = MagicMock()
    window.create_file_dialog.return_value = [str(tmp_path)]
    api = DesktopAPI()
    api.set_window(window)

    assert api.select_folder() == str(tmp_path)
    window.create_file_dialog.assert_called_once_with(_DIALOGO_CARPETA)
    assert _DIALOGO_CARPETA == 20  # el valor de FOLDER_DIALOG en pywebview 5 y 6


def test_select_folder_cancelado_no_modifica_un_destino() -> None:
    window = MagicMock()
    window.create_file_dialog.return_value = None
    api = DesktopAPI()
    api.set_window(window)

    assert api.select_folder() is None


def test_un_evento_con_la_ventana_cerrada_no_rompe_el_hilo() -> None:
    """Al cerrar la ventana WebView2 se destruye; emitir después no debe lanzar."""
    window = MagicMock()
    window.evaluate_js.side_effect = RuntimeError("objeto desechado: WebView2")
    api = DesktopAPI()
    api.set_window(window)

    api.emit_event("log", {"msg": "tarde"})  # no lanza
    window.evaluate_js.assert_called_once()
