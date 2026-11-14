"""Comando y preparación estática de una prueba Java para el sandbox (#182).

No ejecuta procesos en el anfitrión. preparar_java recibe exclusivamente la
copia desechable; Maven se invoca después dentro del sandbox común sin red.
"""

from __future__ import annotations

import copy
import re
import xml.etree.ElementTree as ET
from pathlib import Path, PurePosixPath

from qagent.lenguajes.treesitter import obtener_parser
from qagent.sandbox.informe_pytest import LIMITE_XML, JUnitInvalido
from qagent.sandbox.modelos import ErrorPreparacionSandbox
from qagent.xml_seguro import parsear_xml

POM = ".qagent-junit.xml"
TESTS = ".qagent-junit-tests"
TARGET = ".qagent-junit-target"
JDK = ".qagent-junit-jdk"
MARCA = "QAGENT_JAVA_ETAPA="
_NS = "http://maven.apache.org/POM/4.0.0"
_BASE = "/work/proyecto/"
_RECETA = Path(__file__).resolve().parents[1] / "sandbox/java/calentamiento/pom.xml"


def comando_java(modulo: str) -> list[str]:
    """Devuelve etapas Maven offline separadas, con JaCoCo aun si JUnit falla.

    Requiere preparar_java en la copia antes de ejecutarse. Las rutas del comando
    son constantes; modulo se valida y no se interpola en un script de shell.
    La etapa final y el código de salida permiten distinguir errores técnicos.
    """
    ruta = PurePosixPath(modulo.replace("\\", "/"))
    if (
        ruta.parts[:3] != ("src", "main", "java")
        or ruta.suffix != ".java"
        or any(p in {"", ".", ".."} for p in modulo.replace("\\", "/").split("/"))
        or ":" in modulo
        or not all(
            p.replace("$", "_").isidentifier() for p in (*ruta.parts[3:-1], ruta.stem)
        )
    ):
        raise ValueError(
            "Se requiere una fuente Maven src/main/java/paquete/Clase.java."
        )
    receta = _xml(_RECETA.read_text(encoding="utf-8"))
    version = receta.findtext("{*}properties/{*}jacoco.version")
    if not version or not re.fullmatch(r"[0-9]+(?:\.[0-9]+)+", version):
        raise ValueError("La receta Java no declara una versión JaCoCo válida.")
    script = f"""set -u
# J5: el JDK se elige según maven.compiler.release/source del proyecto. El 25 es el
# predeterminado de la imagen; 17 y 21 se instalan aparte en el Dockerfile.
jdk="$(cat /work/proyecto/{JDK} 2>/dev/null || echo 21)"
case "$jdk" in
  17|21)
    export JAVA_HOME="/usr/lib/jvm/java-${{jdk}}-openjdk-amd64"
    export PATH="$JAVA_HOME/bin:$PATH"
    ;;
esac
ejecutar_maven() {{
  mvn --offline --batch-mode --no-transfer-progress -Dmaven.repo.local=/opt/qagent/m2 -f /work/proyecto/{POM} "$@"
}}
echo '{MARCA}proyecto'
if [ ! -f "/work/proyecto/$1" ]; then
  echo 'La fuente Java seleccionada no existe en la copia' >&2
  exit 1
fi
ejecutar_maven compile || exit $?
echo '{MARCA}prueba'
ejecutar_maven test-compile || exit $?
echo '{MARCA}ejecucion'
ejecutar_maven org.jacoco:jacoco-maven-plugin:{version}:prepare-agent surefire:test
estado_test=$?
if [ "$estado_test" -ne 0 ] && ! find /out/junit-raw -name 'TEST-*.xml' -print -quit 2>/dev/null | grep -q .; then
  exit "$estado_test"
fi
echo '{MARCA}cobertura'
ejecutar_maven org.jacoco:jacoco-maven-plugin:{version}:report
estado_cobertura=$?
if [ "$estado_cobertura" -ne 0 ]; then exit "$estado_cobertura"; fi
if [ ! -f /out/jacoco-report/jacoco.xml ]; then
  echo 'JaCoCo no produjo el informe XML esperado' >&2
  exit 1
fi
cp /out/jacoco-report/jacoco.xml /out/jacoco.xml || exit $?
echo '{MARCA}ejecucion'
exit "$estado_test"
"""
    return ["sh", "-c", script, "qagent-java", ruta.as_posix()]


