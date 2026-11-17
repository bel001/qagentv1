"""Recuperación optativa de ejemplos documentados, sin ejecutar ni modificar fuentes."""

from __future__ import annotations

import copy
import hashlib
import re
from pathlib import Path, PurePosixPath
from typing import Any

from qagent.lenguajes.javascript_estructura import gramatica_de
from qagent.lenguajes.javascript_oraculo import _ejemplos, _marcar_contradicciones
from qagent.lenguajes.treesitter import obtener_parser

MAX_ARCHIVOS = 32
MAX_BYTES = 128_000
MAX_EJEMPLOS = 30
MOTIVO_GENERADOR = (
    "Devuelve un generador: hace falta declarar cuántos elementos consumir y qué "
    "valores esperar. El contexto automático no inventa ese contrato."
)


def _leer(raiz: Path, archivo: str) -> str | None:
    ruta = raiz / archivo
    try:
        if ruta.is_symlink() or not ruta.resolve().is_relative_to(raiz.resolve()):
            return None
        if ruta.stat().st_size > MAX_BYTES:
            return None
        return ruta.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeError, ValueError):
        return None


def archivos_documentales(raiz: Path) -> list[str]:
    """README y documentos Markdown locales; excluye enlaces y limita el recorrido."""
    candidatos = [
        p
        for p in raiz.iterdir()
        if p.is_file()
        and p.name.lower().startswith("readme")
        and p.suffix.lower() == ".md"
    ]
    docs = raiz / "docs"
    if docs.is_dir() and not docs.is_symlink():
        # No se siguen enlaces de directorios. El recorrido es determinista y acotado.
        pendientes = [docs]
        recorridos = 0
        while pendientes and recorridos < 128 and len(candidatos) < MAX_ARCHIVOS:
            carpeta = pendientes.pop(0)
            recorridos += 1
            try:
                for ruta in sorted(carpeta.iterdir()):
                    if ruta.is_symlink():
                        continue
                    if ruta.is_dir():
                        pendientes.append(ruta)
                    elif ruta.suffix.lower() == ".md":
                        candidatos.append(ruta)
                        if len(candidatos) >= MAX_ARCHIVOS:
                            break
            except OSError:
                continue
    return sorted({p.relative_to(raiz).as_posix() for p in candidatos})[:MAX_ARCHIVOS]


def _comentarios(fuente: str, modulo: str) -> list[tuple[int, str]]:
    arbol = obtener_parser(gramatica_de(modulo)).parse(fuente.encode("utf-8"))
    pendientes = [arbol.root_node]
    filas = []
    while pendientes:
        nodo = pendientes.pop()
        if nodo.type == "comment" and nodo.text.startswith(b"/**"):
            activo = False
            for i, fila in enumerate(nodo.text.decode("utf-8").splitlines()):
                texto = (
                    re.sub(r"^\s*(?:/\*\*|\*)\s?", "", fila).removesuffix("*/").strip()
                )
                if texto.startswith("@example"):
                    activo = True
                    texto = texto[len("@example") :].strip()
                elif texto.startswith("@"):
                    activo = False
                if activo and texto:
                    filas.append((nodo.start_point.row + i + 1, texto))
        else:
            pendientes.extend(reversed(nodo.named_children))
    return filas


def _markdown(fuente: str, modulo: str) -> list[tuple[int, str]]:
    # El módulo debe identificarse en la sección o el párrafo anterior al ejemplo.
    # Una mención en el índice del README no vincula todos los bloques del archivo.
    referencia = re.compile(r"(?<![\w/.-])" + re.escape(modulo) + r"(?![\w/.-])")
    dentro = False
    seccion = False
    parrafo = ""
    habilitado = False
    filas = []
    for numero, fila in enumerate(fuente.splitlines(), 1):
        texto = fila.strip()
        if texto.startswith("```"):
            if not dentro:
                habilitado = seccion or bool(referencia.search(parrafo))
            else:
                parrafo = ""
            dentro = not dentro
        elif dentro and habilitado:
            filas.append((numero, texto.removeprefix("@example").strip()))
        elif not dentro:
            if texto.startswith("#"):
                seccion = bool(referencia.search(texto))
                parrafo = texto
            elif texto.startswith("@example"):
                if seccion or referencia.search(parrafo):
                    filas.append((numero, texto.removeprefix("@example").strip()))
            elif texto:
                parrafo = texto
    return filas


def _separar(texto: str) -> list[str]:
    """Separa ejemplos con | solo fuera de literales y paréntesis."""
    partes = []
    inicio = 0
    profundidad = 0
    comilla = ""
    escape = False
    for i, caracter in enumerate(texto):
        if comilla:
            if escape:
                escape = False
            elif caracter == "\\":
                escape = True
            elif caracter == comilla:
                comilla = ""
        elif caracter in "\"'`":
            comilla = caracter
        elif caracter in "([{":
            profundidad += 1
        elif caracter in ")]}":
            profundidad -= 1
        elif caracter == "|" and profundidad == 0:
            partes.append(texto[inicio:i].strip())
            inicio = i + 1
    return [*partes, texto[inicio:].strip()]


