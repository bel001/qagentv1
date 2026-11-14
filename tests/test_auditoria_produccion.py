"""Regresiones de la auditoría: entradas adversarias y límites del producto, sin red."""

from __future__ import annotations

import threading
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from qagent import contracts
from qagent.lenguajes import JavaAdapter
from qagent.lenguajes.java_ejecucion import (
    motivo_proyecto_no_ejecutable,
    recolectar_dependencias,
)
from qagent.lenguajes.java_revision import ReglasRevisionJava, clasificar_java
from qagent.llm import RespuestaLLM
from qagent.llm.llamada import generar_acotado
from qagent.orchestrator.corrida_planificacion import _detener_por_compilacion
from qagent.proyectos.clonador import clonar
from qagent.sandbox import ErrorConstruccionImagen, ResultadoSandbox
from qagent.sandbox.copias import SesionProyecto
from qagent.sandbox.imagen import revisar_requirements


@pytest.mark.parametrize("fallos", [1, 2])
def test_build_reintenta_solo_una_vez_la_exportacion_transitoria(
    tmp_path: Path, fallos: int
) -> None:
    from docker.errors import BuildError

    from qagent.sandbox import imagen

    cliente = Mock()
    errores = [
        BuildError("failed to commit: lease does not exist", []) for _ in range(fallos)
    ]
    cliente.images.build.side_effect = [*errores, (Mock(), [])]
    if fallos == 1:
        imagen._construir(cliente, tmp_path, "qagent-sandbox:prueba", "No se construyó")
    else:
        with pytest.raises(ErrorConstruccionImagen, match="lease does not exist"):
            imagen._construir(
                cliente, tmp_path, "qagent-sandbox:prueba", "No se construyó"
            )
    assert cliente.images.build.call_count == 2


def test_m2_contexto_inferido_no_lee_tests_que_resuelven_fuera_del_proyecto(
    tmp_path: Path, monkeypatch
) -> None:
    from qagent.analysis import inferencia

    raiz = tmp_path / "proyecto"
    raiz.mkdir()
    externo = tmp_path / "test_ajeno.py"
    externo.write_text("def test_privado():\n    secreto()\n", encoding="utf-8")
    # También protege un path externo devuelto por un índice desactualizado.
    monkeypatch.setattr(inferencia, "_archivos_de_prueba", lambda _: [externo])
    assert inferencia.indice_de_tests(raiz) == {}


@pytest.mark.parametrize("prefijo", ["node-", "browser-"])
def test_una_receta_base_nueva_invalida_su_imagen_derivada(
    tmp_path: Path, monkeypatch, prefijo: str
) -> None:
    from dataclasses import replace

    from qagent.sandbox import imagen

    base = imagen.IMAGEN_NODE if prefijo == "node-" else imagen.IMAGEN_NAVEGADOR
    dockerfile = tmp_path / "Dockerfile"
    dockerfile.write_text("FROM node\nENV RECETA=1\n", encoding="utf-8")
    receta = replace(imagen.RECETAS[base], dockerfile=dockerfile, recursos=())
    monkeypatch.setitem(imagen.RECETAS, base, receta)
    archivos = {"package.json": b'{"name":"banco"}'}
    anterior = imagen.etiqueta_para_dependencias(prefijo, archivos, base)
    assert anterior == imagen.etiqueta_para_dependencias(prefijo, archivos, base)
    dockerfile.write_text("FROM node\nENV RECETA=2\n", encoding="utf-8")
    assert anterior != imagen.etiqueta_para_dependencias(prefijo, archivos, base)


def test_b8_impide_empaquetar_con_dependencias_ausentes_o_distintas(
    tmp_path: Path, monkeypatch
) -> None:
    from importlib.metadata import PackageNotFoundError

    from scripts import construir_windows

    carpeta = tmp_path / "packaging"
    carpeta.mkdir()
    (carpeta / "runtime-windows-py313.lock.txt").write_text(
        "docker==7.2.0\npywebview==5.4\n", encoding="utf-8"
    )

    def version(nombre):
        if nombre == "docker":
            raise PackageNotFoundError(nombre)
        return "5.3"

    monkeypatch.setattr(construir_windows, "RAIZ", tmp_path)
    monkeypatch.setattr(construir_windows, "version_instalada", version)
    diferencias = construir_windows.diferencias_dependencias()
    assert len(diferencias) == 2
    assert "docker: no está instalado" in diferencias[0]
    assert "pywebview: 5.3, se requiere 5.4" in diferencias[1]


