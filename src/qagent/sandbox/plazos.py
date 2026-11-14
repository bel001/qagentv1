"""Consumo de un stream con plazo total, incluso cuando deja de producir datos."""

from __future__ import annotations

import contextlib
import queue
import threading
import time
from collections.abc import Callable, Iterable, Iterator
from typing import Any


def iterar_con_plazo(
    abrir: Callable[[], Iterable[Any]], segundos: float
) -> Iterator[Any]:
    """Acota la apertura y cada lectura; cierra el stream al salir o cancelar."""
    eventos = queue.Queue(maxsize=16)
    fin = threading.Event()
    flujo = []

    def publicar(evento) -> bool:
        while not fin.is_set():
            try:
                eventos.put(evento, timeout=0.05)
                return True
            except queue.Full:
                pass
        return False

    def leer() -> None:
        try:
            fuente = abrir()
            flujo.append(fuente)
            for elemento in fuente:
                if not publicar(("dato", elemento)):
                    break
            publicar(("fin", None))
        except Exception as error:  # noqa: BLE001 -- se propaga al consumidor
            publicar(("error", error))

    hilo = threading.Thread(target=leer, name="qagent-stream-build", daemon=True)
    plazo = time.monotonic() + segundos
    hilo.start()
    try:
        while True:
            restante = plazo - time.monotonic()
            if restante <= 0:
                raise TimeoutError("La construcción superó el plazo total.")
            try:
                tipo, dato = eventos.get(timeout=restante)
            except queue.Empty as error:
                raise TimeoutError("La construcción dejó de responder.") from error
            if tipo == "fin":
                return
            if tipo == "error":
                raise dato
            yield dato
    finally:
        fin.set()
        if flujo:
            with contextlib.suppress(ValueError, OSError, RuntimeError):
                cerrar = getattr(flujo[0], "close", None)
                if cerrar:
                    cerrar()
