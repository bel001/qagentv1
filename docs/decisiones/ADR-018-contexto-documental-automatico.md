# ADR-018: Recuperar contexto documental automáticamente

- **Estado:** Aceptado para esta implementación local (2026-11-17)
- **Solicitud:** opción explícita para completar contexto y citar los archivos en el informe.
- **Relacionados:** ADR-007, ADR-008, ADR-009 y contrato `oracle.v1`.

## Decisión

Se añade «Completar contexto automáticamente» al inicio de las pruebas. En esta
primera versión está disponible para funciones JavaScript/TypeScript. Se leen con
tree-sitter los comentarios documentales del módulo seleccionado y, de forma
acotada, README y archivos Markdown de `docs/` que identifiquen ese módulo.

Se recuperan solo llamadas con entradas y resultados explícitos: `f(2) = 4`,
`f(2) => 4` y `f(2) // => 4`. Se conservan archivo, líneas, fragmento original y
huella. Los valores se validan contra `oracle.v1`; una contradicción no se resuelve
eligiendo el ejemplo que haga pasar la prueba. No se infieren valores leyendo la
implementación, no se usan aserciones existentes como contrato y no se modifica
la documentación del usuario. La inferencia de ADR-016 sigue siendo solo Python.

El contexto recuperado viaja como metadata opcional del contrato v3. El Reviewer
reconstruye las evidencias leyendo las fuentes y exige que conserven su huella;
el contenido del contrato por sí solo no acredita un valor. Las specs con fuentes
modificadas se vuelven a planificar. Un generador/iterador no se convierte
arbitrariamente en una lista: se explica que necesita una prueba de consumo acotado.

La búsqueda local no usa un LLM ni consume tokens. La generación posterior sigue
utilizando los agentes configurados y los límites existentes. El diálogo permite
cancelar, comenzar con la selección o activar la recuperación. El informe muestra
qué fuentes se utilizaron y qué objetivos siguen sin evidencia suficiente.

## Consecuencias

Se recuperan contratos documentados que el formato o la ubicación del comentario
ocultaban al analizador. No se garantiza que los tests pasen: un fallo sigue siendo
un hallazgo. No se amplía el alcance a servicios reales, a inferencia de resultados
JS/TS desde la implementación ni a ejecución de código fuera del sandbox.