@pytest.mark.parametrize(
    "constructor",
    [
        "public Servicio(Repo repo) { this.repo = repo; }",
        "@org.springframework.beans.factory.annotation.Autowired private Repo otro;",
        "@javax.inject.Inject private Repo otro;",
    ],
)
def test_j1_no_ofrece_metodos_que_requieren_stubs(
    tmp_path: Path, constructor: str
) -> None:
    archivo = tmp_path / "src/main/java/Servicio.java"
    archivo.parent.mkdir(parents=True)
    archivo.write_text(
        "public class Servicio { private Repo repo; "
        + constructor
        + " public String nombre() { return repo.nombre(); } "
        "public static int suma(int a, int b) { return a+b; } } "
        "interface Repo { String nombre(); }",
        encoding="utf-8",
    )
    [modulo] = JavaAdapter().analizar(tmp_path)["modulos"]
    assert [f["nombre"] for f in modulo["funciones"]] == ["Servicio.suma"]
    assert "Servicio.nombre" in modulo["metodos_con_dependencias_inyectadas"]


@pytest.mark.parametrize(
    "tipo", ["IllegalStateException", "ArithmeticException", "NullPointerException"]
)
def test_j2_excepcion_del_objetivo_no_es_error_de_entorno(tipo: str) -> None:
    xml = (
        '<testsuite><testcase name="contrato"><error type="java.lang.'
        + tipo
        + '">at ejemplo.Servicio.nombre(Servicio.java:12)</error></testcase></testsuite>'
    )
    resultado = ResultadoSandbox(
        1, "QAGENT_JAVA_ETAPA=ejecucion", "", junit_xml=xml, objetivo="Servicio.nombre"
    )
    assert clasificar_java(resultado).tipo == "fallo_asercion"
    resultado.objetivo = "Otra.funcion"
    assert clasificar_java(resultado).motivo_sin_veredicto == "error_ejecucion_pruebas"


def test_j3_detecta_modulos_en_perfiles(tmp_path: Path) -> None:
    (tmp_path / "pom.xml").write_text(
        "<project><profiles><profile><id>prod</id>"
        "<modules><module>backend</module></modules></profile></profiles></project>",
        encoding="utf-8",
    )
    assert "multimódulo" in motivo_proyecto_no_ejecutable(tmp_path)


def test_j2_excepcion_de_clase_anidada_con_nombre_jvm() -> None:
    resultado = ResultadoSandbox(
        1,
        "QAGENT_JAVA_ETAPA=ejecucion",
        "",
        junit_xml='<testsuite><testcase name="contrato"><error '
        'type="java.lang.IllegalStateException">at ejemplo.Outer$Inner.nombre(A.java:12)'
        "</error></testcase></testsuite>",
        objetivo="Outer.Inner.nombre",
    )
    assert clasificar_java(resultado).tipo == "fallo_asercion"


def test_j3_backend_no_llama_llm_ni_docker_si_el_proyecto_no_es_ejecutable(
    tmp_path: Path, monkeypatch
) -> None:
    from qagent.config import cargar_configuracion
    from qagent.orchestrator import corrida

    (tmp_path / "pom.xml").write_text(
        "<project><parent><groupId>x</groupId></parent></project>", encoding="utf-8"
    )
    fuente = tmp_path / "src/main/java/A.java"
    fuente.parent.mkdir(parents=True)
    fuente.write_text(
        "class A { public static int f() { return 1; } }", encoding="utf-8"
    )
    cliente = Mock(side_effect=AssertionError("No debe gastar tokens"))
    preparar = Mock(side_effect=AssertionError("No debe construir imágenes"))
    monkeypatch.setattr(corrida, "crear_cliente", cliente)
    resultado = corrida.ejecutar_corrida(
        tmp_path,
        "humo",
        cargar_configuracion(simulado=True).config,
        None,
        simulado=True,
        preparar_imagen=preparar,
    )
    assert resultado.estado == "fallo_controlado"
    assert "<parent>" in resultado.motivo
    cliente.assert_not_called()
    preparar.assert_not_called()


