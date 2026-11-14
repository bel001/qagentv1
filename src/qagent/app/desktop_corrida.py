"""Métodos de la corrida en vivo del puente de escritorio."""

from __future__ import annotations

import logging
import threading
from typing import Any

from qagent.almacenamiento import BloqueoCorrida, recientes
from qagent.app import bitacora
from qagent.app.desktop_soporte import (
    DOCKER_RESPONDE,
    SEGUIMIENTO,
    _bloqueo_corrida,
    _reintentar_limpieza,
)
from qagent.app.monitor_eventos import a_evento_bitacora, a_fila_monitor
from qagent.storage.registro import (
    PERFIL_REGRESION_PROFUNDA,
    nombre_perfil,
)


def _desktop():
    """Módulo principal, para resolver helpers que las pruebas reemplazan."""
    from qagent.app import desktop

    return desktop


class CorridaMixin:
    """Iniciar y seguir una corrida, estado del sandbox y eventos."""

    @_bloqueo_corrida
    def start_run(
        self,
        folder_path: str,
        profile: str = "deep",
        seleccion: list[dict[str, Any]] | None = None,
        inferir: bool | None = None,
        revisar_inferidos: bool = False,
    ) -> dict:
        """Inicia la corrida del sistema sobre el proyecto seleccionado.

        ``inferir`` (#275, ADR-016) decide si se infiere el contrato de las funciones
        sin docstring (None usa ``[inferencia] activa``); con ``revisar_inferidos`` la
        corrida se detiene a que la persona acepte o descarte cada contrato inferido
        (evento ``revision_inferidos`` y ``responder_revision_inferidos``).

        Primero verifica que Docker responde (HU-13) y luego que el entorno completo
        esté listo: config.toml, claves de .env, Docker y Git (EN-06). Con la IA
        simulada (QAGENT_FAKE_LLM=1, en el sistema o en el .env) Docker es opcional.

        Si todo está listo, la corrida real (análisis → Planner → Generator → Reviewer
        en Docker → log.json/results.json) corre en un hilo y envía a la interfaz los
        eventos `corrida_evento` (una fila del Monitor) y, al terminar, `corrida_fin`
        (resumen). Con la IA simulada y sin Docker listo no hay dónde ejecutar las
        pruebas: la corrida queda en modo demostración y la pantalla usa sus datos de
        ejemplo.

        Returns:
            dict: ``{"status": "started", ..., "run_id", "modo"}`` con ``modo`` igual
            a ``"real"`` o ``"demostracion"`` (``run_id`` es None si el proyecto no
            tiene ``.qagent/``); si Docker no está disponible,
            ``{"status": "docker_no_disponible", "mensaje": str}``; si falta otra cosa
            del entorno, ``{"status": "blocked", "motivo": str, "problemas": list}``;
            si ya hay una corrida en curso, ``{"status": "en_curso", "mensaje": str}``.
            Una selección que no coincida con el AST devuelve
            ``{"status": "seleccion_invalida", "mensaje": str}``. Un proyecto de un
            lenguaje que aún no se soporta devuelve
            ``{"status": "lenguaje_no_soportado", "mensaje": str}`` (#168).
        """
        from qagent.config import modo_simulado
        from qagent.lenguajes import LenguajeNoSoportado, adaptador_del_proyecto
        from qagent.proyectos.seleccion import filtrar_modulos
        from qagent.sandbox import DockerNoDisponible, verificar_docker

        try:
            adaptador = adaptador_del_proyecto(folder_path)
        except LenguajeNoSoportado as exc:
            return {"status": "lenguaje_no_soportado", "mensaje": str(exc)}
        except OSError as exc:
            if seleccion is not None:
                return {"status": "seleccion_invalida", "mensaje": str(exc)}
            adaptador = None  # la corrida informa que la carpeta no existe
        if adaptador is not None and (
            motivo := adaptador.motivo_no_ejecutable(folder_path)
        ):
            return {"status": "blocked", "motivo": motivo, "problemas": [motivo]}
        if seleccion is not None and adaptador is not None:
            try:
                filtrar_modulos(adaptador.analizar(folder_path)["modulos"], seleccion)
            except (OSError, ValueError) as exc:
                return {"status": "seleccion_invalida", "mensaje": str(exc)}

        if profile == PERFIL_REGRESION_PROFUNDA:
            from qagent.orchestrator.regresion import funciones_criticas_repetibles

            if not funciones_criticas_repetibles(folder_path, seleccion):
                return {
                    "status": "perfil_no_disponible",
                    "mensaje": (
                        "La regresión profunda requiere al menos una función crítica "
                        "seleccionada con una prueba guardada válida."
                    ),
                }

        simulado = modo_simulado()
        es_regresion = self._es_regresion(profile)
        if es_regresion or not simulado:
            try:
                verificar_docker()
            except DockerNoDisponible as exc:
                bitacora.registro.warning("Corrida no iniciada: %s", exc)
                return {"status": "docker_no_disponible", "mensaje": str(exc)}

        if es_regresion:
            from qagent.config import carga as config_carga
            from qagent.config import verificar_entorno

            entorno = verificar_entorno(
                config_carga.RUTA_CONFIG,
                config_carga.RUTA_ENV,
                simulado=True,
                ruta_local=config_carga.RUTA_CONFIG_LOCAL,
            )
        else:
            entorno = self.verificar_entorno()
        if not entorno["listo"]:
            bitacora.registro.warning("Corrida no iniciada: %s", entorno["mensaje"])
            return {
                "status": "blocked",
                "motivo": entorno["mensaje"],
                "problemas": entorno["problemas"],
            }

        if self._corrida is not None and self._corrida.is_alive():
            return {
                "status": "en_curso",
                "mensaje": "Ya hay una corrida en curso: espera a que termine.",
            }

        modo = (
            "real"
            if es_regresion or not simulado or self._sandbox_listo()
            else "demostracion"
        )
        bitacora.registro.info(
            "Corrida iniciada en '%s' con perfil '%s' (%s)",
            folder_path,
            profile,
            "IA simulada" if simulado else "IA real",
        )
        if modo == "demostracion":
            bitacora.registro.info(
                "Docker no está listo: la pantalla muestra la demostración y no se "
                "ejecuta el pipeline."
            )
        self._cancelar_corrida.clear()
        imagen = None
        if modo == "real" and adaptador is not None:
            try:
                imagen = adaptador.entorno_sandbox(folder_path).imagen
            except Exception:  # noqa: BLE001
                imagen = None
        tipos = sorted(
            {
                tipo
                for entrada in (seleccion or [])
                for campo, tipo in (
                    ("funciones", "funcion"),
                    ("endpoints", "endpoint"),
                    ("componentes", "componente"),
                    ("integraciones", "integracion"),
                )
                if entrada.get(campo)
            }
        )
        run_id = _desktop()._registrar_run(
            folder_path,
            usa_docker=modo == "real",
            imagen_docker=imagen,
            tipos_prueba=tipos or None,
        )
        # Emite un evento hacia la interfaz JS, con el nombre del perfil para personas (#133)
        self.emit_event(
            "log", {"message": f"Corrida iniciada: {nombre_perfil(profile)}"}
        )
        if modo == "real":
            # Solo viajan las opciones de #275 que la persona cambió.
            extra: dict[str, Any] = {}
            if inferir is not None:
                extra["inferir"] = inferir
            if revisar_inferidos:
                extra["revisar_inferidos"] = True
            self._lanzar_corrida(
                folder_path, profile, run_id, simulado, seleccion, **extra
            )
        return {
            "status": "started",
            "folder": folder_path,
            "profile": profile,
            "run_id": run_id,
            "modo": modo,
        }

    def _sandbox_listo(self) -> bool:
        """True si Docker responde y la imagen base existe (se pueden ejecutar pruebas)."""
        try:
            from qagent.sandbox.estado import estado_docker
        except ImportError:
            return False
        return estado_docker()["estado"] == "ok"

    def _lanzar_corrida(
        self,
        ruta: str,
        perfil: str,
        run_id: str | None,
        simulado: bool,
        seleccion: list[dict[str, Any]] | None,
        *,
        inferir: bool | None = None,
        revisar_inferidos: bool = False,
    ) -> None:
        """Ejecuta la corrida en un hilo para no congelar la ventana.

        #139: antes toma el bloqueo de la corrida, que dice a otras ventanas (y a la
        próxima apertura del proyecto) que sigue viva; si la app se cierra, el sistema
        lo libera solo. El hilo lo suelta al terminar.
        """
        bloqueo = _desktop()._tomar_bloqueo(ruta, run_id)
        self._corrida = threading.Thread(
            target=self._correr_y_liberar,
            args=(ruta, perfil, run_id, simulado, seleccion, bloqueo),
            kwargs={
                clave: valor
                for clave, valor in (
                    ("inferir", inferir),
                    ("revisar_inferidos", revisar_inferidos),
                )
                if valor is not None and valor is not False
            },
            name="qagent-corrida",
            daemon=True,
        )
        self._corrida.start()

    def _correr_y_liberar(
        self,
        ruta: str,
        perfil: str,
        run_id: str | None,
        simulado: bool,
        seleccion: list[dict[str, Any]] | None,
        bloqueo: BloqueoCorrida | None,
        *,
        inferir: bool | None = None,
        revisar_inferidos: bool = False,
    ) -> None:
        """Corre la corrida y suelta su bloqueo al terminar, pase lo que pase (#139)."""
        try:
            if inferir is None and not revisar_inferidos:
                self._correr(ruta, perfil, run_id, simulado, seleccion)
            else:
                self._correr(
                    ruta,
                    perfil,
                    run_id,
                    simulado,
                    seleccion,
                    inferir=inferir,
                    revisar_inferidos=revisar_inferidos,
                )
        finally:
            if bloqueo is not None:
                bloqueo.liberar()
            _desktop()._limpiar_sandbox_tras_corrida()

    def _correr(
        self,
        ruta: str,
        perfil: str,
        run_id: str | None,
        simulado: bool,
        seleccion: list[dict[str, Any]] | None = None,
        *,
        inferir: bool | None = None,
        revisar_inferidos: bool = False,
    ) -> None:
        """Cuerpo del hilo: lee la configuración, corre el pipeline y avisa el final."""
        from qagent.config import carga as config_carga
        from qagent.config import cargar_configuracion
        from qagent.orchestrator.corrida import ResumenCorrida, ejecutar_corrida

        carga = cargar_configuracion(
            simulado=simulado, ruta_local=config_carga.RUTA_CONFIG_LOCAL
        )
        if carga.config is None:
            resumen = ResumenCorrida(
                run_id=run_id,
                estado="fallo_controlado",
                motivo="config.toml no es válido: " + "; ".join(carga.avisos),
                total_funciones=0,
            )
        else:
            import inspect

            opciones_corrida: dict[str, Any] = {
                "simulado": simulado,
                "al_evento": self._reenviar_evento,
                "run_id": run_id,
            }
            try:
                sig = inspect.signature(ejecutar_corrida)
                if "cancelado" in sig.parameters or any(
                    p.kind == inspect.Parameter.VAR_KEYWORD
                    for p in sig.parameters.values()
                ):
                    opciones_corrida["cancelado"] = self._cancelar_corrida.is_set
            except (ValueError, TypeError):
                opciones_corrida["cancelado"] = self._cancelar_corrida.is_set

            if seleccion is not None:
                opciones_corrida["seleccion"] = seleccion
            if inferir is not None:
                opciones_corrida["inferir"] = inferir
            if revisar_inferidos:
                opciones_corrida["revisor_inferidos"] = self._revisar_inferidos
            resumen = ejecutar_corrida(
                ruta,
                perfil,
                carga.config,
                carga.claves,
                **opciones_corrida,
            )
        nivel = logging.INFO if resumen.estado == "fin" else logging.WARNING
        bitacora.registro.log(
            nivel,
            "Corrida %s terminada (%s): %d aceptadas, %d bugs, %d estancadas, "
            "%d tokens, US$ %.4f%s",
            resumen.run_id or "sin registro",
            resumen.estado,
            resumen.aceptadas,
            resumen.bugs_detectados,
            resumen.estancadas,
            resumen.tokens,
            resumen.costo_usd,
            f" · {resumen.motivo}" if resumen.motivo else "",
        )
        if ruta:
            try:
                recientes.registrar_corrida(ruta)
            except OSError as exc:
                bitacora.registro.warning(
                    "No se pudo registrar la última corrida en recientes: %s", exc
                )
        self.emit_event("corrida_fin", resumen.a_dict())

    def _reenviar_evento(self, evento: dict) -> None:
        """Un evento del orquestador -> fila del Monitor y línea de la consola."""
        fila = a_fila_monitor(evento)
        if fila is None:
            return
        bitacora.registrar_evento(a_evento_bitacora(fila))
        self.emit_event("corrida_evento", fila)

    def estado_sandbox(self) -> dict:
        """Devuelve el estado del sandbox Docker para el indicador de la barra lateral.

        Returns:
            dict: `{"estado": "ok" | "sin_imagen" | "no_iniciado" | "no_instalado",
            "mensaje": str, "simulado": bool}`. `simulado` indica que la IA es simulada
            (QAGENT_FAKE_LLM=1): ahí no se ejecuta nada en el sandbox y Docker es
            opcional, así que la interfaz no debe presentar su ausencia como un fallo.
        """
        from qagent.config import modo_simulado

        try:
            from qagent.sandbox.estado import estado_docker
        except ImportError:
            estado = {
                "estado": "no_instalado",
                "mensaje": "Falta el SDK de Docker para Python: pip install -r requirements.txt",
            }
        else:
            estado = estado_docker()
        # La interfaz consulta esto cada 15 s y al volver a la ventana (#251).
        self._refrescar_estado_local(
            docker_responde=estado.get("estado") in DOCKER_RESPONDE
        )
        return {**estado, "simulado": modo_simulado()}

    def _corrida_en_curso(self) -> bool:
        """True si hay una corrida real ejecutándose en su hilo."""
        return self._corrida is not None and self._corrida.is_alive()

    def _refrescar_estado_local(self, docker_responde: bool = False) -> None:
        """Pone al día lo que el programa leyó una sola vez al abrir (#251).

        - `QAGENT_FAKE_LLM` del `.env` (caso 6), salvo durante una corrida.
        - Las claves que oculta la bitácora, si el `.env` cambió (caso 10).
        - La limpieza del sandbox que no pudo hacerse al abrir porque Docker no
          respondía (caso 11), solo si ahora responde y no hay una corrida.

        Solo actúa con la app abierta (`main` activa el seguimiento): las pruebas no
        tocan el entorno del proceso ni el Docker real.
        """
        if not SEGUIMIENTO.activo:
            return
        from qagent.config import carga as config_carga
        from qagent.config import refrescar_simulacion_desde_env

        corrida = self._corrida_en_curso()
        if not corrida:
            refrescar_simulacion_desde_env(config_carga.RUTA_ENV)
        _desktop()._refrescar_claves_si_cambio()
        if docker_responde and not corrida:
            _reintentar_limpieza()

    def registrar_evento(self, evento: dict) -> None:
        """Imprime en la consola de Python un paso de la corrida, con hora.

        La pantalla lo llama con cada evento del Monitor, de modo que la corrida se pueda
        seguir desde la terminal donde se abrió la aplicación. Nunca muestra claves.

        Args:
            evento: `{"tipo", "agente", "archivo", "funcion", "mensaje", "progreso"}`
                (todos opcionales; ver `qagent.app.bitacora.registrar_evento`).
        """
        bitacora.registrar_evento(evento)

    def emit_event(self, event_type: str, data: dict) -> None:
        """Envía un evento desde Python hacia la interfaz JavaScript.

        Args:
            event_type: Nombre del evento ('log', 'progress', etc.).
            data: Carga útil con la información del evento.
        """
        if self._window:
            # Invoca la función receptora definida en el window de JavaScript
            import json

            payload = json.dumps({"type": event_type, "data": data})
            try:
                self._window.evaluate_js(
                    f"window.onQAgentEvent && window.onQAgentEvent({payload});"
                )
            except Exception as exc:  # noqa: BLE001 — la ventana pudo cerrarse
                # Un hilo (corrida, clonado, verificación) puede seguir emitiendo
                # después de cerrar la ventana: WebView2 ya no existe y no hay a
                # quién avisar. No debe romper el hilo ni ensuciar la consola.
                bitacora.registro.debug(
                    "No se pudo enviar el evento '%s' a la interfaz: %s",
                    event_type,
                    exc,
                )