def preparar_java(copia: Path, pruebas: Path) -> None:
    """Crea POM, fuente de prueba y salidas reservadas en la copia, sin compilar.

    Conserva el POM y src/test originales. Admite Maven de un módulo sin padre;
    añade herramientas de la receta del equipo y mantiene las dependencias del
    proyecto. Solo incluye una fuente recibida; no copia pruebas preexistentes.
    Errores de preparación se marcan como proyecto o prueba para su clasificación.
    """
    etapa = "proyecto"
    try:
        for nombre in (POM, TESTS, TARGET, JDK):
            ruta = copia / nombre
            if ruta.exists() or ruta.is_symlink():
                raise ValueError(
                    "El proyecto contiene una ruta reservada de QAgent Java."
                )
        original = _xml(_leer(copia / "pom.xml", copia))
        if original.tag not in {"project", f"{{{_NS}}}project"}:
            raise ValueError("Se requiere un pom.xml Maven válido.")
        if (
            original.find("{*}parent") is not None
            or original.find(".//{*}modules") is not None
        ):
            raise ValueError(
                "La ejecución requiere resolver primero la herencia o los módulos Maven."
            )
        # J5: Lombok anterior a 1.18.40 no compila con el JDK del sandbox.
        _ns_local = f"{{{_NS}}}" if original.tag.startswith("{") else ""
        version_lombok = _version_lombok(original, _ns_local)
        if version_lombok is not None and _lombok_incompatible(
            original, _ns_local, version_lombok
        ):
            raise ValueError(
                f"Lombok {version_lombok} no es compatible con el JDK del sandbox; "
                "actualiza a 1.18.40 o superior."
            )
        (copia / JDK).write_text(_version_jdk(original, _ns_local), encoding="utf-8")
        receta = _xml(_RECETA.read_text(encoding="utf-8"))
        preparado = copy.deepcopy(original)
        ns = f"{{{_NS}}}" if preparado.tag.startswith("{") else ""
        build = _hijo(preparado, ns + "build")
        for nombre, valor in (
            ("directory", _BASE + TARGET),
            ("outputDirectory", _BASE + TARGET + "/classes"),
            ("testOutputDirectory", _BASE + TARGET + "/test-classes"),
            ("testSourceDirectory", _BASE + TESTS),
        ):
            _hijo(build, ns + nombre).text = valor
        plugins = _hijo(build, ns + "plugins")
        propiedades = {
            p.tag.rsplit("}", 1)[-1]: p.text for p in receta.find("{*}properties")
        }
        propiedades_proyecto = _hijo(preparado, ns + "properties")
        if (
            propiedades_proyecto.find(ns + "maven.compiler.release") is None
            and propiedades_proyecto.find(ns + "maven.compiler.source") is None
        ):
            _hijo(
                propiedades_proyecto, ns + "maven.compiler.release"
            ).text = propiedades["maven.compiler.release"]
        for nombre in (
            "maven-resources-plugin",
            "maven-compiler-plugin",
            "maven-surefire-plugin",
            "jacoco-maven-plugin",
        ):
            ejemplo = next(
                p
                for p in receta.findall("{*}build/{*}plugins/{*}plugin")
                if p.findtext("{*}artifactId") == nombre
            )
            existentes = [p for p in plugins if p.findtext("{*}artifactId") == nombre]
            if len(existentes) > 1:
                raise ValueError("El POM contiene plugins de pruebas duplicados.")
            plugin = (
                existentes[0] if existentes else ET.SubElement(plugins, ns + "plugin")
            )
            for campo in ("groupId", "artifactId", "version"):
                valor = ejemplo.findtext("{*}" + campo)
                if valor and valor.startswith("${"):
                    valor = propiedades[valor[2:-1]]
                _hijo(plugin, ns + campo).text = valor
            if nombre == "maven-surefire-plugin":
                config = _hijo(plugin, ns + "configuration")
                opciones_jvm = config.findtext(ns + "argLine") or ""
                for campo in (
                    "includes",
                    "excludes",
                    "skip",
                    "skipTests",
                    "test",
                    "reportsDirectory",
                    "testFailureIgnore",
                    "failIfNoTests",
                    "forkCount",
                    "argLine",
                ):
                    for previo in list(config.findall(ns + campo)):
                        config.remove(previo)
                for campo, valor in (
                    ("reportsDirectory", "/out/junit-raw"),
                    ("testFailureIgnore", "false"),
                    ("failIfNoTests", "true"),
                    ("skip", "false"),
                    ("skipTests", "false"),
                    ("forkCount", "1"),
                    ("argLine", ("@{qagentJacocoArgLine} " + opciones_jvm).strip()),
                ):
                    _hijo(config, ns + campo).text = valor
            elif nombre == "jacoco-maven-plugin":
                # Se usan goals explícitos: no reutilizar agentes/executions del usuario.
                for campo in ("configuration", "executions"):
                    for previo in list(plugin.findall(ns + campo)):
                        plugin.remove(previo)
                config = _hijo(plugin, ns + "configuration")
                for campo, valor in (
                    ("destFile", "/out/jacoco.exec"),
                    ("dataFile", "/out/jacoco.exec"),
                    ("outputDirectory", "/out/jacoco-report"),
                    ("append", "false"),
                    ("propertyName", "qagentJacocoArgLine"),
                ):
                    _hijo(config, ns + campo).text = valor
        _dependencia_junit(preparado, ns, propiedades["junit.version"])
        _dependencia_mockito(preparado, ns)
        _dependencia_vintage(preparado, ns, propiedades["junit.version"])
        etapa = "prueba"
        candidatas = [
            p for p in pruebas.rglob("*") if p.is_file() and p.suffix == ".java"
        ]
        if len(candidatas) != 1:
            raise ValueError(
                "Se requiere exactamente una fuente .java de prueba generada."
            )
        codigo = _leer(candidatas[0], pruebas)
        relativa, selector = _identidad_prueba(codigo)
        destino = copia / TESTS / relativa
        destino.parent.mkdir(parents=True)
        destino.write_text(codigo, encoding="utf-8", newline="")
        surefire = next(
            p for p in plugins if p.findtext("{*}artifactId") == "maven-surefire-plugin"
        )
        _hijo(_hijo(surefire, ns + "configuration"), ns + "test").text = selector
        if ns:
            for nodo in preparado.iter():
                nodo.tag = nodo.tag.removeprefix(ns)
            preparado.set("xmlns", _NS)
        with (copia / POM).open("xb") as archivo:
            ET.ElementTree(preparado).write(
                archivo, encoding="utf-8", xml_declaration=True
            )
    except (OSError, UnicodeError, ValueError, ET.ParseError) as error:
        raise ErrorPreparacionSandbox(
            f"{MARCA}{etapa}\nNo se pudo preparar Java: {error}"
        ) from error


