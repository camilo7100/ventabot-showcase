"""Tests del diagnóstico de firmas.

Una herramienta de diagnóstico que se equivoca es peor que no tenerla: manda a
buscar el problema donde no está. Estos tests cubren los cuatro escenarios
reales, incluido un bug que tuvo la propia herramienta: cuando el secreto está
limpio, varias hipótesis son equivalentes y todas coinciden; quedarse con la
ÚLTIMA hacía que reportara "tienes un BOM" cuando en realidad todo estaba bien.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
from datetime import UTC, datetime, timedelta

import pytest

from scripts.diagnostico_firma import (
    es_payload_de_ejemplo,
    hipotesis,
    huella,
)

SECRETO = "0123456789abcdef0123456789abcdef"  # 32 hex, como los de Meta
CUERPO = b'{"object":"whatsapp_business_account","entry":[]}'


def firmar(secreto: str, cuerpo: bytes) -> str:
    return "sha256=" + hmac.new(secreto.encode(), cuerpo, hashlib.sha256).hexdigest()


def primera_que_encaja(secreto: str, cuerpo: bytes, recibida: str):
    for nombre, calculada, significado in hipotesis(secreto, cuerpo):
        if hmac.compare_digest(calculada, recibida):
            return nombre, significado
    return None


class TestHuella:
    def test_el_mismo_secreto_da_la_misma_huella(self):
        assert huella(SECRETO) == huella(SECRETO)

    def test_secretos_distintos_dan_huellas_distintas(self):
        assert huella(SECRETO) != huella(SECRETO.replace("0", "1"))

    def test_la_huella_no_revela_el_secreto(self):
        h = huella(SECRETO)
        assert SECRETO not in h
        assert len(h) == 12


class TestHipotesis:
    def test_firma_correcta_gana_la_hipotesis_canonica(self):
        """El bug real: con el secreto limpio coinciden varias hipótesis.

        La que se reporta debe ser la canónica ("todo correcto"), no una
        cualquiera de las equivalentes.
        """
        resultado = primera_que_encaja(SECRETO, CUERPO, firmar(SECRETO, CUERPO))
        assert resultado is not None
        assert resultado[1] == "todo correcto"

    def test_detecta_un_bom_delante_del_secreto(self):
        con_bom = "﻿" + SECRETO
        recibida = firmar(SECRETO, CUERPO)  # Meta firma con el secreto limpio
        resultado = primera_que_encaja(con_bom, CUERPO, recibida)
        assert resultado is not None
        assert "BOM" in resultado[0]

    def test_detecta_espacios_alrededor(self):
        recibida = firmar(SECRETO, CUERPO)
        resultado = primera_que_encaja(f"  {SECRETO}\n", CUERPO, recibida)
        assert resultado is not None
        assert "espacios" in resultado[0]

    def test_con_un_secreto_de_otra_app_no_encaja_ninguna(self):
        """El caso importante: descarta el código y señala al secreto."""
        otro = "ffffffffffffffffffffffffffffffff"
        assert primera_que_encaja(SECRETO, CUERPO, firmar(otro, CUERPO)) is None

    def test_si_el_cuerpo_cambia_un_byte_no_encaja_ninguna(self):
        """Detectaría un proxy que modifica el payload en el camino."""
        recibida = firmar(SECRETO, CUERPO)
        alterado = CUERPO.replace(b"entry", b"entrY")
        assert primera_que_encaja(SECRETO, alterado, recibida) is None

    def test_un_secreto_no_hexadecimal_no_rompe_la_herramienta(self):
        """La hipótesis de 'bytes hex' no puede reventar con un secreto raro."""
        hipotesis("no-es-hexadecimal-para-nada", CUERPO)  # no debe lanzar


class TestCapturaDelServidor:
    """El formato del archivo que escribe el servidor al rechazar un webhook."""

    def _captura(self, tmp_path, *, minutos_atras: int = 0):
        momento = datetime.now(UTC) - timedelta(minutes=minutos_atras)
        ruta = tmp_path / "webhook_fallido.json"
        ruta.write_text(
            json.dumps(
                {
                    "capturado_en": momento.isoformat(),
                    "cabeceras": {"x-hub-signature-256": firmar(SECRETO, CUERPO)},
                    "cuerpo_base64": base64.b64encode(CUERPO).decode(),
                    "cuerpo_bytes": len(CUERPO),
                }
            ),
            encoding="utf-8",
        )
        return ruta

    def test_el_cuerpo_sobrevive_intacto_al_viaje_por_base64(self, tmp_path):
        """Guardarlo como texto podría cambiar un salto de línea y el HMAC ya
        no cuadraría: estaríamos depurando un cuerpo distinto al que llegó."""
        datos = json.loads(self._captura(tmp_path).read_text(encoding="utf-8"))
        assert base64.b64decode(datos["cuerpo_base64"]) == CUERPO

    def test_la_captura_no_guarda_el_secreto(self, tmp_path):
        texto = self._captura(tmp_path).read_text(encoding="utf-8")
        assert SECRETO not in texto

    @pytest.mark.parametrize("minutos,vieja", [(0, False), (5, False), (45, True)])
    def test_se_puede_saber_si_la_captura_es_vieja(self, tmp_path, minutos, vieja):
        """Analizar una captura antigua con un secreto nuevo da un veredicto
        falso. Pasó durante las pruebas de esta misma herramienta."""
        datos = json.loads(
            self._captura(tmp_path, minutos_atras=minutos).read_text(encoding="utf-8")
        )
        momento = datetime.fromisoformat(datos["capturado_en"])
        edad_min = (datetime.now(UTC) - momento).total_seconds() / 60
        assert (edad_min > 10) is vieja


#: El cuerpo EXACTO que manda el botón «Probar» del panel de Meta. Capturado de
#: una integración real: es el mismo para todo el mundo, sale de su documentación.
EJEMPLO_DE_META = (
    b'{"object":"whatsapp_business_account","entry":[{"id":"0","changes":'
    b'[{"field":"messages","value":{"messaging_product":"whatsapp","metadata":'
    b'{"display_phone_number":"16505551111","phone_number_id":"123456123"},'
    b'"contacts":[{"profile":{"name":"test user name"},"wa_id":"16315551181"}],'
    b'"messages":[{"id":"ABGGFlA5Fpa","timestamp":"1504902988",'
    b'"from":"16315551181","type":"text","text":{"body":"this is a text message"}}]'
    b"}}]}]}"
)


class TestPayloadDeEjemplo:
    """Distinguir el botón «Probar» de un mensaje real.

    Sin esta detección se pierden horas: el ejemplo de Meta nunca valida contra
    tu secreto, y el 403 es idéntico al de un problema de verdad. Pasó.
    """

    def test_reconoce_el_ejemplo_del_boton_probar(self):
        marcas = es_payload_de_ejemplo(EJEMPLO_DE_META)
        assert len(marcas) >= 2, marcas

    def test_un_mensaje_real_no_se_confunde_con_el_ejemplo(self):
        real = (
            b'{"object":"whatsapp_business_account","entry":[{"id":"123456789012345",'
            b'"changes":[{"field":"messages","value":{"messaging_product":"whatsapp",'
            b'"metadata":{"display_phone_number":"573001112233",'
            b'"phone_number_id":"123456789012345"},"contacts":[{"profile":'
            b'{"name":"Camilo"},"wa_id":"573001112233"}],"messages":[{"from":'
            b'"573001112233","id":"wamid.HBgM","timestamp":"1788400000","type":'
            b'"text","text":{"body":"hola"}}]}}]}]}'
        )
        assert es_payload_de_ejemplo(real) == []

    def test_un_cuerpo_cualquiera_no_da_falsos_positivos(self):
        assert es_payload_de_ejemplo(b'{"hola":"mundo"}') == []

    def test_el_ejemplo_no_valida_con_ningun_secreto_nuestro(self):
        """Confirma por qué confunde: falla igual que un problema de verdad."""
        firma_ajena = "sha256=" + "76a06ece" * 8
        assert primera_que_encaja(SECRETO, EJEMPLO_DE_META, firma_ajena) is None
