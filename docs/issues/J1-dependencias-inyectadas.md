# J1 — Dependencias inyectadas nunca obtienen veredicto

**Severidad:** Crítica  
**Etiqueta:** java, oráculo, planner

## Problema

El prompt dice «Mockito se permite únicamente para objetos de dependencia que recibe el constructor» (`java_generacion.py`), pero el oráculo rechaza todo stub (`when`) y toda implementación alternativa (`java_oraculo.py:530-592`). Solo acepta un mock vacío.

Un mock vacío devuelve `null`/0, así que el método falla con `NullPointerException` y el clasificador lo trata como error técnico (J2).

Consecuencia: en la capa de servicios (Spring o no), que es lo que más se quiere probar, QAgent gasta Planner, hasta 3 intentos del Generator y sandbox, y termina siempre en «sin veredicto». Además, el contrato del Planner no tiene forma de expresar el comportamiento de una dependencia.

## Corrección propuesta

Decidir el diseño:
- (a) Que el contrato del Planner describa stubs verificables de dependencias (entradas → salidas declaradas en Javadoc o tipos) y que el oráculo los valide.
- (b) Excluir explícitamente de la Vista previa los métodos que usan dependencias inyectadas y explicarlo.

Hoy se ofrecen y fallan siempre.

## Archivos afectados

- `src/qagent/lenguajes/java_generacion.py`
- `src/qagent/lenguajes/java_oraculo.py`
- `src/qagent/agents/planner.py`

## Criterios de aceptación

- Un método que usa una dependencia inyectada obtiene un veredicto (bug o aceptado) o se excluye de la Vista previa con explicación.
- El oráculo no rechaza stubs verificables si se elige la opción (a).
- Los tests existentes de Java siguen pasando.
