"""Helpers, estado y arranque interno del puente de escritorio."""

from __future__ import annotations

import threading
from pathlib import Path

from qagent.almacenamiento import AlmacenProyecto, BloqueoCorrida
from qagent.app import bitacora


def _bloqueo_corrida(metodo):
    """Serializa el inicio de corridas/verificaciones/clonados (evita carreras)."""

    def envuelto(self, *args, **kwargs):
        with self._corrida_lock:
            return metodo(self, *args, **kwargs)

    return envuelto


def _resolver_ruta_proyecto(ruta: str, run_id: str | None = None) -> Path:
    """Devuelve la carpeta real del proyecto; en modo demo, `~/.qagent/demo/` si la ruta no existe."""
    from qagent.storage.corrida_demo import CORRIDA_DEMO_ID

    candidata = Path(ruta) if ruta else Path()
    try:
        if ruta and candidata.is_dir():
            return candidata
    except OSError:
        pass
    if run_id == CORRIDA_DEMO_ID or not ruta:
        from qagent.usuario import carpeta_usuario

        # Nunca la carpeta del programa: instalado puede ser de solo lectura (TA-06).
        return carpeta_usuario() / "demo"
    return candidata


def _mostrar_en_explorador(objetivo: Path, seleccionar_archivo: bool = True) -> None:
    """Abre el explorador del sistema mostrando el archivo o carpeta exportada."""
    import os
    import subprocess
    import sys

    try:
        ruta_resuelta = objetivo.resolve()
        if sys.platform == "win32":
            if seleccionar_archivo and ruta_resuelta.is_file():
                subprocess.Popen(  # noqa: S603 -- ruta como argumento, sin shell
                    [
                        str(
                            Path(os.environ.get("WINDIR", r"C:\Windows"))
                            / "explorer.exe"
                        ),
                        f"/select,{ruta_resuelta}",
                    ],
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            elif hasattr(os, "startfile"):
                os.startfile(  # noqa: S606 -- solo se abre la carpeta, no el archivo
                    str(
                        ruta_resuelta
                        if ruta_resuelta.is_dir()
                        else ruta_resuelta.parent
                    )
                )
        elif sys.platform == "darwin":
            cmd = (
                ["open", "-R", str(ruta_resuelta)]
                if seleccionar_archivo
                else ["open", str(ruta_resuelta)]
            )
            subprocess.Popen(  # noqa: S603 -- ejecutable del sistema y ruta como argumento
                cmd,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
    except OSError as exc:
        bitacora.registro.warning("No se pudo abrir el explorador: %s", exc)


def _preparar_almacen(ruta: str) -> None:
    """Crea `.qagent/` en el proyecto abierto (EN-07) sin impedir que se abra.

    Si la carpeta es de solo lectura, el proyecto se abre igual y queda un aviso.
    """
    try:
        AlmacenProyecto(ruta).inicializar()
    except OSError as exc:
        bitacora.registro.warning("No se pudo crear .qagent/ en '%s': %s", ruta, exc)


def _registrar_run(
    ruta: str,
    usa_docker: bool,
    imagen_docker: str | None = None,
    tipos_prueba: list[str] | None = None,
) -> str | None:
    """Crea `.qagent/runs/<run_id>/run.json` de la corrida que empieza (EN-07).

    Solo en proyectos abiertos (con `.qagent/` ya creado al abrirlos). Un fallo al
    escribir no impide la corrida: queda un aviso y se devuelve None. `usa_docker` es
    False en modo demostración: ahí no se ejecuta nada en el sandbox.
    """
    from qagent.almacenamiento import ErrorAlmacen
    from qagent.sandbox.modelos import IMAGEN_BASE

    if tipos_prueba is None:
        tipos_prueba = ["funcion"]
    if usa_docker and imagen_docker is None:
        imagen_docker = IMAGEN_BASE

    almacen = AlmacenProyecto(ruta)
    if not almacen.existe():
        return None
    try:
        run = almacen.crear_run(
            tipos_prueba=tipos_prueba,
            imagen_docker=imagen_docker if usa_docker else None,
        )
    except (OSError, ErrorAlmacen) as exc:
        bitacora.registro.warning(
            "No se pudo registrar la corrida en '%s': %s", ruta, exc
        )
        return None
    bitacora.registro.info("Corrida registrada: %s", almacen.carpeta_run(run["run_id"]))
    return run["run_id"]


def _tomar_bloqueo(ruta: str, run_id: str | None) -> BloqueoCorrida | None:
    """Bloquea la corrida que empieza (#139). Si no se puede, la corrida sigue igual."""
    if run_id is None:
        return None
    try:
        return BloqueoCorrida.tomar(AlmacenProyecto(ruta).carpeta_run(run_id))
    except OSError as exc:
        bitacora.registro.warning(
            "No se pudo bloquear la corrida %s (si la app se cierra, podría verse "
            "como interrumpida aunque siga en otra ventana): %s",
            run_id,
            exc,
        )
        return None


def _corridas_al_abrir(almacen: AlmacenProyecto) -> bool:
    """Cierra las corridas interrumpidas y dice si alguna dejó resultados (#139)."""
    try:
        marcadas = almacen.cerrar_interrumpidas()
    except OSError as exc:
        bitacora.registro.warning("No se revisaron las corridas interrumpidas: %s", exc)
        marcadas = []
    if marcadas:
        bitacora.registro.info(
            "Corridas interrumpidas (la app se cerró a mitad): %s", ", ".join(marcadas)
        )
    return almacen.tiene_corridas_con_resultados()


def _ocultar_claves_en_bitacora() -> None:
    """Vuelve a leer `.env` para que la bitácora oculte también una clave recién guardada.

    Actualiza los dos filtros: el de la bitácora de la corrida y el del logger raíz.
    """
    from qagent.config import Claves, instalar_filtro_logs, leer_env
    from qagent.config import carga as config_carga

    SEGUIMIENTO.firma_env = _firma_env()
    try:
        claves = Claves(leer_env(config_carga.RUTA_ENV))
    except (OSError, UnicodeDecodeError):
        return
    if SEGUIMIENTO.activo:  # el filtro raíz lo instaló main(); en las pruebas no existe
        instalar_filtro_logs(claves)
    bitacora.configurar_registro(claves)


_LIBERANDO_ESPACIO = threading.Lock()


DOCKER_RESPONDE = ("ok", "sin_imagen")


class _Seguimiento:
    """Lo que la app abierta vigila para no quedarse con lo que leyó al iniciar (#251).

    Atributos:
        activo: lo enciende `main`; apagado en las pruebas.
        firma_env: fecha y tamaño del `.env` la última vez que se leyeron sus claves.
        limpieza: "sin_programar", "pendiente" (Docker no respondió), "en_curso" o "hecha".
    """

    def __init__(self) -> None:
        self.activo = False
        self.firma_env: tuple[int, int] | None = None
        self.limpieza = "sin_programar"
        self.candado = threading.Lock()


SEGUIMIENTO = _Seguimiento()


def _firma_env() -> tuple[int, int] | None:
    """Fecha de modificación y tamaño del `.env`, o None si no existe."""
    from qagent.config import carga as config_carga

    try:
        datos = Path(config_carga.RUTA_ENV).stat()
    except OSError:
        return None
    return datos.st_mtime_ns, datos.st_size


def _refrescar_claves_si_cambio() -> bool:
    """Si el `.env` cambió (por ejemplo, editado a mano), la bitácora oculta sus claves nuevas.

    Returns:
        True si se volvieron a leer las claves.
    """
    if _firma_env() == SEGUIMIENTO.firma_env:
        return False
    _ocultar_claves_en_bitacora()
    return True


def _reintentar_limpieza() -> bool:
    """Lanza la limpieza del sandbox si quedó pendiente porque Docker no respondía.

    Returns:
        True si se lanzó (una sola a la vez).
    """
    with SEGUIMIENTO.candado:
        if SEGUIMIENTO.limpieza != "pendiente":
            return False
        SEGUIMIENTO.limpieza = "en_curso"
    threading.Thread(
        target=_limpiar_sandbox, name="limpieza-sandbox", daemon=True
    ).start()
    return True


def _limpiar_sandbox_tras_corrida() -> bool:
    """Lanza la limpieza del sandbox en segundo plano al terminar una corrida (#267).

    Una construcción cortada o una corrida interrumpida deja contenedores y capas en
    Docker; limpiar solo al abrir la app deja que se acumulen mientras está abierta. Va en
    un hilo aparte para no retrasar el fin de la corrida ni mantenerla «en curso». Una
    sola limpieza a la vez, y solo con la app abierta de verdad (no en las pruebas).

    Returns:
        True si se lanzó.
    """
    if not SEGUIMIENTO.activo:
        return False
    with SEGUIMIENTO.candado:
        if SEGUIMIENTO.limpieza == "en_curso":
            return False
        SEGUIMIENTO.limpieza = "en_curso"
    threading.Thread(
        target=_limpiar_sandbox, name="limpieza-sandbox", daemon=True
    ).start()
    return True


def _registrar_estado_configuracion() -> None:
    """Lee config.toml y .env al iniciar y deja en consola un resumen sin claves (EN-06)."""
    from qagent.config import (
        aplicar_simulacion_desde_env,
        cargar_configuracion,
        instalar_filtro_logs,
    )

    # QAGENT_FAKE_LLM=1 en el .env también activa la IA simulada para todo el programa.
    aplicar_simulacion_desde_env()
    from qagent.config import carga as config_carga

    carga = cargar_configuracion(ruta_local=config_carga.RUTA_CONFIG_LOCAL)
    instalar_filtro_logs(carga.claves)
    bitacora.configurar_registro(carga.claves)  # bitácora de la corrida en la consola
    if carga.simulado:
        bitacora.registro.info(
            "IA simulada activa (QAGENT_FAKE_LLM=1): 0 tokens, no se usan claves."
        )
    if carga.ok:
        bitacora.registro.info("Configuración cargada: config.toml y claves en orden.")
    else:
        bitacora.registro.warning(
            "Configuración incompleta: no se podrán iniciar corridas."
        )
        for aviso in carga.avisos:
            bitacora.registro.warning("  - %s", aviso)


def _limpiar_sandbox() -> None:
    """Limpia lo que el sandbox dejó en Docker (en segundo plano): al abrir y al terminar cada corrida.

    Borra contenedores huérfanos y de construcciones cortadas, capas sin etiqueta, imágenes
    sin uso o fuera del tope de espacio (#267). La caché de compilación no se toca aquí.

    Si Docker no respondió, la limpieza queda pendiente y se reintenta cuando el motor
    pase a estar activo (#251).
    """
    from qagent.sandbox.limpieza import limpiar_al_iniciar

    resultado = limpiar_al_iniciar()
    with SEGUIMIENTO.candado:
        SEGUIMIENTO.limpieza = "hecha" if resultado else "pendiente"
    if resultado.get("contenedores"):
        bitacora.registro.info(
            "Sandbox: se borraron %d contenedores de corridas interrumpidas.",
            resultado["contenedores"],
        )
    if resultado.get("construcciones"):
        bitacora.registro.info(
            "Sandbox: se borraron %d contenedores de construcciones interrumpidas.",
            resultado["construcciones"],
        )
    if resultado.get("capas"):
        bitacora.registro.info(
            "Sandbox: se borraron %d capas sin etiqueta (%s).",
            resultado["capas"],
            _texto_tamano(resultado.get("capas_bytes", 0)),
        )
    if resultado.get("imagenes"):
        bitacora.registro.info(
            "Sandbox: se borraron imágenes derivadas sin uso o fuera del tope de "
            "espacio: %s.",
            ", ".join(resultado["imagenes"]),
        )


def _texto_tamano(bytes_: float) -> str:
    """«1,2 GB» o «350 MB» para la bitácora."""
    gb = bytes_ / 1024**3
    if gb >= 1:
        return f"{gb:.1f} GB".replace(".", ",")
    return f"{bytes_ / 1024**2:.0f} MB"
