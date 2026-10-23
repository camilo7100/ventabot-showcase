"""Que en Chatwoot y en el panel se vea QUÉ mandó la clienta (27/09).

El 26/09 apareció un «[adjunto]» en Chatwoot. No era un fallo del bot: Meta lo
entregó como `unsupported` (error 131051, «Message type is currently not
supported») y no le pasa al bot ni el archivo ni el enlace. Lo que sí era
nuestro: decir «[adjunto]» en vez de decir qué era, y que el modelo se lo
inventara («está mandando la foto de la medida»).
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.adapters.channels.whatsapp import WhatsAppAdapter
from app.adapters.crm.chatwoot import _nombre_de_archivo
from app.domain.models import (
    Channel,
    OutboundMessage,
    conversation_id,
    etiqueta_de_mensaje,
)
from app.infra.container import Container


def _webhook(*mensajes):
    return {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "contacts": [
                                {"wa_id": "573001112233", "profile": {"name": "Ana"}}
                            ],
                            "messages": list(mensajes),
                        }
                    }
                ]
            }
        ]
    }


def _msg(tipo, cuerpo, **extra):
    return {
        "from": "573001112233",
        "id": f"wamid.{tipo}",
        "timestamp": "1790448593",
        "type": tipo,
        **({tipo: cuerpo} if cuerpo is not None else {}),
        **extra,
    }


#: Textual, el del 26/09 (sin el número).
NO_SOPORTADO = _msg(
    "unsupported",
    {"type": "unknown", "raw_type": "unknown"},
    errors=[
        {
            "code": 131051,
            "title": "Message type unknown",
            "error_data": {"details": "Message type is currently not supported."},
        }
    ],
)


@pytest.fixture
def canal():
    return WhatsAppAdapter(
        phone_number_id="p", access_token="t", app_secret="s", verify_token="v"
    )


def _uno(canal, mensaje):
    (m,) = canal.parse_webhook(_webhook(mensaje))
    return m


class TestLoQueWhatsAppNoDejaVer:
    def test_llega_como_algo_y_no_como_nada(self, canal):
        m = _uno(canal, NO_SOPORTADO)
        assert m.text is None
        assert [x.kind for x in m.media] == ["unsupported"]

    def test_en_chatwoot_dice_que_era_y_que_hacer(self, canal):
        m = _uno(canal, NO_SOPORTADO)
        texto = etiqueta_de_mensaje(m.text, m.media)
        assert "[adjunto]" not in texto
        assert "WhatsApp no le deja ver" in texto and "Pídele" in texto
        assert "unknown" not in texto, "«unknown» no le dice nada a Lía"

    def test_al_modelo_no_lo_deja_adivinar(self):
        from app.conversacion.asesora import _SIN_ARCHIVO

        assert "No adivines" in _SIN_ARCHIVO["unsupported"]


class TestLosDemasTipos:
    def test_reaccion(self, canal):
        m = _uno(canal, _msg("reaction", {"message_id": "wamid.x", "emoji": "❤️"}))
        assert etiqueta_de_mensaje(m.text, m.media) == "Reaccionó ❤️ a un mensaje"

    def test_quitar_una_reaccion_no_es_un_mensaje(self, canal):
        assert canal.parse_webhook(_webhook(_msg("reaction", {"message_id": "x"}))) == []

    def test_ubicacion_con_enlace_al_mapa(self, canal):
        m = _uno(
            canal,
            _msg(
                "location",
                {
                    "latitude": 7.07,
                    "longitude": -73.1,
                    "name": "Casa",
                    "address": "Cra 7",
                },
            ),
        )
        texto = etiqueta_de_mensaje(m.text, m.media)
        assert texto.startswith("📍 Ubicación") and "Cra 7" in texto
        assert "maps.google.com/?q=7.07,-73.1" in texto

    def test_contacto(self, canal):
        m = _uno(
            canal,
            _msg(
                "contacts",
                None,
                contacts=[
                    {"name": {"formatted_name": "Mamá"}, "phones": [{"phone": "+57 300"}]}
                ],
            ),
        )
        assert etiqueta_de_mensaje(m.text, m.media) == "👤 Contacto · Mamá +57 300"

    def test_boton_de_plantilla_es_lo_que_dijo(self, canal):
        m = _uno(canal, _msg("button", {"text": "Sí, confirmo", "payload": "SI"}))
        assert m.text == "Sí, confirmo" and not m.media

    def test_documento_conserva_su_nombre(self, canal):
        m = _uno(
            canal,
            _msg(
                "document",
                {
                    "id": "d1",
                    "mime_type": "application/pdf",
                    "filename": "comprobante.pdf",
                },
            ),
        )
        assert m.media[0].filename == "comprobante.pdf"
        assert etiqueta_de_mensaje(None, m.media) == "📄 Documento · comprobante.pdf"

    @pytest.mark.parametrize(
        ("tipo", "etiqueta"),
        [
            ("image", "📷 Foto"),
            ("audio", "🎤 Nota de voz"),
            ("video", "🎬 Video"),
            ("sticker", "🙂 Sticker"),
        ],
    )
    def test_sin_texto_se_dice_que_es(self, canal, tipo, etiqueta):
        m = _uno(canal, _msg(tipo, {"id": "x", "mime_type": "y"}))
        assert etiqueta_de_mensaje(m.text, m.media) == etiqueta

    def test_con_texto_manda_el_texto(self, canal):
        m = _uno(canal, _msg("image", {"id": "x", "caption": "mira la regla"}))
        assert etiqueta_de_mensaje(m.text, m.media) == "mira la regla"


class TestLosArchivosEnChatwoot:
    """Chatwoot decide por la EXTENSIÓN si pone un reproductor o un clip."""

    @pytest.mark.parametrize(
        ("mime", "extension"),
        [
            ("image/jpeg", "jpg"),
            ("audio/ogg", "ogg"),
            ("audio/mp4", "m4a"),
            ("audio/aac", "aac"),
            ("audio/amr", "amr"),
            ("video/mp4", "mp4"),
            ("video/3gpp", "3gp"),
            ("image/webp", "webp"),
            ("application/pdf", "pdf"),
        ],
    )
    def test_cada_tipo_con_su_extension(self, mime, extension):
        assert _nombre_de_archivo({}, mime, 1) == f"adjunto-1.{extension}"

    def test_un_documento_con_su_propio_nombre(self):
        nombre = _nombre_de_archivo({"filename": "Cotización.xlsx"}, "x", 1)
        assert nombre == "Cotización.xlsx"

    def test_un_nombre_raro_no_rompe_la_subida(self):
        assert "/" not in _nombre_de_archivo({"filename": 'a/b"c.pdf'}, "", 1)

    def test_un_tipo_desconocido_igual_se_sube(self):
        assert _nombre_de_archivo({}, "", 2) == "adjunto-2.bin"


class TestElPrimerMensajeNoCambia:
    """Antes, un «unsupported» de primer mensaje llegaba como nada y salía la
    apertura fija. Sigue siendo así: al bot no se le pasa en el primer turno."""

    def test_en_el_primer_turno_no_se_le_pasa(self, monkeypatch, tmp_path):
        import app.infra.container as contenedor
        from app.infra.settings import get_settings

        monkeypatch.setenv("REPOSITORY_BACKEND", "memory")
        monkeypatch.setenv("CHANNEL_BACKEND", "console")
        monkeypatch.setenv("LLM_BACKEND", "fake")
        monkeypatch.setenv("SQLITE_PATH", str(tmp_path / "t.db"))
        get_settings.cache_clear()
        contenedor._singleton = None
        try:
            c = contenedor.get_container()
            canal = WhatsAppAdapter(
                phone_number_id="p", access_token="t", app_secret="s", verify_token="v"
            )
            m = _uno(canal, NO_SOPORTADO)
            assert c._media_para_el_bot(m) == []
            c.bot._mundo.anotar_mensaje_de_humano(m.conversation_id, "hola")
            assert [x["kind"] for x in c._media_para_el_bot(m)] == ["unsupported"]
        finally:
            get_settings.cache_clear()
            contenedor._singleton = None


class TestContactosSinWaId:
    """14/10: Meta empezó a mandar contactos con `user_id` y sin `wa_id`; el
    webhook se caía entero (KeyError 'wa_id') y ningún mensaje entraba."""

    def test_entra_igual(self, canal):
        msg = _msg("text", {"body": "hola"})
        cuerpo = _webhook(msg)
        cuerpo["entry"][0]["changes"][0]["value"]["contacts"] = [
            {"user_id": "CO.123", "profile": {"name": "Ana"}}
        ]
        [m] = canal.parse_webhook(cuerpo)
        assert m.text == "hola" and m.sender_id == "573001112233"

    def test_sin_numero_usa_el_identificador_nuevo(self, canal):
        msg = _msg("text", {"body": "hola"})
        del msg["from"]
        msg["from_user_id"] = "CO.123"
        cuerpo = _webhook(msg)
        cuerpo["entry"][0]["changes"][0]["value"]["contacts"] = [
            {"user_id": "CO.123", "profile": {"name": "Ana"}}
        ]
        [m] = canal.parse_webhook(cuerpo)
        assert m.sender_id == "CO.123" and m.sender_name == "Ana"

    def test_se_le_contesta_por_el_identificador_nuevo(self, canal):
        sin_numero = canal.render(
            OutboundMessage(channel=Channel.WHATSAPP, to="CO.123", text="hola")
        )
        assert sin_numero["recipient"] == "CO.123" and "to" not in sin_numero
        con_numero = canal.render(
            OutboundMessage(channel=Channel.WHATSAPP, to="573001112233", text="hola")
        )
        assert con_numero["to"] == "573001112233" and "recipient" not in con_numero

    def test_cuando_llega_con_numero_sigue_en_su_conversacion(self, canal):
        msg = _msg("text", {"body": "ya tengo la talla"})
        msg["from_user_id"] = "CO.123"
        [m] = canal.parse_webhook(_webhook(msg))
        ya_estaba = SimpleNamespace(
            customers=SimpleNamespace(
                get_by_channel_user=lambda canal, usuario: usuario == "CO.123" or None
            )
        )
        m2 = Container._misma_clienta(ya_estaba, m)
        assert m2.sender_id == "CO.123"
        assert m2.conversation_id == conversation_id(Channel.WHATSAPP, "CO.123")
        nueva = SimpleNamespace(
            customers=SimpleNamespace(get_by_channel_user=lambda canal, usuario: None)
        )
        assert Container._misma_clienta(nueva, m).sender_id == "573001112233"

    def test_un_paquete_sin_mensajes_ni_acuses_se_delata(self):
        """16/10: si Meta mueve los mensajes de sitio, nada falla y parece un
        acuse más. Eso tiene que verse."""
        from app.adapters.channels.whatsapp import formato_desconocido

        normal = _webhook(_msg("text", {"body": "hola"}))
        assert not formato_desconocido(normal)
        acuse = _webhook()
        acuse["entry"][0]["changes"][0]["value"]["statuses"] = [{"status": "read"}]
        assert not formato_desconocido(acuse)
        movido = _webhook()
        movido["entry"][0]["changes"][0]["value"]["mensajes_nuevos"] = [{"id": "x"}]
        assert formato_desconocido(movido)
        otro_aviso = {"entry": [{"changes": [{"field": "account_update", "value": {}}]}]}
        assert not formato_desconocido(otro_aviso)

    def test_un_mensaje_raro_no_tumba_a_los_demas(self, canal):
        malo = {"type": "text", "id": "x"}  # sin remitente ni hora
        bueno = _msg("text", {"body": "hola"})
        assert [m.text for m in canal.parse_webhook(_webhook(malo, bueno))] == ["hola"]
