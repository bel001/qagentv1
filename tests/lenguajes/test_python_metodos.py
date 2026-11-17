"""Métodos públicos de clases Python de punta a punta (backlog 11, ADR-017).

Sin Docker ni red: el Planner y el Generator usan la IA simulada con casos
grabados; el Reviewer real valida el oráculo y el sandbox se simula.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from qagent import contracts
from qagent.agents.generator import GeneratorAgent
from qagent.agents.planner import PlannerAgent
from qagent.agents.reviewer import ReviewerAgent
from qagent.lenguajes import PythonAdapter
from qagent.lenguajes.python_planificacion import motivo_constructor
from qagent.lenguajes.python_revision import ReglasRevisionPython
from qagent.llm import TokenTracker
from qagent.llm.fake import FakeLLMClient, generar_test_desde_contrato
from qagent.orchestrator import Orquestador
from qagent.proyectos.compatibilidad import (
    COMPATIBLE,
    NO_SOPORTADO,
    REQUIERE_CONFIGURACION,
    evaluar,
)
from qagent.sandbox import ResultadoSandbox

CODIGO = '''"""Tienda."""
from dataclasses import dataclass


class Carrito:
    """Carrito de compras."""

    def __init__(self, precios: list[float] | None = None, descuento: float = 0.0):
        """Crea el carrito con los precios dados y un descuento entre 0 y 1."""
        self.precios = precios or []
        self.descuento = descuento

    def total(self) -> float:
        """Suma de los precios con el descuento aplicado.

        Carrito([10.0, 20.0], 0.5).total() devuelve 15.0.
        """
        return sum(self.precios) * (1 - self.descuento)

    def agregar(self, precio: float) -> int:
        """Agrega un precio y devuelve cuántos hay. Lanza ValueError si es negativo."""
        if precio < 0:
            raise ValueError("negativo")
        self.precios.append(precio)
        return len(self.precios)

    @staticmethod
    def iva(monto: float) -> float:
        """Devuelve el 18 % de monto. iva(100.0) == 18.0."""
        return monto * 0.18

    @classmethod
    def vacio(cls) -> int:
        """Cantidad de precios de un carrito vacío: 0."""
        return len(cls().precios)

    @property
    def cantidad(self) -> int:
        return len(self.precios)

    def sin_doc(self) -> int:
        return 1


class Servicio:
    def __init__(self, repo: "Repositorio"):
        self.repo = repo

    def buscar(self, id: int) -> dict:
        """Busca un registro."""
        return self.repo.get(id)


@dataclass
class Punto:
    """Un punto."""

    x: int
    y: int = 0

    def norma1(self) -> int:
        """|x| + |y|. Punto(3, -4).norma1() == 7."""
        return abs(self.x) + abs(self.y)


def suelta(a: int) -> int:
    """Devuelve a. suelta(1) == 1."""
    return a
'''


@pytest.fixture
def proyecto(tmp_path: Path) -> Path:
    (tmp_path / "tienda.py").write_text(CODIGO, encoding="utf-8")
    return tmp_path


@pytest.fixture
def modulo(proyecto: Path) -> dict:
    [modulo] = PythonAdapter().analizar(proyecto)["modulos"]
    return modulo


def _funciones(modulo: dict) -> dict:
    return {f["nombre"]: f for f in modulo["funciones"]}


# --- análisis --------------------------------------------------------------------------


def test_los_metodos_publicos_son_objetivos(modulo) -> None:
    funciones = _funciones(modulo)

    assert set(funciones) == {
        "suelta",
        "Carrito.total",
        "Carrito.agregar",
        "Carrito.iva",
        "Carrito.vacio",
        "Carrito.sin_doc",
        "Servicio.buscar",
        "Punto.norma1",
    }
    assert funciones["Carrito.total"]["tipo_metodo"] == "instancia"
    assert funciones["Carrito.iva"]["tipo_metodo"] == "estatico"
    assert funciones["Carrito.vacio"]["tipo_metodo"] == "clase"
    # self y cls no son parámetros del caso.
    assert [p["nombre"] for p in funciones["Carrito.agregar"]["parametros"]] == [
        "precio"
    ]
    assert funciones["Carrito.vacio"]["parametros"] == []
    assert [p["nombre"] for p in funciones["Carrito.iva"]["parametros"]] == ["monto"]


def test_las_propiedades_y_privados_no_se_ofrecen(modulo) -> None:
    funciones = _funciones(modulo)
    assert "Carrito.cantidad" not in funciones
    assert not any(".__" in n or "._" in n for n in funciones)
    [propiedad] = modulo["metodos_no_seleccionables"]
    assert propiedad["nombre"] == "cantidad"
    assert "propiedad" in propiedad["motivo"]


def test_el_constructor_de_cada_clase(modulo) -> None:
    funciones = _funciones(modulo)

    carrito = funciones["Carrito.total"]
    assert carrito["constructor"]["firma"].startswith("Carrito(precios: list[float]")
    assert carrito["constructor"]["docstring"].startswith("Crea el carrito")
    assert "no_soportada" not in carrito

    punto = funciones["Punto.norma1"]
    assert punto["constructor"]["firma"] == "Punto(x: int, y: int = 0)"
    assert "no_soportada" not in punto


def test_una_dependencia_no_construible_se_explica_con_su_nombre(modulo) -> None:
    servicio = _funciones(modulo)["Servicio.buscar"]
    motivo = servicio["no_soportada"]
    assert "`repo: 'Repositorio'`" in motivo
    assert "no construye esa dependencia sin adivinar" in motivo


def test_la_funcion_suelta_no_cambia(modulo) -> None:
    suelta = _funciones(modulo)["suelta"]
    assert "tipo_metodo" not in suelta
    assert "constructor" not in suelta


def test_los_metodos_no_entran_en_las_cadenas_de_integracion(modulo) -> None:
    for integracion in modulo.get("integraciones") or []:
        assert "." not in integracion["nombre"]


# --- compatibilidad -----------------------------------------------------------------


def test_compatibilidad_de_los_metodos(proyecto) -> None:
    analisis = PythonAdapter().analizar(proyecto)
    evaluar(
        proyecto,
        PythonAdapter(),
        analisis["modulos"],
        analisis["errores"],
        inferencia_activa=True,
        limite_inferencia=20,
    )
    estados = {
        f["nombre"]: f["compatibilidad"]["estado"]
        for f in analisis["modulos"][0]["funciones"]
    }

    assert estados["Carrito.total"] == COMPATIBLE
    assert estados["Servicio.buscar"] == NO_SOPORTADO
    # Los métodos no se infieren: sin docstring requieren documentarse.
    assert estados["Carrito.sin_doc"] == REQUIERE_CONFIGURACION


# --- Planner ---------------------------------------------------------------------------

CASOS = {
    "tienda.py::Carrito.total": [
        {
            "id": "con_descuento",
            "constructor": {"precios": [10.0, 20.0], "descuento": 0.5},
            "entrada": {},
            "valor_esperado": 15.0,
            "origen": "docstring",
        }
    ],
    "tienda.py::Carrito.agregar": [
        {
            "id": "negativo",
            "constructor": {},
            "entrada": {"precio": -1.0},
            "excepcion": "ValueError",
            "origen": "docstring",
        }
    ],
    "tienda.py::Carrito.iva": [
        {
            "id": "cien",
            "entrada": {"monto": 100.0},
            "valor_esperado": 18.0,
            "origen": "docstring",
        }
    ],
    "tienda.py::Punto.norma1": [
        {
            "id": "tres_menos_cuatro",
            "constructor": {"x": 3, "y": -4},
            "entrada": {},
            "valor_esperado": 7,
            "origen": "docstring",
        }
    ],
}


def _planner(grabaciones=CASOS) -> PlannerAgent:
    return PlannerAgent(
        FakeLLMClient(grabaciones=grabaciones),
        TokenTracker(),
        es_simulado=True,
        adaptador=PythonAdapter(),
    )


def _solo(modulo: dict, *nombres: str) -> dict:
    return {
        **modulo,
        "funciones": [f for f in modulo["funciones"] if f["nombre"] in nombres],
    }


def test_el_prompt_lleva_el_constructor_y_las_reglas_de_metodos(modulo) -> None:
    prompt = (
        PythonAdapter()
        .reglas_planificacion()
        .prompt_funciones(_solo(modulo, "Carrito.total", "suelta"), False)
    )
    assert '"tipo_metodo": "instancia"' in prompt
    assert "Crea el carrito" in prompt
    assert 'cada caso lleva además "constructor"' in prompt


def test_sin_metodos_el_prompt_no_gasta_tokens_en_sus_reglas(modulo) -> None:
    prompt = (
        PythonAdapter()
        .reglas_planificacion()
        .prompt_funciones(_solo(modulo, "suelta"), False)
    )
    assert "tipo_metodo" not in prompt


def test_el_planner_arma_el_contrato_de_cada_metodo(modulo) -> None:
    plan = _planner().planificar(
        _solo(modulo, "Carrito.total", "Carrito.agregar", "Carrito.iva", "Punto.norma1")
    )
    contratos = {c["objetivo"]: c for c in plan}

    assert set(contratos) == {
        "Carrito.total",
        "Carrito.agregar",
        "Carrito.iva",
        "Punto.norma1",
    }
    for contrato in plan:
        contracts.validar(contracts.PLANNER_V3, contrato)
        assert contrato["critical"] is False  # los métodos aún no se mutan
    assert contratos["Carrito.total"]["metodo"] == {
        "clase": "Carrito",
        "tipo": "instancia",
        "constructor": contratos["Carrito.total"]["metodo"]["constructor"],
    }
    assert contratos["Carrito.total"]["metodo"]["constructor"].startswith("Carrito(")
    assert contratos["Carrito.iva"]["metodo"] == {
        "clase": "Carrito",
        "tipo": "estatico",
    }


@pytest.mark.parametrize(
    ("constructor", "motivo"),
    [
        (None, "necesita 'constructor'"),
        ({"x": 3, "z": 1}, "no recibe: z"),
        ({"y": 1}, "faltan argumentos obligatorios: x"),
    ],
)
def test_un_constructor_que_no_liga_descarta_el_caso(
    modulo, constructor, motivo
) -> None:
    punto = _funciones(modulo)["Punto.norma1"]
    caso = {"id": "c", "entrada": {}, "valor_esperado": 7, "origen": "docstring"}
    if constructor is not None:
        caso["constructor"] = constructor
    assert motivo in motivo_constructor(punto, caso)


def test_un_estatico_o_una_funcion_no_llevan_constructor(modulo) -> None:
    funciones = _funciones(modulo)
    caso = {"id": "c", "constructor": {}, "entrada": {"monto": 1.0}}
    assert "solo un método de instancia" in motivo_constructor(
        funciones["Carrito.iva"], caso
    )
    assert "solo un método de instancia" in motivo_constructor(
        funciones["suelta"], caso
    )
    del caso["constructor"]
    assert motivo_constructor(funciones["Carrito.iva"], caso) is None


def test_el_planner_descarta_el_caso_con_constructor_invalido(modulo) -> None:
    grabaciones = {
        "tienda.py::Punto.norma1": [
            {
                "id": "mal",
                "constructor": {"z": 1},
                "entrada": {},
                "valor_esperado": 7,
                "origen": "docstring",
            }
        ]
    }
    planner = _planner(grabaciones)

    assert planner.planificar(_solo(modulo, "Punto.norma1")) == []
    assert any("Punto.norma1" in d and "constructor" in d for d in planner.descartados)


# --- Generator y validador -----------------------------------------------------------


def _contrato(modulo: dict, objetivo: str) -> dict:
    [contrato] = _planner().planificar(_solo(modulo, objetivo))
    return contrato


def test_el_prompt_del_generator_explica_como_construir_y_llamar(
    modulo, proyecto
) -> None:
    contrato = _contrato(modulo, "Carrito.total")
    prompt = PythonAdapter().prompt_generator(contrato, 1, None, proyecto)

    assert "from tienda import Carrito" in prompt
    assert "objeto = Carrito(**constructor), y llama objeto.total(**entrada)" in prompt
    # El contexto del código es el del método, no el de otra función.
    assert "return sum(self.precios)" in prompt


def test_el_prompt_de_un_estatico_no_construye_el_objeto(modulo, proyecto) -> None:
    prompt = PythonAdapter().prompt_generator(
        _contrato(modulo, "Carrito.iva"), 1, None, proyecto
    )
    assert (
        "Llama directamente Carrito.iva(**entrada), sin construir el objeto" in prompt
    )


@pytest.mark.parametrize(
    "objetivo", ["Carrito.total", "Carrito.iva", "Punto.norma1", "Carrito.agregar"]
)
def test_la_prueba_de_la_ia_simulada_cumple_el_oraculo(modulo, objetivo) -> None:
    contrato = _contrato(modulo, objetivo)
    codigo = generar_test_desde_contrato(contrato)

    ast.parse(codigo)
    assert ReglasRevisionPython.validar_oraculo(contrato, codigo) is None


def test_el_oraculo_acepta_el_objeto_en_una_variable(modulo) -> None:
    contrato = _contrato(modulo, "Carrito.total")
    codigo = (
        "import pytest\nfrom tienda import Carrito\n\n"
        "def test_con_descuento():\n"
        "    carrito = Carrito(precios=[10.0, 20.0], descuento=0.5)\n"
        "    assert carrito.total() == pytest.approx(15.0)\n"
    )
    assert ReglasRevisionPython.validar_oraculo(contrato, codigo) is None


@pytest.mark.parametrize(
    "aserto",
    [
        "Carrito([10.0, 20.0], 0.5).agregar(1.0) == 15.0",  # otro método
        "len(Carrito([10.0, 20.0], 0.5).precios) == 15.0",  # no llama al método
        "suelta(15.0) == 15.0",  # otra función
    ],
)
def test_el_oraculo_rechaza_lo_que_no_es_el_metodo(modulo, aserto) -> None:
    contrato = _contrato(modulo, "Carrito.total")
    codigo = (
        "from tienda import Carrito, suelta\n\n"
        f"def test_con_descuento():\n    assert {aserto}\n"
    )
    problema = ReglasRevisionPython.validar_oraculo(contrato, codigo)
    assert problema is not None
    assert "Carrito(precios=[10.0, 20.0], descuento=0.5).total()" in problema


def test_corrida_simulada_de_metodos_con_el_reviewer_real(modulo, proyecto) -> None:
    tracker = TokenTracker()

    def ejecutor(_imagen, _proyecto, _tests, _modulo) -> ResultadoSandbox:
        return ResultadoSandbox(
            exit_code=0, stdout="1 passed", stderr="", duracion_s=0.01
        )

    orquestador = Orquestador(
        _planner(),
        GeneratorAgent(
            FakeLLMClient(), tracker, es_simulado=True, ruta_proyecto=proyecto
        ),
        ReviewerAgent(tracker, proyecto, "imagen", ejecutor=ejecutor, es_simulado=True),
        tracker=tracker,
    )

    resultado = orquestador.ejecutar(
        _solo(modulo, "Carrito.total", "Carrito.iva", "Punto.norma1")
    )

    assert {o.objetivo: o.decision for o in resultado.objetivos} == {
        "Carrito.total": "accept",
        "Carrito.iva": "accept",
        "Punto.norma1": "accept",
    }


# --- cobertura y regresión ------------------------------------------------------------


def test_el_rango_del_metodo_para_la_cobertura(proyecto) -> None:
    reglas = PythonAdapter().reglas_revision()
    lineas = CODIGO.splitlines()
    inicio, fin = reglas.rango_de_objetivo(proyecto, "tienda.py", "Carrito.total")
    assert "return sum(self.precios)" in "\n".join(lineas[inicio - 1 : fin])
    assert "def agregar" not in "\n".join(lineas[inicio - 1 : fin])
    assert reglas.rango_de_objetivo(proyecto, "tienda.py", "Carrito.no_existe") is None


def _huellas(codigo: str) -> dict:
    return PythonAdapter().huellas_de_archivo(codigo, "tienda.py")


def test_cada_metodo_tiene_su_huella() -> None:
    huellas = _huellas(CODIGO)
    assert {"Carrito.total", "Carrito.iva", "Punto.norma1", "suelta"} <= set(huellas)


def test_cambiar_otro_metodo_no_invalida_la_prueba_guardada() -> None:
    antes = _huellas(CODIGO)
    despues = _huellas(
        CODIGO.replace("return len(self.precios)", "return len(self.precios) + 0")
    )
    assert antes["Carrito.total"] == despues["Carrito.total"]
    assert antes["Carrito.agregar"] != despues["Carrito.agregar"]


def test_cambiar_el_constructor_invalida_los_metodos_de_su_clase() -> None:
    antes = _huellas(CODIGO)
    despues = _huellas(
        CODIGO.replace("self.descuento = descuento", "self.descuento = 0")
    )
    assert antes["Carrito.total"] != despues["Carrito.total"]
    assert antes["Punto.norma1"] == despues["Punto.norma1"]
    assert antes["suelta"] == despues["suelta"]


def test_cambiar_un_campo_de_la_dataclass_invalida_sus_metodos() -> None:
    antes = _huellas(CODIGO)
    despues = _huellas(CODIGO.replace("y: int = 0", "y: int = 1"))
    assert antes["Punto.norma1"] != despues["Punto.norma1"]
