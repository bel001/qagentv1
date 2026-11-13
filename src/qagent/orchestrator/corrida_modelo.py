"""Estado y constantes de una corrida (EN-04, EN-05)."""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from concurrent.futures import Future
from concurrent.futures import TimeoutError as EsperaAgotada
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from qagent.llm.fabrica import FuenteClaves
from qagent.orchestrator.orquestador import FalloControlado, PlanModulo
from qagent.orchestrator.tiempos import segundos

AlEvento = Callable[[dict[str, Any]], None]


PrepararImagen = Callable[[Path], str]


FIN = "fin"


ENTORNO = "entorno"


ENTORNO_PREPARANDO = "preparando"


ENTORNO_AVANCE = "avance"


ENTORNO_LISTO = "listo"


ENTORNO_FALLO = "fallo"


ENTORNO_CANCELADO = "cancelado"


_registro = logging.getLogger("qagent.corrida")


FALLO = "fallo_controlado"


@dataclass
class ResumenCorrida:
    """Lo que la interfaz necesita saber cuando la corrida termina."""

    run_id: str | None
    estado: str
    motivo: str | None
    total_funciones: int
    aceptadas: int = 0
    bugs_detectados: int = 0
    estancadas: int = 0
    sin_veredicto: int = 0
    tokens: int = 0
    tokens_reales: int = 0
    tokens_estimados: int = 0
    costo_usd: float = 0.0
    carpeta: str | None = None
    duracion_s: float = 0.0
    requieren_corrida_nueva: int = 0
    inicio: str | None = None
    fin: str | None = None
    duracion_etapas: dict[str, float] = field(default_factory=dict)
    cancelada: bool = False
    total_seleccionados: int = 0
    total_elegibles: int = 0
    total_procesados: int = 0
    total_pendientes: int = 0
    tipo_terminacion: str = "completada"
    objetivos_omitidos: int = 0

    def a_dict(self) -> dict[str, Any]:
        """Versión serializable a JSON (evento `corrida_fin` de la interfaz)."""
        return asdict(self)


@dataclass
class _EntradaCorrida:
    """Resultado del análisis inicial que la corrida necesita para continuar."""

    adaptador: Any
    analisis: dict[str, Any]
    modulos: list[dict[str, Any]]
    version_python: str | None
    no_soportados: list[dict[str, Any]]
    fuera: list[dict[str, Any]]
    tipos: list[str]


@dataclass(frozen=True)
class _CorteRecursos:
    """Corte de la corrida por cancelación o presupuesto."""

    motivo: str
    tipo: str
    cancelada: bool = False


class ErrorCorrida(RuntimeError):
    """La corrida no puede seguir (motivo legible para la interfaz)."""


INTERVALO_ESPERA_ENTORNO_S = 0.2


class EntornoEnPreparacion:
    """Construye la imagen del sandbox en segundo plano mientras se planifica (#148).

    Usa un hilo daemon: si el usuario cancela o cierra la app mientras `docker build`
    sigue, el proceso no queda esperando a que termine.
    """

    def __init__(
        self,
        preparar: Callable[[], str],
        reloj: Callable[[], float] = time.monotonic,
    ) -> None:
        self._reloj = reloj
        #: Segundos que tomó preparar la imagen (etapa `entorno`).
        self.duracion_s = 0.0
        self._futuro: Future[str] = Future()
        threading.Thread(
            target=self._preparar, args=(preparar,), name="qagent-entorno", daemon=True
        ).start()

    def _preparar(self, preparar: Callable[[], str]) -> None:
        inicio = self._reloj()
        try:
            imagen = preparar()
        except BaseException as error:  # noqa: BLE001 — se relanza en `esperar`
            self.duracion_s = segundos(inicio, self._reloj())
            self._futuro.set_exception(error)
        else:
            self.duracion_s = segundos(inicio, self._reloj())
            self._futuro.set_result(imagen)

    def listo(self) -> bool:
        """True cuando la imagen está lista o su preparación falló."""
        return self._futuro.done()

    def esperar(self, cancelado: Callable[[], bool] | None = None) -> str | None:
        """Espera la imagen; None si el usuario cancela mientras tanto.

        Si la preparación falló, relanza su error.
        """
        while True:
            try:
                return self._futuro.result(timeout=INTERVALO_ESPERA_ENTORNO_S)
            except EsperaAgotada:
                if cancelado is not None and cancelado():
                    return None


class _ReviewerSinEntorno:
    """Reviewer provisional mientras se construye el entorno aislado (#148).

    La corrida lo reemplaza por el `ReviewerAgent` real antes de ejecutar un módulo;
    si se llegara a usar, el módulo termina en fallo controlado.
    """

    def revisar(self, *_args: Any) -> dict[str, Any]:
        raise FalloControlado("El entorno aislado todavía no está listo")


@dataclass
class _ModuloPreparado:
    """Plan de un módulo y lo que la corrida necesita para guardar su spec (#148)."""

    plan: PlanModulo
    accion: str
    plan_guardado: dict[str, Any] | None
    perfiles: dict[str, str]
    completos: dict[str, dict[str, Any]]


@dataclass(frozen=True)
class _ContextoIA:
    """Lo que el Explicador con IA (#166) necesita de la corrida además de la config."""

    claves: FuenteClaves | None
    simulado: bool
    cancelado: Callable[[], bool] | None = None
    #: Docstring de cada objetivo por `(modulo, objetivo)`, del análisis estático.
    docstrings: dict[tuple[str, str], str | None] = field(default_factory=dict)


def _texto_error(error: Exception) -> str:
    if isinstance(error, ErrorCorrida):
        return str(error)
    return f"{type(error).__name__}: {error}"
