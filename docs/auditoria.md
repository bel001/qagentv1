# Auditoría completa — QAgent

**Fecha:** 2026-11-11  
**Entorno de auditoría:** Python 3.13.17, Windows, `QAGENT_FAKE_LLM=1`, sin Docker real.  
**Resultado de la suite:** `3978 passed, 70 skipped` en ~8,7 min. Ruff (`check` + `format --check`) sin hallazgos en `src/`, `tests/`, `scripts/`, `test.py`.

> Este documento es un inventario de mejoras detectadas. No modifica código: cada punto se puede convertir en issue/PR independiente.

---

## 1. Resumen ejecutivo

- El proyecto está **funcional y bien estructurado**: separación por capas, contratos JSON versionados, adaptadores por lenguaje, sandbox endurecido y una suite grande que pasa en verde.
- Las **reglas del equipo** (sin ejecutar código del usuario, agentes no se llaman entre sí, claves solo en `~/.qagent/.env`, frontend sin bundler) se respetan en el código revisado.
- Las principales deudas son de **mantenibilidad** (80 funciones con complejidad ciclomática > 10, varios módulos > 1000 líneas) y de **rendimiento de la suite** (8,7 min sin paralelismo).
- No se detectaron vulnerabilidades obvias (sin `shell=True`, sin `eval`/`exec`, red desactivada en Docker, `cap_drop=ALL`, `read_only=True`, `network_mode=none`).
- La configuración de ruff es conservadora: pasa, pero oculta deuda de simplicidad (`B`, `SIM`) y de complejidad (`C901`). Activar esas reglas daría una lista accionable.

---

## 2. Estándares y calidad de código

### 2.1 Lo que ya cumple
- `ruff check` y `ruff format --check` en verde para `src`, `tests`, `scripts`, `test.py`.
- Convenciones de nombre (`qagent`/QAgent), type hints con sintaxis 3.10+ (`|`, `list[...]`).
- Docstrings en español, una función por responsabilidad en la mayoría de módulos.
- `pip check` sin conflictos de dependencias.
- Marcadores `docker`/`red` bien separados; la IA simulada evita llamadas reales en tests.

### 2.2 Hallazgos y mejoras
1. **Complejidad ciclomática alta (C901): 80 funciones > 10.**  
   Concentración en `src/qagent/storage/exportar_informe.py` (6), `lenguajes/javascript_estructura.py` (4), `analysis/contexto.py`, `analysis/grafo_imports.py`, `analysis/laundering.py`, `contracts/validacion_semantica.py`, `lenguajes/java_oraculo.py` (3 cada uno) y `agents/planner.py`, `analysis/integracion.py`, `analysis/rutas.py`, `analysis/texto_ts.py`, `lenguajes/java_aserciones.py`, `lenguajes/java_spring.py`, `lenguajes/javascript_oraculo.py`, `orchestrator/corrida.py`, `orchestrator/orquestador.py`, `orchestrator/verificacion_correccion.py` (2 cada uno).  
   **Acción:** extraer helpers puros, separar ramas por tipo de lenguaje/contrato, añadir `--select C901` a la CI.

2. **Reglas de Bugbear (B) en `src`: 13 hallazgos.**  
   - 11 `B905`: `zip()` sin `strict=` (riesgo de truncamiento silencioso).  
   - 2 `B007`: variables de bucle no usadas.  
   **Acción:** revisar cada `zip` y decidir `strict=True/False` explícito; renombrar variables no usadas con `_`.

3. **Simplificaciones (SIM): 5 `SIM105`** (`try/except/pass` que podrían ser `contextlib.suppress`).  
   Archivos: `almacenamiento/bloqueo.py`, `app/bitacora.py`, `llm/cliente.py`, `sandbox/ejecucion.py`, `storage/exportar_informe.py`.  
   **Acción:** aplicar `contextlib.suppress` para legibilidad (cambio cosmético, bajo riesgo).