def motivo_proyecto_no_ejecutable(raiz: Path) -> str | None:
    """Explica por qué un proyecto Java no puede ejecutarse en el sandbox (J3/J4).

    Es una comprobación estática y barata para la Vista previa: no compila ni
    ejecuta nada. Devuelve ``None`` cuando el proyecto cumple los requisitos del
    ejecutor (un POM Maven de un módulo sin herencia ni agregación).
    """
    raiz = Path(raiz)
    pom = raiz / "pom.xml"
    if not pom.is_file():
        if any(
            (raiz / nombre).is_file()
            for nombre in ("build.gradle", "build.gradle.kts", "settings.gradle")
        ):
            return (
                "Gradle no está soportado por el ejecutor Java: se requiere un "
                "pom.xml Maven de un módulo."
            )
        return "El proyecto Java requiere un pom.xml Maven en la raíz."
    try:
        original = _xml(_leer(pom, raiz))
    except (OSError, UnicodeError, ValueError, ET.ParseError) as error:
        return f"No se pudo leer el pom.xml: {error}"
    if original.tag not in {"project", f"{{{_NS}}}project"}:
        return "El pom.xml no es un POM Maven válido."
    if original.find("{*}parent") is not None:
        # J4: el ejecutor no resuelve herencia de un POM padre.
        return (
            "El proyecto hereda de un POM padre (<parent>); QAgent solo ejecuta "
            "Maven de un módulo sin herencia."
        )
    if original.find(".//{*}modules") is not None:
        return (
            "El proyecto es multimódulo (<modules>); QAgent solo ejecuta Maven "
            "de un módulo."
        )
    ns = f"{{{_NS}}}" if original.tag.startswith("{") else ""
    version_lombok = _version_lombok(original, ns)
    if version_lombok is not None and _lombok_incompatible(
        original, ns, version_lombok
    ):
        return (
            f"Lombok {version_lombok} no es compatible con el JDK del sandbox; "
            "actualiza a 1.18.40 o superior."
        )
    return None


