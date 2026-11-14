"""Plazos de llamadas y registro único de respuestas, incluidas las tardías."""

from __future__ import annotations

import inspect
import threading
from collections.abc import Callable

from qagent.llm.cliente import ClienteLLMReal
from qagent.llm.modelos import ClienteLLM, RespuestaLLM


def generar_acotado(
    cliente: ClienteLLM,
    prompt: str,
    rol: str,
    tiempo_s: float,
    registrar: Callable[[RespuestaLLM], None],
) -> RespuestaLLM:
    """El transporte real cumple el plazo; los dobles se acotan sin perder consumo."""

    def llamar() -> RespuestaLLM:
        parametros = inspect.signature(cliente.generar).parameters
        opciones = {"timeout_s": tiempo_s, "plazo_total_s": tiempo_s}
        if not any(
            p.kind == inspect.Parameter.VAR_KEYWORD for p in parametros.values()
        ):
            opciones = {k: v for k, v in opciones.items() if k in parametros}
        respuesta = cliente.generar(prompt, rol=rol, **opciones)
        registrar(respuesta)
        return respuesta

    if isinstance(cliente, ClienteLLMReal):
        return llamar()  # Sin hilo abandonado ni una segunda llamada por TypeError.
    salida = {}

    def trabajo() -> None:
        try:
            salida["respuesta"] = llamar()
        except Exception as error:  # noqa: BLE001 -- se propaga en el hilo llamador
            salida["error"] = error

    hilo = threading.Thread(target=trabajo, name=f"qagent-{rol}", daemon=True)
    hilo.start()
    hilo.join(tiempo_s)
    if hilo.is_alive():
        raise TimeoutError(f"el LLM no respondió en {tiempo_s:g} s (tiempo agotado)")
    if "error" in salida:
        raise salida["error"]
    return salida["respuesta"]
