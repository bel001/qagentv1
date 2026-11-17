"""Oráculo estático Java: vincula cada aserción al caso del Planner (#184).

Es conservador: rechaza construcciones no demostrables, sin evaluar Java ni
consultar IA. La compilación y la ejecución real corresponden al sandbox #182.
"""

from __future__ import annotations

import json
import re
from decimal import Decimal
from typing import Any

from tree_sitter import Node

from qagent.lenguajes.java_aserciones import (
    NO_LITERAL,
    AsercionJava,
    analizar_junit,
    argumentos,
    literal,
    nodos,
    resolver,
    texto,
)
from qagent.lenguajes.java_identidad import (
    base_de,
    es_sobrecarga,
    literal_del_tipo,
    literal_esperado,
)
from qagent.lenguajes.treesitter import obtener_parser

#: Tipos de texto sin `equals` por contenido contra un String: su resultado se compara
#: con `assertEquals("esperado", <llamada>.toString())`.
TIPOS_TEXTO = frozenset({"CharSequence", "StringBuilder", "StringBuffer"})
_ENTEROS = frozenset(
    {"byte", "short", "int", "long", "Byte", "Short", "Integer", "Long"}
)


def validar_java(
    contrato: dict[str, Any], codigo: str, contexto: dict[str, Any] | None = None
) -> str | None:
    """Comprueba JUnit real, entradas, esperado/excepción y Mockito de constructor.

    Con contexto verifica también paquete, clase y constructores de la fuente.
    Cada aserción debe corresponder a un caso del contrato y cada caso necesita
    una comprobación. No acepta helpers, control de flujo ni aserciones ajenas.
    """
    try:
        analisis = analizar_junit(codigo)
        problema = _validar(contrato, analisis, contexto)
    except (SyntaxError, ValueError, RecursionError, KeyError, TypeError) as error:
        problema = str(error) or "no se pudo demostrar el oráculo del test Java."
    return "Oráculo inválido: " + problema if problema else None


def _validar(contrato, analisis, contexto):
    """Vincula aserciones, casos y contexto sin ejecutar el código Java."""
    if analisis.evasiones:
        return analisis.evasiones[0]
    if not analisis.aserciones:
        return "el test no contiene aserciones JUnit verificables."
    if any(n.type == "field_declaration" for n in nodos(analisis.raiz)):
        return "usa variables locales estables; los campos de la prueba no son oráculos demostrables."
    clase, metodo = base_de(contrato["objetivo"]).rsplit(".", 1)
    sobrecarga = es_sobrecarga(contrato["objetivo"])
    clase_test = "_".join(clase.split(".")) + "Test"
    clases = [n for n in analisis.raiz.named_children if n.type == "class_declaration"]
    if len(clases) != 1 or texto(clases[0].child_by_field_name("name")) != clase_test:
        return f"se requiere la clase de prueba {clase_test}."
    if contexto is not None:
        problema = _validar_contexto(analisis, contexto, contrato)
        if problema:
            return problema
    for prueba in analisis.pruebas:
        if not any(a.prueba == prueba for a in analisis.aserciones):
            return f"el método {prueba} no comprueba ningún caso."
    if len(analisis.aserciones) != len(contrato["casos"]):
        return "debe haber una aserción del contrato por caso, sin aserciones ajenas o tautologías."
    parametros, es_static, retorno = _firma(contrato["firma"])
    tipos = _tipos_de_firma(contrato["firma"])
    disponibles = list(analisis.aserciones)
    usados: set[int] = set()
    for caso in contrato["casos"]:
        problema = _validar_caso(
            caso,
            disponibles,
            metodo,
            clase,
            parametros,
            es_static,
            retorno,
            contexto,
            usados,
            tipos if sobrecarga else None,
        )
        if problema:
            return problema
    if contexto is not None:
        problema = _mockito(analisis.raiz, analisis.aserciones, usados)
        if problema:
            return problema
    return _instrucciones(analisis, usados)


def _validar_contexto(analisis, contexto, contrato) -> str | None:
    """Comprueba paquete e imports de la prueba contra la fuente analizada."""
    paquete = next(
        (
            texto(n.named_children[-1])
            for n in analisis.raiz.named_children
            if n.type == "package_declaration"
        ),
        "",
    )
    if paquete != contexto["paquete"]:
        return "el paquete de la prueba no coincide con la fuente."
    return _imports_coherentes(analisis.raiz, contexto, contrato)


