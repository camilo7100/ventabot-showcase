"""Cuatro mensajes seguidos son UNA pregunta, y se contestan una vez.

Sale de las conversaciones reales de Lía. Esta es la ráfaga textual de una
clienta, cuatro mensajes en menos de un minuto:

    «Son dos huellitas»
    «Una huellita negra por mi panterita»
    «Y la otra huellita no se jajaja»
    «Tienes referencias de negro con otra huella»

Lía las leyó todas y contestó una vez. El bot contestaba cuatro veces, y la
tercera respuesta estaba mal escrita antes de salir porque se redactó sin haber
leído la cuarta línea.
"""

from __future__ import annotations

import asyncio

from app.domain.models import Channel, InboundMessage, MediaRef
from app.workers.agrupador import Agrupador, fundir

CONV = "wa:573001112233"

RAFAGA = (
    "Son dos huellitas",
    "Una huellita negra por mi panterita",
    "Y la otra huellita no se jajaja",
    "Tienes referencias de negro con otra huella",
)


def msg(texto, id_="wamid.1", media=None):
    return InboundMessage(
        channel=Channel.WHATSAPP,
        sender_id="573001112233",
        conversation_id=CONV,
        external_message_id=id_,
        text=texto,
        media=media or [],
        raw={},
    )


class TestFundir:
    def test_uno_solo_se_devuelve_tal_cual(self):
        m = msg("hola")
        assert fundir([m]) is m

    def test_los_textos_van_en_orden_y_en_lineas_distintas(self):
        junto = fundir([msg(t, f"wamid.{i}") for i, t in enumerate(RAFAGA)])
        assert junto.text == "\n".join(RAFAGA)

    def test_manda_el_id_del_ULTIMO(self):
        """Es el que la deduplicación acaba de marcar como visto, y el que va
        en la clave de idempotencia de la respuesta."""
        junto = fundir([msg("a", "wamid.1"), msg("b", "wamid.2")])
        assert junto.external_message_id == "wamid.2"

    def test_las_fotos_se_suman_todas(self):
        """Si manda el comprobante y luego el anillo sobre la regla, las dos
        cosas hacen falta: quedarse con una pierde media conversación."""

        def foto(n):
            return MediaRef(kind="image", media_id=n, mime_type="image/jpeg")

        uno = msg("mira", "wamid.1", [foto("f1")])
        dos = msg("y esta", "wamid.2", [foto("f2")])
        assert [x.media_id for x in fundir([uno, dos]).media] == ["f1", "f2"]

    def test_un_mensaje_sin_texto_no_deja_lineas_vacias(self):
        junto = fundir([msg("hola", "wamid.1"), msg("", "wamid.2")])
        assert junto.text == "hola"


class TestApagado:
    """Con espera 0 se atiende al llegar, que es el modo por defecto."""

    def test_cada_mensaje_se_atiende_de_inmediato(self):
        vistos = []
        a = Agrupador(vistos.append, espera_s=0)
        assert not a.activo
        for i, t in enumerate(RAFAGA):
            asyncio.run(a.recibir(msg(t, f"wamid.{i}")))
        assert [m.text for m in vistos] == list(RAFAGA)


class TestEncendido:
    """Las corrutinas se arrancan con asyncio.run, a mano.

    Sin pytest-asyncio a propósito: una dependencia más en el proyecto para
    seis tests no se paga, y asyncio.run hace lo mismo en una línea.
    """

    def test_la_rafaga_entera_produce_UNA_respuesta(self):
        vistos = []

        async def corre():
            a = Agrupador(vistos.append, espera_s=0.05)
            for i, t in enumerate(RAFAGA):
                await a.recibir(msg(t, f"wamid.{i}"))
                await asyncio.sleep(0.01)  # escribe rápido, como en la vida real
            await asyncio.sleep(0.2)

        asyncio.run(corre())
        assert len(vistos) == 1, "contestó más de una vez a una sola pregunta"
        assert vistos[0].text == "\n".join(RAFAGA)

    def test_si_deja_de_escribir_se_contesta(self):
        vistos = []

        async def corre():
            a = Agrupador(vistos.append, espera_s=0.05)
            await a.recibir(msg("hola"))
            await asyncio.sleep(0.2)

        asyncio.run(corre())
        assert len(vistos) == 1

    def test_dos_conversaciones_no_se_mezclan(self):
        vistos = []

        async def corre():
            a = Agrupador(vistos.append, espera_s=0.05)
            otra = msg("yo soy otra").model_copy(update={"conversation_id": "wa:999"})
            await a.recibir(msg("yo soy una"))
            await a.recibir(otra)
            await asyncio.sleep(0.2)

        asyncio.run(corre())
        assert len(vistos) == 2
        assert {m.conversation_id for m in vistos} == {CONV, "wa:999"}

    def test_al_parar_se_atiende_lo_que_estaba_esperando(self):
        """Un Ctrl+C no se puede comer el mensaje de una clienta."""
        vistos = []

        async def corre():
            a = Agrupador(vistos.append, espera_s=30)
            await a.recibir(msg("no me pierdas"))
            await a.detener()

        asyncio.run(corre())
        assert [m.text for m in vistos] == ["no me pierdas"]

    def test_un_fallo_al_atender_no_tumba_la_tarea(self):
        """Corre en una tarea de asyncio suelta: una excepción aquí no la vería
        nadie, y el aviso del log es lo único que avisa a una persona."""

        def revienta(_m):
            raise RuntimeError("la base de datos se cayó")

        async def corre():
            a = Agrupador(revienta, espera_s=0.05)
            await a.recibir(msg("hola"))
            await asyncio.sleep(0.2)  # si escapara, la tarea moriría aquí
            await a.detener()

        asyncio.run(corre())  # que no reviente es todo lo que se prueba