def _normalizar(fila: str) -> str:
    if "//" in fila:
        return fila
    coincidencia = re.fullmatch(r"(.+?\))\s*(?:=>|→|=(?!=))\s*(.+)", fila)
    return f"{coincidencia[1]} // => {coincidencia[2]}" if coincidencia else fila


def recuperar_funcion(
    raiz: Path, modulo: str, funcion: dict[str, Any], documentos: list[str]
) -> dict[str, Any]:
    """Enriquece una copia con ejemplos explícitos y su procedencia verificable."""
    copia = copy.deepcopy(funcion)
    registro = copia.setdefault("evidencias", {})
    fuentes = []
    revisados = []
    for archivo in list(dict.fromkeys([modulo, *documentos]))[: MAX_ARCHIVOS + 1]:
        # Los archivos del contrato no autorizan leer otros módulos ni secretos.
        if archivo != modulo and not (
            PurePosixPath(archivo).suffix.lower() == ".md"
            and (
                archivo.startswith("docs/")
                or PurePosixPath(archivo).name.lower().startswith("readme")
            )
        ):
            continue
        fuente = _leer(raiz, archivo)
        if fuente is None:
            continue
        revisados.append(archivo)
        filas = (
            _comentarios(fuente, modulo)
            if archivo == modulo
            else _markdown(fuente, modulo)
        )
        huella = hashlib.sha256(fuente.encode("utf-8")).hexdigest()
        for linea, original in filas:
            if len(original) > 6000:
                continue
            for fila in _separar(original):
                if not re.match(re.escape(funcion["nombre"]) + r"\s*\(", fila):
                    continue
                temporal = {
                    **funcion,
                    "jsdoc": {
                        "ejemplos": [{"texto": _normalizar(fila), "linea": linea}]
                    },
                }
                encontrados = _ejemplos(temporal, archivo, funcion.get("retorno"))
                for entrada in encontrados.values():
                    identificador = (
                        "contexto:"
                        + hashlib.sha256(
                            f"{modulo}:{funcion['nombre']}:{archivo}:{linea}:{fila}".encode()
                        ).hexdigest()[:40]
                    )
                    evidencia = entrada["evidencia"]
                    evidencia.update(
                        id=identificador,
                        fuente="jsdoc" if archivo == modulo else "contrato_explicito",
                        fragmento=original,
                    )
                    registro[identificador] = entrada
                    fuentes.append(
                        {
                            "archivo": archivo,
                            "linea_inicio": linea,
                            "fragmento": original,
                            "huella": huella,
                        }
                    )
                if len(fuentes) >= MAX_EJEMPLOS:
                    break
            if len(fuentes) >= MAX_EJEMPLOS:
                break
        if len(fuentes) >= MAX_EJEMPLOS:
            break
    _marcar_contradicciones(
        {i: e for i, e in registro.items() if "entrada_documentada" in e}
    )
    contradiccion = any(
        e["evidencia"]["caracter"] == "contradictoria" for e in registro.values()
    )
    verificable = any(
        "valor_documentado" in e or "excepcion_documentada" in e
        for e in registro.values()
    )
    estado = (
        "recuperado"
        if verificable
        else "contradictorio"
        if contradiccion
        else "insuficiente"
    )
    motivo = "Se encontraron ejemplos explícitos con entrada y resultado."
    if not verificable:
        motivo = (
            "Las fuentes se contradicen; no se eligió un resultado."
            if contradiccion
            else "No se encontraron ejemplos con entrada y resultado explícitos."
        )
    if funcion.get("es_generador"):
        estado, motivo = "no_soportado", MOTIVO_GENERADOR
    copia["contexto_recuperado"] = {
        "version": "1",
        "estado": estado,
        "motivo": motivo,
        "fuentes": fuentes,
        "archivos_revisados": revisados,
    }
    return copia


def completar_modulos(
    raiz: Path, modulos: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Busca una sola lista acotada de documentos y conserva los módulos originales."""
    documentos = archivos_documentales(raiz)
    return [
        {
            **m,
            "funciones": [
                recuperar_funcion(raiz, m["ruta"], f, documentos)
                for f in m.get("funciones", [])
            ],
        }
        for m in modulos
    ]


def reconstruir_contexto(
    raiz: Path, contrato: dict[str, Any], funcion: dict[str, Any]
) -> dict[str, Any]:
    """Relee fuentes y exige las mismas huellas, sin confiar en valores del contrato."""
    contexto = contrato.get("contexto_recuperado")
    if not contexto:
        return funcion
    for fuente in contexto["fuentes"]:
        texto = _leer(raiz, fuente["archivo"])
        if (
            texto is None
            or hashlib.sha256(texto.encode("utf-8")).hexdigest() != fuente["huella"]
        ):
            raise ValueError(
                "Cambió una fuente de contexto; inicia una nueva planificación."
            )
    nueva = recuperar_funcion(
        raiz, contrato["modulo"], funcion, contexto["archivos_revisados"]
    )
    if nueva["contexto_recuperado"] != contexto:
        raise ValueError(
            "El contexto guardado no coincide con sus fuentes; vuelve a planificar."
        )
    return nueva
