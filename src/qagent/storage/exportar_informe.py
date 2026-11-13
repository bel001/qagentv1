"""Exportación del informe de auditoría como evidencia formal (HU-22).

Genera el informe de una corrida en tres formatos:
- PDF (`informe_<run_id>.pdf`)
- Markdown (`informe_<run_id>.md`)
- JSON (`results_<run_id>.json`)

Por defecto se guarda en `<proyecto>/.qagent/runs/<run_id>/`, o en la carpeta que el
usuario elija. Todas las cifras salen de `results.json` (las mismas que muestra la
pantalla en HU-18 y HU-21), y todo el contenido pasa por el filtro de secretos (RN-07)
para que nunca incluya claves de IA.

La implementación vive en módulos separados por formato; este módulo conserva la
interfaz pública que usan la app y las pruebas.
"""

from __future__ import annotations

from qagent.storage.informe_archivos import (
    carpeta_por_defecto,
    construir_pdf_informe,
    exportar_informe,
    extraer_texto_pdf,
    nombre_archivo_informe,
    verificar_archivo_sin_claves,
)
from qagent.storage.informe_comun import (
    ETIQUETAS_CONTROL,
    ETIQUETAS_ESTADO,
    FORMATOS,
    NOMBRES_AGENTE,
    NOMBRES_ETAPAS,
    FormatoInvalido,
    _sanitizar_estructura,
    normalizar_opciones,
    sanitizar_secretos,
)
from qagent.storage.informe_datos import (
    _filas_entorno,
    avisos_fuera_de_la_corrida,
    construir_cinco_metricas,
    datos_informe,
    resumen_specs_corrida,
)
from qagent.storage.informe_html import construir_html_informe
from qagent.storage.informe_json import construir_json_informe
from qagent.storage.informe_markdown import construir_markdown_informe
from qagent.storage.informe_salud import _salud_proyecto

__all__ = [
    "ETIQUETAS_CONTROL",
    "ETIQUETAS_ESTADO",
    "FORMATOS",
    "NOMBRES_AGENTE",
    "NOMBRES_ETAPAS",
    "FormatoInvalido",
    "_filas_entorno",
    "_salud_proyecto",
    "_sanitizar_estructura",
    "avisos_fuera_de_la_corrida",
    "carpeta_por_defecto",
    "construir_cinco_metricas",
    "construir_html_informe",
    "construir_json_informe",
    "construir_markdown_informe",
    "construir_pdf_informe",
    "datos_informe",
    "exportar_informe",
    "extraer_texto_pdf",
    "nombre_archivo_informe",
    "normalizar_opciones",
    "resumen_specs_corrida",
    "sanitizar_secretos",
    "verificar_archivo_sin_claves",
]
