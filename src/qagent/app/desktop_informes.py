"""Métodos de informes, historial y descargas del puente de escritorio."""

from __future__ import annotations

from pathlib import Path

import webview

from qagent.almacenamiento import AlmacenProyecto
from qagent.app.desktop_soporte import (
    _mostrar_en_explorador,
    _resolver_ruta_proyecto,
)


class InformesMixin:
    """Ejecución, reporte, historial, arquitectura, E2E y descargas ZIP."""

    def obtener_ejecucion(self, ruta: str, run_id: str | None = None) -> dict:
        """Datos de la vista Ejecución de una corrida (HU-18).

        Todo sale de `.qagent/runs/<run_id>/results.json` (por defecto, la corrida más
        reciente con resultados): indicadores comparados con las metas, filtros por
        estado y pruebas agrupadas por módulo.

        Returns:
            dict: ``{"ok": True, ...}`` con lo que arma `vista_ejecucion()`, o
            ``{"ok": False, "motivo": str}`` si no hay resultados que mostrar.
        """
        from qagent.storage.vista_comparacion import cargar_vista_comparacion
        from qagent.storage.vista_ejecucion import (
            ResultadosNoDisponibles,
            leer_results,
            vista_ejecucion,
        )

        try:
            results = leer_results(ruta, run_id)
            comparacion = cargar_vista_comparacion(
                ruta, results["run_id"], results.get("perfil")
            )
            return {"ok": True, **vista_ejecucion(results, comparacion)}
        except ResultadosNoDisponibles as error:
            return {"ok": False, "motivo": str(error)}

    def obtener_reporte(self, ruta: str, run_id: str | None = None) -> dict:
        """Datos del Reporte de auditoría de una corrida (HU-21).

        Las cifras y los controles salen de `results.json`; el contrato, el test y la
        traza de cada función, de `detalle.json` (misma carpeta de la corrida).

        Returns:
            dict: ``{"ok": True, ...}`` con lo que arma `vista_reporte()`, o
            ``{"ok": False, "motivo": str}`` si no hay resultados que mostrar.
        """
        from qagent.storage.vista_comparacion import cargar_vista_comparacion
        from qagent.storage.vista_ejecucion import (
            ResultadosNoDisponibles,
            leer_results,
        )
        from qagent.storage.vista_reporte import (
            leer_detalle,
            leer_explicaciones,
            vista_reporte,
        )

        try:
            results = leer_results(ruta, run_id)
        except ResultadosNoDisponibles as error:
            return {"ok": False, "motivo": str(error)}
        detalle = leer_detalle(ruta, results["run_id"])
        explicaciones = leer_explicaciones(ruta, results)
        comparacion = cargar_vista_comparacion(
            ruta, results["run_id"], results.get("perfil")
        )
        return {
            "ok": True,
            **vista_reporte(results, detalle, explicaciones, comparacion),
        }

    def carpeta_corrida(self, ruta: str, run_id: str | None = None) -> str:
        """Devuelve la carpeta por defecto `<proyecto>/.qagent/runs/<run_id>/` para exportar."""
        from qagent.storage.corrida_demo import CORRIDA_DEMO_ID
        from qagent.storage.exportar_informe import carpeta_por_defecto

        raiz = _resolver_ruta_proyecto(ruta, run_id)
        carpeta = carpeta_por_defecto(raiz, run_id or CORRIDA_DEMO_ID)
        return str(carpeta) + "\\"

    def abrir_carpeta_corrida(self, ruta: str, run_id: str | None = None) -> dict:
        """Abre la carpeta `.qagent/runs/<run_id>/` en el explorador de archivos."""
        from qagent.storage.corrida_demo import CORRIDA_DEMO_ID, asegurar_corrida_demo
        from qagent.storage.exportar_informe import carpeta_por_defecto

        raiz = _resolver_ruta_proyecto(ruta, run_id)
        id_efectivo = run_id or CORRIDA_DEMO_ID
        try:
            if id_efectivo == CORRIDA_DEMO_ID:
                carpeta = asegurar_corrida_demo(raiz, id_efectivo)
            else:
                carpeta = carpeta_por_defecto(raiz, id_efectivo)
                carpeta.mkdir(parents=True, exist_ok=True)
        except OSError as error:
            return {"ok": False, "motivo": str(error)}

        if self._window is not None:
            _mostrar_en_explorador(carpeta, seleccionar_archivo=False)
        return {"ok": True, "carpeta": str(carpeta)}

    def exportar_informe(
        self,
        ruta: str,
        run_id: str | None = None,
        formato: str = "pdf",
        opciones: dict | None = None,
        carpeta_destino: str | None = None,
    ) -> dict:
        """Exporta el informe de la corrida como evidencia en PDF, Markdown o JSON (HU-22).

        Por defecto se guarda en `<proyecto>/.qagent/runs/<run_id>/` como
        `informe_<run_id>.pdf` o `.md`, o `results_<run_id>.json`; si se indica
        `carpeta_destino`, se escribe en esa carpeta.

        Returns:
            dict: ``{"ok": True, "run_id", "formato", "nombre", "ruta", "carpeta",
            "opciones"}``, o ``{"ok": False, "motivo": str}`` si no se pudo exportar.
        """
        from qagent.storage.exportar_informe import FormatoInvalido, exportar_informe
        from qagent.storage.vista_ejecucion import ResultadosNoDisponibles

        raiz = _resolver_ruta_proyecto(ruta, run_id)
        try:
            resultado = exportar_informe(
                raiz,
                run_id=run_id,
                formato=formato,
                opciones=opciones,
                carpeta_destino=carpeta_destino,
            )
        except (ResultadosNoDisponibles, FormatoInvalido, OSError) as error:
            return {"ok": False, "motivo": str(error)}

        if self._window is not None and resultado.get("ok"):
            _mostrar_en_explorador(Path(resultado["ruta"]), seleccionar_archivo=True)
        return resultado

    def obtener_historial(self, ruta: str) -> dict:
        """Corridas y specs persistidas del proyecto para la pantalla Historial."""
        from qagent.almacenamiento.historial import construir_historial

        return {"ok": True, **construir_historial(ruta)}

    def obtener_resultado_arquitectura(self, ruta: str, run_id: str) -> dict:
        """Lee una corrida arquitectónica sin confundirla con `results.json`."""
        from qagent.arquitectura.ejecucion import leer_resultado_arquitectura

        try:
            return {"ok": True, **leer_resultado_arquitectura(ruta, run_id)}
        except (OSError, TypeError, ValueError) as error:
            return {"ok": False, "motivo": str(error)}

    def obtener_reglas_arquitectura(self, ruta: str) -> dict:
        """Reglas vigentes: la universal y las declaradas en `.qagent`."""
        try:
            return {
                "ok": True,
                **AlmacenProyecto(ruta).leer_reglas_arquitectura(),
            }
        except (OSError, TypeError, ValueError) as error:
            return {"ok": False, "motivo": str(error)}

    def guardar_reglas_arquitectura(self, ruta: str, documento: dict) -> dict:
        """Valida y persiste reglas declaradas; nunca acepta comandos ejecutables."""
        try:
            guardado = AlmacenProyecto(ruta).guardar_reglas_arquitectura(documento)
            return {"ok": True, **guardado}
        except (OSError, TypeError, ValueError) as error:
            return {"ok": False, "motivo": str(error)}

    def verificar_arquitectura(self, ruta: str) -> dict:
        """Ejecuta la comprobación determinista en Docker y devuelve su Run ID."""
        from qagent.arquitectura.ejecucion import verificar_arquitectura
        from qagent.config import cargar_configuracion
        from qagent.lenguajes import REGISTRO

        try:
            lenguaje = REGISTRO.lenguaje_principal(ruta)
            carga = cargar_configuracion()
            limites = carga.config.limites_sandbox(lenguaje) if carga.config else None
            return {"ok": True, **verificar_arquitectura(ruta, limites=limites)}
        except (OSError, TypeError, ValueError) as error:
            return {"ok": False, "motivo": str(error)}

    def exportar_informe_arquitectura(
        self, ruta: str, run_id: str, formato: str = "pdf", destino: str | None = None
    ) -> dict:
        """Exporta una corrida arquitectónica como JSON, MD, HTML o PDF."""
        from qagent.arquitectura.informe import exportar

        try:
            return exportar(ruta, run_id, formato, destino)
        except (OSError, ValueError) as error:
            return {"ok": False, "motivo": str(error)}

    def detectar_e2e(self, ruta: str) -> dict:
        """Presenta las rutas antes de que la persona decida ejecutar Playwright."""
        from qagent.e2e.deteccion import detectar_plan_e2e

        try:
            return {"ok": True, **detectar_plan_e2e(ruta)}
        except (OSError, TypeError, ValueError) as error:
            return {"ok": False, "motivo": str(error)}

    def ejecutar_e2e(self, ruta: str) -> dict:
        """Ejecuta voluntariamente el humo E2E determinista, nunca al abrir el proyecto."""
        from qagent.e2e.ejecucion import ejecutar_humo_e2e

        try:
            return {"ok": True, **ejecutar_humo_e2e(ruta)}
        except (OSError, TypeError, ValueError) as error:
            return {"ok": False, "motivo": str(error)}

    def obtener_resultado_e2e(self, ruta: str, run_id: str) -> dict:
        """Lee una corrida E2E separada de los resultados de agentes."""
        from qagent.e2e.ejecucion import leer_resultado_e2e

        try:
            return {"ok": True, **leer_resultado_e2e(ruta, run_id)}
        except (OSError, ValueError) as error:
            return {"ok": False, "motivo": str(error)}

    def exportar_informe_e2e(
        self, ruta: str, run_id: str, formato: str = "html", destino: str | None = None
    ) -> dict:
        """Exporta un resultado E2E con sus referencias de evidencia."""
        from qagent.e2e.informe import exportar

        try:
            return exportar(ruta, run_id, formato, destino)
        except (OSError, ValueError) as error:
            return {"ok": False, "motivo": str(error)}

    def descargar_specs_zip(self, ruta: str, modulo: str | None = None) -> dict:
        """Crea un ZIP y abre el diálogo nativo para elegir dónde guardarlo."""
        from qagent.almacenamiento import ErrorAlmacen

        try:
            nombre, contenido = AlmacenProyecto(ruta).crear_zip_specs(modulo)
        except ErrorAlmacen as error:
            return {"ok": False, "motivo": str(error)}
        return self._guardar_zip(nombre, contenido)

    def descargar_pruebas_zip(self, ruta: str) -> dict:
        """Crea un ZIP con las pruebas guardadas y abre el diálogo para guardarlo."""
        from qagent.almacenamiento import ErrorAlmacen

        try:
            nombre, contenido = AlmacenProyecto(ruta).crear_zip_pruebas()
        except ErrorAlmacen as error:
            return {"ok": False, "motivo": str(error)}
        return self._guardar_zip(nombre, contenido)

    def _guardar_zip(self, nombre: str, contenido: bytes) -> dict:
        """Pide dónde guardar un ZIP con el diálogo nativo y lo escribe."""
        if self._window is None:
            return {"ok": False, "motivo": "La ventana de QAgent no está disponible."}

        seleccion = self._window.create_file_dialog(
            webview.SAVE_DIALOG,
            save_filename=nombre,
            file_types=("Archivos ZIP (*.zip)",),
        )
        if not seleccion:
            return {"ok": False, "cancelado": True}

        destino = Path(seleccion[0])
        if destino.suffix.lower() != ".zip":
            destino = destino.with_suffix(".zip")
        try:
            destino.write_bytes(contenido)
        except OSError as error:
            return {"ok": False, "motivo": f"No se pudo guardar el ZIP: {error}"}
        return {
            "ok": True,
            "nombre": destino.name,
            "ruta": str(destino),
        }