def _version_jdk(pom: ET.Element, ns: str) -> str:
    """Elige el JDK del sandbox (17, 21 o 25) según el POM, sin ejecutar Maven.

    La receta fija ``maven.compiler.release`` 21 cuando el proyecto no declara
    ninguna versión, así que ese es el valor predeterminado. Las versiones
    anteriores a 17 se compilan con el JDK 17 y las posteriores a 21 con el 25;
    javac avisa si la versión declarada no es compatible con ese JDK.
    """
    fuente = (
        _propiedad_pom(pom, ns, "maven.compiler.release")
        or _propiedad_pom(pom, ns, "maven.compiler.source")
        or _propiedad_pom(pom, ns, "java.version")
    )
    if fuente is None:
        fuente = _version_compilador(pom, ns)
    mayor = _mayor_de_version(fuente)
    if mayor is None:
        return "21"
    if mayor <= 17:
        return "17"
    if mayor <= 21:
        return "21"
    return "25"


def recolectar_dependencias(raiz: Path) -> dict[str, bytes]:
    """Prepara para la fase con red las mismas dependencias que usará JUnit offline."""
    pom = _xml(_leer(raiz / "pom.xml", raiz))
    ns = f"{{{_NS}}}" if pom.tag.startswith("{") else ""
    receta = _xml(_RECETA.read_text(encoding="utf-8"))
    version = receta.findtext("{*}properties/{*}junit.version")
    _dependencia_junit(pom, ns, version)
    _dependencia_mockito(pom, ns)
    _dependencia_vintage(pom, ns, version)
    # go-offline no siempre incluye annotationProcessorPaths: se resuelven como
    # dependencias provided en la copia de descarga, sin ejecutar procesadores.
    dependencias = _hijo(pom, ns + "dependencies")
    for procesador in list(pom.findall(".//{*}annotationProcessorPaths/{*}path")):
        identidad = (
            procesador.findtext("{*}groupId"),
            procesador.findtext("{*}artifactId"),
        )
        if not all(identidad) or any(
            (d.findtext("{*}groupId"), d.findtext("{*}artifactId")) == identidad
            for d in dependencias
        ):
            continue
        dependencia = ET.SubElement(dependencias, ns + "dependency")
        for campo in ("groupId", "artifactId", "version"):
            if valor := procesador.findtext("{*}" + campo):
                _hijo(dependencia, ns + campo).text = valor
        _hijo(dependencia, ns + "scope").text = "provided"
    if ns:
        for nodo in pom.iter():
            nodo.tag = nodo.tag.removeprefix(ns)
        pom.set("xmlns", _NS)
    return {"pom.xml": ET.tostring(pom, encoding="utf-8", xml_declaration=True)}


def _propiedad_pom(pom: ET.Element, ns: str, nombre: str) -> str | None:
    """Lee una propiedad literal del POM; ignora referencias sin resolver."""
    propiedades = pom.find(ns + "properties")
    if propiedades is None:
        return None
    valor = propiedades.findtext(ns + nombre)
    if not valor or valor.strip().startswith("${"):
        return None
    return valor.strip()


def _version_compilador(pom: ET.Element, ns: str) -> str | None:
    """Busca release/source en la configuración de maven-compiler-plugin."""
    for plugin in pom.iter(ns + "plugin"):
        if plugin.findtext("{*}artifactId") != "maven-compiler-plugin":
            continue
        configuracion = plugin.find(ns + "configuration")
        if configuracion is None:
            continue
        for campo in ("release", "source"):
            valor = configuracion.findtext(ns + campo)
            if valor and not valor.strip().startswith("${"):
                return valor.strip()
    return None


