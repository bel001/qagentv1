# J5 — El sandbox fuerza JDK 25 y rompe Lombok anterior a 1.18.40

**Severidad:** Alta  
**Etiqueta:** java, sandbox, docker

## Problema

`Dockerfile.java` usa `eclipse-temurin:25`; el proyecto declara `release 17`, pero el compilador sigue siendo el de JDK 25. Lombok < 1.18.40 falla al compilar (C05, C06), y Lombok está en casi todos los proyectos Spring.

`docs/java/README.md:42` dice que se validó con JDK 21: documentación desactualizada.

## Corrección propuesta

- Elegir el JDK según `maven.compiler.release`/`java.version` (imágenes 17/21/25, como ya se hace con Python en ADR-013), o
- Detectar Lombok antiguo y avisar antes de correr.

## Archivos afectados

- `src/qagent/sandbox/Dockerfile.java`
- `src/qagent/lenguajes/java_ejecucion.py`

## Criterios de aceptación

- Un proyecto con `release 17` y Lombok 1.18.30 compila y ejecuta.
- La documentación refleja el JDK real del sandbox.
- Los tests Docker de Java siguen pasando.
