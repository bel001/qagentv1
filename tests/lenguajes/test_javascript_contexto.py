"""Contexto documental optativo: procedencia, oráculo y límites sin ejecutar fuentes."""

import copy
from pathlib import Path

import pytest

from qagent import contracts
from qagent.agents.generator import GeneratorAgent
from qagent.agents.planner import PlannerAgent
from qagent.lenguajes import JavaScriptAdapter, TypeScriptAdapter
from qagent.lenguajes.javascript_contexto import MAX_BYTES, _leer, reconstruir_contexto
from qagent.llm import TokenTracker
from qagent.llm.fake import FakeLLMClient

FUENTE = """/**
 * @example nthFibonacci(4) => 3 | nthFibonacci(6) => 8
 */
function auxiliar(n: number): number { return n; }
export function nthFibonacci(n: number): number {
  return n < 3 ? 1 : nthFibonacci(n - 1) + nthFibonacci(n - 2);
}
"""
CASOS = [
    {"id": "cuarto", "entrada": [4], "valor_esperado": 3, "origen": "docstring"},
    {"id": "sexto", "entrada": [6], "valor_esperado": 8, "origen": "docstring"},
]


def preparar(raiz: Path, fuente: str = FUENTE, archivo: str = "maths/fibonacci.ts"):
    ruta = raiz / archivo
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text(fuente, encoding="utf-8")
    adaptador = TypeScriptAdapter() if archivo.endswith(".ts") else JavaScriptAdapter()
    [modulo] = adaptador.analizar(raiz)["modulos"]
    [completo] = adaptador.completar_contexto(raiz, [modulo])
    return adaptador, modulo, completo


def planificar(adaptador, modulo):
    tracker = TokenTracker()
    planner = PlannerAgent(
        FakeLLMClient(
            grabaciones={f"{Path(modulo['ruta']).name}::nthFibonacci": CASOS}
        ),
        tracker,
        es_simulado=True,
        adaptador=adaptador,
    )
    return planner, planner.planificar(modulo)


def test_recupera_jsdoc_desplazado_conserva_cita_linea_y_no_modifica_fuentes(tmp_path):
    adaptador, original, completo = preparar(tmp_path)
    assert "contexto_recuperado" not in original["funciones"][0]
    funcion = completo["funciones"][0]
    contexto = funcion["contexto_recuperado"]
    assert contexto["estado"] == "recuperado"
    assert contexto["archivos_revisados"] == ["maths/fibonacci.ts"]
    assert {f["linea_inicio"] for f in contexto["fuentes"]} == {2}
    assert {f["fragmento"] for f in contexto["fuentes"]} == {
        "nthFibonacci(4) => 3 | nthFibonacci(6) => 8"
    }
    assert (tmp_path / "maths/fibonacci.ts").read_text(encoding="utf-8") == FUENTE
    _, [contrato] = planificar(adaptador, completo)
    contracts.validar_versionado(contracts.FAMILIA_PLANNER, contrato)
    assert contrato["contexto_recuperado"] == contexto
    assert [c["valor_esperado"] for c in contrato["casos"]] == [3, 8]
    from qagent.lenguajes.javascript_oraculo import oraculo_del_caso

    for caso in contrato["casos"]:
        oraculo, motivo = oraculo_del_caso(
            "typescript", contrato["modulo"], funcion, caso
        )
        assert motivo is None
        assert oraculo["evidencia"]["ubicacion"]["archivo"] == "maths/fibonacci.ts"


def test_readme_identifica_modulo_y_se_revalida_antes_de_ejecutar(tmp_path):
    (tmp_path / "README.md").write_text(
        "Contrato de `maths/fibonacci.ts`\n```ts\nnthFibonacci(4) = 3\n```\n",
        encoding="utf-8",
    )
    fuente = "export function nthFibonacci(n: number): number { return 999; }"
    adaptador, _, completo = preparar(tmp_path, fuente)
    _, [contrato] = planificar(adaptador, completo)
    assert (
        contrato["casos"][0]["valor_esperado"] == 3
    )  # nunca el 999 de la implementación
    from qagent.lenguajes.javascript_oraculo import oraculo_del_caso

    oraculo, motivo = oraculo_del_caso(
        "typescript", contrato["modulo"], completo["funciones"][0], contrato["casos"][0]
    )
    assert motivo is None
    assert oraculo["evidencia"]["fuente"] == "contrato_explicito"
    generado = GeneratorAgent(
        FakeLLMClient(grabaciones={}),
        TokenTracker(),
        es_simulado=True,
        ruta_proyecto=tmp_path,
    ).generar(contrato, 1, None)
    assert adaptador.validar_oraculo(contrato, generado["codigo"], tmp_path) is None
    (tmp_path / "README.md").write_text("Cambió la documentación", encoding="utf-8")
    assert "Cambió una fuente" in adaptador.validar_oraculo(
        contrato, generado["codigo"], tmp_path
    )


