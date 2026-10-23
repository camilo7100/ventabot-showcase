"""Juntar la ráfaga de mensajes antes de contestar. UNA respuesta, no cuatro.

════════════════════════════════════════════════════════════════════════════
EL PROBLEMA, CON UNA CONVERSACIÓN DE VERDAD
════════════════════════════════════════════════════════════════════════════
Nadie escribe por WhatsApp como se escribe un correo. Esto es textual de una
clienta de Lía, cuatro mensajes seguidos en menos de un minuto:

    «Son dos huellitas»
    «Una huellita negra por mi panterita»
    «Y la otra huellita no se jajaja»
    «Tienes referencias de negro con otra huella»

Eso es UNA pregunta. Lía leyó las cuatro líneas y contestó una vez, con las
fotos de anillos negros combinados. El bot contesta cuatro veces, y la tercera
respuesta ya está mal escrita antes de salir, porque se redactó sin haber leído
la cuarta línea.

De todas las cosas que delatan que del otro lado hay una máquina, esta es la
primera — antes que el tono, antes que los emojis y antes que el modelo.

════════════════════════════════════════════════════════════════════════════
CÓMO (rehecho el 27/09 con la conversación de prueba del 26/09)
════════════════════════════════════════════════════════════════════════════
No es un `sleep` fijo. Son tres reglas:

1. UN TURNO A LA VEZ POR CONVERSACIÓN, Y FUERA DEL HILO DEL SERVIDOR. Antes el
   turno —que tarda lo que tarde la IA, 3 a 12 s— corría DENTRO del hilo que
   recibe los webhooks, y el servidor entero se quedaba sordo mientras tanto.
   El 26/09 se reenviaron 8 mensajes en el mismo segundo y entraron de a uno,
   cada uno cuando terminaba el turno anterior: 8 respuestas. Meta hasta
   reenvió un audio porque no le contestamos a tiempo. Ahora el turno corre en
   un hilo aparte (UNO solo, igual que antes: nunca dos turnos a la vez) y el
   servidor sigue recibiendo.

2. LO QUE LLEGA MIENTRAS SE ATIENDE, SE JUNTA. Los mensajes que entran durante
   un turno esperan y se atienden juntos en el siguiente, en el orden en que
   se escribieron: la foto, el audio (que se transcribe antes de contestar) y
   el texto van en el MISMO turno.

3. UNA VENTANA CORTA Y CON TOPE. Antes de atender se espera a que pasen
   `espera_s` segundos SIN que llegue nada (cada mensaje nuevo la reinicia),
   pero nunca más de `tope_s` desde el primero: a quien escribe sin parar
   igual se le contesta.

El PRIMER mensaje de una conversación no espera (`inmediato`): la apertura es
fija, sale al instante, y no se toca (Camilo, 27/09).

Con `espera_s = 0` se atiende sin ventana, pero con las reglas 1 y 2.

════════════════════════════════════════════════════════════════════════════
QUÉ SE PIERDE SI EL PROCESO SE REINICIA
════════════════════════════════════════════════════════════════════════════
Lo que esté esperando en el buffer, igual que ya pasa con `BackgroundTasks`.
La ventana es de segundos, así que la exposición es de segundos. Por eso
`detener()` NO tira lo pendiente: lo atiende. Un reinicio no puede comerse el
mensaje de una clienta que acaba de escribir.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from concurrent.futures import ThreadPoolExecutor

from app.domain.models import InboundMessage

log = logging.getLogger("ventabot.agrupador")


def fundir(mensajes: list[InboundMessage]) -> InboundMessage:
    """Varios mensajes de una conversación, como si fueran uno.

    Se conserva el ÚLTIMO como base y se le pone el texto de todos en orden.
    El último y no el primero porque su `external_message_id` es el que Meta
    acaba de mandar: es el que la deduplicación ya marcó como visto, y el que
    tiene que ir en la clave de idempotencia de la respuesta.

    Las fotos se suman todas: si mandó el comprobante y luego la foto del
    anillo con la regla, las dos cosas hacen falta. Y los originales van en
    `partes`: cada uno se guarda y se copia a Chatwoot tal cual lo escribió.
    """
    if len(mensajes) == 1:
        return mensajes[0]

    ultimo = mensajes[-1]
    textos = [m.text.strip() for m in mensajes if (m.text or "").strip()]
    media = [pieza for m in mensajes for pieza in (m.media or [])]
    return ultimo.model_copy(
        update={
            # Con salto de línea y no con espacio: son frases distintas, y
            # pegarlas con un espacio inventa frases que nadie escribió
            # («…no sé jajaja Tienes referencias…»).
            "text": "\n".join(textos),
            "media": media,
            "partes": list(mensajes),
        }
    )


class Agrupador:
    """Atiende cada conversación de a un turno, juntando lo que llegue.

    `atender` es `Container.procesar_mensaje`: síncrono y lento (llama a la IA).
    Corre en UN hilo aparte, así que el servidor sigue recibiendo mientras
    tanto y nunca hay dos turnos a la vez, como siempre.

    `inmediato(m)` dice si ese mensaje se atiende sin ventana (el primero de
    una conversación). Sin él, todos esperan la ventana.
    """

    def __init__(
        self,
        atender,
        espera_s: float = 0.0,
        *,
        tope_s: float = 15.0,
        inmediato=None,
    ) -> None:
        self._atender = atender
        self._espera = espera_s
        self._tope = max(tope_s, espera_s)
        self._inmediato = inmediato
        self._pendientes: dict[str, list[InboundMessage]] = {}
        #: conversación -> (cuándo llegó el primero del lote, cuándo el último)
        self._reloj: dict[str, tuple[float, float]] = {}
        self._tareas: dict[str, asyncio.Task] = {}
        #: UN hilo: los turnos nunca se pisan, igual que cuando corrían en el
        #: hilo del servidor, pero ya no lo dejan sordo.
        self._hilo = ThreadPoolExecutor(max_workers=1, thread_name_prefix="turno")

    @property
    def activo(self) -> bool:
        return self._espera > 0

    async def recibir(self, m: InboundMessage) -> None:
        """Guarda el mensaje; si nadie atiende su conversación, empieza.

        Con ventana (`activo`), vuelve enseguida: el turno sale solo. Sin
        ventana, espera a que la conversación quede atendida, para que un
        `asyncio.run(recibir(m))` no deje nada a medias.
        """
        conv = m.conversation_id
        ahora = time.monotonic()
        self._pendientes.setdefault(conv, []).append(m)
        primero, _ = self._reloj.get(conv, (ahora, ahora))
        self._reloj[conv] = (primero, ahora)
        if conv in self._tareas:
            # Ya hay un turno en marcha (o esperando la calma): él se lo lleva.
            return
        tarea = asyncio.create_task(self._trabajar(conv), name=f"agrupador:{conv}")
        self._tareas[conv] = tarea
        if not self.activo:
            await asyncio.shield(tarea)

    async def _trabajar(self, conv: str) -> None:
        """Mientras haya algo pendiente: esperar la calma, atender, repetir."""
        try:
            primera_vuelta = True
            while self._pendientes.get(conv):
                pendientes = self._pendientes[conv]
                sin_ventana = (
                    primera_vuelta
                    and len(pendientes) == 1
                    and self._es_inmediato(pendientes[0])
                )
                primera_vuelta = False
                if not sin_ventana:
                    await self._esperar_la_calma(conv)
                lote = self._pendientes.pop(conv, [])
                self._reloj.pop(conv, None)
                if lote:
                    if len(lote) > 1:
                        log.info("juntados %s mensajes en uno · %s", len(lote), conv)
                    await asyncio.get_running_loop().run_in_executor(
                        self._hilo, self._servir, lote
                    )
        except asyncio.CancelledError:
            # Solo lo cancela `detener()`, que se encarga de lo pendiente.
            pass
        finally:
            self._tareas.pop(conv, None)

    def _es_inmediato(self, m: InboundMessage) -> bool:
        if self._inmediato is None:
            return False
        try:
            return bool(self._inmediato(m))
        except Exception:
            # Ante la duda, con ventana: es lo que menos daño hace.
            log.warning("no se supo si era el primer mensaje · %s", m.conversation_id)
            return False

    async def _esperar_la_calma(self, conv: str) -> None:
        """Hasta `espera_s` sin mensajes nuevos, o `tope_s` desde el primero."""
        if not self.activo:
            return
        while True:
            ahora = time.monotonic()
            primero, ultimo = self._reloj.get(conv, (ahora, ahora))
            falta = min(ultimo + self._espera, primero + self._tope) - ahora
            if falta <= 0:
                return
            await asyncio.sleep(falta)

    def _servir(self, lote: list[InboundMessage]) -> None:
        """Atiende el lote. Nunca deja escapar una excepción.

        `atender` ya trae su propia red (`Container.procesar_mensaje`), pero
        esto corre suelto en un hilo: una excepción aquí no la vería nadie, y
        el aviso del log es lo único que puede decirle a una persona que esta
        conversación se quedó sin contestar.
        """
        try:
            self._atender(fundir(lote))
        except Exception:
            log.exception(
                "no se pudo atender un lote de %s mensaje(s) · %s",
                len(lote),
                lote[-1].conversation_id,
            )

    def ocupada(self, conv: str) -> bool:
        """¿Hay un turno en marcha o mensajes esperando en esta charla? Solo
        lectura: los recordatorios (04/10) no le escriben mientras tanto."""
        return conv in self._tareas or bool(self._pendientes.get(conv))

    async def en_el_hilo(self, funcion):
        """Corre `funcion` en el MISMO hilo de los turnos (nunca a la vez que uno).

        Lo usa el reintento de turnos pendientes: si corriera aparte, podría
        contestarle a una clienta al mismo tiempo que un turno normal.
        """
        return await asyncio.get_running_loop().run_in_executor(self._hilo, funcion)

    async def detener(self) -> None:
        """Atiende lo que quede esperando. Un reinicio no se come un mensaje."""
        tareas = list(self._tareas.values())
        for tarea in tareas:
            tarea.cancel()
        for tarea in tareas:
            with contextlib.suppress(BaseException):
                await tarea
        self._tareas.clear()
        bucle = asyncio.get_running_loop()
        for lote in list(self._pendientes.values()):
            if lote:
                await bucle.run_in_executor(self._hilo, self._servir, lote)
        self._pendientes.clear()
        self._reloj.clear()
