"""Vigilancia de escrituras de los bind mounts mientras se ejecuta el sandbox."""

from __future__ import annotations

import contextlib
import shutil
import threading
import time
from pathlib import Path
from typing import Any

from docker.errors import APIError
from requests.exceptions import RequestException

from qagent.recursos import tamano_carpeta

MAX_BYTES_ESCRITURA = 2 * 1024**3
RESERVA_DISCO_BYTES = 512 * 1024**2
#: Cada cuánto se revisa el espacio libre del disco (una consulta, sin recorrer nada).
INTERVALO_S = 0.1
#: Medir lo escrito recorre las carpetas montadas: en un proyecto grande tarda, así
#: que entre dos mediciones se espera varias veces lo que tardó la anterior.
PAUSAS_POR_MEDICION = 4
#: Tope de esa espera, para que el límite de escritura se siga aplicando a tiempo.
INTERVALO_MAXIMO_MEDICION_S = 2.0


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
        if total <= self.max_bytes and self._hay_reserva():
            return True
        return self._cortar()

    def _hay_reserva(self) -> bool:
        """Si el disco del host conserva la reserva de espacio libre."""
        return shutil.disk_usage(self.carpetas[0]).free >= RESERVA_DISCO_BYTES

    def _cortar(self) -> bool:
        self.motivo = (
            "El sandbox superó su límite de disco o la reserva de espacio libre."
        )
        with contextlib.suppress(APIError, RequestException):
            self.contenedor.kill()
        return False

    def _vigilar(self) -> None:
        proxima_medicion = 0.0
        while not self._fin.wait(INTERVALO_S):
            if time.monotonic() < proxima_medicion:
                if not self._hay_reserva():
                    self._cortar()
                    return
                continue
            inicio = time.monotonic()
            if not self.comprobar():
                return
            fin = time.monotonic()
            proxima_medicion = fin + min(
                (fin - inicio) * PAUSAS_POR_MEDICION, INTERVALO_MAXIMO_MEDICION_S
            )

    def __exit__(self, *_args: object) -> None:
        self._fin.set()
        self._hilo.join(timeout=2)
