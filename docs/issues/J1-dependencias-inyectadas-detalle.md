# J1 — Dependencias inyectadas: diseño requerido

## Opción (a): contrato con stubs verificables

El contrato del Planner debe poder expresar:
```json
"dependencias": [
  {"nombre": "repo", "metodo": "findById", "entrada": [1], "salida": {"id": 1, "nombre": "test"}}
]
```

El oráculo valida que el stub `when(repo.findById(1)).thenReturn(...)` use exactamente esos valores.

## Opción (b): exclusión en Vista previa

Marcar en el análisis Java los métodos cuya clase tiene constructor con parámetros no primitivos (servicios inyectados) y excluirlos de la Vista previa con un mensaje explicativo.

## Implementación sugerida para (b)

1. En `java.py`, añadir campo `dependencias_inyectadas: bool` a cada función, calculado a partir de los constructores de su clase.
2. En `JavaAdapter.objetivos()`, filtrar los que tengan `dependencias_inyectadas == True`.
3. En el frontend, mostrar un badge «usa dependencias inyectadas» y deshabilitar la casilla.

## Archivos afectados

- `src/qagent/lenguajes/java.py`
- `src/qagent/lenguajes/java_oraculo.py`
- `src/qagent/frontend/componentes/vista-previa/vista-previa.js`
- `src/qagent/contracts/planner_contract.v3.schema.json`

## Criterios de aceptación

- Un método con dependencias inyectadas se excluye de la Vista previa o se prueba con stubs verificables.
- Los tests de Java siguen pasando.
- La auditoría E1/E2/E6 dejan de ser «sin veredicto».
