"""Compatibilidad antes de iniciar una corrida (backlog 17).

«Estructura admitida» no significa que dependencias, firmas y tipo de prueba sean
ejecutables. Este módulo dice, antes de gastar tokens, qué se puede probar tal
como está, qué necesita que la persona haga algo y qué QAgent no soporta todavía:

- ``compatible``: hay de dónde sacar el resultado esperado y el lenguaje lo soporta.
- ``requiere_configuracion``: se puede probar si la persona hace algo concreto
  (documentar el resultado, activar la inferencia, corregir ``requirements.txt``).
- ``no_soportado``: QAgent no lo puede probar hoy, con el motivo.

Es una lectura estática, sin IA y sin ejecutar código. La preparación del entorno
(si la imagen con las dependencias ya se construyó) consulta Docker y va aparte, en
``estado_preparacion``, para no frenar la Vista previa.

No promete que la IA vaya a proponer casos válidos: dice qué está fuera de su
alcance antes de intentarlo.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

COMPATIBLE = "compatible"
REQUIERE_CONFIGURACION = "requiere_configuracion"
NO_SOPORTADO = "no_soportado"
ESTADOS = (COMPATIBLE, REQUIERE_CONFIGURACION, NO_SOPORTADO)
#: Requisito informativo del proyecto: no impide ni condiciona la corrida.
AVISO = "aviso"
#: Archivo sin funciones, métodos ni endpoints (un `__init__.py` vacío): no hay
#: nada que probar, que no es lo mismo que no estar soportado.
SIN_OBJETIVOS = "sin_objetivos"

#: Estados de la preparación del entorno aislado.
PREPARACION_VALIDADA = "validada"
PREPARACION_PENDIENTE = "pendiente"
PREPARACION_NO_DISPONIBLE = "no_disponible"
PREPARACION_BLOQUEADA = "bloqueada"
PREPARACION_DESCONOCIDA = "desconocida"

MOTIVO_COMPATIBLE = (
    "Tiene firma y documentación de las que puede salir el resultado esperado."
)
MOTIVO_INFERIDO = (
    "Sin docstring: QAgent inferirá el contrato leyendo el código y su uso. Será una "
    "prueba de regresión, no una comprobación contra un contrato documentado."
)
MOTIVO_SIN_DOC = {
    "python": (
        "Sin docstring y con la inferencia desactivada: agrega un docstring que diga "
        "qué devuelve o qué excepción lanza, o activa «Inferir funciones sin "
        "docstring» en Preparar."
    ),
    "java": (
        "Sin Javadoc: en Java el resultado esperado solo puede salir del Javadoc. "
        "Documenta qué devuelve (@return) o qué excepción lanza (@throws)."
    ),
    "javascript": (
        "Sin JSDoc: solo se podrá probar si los tipos determinan el resultado. "
        "Documenta qué devuelve con @returns o un @example."
    ),
}
MOTIVO_METODO_SIN_DOC = (
    "Método sin docstring: los métodos todavía no se infieren (ADR-017). Documenta "
    "qué devuelve o qué excepción lanza."
)
MOTIVO_LIMITE_INFERENCIA = (
    "Sin docstring y el módulo supera el máximo de {limite} funciones que se infieren "
    "por módulo: agrega un docstring o elige menos funciones sin documentar."
)
MOTIVO_INYECTADAS = (
    "Usa dependencias inyectadas (campos o constructor con @Autowired, @Inject o "
    "Lombok): QAgent no puede construir la clase sin adivinar esas dependencias."
)
MOTIVO_RUTA = (
    "No se pudo saber la ruta completa del endpoint sin ejecutar la app; no se puede "
    "planificar."
)


def _frase(texto: str) -> str:
    """El motivo como frase: mayúscula inicial y punto final (vienen de varios módulos)."""
    texto = (texto or "").strip()
    if not texto:
        return texto
    texto = texto[0].upper() + texto[1:]
    return texto if texto.endswith((".", "?", "!")) else texto + "."


def _estado(estado: str, motivo: str) -> dict[str, str]:
    return {"estado": estado, "motivo": _frase(motivo)}


def _familia(lenguaje: str) -> str:
    return "javascript" if lenguaje in ("javascript", "typescript") else lenguaje


def compatibilidad_funcion(
    funcion: dict[str, Any],
    adaptador: Any,
    *,
    inferencia_activa: bool,
    dentro_del_limite: bool = True,
    limite_inferencia: int | None = None,
) -> dict[str, str]:
    """Compatibilidad de una función o método antes de planificar."""
    motivo = adaptador.motivo_funcion_no_soportada(funcion)
    if motivo:
        return _estado(NO_SOPORTADO, motivo[0].upper() + motivo[1:])
    if funcion.get("dependencias_inyectadas"):
        return _estado(NO_SOPORTADO, MOTIVO_INYECTADAS)
    if funcion.get("docstring"):
        return _estado(COMPATIBLE, MOTIVO_COMPATIBLE)
    familia = _familia(adaptador.lenguaje)
    if funcion.get("tipo_metodo"):
        return _estado(REQUIERE_CONFIGURACION, MOTIVO_METODO_SIN_DOC)
    if familia == "python" and inferencia_activa:
        if dentro_del_limite:
            return _estado(COMPATIBLE, MOTIVO_INFERIDO)
        return _estado(
            REQUIERE_CONFIGURACION,
            MOTIVO_LIMITE_INFERENCIA.format(limite=limite_inferencia),
        )
    return _estado(
        REQUIERE_CONFIGURACION,
        MOTIVO_SIN_DOC.get(
            familia,
            "Sin documentación: documenta qué devuelve o qué excepción lanza.",
        ),
    )


def compatibilidad_endpoint(endpoint: dict[str, Any], adaptador: Any) -> dict[str, str]:
    """Compatibilidad de un endpoint: su contrato sale de la declaración de la ruta."""
    if not endpoint.get("objetivo") or not endpoint.get("resuelta", True):
        return _estado(NO_SOPORTADO, MOTIVO_RUTA)
    motivo = adaptador.motivo_endpoint_no_planificable(endpoint)
    if motivo:
        return _estado(NO_SOPORTADO, motivo[0].upper() + motivo[1:])
    return _estado(
        COMPATIBLE,
        "El resultado esperado sale de la declaración de la ruta (estado y modelos).",
    )


def _conteo() -> dict[str, int]:
    return dict.fromkeys(ESTADOS, 0)


def anotar_modulo(
    modulo: dict[str, Any],
    adaptador: Any,
    *,
    inferencia_activa: bool,
    limite_inferencia: int | None,
) -> dict[str, Any]:
    """Pone ``compatibilidad`` en cada función y endpoint y resume el módulo.

    Returns:
        ``{"estado", "motivo", "objetivos": {estado: n}, "fuera": [...]}``. ``fuera``
        son las declaraciones que el análisis ya dejó fuera de la lista
        (sobrecargas, dependencias inyectadas), para que también se cuenten.
    """
    conteo = _conteo()
    inferidas = 0
    for funcion in modulo.get("funciones", []):
        sin_doc = not funcion.get("docstring")
        dentro = limite_inferencia is None or inferidas < limite_inferencia
        funcion["compatibilidad"] = compatibilidad_funcion(
            funcion,
            adaptador,
            inferencia_activa=inferencia_activa,
            dentro_del_limite=dentro,
            limite_inferencia=limite_inferencia,
        )
        if (
            sin_doc
            and funcion["compatibilidad"]["estado"] == COMPATIBLE
            and funcion["compatibilidad"]["motivo"] == MOTIVO_INFERIDO
        ):
            inferidas += 1
        conteo[funcion["compatibilidad"]["estado"]] += 1
    for endpoint in modulo.get("endpoints", []):
        endpoint["compatibilidad"] = compatibilidad_endpoint(endpoint, adaptador)
        conteo[endpoint["compatibilidad"]["estado"]] += 1
    fuera = [
        {
            "objetivo": f"{m.get('clase')}.{m.get('nombre')}",
            "linea": m.get("linea"),
            "motivo": _frase(
                m.get("motivo")
                or "Método dentro de una clase: todavía no se puede seleccionar."
            ),
        }
        for m in modulo.get("metodos_no_seleccionables", [])
    ] + [
        {
            "objetivo": f.get("nombre"),
            "linea": f.get("linea"),
            "motivo": MOTIVO_INYECTADAS,
        }
        for f in modulo.get("funciones_excluidas", [])
    ]
    conteo[NO_SOPORTADO] += len(fuera)
    return {**_resumen_de(conteo), "objetivos": conteo, "fuera": fuera}


def _resumen_de(conteo: dict[str, int]) -> dict[str, str]:
    """Estado del módulo: compatible si algo se puede probar tal como está."""
    if not any(conteo.values()):
        return _estado(
            SIN_OBJETIVOS, "No tiene funciones, métodos ni endpoints que probar."
        )
    if conteo[COMPATIBLE]:
        motivo = f"{conteo[COMPATIBLE]} objetivo(s) se pueden probar tal como están."
        return _estado(COMPATIBLE, motivo)
    if conteo[REQUIERE_CONFIGURACION]:
        return _estado(
            REQUIERE_CONFIGURACION,
            "Ningún objetivo se puede probar tal como está; algunos sí con "
            "documentación o configuración.",
        )
    return _estado(NO_SOPORTADO, "Ningún objetivo de este archivo se puede probar hoy.")


def requisitos_del_proyecto(raiz: str | os.PathLike[str], adaptador: Any) -> list[dict]:
    """Requisitos del proyecto entero que impiden o condicionan la corrida.

    Solo lecturas estáticas: el ejecutor del lenguaje, la versión de Python y que el
    ``requirements.txt`` se pueda instalar de forma segura en el sandbox.
    """
    carpeta = Path(raiz)
    requisitos: list[dict] = []
    if motivo := adaptador.motivo_no_ejecutable(carpeta):
        requisitos.append(_estado(NO_SOPORTADO, motivo))
    if adaptador.lenguaje != "python":
        return requisitos
    from qagent.lenguajes import VersionPythonNoSoportada

    try:
        adaptador.resolver_version_python(carpeta)
    except VersionPythonNoSoportada as error:
        requisitos.append(_estado(NO_SOPORTADO, str(error)))
    requisitos.extend(_requisitos_de_manifiesto(carpeta))
    requirements = carpeta / "requirements.txt"
    if requirements.is_file() and not requirements.is_symlink():
        from qagent.sandbox.imagen import ErrorConstruccionImagen, revisar_requirements

        try:
            revisar_requirements(requirements.read_bytes())
        except ErrorConstruccionImagen as error:
            requisitos.append(_estado(REQUIERE_CONFIGURACION, str(error)))
        except (OSError, UnicodeError) as error:
            requisitos.append(
                _estado(
                    REQUIERE_CONFIGURACION,
                    f"No se pudo leer requirements.txt ({error}); revisa el archivo.",
                )
            )
    return requisitos


def _requisitos_de_manifiesto(carpeta: Path) -> list[dict]:
    """Dependencias declaradas en pyproject.toml, setup.cfg o setup.py (ADR-017)."""
    from qagent.sandbox.manifiestos_python import (
        ManifiestoNoSoportado,
        avisos_de_manifiesto,
        dependencias_del_manifiesto,
    )

    requisitos = []
    if not (carpeta / "requirements.txt").is_file():
        try:
            dependencias_del_manifiesto(carpeta)
        except (ManifiestoNoSoportado, OSError, UnicodeError) as error:
            requisitos.append(_estado(REQUIERE_CONFIGURACION, str(error)))
    for aviso in avisos_de_manifiesto(carpeta):
        estado = REQUIERE_CONFIGURACION if "setup.py" in aviso else AVISO
        requisitos.append(_estado(estado, aviso))
    return requisitos


def evaluar(
    raiz: str | os.PathLike[str],
    adaptador: Any,
    modulos: list[dict[str, Any]],
    errores: list[dict[str, Any]],
    *,
    inferencia_activa: bool,
    limite_inferencia: int | None,
) -> dict[str, Any]:
    """Compatibilidad del proyecto, por módulo y por objetivo.

    Anota ``compatibilidad`` en cada función y endpoint de ``modulos`` (los de la
    Vista previa) y devuelve el resumen para la interfaz.
    """
    por_modulo: dict[str, dict[str, Any]] = {}
    total = _conteo()
    for modulo in modulos:
        resumen = anotar_modulo(
            modulo,
            adaptador,
            inferencia_activa=inferencia_activa,
            limite_inferencia=limite_inferencia,
        )
        modulo["compatibilidad"] = {
            "estado": resumen["estado"],
            "motivo": resumen["motivo"],
        }
        por_modulo[modulo["ruta"]] = resumen
        for estado, cantidad in resumen["objetivos"].items():
            total[estado] += cantidad
    for error in errores:
        por_modulo[error["ruta"]] = {
            **_estado(
                NO_SOPORTADO,
                f"No se pudo analizar el archivo: {error.get('mensaje') or error.get('tipo')}.",
            ),
            "objetivos": _conteo(),
            "fuera": [],
        }
    requisitos = requisitos_del_proyecto(raiz, adaptador)
    if any(r["estado"] == NO_SOPORTADO for r in requisitos):
        estado = NO_SOPORTADO
    elif any(r["estado"] == REQUIERE_CONFIGURACION for r in requisitos):
        estado = REQUIERE_CONFIGURACION
    else:
        estado = _resumen_de(total)["estado"]
    return {
        "estado": estado,
        "requisitos": requisitos,
        "objetivos": total,
        "modulos": por_modulo,
        "origen": "reglas",
        "tokens": 0,
    }


def estado_preparacion(raiz: str | os.PathLike[str]) -> dict[str, str]:
    """Si el entorno aislado del proyecto ya está preparado y comprobado.

    - ``validada``: la imagen con las dependencias del proyecto ya se construyó: su
      instalación se comprobó y se reutilizará.
    - ``pendiente``: se construirá al iniciar la corrida; hasta entonces no se sabe
      si todas las dependencias se instalan (necesita internet, puede tardar).
    - ``no_disponible``: Docker no está instalado o no responde.
    - ``bloqueada``: un requisito del proyecto impide prepararla.
    - ``desconocida``: no se pudo consultar.

    Consulta Docker con un timeout corto; nunca construye ni descarga nada.
    """
    from qagent.lenguajes import (
        LenguajeNoSoportado,
        VersionPythonNoSoportada,
        adaptador_del_proyecto,
    )
    from qagent.sandbox.estado import estado_docker
    from qagent.sandbox.modelos import ErrorConstruccionImagen

    try:
        adaptador = adaptador_del_proyecto(raiz)
    except (LenguajeNoSoportado, NotADirectoryError, OSError) as error:
        return {"estado": PREPARACION_BLOQUEADA, "mensaje": str(error)}
    docker = estado_docker()
    if docker["estado"] in ("no_iniciado", "no_instalado"):
        return {"estado": PREPARACION_NO_DISPONIBLE, "mensaje": docker["mensaje"]}
    try:
        from qagent.sandbox.cliente import obtener_cliente
        from qagent.sandbox.imagen import construccion_pendiente

        imagen = adaptador.entorno_sandbox(Path(raiz)).imagen
        pendiente = construccion_pendiente(raiz, obtener_cliente(), imagen)
    except VersionPythonNoSoportada as error:
        return {"estado": PREPARACION_BLOQUEADA, "mensaje": str(error)}
    except ErrorConstruccionImagen as error:
        return {"estado": PREPARACION_BLOQUEADA, "mensaje": str(error)}
    except Exception as error:  # noqa: BLE001 — informar nunca debe romper la vista
        return {
            "estado": PREPARACION_DESCONOCIDA,
            "mensaje": f"No se pudo consultar el entorno aislado: {error}",
        }
    if pendiente:
        return {
            "estado": PREPARACION_PENDIENTE,
            "mensaje": (
                "El entorno aislado con las dependencias de este proyecto todavía no "
                "existe: se preparará al iniciar la corrida (necesita internet y puede "
                "tardar minutos). Hasta entonces no se sabe si todas las dependencias "
                "se instalan."
            ),
        }
    return {
        "estado": PREPARACION_VALIDADA,
        "mensaje": (
            "El entorno aislado con las dependencias de este proyecto ya se preparó y "
            "su instalación se comprobó: se reutilizará sin descargar nada."
        ),
    }
