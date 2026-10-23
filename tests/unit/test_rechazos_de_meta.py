"""Cuando Meta rechaza un mensaje, el sistema tiene que decir POR QUÉ.

Encontrado en la primera prueba real con el número del negocio: la outbox solo
guardaba «400 Bad Request» y el motivo de verdad —(#131030) el número no está en
la lista de destinatarios— se perdía. Con eso, un fallo en producción es una
adivinanza.
"""

from __future__ import annotations

import httpx
import pytest

from app.adapters.channels.whatsapp import (
    QUE_HACER,
    RechazoDeMeta,
    TokenDelCanalCaducado,
    WhatsAppAdapter,
)
from app.domain.models import Channel, OutboundMessage


def _respuesta(status: int, error: dict) -> httpx.Response:
    return httpx.Response(
        status,
        json={"error": error},
        request=httpx.Request("POST", "https://graph.facebook.com/v21.0/1/messages"),
    )


@pytest.fixture
def canal(monkeypatch):
    def _armar(respuesta: httpx.Response):
        monkeypatch.setattr(httpx, "post", lambda *a, **kw: respuesta)
        return WhatsAppAdapter("1", "token", "secreto", "verify")

    return _armar


def _mensaje() -> OutboundMessage:
    return OutboundMessage(channel=Channel.WHATSAPP, to="573009990001", text="hola")


class TestRechazos:
    def test_el_motivo_de_meta_no_se_pierde(self, canal):
        c = canal(
            _respuesta(
                400,
                {
                    "code": 131030,
                    "message": "(#131030) Recipient phone number not in allowed list",
                    "error_data": {"details": "El número no está en la lista"},
                },
            )
        )
        with pytest.raises(RechazoDeMeta) as error:
            c.send(_mensaje())
        assert error.value.codigo == 131030
        texto = str(error.value)
        assert "131030" in texto and "lista" in texto
        assert "agrégalo" in texto, "dice qué hacer, no solo qué pasó"

    def test_la_ventana_de_24_horas_se_explica(self, canal):
        c = canal(_respuesta(400, {"code": 131047, "message": "Re-engagement message"}))
        with pytest.raises(RechazoDeMeta) as error:
            c.send(_mensaje())
        assert "plantilla" in str(error.value)

    def test_un_codigo_desconocido_igual_dice_lo_que_mando_meta(self, canal):
        c = canal(_respuesta(400, {"code": 999999, "message": "algo nuevo de Meta"}))
        with pytest.raises(RechazoDeMeta) as error:
            c.send(_mensaje())
        assert "algo nuevo de Meta" in str(error.value)

    def test_si_meta_no_manda_json_no_revienta_el_diagnostico(self, canal):
        respuesta = httpx.Response(
            502,
            text="Bad gateway",
            request=httpx.Request("POST", "https://graph.facebook.com/v21.0/1/messages"),
        )
        with pytest.raises(RechazoDeMeta) as error:
            canal(respuesta).send(_mensaje())
        assert "502" in str(error.value)

    def test_el_token_caducado_sigue_siendo_su_propio_error(self, canal):
        """El despachador lo trata distinto: avisa con instrucciones y no reintenta."""
        c = canal(_respuesta(401, {"code": 190, "message": "token expired"}))
        with pytest.raises(TokenDelCanalCaducado):
            c.send(_mensaje())

    def test_los_consejos_estan_en_espanol_y_son_accionables(self):
        for codigo, consejo in QUE_HACER.items():
            assert consejo and len(consejo) > 15, codigo
