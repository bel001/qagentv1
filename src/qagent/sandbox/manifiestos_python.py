"""Dependencias de un proyecto Python a partir de sus manifiestos (backlog 10, ADR-017).

Lee ``pyproject.toml`` (PEP 621 o Poetry) y ``setup.cfg`` como texto y arma una
lista PEP 508 equivalente a un ``requirements.txt``. Nunca ejecuta nada del
proyecto: ``setup.py`` no se lee, porque leerlo de verdad es ejecutarlo.

Lo que no se puede instalar de forma segura (dependencias locales, de Git o por
URL) no se omite en silencio: se rechaza con el nombre de la dependencia, para
que la persona sepa qué cambiar.
"""

from __future__ import annotations

import configparser
import re
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from packaging.requirements import InvalidRequirement, Requirement

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python 3.10
    import tomli as tomllib

#: Tamaño máximo de un manifiesto que se lee (un pyproject real pesa unos KB).
LIMITE_BYTES = 1_000_000
#: Archivos que el proyecto puede tener y que no se usan, para decirlo.
LOCKFILES = ("poetry.lock", "uv.lock", "Pipfile.lock", "pdm.lock")

_POETRY_FUENTES_NO_SOPORTADAS = ("path", "git", "url", "file")


class ManifiestoNoSoportado(ValueError):
    """El manifiesto declara algo que QAgent no instala de forma segura."""


@dataclass(frozen=True)
class DependenciasManifiesto:
    """Dependencias leídas de un manifiesto.

    Atributos:
        origen: texto para personas («pyproject.toml ([project].dependencies)»).
        requisitos: líneas PEP 508, en el orden del manifiesto y sin repetidas.
    """

    origen: str
    requisitos: tuple[str, ...]

    def como_requirements(self) -> bytes:
        """El contenido equivalente de un ``requirements.txt``."""
        return ("\n".join(self.requisitos) + "\n").encode("utf-8")


def _leer(archivo: Path) -> str:
    if archivo.is_symlink() or archivo.stat().st_size > LIMITE_BYTES:
        raise ManifiestoNoSoportado(
            f"{archivo.name} es un enlace o es demasiado grande para leerlo."
        )
    return archivo.read_text(encoding="utf-8-sig")


def _requisito(texto: str, origen: str) -> str:
    """Valida una línea PEP 508; rechaza URLs y rutas con el nombre del paquete."""
    try:
        requisito = Requirement(texto.strip())
    except InvalidRequirement as error:
        raise ManifiestoNoSoportado(
            f"{origen}: la dependencia «{texto.strip()}» no es válida ({error})."
        ) from error
    if requisito.url is not None:
        raise ManifiestoNoSoportado(
            f"{origen}: la dependencia «{requisito.name}» viene de una URL, de Git o "
            "de una carpeta local. QAgent solo instala paquetes publicados en PyPI: "
            "publícala o declárala por nombre y versión."
        )
    return str(requisito)


