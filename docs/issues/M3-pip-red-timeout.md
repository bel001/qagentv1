# M3 — Las dependencias de Python se instalan ejecutando código con red

**Severidad:** Media  
**Etiqueta:** python, sandbox, seguridad

## Problema

`src/qagent/sandbox/imagen.py:66-67`: `pip install -r requirements.txt` en la construcción de la imagen, **con red**. Un `sdist` o una URL `git+https://` ejecuta `setup.py` arbitrario con acceso a internet. Para JS se decidió lo contrario (ADR-015: `--ignore-scripts`).

Además la construcción **no tiene tiempo máximo** (`imagen.py:713`, `:738`).

## Corrección propuesta

- `--only-binary=:all:` por defecto (con opción explícita para permitir sdists).
- Rechazar opciones de `requirements.txt` como `--index-url`/`--extra-index-url`/`--trusted-host`.
- Tiempo máximo de construcción.

Documentarlo en un ADR o en ADR-013.

## Archivos afectados

- `src/qagent/sandbox/imagen.py`

## Criterios de aceptación

- Un `requirements.txt` con `git+https://` se rechaza o se instala sin ejecutar código.
- La construcción se cancela si supera el tiempo máximo.
- Los tests de imagen siguen pasando.
