"""Que Camilo se entere si algo se rompe, sin que avisar rompa nada.

Un token vencido se ve, desde afuera, igual que un día tranquilo: hasta que hay
tres clientas sin respuesta. Estas pruebas cuidan las tres reglas del aviso:
no repite, no lleva datos de clientas, y nunca tumba el envío.
"""

from __future__ import annotations

import asyncio

import pytest

from app.adapters.avisos import AvisosPorNtfy, AvisosPorTelegram, SinAvisos
from app.adapters.channels.whatsapp import TokenDelCanalCaducado
from app.domain.models import Channel, OutboundMessage
from app.domain.ports import AvisosPort
from app.workers.outbox_dispatcher import OutboxDispatcher


class AvisosDeMentira:
    def __init__(self) -> None:
        self.avisos: list[tuple[str, str, str]] = []

    def avisar(self, titulo: str, detalle: str = "", clave: str = "") -> bool:
        self.avisos.append((titulo, detalle, clave))
        return True


class AvisosQueFallan:
    def avisar(self, titulo: str, detalle: str = "", clave: str = "") -> bool:
        raise RuntimeError("el servicio de avisos no responde")


class TestLosAdaptadores:
    def test_cumplen_el_puerto(self):
        assert isinstance(SinAvisos(), AvisosPort)
        assert isinstance(AvisosPorNtfy("tema"), AvisosPort)
        assert isinstance(AvisosPorTelegram("t", "1"), AvisosPort)
        assert isinstance(AvisosDeMentira(), AvisosPort)

    def test_sin_avisos_no_pasa_nada(self):
        assert SinAvisos().avisar("se rompió algo") is False

    def test_el_mismo_problema_no_avisa_dos_veces_seguidas(self, monkeypatch):
        """Una API caída mandaría cien notificaciones y se silenciaría la app."""
        mandados = []

        class _Respuesta:
            def raise_for_status(self):
                return None

        def _post(url, **kw):
            mandados.append(url)
            return _Respuesta()

        import httpx

        monkeypatch.setattr(httpx, "post", _post)
        avisos = AvisosPorNtfy("tema-secreto")
        assert avisos.avisar("token caducado", clave="token") is True
        assert avisos.avisar("token caducado", clave="token") is False
        assert len(mandados) == 1

    def test_si_el_servicio_de_avisos_falla_no_levanta(self, monkeypatch):
        import httpx

        def _post(url, **kw):
            raise httpx.ConnectError("sin internet")

        monkeypatch.setattr(httpx, "post", _post)
        assert AvisosPorNtfy("tema").avisar("algo") is False


# ══════════════════════════════════════════════════════════════════════════
#  EL DESPACHADOR: avisa de lo que de verdad deja clientas sin respuesta
# ══════════════════════════════════════════════════════════════════════════


class _CanalQueFalla:
    def __init__(self, error: Exception) -> None:
        self._error = error

    def send(self, m, *, ventana_abierta: bool = True) -> str:
        raise self._error


class _Outbox:
    def __init__(self, mensajes) -> None:
        self._mensajes = list(mensajes)
        self.fallidos: list[tuple[str, str]] = []

    def pending(self, limit: int = 50):
        return list(self._mensajes)

    def mark_sent(self, clave, external_id=None):
        self._mensajes = [m for m in self._mensajes if m.idempotency_key != clave]

    def mark_failed(self, clave, error):
        self.fallidos.append((clave, error))
        self._mensajes = [m for m in self._mensajes if m.idempotency_key != clave]

    def posponer(self, clave, segundos, motivo):
        return None


def _mensaje() -> OutboundMessage:
    return OutboundMessage(
        channel=Channel.WHATSAPP, to="573001112233", kind="text", text="hola"
    )


def _despachar(error: Exception, avisos) -> None:
    outbox = _Outbox([_mensaje()])
    despachador = OutboxDispatcher(
        outbox, {"whatsapp": _CanalQueFalla(error)}, avisos=avisos
    )
    asyncio.run(despachador._enviar(outbox.pending()[0]))


class TestElDespachador:
    def test_avisa_cuando_el_token_caduco(self):
        avisos = AvisosDeMentira()
        _despachar(TokenDelCanalCaducado("401"), avisos)
        assert avisos.avisos, "un token caducado deja a TODAS las clientas sin respuesta"
        titulo, detalle, clave = avisos.avisos[0]
        assert "no puede responder" in titulo.lower()
        assert "vb token" in detalle
        assert clave == "token"

    def test_avisa_cuando_un_mensaje_no_sale(self):
        avisos = AvisosDeMentira()
        _despachar(RuntimeError("500 del canal"), avisos)
        assert avisos.avisos and avisos.avisos[0][2] == "envio"

    def test_el_aviso_no_lleva_el_telefono_de_la_clienta(self):
        avisos = AvisosDeMentira()
        _despachar(RuntimeError("500 del canal"), avisos)
        todo = " ".join(x for aviso in avisos.avisos for x in aviso)
        assert "573001112233" not in todo, "los avisos viajan por un tercero"

    def test_si_avisar_falla_el_despachador_sigue(self):
        """Avisar es lo menos importante que pasa: nunca puede tumbar la cola."""
        outbox = _Outbox([_mensaje()])
        despachador = OutboxDispatcher(
            outbox,
            {"whatsapp": _CanalQueFalla(RuntimeError("x"))},
            avisos=AvisosQueFallan(),
        )
        asyncio.run(despachador._enviar(outbox.pending()[0]))
        assert outbox.fallidos, "el mensaje se marcó como fallido igual"

    def test_sin_avisos_configurados_todo_funciona_igual(self):
        outbox = _Outbox([_mensaje()])
        despachador = OutboxDispatcher(
            outbox, {"whatsapp": _CanalQueFalla(RuntimeError("x"))}
        )
        asyncio.run(despachador._enviar(outbox.pending()[0]))
        assert outbox.fallidos


@pytest.mark.parametrize(
    "ajustes",
    [
        {"avisos_backend": "ntfy", "ntfy_tema": ""},
        {"avisos_backend": "telegram", "telegram_bot_token": "x", "telegram_chat_id": ""},
    ],
)
def test_mal_configurado_no_arma_avisos(tmp_path, ajustes):
    from app.infra.container import build_container
    from app.infra.settings import Settings

    s = Settings(
        sqlite_path=tmp_path / "t.db",
        repository_backend="memory",
        llm_backend="fake",
        payment_backend="fake",
        channel_backend="console",
        ventas_excel=tmp_path / "v.xlsx",
        **ajustes,
    )
    assert build_container(s).avisos is None
