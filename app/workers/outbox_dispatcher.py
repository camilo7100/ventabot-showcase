"""Despachador de la outbox: lo único del sistema que habla con Meta al enviar.

POR QUÉ EXISTE ESTA PIEZA
=========================
El grafo NO envía mensajes. Escribe una fila en `outbox` y termina. Este
proceso la lee y la envía. Suena a vuelta innecesaria, pero resuelve tres
problemas que si no te muerden todos:

1. ATOMICIDAD. El cambio de estado del pedido y el aviso al cliente se escriben
   en la misma transacción. No existe el caso "cobré pero no avisé" ni el
   inverso.

2. REINTENTOS. Si la API de Meta está caída, el mensaje se queda en la tabla y
   se reintenta con espera creciente. Sin outbox, se perdería.

3. LA VENTANA DE 24 HORAS. Este es EL sitio donde se decide "texto libre o
   plantilla". Si esa decisión estuviera repartida por el código, tarde o
   temprano alguien enviaría texto libre fuera de ventana y Meta lo rechazaría
   con el error 131047.

En la Fase 1 corre como una tarea de fondo dentro de FastAPI: simple y
suficiente. En la Fase 6 se saca a su propio proceso con arq.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging

from app.domain.models import OutboundMessage, conversation_id
from app.domain.ports import TokenDelCanalCaducado
from app.infra.logging import log_conversacion

log = logging.getLogger("ventabot.outbox")

#: Cada cuánto se vuelve a mirar un mensaje que espera a que se abra la
#: ventana. Cinco minutos: la ventana se abre cuando la clienta escribe, y
#: cinco minutos de retraso en responderle a alguien que acaba de escribir es
#: aceptable. Más corto sería mirar la base de datos sin motivo.
ESPERA_VENTANA_S = 300

#: Cuánto se espera DESPUÉS de mandar un archivo, antes de mandar el siguiente
#: mensaje de la misma conversación.
#:
#: ════════════════════════════════════════════════════════════════════════
#: POR QUÉ HACE FALTA
#: ════════════════════════════════════════════════════════════════════════
#: Meta no recibe el archivo: recibe una URL y lo baja de nuestro servidor.
#: Un video de 3,5 MB tarda en bajarse; un texto sale al instante. Mandarlos
#: seguidos NO garantiza que lleguen en ese orden: el 20/09 la presentación
#: salió «video, video, foto+pregunta» y a la clienta le llegó la pregunta en
#: medio del álbum, porque la foto (136 KB) adelantó a los videos.
#:
#: No hay forma de preguntarle a Meta «¿ya llegó?» sin montar un webhook de
#: estados. Esperar un poco tras cada archivo es la solución simple que de
#: verdad ordena la ráfaga, y el coste es que la conversación tarda unos
#: segundos más en terminar de contar lo que está contando.
#: 3 s parejos: lo justo para que el archivo se adelante al texto que viene
#: detrás, sin que la conversación se sienta lenta. Con 6 s por video la
#: presentación tardaba 16 s en salir entera y parecía que el bot se había
#: caído (Camilo, 20/09). NADA se descarta ni se salta: solo se ordena.
ESPERA_TRAS_ARCHIVO_S = dict.fromkeys(("video", "image", "audio", "document"), 3.0)


class OutboxDispatcher:
    def __init__(
        self,
        outbox,
        canales: dict,
        conversaciones=None,
        intervalo_s: float = 1.0,
        lote: int = 20,
        avisos=None,
        informar=None,
        copiar=None,
        anotar=None,
    ) -> None:
        self._outbox = outbox
        #: `copiar(conv, m)`: lo programado, a Chatwoot cuando sale de verdad.
        self._copiar = copiar
        #: `anotar(conv, texto)`: una nota privada en Chatwoot.
        self._anotar = anotar
        #: `informar(conv, texto, motivo, definitivo)`: lo que NO le llegó a la
        #: clienta, a Chatwoot (nota) y al celular (16/10). Chatwoot lo muestra
        #: como enviado apenas se encola: sin esto, no se sabría que no salió.
        self._informar = informar
        #: Los que ya se informaron como «en espera» (para no repetir la nota
        #: cada 5 minutos mientras la ventana sigue cerrada).
        self._canales = canales  # {"whatsapp": adapter, "instagram": ...}
        self._conv = conversaciones
        self._avisos = avisos
        self._intervalo = intervalo_s
        self._lote = lote
        self._tarea: asyncio.Task | None = None
        self._parar = asyncio.Event()
        self.enviados = 0
        self.fallidos = 0
        #: Para no repetir 5 veces el mismo aviso de token caducado.
        self._aviso_token_dado = False
        #: Idem para el aviso de ventana cerrada, que puede durar días.
        self._aviso_ventana_dado = False
        #: Mensajes que no se pudieron mandar porque la ventana está cerrada.
        #: No son fallos: siguen vivos en la cola.
        self.esperando = 0
        self._en_espera_informados: set[str] = set()

    # -- ciclo de vida ------------------------------------------------------

    def arrancar(self) -> None:
        self._parar.clear()
        self._tarea = asyncio.create_task(self._bucle(), name="outbox-dispatcher")
        log.info("despachador de outbox arrancado (cada %.1fs)", self._intervalo)

    async def detener(self) -> None:
        self._parar.set()
        if self._tarea:
            self._tarea.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._tarea
        log.info(
            "despachador detenido (%s enviados, %s fallidos)",
            self.enviados,
            self.fallidos,
        )

    async def _bucle(self) -> None:
        while not self._parar.is_set():
            try:
                await self.despachar_una_vez()
            except Exception:
                log.exception("error en el bucle del despachador")
            await asyncio.sleep(self._intervalo)

    # -- trabajo ------------------------------------------------------------

    async def despachar_una_vez(self) -> int:
        """Envía los pendientes. Devuelve cuántos salieron.

        Se puede llamar directamente desde los tests, sin bucle ni esperas.
        """
        pendientes = self._outbox.pending(self._lote)
        salieron = 0
        for i, m in enumerate(pendientes):
            if not await self._enviar(m):
                continue
            salieron += 1
            # Solo si detrás viene algo MÁS de la misma conversación: esperar
            # por el último archivo de la ráfaga no ordenaría nada y solo
            # retrasaría a la siguiente clienta.
            siguiente = pendientes[i + 1] if i + 1 < len(pendientes) else None
            espera = ESPERA_TRAS_ARCHIVO_S.get(m.kind, 0.0) if siguiente else 0.0
            if espera and siguiente.conversation_id == m.conversation_id:
                await asyncio.sleep(espera)
        return salieron

    def _avisar(self, titulo: str, detalle: str = "", clave: str = "") -> None:
        """Avisar nunca puede tumbar el envío del resto de la cola."""
        if self._avisos is None:
            return
        try:
            self._avisos.avisar(titulo, detalle, clave)
        except Exception as exc:  # pragma: no cover - avisar es lo menos crítico
            log.warning("no se pudo avisar (%s)", exc)

    @staticmethod
    def _llamar(hacer, *args) -> None:
        """Chatwoot es lo de menos: si falla, el envío sigue igual."""
        if hacer is None:
            return
        try:
            hacer(*args)
        except Exception as exc:  # pragma: no cover - el CRM nunca tumba nada
            log.warning("no se pudo copiar a Chatwoot (%s)", exc)

    def _informar_que_no_llego(
        self, conv_id: str, m: OutboundMessage, motivo: str, *, definitivo: bool = True
    ) -> None:
        """Informar nunca puede tumbar el envío del resto de la cola."""
        if self._informar is None:
            return
        texto = m.text or (f"plantilla {m.template_name}" if m.template_name else "")
        try:
            self._informar(conv_id, texto or f"[{m.kind}]", motivo, definitivo)
        except Exception as exc:  # pragma: no cover - informar es lo de menos
            log.warning("no se pudo informar que no llegó (%s)", exc)

    async def _enviar(self, m: OutboundMessage) -> bool:
        # El mensaje trae su conversación. Antes se derivaba cortando el nombre
        # del canal ("whatsapp"[:2] -> "wh") y no coincidía con el "wa:" que usa
        # el resto del sistema: la ventana de 24 h se buscaba con una clave
        # inexistente y salía "cerrada" siempre.
        conv_id = m.conversation_id or conversation_id(m.channel, m.to)
        with log_conversacion(conv_id):
            canal = self._canales.get(m.channel.value)
            if canal is None:
                log.error("no hay canal configurado para %s", m.channel.value)
                self._outbox.mark_failed(m.idempotency_key, "canal no configurado")
                self.fallidos += 1
                return False

            # LA decisión de la ventana de 24 h, en un solo sitio del código.
            abierta = True
            if self._conv is not None:
                abierta = self._conv.ventana_abierta(conv_id)
                if not abierta and not m.template_name:
                    # NO es un fallo: es una espera. Meta lo rechazaría con el
                    # error 131047, y reintentarlo cinco veces solo consigue
                    # abandonarlo en diez minutos.
                    #
                    # Se pospone sin gastar intentos y sale solo en cuanto la
                    # clienta escriba, que es lo que reabre la ventana. Antes
                    # esto se enviaba igual, fallaba, y el mensaje se perdía
                    # en silencio: el peor final posible para un cobro.
                    self._outbox.posponer(
                        m.idempotency_key,
                        ESPERA_VENTANA_S,
                        "ventana de 24 h cerrada y sin plantilla",
                    )
                    if not self._aviso_ventana_dado:
                        self._aviso_ventana_dado = True
                        log.info(
                            "hay mensajes esperando a que la clienta escriba "
                            "(ventana de 24 h cerrada). Con plantillas aprobadas "
                            "saldrían ya: vb plantillas"
                        )
                    self.esperando += 1
                    if m.idempotency_key not in self._en_espera_informados:
                        self._en_espera_informados.add(m.idempotency_key)
                        self._informar_que_no_llego(
                            conv_id,
                            m,
                            "pasaron más de 24 h desde su último mensaje y WhatsApp "
                            "solo deja escribirle con plantilla. Sale solo si ella "
                            "vuelve a escribir; para escribirle ya, manda #asesora "
                            "si ella pidió una persona, o #retomar si fue una falla "
                            "nuestra",
                            definitivo=False,
                        )
                    return False

            if abierta and m.idempotency_key.startswith("retomar:"):
                # La disculpa a una atrasada, programada para las 8 a. m.,
                # sobra si ella ya volvió a escribir: la ventana está abierta y
                # el bot ya la está atendiendo (Jannet, 17/10).
                self._outbox.descartar(m.idempotency_key, "ya volvió a escribir")
                self._llamar(
                    self._anotar,
                    conv_id,
                    "🕗 La disculpa programada NO salió: ella volvió a escribir "
                    "antes y el bot ya la está atendiendo.",
                )
                return False

            try:
                # El envío es HTTP bloqueante; lo sacamos del hilo del bucle
                # para no congelar el resto del servidor.
                external_id = await asyncio.to_thread(
                    canal.send, m, ventana_abierta=abierta
                )
            except TokenDelCanalCaducado as exc:
                # Un solo aviso, con instrucciones. Antes salían cinco
                # warnings idénticos de httpx repartidos por diez minutos y
                # ninguno decía qué hacer.
                if not self._aviso_token_dado:
                    self._aviso_token_dado = True
                    log.error("=" * 62)
                    log.error("NO PUEDO RESPONDER: el token de Meta caducó.")
                    log.error("Los mensajes SÍ están llegando; lo que falla es")
                    log.error("el envío. El token temporal dura 24 horas.")
                    log.error("")
                    log.error("Arréglalo así:   vb token")
                    log.error("=" * 62)
                    self._avisar(
                        "VentaBot no puede responder",
                        "El token de Meta caducó o fue revocado. Arréglalo con: vb token",
                        clave="token",
                    )
                self._outbox.mark_failed(m.idempotency_key, str(exc))
                self.fallidos += 1
                return False
            except Exception as exc:
                log.warning("fallo al enviar: %s", exc)
                se_rindio = self._outbox.mark_failed(m.idempotency_key, str(exc))
                self.fallidos += 1
                if se_rindio:
                    self._informar_que_no_llego(
                        conv_id, m, f"no salió tras 5 intentos: {exc}"[:300]
                    )
                self._avisar(
                    "VentaBot: un mensaje no salió",
                    f"{type(exc).__name__}: {exc}"[:200],
                    clave="envio",
                )
                return False

            self._aviso_token_dado = False
            self._outbox.mark_sent(m.idempotency_key, external_id)
            if m.copiar_al_salir:
                self._llamar(self._copiar, conv_id, m)
            if self._conv is not None:
                # Una foto sin pie dejaba una línea vacía en el historial: al
                # releerlo (o al repasarlo) parecía un turno en blanco.
                texto = m.text or (f"[{m.kind}]" if m.kind != "text" else "")
                self._conv.registrar_saliente(
                    conv_id,
                    m.channel.value,
                    texto,
                    external_id,
                    payload=(
                        {"kind": m.kind, "media_url": m.media_url}
                        if m.media_url
                        else None
                    ),
                )
            self.enviados += 1
            log.info("enviado (%s)", external_id)
            return True
