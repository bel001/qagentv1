"""Métodos de proyectos y vista previa del puente de escritorio."""

from __future__ import annotations

from pathlib import Path

import webview

from qagent.almacenamiento import AlmacenProyecto, recientes
from qagent.app import bitacora
from qagent.app.desktop_soporte import (
    _bloqueo_corrida,
    _corridas_al_abrir,
    _preparar_almacen,
)
from qagent.proyectos import proyecto_local

#: Selector nativo de carpetas. pywebview 6 avisa que ``FOLDER_DIALOG`` está obsoleto
#: y lo quitará; ``FileDialog.FOLDER`` es el mismo valor y existe desde pywebview 5.
_DIALOGO_CARPETA = (
    webview.FileDialog.FOLDER
    if hasattr(webview, "FileDialog")
    else webview.FOLDER_DIALOG
)


def _ruta_de_clon_previo(url: str) -> str | None:
    """Carpeta donde ya se clonó ese repositorio, si sigue en el equipo.

    Se mira en Proyectos recientes: si el usuario ya lo clonó antes (aunque fuera en
    otra carpeta), QAgent abre esa copia en vez de volver a descargarla.
    """
    from qagent.proyectos import clonador

    try:
        entradas = recientes.listar()
    except OSError:
        return None
    identidad = clonador.identidad_repositorio(url)
    for entrada in entradas:
        url_previa = entrada.get("url")
        if not url_previa or not entrada.get("encontrada"):
            continue
        if clonador.identidad_repositorio(url_previa) == identidad:
            return str(entrada["ruta"])
    return None


