"""Análisis inicial, planificación adelantada y cortes de una corrida."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from qagent.agents.planner import contrato_humo, contrato_sin_triviales
from qagent.almacenamiento import AlmacenProyecto
from qagent.config.carga import Mutacion
from qagent.lenguajes import (
    LenguajeNoSoportado,
    VersionPythonNoSoportada,
    adaptador_del_proyecto,
    fuera_de_la_corrida,
)
from qagent.llm import TokenTracker
from qagent.llm.fabrica import FuenteClaves
from qagent.orchestrator.corrida_entorno import (
    omitidos_de_interfaz,
)
from qagent.orchestrator.corrida_modelo import (
    ENTORNO_CANCELADO,
    ENTORNO_FALLO,
    FALLO,
    EntornoEnPreparacion,
    ErrorCorrida,
    PrepararImagen,
    ResumenCorrida,
    _CorteRecursos,
    _EntradaCorrida,
    _ModuloPreparado,
)
from qagent.orchestrator.corrida_registro import (
    _cerrar_run,
    _con_fuente,
    _existe_plan_modulo,
    _objetivos_de,
    _spec_de_modulo,
)
from qagent.orchestrator.mutacion import PERFIL_PROFUNDO, Mutador, mutar_modulo
from qagent.orchestrator.orquestador import ResultadoCorrida, es_error_global
from qagent.sandbox import LimitesSandbox
from qagent.storage.registro import PERFIL_HUMO


def _modulo_corrida():
    """Módulo principal, donde las pruebas reemplazan `crear_cliente` y `_motivo_sin_espacio`."""
    from qagent.orchestrator import corrida

    return corrida


def _detener_entrada(
    resumen: ResumenCorrida,
    almacen: AlmacenProyecto,
    tipos: list[str],
    motivo: str,
    avisar: Callable[..., None],
    avisar_entorno: Callable[..., None],
) -> None:
    """Cierra la corrida antes de planificar por un requisito del entorno."""
    resumen.estado = FALLO
    resumen.tipo_terminacion = "detenida_error"
    resumen.motivo = motivo
    avisar(motivo, "fallo")
    avisar_entorno(motivo, ENTORNO_FALLO, "fallo")
    _cerrar_run(almacen, resumen, tipos)


def _cifras_de_modulos(
    modulos: list[dict[str, Any]],
) -> tuple[int, int, int, int]:
    """Cuenta funciones, integraciones, endpoints y componentes elegidos."""
    n_funciones = sum(
        1 for m in modulos for f in m["funciones"] if not f.get("solo_integracion")
    )
    n_integraciones = sum(len(m.get("integraciones") or []) for m in modulos)
    n_endpoints = sum(len(m.get("endpoints") or []) for m in modulos)
    n_componentes = sum(len(m.get("componentes") or []) for m in modulos)
    return n_funciones, n_integraciones, n_endpoints, n_componentes


def _analizar_entrada(
    ruta: Path,
    resumen: ResumenCorrida,
    almacen: AlmacenProyecto,
    tipos: list[str],
    seleccion: list[dict[str, Any]] | None,
    preparar_imagen: PrepararImagen | None,
    progreso: dict[str, int],
    avisar: Callable[..., None],
    avisar_entorno: Callable[..., None],
) -> _EntradaCorrida | None:
    """Elige el adaptador y los módulos; None si la corrida ya se detuvo."""
    from qagent.proyectos.seleccion import filtrar_modulos

    try:
        adaptador = adaptador_del_proyecto(ruta)
    except LenguajeNoSoportado as error:
        raise ErrorCorrida(str(error)) from error
    version_python = None
    if adaptador.lenguaje == "python" and hasattr(adaptador, "resolver_version_python"):
        try:
            version_python = adaptador.resolver_version_python(ruta)
        except VersionPythonNoSoportada as error:
            _detener_entrada(
                resumen, almacen, tipos, str(error), avisar, avisar_entorno
            )
            return None
    # #267: si hay que construir o descargar una imagen y el disco de Docker está
    # justo, la corrida no empieza (antes de gastar tokens planificando).
    sin_espacio = (
        _modulo_corrida()._motivo_sin_espacio(ruta, adaptador)
        if preparar_imagen is None
        else None
    )
    if sin_espacio is not None:
        _detener_entrada(resumen, almacen, tipos, sin_espacio, avisar, avisar_entorno)
        return None
    analisis = adaptador.analizar(ruta)
    modulos = [
        _con_fuente(ruta, m) for m in filtrar_modulos(analisis["modulos"], seleccion)
    ]
    n_funciones, n_integraciones, n_endpoints, n_componentes = _cifras_de_modulos(
        modulos
    )
    resumen.total_seleccionados = (
        n_funciones + n_endpoints + n_componentes + n_integraciones
    )
    progreso["total"] = resumen.total_funciones = resumen.total_seleccionados
    no_soportados = omitidos_de_interfaz(analisis)
    if no_soportados:
        avisar(no_soportados[0]["motivo"])
    # EP-11: los archivos del lenguaje hermano (JS o TS) no elegido no se prueban;
    # se avisan en el Monitor y quedan en results.json para el informe.
    fuera = fuera_de_la_corrida(ruta, adaptador)
    for aviso in fuera:
        avisar(aviso["mensaje"], "aviso")
    tipos = list(tipos)
    if n_endpoints:
        tipos = ["funcion", "endpoint"] if n_funciones else ["endpoint"]
        avisar(
            f"Análisis estático: {len(modulos)} módulo(s) con {n_funciones} "
            f"función(es) pública(s) y {n_endpoints} endpoint(s)"
        )
    else:
        avisar(
            f"Análisis estático: {len(modulos)} módulo(s) con "
            f"{n_funciones} función(es) pública(s)"
        )
    if n_integraciones:
        tipos = [*tipos, "integracion"]
        avisar(f"Integración interna: {n_integraciones} cadena(s) de funciones")
    if not modulos:
        raise ErrorCorrida(
            "El proyecto no tiene funciones públicas ni endpoints que revisar."
        )
    return _EntradaCorrida(
        adaptador, analisis, modulos, version_python, no_soportados, fuera, tipos
    )


def _cancelar_sin_entorno(
    resumen: ResumenCorrida, avisar_entorno: Callable[..., None]
) -> None:
    """Marca la corrida como cancelada cuando no hubo entorno para ejecutar."""
    if resumen.motivo is not None:
        return
    resumen.estado = FALLO
    resumen.cancelada = True
    resumen.tipo_terminacion = "cancelada"
    resumen.motivo = "Corrida cancelada por el usuario."
    avisar_entorno(resumen.motivo, ENTORNO_CANCELADO, "fallo")


def _guardar_specs_sin_entorno(
    modulos: list[dict[str, Any]],
    preparados: dict[str, _ModuloPreparado],
    planes_specs: list[dict[str, Any]],
    perfil: str,
) -> None:
    """Guarda las specs ya planificadas aunque no haya imagen para ejecutar."""
    for modulo in modulos:
        preparado = preparados.get(modulo["ruta"])
        # Una spec reutilizada ya está guardada tal cual.
        if (
            preparado is None
            or preparado.plan.error is not None
            or preparado.accion == "reutilizado"
        ):
            continue
        spec = _spec_de_modulo(modulo, preparado.plan.contratos, preparado, perfil)
        if spec is not None:
            planes_specs.append(spec)


def _corte_por_recursos(
    cancelado: Callable[[], bool] | None,
    tracker: TokenTracker,
    tope: float,
    tope_tokens: int | None,
) -> _CorteRecursos | None:
    """Motivo del corte antes de un módulo, o None si se puede continuar."""
    if cancelado is not None and cancelado():
        return _CorteRecursos("Corrida cancelada por el usuario.", "cancelada", True)
    if tracker.total_costo_usd >= tope:
        return _CorteRecursos(
            f"Se alcanzó el tope de gasto por corrida (US$ {tope:.2f}); "
            "los módulos restantes no se revisaron.",
            "limitada_recursos",
        )
    if tope_tokens is not None and tracker.total_tokens >= tope_tokens:
        return _CorteRecursos(
            f"Se alcanzó el presupuesto de tokens por corrida ({tope_tokens} tokens); "
            "los módulos restantes no se revisaron.",
            "limitada_recursos",
        )
    return None


def _marcar_fallo_modulo(
    resumen: ResumenCorrida,
    resultado: ResultadoCorrida,
    cancelado: Callable[[], bool] | None,
) -> None:
    """Registra el primer fallo de módulo y detecta si fue una cancelación."""
    if resultado.estado_final.value != FALLO or resumen.motivo is not None:
        return
    resumen.estado = FALLO
    resumen.motivo = f"{resultado.modulo}: {resultado.motivo_fallo}"
    if (cancelado is not None and cancelado()) or any(
        p in (resultado.motivo_fallo or "").lower()
        for p in ("cancelad", "por el usuario")
    ):
        resumen.cancelada = True
        resumen.tipo_terminacion = "cancelada"


def _detener_por_error_global(
    resumen: ResumenCorrida, resultado: ResultadoCorrida, avisar: Callable[..., None]
) -> bool:
    """Corta la corrida ante un error de cuenta que se repetiría (FIX-02)."""
    if not resultado.error_global:
        return False
    resumen.tipo_terminacion = "detenida_error"
    avisar(
        "Error de la cuenta del proveedor de IA: no se procesarán más módulos.",
        "fallo",
    )
    return True


def _detener_por_compilacion(
    resumen: ResumenCorrida, resultado: ResultadoCorrida, avisar: Callable[..., None]
) -> bool:
    """Corta la corrida si el proyecto Java no compila (J8), sin gastar más tokens."""
    feedbacks = " ".join(
        str(r.get("feedback", "") or "")
        for o in resultado.objetivos
        for r in (o.revisiones or [])
    )
    if "error_compilacion_proyecto" not in feedbacks.lower():
        return False
    detalle_javac = next(
        (
            linea.strip()[:300]
            for linea in feedbacks.splitlines()
            if ".java:" in linea or "error:" in linea.lower()
        ),
        "",
    )
    resumen.tipo_terminacion = "detenida_error"
    resumen.motivo = f"{resultado.modulo}: error_compilacion_proyecto" + (
        f" — {detalle_javac}" if detalle_javac else ""
    )
    avisar("El proyecto Java no compila; no se procesarán más módulos.", "fallo")
    return True


def _iniciar_corrida(
    ruta: Path,
    resumen: ResumenCorrida,
    almacen: AlmacenProyecto,
    tipos: list[str],
    cancelado: Callable[[], bool] | None,
    avisar: Callable[..., None],
) -> bool:
    """Valida la carpeta, la cancelación y crea el run; True si hay que salir."""
    if not ruta.is_dir():
        raise ErrorCorrida(f"La carpeta del proyecto no existe: {ruta}")
    if cancelado is not None and cancelado():
        resumen.estado = FALLO
        resumen.cancelada = True
        resumen.tipo_terminacion = "cancelada"
        resumen.motivo = "Corrida cancelada por el usuario."
        avisar(resumen.motivo, "fallo")
        _cerrar_run(almacen, resumen, tipos)
        return True
    if resumen.run_id is None and almacen.existe():
        resumen.run_id = almacen.crear_run(tipos_prueba=["funcion"])["run_id"]
    return False


def _proveedor_inferencia(
    adaptador: Any,
    ruta: Path,
    analisis: dict[str, Any],
    inferencia: Any,
    inferir: bool | None,
) -> Any:
    """Proveedor estático de ADR-016, o None si la inferencia está apagada."""
    crear = getattr(adaptador, "proveedor_inferencia", None)
    if crear is None:
        return None
    activa = inferir if inferir is not None else getattr(inferencia, "activa", True)
    if not activa:
        return None
    return crear(ruta, analisis, getattr(inferencia, "max_caracteres_contexto", 6000))


def _planificar_adelantado(
    modulos: list[dict[str, Any]],
    entorno: EntornoEnPreparacion,
    cancelado: Callable[[], bool] | None,
    sin_recursos: Callable[[], bool],
    preparar_modulo: Callable[[dict[str, Any]], _ModuloPreparado],
) -> dict[str, _ModuloPreparado]:
    """Planifica módulos mientras se construye el entorno; corta si toca."""
    preparados: dict[str, _ModuloPreparado] = {}
    for modulo in modulos:
        if entorno.listo() or (cancelado is not None and cancelado()) or sin_recursos():
            break
        preparado = preparar_modulo(modulo)
        preparados[modulo["ruta"]] = preparado
        # Solo un error de la cuenta (FIX-02) se repetiría en los demás módulos; un
        # fallo de red de un módulo no frena la planificación de los siguientes.
        if preparado.plan.error is not None and es_error_global(preparado.plan.error):
            break
    return preparados


def _mutar_si_profundo(
    perfil: str,
    ruta: Path,
    imagen: str | None,
    modulo: dict[str, Any],
    resultado: ResultadoCorrida,
    configuracion: Any,
    mutador: Mutador | None,
    avisar: Callable[..., None],
    almacen: AlmacenProyecto,
    resumen: ResumenCorrida,
    huellas: dict[tuple[str, str], str] | None,
    limites: LimitesSandbox,
) -> None:
    """Aplica mutación a las funciones críticas del módulo en el perfil Profundo."""
    if perfil != PERFIL_PROFUNDO:
        return
    mutar_modulo(
        ruta,
        imagen,
        modulo,
        resultado,
        getattr(configuracion, "mutacion", Mutacion()).tiempo_maximo_por_funcion_s,
        mutador,
        lambda mensaje, archivo=modulo["ruta"]: avisar(mensaje, archivo=archivo),
        almacen=almacen if almacen.existe() else None,
        run_id=resumen.run_id,
        huellas=huellas,
        limites=limites,
    )


def _registrar_modulo(
    resultados: list[ResultadoCorrida],
    planes_specs: list[dict[str, Any]],
    modulo: dict[str, Any],
    resultado: ResultadoCorrida,
    preparado: _ModuloPreparado,
    perfil: str,
) -> None:
    """Guarda el resultado del módulo y su spec si se puede reutilizar."""
    resultados.append(resultado)
    spec = _spec_de_modulo(modulo, resultado.plan_completo, preparado, perfil)
    if spec is not None:
        planes_specs.append(spec)


def _crear_clientes(
    configuracion: Any, claves: FuenteClaves | None, simulado: bool
) -> dict[str, Any]:
    """Crea el cliente de cada agente; el Explicador se crea al final (ADR-008)."""
    return {
        agente: _modulo_corrida().crear_cliente(precio, claves, simulado=simulado)
        for agente, precio in configuracion.agentes.items()
        if agente != "explicador"
    }


def _preparar_modulo(
    almacen: AlmacenProyecto,
    modulo: dict[str, Any],
    perfil: str,
    avisar: Callable[..., None],
    orquestador: Any,
) -> _ModuloPreparado:
    """Decide si se reutiliza la spec vigente y planifica el módulo."""
    plan_guardado = almacen.buscar_plan_vigente(modulo["ruta"], modulo["huella"])
    habia_spec = _existe_plan_modulo(almacen, modulo["ruta"])
    perfiles: dict[str, str] = dict((plan_guardado or {}).get("perfiles") or {})
    # La spec vigente se usa solo para los objetivos elegidos en la Vista
    # previa; si le falta alguno, se vuelve a planificar el módulo.
    elegidos: list[dict[str, Any]] = []
    completos: dict[str, dict[str, Any]] = {}
    faltan: set[str] = set()
    de_humo: set[str] = set()
    if plan_guardado is not None:
        objetivos = _objetivos_de(modulo)
        elegidos = [c for c in plan_guardado["contratos"] if c["objetivo"] in objetivos]
        # #138: una spec anterior puede traer casos triviales de TypeError; sin
        # ellos, la que queda vacía se vuelve a planificar.
        elegidos = [h for h in map(contrato_sin_triviales, elegidos) if h]
        if perfil == PERFIL_HUMO:
            # #75: de una spec completa, Humo toma el primer caso normal.
            completos = {c["objetivo"]: c for c in elegidos}
            elegidos = [h for h in map(contrato_humo, elegidos) if h]
        else:
            # #75: una spec de Humo tiene un solo caso; no sirve aquí.
            de_humo = {
                c["objetivo"]
                for c in elegidos
                if perfiles.get(c["objetivo"]) == PERFIL_HUMO
            }
            elegidos = [c for c in elegidos if c["objetivo"] not in de_humo]
        faltan = objetivos - {c["objetivo"] for c in elegidos}
    if plan_guardado is not None and elegidos and not faltan:
        accion = "reutilizado"
        avisar(
            "Spec vigente: se omite el Planner (0 tokens)",
            archivo=modulo["ruta"],
        )
        plan = orquestador.planificar(modulo, plan_reutilizado=elegidos)
    else:
        accion = "regenerado" if habia_spec else "generado"
        if de_humo:
            avisar(
                f"La spec vigente de {len(de_humo)} objetivo(s) se creó con "
                "Humo (un solo caso): regenerando spec",
                archivo=modulo["ruta"],
            )
        elif plan_guardado is not None:
            avisar(
                f"La spec vigente no incluye {len(faltan)} objetivo(s) "
                "seleccionado(s): regenerando spec",
                archivo=modulo["ruta"],
            )
        elif accion == "regenerado":
            avisar(
                "El código o docstring cambió: regenerando spec",
                archivo=modulo["ruta"],
            )
        plan = orquestador.planificar(modulo)
    return _ModuloPreparado(plan, accion, plan_guardado, perfiles, completos)
