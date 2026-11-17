"""Corrida completa sobre un proyecto: análisis → agentes → registro (EN-04, EN-05, EN-07).

Une las piezas que ya existían por separado:

1. Analiza el proyecto con el adaptador y tree-sitter y cuenta los objetivos a revisar.
2. Crea el cliente LLM de cada agente desde `config.toml` y `.env` (o la IA simulada).
3. Ejecuta el orquestador módulo por módulo; cada `Evento` llega a `al_evento` con el
   progreso (`hechos` / `total`), para el Monitor en vivo (HU-09).
4. Corta antes del siguiente módulo si se alcanzó el tope de gasto de `config.toml`.
5. En el perfil Profundo, aplica el motor del adaptador a las funciones críticas aprobadas.
6. Reutiliza la spec modular si su huella sigue vigente, solo para los objetivos
   elegidos en la Vista previa; si cambió o le falta alguno, llama al Planner. La
   spec guardada conserva los contratos de los objetivos que no se eligieron.
   Cada spec recuerda el perfil con que se creó (#75): una de Humo (un solo caso) no
   se reutiliza en Estándar ni Profundo, y una Estándar en Humo usa su primer caso
   normal.
7. Escribe `log.json` y `results.json` (EN-05) en la carpeta de la corrida, guarda las
   specs y las pruebas aprobadas en `.qagent/` y cierra el `run.json` (EN-07).

No depende de la interfaz: la app la llama en un hilo y le pasa una función para los
eventos. Nunca lanza excepciones: cualquier problema termina en `fallo_controlado` con
el motivo en el resumen.
"""

from __future__ import annotations

import importlib
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from qagent.agents import GeneratorAgent, PlannerAgent, ReviewerAgent
from qagent.agents.reviewer import Ejecutor
from qagent.almacenamiento import AlmacenProyecto
from qagent.llm import TokenTracker
from qagent.llm.fabrica import FuenteClaves
from qagent.orchestrator.corrida_entorno import (
    _anunciar_entorno_listo,
    _esperar_imagen,
    _preparar_imagen,
    avance_limitado,
    limites_del_lenguaje,
)
from qagent.orchestrator.corrida_explicacion import _docstrings
from qagent.orchestrator.corrida_modelo import (
    ENTORNO,
    ENTORNO_AVANCE,
    ENTORNO_PREPARANDO,
    FALLO,
    FIN,
    AlEvento,
    EntornoEnPreparacion,
    PrepararImagen,
    ResumenCorrida,
    _ContextoIA,
    _ModuloPreparado,
    _ReviewerSinEntorno,
    _texto_error,
)
from qagent.orchestrator.corrida_planificacion import (
    _analizar_entrada,
    _cancelar_sin_entorno,
    _corte_por_recursos,
    _crear_clientes,
    _detener_por_compilacion,
    _detener_por_error_global,
    _guardar_specs_sin_entorno,
    _iniciar_corrida,
    _marcar_fallo_modulo,
    _mutar_si_profundo,
    _planificar_adelantado,
    _preparar_modulo,
    _proveedor_inferencia,
    _registrar_modulo,
)
from qagent.orchestrator.corrida_registro import (
    _cerrar_contabilidad,
    _cerrar_run,
    _contar,
    _registrar,
    _registrar_limite_tokens,
    _texto_terminacion,
    _titulo_final,
)
from qagent.orchestrator.eventos import BusEventos, Evento
from qagent.orchestrator.mutacion import PERFIL_PROFUNDO, Mutador
from qagent.orchestrator.orquestador import (
    Orquestador,
    ResultadoCorrida,
    timeout_paso_para,
)
from qagent.orchestrator.regresion import huellas_de_objetivos
from qagent.orchestrator.tiempos import iso_utc, segundos
from qagent.sandbox import ejecutar_pruebas
from qagent.sandbox.copias import con_sesion_de_copias
from qagent.storage.registro import PERFILES_REGRESION

