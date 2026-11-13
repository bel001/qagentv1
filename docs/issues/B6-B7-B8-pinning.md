# B6/B7/B8 — Pinning de acciones, imágenes base y dependencias

**Severidad:** Baja  
**Etiqueta:** ci, reproducibilidad, seguridad

## Problema

- `.github/workflows/*.yml`: acciones por etiqueta (`@v4`, `@release/v1`) en lugar de SHA.
- `src/qagent/sandbox/Dockerfile*`: imágenes base por etiqueta sin digest.
- `pyproject.toml`: dependencias sin tope superior y sin archivo de bloqueo.

## Corrección propuesta

- Fijar acciones por SHA (Dependabot puede actualizarlas).
- Fijar imágenes base por digest o documentar la decisión.
- Archivo de restricciones para `construir_windows.py` y CI.

## Archivos afectados

- `.github/workflows/*.yml`
- `src/qagent/sandbox/Dockerfile*`
- `pyproject.toml`

## Criterios de aceptación

- Las acciones se referencian por SHA.
- Las imágenes base se referencian por digest o hay documentación justificando etiquetas.
- Existe un archivo de restricciones para el empaquetado.

## Resolución

**B6 — Acciones por SHA.** Todas las acciones de `.github/workflows/` van por SHA (con la
versión en un comentario al lado): `actions/checkout`, `actions/setup-python`,
`actions/upload-artifact`, `actions/download-artifact` y `pypa/gh-action-pypi-publish`
(`release/v1` → `7245906fb61fa33a13554f9d5fb856fe61758086`).

**B7 — Imágenes base por digest.** `Dockerfile.java`, `Dockerfile.node` y
`Dockerfile.navegador` fijan su imagen base por digest. La imagen de Python va por
etiqueta a propósito: la versión se elige al construir según la del proyecto (ADR-013),
así que no puede fijarse un único digest; el motivo y los digests están en
`docs/desarrollo.md` («Imágenes base del sandbox»).

**B8 — Restricciones del empaquetado.** `packaging/constraints.txt` fija las versiones
de `build`, `pyinstaller`, `setuptools`, `twine` y `wheel`; la CI y
`scripts/construir_windows.py` la usan (`pip install -c packaging/constraints.txt …`).

**Guarda de futuro:** `tests/test_ci_pinning.py` falla si una acción vuelve a una
etiqueta, si una imagen base fija pierde el digest o si falta el archivo de
restricciones.
