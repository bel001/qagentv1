"""ADR-017 con Docker real: dependencias desde manifiestos, `src/` y métodos de clases.

Construye imágenes de dependencias (necesita internet la primera vez) y ejecuta las
pruebas generadas dentro del sandbox. Las imágenes que cree la corrida se borran al
terminar (#250).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from qagent.agents.planner import PlannerAgent
from qagent.agents.reviewer import ReviewerAgent
from qagent.lenguajes import PythonAdapter
from qagent.llm import TokenTracker
from qagent.llm.fake import FakeLLMClient, generar_test_desde_contrato
from qagent.sandbox import ejecutar_pruebas, preparar_imagen
from qagent.sandbox.imagen import etiqueta_para_requirements
from qagent.sandbox.modelos import ErrorConstruccionImagen

pytestmark = pytest.mark.docker

PRUEBA_SIX = "import six\n\ndef test_six():\n    assert six.__version__ == '1.17.0'\n"


def _escribir(raiz: Path, archivos: dict[str, str]) -> Path:
    for relativa, contenido in archivos.items():
        ruta = raiz / relativa
        ruta.parent.mkdir(parents=True, exist_ok=True)
        ruta.write_bytes(contenido.encode("utf-8"))
    return raiz


def _tests(tmp_path: Path, codigo: str) -> Path:
    return _escribir(tmp_path / "tests", {"test_generado.py": codigo})


# --- dependencias desde manifiestos ------------------------------------------------


@pytest.mark.parametrize(
    "manifiesto",
    [
        {"pyproject.toml": '[project]\nname = "app"\ndependencies = ["six==1.17.0"]\n'},
        {
            "pyproject.toml": '[tool.poetry.dependencies]\npython = "^3.10"\nsix = "1.17.0"\n'
        },
        {"setup.cfg": "[options]\ninstall_requires =\n    six==1.17.0\n"},
    ],
    ids=["pep621", "poetry", "setup_cfg"],
)
def test_el_manifiesto_instala_sus_dependencias(
    imagen_base, tmp_path, manifiesto
) -> None:
    proyecto = _escribir(tmp_path / "proyecto", {"calc.py": "X = 1\n", **manifiesto})

    imagen = preparar_imagen(proyecto)
    resultado = ejecutar_pruebas(imagen, proyecto, _tests(tmp_path, PRUEBA_SIX), "calc")

    assert resultado.exit_code == 0, resultado.stdout + resultado.stderr
    # La misma lista que un requirements.txt: la misma imagen, que se reutiliza.
    assert imagen == etiqueta_para_requirements(b"six==1.17.0\n")


def test_una_dependencia_local_se_rechaza_sin_construir(imagen_base, tmp_path) -> None:
    proyecto = _escribir(
        tmp_path / "proyecto",
        {
            "calc.py": "X = 1\n",
            "pyproject.toml": '[tool.poetry.dependencies]\nmilib = { path = "../milib" }\n',
        },
    )
    with pytest.raises(ErrorConstruccionImagen, match="«milib»"):
        preparar_imagen(proyecto)


# --- estructura src/ -------------------------------------------------------------------

SRC = {
    "pyproject.toml": '[project]\nname = "mipaquete"\ndependencies = []\n',
    "src/mipaquete/__init__.py": "",
    "src/mipaquete/util.py": "def doble(x: int) -> int:\n    return x * 2\n",
    "src/mipaquete/calc.py": (
        "from mipaquete.util import doble\n\n\n"
        "def cuadruple(x: int) -> int:\n"
        '    """Devuelve 4 veces x. cuadruple(3) == 12."""\n'
        "    return doble(doble(x))\n"
    ),
}


def test_un_proyecto_src_importa_su_paquete_sin_instalarlo(
    imagen_base, tmp_path
) -> None:
    proyecto = _escribir(tmp_path / "proyecto", SRC)
    contrato = {
        "version": "3",
        "lenguaje": "python",
        "framework_pruebas": "pytest",
        "modulo": "src/mipaquete/calc.py",
        "huella": "a" * 64,
        "tipo": "funcion",
        "objetivo": "cuadruple",
        "firma": "(x: int) -> int",
        "critical": False,
        "llama_a": [],
        "casos": [
            {
                "id": "tres",
                "entrada": {"x": 3},
                "valor_esperado": 12,
                "origen": "docstring",
            }
        ],
    }
    generado = {
        "version": "1",
        "objetivo": "cuadruple",
        "intento": 1,
        "codigo": generar_test_desde_contrato(contrato),
        "casos_cubiertos": ["tres"],
    }

    revision = ReviewerAgent(
        TokenTracker(), proyecto, preparar_imagen(proyecto)
    ).revisar(contrato, generado, None)

    assert revision["estado_sandbox"] == "ok", revision["feedback"]
    assert revision["decision"] == "accept"


# --- métodos de clases -----------------------------------------------------------------

TIENDA = '''from dataclasses import dataclass


class Carrito:
    def __init__(self, precios: list[float] | None = None, descuento: float = 0.0):
        """Crea el carrito con los precios y un descuento entre 0 y 1."""
        self.precios = precios or []
        self.descuento = descuento

    def total(self) -> float:
        """Suma con el descuento. Carrito([10.0, 20.0], 0.5).total() == 15.0."""
        return sum(self.precios) * (1 - self.descuento)

    def con_error(self) -> float:
        """Igual que total. Carrito([10.0, 20.0], 0.5).con_error() == 15.0."""
        return sum(self.precios) * self.descuento + 1

    @staticmethod
    def iva(monto: float) -> float:
        """El 18 % de monto. iva(100.0) == 18.0."""
        return monto * 0.18


@dataclass
class Punto:
    x: int
    y: int = 0

    def norma1(self) -> int:
        """|x| + |y|. Punto(3, -4).norma1() == 7."""
        return abs(self.x) + abs(self.y)
'''

CASOS = {
    "tienda.py::Carrito.total": [
        {
            "id": "descuento",
            "constructor": {"precios": [10.0, 20.0], "descuento": 0.5},
            "entrada": {},
            "valor_esperado": 15.0,
            "origen": "docstring",
        }
    ],
    "tienda.py::Carrito.con_error": [
        {
            "id": "descuento",
            "constructor": {"precios": [10.0, 20.0], "descuento": 0.5},
            "entrada": {},
            "valor_esperado": 15.0,
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


@pytest.fixture(scope="module")
def tienda(tmp_path_factory) -> tuple[Path, dict]:
    proyecto = _escribir(tmp_path_factory.mktemp("tienda"), {"tienda.py": TIENDA})
    [modulo] = PythonAdapter().analizar(proyecto)["modulos"]
    planner = PlannerAgent(
        FakeLLMClient(grabaciones=CASOS),
        TokenTracker(),
        es_simulado=True,
        adaptador=PythonAdapter(),
    )
    contratos = {c["objetivo"]: c for c in planner.planificar(modulo)}
    return proyecto, contratos


def _revisar(proyecto: Path, contrato: dict, imagen: str) -> dict:
    generado = {
        "version": "1",
        "objetivo": contrato["objetivo"],
        "intento": 1,
        "codigo": generar_test_desde_contrato(contrato),
        "casos_cubiertos": [c["id"] for c in contrato["casos"]],
    }
    return ReviewerAgent(TokenTracker(), proyecto, imagen).revisar(
        contrato, generado, None
    )


@pytest.mark.parametrize("objetivo", ["Carrito.total", "Carrito.iva", "Punto.norma1"])
def test_un_metodo_correcto_se_aprueba_en_el_sandbox(
    imagen_base, tienda, objetivo
) -> None:
    proyecto, contratos = tienda

    revision = _revisar(proyecto, contratos[objetivo], imagen_base)

    assert revision["estado_sandbox"] == "ok", revision["feedback"]
    assert revision["decision"] == "accept"
    assert revision["ejecucion"]["casos"][0]["resultado"] == "paso"
    # La cobertura es la del método, no la del archivo entero.
    assert revision["cobertura"]["lineas"] == 100.0


def test_un_metodo_que_no_cumple_su_docstring_es_un_bug(imagen_base, tienda) -> None:
    proyecto, contratos = tienda

    revision = _revisar(proyecto, contratos["Carrito.con_error"], imagen_base)

    assert revision["estado_sandbox"] == "fallo"
    assert revision["decision"] == "bug_detectado"
    assert revision["laundering_detectado"] is False
