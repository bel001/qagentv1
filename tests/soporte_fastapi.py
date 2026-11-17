"""Proyecto controlado para verificar autenticación y servicios FastAPI en Docker."""

from pathlib import Path

from qagent.lenguajes.python_endpoints import montaje_endpoint

AUTH = """from typing import Annotated
from types import SimpleNamespace
from fastapi import Depends

async def require_session() -> SimpleNamespace:
    raise RuntimeError("Instance of type AuthenticationConfiguration not found in registry")

RequiredSession = Annotated[SimpleNamespace, Depends(require_session)]
"""

API = '''from fastapi import APIRouter
from auth import RequiredSession

router = APIRouter(prefix="/api")

async def _get_server(server_id: int):
    raise RuntimeError("La base de datos real no debe utilizarse en estas pruebas")

def _get_service():
    raise RuntimeError("El servicio real no debe utilizarse en estas pruebas")

@router.get("/{server_id}/tools")
async def tools(server_id: int, user: RequiredSession) -> list[dict]:
    """Lista las herramientas disponibles para el usuario autenticado."""
    server = await _get_server(server_id)
    return await _get_service().discover(server, user.user_id)
'''

PRUEBAS = """
import pytest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
import api
from auth import require_session

@pytest.fixture(autouse=True)
def preparar():
    original = dict(app_pruebas.dependency_overrides)
    app_pruebas.dependency_overrides[require_session] = lambda: SimpleNamespace(user_id=1)
    servicio = SimpleNamespace(discover=AsyncMock(return_value=[]))
    try:
        with patch.object(api, '_get_server', new=AsyncMock(return_value=object())), \\
             patch.object(api, '_get_service', return_value=servicio):
            yield
    finally:
        app_pruebas.dependency_overrides.clear()
        app_pruebas.dependency_overrides.update(original)

def test_valido():
    respuesta = client.request("GET", "/externo/api/1/tools")
    assert respuesta.status_code == 200
    assert respuesta.json() == []

def test_invalido():
    respuesta = client.request("GET", "/externo/api/abc/tools")
    assert respuesta.status_code == 422
"""


def crear_proyecto(raiz: Path) -> Path:
    """Escribe fuentes de prueba sin importarlas ni ejecutarlas en el host."""
    raiz.mkdir(parents=True, exist_ok=True)
    for nombre, contenido in {
        "auth.py": AUTH,
        "api.py": API,
        "main.py": (
            "from fastapi import FastAPI\nfrom api import router\n"
            "app = FastAPI()\napp.include_router(router, prefix='/externo')\n"
        ),
        "requirements.txt": "fastapi>=0.110\n",
        "pyproject.toml": "[tool.coverage.report]\nfail_under = 100\n",
    }.items():
        (raiz / nombre).write_text(contenido, encoding="utf-8")
    return raiz


def contrato() -> dict:
    """Contrato declarado con autenticación importada y un prefijo de montaje."""
    return {
        "version": "3",
        "lenguaje": "python",
        "framework_pruebas": "pytest",
        "framework_app": "fastapi",
        "modulo": "api.py",
        "huella": "a" * 64,
        "tipo": "endpoint",
        "objetivo": "GET /externo/api/{server_id}/tools",
        "manejador": "tools",
        "aplicacion": "router",
        "dependencias": [],
        "dependencias_detectadas": [
            {
                "parametro": "user",
                "funcion": "require_session",
                "en_proyecto": "auth.py::require_session",
            }
        ],
        "firma": "(server_id: int, user: RequiredSession) -> list[dict]",
        "critical": False,
        "llama_a": [],
        "casos": [
            {
                "id": "valido",
                "entrada": {"metodo": "GET", "ruta": "/externo/api/1/tools"},
                "valor_esperado": {"status_code": 200, "json": []},
                "origen": "docstring",
            },
            {
                "id": "invalido",
                "entrada": {"metodo": "GET", "ruta": "/externo/api/abc/tools"},
                "valor_esperado": {"status_code": 422},
                "origen": "tipo",
            },
        ],
    }


def codigo() -> str:
    """Ensambla el montaje determinista y las pruebas controladas del contrato."""
    return montaje_endpoint(contrato()) + "\n" + PRUEBAS
