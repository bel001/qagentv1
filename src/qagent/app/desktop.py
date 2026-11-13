"""Módulo principal de la aplicación de escritorio con pywebview.

La interfaz pública (`DesktopAPI`, `ejecutar`) se conserva; los métodos viven en
mixins por responsabilidad y los helpers en `desktop_soporte`.
"""

from __future__ import annotations

import logging
import sys
import threading
from pathlib import Path
from typing import Any

import webview

from qagent.almacenamiento import AlmacenProyecto, BloqueoCorrida, recientes
from qagent.app import bitacora
from qagent.app.desktop_configuracion import ConfiguracionMixin
from qagent.app.desktop_corrida import CorridaMixin
from qagent.app.desktop_informes import InformesMixin
from qagent.app.desktop_proyectos import ProyectosMixin
from qagent.app.desktop_soporte import (
    _LIBERANDO_ESPACIO,
    DOCKER_RESPONDE,
    SEGUIMIENTO,
    _bloqueo_corrida,
    _corridas_al_abrir,
    _firma_env,
    _limpiar_sandbox,
    _limpiar_sandbox_tras_corrida,
    _mostrar_en_explorador,
    _ocultar_claves_en_bitacora,
    _preparar_almacen,
    _refrescar_claves_si_cambio,
    _registrar_estado_configuracion,
    _registrar_run,
    _reintentar_limpieza,
    _resolver_ruta_proyecto,
    _Seguimiento,
    _texto_tamano,
    _tomar_bloqueo,
)
from qagent.app.desktop_verificacion import VerificacionMixin
from qagent.app.monitor_eventos import a_evento_bitacora, a_fila_monitor
from qagent.proyectos import proyecto_local
from qagent.storage.registro import (
    PERFIL_REGRESION_PROFUNDA,
    PERFILES_REGRESION,
    nombre_perfil,
)

# Interfaz web (HTML/CSS/JS), separada del backend e instalada con el paquete: qagent/frontend/
FRONTEND_DIR = Path(__file__).resolve().parents[1] / "frontend"

# Se conservan todos los nombres que antes vivían aquí: pruebas y app los importan.
__all__ = [
    "DOCKER_RESPONDE",
    "FRONTEND_DIR",
    "PERFILES_REGRESION",
    "PERFIL_REGRESION_PROFUNDA",
    "SEGUIMIENTO",
    "_LIBERANDO_ESPACIO",
    "AlmacenProyecto",
    "Any",
    "BloqueoCorrida",
    "DesktopAPI",
    "Path",
    "_Seguimiento",
    "_bloqueo_corrida",
    "_corridas_al_abrir",
    "_firma_env",
    "_limpiar_sandbox",
    "_limpiar_sandbox_tras_corrida",
    "_mostrar_en_explorador",
    "_ocultar_claves_en_bitacora",
    "_preparar_almacen",
    "_refrescar_claves_si_cambio",
    "_registrar_estado_configuracion",
    "_registrar_run",
    "_reintentar_limpieza",
    "_resolver_ruta_proyecto",
    "_texto_tamano",
    "_tomar_bloqueo",
    "a_evento_bitacora",
    "a_fila_monitor",
    "bitacora",
    "ejecutar",
    "logging",
    "main",
    "nombre_perfil",
    "proyecto_local",
    "recientes",
    "sys",
    "threading",
    "webview",
]


class DesktopAPI(
    ProyectosMixin,
    ConfiguracionMixin,
    InformesMixin,
    VerificacionMixin,
    CorridaMixin,
):
    """Puente de comunicación entre la interfaz JS y el backend Python."""

    def __init__(self) -> None:
        self._window: webview.Window | None = None
        self._corrida: threading.Thread | None = None  # corrida real en curso
        self._corrida_lock = threading.Lock()  # evita dos inicios simultáneos (A3)
        self._cancelar_corrida = threading.Event()
        # #275 (ADR-016): la corrida espera aquí a que la persona revise los contratos
        # inferidos; `responder_revision_inferidos` la despierta.
        self._revision_evento: threading.Event | None = None
        self._revision_aceptados: set[str] = set()

    def set_window(self, window: webview.Window) -> None:
        """Asigna la instancia de la ventana activa."""
        self._window = window

    def _es_regresion(self, profile: str) -> bool:
        """True si el perfil repite pruebas aprobadas sin IA (#70)."""
        es_regresion = profile in PERFILES_REGRESION  # reg y reg_deep: sin IA
        return es_regresion


def main() -> None:
    """Abre la aplicación de escritorio."""
    from qagent.config.carga import migrar_desde_repositorio

    # Orden importante: ~/.pyagent/ solo se renombra si ~/.qagent/ aún no existe, y
    # mover el .env la crearía. La configuración se lee después de las dos migraciones.
    if recientes.migrar_carpeta_anterior():
        bitacora.registro.info(
            "Se migró ~/.pyagent/ a ~/.qagent/ (proyectos recientes)."
        )
    for nombre in migrar_desde_repositorio():
        bitacora.registro.info(
            "Se movió %s de la carpeta del código a ~/.qagent/.", nombre
        )
    _registrar_estado_configuracion()
    # #251: desde aquí la app vigila el .env y reintenta la limpieza si Docker no estaba.
    SEGUIMIENTO.activo = True
    SEGUIMIENTO.firma_env = _firma_env()
    SEGUIMIENTO.limpieza = "pendiente"
    _reintentar_limpieza()
    # Se carga como file:// y no como ruta: con una ruta, pywebview sirve la carpeta con un servidor
    # HTTP interno cuya cola admite 5 conexiones, y al abrir la ventana (decenas de CSS, JS y fuentes
    # a la vez) rechaza algunas peticiones al azar y la interfaz queda sin estilos o sin scripts.
    url = (FRONTEND_DIR / "index.html").as_uri()

    api = DesktopAPI()

    window = webview.create_window(
        title="QAgent — Autonomous Test Engine",
        url=url,
        js_api=api,
        width=1400,
        height=900,
        min_size=(960, 600),
    )

    api.set_window(window)
    # Herramientas de desarrollo solo al programar, nunca en el ejecutable (TA-06).
    webview.start(debug=not getattr(sys, "frozen", False))


def ejecutar(argv: list[str] | None = None) -> None:
    """Comando `qagent` (y `python -m qagent`): atiende `--version` y abre la app."""
    import argparse

    from qagent import __version__

    parser = argparse.ArgumentParser(
        prog="qagent", description="Abre la aplicación de escritorio de QAgent."
    )
    parser.add_argument("--version", action="version", version=f"QAgent {__version__}")
    parser.parse_args(argv)
    main()


if __name__ == "__main__":
    main()
