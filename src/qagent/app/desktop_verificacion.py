"""Métodos de verificación de corrección y cancelación del puente de escritorio."""

from __future__ import annotations

import threading
from typing import Any

from qagent.almacenamiento import AlmacenProyecto, BloqueoCorrida, recientes
from qagent.app import bitacora
from qagent.app.desktop_soporte import (
    _bloqueo_corrida,
)


def _desktop():
    """Módulo principal, para resolver helpers que las pruebas reemplazan."""
    from qagent.app import desktop

    return desktop


class VerificacionMixin:
    """Detener la corrida, revisar inferidos y reejecutar pruebas aprobadas."""

    def detener_corrida(self) -> dict:
        """Detiene de forma controlada la corrida en curso."""
        if self._corrida is not None and self._corrida.is_alive():
            self._cancelar_corrida.set()
            bitacora.registro.info("Solicitud de detención de corrida recibida.")
            return {"ok": True, "mensaje": "Deteniendo corrida de forma controlada..."}
        return {"ok": False, "mensaje": "No hay una corrida en ejecución."}

    def _revisar_inferidos(self, propuestas: list[dict[str, Any]]) -> set[str]:
        """Espera a que la persona revise los contratos inferidos (#275, ADR-016).

        Envía el evento ``revision_inferidos`` y bloquea el hilo de la corrida hasta que
        llegue ``responder_revision_inferidos`` o se detenga la corrida (en ese caso no
        se acepta nada).
        """
        self._revision_aceptados = set()
        evento = threading.Event()
        self._revision_evento = evento
        self.emit_event("revision_inferidos", {"propuestas": propuestas})
        while not evento.wait(0.5):
            if self._cancelar_corrida.is_set():
                self._revision_evento = None
                return set()
        self._revision_evento = None
        return set(self._revision_aceptados)

    def responder_revision_inferidos(self, aceptados: list[str]) -> dict:
        """Recibe de la interfaz los objetivos cuyo contrato inferido se acepta."""
        evento = self._revision_evento
        if evento is None or evento.is_set():
            return {
                "ok": False,
                "mensaje": "No hay una revisión de contratos pendiente.",
            }
        self._revision_aceptados = {str(n) for n in aceptados or []}
        evento.set()
        return {"ok": True}

    def tiene_pruebas_aprobadas(self, ruta: str) -> bool:
        """Habilita Regresion solo si hay pruebas aprobadas persistidas."""
        return AlmacenProyecto(ruta).tiene_pruebas_aprobadas()

    def pruebas_repetibles(self, ruta: str) -> list[dict[str, str]]:
        """Funciones y endpoints con prueba guardada que hoy se puede repetir (#70)."""
        from qagent.orchestrator.regresion import objetivos_repetibles

        try:
            return objetivos_repetibles(ruta)
        except OSError as error:
            bitacora.registro.warning("No se leyeron las pruebas guardadas: %s", error)
            return []

    @_bloqueo_corrida
    def verificar_correccion(self, ruta: str, run_origen_id: str) -> dict:
        """Inicia desde Historial una verificación determinista de la corrida elegida."""
        from qagent.almacenamiento import ErrorAlmacen
        from qagent.config import carga as config_carga
        from qagent.config import verificar_entorno
        from qagent.orchestrator.verificacion_correccion import (
            inspeccionar_verificacion,
        )
        from qagent.sandbox import DockerNoDisponible, verificar_docker

        if self._corrida is not None and self._corrida.is_alive():
            return {
                "status": "en_curso",
                "mensaje": "Ya hay una corrida en curso: espera a que termine.",
            }
        try:
            inspeccion = inspeccionar_verificacion(ruta, run_origen_id)
        except (OSError, ErrorAlmacen, ValueError) as error:
            return {"status": "no_verificable", "mensaje": str(error)}

        if inspeccion["ejecutables"]:
            try:
                verificar_docker()
            except DockerNoDisponible as error:
                return {"status": "docker_no_disponible", "mensaje": str(error)}

        entorno = verificar_entorno(
            config_carga.RUTA_CONFIG,
            config_carga.RUTA_ENV,
            simulado=True,
            ruta_local=config_carga.RUTA_CONFIG_LOCAL,
        )
        if not entorno["listo"]:
            return {
                "status": "blocked",
                "motivo": entorno["mensaje"],
                "problemas": entorno["problemas"],
            }

        self._cancelar_corrida.clear()
        imagen = None
        if inspeccion["ejecutables"]:
            try:
                from qagent.lenguajes import adaptador_del_proyecto

                imagen = adaptador_del_proyecto(ruta).entorno_sandbox().imagen
            except Exception:  # noqa: BLE001
                imagen = None
        run_id = _desktop()._registrar_run(
            ruta, usa_docker=bool(inspeccion["ejecutables"]), imagen_docker=imagen
        )
        if run_id is None:
            return {
                "status": "blocked",
                "motivo": "No se pudo registrar la corrida de verificación.",
            }
        bloqueo = _desktop()._tomar_bloqueo(ruta, run_id)
        self._corrida = threading.Thread(
            target=self._correr_verificacion_y_liberar,
            args=(ruta, run_origen_id, run_id, bloqueo),
            name="qagent-verificar-correccion",
            daemon=True,
        )
        self._corrida.start()
        self.emit_event(
            "log",
            {
                "message": (
                    f"Verificación de corrección iniciada desde {run_origen_id}; "
                    "se reutilizan las pruebas originales y no se usa IA"
                )
            },
        )
        return {
            "status": "started",
            "folder": ruta,
            "run_origen_id": run_origen_id,
            "run_id": run_id,
            "modo": "real",
            **inspeccion,
        }

    def _correr_verificacion_y_liberar(
        self,
        ruta: str,
        run_origen_id: str,
        run_id: str,
        bloqueo: BloqueoCorrida | None,
    ) -> None:
        """Ejecuta la verificación en segundo plano y libera su bloqueo."""
        try:
            from qagent.config import carga as config_carga
            from qagent.config import cargar_configuracion
            from qagent.orchestrator.corrida import ResumenCorrida
            from qagent.orchestrator.verificacion_correccion import (
                ejecutar_verificacion_correccion,
            )

            carga = cargar_configuracion(
                simulado=True, ruta_local=config_carga.RUTA_CONFIG_LOCAL
            )
            if carga.config is None:
                resumen = ResumenCorrida(
                    run_id,
                    "fallo_controlado",
                    "config.toml no es válido: " + "; ".join(carga.avisos),
                    0,
                )
            else:
                resumen = ejecutar_verificacion_correccion(
                    ruta,
                    run_origen_id,
                    carga.config,
                    al_evento=self._reenviar_evento,
                    run_id=run_id,
                    cancelado=self._cancelar_corrida.is_set,
                )
            try:
                recientes.registrar_corrida(ruta)
            except OSError as error:
                bitacora.registro.warning(
                    "No se pudo registrar la última corrida en recientes: %s", error
                )
            datos = resumen.a_dict()
            datos["run_origen_id"] = run_origen_id
            self.emit_event("corrida_fin", datos)
        finally:
            if bloqueo is not None:
                bloqueo.liberar()
            _desktop()._limpiar_sandbox_tras_corrida()