def _validar_caso(
    caso,
    disponibles: list[AsercionJava],
    metodo: str,
    clase: str,
    parametros: list[str],
    es_static: bool,
    retorno: str,
    contexto,
    usados: set[int],
    tipos_sobrecarga: list[str] | None = None,
) -> str | None:
    """Busca y consume la aserción que demuestra un caso del contrato.

    Con ``tipos_sobrecarga`` (el método está sobrecargado) cada argumento debe ser el
    literal exacto de su tipo, para que Java llame a esta versión y no a otra.
    """
    entrada = caso.get("entrada")
    if isinstance(entrada, dict):
        if set(entrada) != set(parametros):
            return f"las entradas del caso {caso['id']} no corresponden a su firma."
        esperados = [entrada[p] for p in parametros]
    elif isinstance(entrada, list):
        esperados = entrada
    elif entrada is None and not parametros:
        esperados = []
    else:
        return f"las entradas del caso {caso['id']} no son verificables."
    pistas: list[tuple[int, str]] = []
    encontrada, problema = _buscar_asercion(
        disponibles,
        esperados,
        metodo,
        clase,
        es_static,
        retorno,
        caso,
        contexto,
        usados,
        pistas,
        tipos_sobrecarga,
    )
    if problema:
        return problema
    if encontrada is None:
        # La pista de la aserción que más cerca estuvo: así el siguiente intento
        # sabe qué argumento, llamada, tipo o aserción corregir.
        detalle = (
            max(pistas, key=lambda pista: pista[0])[1]
            if pistas
            else _pista_sin_llamada(disponibles, metodo, clase, retorno)
        )
        return (
            f"el caso '{caso['id']}' no comprueba sus entradas y valor esperado o "
            f"excepción sobre el método real. Corrige esto: {detalle}"
        )
    disponibles.pop(encontrada)
    return None


def _buscar_asercion(
    disponibles: list[AsercionJava],
    esperados: list,
    metodo: str,
    clase: str,
    es_static: bool,
    retorno: str,
    caso,
    contexto,
    usados: set[int],
    pistas: list[tuple[int, str]] | None = None,
    tipos_sobrecarga: list[str] | None = None,
) -> tuple[int | None, str | None]:
    """Devuelve el índice de la aserción del caso y el problema de constructor, si hay.

    En `pistas` deja, por cada aserción que llama al método pero no demuestra el
    caso, hasta dónde llegó (1 receptor, 2 argumentos, 3 comprobación) y qué falló.
    """
    pistas = pistas if pistas is not None else []
    for indice, asercion in enumerate(disponibles):
        llamada = _llamada(asercion)
        if llamada is None or texto(llamada.child_by_field_name("name")) != metodo:
            continue
        receptor = llamada.child_by_field_name("object")
        if receptor is None:
            pistas.append(
                (
                    1,
                    (
                        f"la aserción de la línea {asercion.linea} llama a {metodo}(...) "
                        f"sin receptor; usa {_forma_receptor(clase, metodo, es_static)}."
                    ),
                )
            )
            continue
        nombres = {clase}
        if contexto is not None and contexto["paquete"]:
            nombres.add(contexto["paquete"] + "." + clase)
        if es_static:
            if (
                texto(receptor) not in nombres
                or texto(receptor).split(".")[0] in asercion.alias
            ):
                pistas.append(
                    (
                        1,
                        (
                            f"la aserción de la línea {asercion.linea} llama a {metodo} "
                            f"sobre `{texto(receptor)}`; el método es static: usa "
                            f"{_forma_receptor(clase, metodo, es_static)}."
                        ),
                    )
                )
                continue
        else:
            receptor = resolver(receptor, asercion.alias)
            if (
                receptor.type != "object_creation_expression"
                or texto(receptor.child_by_field_name("type")) not in nombres
            ):
                pistas.append(
                    (
                        1,
                        (
                            f"la aserción de la línea {asercion.linea} no llama a {metodo} "
                            f"sobre un objeto construido en la prueba; usa "
                            f"{_forma_receptor(clase, metodo, es_static)}."
                        ),
                    )
                )
                continue
            if contexto is not None:
                problema, mocks = _constructor(receptor, asercion.alias, contexto)
                if problema:
                    return None, problema
                usados.update(mocks)
        args = argumentos(llamada)
        if len(args) != len(esperados) or not all(
            _igual(literal(a, asercion.alias), e)
            for a, e in zip(args, esperados, strict=False)
        ):
            pistas.append((2, _pista_argumentos(asercion, args, esperados, caso)))
            continue
        if tipos_sobrecarga is not None:
            pista = _pista_literales(asercion, args, tipos_sobrecarga, metodo)
            if pista is not None:
                pistas.append((2, pista))
                continue
        if not _comprueba(asercion, caso, retorno):
            pistas.append((3, _pista_comprobacion(asercion, caso, retorno)))
            continue
        return indice, None
    return None, None