@pytest.mark.parametrize(("jdk", "bloqueado"), [(17, False), (21, False), (25, True)])
def test_j5_lombok_processor_se_valida_con_el_jdk_real(
    tmp_path: Path, jdk: int, bloqueado: bool
) -> None:
    (tmp_path / "pom.xml").write_text(
        f"""<project><properties><maven.compiler.release>{jdk}</maven.compiler.release></properties>
    <build><plugins><plugin><configuration><annotationProcessorPaths><path>
    <groupId>org.projectlombok</groupId><artifactId>lombok</artifactId><version>1.18.30</version>
    </path></annotationProcessorPaths></configuration></plugin></plugins></build></project>""",
        encoding="utf-8",
    )
    assert bool(motivo_proyecto_no_ejecutable(tmp_path)) == bloqueado


def test_j6_j7_prepara_las_dependencias_offline_en_la_fase_con_red(
    tmp_path: Path,
) -> None:
    pom = tmp_path / "pom.xml"
    original = "<project><dependencies><dependency><groupId>junit</groupId><artifactId>junit</artifactId><version>4.13.2</version></dependency></dependencies></project>"
    pom.write_text(original, encoding="utf-8")
    preparado = recolectar_dependencias(tmp_path)["pom.xml"].decode()
    assert all(
        nombre in preparado
        for nombre in ("mockito-core", "junit-vintage-engine", "junit-jupiter")
    )
    assert pom.read_text(encoding="utf-8") == original


def test_j8_corte_usa_el_campo_del_contrato_no_el_texto_del_feedback() -> None:
    revision = {
        "version": "1",
        "objetivo": "A.f",
        "intento": 1,
        "estado_sandbox": "error",
        "cobertura": None,
        "laundering_detectado": False,
        "tipo_fallo": None,
        "hash_error": None,
        "decision": "stalled",
        "feedback": "El proyecto no pudo compilarse.",
        "motivo_sin_veredicto": "error_compilacion_proyecto",
        "detener_corrida": True,
    }
    contracts.validar(contracts.REVIEW_RESULT, revision)
    resultado = SimpleNamespace(
        modulo="A.java", objetivos=[SimpleNamespace(revisiones=[revision])]
    )
    resumen = SimpleNamespace()
    assert _detener_por_compilacion(resumen, resultado, Mock())
    assert resumen.tipo_terminacion == "detenida_error"


def test_j10_localiza_la_clase_correcta_y_rechaza_sobrecargas(tmp_path: Path) -> None:
    archivo = tmp_path / "A.java"
    archivo.write_text(
        "class A {\n public int igual() { return 1; }\n}\n"
        "class B {\n public int igual() { return 2; }\n}\n",
        encoding="utf-8",
    )
    reglas = ReglasRevisionJava()
    assert reglas.rango_de_objetivo(tmp_path, "A.java", "A.igual") == (2, 2)
    assert reglas.rango_de_objetivo(tmp_path, "A.java", "B.igual") == (5, 5)
    archivo.write_text(
        "class A { public int f(){return 1;} public int f(int x){return x;} }",
        encoding="utf-8",
    )
    assert reglas.rango_de_objetivo(tmp_path, "A.java", "A.f") is None


@pytest.mark.parametrize(
    "requisito",
    [
        "-i https://otro.test/simple",
        "-ihttps://otro.test/simple",
        "--extra-index-url=https://otro.test",
        "-e .",
        "-r otros.txt",
        "-c constraints.txt",
        "git+https://otro.test/repo.git",
        "lib @ https://otro.test/lib.whl",
        "./paquete",
        "requests \\\n --no-binary=:all:",
    ],
)
def test_m3_rechaza_fuentes_que_ejecutan_codigo_o_cambian_el_indice(
    requisito: str,
) -> None:
    with pytest.raises(ErrorConstruccionImagen):
        revisar_requirements(requisito.encode())


