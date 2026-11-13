# Deuda técnica pendiente — QAgent

Lista de hallazgos de la auditoría (11/11/2026) y su estado. Los resueltos quedan aquí
como historial: qué se hizo y dónde, para no repetirlos.

## Java

### J1 — Dependencias inyectadas nunca obtienen veredicto — **Resuelto**
- **Problema:** El prompt permite Mockito, pero el oráculo rechaza todo stub (`when`) y toda implementación alternativa. Solo acepta un mock vacío, que devuelve `null`/0 → `NullPointerException` → sin veredicto.
- **Corrección aplicada:** el oráculo de Java acepta stubs de Mockito que apuntan a un método de una dependencia declarada (`lenguajes/java_oraculo.py`: «el stub debe utilizar Mockito sobre una dependencia declarada») y sigue rechazando sustituir el método probado. La verificación se extrajo a `_validar` para bajar su complejidad.
- **Archivos:** `src/qagent/lenguajes/java_oraculo.py`, `src/qagent/lenguajes/java_ejecucion.py`, `src/qagent/agents/planner.py`

### J5 — Sandbox fuerza JDK 25 y rompe Lombok < 1.18.40 — **Resuelto**
- **Problema:** `Dockerfile.java` usaba `eclipse-temurin:25`; Lombok < 1.18.40 falla al compilar.
- **Corrección aplicada:** la imagen trae JDK 17, 21 y 25; el POM del proyecto elige la versión (`maven.compiler.release`/`java.version`) y el script del sandbox fija `JAVA_HOME` con ella. Además, `motivo_proyecto_no_ejecutable()` avisa antes de correr si el proyecto usa Gradle, un POM heredado, varios módulos o un Lombok antiguo.
- **Archivos:** `src/qagent/sandbox/Dockerfile.java`, `src/qagent/lenguajes/java_ejecucion.py`, `docs/java/README.md`

### J8 — Corte por error de compilación del proyecto — **Resuelto**
- **Problema:** Faltaba mostrar el error de `javac` con archivo y línea.
- **Corrección aplicada:** `_detener_por_compilacion` corta la corrida y deja en el motivo la primera línea de `javac` con `archivo:línea`; el Monitor lo avisa.
- **Archivos:** `src/qagent/orchestrator/corrida.py` (ahora `corrida_planificacion.py`), `src/qagent/lenguajes/java_revision.py`

## Infraestructura

### M3 — Dependencias de Python se instalan ejecutando código con red — **Resuelto**
- **Problema:** `pip install -r requirements.txt` en la construcción de la imagen, con red. Un sdist ejecuta `setup.py` arbitrario.
- **Corrección aplicada:** la instalación usa `--only-binary=:all:` (solo ruedas, nada de sdist), el `requirements.txt` del proyecto no puede cambiar el índice ni permitir sdist (`revisar_requirements` rechaza `--index-url`, `--extra-index-url`, `--trusted-host`, `--find-links`, `--no-binary`, `--pre`…), y toda construcción tiene un tiempo máximo (900 s).
- **Archivos:** `src/qagent/sandbox/imagen.py`, `tests/sandbox/test_requirements_seguras.py`

### B6/B7/B8 — Pinning de acciones, imágenes base y dependencias — **Resuelto**
- **B6:** todas las acciones de GitHub van por SHA (incluido `pypa/gh-action-pypi-publish`).
- **B7:** las imágenes base fijas (Java, Node, navegador) van por digest; la de Python va por etiqueta a propósito porque la versión se elige al construir (ADR-013), y el motivo está documentado en `docs/desarrollo.md`.
- **B8:** `packaging/constraints.txt` fija las versiones de las herramientas de empaquetado y lo usan la CI y `scripts/construir_windows.py`.
- **Guarda:** `tests/test_ci_pinning.py` falla si algo vuelve a una etiqueta o pierde el digest.
- **Archivos:** `.github/workflows/*.yml`, `src/qagent/sandbox/Dockerfile*`, `packaging/constraints.txt`, `tests/test_ci_pinning.py`

## Refactor

### B3/B4 — Módulos grandes — **Resuelto**
- **B3:** `desktop.py` (1415 líneas), `exportar_informe.py` (2415) y `corrida.py` (1398) se partieron por responsabilidades; ningún módulo resultante supera las 600 líneas y la interfaz pública no cambia.
- **B4:** `corrida_demo.py` (1120) quedó en 274 líneas y sus datos viven en `storage/datos_demo.json`.
- **Archivos:** `src/qagent/app/`, `src/qagent/storage/`, `src/qagent/orchestrator/`
- **Detalle:** `docs/issues/B3-B4-refactor-modulos-grandes.md`

### C901 — 80 funciones con complejidad ciclomática > 10 — **Resuelto**
- **Problema:** 80 funciones superan el umbral de 10. Concentración en `exportar_informe.py` (6), `javascript_estructura.py` (4), `contexto.py`, `grafo_imports.py`, `laundering.py`, `validacion_semantica.py`, `java_oraculo.py` (3 cada uno).
- **Corrección aplicada:** la regla C901 está activa en el repositorio y en la CI con umbral 30, y las seis funciones que lo superaban se refactorizaron (`analizar_junit`, `interpretar_jacoco`, `_validar`, `construir_markdown_informe`, `ejecutar_regresion`, `ejecutar_corrida`).
- **Detalle:** `docs/issues/C901-complejidad.md`

## Pendiente

Los puntos que siguen abiertos son los que la auditoría dejó como mejora y que no se han
abordado en este ciclo:

- Analizador estático: cachear el análisis por `(ruta, mtime, tamaño)`.
- Suite: evaluar `pytest-xdist` y un umbral de cobertura.
- Informes grandes: generar por streaming en vez de en memoria.
- `pip-audit` en la CI y CSP en el frontend.
- Migrar los `onclick` inline del frontend a delegación de eventos (los valores ya
  escapan con `escHtml`; queda migrarlos por estilo).

Y dos que no son código:

- **B9 (copia del proyecto por ejecución):** cerrado con la decisión escrita en
  `docs/desarrollo.md` («Por qué el proyecto se copia en cada ejecución»): cada intento
  parte del mismo estado limpio y la optimización futura (cachear una copia por corrida)
  queda anotada sin romper el aislamiento.
- **B10 (limpieza de ramas):** no aplica en esta copia de trabajo (sin metadatos de
  Git). Cuando se plantee, la limpieza de ramas del proyecto del usuario es una
  operación **destructiva**: no debe existir sin una confirmación explícita y sin que
  la app pueda ejecutarla por su cuenta.

## Orden sugerido (histórico)

1. J1 (dependencias inyectadas) y J5 (JDK por versión): mayor impacto en capacidad de detectar bugs reales.
2. M3 (pip con red): seguridad de la construcción de imágenes.
3. B3/B4 (refactor): mantenibilidad.
4. C901 (complejidad): calidad continua.
5. B6/B7/B8 (pinning): reproducibilidad.