def _tipos_de_firma(firma: str) -> list[str]:
    """Tipos de los parámetros de la firma del contrato, en orden."""
    raiz = (
        obtener_parser("java")
        .parse(("class Contexto { " + firma + " {} }").encode("utf-8"))
        .root_node
    )
    metodo = next((n for n in nodos(raiz) if n.type == "method_declaration"), None)
    if metodo is None:
        return []
    parametros = metodo.child_by_field_name("parameters")
    return [
        texto(p.child_by_field_name("type"))
        for p in (parametros.named_children if parametros is not None else [])
        if p.child_by_field_name("type") is not None
    ]


def _pista_literales(
    asercion: AsercionJava, args: list[Node], tipos: list[str], metodo: str
) -> str | None:
    """En una sobrecarga, el argumento cuyo literal no es del tipo de esa versión."""
    for posicion, (argumento, tipo) in enumerate(zip(args, tipos, strict=False), 1):
        nodo = resolver(argumento, asercion.alias)
        if nodo.type == "unary_expression":
            nodo = nodo.child_by_field_name("operand") or nodo
        if literal_del_tipo(nodo.type, texto(nodo), tipo):
            continue
        forma = literal_esperado(tipo) or f"un literal de tipo {tipo}"
        return (
            f"{metodo} está sobrecargado: en la llamada de la línea {asercion.linea} "
            f"el argumento {posicion} (`{texto(argumento)}`) debe ser {forma} para que "
            f"Java llame a la versión con {tipo} y no a otra."
        )
    return None


def _forma_receptor(clase: str, metodo: str, es_static: bool) -> str:
    """Cómo debe escribirse la llamada al método real."""
    if es_static:
        return f"{clase}.{metodo}(...)"
    return f"new {clase}(...).{metodo}(...) (o una variable local con ese objeto)"


def _json(valor: Any) -> str:
    return json.dumps(valor, ensure_ascii=False)


def _pista_sin_llamada(
    disponibles: list[AsercionJava], metodo: str, clase: str, retorno: str
) -> str:
    """Ninguna aserción llama al método de forma directa: dice cuál lo envuelve."""
    simple = _tipo_simple(retorno)
    for asercion in disponibles:
        if asercion.tipo in {"excepcion", "excepcion_exacta"}:
            continue
        actual = resolver(asercion.actual, asercion.alias)
        anidada = next(
            (
                n
                for n in nodos(actual)
                if n.type == "method_invocation"
                and texto(n.child_by_field_name("name")) == metodo
            ),
            None,
        )
        if anidada is None:
            continue
        admitido = (
            " Para comparar el texto solo se admite `.toString()` sobre la llamada."
            if simple in TIPOS_TEXTO
            else ""
        )
        return (
            f"la aserción de la línea {asercion.linea} compara `{texto(actual)}`: la "
            f"llamada a {metodo} está dentro de otra operación. Compara directamente "
            f"el resultado de {clase}.{metodo}(...), sin transformarlo.{admitido}"
        )
    return (
        f"ninguna aserción llama a {clase}.{metodo}(...) con las entradas del caso; "
        "la llamada al método real debe ser el valor obtenido de la aserción."
    )


def _pista_argumentos(
    asercion: AsercionJava, args: list[Node], esperados: list, caso: dict[str, Any]
) -> str:
    """Qué argumento de la llamada no coincide con la entrada del caso."""
    lugar = f"la llamada de la línea {asercion.linea}"
    if len(args) != len(esperados):
        return (
            f"{lugar} pasa {len(args)} argumento(s) y el caso '{caso['id']}' define "
            f"{len(esperados)}: {_json(esperados)}."
        )
    for posicion, (argumento, esperado) in enumerate(
        zip(args, esperados, strict=False), start=1
    ):
        if not _igual(literal(argumento, asercion.alias), esperado):
            return (
                f"en {lugar} el argumento {posicion} es `{texto(argumento)}` y el caso "
                f"'{caso['id']}' pide {_json(esperado)}; escríbelo como literal con "
                "ese valor exacto."
            )
    return f"{lugar} no usa las entradas del caso '{caso['id']}': {_json(esperados)}."