def test_a3_solo_hay_un_clonado_activo(monkeypatch) -> None:
    from qagent.app.desktop import DesktopAPI

    iniciar = Mock()
    monkeypatch.setattr(threading.Thread, "start", iniciar)
    api = DesktopAPI()
    assert api.clonar_repositorio("https://github.com/ejemplo/repo", "main", "destino")[
        "iniciado"
    ]
    assert not api.clonar_repositorio(
        "https://github.com/ejemplo/repo", "main", "destino"
    )["iniciado"]
    assert iniciar.call_count == 1
    api.cancelar_clonado()
    assert api._cancelar_clonado.is_set()


def test_m7_el_timeout_cubre_stderr_bloqueado(tmp_path: Path) -> None:
    liberar = threading.Event()
    flujo = Mock()
    flujo.read.side_effect = lambda _n: (liberar.wait(2), "")[1]
    proceso = Mock(stderr=flujo)
    proceso.kill.side_effect = liberar.set
    proceso.wait.return_value = 137
    try:
        resultado = clonar(
            "https://github.com/ejemplo/repo",
            "main",
            tmp_path / "destino",
            popen=lambda *a, **k: proceso,
            timeout_s=0.01,
        )
        assert resultado.tipo_error == "timeout"
        proceso.kill.assert_called_once()
    finally:
        liberar.set()


def test_m7_cancelar_detiene_los_hijos_aunque_stderr_ya_este_cerrado(
    tmp_path: Path,
) -> None:
    import subprocess
    import sys
    import time

    latido = tmp_path / "latido.txt"
    hijo = (
        "import pathlib,sys,time; p=pathlib.Path(sys.argv[1]); "
        "[(p.write_text(str(i)),time.sleep(.05)) for i in range(100)]"
    )
    padre = (
        "import os,subprocess,sys,time; "
        f"subprocess.Popen([sys.executable,'-c',{hijo!r},sys.argv[1]],stderr=subprocess.DEVNULL); "
        "os.close(2); time.sleep(30)"
    )

    def proceso_controlado(_comando, **opciones):
        # Ejecuta exclusivamente este helper del sistema de pruebas, sin Git ni red.
        return subprocess.Popen([sys.executable, "-c", padre, str(latido)], **opciones)

    inicio = time.monotonic()
    resultado = clonar(
        "https://github.com/ejemplo/repo",
        "main",
        tmp_path / "destino",
        popen=proceso_controlado,
        cancelado=latido.exists,
        timeout_s=5,
    )
    assert resultado.tipo_error == "cancelado"
    assert time.monotonic() - inicio < 5
    ultimo = latido.read_text(encoding="utf-8")
    time.sleep(0.25)
    assert latido.read_text(encoding="utf-8") == ultimo


def test_a4_lectura_de_logs_no_consumen_el_stream_completo(monkeypatch) -> None:
    from qagent.sandbox import ejecucion

    consumidos = []

    def bloques():
        for i in range(1000):
            consumidos.append(i)
            yield b"12345"

    contenedor = Mock()
    contenedor.logs.side_effect = lambda **kwargs: bloques()
    monkeypatch.setattr(ejecucion, "LIMITE_LOGS_BYTES", 8)
    salida = ejecucion._leer_logs(contenedor, True)
    assert "truncada" in salida
    assert len(consumidos) == 2
    assert contenedor.logs.call_args.kwargs["stream"] is True


def test_a4_vigilancia_corta_por_disco(tmp_path: Path) -> None:
    from qagent.sandbox.vigilancia import VigilanciaDisco

    (tmp_path / "salida").write_bytes(b"12345")
    contenedor = Mock()
    vigilancia = VigilanciaDisco(contenedor, [tmp_path], max_bytes=4)
    assert not vigilancia.comprobar()
    contenedor.kill.assert_called_once()
    assert "disco" in vigilancia.motivo


def test_b9_reutiliza_copia_sin_contaminar_la_siguiente_prueba(tmp_path: Path) -> None:
    fuente = tmp_path / "calc.py"
    fuente.write_text("original", encoding="utf-8")
    sesion = SesionProyecto(tmp_path)
    try:
        with sesion.prestar() as primera:
            (primera / "calc.py").write_text("alterado", encoding="utf-8")
            (primera / "nuevo").write_text("sobrante", encoding="utf-8")
        with sesion.prestar() as segunda:
            assert segunda == primera
            assert (segunda / "calc.py").read_text(encoding="utf-8") == "original"
            assert not (segunda / "nuevo").exists()
        assert fuente.read_text(encoding="utf-8") == "original"
    finally:
        sesion.cerrar()


