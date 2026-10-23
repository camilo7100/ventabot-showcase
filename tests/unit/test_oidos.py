"""Las notas de voz: si se pueden oír, la venta sigue sin que ella teclee nada.

Muchas clientas hablan en vez de escribir. «¿Me lo escribes porfa?» es una venta
que se enfría, así que transcribir importa — pero **nunca** puede tumbar el turno:
si el servicio falla, el bot vuelve a pedirlo por escrito y sigue vendiendo.
"""

from __future__ import annotations

import pytest

from app.adapters.llm.oidos import MAXIMO_BYTES, OidosDeGroq, OidosSordos
from app.domain.ports import OidosPort
from tests.unit.test_asesora import (  # noqa: F401  (mundo es un fixture)
    CONV,
    Guion,
    _con_guion,
    _jugada,
    mundo,
)

AUDIO = [{"kind": "audio", "media_id": "nota-1", "mime_type": "audio/ogg"}]


class OidosDeMentira:
    """Oye siempre lo mismo. Es lo que se usa en los tests del turno."""

    def __init__(self, dicho: str | None = "quiero el anillo de dos huellitas"):
        self.dicho = dicho
        self.veces = 0

    def transcribir(self, datos: bytes, mime: str = "") -> str | None:
        self.veces += 1
        return self.dicho


class OidosQueFallan:
    def transcribir(self, datos: bytes, mime: str = "") -> str | None:
        raise RuntimeError("el servicio de transcripción se cayó")


class TestElPuerto:
    def test_los_adaptadores_cumplen_el_puerto(self):
        assert isinstance(OidosSordos(), OidosPort)
        assert isinstance(OidosDeGroq("clave"), OidosPort)
        assert isinstance(OidosDeMentira(), OidosPort)

    def test_sin_servicio_no_se_oye_nada(self):
        assert OidosSordos().transcribir(b"lo que sea") is None

    def test_un_audio_gigante_ni_se_intenta(self):
        """Transcribir media hora de audio cuesta, tarda y no es una nota de voz."""
        enorme = b"x" * (MAXIMO_BYTES + 1)
        assert OidosDeGroq("clave").transcribir(enorme) is None
        assert OidosDeGroq("clave").transcribir(b"") is None


def _asesora_con_oidos(mundo, oidos, jugada=None):  # noqa: F811
    guion = Guion(jugada or _jugada("¡Dale! 🫶"))
    a = _con_guion(mundo, guion)
    a._oidos = oidos
    a._descargar = lambda adjunto: b"audio-de-mentira"
    return a, guion


class TestElTurno:
    def test_lo_que_dijo_en_el_audio_llega_al_modelo(self, mundo):  # noqa: F811
        oidos = OidosDeMentira("hola, quiero el de dos huellitas en negro")
        a, guion = _asesora_con_oidos(mundo, oidos)

        a.ejecutar(CONV, "", AUDIO)

        assert oidos.veces == 1
        entrada = guion.entradas[0]
        assert "dos huellitas en negro" in entrada
        assert "nota de voz" in entrada

    def test_si_no_se_puede_oir_se_le_pide_por_escrito(self, mundo):  # noqa: F811
        a, guion = _asesora_con_oidos(mundo, OidosDeMentira(None))
        a.ejecutar(CONV, "", AUDIO)
        assert "no se puede escuchar" in guion.entradas[0]

    def test_si_el_servicio_falla_el_turno_sigue(self, mundo):  # noqa: F811
        """Perder la transcripción es quedarse como antes; reventar es perder la venta."""
        a, guion = _asesora_con_oidos(mundo, OidosQueFallan())
        turno = a.ejecutar(CONV, "", AUDIO)
        assert turno.respuesta.texto_plano.strip()
        assert "no se puede escuchar" in guion.entradas[0]

    def test_sin_oidos_configurados_se_comporta_como_siempre(self, mundo):  # noqa: F811
        guion = Guion(_jugada("¡Dale! 🫶"))
        a = _con_guion(mundo, guion)
        a._descargar = lambda adjunto: b"audio"
        a.ejecutar(CONV, "", AUDIO)
        assert "no se puede escuchar" in guion.entradas[0]


class TestConfiguracion:
    def test_groq_sin_clave_no_arma_oidos(self, tmp_path):
        from app.infra.container import build_container
        from app.infra.settings import Settings

        s = Settings(
            sqlite_path=tmp_path / "t.db",
            repository_backend="memory",
            llm_backend="fake",
            payment_backend="fake",
            channel_backend="console",
            transcripcion_backend="groq",
            groq_api_key="",
            ventas_excel=tmp_path / "v.xlsx",
        )
        c = build_container(s)
        assert getattr(c.bot, "_oidos", None) is None


@pytest.mark.parametrize("mime", ["audio/ogg; codecs=opus", "audio/mpeg", ""])
def test_el_mime_de_whatsapp_no_rompe_nada(mime):
    """WhatsApp manda `audio/ogg; codecs=opus`: la extensión sale de ahí."""
    assert OidosDeGroq("clave").transcribir(b"", mime) is None