def _sin_repetidas(lineas: Iterable[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(lineas))


# --- PEP 621 -----------------------------------------------------------------------


def _pep621(raiz: Path, datos: dict[str, Any]) -> DependenciasManifiesto | None:
    proyecto = datos.get("project")
    if not isinstance(proyecto, dict):
        return None
    origen = "pyproject.toml ([project].dependencies)"
    if "dependencies" in (proyecto.get("dynamic") or []):
        return _dinamicas(raiz, datos)
    dependencias = proyecto.get("dependencies") or []
    if not isinstance(dependencias, list):
        raise ManifiestoNoSoportado(f"{origen} no es una lista.")
    return DependenciasManifiesto(
        origen, _sin_repetidas(_requisito(str(d), origen) for d in dependencias)
    )


def _dinamicas(raiz: Path, datos: dict[str, Any]) -> DependenciasManifiesto:
    """``dynamic = ["dependencies"]`` leídas de los archivos que indica setuptools."""
    dinamico = (
        ((datos.get("tool") or {}).get("setuptools") or {}).get("dynamic") or {}
    ).get("dependencies")
    archivos = dinamico.get("file") if isinstance(dinamico, dict) else None
    if isinstance(archivos, str):
        archivos = [archivos]
    if not archivos:
        raise ManifiestoNoSoportado(
            "pyproject.toml declara las dependencias como dinámicas sin indicar de qué "
            "archivo salen: decláralas en [project].dependencies o en requirements.txt."
        )
    lineas: list[str] = []
    for nombre in archivos:
        ruta = (raiz / str(nombre)).resolve()
        if not ruta.is_relative_to(raiz.resolve()) or not ruta.is_file():
            raise ManifiestoNoSoportado(
                f"pyproject.toml toma las dependencias de «{nombre}», que no está en el "
                "proyecto."
            )
        lineas.extend(_lineas_de_requirements(_leer(ruta), str(nombre)))
    return DependenciasManifiesto(
        f"pyproject.toml (dependencias dinámicas desde {', '.join(map(str, archivos))})",
        _sin_repetidas(lineas),
    )


def _lineas_de_requirements(texto: str, origen: str) -> list[str]:
    lineas = []
    for linea in texto.splitlines():
        limpia = linea.split(" #", 1)[0].strip()
        if not limpia or limpia.startswith("#"):
            continue
        if limpia.startswith("-"):
            raise ManifiestoNoSoportado(
                f"{origen}: la opción de pip «{limpia.split()[0]}» no se admite; usa "
                "nombres y versiones de PyPI."
            )
        lineas.append(_requisito(limpia, origen))
    return lineas


# --- Poetry ------------------------------------------------------------------------


def _version_poetry(restriccion: str, nombre: str) -> str:
    """``^1.2.3`` -> ``>=1.2.3,<2.0.0``; ``~1.2`` -> ``>=1.2,<1.3``; ``*`` -> ``""``."""
    texto = restriccion.strip()
    if texto in ("", "*"):
        return ""
    if texto[0] in "^~" and not texto.startswith("~="):
        version = texto[1:].strip()
        partes = version.split(".")
        if not all(p.isdigit() for p in partes):
            raise ManifiestoNoSoportado(
                f"pyproject.toml (Poetry): la versión «{texto}» de «{nombre}» no se "
                "puede traducir; escríbela como rango (>=1.2,<2.0)."
            )
        numeros = [int(p) for p in partes]
        if texto[0] == "^":
            posicion = next((i for i, n in enumerate(numeros) if n != 0), 0)
            posicion = min(posicion, len(numeros) - 1)
        else:
            posicion = 0 if len(numeros) == 1 else 1
        tope = numeros[: posicion + 1]
        tope[-1] += 1
        tope += [0] * (len(numeros) - len(tope))
        return f">={version},<{'.'.join(map(str, tope))}"
    if re.fullmatch(r"\d+(\.\d+)*", texto):
        return f"=={texto}"
    return ",".join(p.strip() for p in texto.split(","))


def _poetry(datos: dict[str, Any]) -> DependenciasManifiesto | None:
    poetry = (datos.get("tool") or {}).get("poetry")
    if not isinstance(poetry, dict) or "dependencies" not in poetry:
        return None
    origen = "pyproject.toml ([tool.poetry.dependencies])"
    lineas = []
    for nombre, valor in (poetry.get("dependencies") or {}).items():
        if nombre.lower() == "python":
            continue
        extras: list[str] = []
        marcadores = ""
        if isinstance(valor, list):
            raise ManifiestoNoSoportado(
                f"{origen}: «{nombre}» declara varias restricciones según la plataforma; "
                "QAgent no elige una. Decláralas en requirements.txt."
            )
        if isinstance(valor, dict):
            fuente = next(
                (c for c in _POETRY_FUENTES_NO_SOPORTADAS if c in valor), None
            )
            if fuente is not None:
                raise ManifiestoNoSoportado(
                    f"{origen}: «{nombre}» se instala desde {fuente} (dependencia local o "
                    "externa a PyPI). QAgent solo instala paquetes publicados en PyPI."
                )
            if valor.get("optional"):
                continue
            extras = [str(e) for e in valor.get("extras") or []]
            marcadores = str(valor.get("markers") or "")
            valor = valor.get("version", "*")
        version = _version_poetry(str(valor), nombre)
        texto = nombre + (f"[{','.join(extras)}]" if extras else "") + version
        if marcadores:
            texto += f"; {marcadores}"
        lineas.append(_requisito(texto, origen))
    return DependenciasManifiesto(origen, _sin_repetidas(lineas))


# --- setup.cfg ---------------------------------------------------------------------


def _setup_cfg(raiz: Path) -> DependenciasManifiesto | None:
    archivo = raiz / "setup.cfg"
    if not archivo.is_file():
        return None
    lector = configparser.ConfigParser(interpolation=None)
    try:
        lector.read_string(_leer(archivo))
    except configparser.Error as error:
        raise ManifiestoNoSoportado(f"setup.cfg no se puede leer ({error}).") from error
    if not lector.has_option("options", "install_requires"):
        return None
    origen = "setup.cfg ([options].install_requires)"
    return DependenciasManifiesto(
        origen,
        _sin_repetidas(
            _lineas_de_requirements(lector.get("options", "install_requires"), origen)
        ),
    )


# --- entrada pública -----------------------------------------------------------------


def dependencias_del_manifiesto(raiz: str | Path) -> DependenciasManifiesto | None:
    """Dependencias declaradas en ``pyproject.toml`` o ``setup.cfg``, o None si no hay.

    ``requirements.txt`` tiene prioridad y lo lee el sandbox como siempre: esta
    función es para los proyectos que no lo tienen.

    Raises:
        ManifiestoNoSoportado: si el manifiesto declara algo que no se instala de
            forma segura, con el nombre de la dependencia y qué hacer.
    """
    carpeta = Path(raiz)
    pyproject = carpeta / "pyproject.toml"
    if pyproject.is_file():
        try:
            datos = tomllib.loads(_leer(pyproject))
        except tomllib.TOMLDecodeError as error:
            raise ManifiestoNoSoportado(
                f"pyproject.toml no es TOML válido ({error})."
            ) from error
        for lector in (_pep621, lambda _raiz, d: _poetry(d)):
            encontradas = lector(carpeta, datos)
            if encontradas is not None:
                return encontradas
    return _setup_cfg(carpeta)


def avisos_de_manifiesto(raiz: str | Path) -> list[str]:
    """Lo que el proyecto declara y QAgent no usa, para decirlo antes de la corrida."""
    carpeta = Path(raiz)
    avisos = []
    if (carpeta / "setup.py").is_file() and not (
        (carpeta / "requirements.txt").is_file() or _declara_en_pyproject_o_cfg(carpeta)
    ):
        avisos.append(
            "El proyecto declara sus dependencias en setup.py, que QAgent no lee porque "
            "leerlo es ejecutarlo. Decláralas en pyproject.toml ([project].dependencies) "
            "o en requirements.txt."
        )
    usados = [nombre for nombre in LOCKFILES if (carpeta / nombre).is_file()]
    if usados:
        avisos.append(
            f"{', '.join(usados)} no se usa: se instalan los rangos declarados, así que "
            "las versiones pueden no ser exactamente las del lockfile."
        )
    return avisos


def _declara_en_pyproject_o_cfg(carpeta: Path) -> bool:
    try:
        return dependencias_del_manifiesto(carpeta) is not None
    except ManifiestoNoSoportado:
        return True
