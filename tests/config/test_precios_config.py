"""Verifica que los modelos y precios de config.toml coinciden con el catálogo (M4)."""

from pathlib import Path

import tomllib

RAIZ = Path(__file__).resolve().parents[2]
CONFIG = RAIZ / "src" / "qagent" / "config" / "config.toml"
PROVEEDORES = RAIZ / "src" / "qagent" / "llm" / "proveedores.toml"


def test_precios_config_coinciden_con_catalogo():
    cfg = tomllib.loads(CONFIG.read_text(encoding="utf-8"))
    prov = tomllib.loads(PROVEEDORES.read_text(encoding="utf-8"))
    proveedores = prov["proveedores"]

    for agente, datos in cfg["agentes"].items():
        if not isinstance(datos, dict) or "modelo" not in datos:
            continue
        proveedor = datos["proveedor"]
        modelo_id = datos["modelo"]
        catalogo = proveedores[proveedor]["modelos"]
        entrada_cat = next(
            (m.get("entrada") for m in catalogo if m["id"] == modelo_id), None
        )
        salida_cat = next(
            (m.get("salida") for m in catalogo if m["id"] == modelo_id), None
        )
        assert entrada_cat is not None, (
            f"{agente}: {modelo_id} sin precio en el catálogo"
        )
        assert salida_cat is not None, (
            f"{agente}: {modelo_id} sin precio en el catálogo"
        )
        assert abs(datos["precio_entrada_usd_m"] - entrada_cat) < 1e-9
        assert abs(datos["precio_salida_usd_m"] - salida_cat) < 1e-9
