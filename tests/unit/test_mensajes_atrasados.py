"""Lo que Meta entrega con más de 24 h de atraso (16/10).

Del 9 al 15/10 Meta no pudo entregar los mensajes de las clientas sin número
y los reintentó días después (Ivonne escribió el 9/10 y llegó el 15/10).
WhatsApp ya no deja contestarles libre: se registran, van a Chatwoot con la
nota «📩 Mensaje ATRASADO» y se les escribe con la plantilla de emergencia.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.domain.models import Channel, InboundMessage


def _mensaje(hace: timedelta, texto: str = "hola") -> InboundMessage:
    return InboundMessage(
        channel=Channel.WHATSAPP,
        external_message_id=f"wamid.{texto}",
        conversation_id="wa:573001112233",
        sender_id="573001112233",
        text=texto,
        timestamp=datetime.now(UTC) - hace,
    )


def test_lo_escrito_hace_mas_de_24h_se_registra_sin_respuesta(tmp_path):
    """16/10: Ivonne escribió el 9/10 y Meta lo entregó el 15/10. WhatsApp ya
    no deja contestarle libre: nada a la outbox (saldría viejo el día que
    vuelva a escribir), pero queda en su historial."""
    import sqlite3

    from app.infra import container as contenedor
    from app.infra.settings import Settings

    s = Settings(
        sqlite_path=tmp_path / "a.db",
        repository_backend="memory",
        llm_backend="fake",
        payment_backend="fake",
        channel_backend="console",
        meta_app_secret="secreto",
        meta_verify_token="verify",
        chatwoot_webhook_token="",
        ventas_excel=tmp_path / "v.xlsx",
    )
    c = contenedor.build_container(s)
    try:
        viejo = _mensaje(timedelta(days=6), "Quiero más información")
        cuando = str(int(viejo.timestamp.timestamp()))
        viejo = viejo.model_copy(update={"raw": {"timestamp": cuando}})
        assert c.procesar_mensaje(viejo) == []
        with sqlite3.connect(str(s.sqlite_path)) as cx:
            assert cx.execute("SELECT count(*) FROM outbox").fetchone()[0] == 0
        hist = c.conversaciones.historial("wa:573001112233", limite=10)
        assert [h["texto"] for h in hist] == ["Quiero más información"]
    finally:
        c.cerrar()


class TestLaPlantillaDeEmergenciaDeDia:
    """La disculpa a las atrasadas nunca sale de noche (Camilo, 16/10). Solo
    eso: los mensajes que llegan a tiempo se contestan a cualquier hora."""

    def _colombia(self, hora: int) -> datetime:
        return datetime(2026, 10, 16, hora, 30, tzinfo=UTC) + timedelta(hours=5)

    def test_de_dia_sale_ya(self):
        from app.domain.plantilla_de_emergencia import cuando_mandarla

        assert cuando_mandarla(self._colombia(8)) is None
        assert cuando_mandarla(self._colombia(19)) is None

    def test_de_noche_espera_a_las_8(self):
        from app.domain.plantilla_de_emergencia import cuando_mandarla

        las_8_de_hoy = datetime(2026, 10, 16, 13, 0, tzinfo=UTC)
        assert cuando_mandarla(self._colombia(2)) == las_8_de_hoy
        assert cuando_mandarla(self._colombia(22)) == las_8_de_hoy + timedelta(days=1)


def test_con_la_plantilla_aprobada_le_llega_sola_una_vez(tmp_path):
    """Si Meta ya aprobó la plantilla, la atrasada la recibe sin que nadie haga
    nada; si Meta reintenta el mismo mensaje, no se le manda dos veces."""
    import sqlite3

    from app.domain.plantilla_de_emergencia import NOMBRE
    from app.infra import container as contenedor
    from app.infra.settings import Settings

    s = Settings(
        sqlite_path=tmp_path / "b.db",
        repository_backend="memory",
        llm_backend="fake",
        payment_backend="fake",
        channel_backend="console",
        meta_app_secret="secreto",
        meta_verify_token="verify",
        chatwoot_webhook_token="",
        ventas_excel=tmp_path / "v.xlsx",
    )
    c = contenedor.build_container(s)
    try:
        c._emergencia = (datetime.now(UTC), NOMBRE)  # Meta ya la aprobó
        viejo = _mensaje(timedelta(days=3), "Quiero más información")
        cuando = str(int(viejo.timestamp.timestamp()))
        viejo = viejo.model_copy(update={"raw": {"timestamp": cuando}})
        c.procesar_mensaje(viejo)
        c.procesar_mensaje(viejo)  # el mismo reintento otra vez
        with sqlite3.connect(str(s.sqlite_path)) as cx:
            filas = cx.execute("SELECT payload FROM outbox").fetchall()
        assert len(filas) == 1 and NOMBRE in filas[0][0]
    finally:
        c.cerrar()