#: Módulos donde viven los nombres que antes se importaban de `qagent.orchestrator.corrida`.
_MODULOS_REEXPORTADOS = (
    "collections.abc",
    "concurrent.futures",
    "dataclasses",
    "json",
    "logging",
    "pathlib",
    "threading",
    "time",
    "typing",
    "qagent.orchestrator.corrida_modelo",
    "qagent.orchestrator.corrida_entorno",
    "qagent.orchestrator.corrida_registro",
    "qagent.orchestrator.corrida_explicacion",
    "qagent.orchestrator.corrida_planificacion",
    "qagent.agents",
    "qagent.agents.explicador",
    "qagent.agents.planner",
    "qagent.agents.reviewer",
    "qagent.almacenamiento",
    "qagent.config.carga",
    "qagent.lenguajes",
    "qagent.llm",
    "qagent.llm.fabrica",
    "qagent.orchestrator.eventos",
    "qagent.orchestrator.mutacion",
    "qagent.orchestrator.orquestador",
    "qagent.orchestrator.regresion",
    "qagent.orchestrator.tiempos",
    "qagent.proyectos.proyecto_local",
    "qagent.sandbox",
    "qagent.storage",
    "qagent.storage.registro",
    "qagent",
)


def __getattr__(nombre: str) -> Any:
    """Resuelve los nombres que antes vivían aquí y hoy están en otros módulos."""
    for ruta in _MODULOS_REEXPORTADOS:
        try:
            modulo = importlib.import_module(ruta)
        except ImportError:
            continue
        if hasattr(modulo, nombre):
            return getattr(modulo, nombre)
    raise AttributeError(f"módulo {__name__!r} no tiene el atributo {nombre!r}")