def test_m6_una_respuesta_tardia_se_contabiliza_sin_reintentar() -> None:
    liberar = threading.Event()
    registrado = threading.Event()
    respuesta = RespuestaLLM("{}", 10, 5, 0.1, "modelo-falso")
    cliente = Mock()
    cliente.generar.side_effect = lambda *a, **k: (liberar.wait(2), respuesta)[1]
    registros = []

    def registrar(valor):
        registros.append(valor)
        registrado.set()

    try:
        with pytest.raises(TimeoutError):
            generar_acotado(cliente, "prompt", "explicador", 0.01, registrar)
        liberar.set()
        assert registrado.wait(1)
        assert registros == [respuesta]
        cliente.generar.assert_called_once()
    finally:
        liberar.set()


def test_m3_el_plazo_cubre_un_stream_de_build_silencioso() -> None:
    from qagent.sandbox.plazos import iterar_con_plazo

    liberar = threading.Event()

    def abrir():
        liberar.wait(2)
        yield {"stream": "terminado"}

    try:
        with pytest.raises(TimeoutError):
            list(iterar_con_plazo(abrir, 0.01))
    finally:
        liberar.set()


def test_j13_no_se_borran_imagenes_de_otra_sesion() -> None:
    from tests.soporte_docker import imagen_de_sesion

    cliente = Mock()
    cliente.images.get.return_value.attrs = {
        "Config": {"Labels": {"qagent.test.session": "otra"}}
    }
    assert not imagen_de_sesion(cliente, "qagent-sandbox:req-compartida", "actual")
    cliente.images.get.return_value.attrs["Config"]["Labels"]["qagent.test.session"] = (
        "actual"
    )
    assert imagen_de_sesion(cliente, "qagent-sandbox:req-propia", "actual")
    assert not imagen_de_sesion(cliente, "qagent-sandbox:req-propia", None)


def test_a1_no_se_puede_elegir_un_modelo_sin_precio(monkeypatch) -> None:
    from dataclasses import replace

    from qagent.config import roles

    proveedor = roles.catalogo()["openai"]
    modelo = replace(
        proveedor.modelos[0], precio_confirmado=False, entrada_usd_m=0, salida_usd_m=0
    )
    monkeypatch.setattr(
        roles, "catalogo", lambda: {"openai": replace(proveedor, modelos=(modelo,))}
    )
    with pytest.raises(roles.ErrorRol, match="precio confirmado"):
        roles._validar_eleccion("planner", "openai", modelo.id)


def test_j8_un_error_global_detiene_el_modulo_sin_generar_el_segundo_objetivo() -> None:
    from copy import deepcopy

    from qagent.llm import TokenTracker
    from qagent.orchestrator.orquestador import Estado, Orquestador
    from tests.orchestrator.fakes import (
        MODULO,
        GeneratorSimulado,
        PlannerSimulado,
        veredicto,
    )
    from tests.orchestrator.test_orquestador import plan_grabado

    plan = plan_grabado()
    plan.append({**deepcopy(plan[0]), "objetivo": "otra"})
    modulo = {
        **MODULO,
        "funciones": [
            *MODULO["funciones"],
            {"nombre": "otra", "firma": "(x: int) -> int"},
        ],
    }
    tracker = TokenTracker()
    generator = GeneratorSimulado(tracker)
    reviewer = Mock()
    reviewer.revisar.side_effect = lambda c, t, a: veredicto(
        c["objetivo"],
        1,
        "stalled",
        tipo_fallo=None,
        motivo_sin_veredicto="error_compilacion_proyecto",
        detener_corrida=True,
    )
    resultado = Orquestador(
        PlannerSimulado(tracker, plan), generator, reviewer, tracker=tracker
    ).ejecutar(modulo)
    assert resultado.estado_final is Estado.FALLO_CONTROLADO
    assert len(resultado.objetivos) == 1
    assert len(generator.feedbacks) == reviewer.revisar.call_count == 1