def _pista_comprobacion(
    asercion: AsercionJava, caso: dict[str, Any], retorno: str
) -> str:
    """Por qué la aserción llama bien al método pero no demuestra el caso."""
    lugar = f"la aserción de la línea {asercion.linea}"
    if not _argumentos_asercion_validos(asercion):
        return (
            f"{lugar} lleva argumentos de más: solo se admite un mensaje literal (y "
            "una delta literal en float/double)."
        )
    if "excepcion" in caso:
        excepcion = caso["excepcion"]
        if asercion.tipo != "excepcion" or asercion.valor is None:
            return (
                f"el caso '{caso['id']}' espera la excepción {excepcion}: usa "
                f"assertThrows({excepcion}.class, () -> <llamada>)."
            )
        return (
            f"{lugar} espera `{texto(asercion.valor)}` y el contrato pide "
            f"{excepcion}.class."
        )
    if "valor_esperado" not in caso:
        return f"el caso '{caso['id']}' no define un valor esperado verificable."
    esperado = caso["valor_esperado"]
    if not _tipo_comparacion(asercion, esperado, retorno):
        return f"{lugar}: {_pista_tipo(asercion, esperado, retorno)}"
    if asercion.tipo in {"igualdad", "array"}:
        if not _igual(literal(asercion.valor, asercion.alias), esperado):
            return (
                f"{lugar} compara con `{texto(asercion.valor)}` y el contrato pide "
                f"{_json(esperado)}; no cambies el valor esperado."
            )
        return (
            f"{lugar}: la delta debe ser un literal entre 0 y "
            "1e-6 * max(1, |esperado|), y solo se admite en float/double."
        )
    if isinstance(esperado, bool):
        forma = "assertTrue" if esperado else "assertFalse"
        return (
            f"el caso '{caso['id']}' espera {_json(esperado)}: usa {forma}(<llamada>)."
        )
    if esperado is None:
        return f"el caso '{caso['id']}' espera null: usa assertNull(<llamada>)."
    return (
        f"el caso '{caso['id']}' espera {_json(esperado)}: usa "
        "assertEquals(<esperado>, <llamada>)."
    )


def _pista_tipo(asercion: AsercionJava, esperado: Any, retorno: str) -> str:
    """La forma de comparar que corresponde al tipo de retorno del método."""
    simple = _tipo_simple(retorno)
    if _usa_to_string(asercion) and not (
        isinstance(esperado, str) and simple in TIPOS_TEXTO
    ):
        return (
            f"quita `.toString()`: el método devuelve {simple} y su resultado se "
            "compara directamente."
        )
    if isinstance(esperado, list):
        if retorno.endswith("[]"):
            return (
                "el método devuelve un array: usa assertArrayEquals con un array "
                "literal (new T[] {...}) como esperado."
            )
        return (
            "el método devuelve una lista: usa assertEquals(List.of(...), <llamada>)."
        )
    if asercion.tipo == "array":
        return f"el método devuelve {simple}, no un array: usa assertEquals."
    if isinstance(esperado, str):
        if simple in {"char", "Character"}:
            return "el método devuelve char: el esperado es un literal de carácter ('a'), no un String."
        if simple == "String":
            return 'el esperado debe ser un literal String entre comillas ("...").'
        if simple in TIPOS_TEXTO:
            return (
                f"el método devuelve {simple}, que no se compara con equals contra un "
                f"String: compara su contenido con assertEquals({_json(esperado)}, "
                "<llamada>.toString())."
            )
        return (
            f"el contrato espera el texto {_json(esperado)}, pero el método devuelve "
            f"{simple}: este guardrail no puede demostrar esa comparación."
        )
    if isinstance(esperado, bool):
        return f"el contrato espera un booleano y el método devuelve {simple}."
    if isinstance(esperado, (int, float)):
        if simple in _ENTEROS:
            return (
                f"el método devuelve {simple}: el esperado es un literal entero, sin "
                "decimales ni delta."
            )
        return f"el contrato espera un número y el método devuelve {simple}."
    if esperado is None:
        return f"el método devuelve {simple}, que no puede ser null."
    return f"la aserción no corresponde al tipo de retorno {retorno}."


