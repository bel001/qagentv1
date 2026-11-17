"""Registro de una corrida: contabilidad, specs y escritura de resultados."""

from __future__ import annotations


def _modulo_corrida():
    """Módulo principal, donde las pruebas reemplazan `escribir_corrida` y otras."""
    from qagent.orchestrator import corrida

    return corrida


from collections.abc import Callable
from pathlib import Path
from typing import Any

from qagent import contracts
from qagent.almacenamiento import (
    AlmacenProyecto,
    ErrorAlmacen,
    id_de_spec,
    nombre_prueba,
)
from qagent.llm import TokenTracker
from qagent.orchestrator.corrida_explicacion import _explicar
from qagent.orchestrator.corrida_modelo import (
    FALLO,
    FIN,
    ResumenCorrida,
    _ContextoIA,
    _ModuloPreparado,
    _registro,
)
from qagent.orchestrator.orquestador import (
    LIMITE_TOKENS,
    ResultadoCorrida,
)
from qagent.orchestrator.regresion import huellas_de_objetivos
from qagent.proyectos.proyecto_local import detectar_rama


def _registrar_limite_tokens(
    resumen: ResumenCorrida,
    resultado: ResultadoCorrida,
    limite_tokens: int | None,
) -> bool:
    """Marca como detenida una corrida cuyo objetivo agotó el presupuesto."""
    if not any(
        objetivo.motivo_estancado == LIMITE_TOKENS for objetivo in resultado.objetivos
    ):
        return False
    resumen.estado = FALLO
    resumen.tipo_terminacion = "limitada_recursos"
    resumen.motivo = (
        f"Se alcanzó el presupuesto de tokens por corrida ({limite_tokens} tokens); "
        "no se procesarán más objetivos."
    )
    return True


def _contar(
    resumen: ResumenCorrida,
    resultados: list[ResultadoCorrida],
    tracker: TokenTracker,
) -> None:
    decisiones = [o.decision for r in resultados for o in r.objetivos]
    resumen.total_procesados = len(decisiones)
    # Omitido (sin resultado esperado verificable o ruta sin resolver) no es pendiente:
    # pendiente es solo lo que una detención dejó sin revisar.
    resumen.objetivos_omitidos = sum(len(r.omitidos) for r in resultados)
    resumen.total_elegibles = max(
        0, resumen.total_seleccionados - resumen.objetivos_omitidos
    )
    resumen.total_pendientes = max(
        0,
        resumen.total_elegibles - resumen.total_procesados,
    )
    resumen.total_funciones = len(decisiones)
    resumen.aceptadas = decisiones.count("accept")
    resumen.bugs_detectados = decisiones.count("bug_detectado")
    resumen.estancadas = decisiones.count("stalled")
    resumen.sin_veredicto = decisiones.count(None)
    resumen.tokens = tracker.total_tokens
    resumen.tokens_reales = tracker.total_tokens_reales
    resumen.tokens_estimados = tracker.total_tokens_estimados
    resumen.costo_usd = round(tracker.total_costo_usd, 8)
    etapas = {
        "planner": 0.0,
        "generator": 0.0,
        "reviewer": 0.0,
        "sandbox": 0.0,
        "pytest": 0.0,
    }
    for resultado in resultados:
        for etapa, segundos_etapa in (resultado.duracion_etapas or {}).items():
            etapas[etapa] = round(etapas.get(etapa, 0.0) + segundos_etapa, 3)
    resumen.duracion_etapas = etapas


def _spec_de_modulo(
    modulo: dict[str, Any],
    contratos: list[dict[str, Any]],
    preparado: _ModuloPreparado,
    perfil: str,
) -> dict[str, Any] | None:
    """Spec del módulo a guardar con los contratos de esta corrida, o None si no hay.

    Conserva los contratos guardados de los objetivos que no se eligieron y el perfil
    con que se creó cada uno (#75).
    """
    perfiles = preparado.perfiles
    if preparado.accion == "reutilizado":
        # En Humo se probó un solo caso, pero la spec guardada sigue completa; solo se
        # actualiza la marca Profundizar de esta corrida.
        contratos = [
            {**preparado.completos.get(c["objetivo"], c), "critical": c["critical"]}
            for c in contratos
        ]
    else:
        # Los que salieron de la spec vigente conservan su contrato guardado y el
        # perfil con que se crearon; solo los planificados ahora llevan el de hoy.
        vigentes = preparado.reutilizados
        contratos = [
            {**preparado.completos.get(c["objetivo"], c), "critical": c["critical"]}
            if c["objetivo"] in vigentes
            else c
            for c in contratos
        ]
        perfiles.update(
            {c["objetivo"]: perfil for c in contratos if c["objetivo"] not in vigentes}
        )
    if contratos and preparado.plan_guardado is not None:
        contratos = _combinar_plan(preparado.plan_guardado["contratos"], contratos)
    validos = [c for c in contratos if contracts.es_planner_valido(c)]
    if not validos:
        return None
    return {
        "modulo": modulo["ruta"],
        "huella": modulo["huella"],
        "contratos": validos,
        "accion": preparado.accion,
        "perfiles": {
            c["objetivo"]: perfiles[c["objetivo"]]
            for c in validos
            if c["objetivo"] in perfiles
        },
    }


