"""Preparación del entorno aislado y avisos del Monitor en una corrida."""

from __future__ import annotations

import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from qagent.orchestrator.corrida_modelo import (
    ENTORNO_CANCELADO,
    ENTORNO_FALLO,
    ENTORNO_LISTO,
    FALLO,
    EntornoEnPreparacion,
    ResumenCorrida,
    _registro,
    _texto_error,
)
from qagent.orchestrator.tiempos import segundos
from qagent.sandbox import (
    LIMITES_POR_DEFECTO,
    ConstruccionCancelada,
    LimitesSandbox,
)

#: Segundos entre avisos del progreso de la construcción al Monitor (#148).
INTERVALO_AVANCE_S = 2.0

#: Motivo por el que un componente de interfaz se omite de la corrida (EP-11b).
MOTIVO_COMPONENTES_NO_SOPORTADOS = (
    "Componentes no soportados ({framework}): QAgent prueba solo los archivos "
    "de lógica .ts/.js de este proyecto."
)


def limites_del_lenguaje(configuracion: Any, lenguaje: str) -> LimitesSandbox:
    """Límites del sandbox de `lenguaje` (#169); `[sandbox]` si no tiene propios."""
    por_lenguaje = getattr(configuracion, "limites_sandbox", None)
    if callable(por_lenguaje):
        return por_lenguaje(lenguaje)
    return getattr(configuracion, "sandbox", LIMITES_POR_DEFECTO)


def _motivo_sin_espacio(ruta: Path, adaptador: Any) -> str | None:
    """Mensaje en lenguaje simple si falta espacio para construir la imagen; None si no.

    Solo se comprueba cuando de verdad hay que construir o descargar (falta la imagen
    base o la de las dependencias del proyecto). Si no se puede saber (Docker cerrado,
    sin imagen que construir…), devuelve None: ese caso ya lo atiende el flujo normal.
    """
    from qagent.sandbox import EspacioInsuficiente
    from qagent.sandbox.cliente import obtener_cliente
    from qagent.sandbox.espacio import verificar_espacio_libre
    from qagent.sandbox.imagen import construccion_pendiente

    try:
        imagen = adaptador.entorno_sandbox(ruta).imagen
        if not construccion_pendiente(ruta, obtener_cliente(), imagen):
            return None
        verificar_espacio_libre()
    except EspacioInsuficiente as error:
        return str(error)
    except Exception as error:  # noqa: BLE001 — comprobar el espacio nunca frena la corrida
        _registro.warning("No se comprobó el espacio libre: %s", error)
    return None


def _preparar_imagen(
    ruta: Path,
    avanzar: Callable[[str], None] | None = None,
    avisar_faltante: Callable[[str], None] | None = None,
    *,
    imagen_base: str | None = None,
    comprobar_librerias: bool = True,
) -> str:
    """Imagen del sandbox del proyecto; construye la imagen base si todavía no existe.

    Sobre la imagen de dependencias se comprueba el entorno e instala las librerías del
    sistema que faltan (issue 142). Las que no se pudieron resolver se avisan.

    Args:
        ruta: carpeta del proyecto.
        avanzar: recibe el avance de la construcción en textos para personas.
        avisar_faltante: recibe un aviso por cada librería del sistema sin resolver.
        imagen_base: imagen indicada por el adaptador; None conserva el valor del sandbox.
        comprobar_librerias: habilita la comprobación específica del entorno Python.
    """
    from qagent.sandbox import (
        ImagenNoEncontrada,
        construir_imagen_base,
        preparar_imagen,
    )
    from qagent.sandbox.cliente import obtener_cliente
    from qagent.sandbox.librerias import asegurar_librerias_sistema
    from qagent.sandbox.limpieza import registrar_uso

    opciones = {"imagen": imagen_base} if imagen_base is not None else {}
    try:
        imagen = preparar_imagen(ruta, avanzar=avanzar, **opciones)
    except ImagenNoEncontrada:
        construir_imagen_base(avanzar=avanzar, **opciones)
        imagen = preparar_imagen(ruta, avanzar=avanzar, **opciones)
    # Las imágenes req- sin uso se borran al abrir la app. Se anota también la de
    # dependencias: la final se construye encima y reinstalar pip puede tardar minutos.
    registrar_uso(imagen)
    if not comprobar_librerias:
        return imagen
    try:
        entorno = asegurar_librerias_sistema(imagen, obtener_cliente(), avanzar)
    except ConstruccionCancelada:
        raise
    except Exception as error:  # noqa: BLE001 — comprobar el entorno nunca frena la corrida
        _registro.warning("No se comprobaron las librerías del sistema: %s", error)
        return imagen
    if entorno.imagen != imagen:
        registrar_uso(entorno.imagen)
    for faltante in entorno.faltantes:
        if avisar_faltante is not None:
            avisar_faltante(faltante["mensaje"])
    return entorno.imagen


