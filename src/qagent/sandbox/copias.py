"""Instantánea de proyecto por corrida y restauración entre ejecuciones aisladas."""

from __future__ import annotations

import contextlib
import functools
import os
import shutil
import tempfile
import threading
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

_SESIONES: dict[Path, SesionProyecto] = {}
_CANDADO = threading.RLock()


def _firma(ruta: str) -> tuple[int, int, int]:
    """Tamaño y marcas de tiempo de un archivo, sin leer su contenido."""
    estado = os.lstat(ruta)
    return (estado.st_size, estado.st_mtime_ns, estado.st_ctime_ns)


def _sale_de_la_raiz(entrada: os.DirEntry[str], raiz_real: Path) -> bool:
    """Indica si una carpeta es una unión de directorio que apunta fuera de la copia.

    Una carpeta corriente no puede salir de la raíz desde la que se recorre; solo se
    resuelve la ruta (costoso en Windows) cuando es una unión o no se puede saber.
    """
    es_union = getattr(entrada, "is_junction", None)  # Python 3.12+
    if es_union is not None and not es_union():
        return False
    return not Path(entrada.path).resolve().is_relative_to(raiz_real)


def _entradas(raiz: Path) -> dict[str, tuple[str, Any]]:
    """Tipo y firma de cada entrada de `raiz`, por ruta relativa POSIX.

    De un archivo guarda `_firma` (tamaño y tiempos) y no un hash de su contenido:
    recorrer así un proyecto de miles de archivos cuesta décimas de segundo, y se
    hace antes de cada ejecución del sandbox.
    """
    resultado: dict[str, tuple[str, Any]] = {}
    raiz_real = raiz.resolve()
    pendientes: list[tuple[str, str]] = [(str(raiz), "")]
    while pendientes:
        carpeta, prefijo = pendientes.pop()
        with os.scandir(carpeta) as entradas:
            for entrada in entradas:
                relativa = prefijo + entrada.name
                if entrada.is_symlink():
                    resultado[relativa] = ("enlace", os.readlink(entrada.path))
                elif entrada.is_dir(follow_symlinks=False):
                    if _sale_de_la_raiz(entrada, raiz_real):
                        raise ValueError(
                            "La copia contiene una unión de directorio externa."
                        )
                    resultado[relativa] = ("directorio", None)
                    pendientes.append((entrada.path, relativa + "/"))
                elif entrada.is_file(follow_symlinks=False):
                    resultado[relativa] = ("archivo", _firma(entrada.path))
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

    Un archivo se da por modificado cuando cambia su firma (tamaño, fecha de
    modificación o de cambio/creación) respecto de la que tenía al restaurarlo. No se
    vuelve a calcular el hash de todo el proyecto antes de cada prueba: en un
    proyecto grande eso tardaba más que la prueba misma.
    """

    def __init__(self, raiz: Path) -> None:
        self.raiz = raiz
        self._temporal = tempfile.TemporaryDirectory(prefix="qagent-copias-")
        self.base = Path(self._temporal.name) / "base"
        self.trabajo = Path(self._temporal.name) / "trabajo"
        #: Entradas de la instantánea: ruta -> (tipo, destino del enlace o None).
        self._manifest: dict[str, tuple[str, Any]] | None = None
        #: Firma de cada archivo de la carpeta de trabajo tal como quedó restaurado.
        self._restaurado: dict[str, tuple[str, Any]] = {}
        self._lock = threading.Lock()

    @contextlib.contextmanager
    def prestar(self) -> Iterator[Path]:
        """Entrega una copia restaurada con uso exclusivo hasta terminar el sandbox."""
        from qagent.sandbox.ejecucion import copiar_proyecto

        with self._lock:
            if self._manifest is None:
                copiar_proyecto(self.raiz, self.base)
                self._manifest = {
                    nombre: (tipo, valor if tipo == "enlace" else None)
                    for nombre, (tipo, valor) in _entradas(self.base).items()
                }
                copiar_proyecto(self.base, self.trabajo)
                self._restaurado = _entradas(self.trabajo)
            else:
                self._restaurar(self._manifest)
            yield self.trabajo

    def _restaurar(self, manifest: dict[str, tuple[str, Any]]) -> None:
        """Deja la carpeta de trabajo igual que la instantánea."""
        actuales = _entradas(self.trabajo)
        for nombre in sorted(actuales, key=lambda n: n.count("/"), reverse=True):
            if nombre not in manifest or actuales[nombre][0] != manifest[nombre][0]:
                _quitar(self.trabajo / nombre)
                actuales.pop(nombre)
        for nombre, (tipo, valor) in manifest.items():
            destino = self.trabajo / nombre
            if tipo == "directorio":
                destino.mkdir(parents=True, exist_ok=True)
            elif tipo == "enlace":
                if actuales.get(nombre) != (tipo, valor):
                    destino.parent.mkdir(parents=True, exist_ok=True)
                    _quitar(destino)
                    destino.symlink_to(
                        valor, target_is_directory=(self.base / nombre).is_dir()
                    )
            elif actuales.get(nombre) != self._restaurado.get(nombre):
                destino.parent.mkdir(parents=True, exist_ok=True)
                _quitar(destino)
                shutil.copy2(self.base / nombre, destino)
                self._restaurado[nombre] = ("archivo", _firma(str(destino)))

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
