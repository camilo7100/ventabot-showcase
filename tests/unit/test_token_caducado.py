"""Un token caducado tiene que verse DISTINTO de una caída de red.

Este archivo protege una lección que costó una mañana: el bot recibía los
mensajes sin problema y no podía responder ninguno, y el log solo repetía
cinco veces `401 Unauthorized` sin decir que era el token ni qué hacer.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RAIZ / "scripts"))

from app.adapters.channels.whatsapp import WhatsAppAdapter  # noqa: E402
from app.domain.models import Channel, OutboundMessage  # noqa: E402
from app.domain.ports import TokenDelCanalCaducado  # noqa: E402
from app.workers.outbox_dispatcher import OutboxDispatcher  # noqa: E402


class RespuestaFalsa:
    def __init__(self, status_code: int, cuerpo: dict) -> None:
        self.status_code = status_code
        self._cuerpo = cuerpo

    def json(self) -> dict:
        return self._cuerpo

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


def _cliente(monkeypatch, respuesta):
    import httpx

    monkeypatch.setattr(httpx, "post", lambda *a, **k: respuesta)
    return WhatsAppAdapter(
        phone_number_id="123",
        access_token="EAAfalso",
        app_secret="0" * 32,
        verify_token="y",
    )


MENSAJE = OutboundMessage(
    channel=Channel.WHATSAPP,
    to="573001112233",
    text="hola",
    idempotency_key="k1",
    conversation_id="wa:573001112233",
)


class TestElAdaptadorDistingueElToken:
    def test_un_401_es_token_caducado(self, monkeypatch):
        cliente = _cliente(monkeypatch, RespuestaFalsa(401, {"error": {"code": 190}}))
        with pytest.raises(TokenDelCanalCaducado):
            cliente.send(MENSAJE)

    def test_el_codigo_190_tambien_aunque_venga_con_200(self, monkeypatch):
        """Meta no siempre usa el status HTTP: a veces manda 200 con error dentro."""
        cliente = _cliente(monkeypatch, RespuestaFalsa(200, {"error": {"code": 190}}))
        with pytest.raises(TokenDelCanalCaducado):
            cliente.send(MENSAJE)

    def test_otros_errores_NO_se_confunden_con_el_token(self, monkeypatch):
        """Un 500 de Meta sí es transitorio y sí merece reintento."""
        cliente = _cliente(monkeypatch, RespuestaFalsa(500, {"error": {"code": 1}}))
        with pytest.raises(Exception) as e:
            cliente.send(MENSAJE)
        assert not isinstance(e.value, TokenDelCanalCaducado)


class CanalQueNoTieneToken:
    def send(self, m, *, ventana_abierta=True):
        raise TokenDelCanalCaducado("caducó")


class OutboxFalsa:
    def __init__(self, mensajes):
        self.mensajes = mensajes
        self.fallidos: list[str] = []

    def pending(self, limit):
        return self.mensajes

    def mark_failed(self, key, error):
        self.fallidos.append(key)

    def mark_sent(self, key, external_id):  # pragma: no cover
        raise AssertionError("no debería enviarse")


class TestElDespachadorAvisaUnaSolaVez:
    def test_tres_mensajes_producen_un_solo_aviso(self, caplog):
        mensajes = [
            OutboundMessage(
                channel=Channel.WHATSAPP,
                to="573001112233",
                text=f"m{i}",
                idempotency_key=f"k{i}",
                conversation_id="wa:573001112233",
            )
            for i in range(3)
        ]
        outbox = OutboxFalsa(mensajes)
        d = OutboxDispatcher(outbox, {"whatsapp": CanalQueNoTieneToken()})

        with caplog.at_level("ERROR"):
            asyncio.run(d.despachar_una_vez())

        avisos = [r for r in caplog.records if "el token de Meta caducó" in r.message]
        assert len(avisos) == 1, "el aviso se repitió por cada mensaje"
        assert d.fallidos == 3
        assert len(outbox.fallidos) == 3

    def test_el_aviso_dice_QUE_HACER(self, caplog):
        outbox = OutboxFalsa([MENSAJE])
        d = OutboxDispatcher(outbox, {"whatsapp": CanalQueNoTieneToken()})
        with caplog.at_level("ERROR"):
            asyncio.run(d.despachar_una_vez())
        texto = "\n".join(r.message for r in caplog.records)
        assert "vb token" in texto, "el aviso no dice cómo arreglarlo"


class TestElComandoToken:
    def test_humaniza_el_tiempo_restante(self):
        from token_meta import humanizar

        assert humanizar(-1) == "ya caducó"
        assert "minutos" in humanizar(600)
        assert "horas" in humanizar(5 * 3600)
        assert "días" in humanizar(30 * 24 * 3600)

    def test_el_script_no_tapa_el_modulo_token_de_python(self):
        """Llamarlo scripts/token.py rompía la libreria estandar entera:
        `scripts/` esta en sys.path, asi que `import token` (que usan
        inspect, dis y linecache) cargaba el script en su lugar."""
        import token as stdlib

        assert hasattr(stdlib, "NAME"), "algo esta tapando el modulo token"