def avance_limitado(
    avisar: Callable[[str], None],
    intervalo_s: float = INTERVALO_AVANCE_S,
    reloj: Callable[[], float] = time.monotonic,
    cancelado: Callable[[], bool] | None = None,
) -> Callable[[str], None]:
    """Reenvía el avance de la construcción a `avisar`, sin saturar el Monitor.

    Las fases (empezar a instalar, terminar, comprobar las librerías del sistema)
    siempre pasan; los pasos de pip («Descargando torch…») como mucho uno cada
    `intervalo_s`. Un texto igual al anterior no se repite. Si el usuario canceló,
    lanza `ConstruccionCancelada` para cortar la construcción (#148).
    """
    from qagent.sandbox.imagen import (
        AVISO_BASE,
        AVISO_CONSTRUYENDO,
        AVISO_DEPENDENCIAS,
        AVISO_DEPENDENCIAS_LISTAS,
        AVISO_GUARDANDO,
        AVISO_LISTO,
    )
    from qagent.sandbox.librerias import (
        AVISO_COMPROBANDO,
        AVISO_INSTALANDO,
        AVISO_LISTAS,
    )

    fases = {
        AVISO_BASE,
        AVISO_CONSTRUYENDO,
        AVISO_DEPENDENCIAS,
        AVISO_DEPENDENCIAS_LISTAS,
        AVISO_GUARDANDO,
        AVISO_LISTO,
        AVISO_COMPROBANDO,
        AVISO_LISTAS,
    }
    estado: dict[str, Any] = {"ultimo": None, "momento": None}

    def avanzar(texto: str) -> None:
        if cancelado is not None and cancelado():
            raise ConstruccionCancelada("Corrida cancelada por el usuario.")
        if texto == estado["ultimo"]:
            return
        ahora = reloj()
        reciente = (
            estado["momento"] is not None and ahora - estado["momento"] < intervalo_s
        )
        es_fase = texto in fases or texto.startswith(AVISO_INSTALANDO)  # issue 142
        if reciente and not es_fase:
            return
        estado["ultimo"], estado["momento"] = texto, ahora
        avisar(texto)

    return avanzar


def omitidos_de_interfaz(analisis: dict[str, Any]) -> list[dict[str, str]]:
    """Componentes que no se prueban porque su framework no tiene soporte (#171).

    El adaptador deja en ``framework_ui`` el framework detectado en ``package.json``.
    Si no es React, cada componente JSX analizado aparece como omitido; si no hay
    ninguno (Vue, Astro… viven en archivos que no se analizan), una sola entrada
    avisa para todo el proyecto. Así el informe dice «componentes no soportados».
    """
    framework = analisis.get("framework_ui") or {}
    if framework.get("soportado", True):
        return []
    motivo = MOTIVO_COMPONENTES_NO_SOPORTADOS.format(framework=framework["nombre"])
    omitidos = [
        {
            "modulo": modulo["ruta"],
            "objetivo": componente["nombre"],
            "tipo": "componente",
            "motivo": motivo,
        }
        for modulo in analisis.get("modulos", [])
        for componente in modulo.get("componentes_no_soportados") or []
    ]
    return omitidos or [
        {
            "modulo": "package.json",
            "objetivo": f"Componentes de {framework['nombre']}",
            "tipo": "componente",
            "motivo": motivo,
        }
    ]


def _anunciar_entorno_listo(
    version_python: str | None, avisar_entorno: Callable[..., None]
) -> None:
    """Avisa que el entorno está listo, con la versión de Python si se conoce."""
    avisar_entorno(
        (
            f"Entorno aislado listo con Python {version_python}: se escriben y verifican las pruebas"
            if version_python
            else "Entorno aislado listo: se escriben y verifican las pruebas"
        ),
        ENTORNO_LISTO,
    )


def _esperar_imagen(
    entorno: EntornoEnPreparacion,
    cancelado: Callable[[], bool] | None,
    resumen: ResumenCorrida,
    avisar_entorno: Callable[..., None],
    etapas_entorno: dict[str, float],
    reloj: Callable[[], float],
) -> str | None:
    """Espera la imagen del entorno y registra sus tiempos; None si no hay."""
    inicio_espera = reloj()
    try:
        imagen = entorno.esperar(cancelado)
    except ConstruccionCancelada:
        imagen = None  # el usuario canceló mientras se construía
        avisar_entorno(
            "Se detuvo la preparación del entorno aislado", ENTORNO_CANCELADO
        )
    except Exception as error:  # noqa: BLE001 — lo planificado no se pierde
        imagen = None
        resumen.estado = FALLO
        resumen.tipo_terminacion = "detenida_error"
        resumen.motivo = (
            f"No se pudo preparar el entorno aislado: {_texto_error(error)}"
        )
        avisar_entorno(resumen.motivo, ENTORNO_FALLO, "fallo")
    finally:
        etapas_entorno.update(
            {
                "entorno": entorno.duracion_s,
                "espera_entorno": segundos(inicio_espera, reloj()),
            }
        )
    return imagen