@pytest.mark.parametrize("extension", ["ts", "js"])
def test_no_infiere_implementacion_tests_ni_ejemplos_de_otro_modulo(
    tmp_path, extension
):
    (tmp_path / "README.md").write_text(
        "Contrato de `otro/fibonacci.ts`\n```ts\nnthFibonacci(4) = 3\n```",
        encoding="utf-8",
    )
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests/fib.test.ts").write_text(
        "expect(nthFibonacci(4)).toBe(3)", encoding="utf-8"
    )
    tipo = ": number" if extension == "ts" else ""
    adaptador, _, completo = preparar(
        tmp_path,
        f"export function nthFibonacci(n{tipo}){tipo} {{ return 3; }}",
        f"maths/fibonacci.{extension}",
    )
    contexto = completo["funciones"][0]["contexto_recuperado"]
    assert contexto["estado"] == "insuficiente"
    assert contexto["fuentes"] == []

    class SinLlamadas:
        def completar(self, *args, **kwargs):
            pytest.fail("No debe consumir tokens si no hay evidencia")

    planner = PlannerAgent(SinLlamadas(), TokenTracker(), adaptador=adaptador)
    assert planner.planificar(completo) == []
    assert "nthFibonacci" in planner.omitidas


def test_contradicciones_no_se_resuelven_eligiendo_el_resultado_que_pasa(tmp_path):
    (tmp_path / "README.md").write_text(
        "maths/fibonacci.ts\n```ts\nnthFibonacci(4) = 999\nnthFibonacci(6) = 999\n```",
        encoding="utf-8",
    )
    adaptador, _, completo = preparar(tmp_path)
    assert completo["funciones"][0]["contexto_recuperado"]["estado"] == "contradictorio"
    planner, contratos = planificar(adaptador, completo)
    assert contratos == []
    assert "nthFibonacci" in planner.omitidas


def test_generador_se_omite_con_motivo_sin_consumir_tokens(tmp_path):
    adaptador, _, completo = preparar(
        tmp_path, "export function* primeGenerator() { while(true) yield 2; }"
    )
    funcion = completo["funciones"][0]
    assert funcion["es_generador"] is True
    assert funcion["contexto_recuperado"]["estado"] == "no_soportado"
    planner, contratos = planificar(adaptador, completo)
    assert contratos == []
    assert "cuántos elementos" in planner.omitidas["primeGenerator"]


def test_manipular_procedencia_o_casos_no_permite_ejecutar(tmp_path):
    adaptador, original, completo = preparar(tmp_path)
    _, [contrato] = planificar(adaptador, completo)
    alterado = copy.deepcopy(contrato)
    alterado["contexto_recuperado"]["fuentes"][0]["fragmento"] = "nthFibonacci(4) = 999"
    with pytest.raises(ValueError, match="no coincide"):
        reconstruir_contexto(tmp_path, alterado, original["funciones"][0])
    alterado = copy.deepcopy(contrato)
    alterado["casos"][0]["valor_esperado"] = 999
    assert "no coincide" in adaptador.validar_oraculo(alterado, "", tmp_path)
    assert not adaptador.contexto_spec_vigente(contrato, original)
    assert adaptador.contexto_spec_vigente(contrato, completo)
    (tmp_path / "maths/fibonacci.ts").write_text(
        FUENTE + "\n// cambio", encoding="utf-8"
    )
    [nuevo] = adaptador.completar_contexto(
        tmp_path, adaptador.analizar(tmp_path)["modulos"]
    )
    assert not adaptador.contexto_spec_vigente(contrato, nuevo)


def test_limites_de_lectura_no_permiten_archivos_fuera_del_proyecto(tmp_path):
    raiz = tmp_path / "proyecto"
    raiz.mkdir()
    (tmp_path / "afuera.md").write_text("dato", encoding="utf-8")
    (raiz / "grande.md").write_text("x" * (MAX_BYTES + 1), encoding="utf-8")
    assert _leer(raiz, "../afuera.md") is None
    assert _leer(raiz, "grande.md") is None


def test_un_indice_no_atribuye_ejemplos_de_otra_seccion_al_modulo(tmp_path):
    (tmp_path / "README.md").write_text(
        "# Índice\n[Algoritmo](maths/fibonacci.ts)\n"
        "# Otro algoritmo\n```ts\nnthFibonacci(4) = 999\n```\n",
        encoding="utf-8",
    )
    adaptador, _, completo = preparar(tmp_path)
    _, [contrato] = planificar(adaptador, completo)
    assert [c["valor_esperado"] for c in contrato["casos"]] == [3, 8]
    assert {
        f["archivo"] for f in completo["funciones"][0]["contexto_recuperado"]["fuentes"]
    } == {"maths/fibonacci.ts"}


def test_schema_rechaza_procedencia_incompleta_y_otro_lenguaje(tmp_path):
    adaptador, _, completo = preparar(tmp_path)
    _, [contrato] = planificar(adaptador, completo)
    for campo, valor in [("huella", "invalida"), ("linea_inicio", 0)]:
        alterado = copy.deepcopy(contrato)
        alterado["contexto_recuperado"]["fuentes"][0][campo] = valor
        with pytest.raises(contracts.ContratoInvalido):
            contracts.validar_versionado(contracts.FAMILIA_PLANNER, alterado)
    alterado = copy.deepcopy(contrato)
    alterado.update(lenguaje="python", framework_pruebas="pytest")
    with pytest.raises(contracts.ContratoInvalido):
        contracts.validar_versionado(contracts.FAMILIA_PLANNER, alterado)