def _mayor_de_version(valor: str | None) -> int | None:
    """Extrae la versión mayor de ``1.8``, ``8``, ``17`` o ``21.0``."""
    if valor is None:
        return None
    coincidencia = re.match(r"\s*(?:1\.)?(\d+)", valor)
    return int(coincidencia.group(1)) if coincidencia else None


def _dependencia_junit(pom: ET.Element, ns: str, version: str) -> None:
    """Añade JUnit 5 solo si falta, respetando la versión existente del proyecto."""
    dependencias = _hijo(pom, ns + "dependencies")
    junit = [d for d in dependencias if d.findtext("{*}groupId") == "org.junit.jupiter"]
    if any(d.findtext("{*}artifactId") == "junit-jupiter" for d in junit):
        return
    dependencia = ET.SubElement(dependencias, ns + "dependency")
    for campo, valor in (
        ("groupId", "org.junit.jupiter"),
        ("artifactId", "junit-jupiter"),
        ("scope", "test"),
    ):
        _hijo(dependencia, ns + campo).text = valor
    if junit:
        existente = junit[0].findtext("{*}version")
        if existente:
            _hijo(dependencia, ns + "version").text = existente
    else:
        _hijo(dependencia, ns + "version").text = version


def _dependencia_mockito(pom: ET.Element, ns: str) -> None:
    """Anade Mockito como dependencia de prueba si falta (J6).

    QAgent permite Mockito en las pruebas generadas para dependencias inyectadas;
    sin él, la prueba no compila aunque el código sea correcto. Se respeta una
    versión ya declarada por el proyecto.
    """
    dependencias = _hijo(pom, ns + "dependencies")
    existentes = [d for d in dependencias if d.findtext("{*}groupId") == "org.mockito"]
    if any(d.findtext("{*}artifactId") == "mockito-core" for d in existentes):
        return
    dependencia = ET.SubElement(dependencias, ns + "dependency")
    for campo, valor in (
        ("groupId", "org.mockito"),
        ("artifactId", "mockito-core"),
        (
            "version",
            _xml(_RECETA.read_text(encoding="utf-8")).findtext(
                "{*}properties/{*}mockito.version"
            ),
        ),
        ("scope", "test"),
    ):
        _hijo(dependencia, ns + campo).text = valor


def _dependencia_vintage(pom: ET.Element, ns: str, version: str) -> None:
    """Anade junit-vintage-engine si el proyecto usa JUnit 4 (J7)."""
    dependencias = _hijo(pom, ns + "dependencies")
    usa_junit4 = any(
        d.findtext("{*}groupId") == "junit" and d.findtext("{*}artifactId") == "junit"
        for d in dependencias
    )
    if not usa_junit4:
        return
    if any(
        d.findtext("{*}artifactId") == "junit-vintage-engine"
        for d in dependencias
        if d.findtext("{*}groupId") == "org.junit.vintage"
    ):
        return
    dependencia = ET.SubElement(dependencias, ns + "dependency")
    for campo, valor in (
        ("groupId", "org.junit.vintage"),
        ("artifactId", "junit-vintage-engine"),
        ("scope", "test"),
    ):
        _hijo(dependencia, ns + campo).text = valor
    _hijo(dependencia, ns + "version").text = version


def _version_lombok(pom: ET.Element, ns: str) -> str | None:
    """Considera dependencias y procesadores: la version mas antigua debe ser compatible."""
    from packaging.version import InvalidVersion, Version

    versiones = []
    for dep in pom.iter():
        if dep.tag not in {ns + "dependency", ns + "path"}:
            continue
        if (
            dep.findtext("{*}groupId") != "org.projectlombok"
            or dep.findtext("{*}artifactId") != "lombok"
        ):
            continue
        version = (dep.findtext("{*}version") or "").strip()
        for _ in range(8):
            if not (version.startswith("${") and version.endswith("}")):
                break
            version = (
                pom.findtext(ns + "properties/" + ns + version[2:-1]) or ""
            ).strip()
        if version and not version.startswith("${"):
            versiones.append(version)
    try:
        return min(versiones, key=Version) if versiones else None
    except InvalidVersion:
        return versiones[0] if versiones else None