def _instrucciones(analisis, mocks: set[int]) -> str | None:
    """Exige instrucciones directas: no permite código ajeno que fabrique un fallo."""
    pruebas = {}
    for asercion in analisis.aserciones:
        pruebas.setdefault(asercion.prueba, []).append(asercion)
    for metodo in (n for n in nodos(analisis.raiz) if n.type == "method_declaration"):
        aserciones = pruebas.get(texto(metodo.child_by_field_name("name")), [])
        alias = aserciones[0].alias if aserciones else {}
        llamadas = {
            _llamada(a).start_byte for a in aserciones if _llamada(a) is not None
        }
        receptores = {
            resolver(_llamada(a).child_by_field_name("object"), alias).start_byte
            for a in aserciones
            if _llamada(a) is not None
            and _llamada(a).child_by_field_name("object") is not None
        }
        lambdas = {
            resolver(a.actual, alias).start_byte
            for a in aserciones
            if a.tipo in {"excepcion", "excepcion_exacta"}
        }
        verificaciones = {a.actual.parent.parent.start_byte for a in aserciones}
        cuerpo = metodo.child_by_field_name("body")
        if cuerpo is None:
            continue
        for instruccion in cuerpo.named_children:
            if instruccion.type in {"line_comment", "block_comment"}:
                continue
            if instruccion.type == "local_variable_declaration":
                for variable in (
                    v
                    for v in instruccion.named_children
                    if v.type == "variable_declarator"
                ):
                    valor = variable.child_by_field_name("value")
                    if valor is None:
                        return "las variables locales deben tener un valor verificable."
                    valor = resolver(valor, alias)
                    if (
                        literal(valor, alias) is not NO_LITERAL
                        or valor.start_byte
                        in llamadas | receptores | mocks | lambdas | verificaciones
                    ):
                        continue
                    return "una variable local ejecuta una operación ajena al caso o al constructor declarado."
                continue
            if (
                instruccion.type == "expression_statement"
                and len(instruccion.named_children) == 1
            ):
                llamada = instruccion.named_children[0]
                if llamada.start_byte in verificaciones:
                    continue
                receptor = llamada.child_by_field_name("object")
                if (
                    llamada.type == "method_invocation"
                    and texto(llamada.child_by_field_name("name"))
                    in {"thenReturn", "thenThrow"}
                    and receptor is not None
                    and receptor.type == "method_invocation"
                    and texto(receptor.child_by_field_name("name")) == "when"
                ) and all(
                    literal(a, alias) is not NO_LITERAL or a.type == "class_literal"
                    for a in argumentos(llamada)
                ):
                    continue
            return "la prueba contiene una instrucción ajena a las comprobaciones y mocks del contrato."
    return None


def _firma(firma: str) -> tuple[list[str], bool, str]:
    """Lee los nombres de parámetros y static de la firma, sin compilarla."""
    raiz = (
        obtener_parser("java")
        .parse(("class Contexto { " + firma + " {} }").encode("utf-8"))
        .root_node
    )
    if raiz.has_error:
        raise ValueError("La firma Java del contrato no es verificable.")
    metodo = next(n for n in nodos(raiz) if n.type == "method_declaration")
    parametros = metodo.child_by_field_name("parameters")
    nombres = []
    for parametro in parametros.named_children:
        nombre = parametro.child_by_field_name("name")
        if parametro.type != "formal_parameter" or nombre is None:
            raise ValueError(
                "Este guardrail necesita parámetros fijos; no admite varargs."
            )
        nombres.append(texto(nombre))
    modificadores = next(
        (n for n in metodo.named_children if n.type == "modifiers"), None
    )
    return (
        nombres,
        modificadores is not None
        and any(h.type == "static" for h in modificadores.children),
        texto(metodo.child_by_field_name("type")),
    )