@con_sesion_de_copias
def ejecutar_corrida(
    ruta_proyecto: str | Path,
    perfil: str,
    configuracion: Any,
    claves: FuenteClaves | None,
    *,
    simulado: bool,
    al_evento: AlEvento | None = None,
    run_id: str | None = None,
    preparar_imagen: PrepararImagen | None = None,
    ejecutor: Ejecutor = ejecutar_pruebas,
    timeout_paso_s: float | None = None,
    seleccion: list[dict[str, Any]] | None = None,
    mutador: Mutador | None = None,
    reloj: Callable[[], float] = time.monotonic,
    ahora: Callable[[], str] = iso_utc,
    cancelado: Callable[[], bool] | None = None,
    inferir: bool | None = None,
    revisor_inferidos: Callable[[list[dict[str, Any]]], set[str]] | None = None,
    completar_contexto: bool = False,
) -> ResumenCorrida:
    """Ejecuta la corrida completa de un proyecto y devuelve su resumen.

    Args:
        ruta_proyecto: carpeta del proyecto abierto.
        perfil: perfil elegido en la interfaz (se registra en log.json). Con `humo`
            el Planner pide un solo caso normal por objetivo (#75).
        configuracion: `Configuracion` de `cargar_configuracion()` (agentes, tope de
            gasto y reintentos).
        claves: claves de `.env`; no se usan con la IA simulada.
        simulado: True con `QAGENT_FAKE_LLM=1` (0 tokens).
        al_evento: recibe cada evento como dict (`Evento.a_dict()` + `progreso`).
        run_id: corrida creada al pulsar «Iniciar» (`run.json`); si es None se crea una
            si el proyecto tiene `.qagent/`.
        preparar_imagen: devuelve la imagen Docker del sandbox para el proyecto; por
            defecto `sandbox.preparar_imagen` (construye la base si falta).
        ejecutor: cómo ejecuta el Reviewer las pruebas (Docker; reemplazable en pruebas).
        timeout_paso_s: tiempo máximo por paso de un agente; por defecto el del
            orquestador, alargado si `[sandbox] timeout_s` lo pide.
        seleccion: módulos, funciones y endpoints elegidos en la Vista previa. Si es
            ``None``, se conservan todos los objetivos analizables.
        mutador: motor de mutación sustituible en pruebas. None selecciona el del
            adaptador del contrato (mutmut para Python, PIT para Java).
        reloj: reloj monotónico inyectable para medir duraciones (#115).
        ahora: marca UTC ISO inyectable para inicio y fin (#115).
        cancelado: consulta inyectable para detener la corrida de forma controlada.
        inferir: si se infiere el contrato de las funciones sin docstring (#275,
            ADR-016). None usa `[inferencia] activa` de la configuración.
        revisor_inferidos: revisión humana opcional de esos contratos: recibe las
            propuestas y devuelve los objetivos aceptados.
    """
    if perfil in PERFILES_REGRESION:
        from qagent.orchestrator.regresion import ejecutar_regresion

        return ejecutar_regresion(
            ruta_proyecto,
            perfil,
            configuracion,
            al_evento=al_evento,
            run_id=run_id,
            preparar_imagen=preparar_imagen,
            ejecutor=ejecutor,
            seleccion=seleccion,
            mutador=mutador,
            reloj=reloj,
            ahora=ahora,
            cancelado=cancelado,
        )

    inicio = reloj()
    inicio_utc = ahora()
    ruta = Path(ruta_proyecto)
    progreso = {"hechos": 0, "total": 0}
    objetivos_procesados: set[tuple[str | None, str | None]] = set()

    # #148: la construcción del entorno aislado avisa desde otro hilo.
    candado = threading.RLock()

    def emitir(evento: Evento) -> None:
        with candado:
            _emitir(evento)

    def _emitir(evento: Evento) -> None:
        if evento.tipo == "veredicto":
            objetivos_procesados.add((evento.archivo, evento.funcion))
            progreso["hechos"] = len(objetivos_procesados)
        if al_evento is not None:
            datos_evento = dict(evento.datos or {})
            if "tracker" in locals():
                datos_evento.setdefault("tokens_acumulados", tracker.total_tokens)
                datos_evento.setdefault("tokens_reales", tracker.total_tokens_reales)
                datos_evento.setdefault(
                    "tokens_estimados", tracker.total_tokens_estimados
                )
            if "tope_tokens" in locals() and tope_tokens:
                datos_evento.setdefault("limite_tokens", tope_tokens)
            al_evento(
                {
                    **evento.a_dict(),
                    "datos": datos_evento,
                    "progreso": dict(progreso),
                    "tokens_acumulados": tracker.total_tokens
                    if "tracker" in locals()
                    else 0,
                    "tokens_reales": tracker.total_tokens_reales
                    if "tracker" in locals()
                    else 0,
                    "tokens_estimados": tracker.total_tokens_estimados
                    if "tracker" in locals()
                    else 0,
                    "limite_tokens": tope_tokens if "tope_tokens" in locals() else None,
                    "inicio_corrida": inicio_utc,
                    "transcurrido_s": segundos(inicio, reloj()),
                    "etapas_s": dict(resumen.duracion_etapas),
                }
            )

    def avisar(
        mensaje: str,
        tipo: str = "agente",
        archivo: str | None = None,
        datos: dict[str, Any] | None = None,
    ) -> None:
        emitir(
            Evento(
                "orquestador", archivo, None, mensaje, "preparacion", tipo, datos=datos
            )
        )

    def avisar_entorno(mensaje: str, estado: str, tipo: str = "agente") -> None:
        # #148: el Monitor muestra el entorno aparte de la etapa de los agentes.
        avisar(mensaje, tipo, datos={ENTORNO: estado})

    almacen = AlmacenProyecto(ruta)
    resumen = ResumenCorrida(
        run_id=run_id,
        estado=FIN,
        motivo=None,
        total_funciones=0,
        inicio=inicio_utc,
    )
    resultados: list[ResultadoCorrida] = []
    tipos: list[str] = ["funcion"]
    #: Segundos construyendo el entorno aislado y los que la corrida lo esperó (#148).
    etapas_entorno: dict[str, float] = {}
    try:
        if _iniciar_corrida(ruta, resumen, almacen, tipos, cancelado, avisar):
            return resumen

        entrada = _analizar_entrada(
            ruta,
            resumen,
            almacen,
            tipos,
            seleccion,
            preparar_imagen,
            progreso,
            avisar,
            avisar_entorno,
            completar_contexto=completar_contexto,
        )
        if entrada is None:
            return resumen
        adaptador = entrada.adaptador
        analisis = entrada.analisis
        modulos = entrada.modulos
        version_python = entrada.version_python
        no_soportados = entrada.no_soportados
        fuera = entrada.fuera
        tipos = entrada.tipos

        tracker = TokenTracker(configuracion.agentes)
        # El Explicador crea su cliente al final (`_redactor_ia`): sin su clave la
        # corrida no se detiene, usa la plantilla (ADR-008).
        clientes = _crear_clientes(configuracion, claves, simulado)
        avisar_entorno(
            (
                f"Preparando el entorno aislado (Docker) con Python {version_python} para ejecutar las pruebas"
                if version_python
                else "Preparando el entorno aislado (Docker) para ejecutar las pruebas"
            ),
            ENTORNO_PREPARANDO,
        )
        # #148: construir la imagen puede tardar minutos (APP-RF: 11 de 13). Se
        # construye en segundo plano mientras el Planner, que no necesita Docker,
        # planifica los módulos; su avance va al Monitor.
        if preparar_imagen is not None:
            preparar = preparar_imagen
        else:

            def preparar(ruta_imagen: Path) -> str:
                return _preparar_imagen(
                    ruta_imagen,
                    imagen_base=adaptador.entorno_sandbox(ruta).imagen,
                    comprobar_librerias=adaptador.comprobar_librerias_sistema,
                    avanzar=avance_limitado(
                        lambda texto: avisar_entorno(texto, ENTORNO_AVANCE),
                        cancelado=cancelado,
                    ),
                    # La librería faltante se destaca aparte como alerta (issue 142).
                    avisar_faltante=lambda mensaje: avisar(mensaje, "aviso"),
                )

        entorno = EntornoEnPreparacion(lambda: preparar(ruta), reloj)

        bus = BusEventos()
        bus.suscribir(emitir)
        # #168: memoria y tiempo del lenguaje (`[sandbox.<lenguaje>]`, #169); Python
        # usa `[sandbox]` como siempre.
        limites = limites_del_lenguaje(configuracion, adaptador.lenguaje)
        tope_tokens = getattr(configuracion.presupuesto, "max_tokens_por_corrida", None)
        opciones: dict[str, Any] = {
            "max_intentos": configuracion.max_intentos,
            "timeout_paso_s": timeout_paso_s
            if timeout_paso_s is not None
            else timeout_paso_para(limites.timeout_s),
            "reloj": reloj,
            "ahora": ahora,
            "limite_tokens": tope_tokens,
            "cancelado": cancelado,
            "revisor_inferidos": revisor_inferidos,
        }
        # #275 (ADR-016): contexto estático para inferir las funciones sin docstring.
        inferencia = getattr(configuracion, "inferencia", None)
        proveedor_inferencia = _proveedor_inferencia(
            adaptador, ruta, analisis, inferencia, inferir
        )
        orquestador = Orquestador(
            PlannerAgent(
                clientes["planner"],
                tracker,
                es_simulado=simulado,
                perfil=perfil,
                adaptador=adaptador,
                proveedor_inferencia=proveedor_inferencia,
                max_inferidas=getattr(inferencia, "max_funciones_por_modulo", 20),
            ),
            GeneratorAgent(
                clientes["generator"], tracker, es_simulado=simulado, ruta_proyecto=ruta
            ),
            # El Reviewer necesita la imagen: se asigna cuando el entorno está listo.
            _ReviewerSinEntorno(),
            bus=bus,
            tracker=tracker,
            **opciones,
        )

        planes_specs: list[dict[str, Any]] = []
        # #70: con las huellas, el Mutation Score de esta corrida queda guardado para
        # reutilizarlo al repetir las pruebas sin cambios.
        huellas = huellas_de_objetivos(ruta) if perfil == PERFIL_PROFUNDO else None
        tope = configuracion.presupuesto.tope_por_corrida_usd

        def preparar_modulo(modulo: dict[str, Any]) -> _ModuloPreparado:
            """Decide si se reutiliza la spec vigente y planifica el módulo."""
            return _preparar_modulo(almacen, modulo, perfil, avisar, orquestador)

        def sin_recursos() -> bool:
            return tracker.total_costo_usd >= tope or (
                tope_tokens is not None and tracker.total_tokens >= tope_tokens
            )

        # #148: mientras se construye el entorno se planifican los módulos en orden.
        # Los cortes por cancelación o presupuesto se avisan después, en el bucle de
        # ejecución, al llegar a ese módulo.
        preparados = _planificar_adelantado(
            modulos, entorno, cancelado, sin_recursos, preparar_modulo
        )

        imagen = _esperar_imagen(
            entorno, cancelado, resumen, avisar_entorno, etapas_entorno, reloj
        )
        resumen.imagen_docker = imagen
        a_ejecutar = modulos
        if imagen is None:
            # #148: sin entorno no se ejecuta nada, pero las specs ya planificadas se
            # guardan para reutilizarlas en la próxima corrida (0 tokens).
            a_ejecutar = []
            _cancelar_sin_entorno(resumen, avisar_entorno)
            _guardar_specs_sin_entorno(modulos, preparados, planes_specs, perfil)
        else:
            _anunciar_entorno_listo(version_python, avisar_entorno)
            orquestador.reviewer = ReviewerAgent(
                tracker,
                ruta,
                imagen,
                cliente=clientes["reviewer"],
                ejecutor=ejecutor,
                es_simulado=simulado,
                limites=limites,
            )

        for modulo in a_ejecutar:
            corte = _corte_por_recursos(cancelado, tracker, tope, tope_tokens)
            if corte is not None:
                resumen.estado = FALLO
                resumen.cancelada = corte.cancelada
                resumen.tipo_terminacion = corte.tipo
                resumen.motivo = corte.motivo
                avisar(resumen.motivo, "fallo")
                break
            preparado = preparados.pop(modulo["ruta"], None) or preparar_modulo(modulo)
            resultado = orquestador.ejecutar(modulo, plan_previo=preparado.plan)
            _mutar_si_profundo(
                perfil,
                ruta,
                imagen,
                modulo,
                resultado,
                configuracion,
                mutador,
                avisar,
                almacen,
                resumen,
                huellas,
                limites,
            )
            _registrar_modulo(
                resultados,
                planes_specs,
                modulo,
                resultado,
                preparado,
                perfil,
            )
            _marcar_fallo_modulo(resumen, resultado, cancelado)
            if _detener_por_error_global(resumen, resultado, avisar):
                break
            if _detener_por_compilacion(resumen, resultado, avisar):
                break
            if _registrar_limite_tokens(resumen, resultado, tope_tokens):
                avisar(resumen.motivo, "fallo")
                break

        _cerrar_contabilidad(resumen, resultados, tracker, etapas_entorno)
        progreso["total"] = resumen.total_seleccionados or resumen.total_funciones
        resumen.duracion_s = segundos(inicio, reloj())
        resumen.fin = ahora()
        _registrar(
            ruta,
            almacen,
            resumen,
            resultados,
            tracker,
            configuracion,
            perfil,
            planes_specs,
            tipos,
            ia=_ContextoIA(claves, simulado, cancelado, _docstrings(modulos)),
            no_soportados=no_soportados,
            fuera_de_la_corrida=fuera,
            al_aviso=lambda mensaje: avisar(mensaje, "aviso"),
        )
    except Exception as error:  # noqa: BLE001 — la corrida nunca debe tumbar la app
        if "tracker" in locals():
            _contar(resumen, resultados, tracker)
            resumen.duracion_etapas.update(etapas_entorno)
        else:
            resumen.total_elegibles = max(
                0, resumen.total_seleccionados - resumen.objetivos_omitidos
            )
            resumen.total_pendientes = max(
                0, resumen.total_elegibles - resumen.total_procesados
            )
        resumen.estado = FALLO
        resumen.tipo_terminacion = "detenida_error"
        resumen.motivo = resumen.motivo or _texto_error(error)
        resumen.duracion_s = segundos(inicio, reloj())
        resumen.fin = ahora()
        avisar(f"Corrida detenida: {resumen.motivo}", "fallo")
        _cerrar_run(almacen, resumen, tipos)

    resumen.duracion_s = resumen.duracion_s or segundos(inicio, reloj())
    resumen.fin = resumen.fin or ahora()
    avisar(f"{_titulo_final(resumen)}: {_texto_terminacion(resumen)}", "fin")
    return resumen
