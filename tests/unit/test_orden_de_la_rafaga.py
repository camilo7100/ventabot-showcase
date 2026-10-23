"""Que el texto llegue DESPUÉS de los archivos, y no en medio del álbum.

════════════════════════════════════════════════════════════════════════════
LO QUE PASÓ
════════════════════════════════════════════════════════════════════════════
La presentación sale en cuatro piezas: la ficha, dos videos y la foto con la
pregunta de pie. Se mandan en ese orden y a la clienta le llegó la pregunta
**en medio** del álbum.

No es un bug del orden: Meta no recibe el archivo, recibe una URL y lo baja de
nuestro servidor. Los videos pesan 3,5 MB y la foto 136 KB, así que la foto
adelantó a los videos. Mandar en orden no es llegar en orden.

La solución es esperar un poco tras cada archivo. Lo que se prueba aquí es que
se espera cuando hace falta y —igual de importante— que NO se espera cuando no
hace falta, porque cada segundo de más es una clienta esperando.
"""

from __future__ import annotations

import asyncio

from app.domain.models import Channel, OutboundMessage
from app.workers.outbox_dispatcher import ESPERA_TRAS_ARCHIVO_S, OutboxDispatcher


class _OutboxDeMentira:
    def __init__(self, mensajes):
        self._mensajes = list(mensajes)
        self.enviados = []

    def pending(self, limite=50):
        return [m for m in self._mensajes if m.idempotency_key not in self.enviados]

    def mark_sent(self, clave, external_id):
        self.enviados.append(clave)

    def mark_failed(self, clave, motivo):  # pragma: no cover - aquí no falla nada
        raise AssertionError(motivo)


class _CanalQueAnota:
    def __init__(self):
        self.orden = []

    def send(self, m, *, ventana_abierta=True):
        self.orden.append(m.idempotency_key)
        return f"wamid.{m.idempotency_key}"


def _pieza(clave: str, kind: str, conv: str = "wa:573001112233") -> OutboundMessage:
    return OutboundMessage(
        channel=Channel.WHATSAPP,
        to=conv.partition(":")[2],
        kind=kind,
        text="" if kind != "text" else "hola",
        media_url="" if kind == "text" else f"https://x.dev/media/{clave}",
        conversation_id=conv,
        idempotency_key=clave,
    )


def _despachar(mensajes) -> tuple[list[str], list[float]]:
    """Despacha y devuelve (orden de envío, esperas que hizo)."""
    esperas: list[float] = []
    canal = _CanalQueAnota()
    outbox = _OutboxDeMentira(mensajes)
    despachador = OutboxDispatcher(outbox, {"whatsapp": canal})

    dormir = asyncio.sleep

    async def _espiar(segundos, *a, **kw):
        if segundos:
            esperas.append(segundos)
        return await dormir(0)

    async def _correr():
        asyncio.sleep = _espiar
        try:
            await despachador.despachar_una_vez()
        finally:
            asyncio.sleep = dormir

    asyncio.run(_correr())
    return canal.orden, esperas


class TestLaPresentacionLlegaEnOrden:
    def test_se_espera_tras_cada_video_antes_de_seguir(self):
        orden, esperas = _despachar(
            [
                _pieza("ficha", "text"),
                _pieza("video1", "video"),
                _pieza("video2", "video"),
                _pieza("foto", "image"),
            ]
        )
        assert orden == ["ficha", "video1", "video2", "foto"]
        # Dos esperas: una tras cada video. Tras el texto no hace falta (sale
        # al instante) y tras la última pieza tampoco (no hay nada detrás).
        assert esperas == [ESPERA_TRAS_ARCHIVO_S["video"]] * 2

    def test_tras_el_ULTIMO_archivo_no_se_espera(self):
        """Esperar por el último no ordena nada y retrasa a la siguiente."""
        _, esperas = _despachar([_pieza("ficha", "text"), _pieza("foto", "image")])
        assert esperas == []

    def test_no_se_espera_si_lo_siguiente_es_de_OTRA_clienta(self):
        """El texto de otra conversación no se puede desordenar con este
        archivo, así que hacerla esperar seis segundos sería gratis y cruel."""
        _, esperas = _despachar(
            [
                _pieza("video1", "video"),
                _pieza("otra", "text", conv="wa:573009998877"),
            ]
        )
        assert esperas == []

    def test_la_espera_es_corta(self):
        """Con 6 s por video la presentación tardaba 16 s en salir entera y
        parecía que el bot se había caído (Camilo, 20/09). Lo justo para
        ordenar, no para que se note."""
        assert 0 < ESPERA_TRAS_ARCHIVO_S["video"] <= 3.0
        assert ESPERA_TRAS_ARCHIVO_S["image"] == ESPERA_TRAS_ARCHIVO_S["video"]

    def test_nada_se_descarta_por_esperar(self):
        """Lo que más importa: la espera ORDENA, no filtra. Todo lo que entra
        a la cola sale."""
        orden, _ = _despachar(
            [
                _pieza("uno", "video"),
                _pieza("dos", "image"),
                _pieza("tres", "text"),
            ]
        )
        assert orden == ["uno", "dos", "tres"]
