"""Vigilancia de escrituras de los bind mounts mientras se ejecuta el sandbox."""

from __future__ import annotations

import contextlib
import shutil
import threading
from pathlib import Path
from typing import Any

from docker.errors import APIError
from requests.exceptions import RequestException

from qagent.recursos import tamano_carpeta

MAX_BYTES_ESCRITURA = 2 * 1024**3
RESERVA_DISCO_BYTES = 512 * 1024**2


class VigilanciaDisco:
    """Mata el contenedor al superar el presupuesto o la reserva del disco host."""

    def __init__(
        self,
        contenedor: Any,
        carpetas: list[Path],
        max_bytes: int = MAX_BYTES_ESCRITURA,
    ) -> None:
        self.contenedor = contenedor
        self.carpetas = carpetas
        self.max_bytes = max_bytes
        self.motivo: str | None = None
        self._fin = threading.Event()
        self._hilo = threading.Thread(
            target=self._vigilar, name="qagent-disco-sandbox", daemon=True
        )

    def __enter__(self) -> VigilanciaDisco:  # noqa: PYI034 -- compatible con Python 3.10 sin typing_extensions
        self._hilo.start()
        return self

    def comprobar(self) -> bool:
        """Devuelve False y corta la ejecución si el espacio ya no es seguro."""
        total = sum(tamano_carpeta(p, self.max_bytes) for p in self.carpetas)
        libre = shutil.disk_usage(self.carpetas[0]).free
        if total <= self.max_bytes and libre >= RESERVA_DISCO_BYTES:
            return True
        self.motivo = (
            "El sandbox superó su límite de disco o la reserva de espacio libre."
        )
        with contextlib.suppress(APIError, RequestException):
            self.contenedor.kill()
        return False

    def _vigilar(self) -> None:
        while not self._fin.wait(0.1):
            if not self.comprobar():
                return

    def __exit__(self, *_args: object) -> None:
        self._fin.set()
        self._hilo.join(timeout=2)