class ProyectosMixin:
    """Abrir, clonar y recordar proyectos; vista previa y selección de objetivos."""

    def select_folder(self) -> str | None:
        """Abre el diálogo nativo del sistema operativo para seleccionar una carpeta.

        Returns:
            str | None: Ruta absoluta de la carpeta seleccionada, o None si se canceló.
        """
        if not self._window:
            return None

        # Selector de carpetas nativo (Windows/Linux/Mac)
        result = self._window.create_file_dialog(_DIALOGO_CARPETA)
        if result and len(result) > 0:
            folder_path = result[0]
            bitacora.registro.info("Carpeta seleccionada: %s", folder_path)
            return folder_path
        return None

    def destino_clonado(self, url: str) -> dict:
        """Valida la URL y propone la carpeta destino del clonado (HU-02).

        Si el repositorio ya está en el equipo —en la carpeta de destino o en
        cualquier otra donde ya se clonó— lo dice (``ya_clonado``): al confirmar,
        QAgent abre el que ya está en vez de volver a descargarlo.

        Returns:
            dict: ``{"ok": bool, "destino": str, "formato": str, "estado": str,
            "ya_clonado": bool}``.
        """
        from qagent.proyectos import clonador

        if not clonador.validar_url(url):
            return {"ok": False, "destino": "", "formato": clonador.FORMATO_URL}
        destino = clonador.destino_por_defecto(url)
        estado = clonador.estado_destino(destino, url)
        if estado != "ya_clonado":
            # Quizá ya se clonó antes en otra carpeta: se apunta a esa.
            previa = _ruta_de_clon_previo(url)
            if previa is not None:
                destino = Path(previa)
                estado = "ya_clonado"
        return {
            "ok": True,
            "destino": str(destino),
            "formato": clonador.FORMATO_URL,
            "estado": estado,
            "ya_clonado": estado == "ya_clonado",
        }

    @_bloqueo_corrida
    def clonar_repositorio(
        self, url: str, rama: str, destino: str, superficial: bool = True
    ) -> dict:
        """Inicia ``git clone`` en un hilo para no bloquear la interfaz (HU-02).

        El avance llega a la interfaz con eventos ``clonado_avance`` y el final con
        ``clonado_fin`` (el resultado de ``clonador.clonar``).

        Returns:
            dict: ``{"iniciado": True}``.
        """
        import threading
        from dataclasses import asdict

        from qagent.proyectos import clonador

        if self._clonando:
            return {"iniciado": False, "mensaje": "Ya hay un clonado en curso."}
        self._clonando = True
        self._cancelar_clonado.clear()

        def avanzar(porcentaje: int | None, linea: str) -> None:
            self.emit_event(
                "clonado_avance", {"porcentaje": porcentaje, "linea": linea}
            )

        def trabajo() -> None:
            resultado = clonador.clonar(
                url,
                rama,
                destino,
                superficial,
                al_avanzar=avanzar,
                cancelado=self._cancelar_clonado.is_set,
            )
            # Si el repositorio ya estaba clonado, no se descarga otra vez: se abre
            # el que hay (y no se toca nada de lo que hay dentro).
            ya_clonado = resultado.ya_clonado
            carpeta = Path(resultado.destino)
            if (
                (resultado.ok or ya_clonado)
                and carpeta.is_dir()
                and any(carpeta.iterdir())
            ):
                import shutil

                inspeccion = proyecto_local.inspeccionar_carpeta(carpeta)
                if not inspeccion["ok"]:
                    if ya_clonado:
                        # Ya estaba clonado: se informa, pero no se borra nada.
                        self.emit_event(
                            "clonado_fin",
                            {
                                "ok": False,
                                "destino": resultado.destino,
                                "tipo_error": "incompatibilidad_lenguaje",
                                "error": inspeccion["error"],
                            },
                        )
                        return
                    # No se borra la carpeta destino si ya existía (promesa de clonador);
                    # solo se limpia su contenido para no dejar restos.
                    for hijo in carpeta.iterdir():
                        if hijo.is_dir() and not hijo.is_symlink():
                            shutil.rmtree(hijo, ignore_errors=True)
                        else:
                            hijo.unlink(missing_ok=True)
                    self.emit_event(
                        "clonado_fin",
                        {
                            "ok": False,
                            "destino": resultado.destino,
                            "tipo_error": "incompatibilidad_lenguaje",
                            "error": inspeccion["error"],
                        },
                    )
                    return
            datos = asdict(resultado)
            if ya_clonado:
                datos["ok"] = True
                datos["tipo_error"] = None
                datos["error"] = None
                datos["advertencia"] = (
                    f"Ya estaba clonado en {resultado.destino}: no se volvió a descargar."
                )
            if resultado.ok or ya_clonado:
                nombre = Path(resultado.destino).name or clonador.nombre_repositorio(
                    url
                )
                try:
                    recientes.registrar(nombre, "git", resultado.destino, url=url)
                except OSError as exc:
                    bitacora.registro.warning(
                        "El repositorio se clonó, pero no se pudo registrar en recientes: %s",
                        exc,
                    )
                    datos["advertencia"] = (
                        "El repositorio se clonó correctamente, pero no se pudo guardar "
                        "en Proyectos recientes."
                    )
                _preparar_almacen(resultado.destino)
            self.emit_event("clonado_fin", datos)

        def ejecutar() -> None:
            try:
                trabajo()
            except Exception as error:  # noqa: BLE001 -- el puente debe liberar el estado del hilo
                self.emit_event("clonado_fin", {"ok": False, "error": str(error)})
            finally:
                self._clonando = False

        try:
            threading.Thread(target=ejecutar, name="clonado-git", daemon=True).start()
        except Exception:
            self._clonando = False
            raise
        return {"iniciado": True}

    def cancelar_clonado(self) -> dict:
        """Solicita detener Git, conservando cualquier carpeta preexistente."""
        self._cancelar_clonado.set()
        return {"ok": True}

    def inspeccionar_carpeta(self, ruta: str) -> dict:
        """Valida la carpeta y cuenta las fuentes del adaptador elegido (HU-01).

        Returns:
            dict: lenguaje, cantidad de fuentes, ruta, rama y motivo si no se puede abrir.
        """
        return proyecto_local.inspeccionar_carpeta(ruta)

    def abrir_proyecto(self, ruta: str) -> dict:
        """Revalida la carpeta y, si tiene fuentes soportadas, registra el proyecto.

        Una carpeta sin fuentes analizables nunca se registra.

        Returns:
            dict: El resultado de ``inspeccionar_carpeta``; si no se pudo
            guardar en recientes, ``ok`` es False con el motivo en ``error``.
        """
        proyecto = proyecto_local.inspeccionar_carpeta(ruta)
        if not proyecto["ok"]:
            return proyecto
        try:
            recientes.registrar(proyecto["nombre"], "local", proyecto["ruta"])
        except OSError:
            return {
                **proyecto,
                "ok": False,
                "error": "No se pudo guardar el proyecto en Proyectos recientes "
                f"({recientes.ruta_por_defecto()}).",
            }
        _preparar_almacen(proyecto["ruta"])
        almacen = AlmacenProyecto(proyecto["ruta"])
        tiene_pruebas = almacen.tiene_pruebas_aprobadas()
        # #139: solo cuentan las corridas con resultados (no las interrumpidas).
        tiene_corridas = _corridas_al_abrir(almacen)
        return {
            **proyecto,
            "tiene_pruebas": tiene_pruebas,
            "tiene_corridas": tiene_corridas,
            "ya_cargo_prueba": tiene_corridas or tiene_pruebas,
        }

    def listar_recientes(self) -> list[dict]:
        """Hasta 10 proyectos recientes para la Bienvenida (HU-03)."""
        return recientes.listar()

    def listar_proyectos_de_carpeta(self, carpeta: str | None = None) -> dict:
        """Los proyectos que ya están en tu equipo, dentro de una carpeta.

        Escanea un nivel de la carpeta indicada (por defecto, la carpeta donde QAgent
        clona: ``~/Proyectos``) y devuelve las carpetas que tienen fuentes de un
        lenguaje soportado, para abrirlas con un clic sin buscarlas a mano. Solo lee
        el sistema de archivos: nunca importa ni ejecuta nada.

        Returns:
            dict: ``{"ok": True, "carpeta": str, "existe": bool, "proyectos": [...]}``
            con ``nombre``, ``ruta``, ``lenguaje``, ``nombre_lenguaje``,
            ``cantidad_fuentes`` y ``rama`` de cada proyecto.
        """
        from qagent.proyectos import clonador

        base = (
            Path(carpeta).expanduser()
            if carpeta
            else clonador.carpeta_proyectos_por_defecto()
        )
        proyectos: list[dict] = []
        existe = base.is_dir()
        if existe:
            try:
                hijos = sorted(base.iterdir(), key=lambda p: p.name.lower())
            except OSError:
                hijos = []
            for hijo in hijos:
                if not hijo.is_dir() or hijo.name.startswith("."):
                    continue
                info = proyecto_local.inspeccionar_carpeta(hijo)
                if not info["ok"]:
                    continue
                proyectos.append(
                    {
                        "nombre": hijo.name,
                        "ruta": str(hijo),
                        "lenguaje": info["lenguaje"],
                        "nombre_lenguaje": info["nombre_lenguaje"],
                        "cantidad_fuentes": info["cantidad_fuentes"],
                        "rama": info["rama"],
                    }
                )
        return {
            "ok": True,
            "carpeta": str(base),
            "existe": existe,
            "proyectos": proyectos,
        }

    def abrir_reciente(self, ruta: str) -> dict:
        """Reabre un proyecto reciente y devuelve los datos para la Vista previa (HU-03).

        Returns:
            dict: Lo mismo que ``inspeccionar_carpeta`` más ``origen`` y ``url``; si la
            carpeta ya no existe, ``ok`` es False y ``motivo`` es ``"no_encontrada"``.
        """
        try:
            abierto = recientes.abrir(ruta)
        except OSError:
            return {
                "ok": False,
                "motivo": "error",
                "error": "No se pudo actualizar Proyectos recientes.",
            }
        if not abierto["ok"]:
            return abierto
        reciente = abierto["proyecto"]
        proyecto = proyecto_local.inspeccionar_carpeta(reciente["ruta"])
        tiene_pruebas = False
        tiene_corridas = False
        if proyecto["ok"]:
            _preparar_almacen(proyecto["ruta"])
            almacen = AlmacenProyecto(proyecto["ruta"])
            tiene_pruebas = almacen.tiene_pruebas_aprobadas()
            # #139: solo cuentan las corridas con resultados (no las interrumpidas ni
            # la fecha de recientes, que se anota aunque la corrida no deje resultados).
            tiene_corridas = _corridas_al_abrir(almacen)
        return {
            **proyecto,
            "origen": reciente["origen"],
            "url": reciente["url"],
            "ultima_corrida": reciente.get("ultima_corrida"),
            "tiene_pruebas": tiene_pruebas,
            "tiene_corridas": tiene_corridas,
            "ya_cargo_prueba": tiene_corridas or tiene_pruebas,
        }

    def quitar_reciente(self, ruta: str) -> bool:
        """Quita un proyecto de la lista de recientes sin borrar su carpeta (HU-03)."""
        try:
            return recientes.quitar(ruta)
        except OSError:
            return False

    def obtener_vista_previa(self, ruta: str, usar_ia: bool = False) -> dict:
        """Obtiene la vista previa del proyecto analizado por AST (HU-04).

        Devuelve los módulos priorizados (primero los que tienen más funciones
        con ramas), los errores de sintaxis y el resumen de métricas e
        inconsistencias según el JSON de EN-02.
        Por defecto no consulta modelos. ``usar_ia=True`` solicita explícitamente
        la recomendación opcional de tipos con IA, entregada mediante un evento.
        """
        import threading

        from qagent.proyectos import vista_previa

        if usar_ia is not True:
            return vista_previa.generar_vista_previa(ruta, ia=False)
        recomendador = vista_previa.recomendador_ia_configurado()
        if recomendador is None:
            return vista_previa.generar_vista_previa(ruta, ia=False)
        # Con el Recomendador en modo IA, el LLM tardaba hasta 30 s y la Vista previa
        # no aparecía hasta que respondía. Ahora se muestra al momento con las reglas y
        # la recomendación de la IA llega después con el evento ``recomendacion_ia``.
        vista = vista_previa.generar_vista_previa(ruta, ia=False)
        if not vista.get("ok") or not vista.get("recomendacion", {}).get(
            "recomendaciones"
        ):
            return vista

        def pedir_a_la_ia() -> None:
            try:
                datos = vista_previa.recomendar_con_ia_para_vista(
                    vista, ruta, recomendador
                )
            except Exception as exc:  # noqa: BLE001 — la IA es opcional
                bitacora.registro.warning("Recomendación con reglas, sin IA: %s", exc)
                datos = {}
            self.emit_event("recomendacion_ia", {"ruta": vista["ruta"], **datos})

        threading.Thread(
            target=pedir_a_la_ia, name="recomendador-ia-vista", daemon=True
        ).start()
        return {**vista, "recomendacion_ia_pendiente": True}

    def estado_preparacion(self, ruta: str) -> dict:
        """Si el entorno aislado del proyecto ya está preparado (backlog 17).

        La interfaz lo pide aparte, después de mostrar la Vista previa: consulta
        Docker y no debe retrasarla. Nunca construye ni descarga nada.
        """
        from qagent.proyectos.compatibilidad import estado_preparacion

        try:
            return estado_preparacion(ruta)
        except Exception as exc:  # noqa: BLE001 — informar nunca debe romper la vista
            bitacora.registro.warning("No se consultó la preparación: %s", exc)
            return {"estado": "desconocida", "mensaje": str(exc)}

    def analizar_proyecto(self, ruta: str) -> dict:
        """Alias de obtener_vista_previa para la interfaz JavaScript (HU-04)."""
        return self.obtener_vista_previa(ruta)

    def obtener_seleccion_objetivos(self, ruta: str) -> dict:
        """Recupera la selección de Explorar guardada para este proyecto."""
        from qagent.proyectos.preferencias import cargar_seleccion_objetivos

        return {"ok": True, "seleccion": cargar_seleccion_objetivos(ruta)}

    def guardar_seleccion_objetivos(self, ruta: str, seleccion: dict) -> dict:
        """Persiste la selección de Explorar dentro del almacén del proyecto."""
        from qagent.proyectos.preferencias import guardar_seleccion_objetivos

        try:
            guardar_seleccion_objetivos(ruta, seleccion)
        except (OSError, TypeError, ValueError) as exc:
            bitacora.registro.warning(
                "No se pudo guardar la selección de objetivos en '%s': %s", ruta, exc
            )
            return {"ok": False, "error": str(exc)}
        return {"ok": True}
