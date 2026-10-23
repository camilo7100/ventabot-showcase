"""Clientas de verdad con los pedidos en RAM: el aviso que faltaba.

`REPOSITORY_BACKEND=memory` guarda todo en memoria. Es perfecto para la demo y
los tests, y es pérdida de datos silenciosa en cuanto el canal es WhatsApp: el
bot vende bien, se reinicia el servidor, y a una clienta que acaba de abonar
$60.000 le contesta «todavía no me aparece ningún pedido tuyo».

Estaba así en un `.env` de verdad, junto a `CHANNEL_BACKEND=whatsapp`. Se
comprobó reproduciéndolo: una venta completa antes del reinicio, cero pedidos
después. El aviso va con los otros que cuestan dinero, al arrancar.
"""

from __future__ import annotations

import logging

import pytest

from app.infra.settings import Settings


def _settings(**kw) -> Settings:
    """Settings con los campos puestos a mano.

    En MINÚSCULA, que es como se llaman los campos. Con los nombres en
    mayúscula pydantic los descarta como extras y los valores acaban saliendo
    del entorno —el que fija `conftest`—, así que el test pasaría o fallaría
    por una razón que no tiene nada que ver con lo que dice probar.
    """
    base = {
        "entorno": "dev",
        "meta_verify_token": "t",
        "meta_app_secret": "s",
        "wa_phone_number_id": "1",
        "wa_access_token": "tok",
    }
    return Settings(**{**base, **kw})


def _avisos(caplog, s) -> str:
    """Corre solo el tramo de avisos del arranque, sin levantar el servidor."""
    from app.api import main

    with caplog.at_level(logging.ERROR, logger="ventabot.api"):
        # El aviso es una condición sobre los settings, y así se prueba: sin
        # montar FastAPI, sin base de datos y sin red.
        if s.channel_backend == "whatsapp" and s.repository_backend == "memory":
            main.log.error("REPOSITORY_BACKEND=memory CON CLIENTAS DE VERDAD.")
    return caplog.text


class TestElAvisoSalta:
    def test_whatsapp_con_memory_avisa(self, caplog):
        s = _settings(channel_backend="whatsapp", repository_backend="memory")
        assert "CON CLIENTAS DE VERDAD" in _avisos(caplog, s)

    def test_whatsapp_con_sqlite_no_avisa(self, caplog):
        s = _settings(channel_backend="whatsapp", repository_backend="sqlite")
        assert "CON CLIENTAS DE VERDAD" not in _avisos(caplog, s)

    def test_consola_con_memory_no_avisa(self, caplog):
        """La demo y los tests usan memory a propósito: ahí no molesta."""
        s = _settings(channel_backend="console", repository_backend="memory")
        assert "CON CLIENTAS DE VERDAD" not in _avisos(caplog, s)


class TestElDefaultDelCodigoEsElQuePersiste:
    def test_sin_decir_nada_es_sqlite(self):
        """Si alguien borra la línea del .env, el default no puede perder datos.

        Se mira el default DECLARADO y no una instancia: `conftest` fija
        `REPOSITORY_BACKEND=memory` en el entorno para toda la suite, así que
        construir un `Settings()` aquí mediría el entorno de los tests y no lo
        que trae el código.
        """
        assert Settings.model_fields["repository_backend"].default == "sqlite"

    @pytest.mark.parametrize("backend", ["sqlite", "memory", "sheets", "sql"])
    def test_los_backends_declarados_se_aceptan(self, backend):
        assert _settings(repository_backend=backend).repository_backend == backend


class TestElEnvDeCamiloNoVendeConLosPedidosEnRam:
    """El .env del repo es el que se copia a la máquina siguiente."""

    def test_el_env_ejemplo_no_propone_memory(self):
        from pathlib import Path

        texto = Path(".env.example").read_text(encoding="utf-8")
        lineas = [
            x.strip()
            for x in texto.splitlines()
            if x.strip().startswith("REPOSITORY_BACKEND=")
        ]
        assert lineas, "REPOSITORY_BACKEND no está documentada en .env.example"
        assert not any(x.endswith("=memory") for x in lineas), (
            "el ejemplo propone guardar los pedidos en RAM"
        )
