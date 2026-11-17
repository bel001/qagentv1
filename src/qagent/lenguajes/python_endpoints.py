"""Comprueba el montaje de FastAPI antes del sandbox, sin importar el proyecto."""

from __future__ import annotations

import ast
from pathlib import Path, PurePosixPath
from typing import Any

from qagent.analysis.arbol_ts import campo, nombrados, parsear, texto
from qagent.analysis.rutas import sentencias_modulo
from qagent.sandbox.ejecucion import DIR_PROYECTO


def montaje_endpoint(contrato: dict[str, Any]) -> str:
    """Plantilla de imports, montaje y cliente calculada a partir del contrato."""
    ruta = PurePosixPath(contrato["modulo"].replace("\\", "/"))
    modulo = ruta.with_suffix("").as_posix().replace("/", ".")
    simbolos = [contrato["aplicacion"]]
    for dependencia in contrato.get("dependencias", []):
        simbolos.extend([dependencia["funcion"], dependencia["reemplazo"]])
    lineas = [
        "from fastapi import FastAPI",
        "from fastapi.testclient import TestClient",
    ]
    if "src" in ruta.parts:
        indice = max(i for i, parte in enumerate(ruta.parts) if parte == "src")
        carpeta = "/".join([DIR_PROYECTO, *ruta.parts[: indice + 1]])
        lineas.extend(["import sys", f"sys.path.insert(0, {carpeta!r})"])
    if all(parte.isidentifier() for parte in modulo.split(".")):
        lineas.append(f"from {modulo} import {', '.join(dict.fromkeys(simbolos))}")
    else:
        lineas.extend(
            [
                "import importlib",
                f"_qagent_modulo = importlib.import_module({modulo!r})",
                *(f"{s} = _qagent_modulo.{s}" for s in dict.fromkeys(simbolos)),
            ]
        )
    objeto = contrato["aplicacion"]
    metodo, destino = contrato["objetivo"].split(" ", 1)
    excepciones = not any(
        caso.get("valor_esperado", {}).get("status_code") == 500
        for caso in contrato.get("casos", [])
    )
    lineas.extend(
        [
            f"app_pruebas = {objeto} if isinstance({objeto}, FastAPI) else FastAPI()",
            f"if app_pruebas is not {objeto}:",
            "    _qagent_ruta = next(",
            f"        r.path for r in {objeto}.routes",
            f"        if getattr(getattr(r, 'endpoint', None), '__name__', '') == {contrato['manejador']!r}",
            f"        and {metodo!r} in (getattr(r, 'methods', None) or set())",
            "    )",
            f"    if not {destino!r}.endswith(_qagent_ruta):",
            "        raise ValueError('El prefijo del router no coincide con el contrato')",
            f"    app_pruebas.include_router({objeto}, prefix={destino!r}[:-len(_qagent_ruta)] if _qagent_ruta else {destino!r})",
            f"client = TestClient(app_pruebas, raise_server_exceptions={excepciones})",
        ]
    )
    return "\n".join(lineas)


def _es_router(contrato: dict[str, Any], raiz: Path) -> bool:
    """Reconoce el símbolo APIRouter del contrato mediante tree-sitter."""
    ruta = raiz / contrato["modulo"]
    try:
        if not ruta.resolve().is_relative_to(raiz.resolve()):
            return False
        arbol = parsear(ruta.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, ValueError):
        return False
    for sentencia in sentencias_modulo(arbol.root_node):
        if sentencia.type != "expression_statement":
            continue
        for asignacion in nombrados(sentencia):
            if asignacion.type != "assignment":
                continue
            if texto(campo(asignacion, "left")) != contrato["aplicacion"]:
                continue
            valor = campo(asignacion, "right")
            if valor is not None and valor.type == "call":
                return texto(campo(valor, "function")).split(".")[-1] == "APIRouter"
    return False


def error_preparacion_endpoint(
    contrato: dict[str, Any], codigo: str, raiz: Path
) -> str | None:
    """Rechaza overrides y TestClient sobre un router en vez de una app FastAPI."""
    if contrato.get("tipo") != "endpoint" or not _es_router(contrato, raiz):
        return None
    arbol = ast.parse(codigo)  # Solo el test generado, nunca la fuente del usuario.
    routers = {contrato["aplicacion"]}
    clientes = {"TestClient"}
    for nodo in ast.walk(arbol):
        if isinstance(nodo, ast.ImportFrom):
            for alias in nodo.names:
                if alias.name in routers:
                    routers.add(alias.asname or alias.name)
                if alias.name == "TestClient":
                    clientes.add(alias.asname or alias.name)
        if isinstance(nodo, ast.Assign) and _es_referencia_router(nodo.value, routers):
            routers.update(t.id for t in nodo.targets if isinstance(t, ast.Name))
    for nodo in ast.walk(arbol):
        if (
            isinstance(nodo, ast.Attribute)
            and nodo.attr == "dependency_overrides"
            and _es_referencia_router(nodo.value, routers)
        ) or (
            isinstance(nodo, ast.Call)
            and isinstance(nodo.func, ast.Name)
            and nodo.func.id in clientes
            and nodo.args
            and _es_referencia_router(nodo.args[0], routers)
        ):
            return (
                "Montaje inválido: APIRouter no es la aplicación de prueba. "
                "Crea app_pruebas = FastAPI(), incluye el router con "
                "app_pruebas.include_router(router), registra los overrides en "
                "app_pruebas.dependency_overrides y usa TestClient(app_pruebas, "
                "raise_server_exceptions=True). Conserva las aserciones."
            )
    return None


def _es_referencia_router(nodo: ast.AST, nombres: set[str]) -> bool:
    return (isinstance(nodo, ast.Name) and nodo.id in nombres) or (
        isinstance(nodo, ast.Attribute) and nodo.attr in nombres
    )
