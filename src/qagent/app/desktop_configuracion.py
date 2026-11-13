"""Métodos de configuración, claves y espacio del puente de escritorio."""

from __future__ import annotations

from qagent.app import bitacora
from qagent.app.desktop_soporte import (
    _LIBERANDO_ESPACIO,
    _ocultar_claves_en_bitacora,
)


class ConfiguracionMixin:
    """Entorno, proveedores, roles, límites, tema y espacio en disco."""

    def verificar_entorno(self) -> dict:
        """Verifica config.toml, claves de .env, Docker y Git (EN-06).

        Se vuelve a leer todo en cada llamada, así que el usuario puede corregir el
        `.env` y pulsar Reintentar sin reiniciar la aplicación. Nunca devuelve claves.

        Returns:
            dict: `listo`, `mensaje`, `problemas` y `comprobaciones` (ver
            `qagent.config.verificar_entorno`).
        """
        from qagent.config import carga as config_carga
        from qagent.config import verificar_entorno

        self._refrescar_estado_local()  # #251: IA simulada y claves del .env al día
        return verificar_entorno(
            config_carga.RUTA_CONFIG,
            config_carga.RUTA_ENV,
            ruta_local=config_carga.RUTA_CONFIG_LOCAL,
        )

    def listar_proveedores(self) -> list[dict]:
        """Proveedores y modelos del catálogo para el formulario «Agregar API» (HU-30)."""
        from qagent.config.roles import listar_proveedores

        return listar_proveedores()

    def obtener_version(self) -> str:
        """Versión instalada de QAgent (la de `qagent --version`), para la interfaz."""
        from qagent import __version__

        return __version__

    def obtener_roles(self) -> list[dict]:
        """Proveedor, modelo y clave enmascarada de cada agente (HU-30).

        Incluye al Recomendador (#244), que es opcional: sin su clave se usan las reglas.
        """
        from qagent.config import carga as config_carga
        from qagent.config.roles import leer_roles

        return leer_roles(
            config_carga.RUTA_CONFIG,
            config_carga.RUTA_ENV,
            config_carga.RUTA_CONFIG_LOCAL,
            con_opcionales=True,
        )

    def guardar_api_rol(
        self, agente: str, proveedor: str, modelo: str, clave: str | None = None
    ) -> dict:
        """Prueba la conexión y, si responde, guarda la API del agente (HU-30).

        La clave va solo a `.env`, en la variable propia del agente; el
        `config.local.toml` del usuario (`~/.qagent/`) recibe proveedor y modelo. El proveedor puede repetirse entre agentes, la clave
        no. Si la prueba falla no se guarda nada. La respuesta nunca incluye la clave.

        Returns:
            dict: ``{"ok", "mensaje", "detalle"?, "roles"}``.
        """
        from qagent.config import carga as config_carga
        from qagent.config.roles import configurar_rol

        resultado = configurar_rol(
            agente,
            proveedor,
            modelo,
            clave,
            ruta_config=config_carga.RUTA_CONFIG,
            ruta_env=config_carga.RUTA_ENV,
            ruta_local=config_carga.RUTA_CONFIG_LOCAL,
        )
        if resultado["ok"]:
            if clave:
                _ocultar_claves_en_bitacora()
            bitacora.registro.info(
                "API del %s guardada: %s / %s", agente, proveedor, modelo
            )
            if resultado.get("aviso"):
                bitacora.registro.warning("  %s", resultado["aviso"])
        else:
            bitacora.registro.warning(
                "API del %s no guardada (%s / %s): %s",
                agente,
                proveedor,
                modelo,
                resultado["mensaje"],
            )
        return {**resultado, "roles": self.obtener_roles()}

    def eliminar_api_rol(self, agente: str) -> dict:
        """Deja al agente «Sin configurar» en esta computadora y quita su clave (HU-30).

        Returns:
            dict: ``{"ok", "mensaje", "roles"}``.
        """
        from qagent.config import carga as config_carga
        from qagent.config.roles import eliminar_rol

        resultado = eliminar_rol(
            agente,
            ruta_config=config_carga.RUTA_CONFIG,
            ruta_env=config_carga.RUTA_ENV,
            ruta_local=config_carga.RUTA_CONFIG_LOCAL,
        )
        if resultado["ok"]:
            bitacora.registro.info("API del %s eliminada: sin configurar.", agente)
        return {**resultado, "roles": self.obtener_roles()}

    def obtener_limites(self) -> dict:
        """Límites de verificación vigentes para la pantalla Configuración.

        Returns:
            dict: ver `qagent.config.limites.leer_limites`.
        """
        from qagent.config.limites import leer_limites

        return leer_limites()

    def guardar_limites(self, max_intentos: int, max_tokens: int | None = None) -> dict:
        """Guarda los intentos y el presupuesto de tokens en el `config.local.toml`.

        El tiempo máximo por prueba no se guarda: `[sandbox]` lo define solo el equipo.

        Returns:
            dict: ``{"ok", "mensaje", "limites"}``.
        """
        from qagent.config.limites import (
            guardar_limites as config_guardar_limites,
        )
        from qagent.config.limites import (
            leer_limites,
        )

        resultado = config_guardar_limites(
            max_intentos=max_intentos, max_tokens=max_tokens
        )
        if resultado["ok"]:
            bitacora.registro.info(
                "Límites actualizados: intentos=%s, tokens=%s", max_intentos, max_tokens
            )
        return {**resultado, "limites": leer_limites()}

    def obtener_espacio_disco(self) -> dict:
        """Cuánto ocupa QAgent en Docker y cuánto espacio libre queda (Configuración, #267).

        Returns:
            dict: ver `qagent.sandbox.uso_disco.medir_uso`.
        """
        from qagent.sandbox.uso_disco import medir_uso

        return medir_uso()

    def liberar_espacio(self, incluir_cache: bool = False) -> dict:
        """Borra lo que QAgent puede reconstruir en Docker (botón «Liberar espacio», #267).

        Conserva las imágenes base y no corre mientras haya una corrida en curso (su imagen
        no se puede borrar). La caché de compilación de Docker, que es de todos los
        `docker build` y no solo de QAgent, solo se poda con `incluir_cache`, que la interfaz
        pide tras avisarlo en la confirmación.

        Returns:
            dict: ver `qagent.sandbox.uso_disco.liberar_espacio`, más `uso` (la medición
            nueva) y `en_curso` si se rechazó por la corrida.
        """
        from qagent.sandbox.uso_disco import liberar_espacio, medir_uso

        if self._corrida is not None and self._corrida.is_alive():
            return {
                "ok": False,
                "en_curso": True,
                "mensaje": (
                    "Hay una corrida en curso y está usando el entorno aislado: "
                    "espera a que termine para liberar espacio."
                ),
            }
        if not _LIBERANDO_ESPACIO.acquire(blocking=False):
            return {"ok": False, "mensaje": "Ya se está liberando espacio."}
        try:
            resultado = liberar_espacio(incluir_cache=bool(incluir_cache))
            if resultado["ok"]:
                bitacora.registro.info("Sandbox: %s", resultado["mensaje"])
            return {**resultado, "uso": medir_uso()}
        finally:
            _LIBERANDO_ESPACIO.release()

    def obtener_tema(self) -> dict:
        """Tema visual vigente (oscuro o claro) para la interfaz de escritorio."""
        from qagent.config.apariencia import leer_tema

        return {"ok": True, "tema": leer_tema()}

    def guardar_tema(self, tema: str) -> dict:
        """Guarda la preferencia de tema (oscuro o claro) en `config.local.toml`."""
        from qagent.config.apariencia import guardar_tema

        resultado = guardar_tema(tema)
        if resultado["ok"]:
            bitacora.registro.info("Tema de la interfaz: %s", tema)
        return resultado
