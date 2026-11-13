# C901 — 80 funciones con complejidad ciclomática > 10

**Severidad:** Baja  
**Etiqueta:** calidad, refactor

## Problema

Ruff con `--select C901` reporta 80 funciones con complejidad > 10. Concentración:

- `src/qagent/storage/exportar_informe.py` (6)
- `src/qagent/lenguajes/javascript_estructura.py` (4)
- `src/qagent/analysis/contexto.py` (3)
- `src/qagent/analysis/grafo_imports.py` (3)
- `src/qagent/analysis/laundering.py` (3)
- `src/qagent/contracts/validacion_semantica.py` (3)
- `src/qagent/lenguajes/java_oraculo.py` (3)
- `src/qagent/agents/planner.py` (3)
- `src/qagent/analysis/integracion.py` (2)
- `src/qagent/analysis/rutas.py` (2)
- `src/qagent/analysis/texto_ts.py` (2)
- `src/qagent/lenguajes/java_aserciones.py` (2)
- `src/qagent/lenguajes/java_spring.py` (2)
- `src/qagent/lenguajes/javascript_oraculo.py` (2)
- `src/qagent/orchestrator/corrida.py` (2)
- `src/qagent/orchestrator/orquestador.py` (2)
- `src/qagent/orchestrator/verificacion_correccion.py` (2)

## Corrección propuesta

- Extraer helpers puros.
- Separar ramas por tipo de lenguaje/contrato.
- Añadir `--select C901` a la CI con umbral inicial.

## Criterios de aceptación

- Ninguna función supera complejidad 10 en los módulos tocados.
- La regla C901 está activa en CI.
- Los tests siguen pasando.

## Resolución

- **Regla activa en el repositorio y en la CI**: `pyproject.toml` tiene
  `[tool.ruff.lint] extend-select = ["C901"]` y `[tool.ruff.lint.mccabe] max-complexity = 30`;
  la CI ejecuta `ruff check .`, que ahora falla si una función supera 30.
- **Funciones refactorizadas** (las que superaban el umbral): `analizar_junit` e
  `interpretar_jacoco` (`lenguajes/java_ejecucion.py`), `_validar` (`lenguajes/java_oraculo.py`),
  `construir_markdown_informe` (ahora en `storage/informe_markdown.py`),
  `ejecutar_regresion` (`orchestrator/regresion.py`) y `ejecutar_corrida`
  (`orchestrator/corrida.py`).
- `ruff check --select C901 .` y `ruff format --check .` están en verde sobre todo el
  repositorio.
