"""Tests de `scripts/app_meta.py`, el diagnóstico que identifica la app de Meta.

Lo que se prueba aquí no es "que el código corra": es que el `appsecret_proof`
sea EXACTAMENTE el que Meta espera. Si esa fórmula está mal, el script diría
"tu secreto es de otra app" siempre, y mandaría a cambiar un secreto que estaba
bien. Un diagnóstico que miente es peor que no tenerlo.
"""

from __future__ import annotations

import hashlib
import hmac
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RAIZ / "scripts"))

import app_meta  # noqa: E402


class TestAppsecretProof:
    def test_es_hmac_del_token_con_el_secreto_de_clave(self):
        """La clave es el SECRETO y el mensaje es el TOKEN. Invertirlos es el
        error clásico, y produce un hex igual de válido pero incorrecto."""
        token, secreto = "EAAtoken123", "0123456789abcdef0123456789abcdef"
        esperado = hmac.new(secreto.encode(), token.encode(), hashlib.sha256).hexdigest()
        assert app_meta.proof(token, secreto) == esperado

    def test_no_es_simetrico(self):
        token, secreto = "EAAtoken123", "0123456789abcdef0123456789abcdef"
        assert app_meta.proof(token, secreto) != app_meta.proof(secreto, token)

    def test_devuelve_64_hex(self):
        p = app_meta.proof("t", "s")
        assert len(p) == 64
        assert all(ch in "0123456789abcdef" for ch in p)


class TestHuella:
    def test_dos_secretos_iguales_dan_la_misma_huella(self):
        assert app_meta.huella("abc") == app_meta.huella("abc")

    def test_no_revela_el_secreto(self):
        secreto = "0123456789abcdef0123456789abcdef"
        assert secreto not in app_meta.huella(secreto)

    def test_coincide_con_la_de_vb_firma(self):
        """Las dos herramientas tienen que dar la MISMA huella o compararlas
        entre sí (que es justo lo que se le pide al usuario) no sirve de nada."""
        import diagnostico_firma

        assert app_meta.huella("hola") == diagnostico_firma.huella("hola")


class TestAppsDeMeta:
    def test_reconoce_la_app_interna_que_ensucia_el_listado(self):
        assert app_meta.es_de_meta("WA DevX Webhook Events 1P App")

    def test_no_marca_una_app_del_usuario(self):
        assert not app_meta.es_de_meta("VentaBot")
        assert not app_meta.es_de_meta("Mi tienda")


class TestUrlDelSecreto:
    def test_apunta_a_la_pagina_exacta(self):
        url = app_meta.url_del_secreto("1234567890")
        assert url == "https://developers.facebook.com/apps/1234567890/settings/basic/"