class TestLoQuePasoEl26DeSeptiembre:
    """Ocho mensajes reenviados en el mismo segundo produjeron ocho respuestas.

    El turno corría DENTRO del hilo que recibe los webhooks: mientras la IA
    pensaba, el servidor no oía nada, y cada mensaje entraba solo cuando el
    anterior ya estaba contestado.
    """

    def test_lo_que_llega_mientras_piensa_se_junta_en_el_turno_siguiente(self):
        import threading

        vistos = []
        pensando = threading.Event()
        sigue = threading.Event()

        def atender(m):
            vistos.append(m)
            if len(vistos) == 1:
                pensando.set()
                sigue.wait(2)  # la IA tardando

        async def corre():
            a = Agrupador(atender, espera_s=0.02, tope_s=1)
            await a.recibir(msg("Preciso no tenia una regla mejor", "w1"))
            await asyncio.to_thread(pensando.wait, 2)
            # Mientras piensa el primero, llegan tres más: el servidor los oye.
            await a.recibir(msg("O mi fondo no cuadra", "w2"))
            await a.recibir(msg("Si mira me da como esta foto", "w3"))
            await a.recibir(msg("Cody Nala", "w4"))
            sigue.set()
            await asyncio.sleep(0.3)

        asyncio.run(corre())
        assert len(vistos) == 2, "contestó más de dos veces a una ráfaga"
        assert (
            vistos[1].text
            == "O mi fondo no cuadra\nSi mira me da como esta foto\nCody Nala"
        )

    def test_mientras_piensa_el_servidor_sigue_oyendo(self):
        """Antes, un turno de 10 s dejaba al servidor sordo 10 s (y Meta
        reenviaba el audio porque no le contestábamos)."""
        import threading
        import time

        libre = threading.Event()

        def atender(_m):
            libre.wait(2)

        async def corre():
            a = Agrupador(atender, espera_s=0.01)
            await a.recibir(msg("hola", "w1"))
            await asyncio.sleep(0.05)  # ya está pensando, en su hilo
            inicio = time.monotonic()
            await a.recibir(msg("otra cosa", "w2"))
            tardo = time.monotonic() - inicio
            libre.set()
            await a.detener()
            return tardo

        assert asyncio.run(corre()) < 0.1

    def test_la_ventana_es_calma_y_no_un_sleep_fijo(self):
        """Mientras siga escribiendo se espera; con el tope, se contesta igual."""
        vistos = []

        async def corre():
            a = Agrupador(vistos.append, espera_s=0.05, tope_s=0.15)
            for i in range(12):  # escribe sin parar durante ~0.24 s
                await a.recibir(msg(f"linea {i}", f"w{i}"))
                await asyncio.sleep(0.02)
            await asyncio.sleep(0.3)

        asyncio.run(corre())
        assert 2 <= len(vistos) <= 3, "o no respetó el tope o no juntó nada"
        assert sum(len(m.text.split("\n")) for m in vistos) == 12, "se perdió una línea"

    def test_el_primer_mensaje_no_espera(self):
        """La apertura es fija y sale al instante: eso no se toca."""
        import time

        cuando = []

        async def corre():
            a = Agrupador(
                lambda m: cuando.append(time.monotonic()),
                espera_s=5,
                inmediato=lambda m: True,
            )
            inicio = time.monotonic()
            await a.recibir(msg("Hola"))
            await asyncio.sleep(0.2)
            await a.detener()
            return inicio

        inicio = asyncio.run(corre())
        assert cuando and cuando[0] - inicio < 0.2

    def test_la_foto_el_audio_y_el_texto_van_en_el_mismo_turno(self):
        """El audio se transcribe DENTRO del turno: juntos, se contesta con él
        ya oído, y no «¡Gracias por la foto!» dos veces antes de oírlo."""
        vistos = []

        def pieza(kind, n):
            return MediaRef(kind=kind, media_id=n, mime_type="x")

        async def corre():
            a = Agrupador(vistos.append, espera_s=0.05)
            await a.recibir(msg("Cody Nala", "w1"))
            await a.recibir(msg(None, "w2", [pieza("image", "f1")]))
            await a.recibir(msg(None, "w3", [pieza("audio", "a1")]))
            await asyncio.sleep(0.2)

        asyncio.run(corre())
        assert len(vistos) == 1
        assert [x.kind for x in vistos[0].media] == ["image", "audio"]

    def test_cada_mensaje_original_viaja_en_partes(self):
        """Para guardarlos y copiarlos a Chatwoot uno por uno, como los escribió."""
        junto = fundir([msg("a", "w1"), msg("b", "w2")])
        assert [p.external_message_id for p in junto.partes] == ["w1", "w2"]
