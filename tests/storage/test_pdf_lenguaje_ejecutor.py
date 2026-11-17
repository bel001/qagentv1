"""El PDF nombra el lenguaje y el ejecutor de la corrida, no «Python» y «pytest» fijos."""

from __future__ import annotations

from qagent.storage.informe_pdf import lenguajes_de_la_corrida, nombre_de_lenguaje


def test_nombre_visible_de_cada_lenguaje() -> None:
    assert nombre_de_lenguaje("python") == "Python"
    assert nombre_de_lenguaje("java") == "Java"
    assert nombre_de_lenguaje("typescript") == "TypeScript"
    assert nombre_de_lenguaje("javascript") == "JavaScript"


def test_un_lenguaje_sin_adaptador_no_rompe_el_informe() -> None:
    assert nombre_de_lenguaje("kotlin") == "Kotlin"


def test_una_corrida_java_no_dice_python() -> None:
    funciones = [{"lenguaje": "java"}, {"lenguaje": "java"}]
    assert lenguajes_de_la_corrida(funciones) == "Java"


def test_resultados_anteriores_sin_lenguaje_son_python() -> None:
    assert lenguajes_de_la_corrida([{"nombre": "f"}]) == "Python"
    assert lenguajes_de_la_corrida([]) == "Python"


def test_varios_lenguajes_se_nombran_en_orden_de_aparicion() -> None:
    funciones = [{"lenguaje": "typescript"}, {"lenguaje": "python"}]
    assert lenguajes_de_la_corrida(funciones) == "TypeScript y Python"
