"""Opción desde la corrida hasta los informes exportados, con IA y Docker simulados."""

import copy
import json
from pathlib import Path

import pytest

from qagent import contracts
from qagent.almacenamiento import AlmacenProyecto
from qagent.config import cargar_configuracion
from qagent.config.carga import RUTA_CONFIG
from qagent.llm.fake import FakeLLMClient
from qagent.orchestrator.corrida import ejecutar_corrida
from qagent.sandbox import ResultadoSandbox
from qagent.storage.exportar_informe import exportar_informe, extraer_texto_pdf
from tests.lenguajes.test_javascript_contexto import CASOS, FUENTE


@pytest.mark.parametrize("activar", [False, True])
def test_opcion_es_voluntaria_y_procedencia_llega_a_todos_los_informes(
    tmp_path, monkeypatch, activar
):
    (tmp_path / "maths").mkdir()
    (tmp_path / "package.json").write_text(
        '{"name":"contexto","type":"module"}', encoding="utf-8"
    )
    (tmp_path / "maths/fibonacci.ts").write_text(FUENTE, encoding="utf-8")
    almacen = AlmacenProyecto(tmp_path)
    almacen.inicializar()
    cliente = FakeLLMClient(grabaciones={"fibonacci.ts::nthFibonacci": CASOS})
    monkeypatch.setattr(
        "qagent.orchestrator.corrida.crear_cliente", lambda *a, **kw: cliente
    )
    ejecutadas = []

    def ejecutar(imagen, proyecto, tests, modulo, **kw):
        ejecutadas.append(modulo)
        return ResultadoSandbox(
            exit_code=0, stdout="2 passed", stderr="", duracion_s=0.1
        )

    config = cargar_configuracion(RUTA_CONFIG, "no-existe.env", simulado=True).config
    resumen = ejecutar_corrida(
        tmp_path,
        "deep",
        config,
        None,
        simulado=True,
        preparar_imagen=lambda *a, **kw: "imagen-simulada",
        ejecutor=ejecutar,
        completar_contexto=activar,
    )
    assert resumen.estado == "fin", resumen.motivo
    assert resumen.aceptadas == int(activar)
    assert bool(ejecutadas) is activar
    detalle = json.loads(
        (Path(resumen.carpeta) / "detalle.json").read_text(encoding="utf-8")
    )
    contracts.validar(contracts.DETALLE, detalle)
    assert bool(detalle.get("contexto_automatico")) is activar
    if not activar:
        return
    [procedencia] = detalle["contexto_automatico"]
    assert procedencia["objetivo"] == "nthFibonacci"
    assert procedencia["contexto"]["fuentes"][0]["archivo"] == "maths/fibonacci.ts"
    alterado = copy.deepcopy(detalle)
    alterado["contexto_automatico"][0]["contexto"]["fuentes"][0]["linea_inicio"] = 0
    with pytest.raises(contracts.ContratoInvalido):
        contracts.validar(contracts.DETALLE, alterado)
    for formato in ("json", "md", "html", "pdf"):
        resultado = exportar_informe(tmp_path, resumen.run_id, formato)
        ruta = Path(resultado["ruta"])
        texto = (
            extraer_texto_pdf(ruta)
            if formato == "pdf"
            else ruta.read_text(encoding="utf-8")
        )
        assert "maths/fibonacci.ts" in texto
        assert "nthFibonacci(4)" in texto
        if formato == "json":
            assert (
                json.loads(texto)["contexto_automatico"]
                == detalle["contexto_automatico"]
            )
