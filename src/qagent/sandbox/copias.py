"""Instantánea de proyecto por corrida y restauración entre ejecuciones aisladas."""

from __future__ import annotations

import contextlib
import functools
import hashlib
import os
import shutil
import tempfile
import threading
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

_SESIONES: dict[Path, SesionProyecto] = {}
_CANDADO = threading.RLock()


def _huella(archivo: Path) -> bytes:
    resumen = hashlib.sha256()
    with archivo.open("rb") as flujo:
        for bloque in iter(lambda: flujo.read(65536), b""):
            resumen.update(bloque)
    return resumen.digest()


def _entradas(raiz: Path) -> dict[str, tuple[str, Any]]:
    resultado = {}
    for carpeta, directorios, archivos in os.walk(raiz, followlinks=False):
        for nombre in [*directorios, *archivos]:
            ruta = Path(carpeta) / nombre
            relativa = ruta.relative_to(raiz).as_posix()
            if ruta.is_symlink():
                resultado[relativa] = ("enlace", os.readlink(ruta))
            elif ruta.is_dir():
                if not ruta.resolve().is_relative_to(raiz.resolve()):
                    raise ValueError(
                        "La copia contiene una unión de directorio externa."
                    )
                resultado[relativa] = ("directorio", None)
            elif ruta.is_file():
                resultado[relativa] = ("archivo", _huella(ruta))
    return resultado


def _quitar(ruta: Path) -> None:
    if ruta.is_symlink():
        ruta.unlink()
    elif ruta.is_dir():
        shutil.rmtree(ruta)
    elif ruta.exists():
        ruta.unlink()


class SesionProyecto:
    """Conserva una instantánea y restaura solo los archivos modificados por cada test.

    La instantánea nunca se monta en Docker; cada ejecución recibe la carpeta de
    trabajo restaurada, sin compartir escrituras con la siguiente ejecución.
    """

    def __init__(self, raiz: Path) -> None:
        self.raiz = raiz
        self._temporal = tempfile.TemporaryDirectory(prefix="qagent-copias-")
        self.base = Path(self._temporal.name) / "base"
        self.trabajo = Path(self._temporal.name) / "trabajo"
        self._manifest: dict[str, tuple[str, Any]] | None = None
        self._lock = threading.Lock()

    @contextlib.contextmanager
    def prestar(self) -> Iterator[Path]:
        """Entrega una copia restaurada con uso exclusivo hasta terminar el sandbox."""
        from qagent.sandbox.ejecucion import copiar_proyecto

        with self._lock:
            if self._manifest is None:
                copiar_proyecto(self.raiz, self.base)
                self._manifest = _entradas(self.base)
                copiar_proyecto(self.base, self.trabajo)
            else:
                actuales = _entradas(self.trabajo)
                for nombre in sorted(
                    actuales, key=lambda n: n.count("/"), reverse=True
                ):
                    if (
                        nombre not in self._manifest
                        or actuales[nombre][0] != self._manifest[nombre][0]
                    ):
                        _quitar(self.trabajo / nombre)
                for nombre, (tipo, valor) in self._manifest.items():
                    destino = self.trabajo / nombre
                    if tipo == "directorio":
                        destino.mkdir(parents=True, exist_ok=True)
                    elif actuales.get(nombre) != (tipo, valor):
                        destino.parent.mkdir(parents=True, exist_ok=True)
                        _quitar(destino)
                        if tipo == "enlace":
                            destino.symlink_to(
                                valor, target_is_directory=(self.base / nombre).is_dir()
                            )
                        else:
                            shutil.copy2(self.base / nombre, destino)
            yield self.trabajo

    def cerrar(self) -> None:
        """Elimina las carpetas temporales al terminar la corrida."""
        with self._lock:
            self._temporal.cleanup()


def sesion_actual(raiz: Path) -> SesionProyecto | None:
    """Obtiene la sesión compartida por los hilos de agentes de esa corrida."""
    with _CANDADO:
        return _SESIONES.get(raiz.resolve())


def con_sesion_de_copias(funcion: Callable[..., Any]) -> Callable[..., Any]:
    """Mantiene las copias durante la corrida, incluyendo su modo de regresión."""

    @functools.wraps(funcion)
    def ejecutar(ruta_proyecto, *args, **kwargs):
        raiz = Path(ruta_proyecto).resolve()
        with _CANDADO:
            if raiz in _SESIONES:
                raise ValueError("Ya hay una corrida usando la copia de este proyecto.")
            sesion = SesionProyecto(raiz)
            _SESIONES[raiz] = sesion
        try:
            return funcion(ruta_proyecto, *args, **kwargs)
        finally:
            with _CANDADO:
                _SESIONES.pop(raiz, None)
            sesion.cerrar()

    return ejecutar