def _llamada(asercion: AsercionJava) -> Node | None:
    """Exige una llamada directa o una lambda de assertThrows que solo la invoque."""
    actual = resolver(asercion.actual, asercion.alias)
    if asercion.tipo in {"excepcion", "excepcion_exacta"}:
        if actual.type != "lambda_expression":
            return None
        parametros = actual.child_by_field_name("parameters")
        if (
            parametros is None
            or parametros.type != "formal_parameters"
            or parametros.named_children
        ):
            return None
        actual = actual.child_by_field_name("body")
        if actual is not None and actual.type == "block":
            hijos = [
                h
                for h in actual.named_children
                if h.type not in {"line_comment", "block_comment"}
            ]
            if (
                len(hijos) != 1
                or hijos[0].type != "expression_statement"
                or len(hijos[0].named_children) != 1
            ):
                return None
            actual = hijos[0].named_children[0]
    elif _es_to_string(actual):
        # `<llamada>.toString()`: la única transformación que se reconoce, y solo se
        # acepta si el método devuelve un tipo de texto (ver `_tipo_comparacion`).
        actual = resolver(actual.child_by_field_name("object"), asercion.alias)
    return actual if actual is not None and actual.type == "method_invocation" else None


def _es_to_string(nodo: Node | None) -> bool:
    """`x.toString()` sin argumentos."""
    return (
        nodo is not None
        and nodo.type == "method_invocation"
        and texto(nodo.child_by_field_name("name")) == "toString"
        and nodo.child_by_field_name("object") is not None
        and not argumentos(nodo)
    )


def _usa_to_string(asercion: AsercionJava) -> bool:
    """Si la aserción compara `<llamada>.toString()` en vez del resultado directo."""
    return asercion.tipo not in {"excepcion", "excepcion_exacta"} and _es_to_string(
        resolver(asercion.actual, asercion.alias)
    )


def _tipo_simple(retorno: str) -> str:
    """`java.util.List<String>` -> `List`."""
    return re.sub(r"<.*>", "", retorno).rsplit(".", 1)[-1]


def _comprueba(asercion: AsercionJava, caso: dict[str, Any], retorno: str) -> bool:
    """Verifica el literal esperado o la clase exacta de excepción del contrato."""
    if not _argumentos_asercion_validos(asercion):
        return False
    if "excepcion" in caso:
        return (
            asercion.tipo == "excepcion"
            and asercion.valor is not None
            and asercion.valor.type == "class_literal"
            and texto(asercion.valor).removesuffix(".class").removeprefix("java.lang.")
            == caso["excepcion"].removeprefix("java.lang.")
        )
    esperado = caso.get("valor_esperado", NO_LITERAL)
    if not _tipo_comparacion(asercion, esperado, retorno):
        return False
    if asercion.tipo in {"igualdad", "array"}:
        if not _igual(literal(asercion.valor, asercion.alias), esperado):
            return False
        if asercion.delta is not None:
            delta = literal(asercion.delta, asercion.alias)
            return (
                not isinstance(esperado, bool)
                and isinstance(esperado, (int, float))
                and retorno.rsplit(".", 1)[-1] in {"double", "float", "Double", "Float"}
                and isinstance(delta, Decimal)
                and Decimal(0)
                <= delta
                <= max(Decimal(1), abs(Decimal(str(esperado)))) * Decimal("0.000001")
            )
        return True
    if asercion.tipo == "booleano" and isinstance(esperado, bool):
        return asercion.esperado == ("bool:True" if esperado else "bool:False")
    return asercion.tipo == "nulo" and esperado is None


def _tipo_comparacion(asercion: AsercionJava, esperado: Any, retorno: str) -> bool:
    """Evita igualdad de identidad de arrays, char/String y coerciones de enteros."""
    valor = (
        resolver(asercion.valor, asercion.alias) if asercion.valor is not None else None
    )
    simple = _tipo_simple(retorno)
    con_texto = _usa_to_string(asercion)
    if con_texto != (isinstance(esperado, str) and simple in TIPOS_TEXTO):
        # CharSequence, StringBuilder y StringBuffer no definen equals por contenido:
        # se comparan con `.toString()`. En cualquier otro retorno, `.toString()`
        # cambiaría lo que se comprueba y no se admite.
        return False
    if isinstance(esperado, list):
        if retorno.endswith("[]"):
            return (
                asercion.tipo == "array"
                and valor is not None
                and valor.type == "array_creation_expression"
            )
        return (
            asercion.tipo == "igualdad"
            and valor is not None
            and valor.type == "method_invocation"
            and simple == "List"
        )
    if asercion.tipo == "array":
        return False
    if isinstance(esperado, str):
        return valor is not None and (
            valor.type == "character_literal"
            if simple in {"char", "Character"}
            else valor.type == "string_literal"
            if simple == "String" or simple in TIPOS_TEXTO
            else False
        )
    if (
        isinstance(esperado, (int, float))
        and not isinstance(esperado, bool)
        and simple in _ENTEROS
    ):
        if valor is None:
            return False
        if valor.type == "unary_expression":
            valor = valor.child_by_field_name("operand")
        return (
            valor is not None
            and valor.type.endswith("integer_literal")
            and asercion.delta is None
        )
    if isinstance(esperado, bool):
        return simple in {"boolean", "Boolean"}
    if isinstance(esperado, (int, float)):
        return simple in {"double", "float", "Double", "Float"}
    if esperado is None:
        return simple not in {
            "byte",
            "short",
            "int",
            "long",
            "float",
            "double",
            "char",
            "boolean",
            "void",
        }
    return False