def _lombok_incompatible(pom: ET.Element, ns: str, version: str) -> bool:
    """Comprueba Lombok contra el compilador elegido, también en procesadores."""
    minima = {"17": "1.18.22", "21": "1.18.30", "25": "1.18.40"}[_version_jdk(pom, ns)]
    return _version_menor(version, minima)


def _version_menor(version: str, referencia: str) -> bool:
    """Compara versiones PEP 440 (reutiliza packaging)."""
    try:
        from packaging.version import Version

        return Version(version) < Version(referencia)
    except (ImportError, ValueError):
        return version < referencia


def _identidad_prueba(codigo: str) -> tuple[Path, str]:
    """Obtiene paquete y clase del AST; no confunde una sintaxis inválida con el proyecto.

    Si la prueba no permite reconocer una identidad, se guarda con un nombre
    auxiliar: test-compile reportará el error en la etapa prueba. No repara su código.
    """
    raiz = obtener_parser("java").parse(codigo.encode("utf-8")).root_node
    paquete = next(
        (
            n.named_children[-1].text.decode("utf-8")
            for n in raiz.named_children
            if n.type == "package_declaration"
        ),
        "",
    )
    tipos = [
        n
        for n in raiz.named_children
        if n.type in {"class_declaration", "record_declaration", "enum_declaration"}
    ]
    nombre = tipos[0].child_by_field_name("name") if len(tipos) == 1 else None
    clase = nombre.text.decode("utf-8") if nombre is not None else "QAgentGeneratedTest"
    segmentos = [*paquete.split("."), clase] if paquete else [clase]
    if not all(s.replace("$", "_").isidentifier() for s in segmentos):
        segmentos = ["QAgentGeneratedTest"]
    return Path(*segmentos[:-1], segmentos[-1] + ".java"), ".".join(segmentos)


def recoger_junit(dir_salida: Path) -> str | None:
    """Agrega los informes Surefire de esta ejecución, con límites y sin enlaces externos."""
    from qagent.lenguajes.java_junit import interpretar_junit_java

    raiz = ET.Element("testsuites")
    total = 0
    try:
        carpeta = dir_salida / "junit-raw"
        if carpeta.is_symlink() or not carpeta.resolve().is_relative_to(
            dir_salida.resolve()
        ):
            return None
        informes = sorted(carpeta.glob("TEST-*.xml"))
        if not informes or len(informes) > 50:
            return None
        for archivo in informes:
            texto = _leer(archivo, dir_salida)
            total += len(texto.encode("utf-8"))
            if total > LIMITE_XML:
                return None
            interpretar_junit_java(texto)
            suite = parsear_xml(texto)
            if suite.tag == "testsuite":
                raiz.append(suite)
            else:
                raiz.extend(list(suite))
        agregado = ET.tostring(raiz, encoding="unicode")
        interpretar_junit_java(agregado)
        return agregado
    except (OSError, UnicodeError, ValueError, ET.ParseError, JUnitInvalido):
        return None


def _leer(archivo: Path, raiz: Path) -> str:
    """Lee UTF-8 acotado dentro de una raíz, sin seguir fuentes externas."""
    if archivo.is_symlink() or not archivo.resolve().is_relative_to(raiz.resolve()):
        raise ValueError("No se admite una ruta externa al sandbox.")
    with archivo.open("rb") as entrada:
        datos = entrada.read(LIMITE_XML + 1)
    if len(datos) > LIMITE_XML:
        raise ValueError("El archivo supera el tamaño permitido.")
    return datos.decode("utf-8-sig")


def _xml(texto: str) -> ET.Element:
    """Lee POM sin resolver DTD ni entidades externas."""
    if "<!DOCTYPE" in texto or "<!ENTITY" in texto:
        raise ValueError("No se admiten DTD ni entidades en el POM.")
    return parsear_xml(texto)


def _hijo(padre: ET.Element, nombre: str) -> ET.Element:
    """Obtiene o crea un hijo sin sobrescribir elementos ajenos al ajuste requerido."""
    encontrado = padre.find(nombre)
    return encontrado if encontrado is not None else ET.SubElement(padre, nombre)