def _objetivos_de(modulo: dict[str, Any]) -> set[str]:
    """Funciones, endpoints, componentes e integraciones que la selección dejó.

    Un endpoint sin ruta resuelta no se planifica (el Planner lo omite), así que no
    cuenta como faltante en la spec. Los componentes React (#171) sí cuentan: sin
    ellos, una spec reutilizada dejaba de probarlos en la corrida siguiente.
    """
    funciones = {
        f["nombre"]
        for f in modulo.get("funciones") or []
        if not f.get("solo_integracion")  # #245: solo sirve para derivar la integración
    }
    endpoints = {
        e["objetivo"]
        for e in modulo.get("endpoints") or []
        if e.get("objetivo") and e.get("resuelta", True)
    }
    integraciones = {i["objetivo"] for i in modulo.get("integraciones") or []}
    componentes = {
        c["nombre"] for c in modulo.get("componentes") or [] if c.get("nombre")
    }
    return funciones | endpoints | integraciones | componentes


def _combinar_plan(
    guardados: list[dict[str, Any]], nuevos: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Plan a guardar cuando la huella no cambió.

    Los contratos de esta corrida reemplazan a los guardados del mismo objetivo; los
    de objetivos que no se eligieron se conservan para reutilizarlos más adelante.
    """
    por_objetivo = {c["objetivo"]: c for c in nuevos}
    combinado = [por_objetivo.pop(c["objetivo"], c) for c in guardados]
    return [*combinado, *por_objetivo.values()]


def _existe_plan_modulo(almacen: AlmacenProyecto, modulo: str) -> bool:
    """Distingue la primera generación de una regeneración por cambio de huella."""
    try:
        almacen.leer_plan_modulo(modulo)
    except ErrorAlmacen:
        return False
    return True


def metas_de(configuracion: Any) -> dict[str, Any]:
    """Metas de la carta (`[umbrales]`) y tope de gasto por corrida de config.toml."""
    umbrales = configuracion.umbrales
    metas: dict[str, Any] = {
        "pass_rate_min": umbrales.pass_rate_min,
        "cobertura_lineas_min": umbrales.cobertura_lineas_min,
        "iteraciones_promedio_max": umbrales.iteraciones_promedio_max,
        "tope_por_corrida_usd": configuracion.presupuesto.tope_por_corrida_usd,
    }
    tope_tokens = getattr(configuracion.presupuesto, "max_tokens_por_corrida", None)
    if tope_tokens is not None:
        metas["tope_tokens_por_corrida"] = tope_tokens
    return metas


def _con_fuente(ruta: Path, modulo: dict[str, Any]) -> dict[str, Any]:
    """Agrega el código del módulo si tiene endpoints: el Planner recorta sus rutas."""
    if not modulo.get("endpoints"):
        return modulo
    try:
        fuente = (ruta / modulo["ruta"]).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return modulo
    return {**modulo, "fuente": fuente}


def _cerrar_run(
    almacen: AlmacenProyecto,
    resumen: ResumenCorrida,
    tipos: list[str] | None = None,
) -> None:
    """Marca el `run.json` como terminado. Si no se puede, la corrida no se pierde."""
    if resumen.run_id is None or not almacen.existe():
        return
    try:
        if resumen.imagen_docker:
            run = almacen.leer_run(resumen.run_id)
            run["imagen_docker"] = resumen.imagen_docker
            almacen.guardar_run(run)
        almacen.finalizar_run(
            resumen.run_id,
            resumen.estado,
            pasaron=resumen.aceptadas,
            fallaron=resumen.bugs_detectados
            + resumen.estancadas
            + resumen.sin_veredicto
            + resumen.requieren_corrida_nueva,
            tipos_prueba=tipos or ["funcion"],
            duracion_s=resumen.duracion_s,
            total_seleccionados=resumen.total_seleccionados,
            total_elegibles=resumen.total_elegibles,
            total_procesados=resumen.total_procesados,
            total_pendientes=resumen.total_pendientes,
            objetivos_omitidos=resumen.objetivos_omitidos,
            tipo_terminacion=resumen.tipo_terminacion,
            motivo=resumen.motivo,
        )
    except Exception as error:  # noqa: BLE001 — run.json dañado: no es motivo de fallo
        _registro.warning(
            "No se pudo cerrar el run.json de %s: %s", resumen.run_id, error
        )


def tipo_terminacion(resumen: ResumenCorrida) -> str:
    """Cómo terminó una corrida, a partir de su resumen ya contado.

    Los objetivos omitidos (sin resultado esperado verificable o con ruta sin
    resolver) no la vuelven «detenida»: solo los pendientes, que son lo que una
    detención dejó sin revisar (`_contar`).
    """
    motivo = (resumen.motivo or "").lower()
    if resumen.cancelada or any(p in motivo for p in ("cancelad", "por el usuario")):
        return "cancelada"
    if any(p in motivo for p in ("token", "presupuesto", "gasto", "tiempo")):
        return "limitada_recursos"
    if resumen.estado == FALLO:
        return "detenida_error"
    if resumen.sin_veredicto > 0 or resumen.estancadas > 0:
        return "completada_con_errores"
    if resumen.total_pendientes > 0:
        return "detenida_error"
    return "completada"


def _cerrar_contabilidad(
    resumen: ResumenCorrida,
    resultados: list[ResultadoCorrida],
    tracker: TokenTracker,
    etapas_entorno: dict[str, float],
) -> None:
    """Cuenta los resultados, suma el entorno y fija el tipo de terminación."""
    _contar(resumen, resultados, tracker)
    resumen.duracion_etapas.update(etapas_entorno)
    if resumen.estado == FIN and resumen.sin_veredicto > 0 and resumen.motivo is None:
        resumen.motivo = (
            f"Corrida completada con errores: {resumen.sin_veredicto} objetivo(s) "
            "quedaron sin veredicto."
        )
    if not resumen.tipo_terminacion or resumen.tipo_terminacion == "completada":
        resumen.tipo_terminacion = tipo_terminacion(resumen)
        if resumen.tipo_terminacion == "cancelada":
            resumen.cancelada = True


def _texto_terminacion(resumen: ResumenCorrida) -> str:
    """Resumen breve de los veredictos para el evento de fin."""
    partes = [
        f"{resumen.aceptadas} aceptada(s)",
        f"{resumen.bugs_detectados} bug(s) detectado(s)",
        f"{resumen.estancadas} estancada(s)",
    ]
    if resumen.sin_veredicto:
        partes.append(f"{resumen.sin_veredicto} sin veredicto")
    if resumen.objetivos_omitidos:
        partes.append(f"{resumen.objetivos_omitidos} sin probar")
    return ", ".join(partes)


def _titulo_final(resumen: ResumenCorrida) -> str:
    """Título del evento de fin según el estado y la cancelación."""
    if resumen.cancelada or (resumen.motivo and "cancelad" in resumen.motivo.lower()):
        return "Corrida cancelada"
    if resumen.estado == FIN:
        return (
            "Corrida completada con errores"
            if resumen.sin_veredicto
            else "Corrida terminada"
        )
    return "Corrida detenida"


def _registrar(
    ruta: Path,
    almacen: AlmacenProyecto,
    resumen: ResumenCorrida,
    resultados: list[ResultadoCorrida],
    tracker: TokenTracker,
    configuracion: Any,
    perfil: str,
    planes_specs: list[dict[str, Any]],
    tipos: list[str] | None = None,
    ia: _ContextoIA | None = None,
    no_soportados: list[dict[str, str]] | None = None,
    fuera_de_la_corrida: list[dict[str, Any]] | None = None,
    al_aviso: Callable[[str], None] | None = None,
) -> None:
    """log.json y results.json, specs y pruebas aprobadas, y cierre del run.json.

    ``no_soportados`` son los componentes de un framework sin soporte (#171): van a
    ``omitidos`` para que el informe diga «componentes no soportados».
    ``fuera_de_la_corrida`` son los archivos JS o TS que no se prueban (EP-11): van
    aparte, sin cambiar los conteos, para que el informe lo avise.
    """
    if resultados:
        rutas = _modulo_corrida().escribir_corrida(
            ruta,
            resultados,
            tracker,
            configuracion.agentes,
            perfil,
            run_id=resumen.run_id,
            metas=metas_de(configuracion),
            rama=detectar_rama(ruta),
            inicio=resumen.inicio,
            fin=resumen.fin,
            duracion_s=resumen.duracion_s,
            duracion_etapas=resumen.duracion_etapas,
            total_seleccionados=resumen.total_seleccionados,
            total_descubiertos=resumen.total_descubiertos,
            total_elegibles=resumen.total_elegibles,
            total_procesados=resumen.total_procesados,
            total_pendientes=resumen.total_pendientes,
            tipo_terminacion=resumen.tipo_terminacion,
            objetivos_omitidos=resumen.objetivos_omitidos,
            omitidos=[
                *(
                    {"modulo": r.modulo, **omitido}
                    for r in resultados
                    for omitido in r.omitidos
                ),
                *(no_soportados or []),
            ],
            fuera_de_la_corrida=fuera_de_la_corrida,
        )
        resumen.run_id = rutas.run_id
        resumen.carpeta = str(rutas.carpeta)
        _explicar(rutas, resumen, perfil, configuracion, tracker, ia)

    if resumen.run_id is not None and almacen.existe():
        huellas_objetivos = huellas_de_objetivos(ruta)
        # La spec de cada objetivo es la del plan del módulo (completa aunque en Humo se
        # haya probado un solo caso) con el perfil con que se creó (#75).
        guardadas = {
            (plan["modulo"], contrato["objetivo"]): (
                contrato,
                plan["perfiles"].get(contrato["objetivo"]),
            )
            for plan in planes_specs
            for contrato in plan["contratos"]
        }
        for resultado in resultados:
            for objetivo in resultado.objetivos:
                if objetivo.contrato is None:
                    continue
                archivo = None
                if objetivo.decision == "accept" and objetivo.codigo:
                    spec_id = id_de_spec(resultado.modulo, objetivo.objetivo)
                    archivo = nombre_prueba(spec_id)
                    almacen.guardar_prueba_aprobada(archivo, objetivo.codigo)
                elif objetivo.decision == "bug_detectado" and objetivo.codigo:
                    try:
                        almacen.guardar_evidencia_bug(
                            objetivo.contrato, objetivo.codigo, resumen.run_id
                        )
                    except (OSError, ErrorAlmacen) as error:
                        mensaje = (
                            f"Se detectó un bug en {objetivo.objetivo}, pero no se pudo "
                            "guardar su evidencia. El resultado se conserva y la "
                            "corrida continúa; revisa el espacio y los permisos de la carpeta."
                        )
                        _registro.warning("%s (%s)", mensaje, error)
                        if al_aviso is not None:
                            al_aviso(mensaje)
                huella = huellas_objetivos.get((resultado.modulo, objetivo.objetivo))
                contrato, perfil_spec = guardadas.get(
                    (resultado.modulo, objetivo.objetivo), (objetivo.contrato, None)
                )
                if contrato is not None and contracts.es_planner_valido(contrato):
                    almacen.guardar_spec(
                        contrato,
                        resumen.run_id,
                        archivo,
                        huella_objetivo=huella,
                        perfil=perfil_spec,
                    )
        registros = []
        for plan in planes_specs:
            guardado = almacen.guardar_plan_modulo(
                plan["modulo"],
                plan["huella"],
                plan["contratos"],
                resumen.run_id,
                plan["accion"],
                perfiles=plan["perfiles"],
            )
            registros.append(
                {
                    "modulo": guardado["modulo"],
                    "huella": guardado["huella"],
                    "run_origen": guardado["run_origen"],
                    "estado": guardado["ultima_accion"],
                }
            )
        if registros:
            try:
                almacen.registrar_specs_run(resumen.run_id, registros)
            except ErrorAlmacen as error:
                _registro.warning(
                    "No se pudo registrar las specs en la corrida %s: %s",
                    resumen.run_id,
                    error,
                )
    _cerrar_run(almacen, resumen, tipos)
