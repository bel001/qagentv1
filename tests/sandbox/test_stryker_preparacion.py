"""Pruebas de preparación de la copia del sandbox para Stryker (#179).

Verifica la detección de configuraciones propias de Stryker, la copia y ajuste
de rutas de las pruebas aprobadas y la escritura de `.qagent-stryker.json`.
"""

import json
from pathlib import Path

import pytest

from qagent.sandbox.stryker_preparacion import (
    CARPETA_PRUEBAS_STRYKER,
    CONFIGURACIONES_PROPIAS,
    ConfiguracionStrykerPropia,
    detectar_configuracion_propia,
    escribir_config_stryker,
    extraer_rangos_funciones,
    preparar_pruebas_stryker,
    preparar_stryker,
)

FUENTE_TS = """export function calcular(a: number, b: number): number {
  if (a > 0) {
    return a + b;
  }
  return b;
}

export function otra(x: string): string {
  return x.trim();
}
"""


def test_config_reservada_no_sobrescribe_archivos_del_proyecto(tmp_path: Path) -> None:
    archivo = tmp_path / ".qagent-stryker.json"
    archivo.write_text("original", encoding="utf-8")
    with pytest.raises(ValueError, match="reservada"):
        escribir_config_stryker(tmp_path, "calc.ts", {"calcular": (1, 3)})
    assert archivo.read_text(encoding="utf-8") == "original"


@pytest.mark.parametrize("destino", ["carpeta", "test", "config"])
def test_preparacion_no_escribe_a_traves_de_enlaces(
    tmp_path: Path, destino: str
) -> None:
    copia = tmp_path / "proyecto"
    copia.mkdir()
    pruebas = tmp_path / "pruebas"
    pruebas.mkdir()
    (pruebas / "calc.py").write_text("assert true", encoding="utf-8")
    externo = tmp_path / "externo"
    externo.mkdir()
    archivo = externo / "original.txt"
    archivo.write_text("original", encoding="utf-8")
    carpeta = copia / CARPETA_PRUEBAS_STRYKER
    try:
        if destino == "carpeta":
            carpeta.symlink_to(externo, target_is_directory=True)
        elif destino == "test":
            carpeta.mkdir()
            (carpeta / "calc.test.ts").symlink_to(archivo)
        else:
            (copia / ".qagent-stryker.json").symlink_to(archivo)
    except OSError:
        pytest.skip("El sistema no permite crear enlaces simbólicos")

    with pytest.raises(ValueError):
        if destino == "config":
            escribir_config_stryker(copia, "calc.ts", {"calcular": (1, 3)})
        else:
            preparar_pruebas_stryker(copia, pruebas, "calc.ts")
    assert archivo.read_text(encoding="utf-8") == "original"
    assert sorted(p.name for p in externo.iterdir()) == ["original.txt"]


@pytest.mark.parametrize("archivo_config", list(CONFIGURACIONES_PROPIAS))
def test_detecta_configuracion_propia_archivos(
    tmp_path: Path, archivo_config: str
) -> None:
    """Detecta archivos existentes como stryker.config.json o stryker.conf.js."""
    (tmp_path / archivo_config).write_text("{}", encoding="utf-8")
    with pytest.raises(ConfiguracionStrykerPropia):
        detectar_configuracion_propia(tmp_path)


def test_detecta_configuracion_propia_en_package_json(tmp_path: Path) -> None:
    """Detecta la clave 'stryker' dentro de package.json."""
    (tmp_path / "package.json").write_text(
        json.dumps({"name": "mi-proyecto", "stryker": {"testRunner": "jest"}}),
        encoding="utf-8",
    )
    with pytest.raises(ConfiguracionStrykerPropia):
        detectar_configuracion_propia(tmp_path)


def test_no_falla_si_no_hay_configuracion_propia(tmp_path: Path) -> None:
    """Un proyecto sin Stryker pasa la detección sin error."""
    (tmp_path / "package.json").write_text(
        json.dumps({"name": "mi-proyecto"}), encoding="utf-8"
    )
    detectar_configuracion_propia(tmp_path)


def test_extraer_rangos_funciones_con_treesitter(tmp_path: Path) -> None:
    """Extrae líneas de inicio y fin exactas para las funciones exportadas."""
    mod = tmp_path / "src/calc.ts"
    mod.parent.mkdir(parents=True)
    mod.write_text(FUENTE_TS, encoding="utf-8")

    rangos = extraer_rangos_funciones(tmp_path, "src/calc.ts", ["calcular", "otra"])
    assert rangos["calcular"] == (1, 6)
    assert rangos["otra"] == (8, 10)


def test_preparar_pruebas_ajusta_rutas_de_importacion(tmp_path: Path) -> None:
    """Las pruebas aprobadas se copian en _qagent_mutacion y ../proyecto/ pasa a ../."""
    copia = tmp_path / "proyecto"
    copia.mkdir()
    pruebas = tmp_path / "pruebas"
    pruebas.mkdir()

    codigo_test = """import { describe, it, expect } from 'vitest';
import { calcular } from '../proyecto/src/calc';

describe('calcular', () => {
  it('prueba', () => {
    expect(calcular(1, 2)).toBe(3);
  });
});
"""
    (pruebas / "test_calcular.py").write_text(codigo_test, encoding="utf-8")

    preparar_pruebas_stryker(copia, pruebas, "src/calc.ts")

    carpeta_dest = copia / CARPETA_PRUEBAS_STRYKER
    assert carpeta_dest.is_dir()
    archivos = list(carpeta_dest.iterdir())
    assert len(archivos) == 1
    assert archivos[0].name.endswith(".test.ts")

    contenido = archivos[0].read_text(encoding="utf-8")
    assert "from '../src/calc'" in contenido
    assert "../proyecto/" not in contenido


def test_escribir_config_stryker_genera_json_correcto(tmp_path: Path) -> None:
    """Escribe .qagent-stryker.json con vitest.dir en _qagent_mutacion y mutate acotado."""
    rangos = {"calcular": (1, 6)}
    config_path = escribir_config_stryker(tmp_path, "src/calc.ts", rangos)

    assert config_path.is_file()
    datos = json.loads(config_path.read_text(encoding="utf-8"))
    assert datos["testRunner"] == "vitest"
    assert datos["vitest"]["dir"] == CARPETA_PRUEBAS_STRYKER
    assert datos["mutate"] == ["src/calc.ts:1-6"]
    assert datos["concurrency"] == 1


def test_preparar_stryker_flujo_completo(tmp_path: Path) -> None:
    """preparar_stryker ejecuta todas las fases y devuelve los rangos."""
    copia = tmp_path / "copia"
    copia.mkdir()
    src = copia / "src"
    src.mkdir()
    (src / "calc.ts").write_text(FUENTE_TS, encoding="utf-8")

    pruebas = tmp_path / "pruebas"
    pruebas.mkdir()
    (pruebas / "test.ts").write_text("// test", encoding="utf-8")

    rangos = preparar_stryker(copia, pruebas, "src/calc.ts", ["calcular"])
    assert rangos == {"calcular": (1, 6)}
    assert (copia / ".qagent-stryker.json").is_file()
    assert (copia / CARPETA_PRUEBAS_STRYKER).is_dir()