4. **Aserciones en código de producción (3).**  
   `config/roles.py` (2) y `storage/informe_pdf.py` (1) usan `assert`. Con `python -O` desaparecen y pueden ocultar invariantes.  
   **Acción:** convertir en `if ...: raise RuntimeError/ValueError` o mantener solo en tests.

5. **Type hints no obligatorios.**  
   Ruff no tiene activado `ANN`: 3639 avisos potenciales. El estándar del equipo exige anotaciones solo en funciones públicas.  
   **Acción (opcional):** activar `ANN` con `ignore = ["ANN101","ANN102"]` y corregir gradualmente empezando por `agents/` y `orchestrator/`.

6. **Módulos muy grandes (> 1000 líneas).**  
   `storage/exportar_informe.py` (2415), `app/desktop.py` (1415), `orchestrator/corrida.py` (1398), `orchestrator/orquestador.py` (1256), `almacenamiento/proyecto.py` (1201), `storage/corrida_demo.py` (1094).  
   **Acción:** dividir por responsabilidad (exportación MD/HTML/PDF, API de escritorio, ejecución de corrida, almacenamiento). Mejora testeabilidad y tiempos de import.

7. **Compatibilidad de versión de Python.**  
   `requires-python = ">=3.10"` y soporte declarado hasta 3.14. La CI usa 3.13.17. Python 3.15 no está soportado (tree-sitter no compila sin toolchain C++).  
   **Acción:** documentar en `README`/`docs/desarrollo.md` que 3.15 queda fuera hasta actualizar tree-sitter; o subir el rango cuando haya wheels.

8. **Frontend.**  
   Uso extensivo de `innerHTML` con `escHtml` (bien), pero varias interpolaciones en atributos `onclick` (`run_id`, etc.).  
   **Acción:** migrar esos `onclick` a `data-*` + delegación de eventos para evitar inyección si algún valor no pasa por `escHtml`; auditar cada punto de `innerHTML`.

---

## 3. Seguridad

### 3.1 Lo que ya cumple
- Claves solo en `~/.qagent/.env`; `config/auditoria.py` busca patrones de clave en el repo.
- Ejecución de código del usuario **solo en Docker**: `network_mode="none"`, `read_only=True`, `cap_drop=["ALL"]`, `pids_limit`, límites de CPU/memoria, timeout por ejecución.
- Subprocess sin `shell=True`; `explorer.exe`/`open` se invocan con lista de argumentos.
- Sin `eval`/`exec`/`pickle` en `src`.
- Pywebview carga la UI como `file://` (evita servidor HTTP interno).
- Secretos saneados en informes (`sanitizar_secretos`).

### 3.2 Mejoras recomendadas
1. **Auditar `DesktopAPI` (js_api).**  
   Verificar que ningún método expuesto permita leer/escribir rutas arbitrarias o borrar archivos fuera de `.qagent/`. Añadir tests de contrato para la superficie expuesta.

2. **Validación de URL/rama en clonador.**  
   Ya valida formato; añadir límite de longitud y rechazo de caracteres de control/inyección en `rama` (defensa en profundidad).

3. **Path traversal en exportación.**  
   Las rutas de exportación (`exportar_informe.py`) deberían validarse contra una carpeta base permitida para evitar escritura fuera del proyecto.

4. **CSP para el frontend.**  
   Añadir una Content-Security-Policy en `index.html` (aunque sea `file://`) para reducir riesgo de XSS si se inyecta HTML no saneado.

5. **Dependencias.**  
   Ejecutar `pip-audit` (no instalado en este entorno) y fijar versiones vulnerables; añadirlo a CI.

---

## 4. Rendimiento y eficiencia

### 4.1 Suite de tests
- 3978 tests en ~8,7 min (≈0,13 s/test) sin paralelismo.  
  **Acción:** evaluar `pytest-xdist` (`-n auto`) para desarrollo local; medir ganancia real (algunos tests comparten estado/Docker).

