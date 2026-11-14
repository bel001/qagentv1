"""Decisiones de ejecución Java basadas en etapas Maven e informes JUnit (#182).

No sustituye la validación del oráculo ni el guardrail de generación de #184.
"""

from __future__ import annotations

import re
from pathlib import Path

_PATRON_ERROR_JAVAC = re.compile(r"(\S+\.java):\[(\d+)(?:,\s*\d+)?\]\s*(.+)")


def _extraer_error_javac(salida: str) -> str | None:
    """Extrae la primera línea de error de javac con archivo y línea."""
    for linea in salida.splitlines():
        match = _PATRON_ERROR_JAVAC.search(linea)
        if match:
            archivo, linea_no, mensaje = match.groups()
            return f"{archivo}:{linea_no}: {mensaje.strip()}"
    # Formato alternativo: /path/File.java:10: error: ...
    for linea in salida.splitlines():
        if ".java:" in linea and "error" in linea.lower():
            return linea.strip()[-300:]
    return None


from typing import Any

from qagent.lenguajes.base import Clasificacion
from qagent.lenguajes.java_ejecucion import MARCA
from qagent.lenguajes.java_generacion import ReglasGeneracionJava
from qagent.lenguajes.java_junit import interpretar_junit_java
from qagent.lenguajes.treesitter import extraer_errores_sintaxis, obtener_parser
from qagent.sandbox.informe_pytest import JUnitInvalido
from qagent.sandbox.modelos import ResultadoSandbox


def clasificar_java(resultado: ResultadoSandbox) -> Clasificacion | None:
    """Distingue errores técnicos y aserciones; nunca acepta suites vacías u omitidas.

    La etapa proyecto impide regenerar una prueba para corregir código ajeno.
    Un fallo de compilación en la etapa prueba consume un intento del Generator.
    Un timeout, OOM o XML ausente/incoherente no demuestra un bug.
    """

    def sin(motivo: str, detalle: str) -> Clasificacion:
        return Clasificacion(
            "entorno",
            detalle,
            motivo,
            detener_corrida=motivo == "error_compilacion_proyecto",
        )

    if resultado.timed_out:
        return sin("timeout_sandbox", "Java excedió el tiempo máximo del sandbox.")
    if resultado.oom_killed:
        return sin("memoria_sandbox", "Java excedió la memoria del sandbox.")
    salida = resultado.stdout + "\n" + resultado.stderr
    if "Surefire is going to kill self fork JVM" in salida:
        return sin(
            "terminacion_jvm",
            "Surefire forzó el cierre de la JVM de pruebas. Sus datos de cobertura pueden estar incompletos; repite la corrida con recursos disponibles.",
        )
    etapas = re.findall(
        re.escape(MARCA) + r"(proyecto|prueba|ejecucion|cobertura)\b", salida
    )
    etapa = etapas[-1] if etapas else None
    if etapa == "proyecto":
        detalle_error = _extraer_error_javac(salida)
        mensaje = "El proyecto Java no pudo compilarse o prepararse."
        if detalle_error:
            mensaje += " " + detalle_error
        return sin(
            "error_compilacion_proyecto",
            mensaje + "\n" + salida[-4000:],
        )
    if etapa == "prueba":
        return Clasificacion(
            "error_test", "La prueba Java no compila: " + salida[-4000:]
        )
    if etapa == "cobertura":
        return sin(
            "error_cobertura",
            "No se pudo producir el informe JaCoCo. " + salida[-4000:],
        )
    try:
        informe = interpretar_junit_java(resultado.junit_xml or "")
    except JUnitInvalido:
        return sin(
            "informe_pruebas_invalido",
            "No hay un informe JUnit válido para juzgar el método. " + salida[-4000:],
        )
    if informe["total"] == informe["omitidos"]:
        return sin(
            "pruebas_no_ejecutadas", "JUnit omitió todas las pruebas del objetivo."
        )
    if informe["errores"]:
        tipos_error = {
            (c.get("tipo_error") or "").rsplit(".", 1)[-1]
            for c in informe["casos"]
            if c["resultado"] == "error"
        }
        entorno = {
            "OutOfMemoryError",
            "StackOverflowError",
            "ClassNotFoundException",
            "NoClassDefFoundError",
            "UnsupportedClassVersionError",
            "VerifyError",
            "ExceptionInInitializerError",
            "MockitoException",
            "SurefireBooterForkException",
        }
        errores = [c for c in informe["casos"] if c["resultado"] == "error"]
        objetivo = getattr(resultado, "objetivo", None)
        en_objetivo = not objetivo or any(
            re.search(
                r"\bat\s+(?:[\w$]+\.)*"
                + r"[.$]".join(re.escape(parte) for parte in objetivo.split("."))
                + r"\(",
                c.get("traza") or "",
            )
            for c in errores
        )
        if (tipos_error and tipos_error <= entorno) or not en_objetivo:
            return sin(
                "error_ejecucion_pruebas",
                "JUnit informó errores técnicos; no prueban un incumplimiento del contrato.",
            )
        # Una excepción no esperada del código probado (ArithmeticException,
        # NullPointerException, IndexOutOfBoundsException...) es un bug, no un
        # fallo del entorno (J2).
        return Clasificacion(
            "fallo_asercion",
            "El método lanzó una excepción no esperada: "
            + ", ".join(sorted(tipos_error)),
        )
    if not informe["fallaron"]:
        if resultado.exit_code != 0:
            return sin(
                "salida_runner_incoherente", "JUnit pasó, pero Maven terminó con error."
            )
        return None
    if resultado.exit_code != 1:
        return sin(
            "salida_runner_incoherente",
            "JUnit informó fallos con un código de salida inesperado.",
        )
    tipos = {c.get("tipo_error") for c in informe["casos"] if c["resultado"] == "fallo"}
    if tipos <= {
        "org.opentest4j.AssertionFailedError",
        "org.opentest4j.MultipleFailuresError",
        "java.lang.AssertionError",
    }:
        return Clasificacion(
            "fallo_asercion", "La aserción JUnit del contrato no se cumplió."
        )
    return sin(
        "fallo_junit_no_clasificado",
        "JUnit informó un fallo que no se reconoce como aserción del contrato.",
    )


