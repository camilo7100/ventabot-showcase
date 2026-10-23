"""Vigila que los mensajes SIGAN ENTRANDO, que es lo único que importa.

════════════════════════════════════════════════════════════════════════════
POR QUÉ EXISTE
════════════════════════════════════════════════════════════════════════════
El 20/09 una clienta escribió y su mensaje **nunca llegó al bot**. Tuvo que
repetirlo tres minutos después; en el registro de webhooks solo está la
segunda copia. Desde el PC todo se veía bien —ngrok corriendo, su API local
contestando, el servidor perfecto— y aun así se perdió una conversación.

Un mensaje perdido es una venta perdida, y no deja rastro: ni error, ni
excepción. Solo una clienta que escribió y a la que nadie contestó.

════════════════════════════════════════════════════════════════════════════
POR QUÉ NO SE MIDE PIDIÉNDOLE `/health` A LA URL PÚBLICA
════════════════════════════════════════════════════════════════════════════
Fue lo primero que se intentó, y dio **falsas alarmas** la misma noche: el
registro gritaba «el túnel no responde» mientras los mensajes entraban con
toda normalidad, un minuto antes y un minuto después.

La razón es que esa prueba no mide lo que parece. Sale de este PC, da la vuelta
por el borde de ngrok y vuelve a entrar aquí; que ese viaje falle dice algo de
la salida de esta máquina —o de los límites del plan gratuito— y nada de si
Meta puede entregar. Y una alarma que se equivoca es peor que no tener alarma:
enseña a ignorarla, y el día que sea verdad nadie la va a mirar.

════════════════════════════════════════════════════════════════════════════
LO QUE SÍ SE MIDE
════════════════════════════════════════════════════════════════════════════
La evidencia directa: **Meta acusa recibo de todo lo que se manda**, en
segundos («sent», «delivered», «read»), y esos acuses entran por el mismo
webhook que los mensajes de las clientas.

Así que la pregunta es una sola, y no se puede falsear:

    ¿acabamos de mandar algo y no ha vuelto NADA?

Si el bot lleva minutos sin recibir ni un acuse después de haber respondido, el
camino de entrada está roto. Si no se ha mandado nada —de madrugada, sin
clientas—, no hay nada que concluir y el vigía se calla.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from datetime import UTC, datetime, timedelta

log = logging.getLogger("ventabot.tunel")

#: Cada cuánto se mira. No cuesta nada: son dos lecturas locales.
CADA_S = 120.0
#: Cuánto puede tardar un acuse de Meta antes de que sea raro. Llegan en
#: segundos; tres minutos es holgado hasta con la red a rastras.
MARGEN = timedelta(minutes=3)
#: Si lo último que mandamos es más viejo que esto, no se concluye nada: los
#: acuses de hace media hora ya no tienen por qué seguir llegando.
VENTANA_DE_ACTIVIDAD = timedelta(minutes=15)
#: Dos comprobaciones seguidas en falso antes de gritar. Una sola puede caer
#: justo en el hueco entre el envío y el acuse.
FALLOS_PARA_AVISAR = 2


class VigiaDelTunel:
    """Se entera de que no está entrando nada, y lo dice. No toca nada.

    `ultimo_enviado` y `ultimo_webhook` devuelven un datetime con zona (o
    None). Se inyectan para que este worker no conozca ni la base ni el
    archivo de registro.
    """

    def __init__(
        self,
        ultimo_enviado,
        ultimo_webhook,
        *,
        avisos=None,
        cada_s: float = CADA_S,
    ) -> None:
        self._ultimo_enviado = ultimo_enviado
        self._ultimo_webhook = ultimo_webhook
        self._avisos = avisos
        self._cada = cada_s
        self._parar = asyncio.Event()
        self._tarea: asyncio.Task | None = None
        #: Comprobaciones seguidas en las que no volvió nada.
        self.fallos = 0
        #: Ya se avisó de esta caída: no se repite la alarma cada 2 minutos.
        self._avisado = False

    def arrancar(self) -> None:
        self._tarea = asyncio.create_task(self._bucle())

    async def detener(self) -> None:
        self._parar.set()
        if self._tarea is not None:
            self._tarea.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._tarea

    async def _bucle(self) -> None:
        while not self._parar.is_set():
            with contextlib.suppress(asyncio.CancelledError):
                await asyncio.sleep(self._cada)
            if self._parar.is_set():
                return
            try:
                await asyncio.to_thread(self.mirar_una_vez)
            except Exception:  # pragma: no cover - vigilar no tumba nada
                log.exception("el vigía falló")

    def mirar_una_vez(self) -> bool | None:
        """True si entra todo, False si no entra nada, None si no se sabe.

        None es una respuesta legítima y la más frecuente: sin haber mandado
        nada hace poco, la falta de acuses no significa nada.
        """
        ahora = datetime.now(UTC)
        enviado = self._cuando(self._ultimo_enviado)
        if enviado is None or ahora - enviado > VENTANA_DE_ACTIVIDAD:
            return None  # nada que concluir

        webhook = self._cuando(self._ultimo_webhook)
        # Meta acusa recibo de lo que mandamos. Si el último webhook es
        # anterior a ese envío y ya pasó el margen, no está entrando nada.
        entra = webhook is not None and webhook >= enviado - timedelta(seconds=5)
        if not entra and ahora - enviado <= MARGEN:
            return None  # todavía es pronto para el acuse

        if entra:
            if self.fallos:
                log.info("vuelven a entrar los mensajes")
                self._avisar("VentaBot: ya entran los mensajes", "El camino se arregló.")
            self.fallos = 0
            self._avisado = False
            return True

        self.fallos += 1
        log.warning(
            "no ha entrado NINGÚN webhook desde que se respondió a las %s",
            enviado.astimezone().strftime("%H:%M"),
        )
        if self.fallos >= FALLOS_PARA_AVISAR and not self._avisado:
            self._avisado = True
            self._gritar(enviado)
        return False

    @staticmethod
    def _cuando(fuente) -> datetime | None:
        """Lo que devuelva la fuente, con zona. Un fallo al leer no concluye."""
        try:
            valor = fuente()
        except Exception:  # pragma: no cover - una lectura rota no da alarma
            return None
        if valor is None:
            return None
        return valor if valor.tzinfo else valor.replace(tzinfo=UTC)

    def _gritar(self, enviado: datetime) -> None:
        log.error("=" * 62)
        log.error("NO ESTÁN ENTRANDO LOS MENSAJES.")
        cuando = enviado.astimezone().strftime("%H:%M")
        log.error("Se respondió a las %s y Meta no ha acusado", cuando)
        log.error("recibo de nada: lo que escriban las clientas SE PIERDE.")
        log.error("")
        log.error("Arréglalo así: cierra la ventana «VentaBot - TUNEL»")
        log.error("y vuelve a abrir ENCENDER-BOT.cmd")
        log.error("=" * 62)
        self._avisar(
            "VentaBot: no están entrando los mensajes",
            "Meta no acusa recibo. Reinicia con ENCENDER-BOT.cmd",
        )

    def _avisar(self, titulo: str, detalle: str) -> None:
        if self._avisos is None:
            return
        with contextlib.suppress(Exception):
            self._avisos.avisar(titulo, detalle, "tunel")