def _argumentos_asercion_validos(asercion: AsercionJava) -> bool:
    """No permite proveedores de mensajes ni argumentos extra que ejecuten código."""
    invocacion = asercion.actual.parent.parent
    args = argumentos(invocacion)
    base = (
        2
        if asercion.tipo
        in {"igualdad", "array", "distinto", "excepcion", "excepcion_exacta"}
        else 1
    )
    extras = args[base:]
    if not extras:
        return len(args) == base
    valores = [literal(a, asercion.alias) for a in extras]
    if asercion.tipo in {"igualdad", "array"} and isinstance(valores[0], Decimal):
        return len(valores) == 1 or (len(valores) == 2 and isinstance(valores[1], str))
    return len(valores) == 1 and isinstance(valores[0], str)


def _igual(valor: Any, esperado: Any) -> bool:
    """Igualdad de datos del contrato, separando booleanos, números, nulos y listas."""
    if valor is NO_LITERAL or esperado is NO_LITERAL:
        return False
    if isinstance(esperado, bool):
        return type(valor) is bool and valor == esperado
    if isinstance(esperado, (int, float)):
        return isinstance(valor, Decimal) and valor == Decimal(str(esperado))
    if isinstance(esperado, list):
        return (
            isinstance(valor, list)
            and len(valor) == len(esperado)
            and all(_igual(v, e) for v, e in zip(valor, esperado, strict=False))
        )
    return type(valor) is type(esperado) and valor == esperado


def _constructor(
    nodo: Node, alias: dict[str, Node], contexto: dict[str, Any]
) -> tuple[str | None, set[int]]:
    """Acepta el constructor real y mocks de sus dependencias en el orden declarado."""
    args = argumentos(nodo)
    if not args and (
        contexto["constructor_implicito"]
        or any(not c["parametros"] for c in contexto["constructores"])
    ):
        return None, set()
    for constructor in contexto["constructores"]:
        parametros = constructor["parametros"]
        if len(parametros) != len(args):
            continue
        usados = set()
        valido = True
        for argumento, parametro in zip(args, parametros, strict=False):
            valor = resolver(argumento, alias)
            tipo = re.sub(r"<.*>", "", parametro["tipo"]).strip()
            simple = tipo.rsplit(".", 1)[-1]
            if simple in {
                "byte",
                "short",
                "int",
                "long",
                "float",
                "double",
                "boolean",
                "char",
                "String",
                "List",
                "Map",
                "Set",
                "Collection",
            }:
                valido = False
                break
            opciones = argumentos(valor) if valor.type == "method_invocation" else []
            nombres = {tipo}
            nombres.update(
                i.removeprefix("import ").removesuffix(";").strip()
                for i in contexto["imports"]
                if i.strip().endswith("." + simple + ";")
                and not i.strip().startswith("import static ")
            )
            if (
                texto(valor.child_by_field_name("name")) != "mock"
                or len(opciones) != 1
                or opciones[0].type != "class_literal"
                or texto(opciones[0]).removesuffix(".class") not in nombres
            ):
                valido = False
                break
            usados.add(valor.start_byte)
        if valido:
            return None, usados
    return (
        "el constructor debe ser accesible y sus mocks corresponder solo a dependencias declaradas; no se inventan valores de construcción.",
        set(),
    )