### 4.2 Análisis estático
- `analizar()` re-parsea todo el proyecto en cada corrida; no hay caché por mtime/hash.  
  **Acción:** cachear resultados por `(ruta, mtime, tamaño)` en memoria o en `.qagent/cache/` (invalidar al cambiar archivos). Impacto alto en proyectos grandes.

### 4.3 Reportes e informes
- `exportar_informe.py` (2415 líneas) construye Markdown/HTML/PDF completos en memoria.  
  **Acción:** generar por streaming/chunks y medir pico de memoria; separar renderizadores.

### 4.4 Frontend
- Reconstrucción completa de listas con `innerHTML` en cada filtro (historial, vista previa).  
  **Acción:** diff mínimo o virtualización para listas > 200 elementos; medir con profiler.

### 4.5 Docker/espacio en disco
- Ya existe gestión de imágenes derivadas y límite de espacio libre.  
  **Acción:** añadir métrica de tiempo de build por imagen y caché de dependencias por lockfile (npm/pnpm/yarn) para evitar reinstalaciones.

### 4.6 Importaciones
- Imports pesados (tree-sitter, pywebview) se cargan al inicio.  
  **Acción:** lazy import en rutas CLI/no-GUI (ej. `qagent.analysis` standalone) para acelerar `--version` y scripts.

---

## 5. Mantenibilidad y arquitectura

1. **Dividir módulos grandes** (ver 2.2.6) manteniendo la interfaz pública.
2. **Reducir complejidad** de 80 funciones (ver 2.2.1) con extracción y tablas de despacho.
3. **Cobertura de tests:** no hay umbral de cobertura configurado.  
   **Acción:** añadir `pytest-cov` con umbral inicial 70 % y ratchet en CI.
4. **Documentación de performance:** los tiempos esperados (corrida, build Docker) no están en `docs/desarrollo.md`.  
   **Acción:** añadir sección "Presupuestos de rendimiento" con métricas y cómo medirlas.
5. **Observabilidad:** logging estructurado (JSON) opcional para depurar corridas largas; hoy es texto plano.

---

## 6. Lista priorizada de mejoras

### P0 (bloqueantes / riesgo)
- Auditar superficie `js_api` de pywebview (seguridad).
- Validar rutas de exportación contra carpeta base (path traversal).
- Documentar que Python 3.15 no está soportado hasta actualizar tree-sitter.

### P1 (alto impacto, bajo-medio esfuerzo)
- Activar reglas `B` y `SIM` en ruff y corregir los 18 hallazgos en `src`.
- Refactorizar las 6 funciones más complejas de `exportar_informe.py` y `planner.py`.
- Añadir caché de análisis por mtime.
- Evaluar `pytest-xdist` y fijar un umbral de cobertura.

### P2 (mejora continua)
- Reducir complejidad de las 80 funciones C901 restantes.
- Migrar `onclick` inline a delegación en frontend.
- Lazy imports para CLI/scripts.
- Streaming de informes grandes.
- `pip-audit` en CI.

---

## 7. Comandos de verificación usados

```bash
python -m ruff check .
python -m ruff format --check .
python -m ruff check --select C901 --target-version py310 .
python -m ruff check --select B --target-version py310 src
python -m ruff check --select SIM --target-version py310 src
python -m ruff check --select UP --target-version py310 .
python -m pip check
# Suite completa (IA simulada):
QAGENT_FAKE_LLM=1 python -m pytest -q   # 3978 passed, 70 skipped
```

---

## 8. Conclusión

QAgent cumple con los estándares del equipo y con buenas prácticas de seguridad en el sandbox. Las mejoras más valiosas son de **mantenibilidad** (complejidad y tamaño de módulos) y de **rendimiento** (caché de análisis y paralelismo de tests), no de corrección funcional. Se recomienda abrir issues por cada punto P0/P1 y abordarlos en PRs pequeños.