class ReglasRevisionJava(ReglasGeneracionJava):
    """Conserva el oráculo de #184 y añade clasificación y ubicación para #182."""

    def error_de_sintaxis(self, codigo: str) -> str | None:
        """Devuelve errores del parser Java sin compilar ni ejecutar el test."""
        raiz = obtener_parser("java").parse(codigo.encode("utf-8")).root_node
        return "; ".join(extraer_errores_sintaxis(raiz)) if raiz.has_error else None

    def clasificar_salida(
        self, salida: str, contrato: dict[str, Any], raiz: Path
    ) -> Clasificacion | None:
        """La clasificación Java requiere ResultadoSandbox y su XML, no solo texto."""
        return None

    def rango_de_objetivo(
        self, raiz: Path, modulo: str, nombre: str
    ) -> tuple[int, int] | None:
        """Ubica un método por clase y nombre; una sobrecarga no elige al azar."""
        # J10: no se analiza todo el proyecto; se lee solo el archivo del objetivo.
        try:
            arbol = obtener_parser("java").parse((raiz / modulo).read_bytes()).root_node
        except OSError:
            return None
        encontrados = []

        def visitar(nodo, clase=""):
            if nodo.type in {
                "class_declaration",
                "interface_declaration",
                "enum_declaration",
                "record_declaration",
            }:
                simple = nodo.child_by_field_name("name").text.decode("utf-8")
                clase = f"{clase}.{simple}" if clase else simple
            if nodo.type == "method_declaration":
                simple = nodo.child_by_field_name("name").text.decode("utf-8")
                if f"{clase}.{simple}" == nombre:
                    encontrados.append(
                        (nodo.start_point.row + 1, nodo.end_point.row + 1)
                    )
                return
            for hijo in nodo.named_children:
                visitar(hijo, clase)

        visitar(arbol)
        return encontrados[0] if len(encontrados) == 1 else None