def _imports_coherentes(
    raiz: Node, contexto: dict[str, Any], contrato: dict[str, Any]
) -> str | None:
    """Impide sustituir el objetivo o su dependencia por un homónimo de otro paquete."""
    origen = {}
    for entrada in contexto["imports"]:
        nombre = entrada.replace(" ", "").removeprefix("import").removesuffix(";")
        if not nombre.startswith("static") and not nombre.endswith(".*"):
            origen[nombre.rsplit(".", 1)[-1]] = nombre
    clase = contexto["clase"].split(".")[0]
    origen[clase] = (contexto["paquete"] + "." if contexto["paquete"] else "") + clase
    criticos = {clase}
    for constructor in contexto["constructores"]:
        for parametro in constructor["parametros"]:
            tipo = re.sub(r"<.*>", "", parametro["tipo"]).strip()
            simple = tipo.rsplit(".", 1)[-1]
            criticos.add(simple)
            origen.setdefault(
                simple,
                tipo
                if "." in tipo
                else (contexto["paquete"] + "." if contexto["paquete"] else "")
                + simple,
            )
    conocidos = {
        "Exception",
        "RuntimeException",
        "IllegalArgumentException",
        "IllegalStateException",
        "NullPointerException",
        "ArithmeticException",
        "IndexOutOfBoundsException",
        "UnsupportedOperationException",
        "AssertionError",
    }
    for caso in contrato["casos"]:
        tipo = caso.get("excepcion")
        if tipo:
            simple = tipo.rsplit(".", 1)[-1]
            criticos.add(simple)
            origen.setdefault(
                simple,
                tipo
                if "." in tipo
                else "java.lang." + tipo
                if tipo in conocidos
                else (contexto["paquete"] + "." if contexto["paquete"] else "") + tipo,
            )
    for nodo in raiz.named_children:
        if nodo.type != "import_declaration":
            continue
        nombre = texto(nodo).replace(" ", "").removeprefix("import").removesuffix(";")
        if (
            not nombre.startswith("static")
            and nombre.rsplit(".", 1)[-1] in criticos
            and nombre != origen[nombre.rsplit(".", 1)[-1]]
        ):
            return "un import sustituye el objetivo, dependencia o excepción por un tipo de otro paquete."
    return None


def _mockito(
    raiz: Node, aserciones: list[AsercionJava], usados: set[int]
) -> str | None:
    """Rechaza mocks del objetivo, spies y stubs que no pertenecen a dependencias."""
    imports = [
        texto(n).replace(" ", "")
        for n in raiz.named_children
        if n.type == "import_declaration"
    ]
    llamadas = [n for n in nodos(raiz) if n.type == "method_invocation"]
    aliases = [a.alias for a in aserciones]
    for llamada in llamadas:
        nombre = texto(llamada.child_by_field_name("name"))
        if nombre in {
            "spy",
            "mockStatic",
            "mockConstruction",
            "doReturn",
            "doThrow",
            "doAnswer",
            "verify",
            "lenient",
        }:
            return f"Mockito {nombre} no está permitido para sustituir o alterar el objetivo."
        if nombre == "mock":
            receptor = texto(llamada.child_by_field_name("object"))
            valido = (
                receptor == "org.mockito.Mockito"
                or (
                    receptor == "Mockito"
                    and any(i == "importorg.mockito.Mockito;" for i in imports)
                )
                or (
                    not receptor
                    and any(
                        i
                        in {
                            "importstaticorg.mockito.Mockito.mock;",
                            "importstaticorg.mockito.Mockito.*;",
                        }
                        for i in imports
                    )
                )
            )
            if not valido or llamada.start_byte not in usados:
                return "cada mock debe provenir de Mockito y utilizarse exclusivamente como dependencia del constructor real."
        if nombre == "when":
            receptor = texto(llamada.child_by_field_name("object"))
            proveedor = (
                receptor == "org.mockito.Mockito"
                or (receptor == "Mockito" and "importorg.mockito.Mockito;" in imports)
                or (
                    not receptor
                    and any(
                        i
                        in {
                            "importstaticorg.mockito.Mockito.when;",
                            "importstaticorg.mockito.Mockito.*;",
                        }
                        for i in imports
                    )
                )
            )
            if not proveedor:
                return "el stub debe utilizar Mockito sobre una dependencia declarada."
            args = argumentos(llamada)
            if len(args) != 1 or args[0].type != "method_invocation":
                return "el stub de Mockito no apunta a un método de dependencia."
            objeto = args[0].child_by_field_name("object")
            if objeto is None or not any(
                resolver(objeto, alias).start_byte in usados for alias in aliases
            ):
                return "no se permite sustituir el método probado mediante un stub."
    return None
