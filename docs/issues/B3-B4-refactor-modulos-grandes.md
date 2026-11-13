# B3/B4 — Refactor de módulos grandes

**Severidad:** Baja  
**Etiqueta:** mantenibilidad, refactor

## Problema

- `src/qagent/storage/exportar_informe.py` tiene 2415 líneas.
- `src/qagent/app/desktop.py` tiene 1415 líneas.
- `src/qagent/orchestrator/corrida.py` tiene 1398 líneas.
- `src/qagent/storage/corrida_demo.py` tiene 1120 líneas (datos de demostración dentro del paquete de lógica).

CLAUDE.md dice que `desktop.py` es «solo el puente», pero contiene lógica (abrir explorador, bloqueos, limpieza, migración).

## Corrección propuesta

- Partir por responsabilidades (exportación MD/HTML/PDF, API de escritorio, ejecución de corrida).
- Mover datos de demostración a un recurso JSON.

## Archivos afectados

- `src/qagent/app/desktop.py`
- `src/qagent/storage/exportar_informe.py`
- `src/qagent/orchestrator/corrida.py`
- `src/qagent/storage/corrida_demo.py`

## Criterios de aceptación

- Cada módulo resultante tiene < 600 líneas.
- La interfaz pública no cambia (tests pasan sin modificar).
- Los tests de storage y app siguen pasando.

## Resolución

Los cuatro módulos se partieron por responsabilidades; ninguno supera las 600 líneas.

| Antes | Ahora |
|---|---|
| `storage/exportar_informe.py` (2415) | `informe_comun.py` (115), `informe_datos.py` (393), `informe_detalle.py` (84), `informe_salud.py` (278), `informe_ejecucion.py` (373), `informe_markdown.py` (505), `informe_html.py` (566), `informe_html_estilos.py` (57), `informe_json.py` (214), `informe_archivos.py` (180) y `exportar_informe.py` (75) como fachada que conserva la interfaz pública |
| `app/desktop.py` (1415) | `desktop.py` (185) con `DesktopAPI` y el arranque, más los mixins `desktop_proyectos.py` (244), `desktop_configuracion.py` (213), `desktop_informes.py` (287), `desktop_verificacion.py` (207), `desktop_corrida.py` (427) y los helpers en `desktop_soporte.py` (335) |
| `orchestrator/corrida.py` (1398) | `corrida.py` (521) con `ejecutar_corrida`, más `corrida_modelo.py` (200), `corrida_entorno.py` (259), `corrida_planificacion.py` (465), `corrida_registro.py` (438) y `corrida_explicacion.py` (142) |
| `storage/corrida_demo.py` (1120) | `corrida_demo.py` (275) y los datos de demostración en `storage/datos_demo.json` (38 KB) |

Detalles que mantienen la interfaz pública:

- `qagent.app.desktop.DesktopAPI` sigue siendo la clase que se pasa a pywebview; los
  métodos viven en mixins y `desktop.py` reexporta los nombres que se usan desde fuera
  (`FRONTEND_DIR`, `SEGUIMIENTO`, `_resolver_ruta_proyecto`, `ejecutar`…).
- `qagent.storage.exportar_informe` sigue exportando lo mismo (`exportar_informe`,
  `construir_markdown_informe`, `construir_html_informe`, `construir_pdf_informe`,
  `construir_json_informe`, `sanitizar_secretos`, `datos_informe`…).
- `qagent.orchestrator.corrida` sigue exportando `ejecutar_corrida`, `ResumenCorrida`,
  `EntornoEnPreparacion`, `limites_del_lenguaje`, `metas_de`, `tipo_terminacion` y los
  helpers que usan la app y las pruebas; los nombres que no están importados se
  resuelven con `__getattr__`.
- Los dobles de prueba siguen funcionando: donde las pruebas reemplazan un nombre en
  `qagent.app.desktop` o en `qagent.orchestrator.corrida` (por ejemplo
  `_registrar_run`, `_tomar_bloqueo`, `crear_cliente`, `escribir_corrida`,
  `escribir_explicaciones`), el código lo resuelve en tiempo de llamada desde ese
  módulo.
- `datos_demo.json` se instala con el paquete (`package-data` de `qagent.storage`).

Un solo test cambió de pointers: `tests/orchestrator/test_omitidos_no_son_pendientes.py`
comprobaba que el criterio común de los informes viviera en `exportar_informe.py`; ahora
comprueba los tres módulos que construyen los informes (`informe_markdown.py`,
`informe_html.py` e `informe_pdf.py`) y el de datos (`informe_datos.py`). La aserción es
la misma; solo cambia el archivo donde vive el código.
