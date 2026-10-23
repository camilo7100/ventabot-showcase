"""Contenedor de dependencias: el ÚNICO lugar donde se eligen implementaciones.

Aquí es donde "cambiar de backend" es cambiar una variable de entorno. Todo el
resto del sistema solo conoce Protocols.

    REPOSITORY_BACKEND=memory   -> pedidos y catálogo en RAM (Fase 1)
    REPOSITORY_BACKEND=sheets   -> Fase 2
    REPOSITORY_BACKEND=sql      -> Fase 6

    CHANNEL_BACKEND=console     -> imprime en la terminal (pruebas sin Meta)
    CHANNEL_BACKEND=whatsapp    -> envía de verdad

    LLM_BACKEND=fake | ollama
    PAYMENT_BACKEND=fake | bold

Ojo con una asimetría deliberada: los datos de NEGOCIO pueden estar en RAM
durante la Fase 1, pero los del TRANSPORTE (deduplicación, outbox, historial,
checkpoints) van a SQLite desde ya. Si la deduplicación viviera en memoria, un
reinicio haría que Meta reenviara los webhooks y el cliente recibiera la misma
respuesta dos veces.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from app.adapters.channels.console import ConsoleChannel
from app.adapters.channels.whatsapp import WhatsAppAdapter
from app.adapters.llm.ollama_client import FakeLLM, OllamaLLM
from app.adapters.payments.bold import BoldGateway, FakeGateway
from app.adapters.repositories.memory import (
    InMemoryCustomerRepository,
    InMemoryOrderRepository,
    InMemoryPaymentRepository,
    InMemoryProductRepository,
)
from app.adapters.repositories.sqlite_store import (
    SqliteContexto,
    SqliteConversaciones,
    SqliteCustomerRepository,
    SqliteDB,
    SqliteDecisiones,
    SqliteIdempotencyStore,
    SqliteOrderRepository,
    SqliteOutbox,
)
from app.domain.models import (
    Channel,
    InboundMessage,
    OutboundMessage,
    Product,
    conversation_id,
    etiqueta_de_mensaje,
)
from app.domain.numeros_propios import solo_respuesta_inmediata
from app.domain.pricing import formatear_cop
from app.domain.tallas import talla_texto
from app.graph.build import Deps, build_graph
from app.infra.centro_de_mando import NOMBRE_DE_LA_HOJA, filas_del_centro_de_mando
from app.infra.logging import log_conversacion
from app.infra.settings import Settings, get_settings
from app.infra.trazas import anotar, etiquetar, traza
from app.workers.agrupador import Agrupador
from app.workers.outbox_dispatcher import OutboxDispatcher

#: Cuándo arrancó ESTE proceso. Lo publica `/health` y lo enseña el centro de
#: mando («lleva 3 h atendiendo»). Vive aquí porque es lo único que los dos
#: pueden importar sin darse la vuelta el uno al otro.
ARRANCADO = datetime.now(UTC)

log = logging.getLogger("ventabot.container")

CATALOGO_FALLBACK = [
    Product(
        sku="CAM-001",
        nombre="Camiseta de prueba",
        precio_cop=85_000,
        dias_produccion=5,
        descripcion="fallback si falta data/catalogo.csv",
    ),
]


def cargar_catalogo(s: Settings | None = None) -> list[Product]:
    """El catálogo sale de data/catalogo.csv, un archivo real versionado en Git.

    En la Fase 2 el mismo Protocol lo servirá desde Google Sheets, y en la
    Fase 6 desde SQL, sin tocar nada más.
    """
    from app.adapters.repositories.csv_files import cargar_catalogo_csv

    ruta = (s or get_settings()).catalogo_csv
    if not ruta.exists():
        log.warning("no existe %s; usando catálogo de emergencia", ruta)
        return CATALOGO_FALLBACK
    return cargar_catalogo_csv(ruta)


class FakeMedia:
    """MediaPort de prueba. En la Fase 5 se cambia por descarga + S3."""

    def download(self, media_id_or_url: str) -> bytes:
        return b"\xff\xd8\xff\xe0fake-jpeg"

    def store(self, data: bytes, *, filename: str) -> str:
        return f"https://storage.test/{filename}"


@dataclass
class Container:
    settings: Settings
    db: SqliteDB
    products: Any
    customers: Any
    orders: Any
    payments: Any
    gateway: Any
    llm: Any
    media: Any
    idempotency: SqliteIdempotencyStore
    outbox: SqliteOutbox
    conversaciones: SqliteConversaciones
    #: Por dónde se avisa que algo se rompió. None = solo queda en el log.
    avisos: Any = None
    canales: dict = field(default_factory=dict)
    whatsapp: Any = None
    graph: Any = None
    #: El gestor conversacional. Es quien contesta desde la Fase 3.
    bot: Any = None
    #: El espejo en Chatwoot. None = no se copia nada y el bot es idéntico.
    crm: Any = None
    #: El ERP del negocio (Google Sheets). None = no se escribe nada.
    erp: Any = None
    #: La venta a Meta al confirmar un abono (13/10). None = no se manda nada.
    conversiones: Any = None
    #: Un candado por conversación para las acciones que llegan de Chatwoot:
    #: dos webhooks casi a la vez no pueden mover el mismo pedido dos veces.
    _candados: dict = field(default_factory=dict)
    _candados_lock: Any = field(default_factory=threading.Lock)
    contexto: Any = None
    dispatcher: OutboxDispatcher | None = None
    #: El Excel de ventas que se actualiza solo. None = apagado.
    ventas: Any = None
    #: Le escribe a quien no abonó. None = apagado (lo normal).
    recordador: Any = None
    #: Mira desde INTERNET que el túnel siga abierto. Sin él, un túnel caído
    #: se lleva los mensajes en silencio (20/09).
    vigia: Any = None
    #: Junta la ráfaga de mensajes antes de contestar. Se construye siempre;
    #: con `AGRUPAR_SEGUNDOS=0` no retiene nada y el camino es el de siempre.
    agrupador: Any = None
    #: La tabla de análisis: una fila por pedido (`app.domain.analitica`).
    analitica: Any = None
    #: Los colores de circón editables en el panel (`SqliteColores`).
    colores: Any = None
    #: La vista cuadrada de la huellita (`RenderDeHuellitas`). El panel de
    #: Colores la usa para «Ver» un tinte antes de guardarlo.
    render: Any = None
    #: El registro de decisiones (capa, confianza, contexto, costo). None =
    #: apagado con `REGISTRAR_DECISIONES=false`.
    decisiones: Any = None
    #: Lo último que dijo Meta de la plantilla de emergencia: (cuándo, la que
    #: está aprobada o None).
    _emergencia: Any = None
    _asesora: Any = None

    # -- casos de uso -------------------------------------------------------

    async def recibir_mensaje(self, m: InboundMessage) -> None:
        """La puerta de entrada del webhook. Puede esperar por si sigue escribiendo.

        El webhook llama a ESTO y no a `procesar_mensaje` porque una clienta
        manda cuatro mensajes seguidos que son una sola pregunta, y contestarle
        cuatro veces es lo que más delata que del otro lado hay una máquina.
        Ver `app/workers/agrupador.py`.
        """
        m = self._misma_clienta(m)
        if self.agrupador is None:
            self.procesar_mensaje(m)
            return
        await self.agrupador.recibir(m)

    def _misma_clienta(self, m: InboundMessage) -> InboundMessage:
        """La clienta que entró SIN número sigue en SU conversación cuando llega con él.

        Desde el 14/10 Meta manda a quien usa nombre de usuario solo con su
        identificador nuevo (`from_user_id`), sin teléfono. Cuando le
        contestamos, los mensajes siguientes ya traen el teléfono: sin esto
        quedaría partida en dos conversaciones y el bot le volvería a saludar.
        """
        bsuid = (m.raw or {}).get("from_user_id")
        if m.channel.value != "whatsapp" or not bsuid or m.sender_id == bsuid:
            return m
        if self.customers.get_by_channel_user("whatsapp", bsuid) is None:
            return m
        return m.model_copy(
            update={
                "sender_id": bsuid,
                "conversation_id": conversation_id(m.channel, bsuid),
            }
        )

    @traza("turno")
    def procesar_mensaje(self, m: InboundMessage) -> list[OutboundMessage]:
        """Atiende un mensaje. Pase lo que pase, la clienta recibe algo.

        ════════════════════════════════════════════════════════════════════
        POR QUÉ ESTO ESTÁ ENVUELTO EN UN try
        ════════════════════════════════════════════════════════════════════
        Esto lo llama el webhook con `BackgroundTasks`, DESPUÉS de haber
        contestado 200 a Meta y DESPUÉS de haber marcado el mensaje como
        procesado. Así que una excepción aquí no es un error visible: es
        SILENCIO. Meta no reintenta (ya le dijimos que sí), la deduplicación
        descartaría el reintento de todas formas, y la clienta se queda
        mirando un chat en el que nadie contestó nunca.

        Probándolo con la base de datos caída a mitad de turno, eso es
        exactamente lo que pasaba. Un fallo puntual —el disco, el modelo, un
        campo raro— no puede costar una venta y además no dejar rastro.

        Lo que se hace en cambio: se avisa en el log, se le dice a la clienta
        la verdad en una línea, y se escala a una persona. El mensaje de
        auxilio se construye a mano y sin tocar nada más, porque lo que esté
        roto puede ser justo lo que haría falta para construirlo bien.
        """
        try:
            return self._atender(m)
        except Exception as exc:
            log.exception("el turno falló entero · conversacion=%s", m.conversation_id)
            self._registrar_fallo(m, exc)
            return self._pedir_auxilio(m)

    def _registrar_fallo(self, m: InboundMessage, exc: Exception) -> None:
        """Un turno caído también es una decisión: cuenta como error."""
        if self.decisiones is None:
            return
        try:
            from datetime import UTC, datetime

            from app.domain.decisiones import RegistroDeDecision, huella_conversacion

            self.decisiones.guardar(
                RegistroDeDecision(
                    ts=datetime.now(UTC).isoformat(timespec="seconds"),
                    conversacion=huella_conversacion(m.conversation_id),
                    routing_layer="error",
                    motivo="turno_caido",
                    escalated=False,
                    escalation_reason="",
                    intent="",
                    action="",
                    verdict="",
                    confidence="",
                    context_source="",
                    active_orders=0,
                    closed_orders=0,
                    historical_lookup=False,
                    candidate_orders=0,
                    human_review=True,
                    image="",
                    corrected=False,
                    model_said="",
                    error=type(exc).__name__,
                )
            )
        except Exception:  # pragma: no cover - el registro no rompe nada
            log.debug("no se pudo registrar el fallo del turno")

    #: Lo único que se le dice cuando el turno se cayó. Honesto y corto: no
    #: promete nada que dependa de que el sistema funcione, salvo que una
    #: persona va a entrar — y de eso se encarga el log y la etiqueta del CRM.
    AUXILIO = (
        "Uy, se me enredó algo de mi lado 🙈 Ya le avisé a una personita del "
        "equipo para que te escriba por aquí en un momentico 💓"
    )

    def _pedir_auxilio(self, m: InboundMessage) -> list[OutboundMessage]:
        """Un mensaje a mano, sin pasar por el gestor ni por el contexto."""
        aviso = OutboundMessage(
            channel=m.channel,
            to=m.sender_id,
            kind="text",
            text=self.AUXILIO,
            conversation_id=m.conversation_id,
            idempotency_key=f"auxilio:{m.external_message_id}",
        )
        # El turno se cayó antes de copiar lo que ella escribió.
        self._copiar_entrante_al_crm(m)
        try:
            self.enviar_a_la_clienta(m.conversation_id, aviso)
        except Exception:
            # Si la outbox también está caída no queda nada que hacer por la
            # clienta desde aquí. Lo que NO se puede es tirar la excepción
            # hacia arriba y perder el aviso del log, que es lo único que va a
            # decirle a alguien que esta conversación necesita una persona.
            log.exception("tampoco se pudo encolar el aviso de auxilio")
        return [aviso]

    def _atender(self, m: InboundMessage) -> list[OutboundMessage]:
        """Corre el gestor conversacional y ENCOLA lo que haya que decir.

        No envía nada: escribe en la outbox y el despachador se encarga. Y
        devuelve una LISTA, porque una respuesta puede ser «texto + tres
        fotos + texto»: el techo de un mensaje por turno era la razón real de
        que las imágenes del catálogo no salieran nunca.

        ⚠️ EN PRODUCCIÓN, ANTES DE PROCESAR:
            adquirir un lock por conversación (Redis SET NX PX). Dos workers
            atendiendo la misma conversación a la vez se pisan el contexto.
        """
        from app.conversacion.salida import a_mensajes

        with log_conversacion(m.conversation_id):
            # Registra el entrante: abre la ventana de 24 h y guarda historial.
            # Si es una ráfaga, cada mensaje por separado, como los escribió.
            for parte in m.partes or [m]:
                self.conversaciones.registrar_entrante(
                    m.conversation_id,
                    m.channel.value,
                    m.sender_id,
                    parte.external_message_id,
                    parte.text,
                    parte.raw,
                )
                log.info("entra: %r", etiqueta_de_mensaje(parte.text, parte.media)[:80])
            if m.partes:
                log.info("  (%s mensajes, un solo turno)", len(m.partes))

            # La clienta tiene que existir antes de interpretar: de ella
            # cuelgan sus pedidos, y sin ellos no se puede resolver «el
            # segundo» ni saber si «ya pagué» es ambiguo.
            cliente = self.bot._mundo.asegurar_cliente(m.conversation_id)
            # Su nombre de WhatsApp, la primera vez (13/10): con él la saludan los
            # recordatorios («Hola Laura 💜» y no «Hola de nuevo»). No pisa uno
            # que ya esté guardado.
            if (m.sender_name or "").strip() and not (cliente.nombre or "").strip():
                self.customers.upsert(
                    cliente.model_copy(update={"nombre": m.sender_name.strip()[:80]})
                )
            # De qué anuncio llegó. Va antes de ver si la atiende una persona:
            # la venta se le cuenta al anuncio la cierre quien la cierre.
            self._anotar_anuncio(m)

            # Lo escribió hace más de 24 h y Meta lo entregó tarde (16/10: Ivonne
            # escribió el 9/10 y llegó el 15/10 en la noche): WhatsApp ya no deja
            # contestarle libre. Una respuesta quedaría en espera y saldría,
            # vieja, el día que vuelva a escribir. Se registra y se le avisa a Lía.
            if not self.conversaciones.ventana_abierta(m.conversation_id):
                self._llego_atrasado(m)
                return []

            # Si hay una persona atendiendo, el bot NO contesta encima: dos
            # voces en el mismo chat es lo que rompe la confianza de una venta.
            if self.bot._mundo.la_atiende_una_persona(m.conversation_id):
                log.info("no contesta: la atiende una persona")
                self._copiar_entrante_al_crm(m)
                return []

            # Solo reaccionó con un emoji (13/10): se ve en Chatwoot y no se le
            # contesta, salvo que sea el «sí» al resumen o a su nombre.
            if self._solo_reacciona(m):
                log.info("no contesta: solo reaccionó a un mensaje")
                self._copiar_entrante_al_crm(m)
                return []

            pago_antes = self._pago_por_verificar(m.conversation_id)
            turno = self.bot.ejecutar(
                m.conversation_id,
                m.text,
                self._media_para_el_bot(m) or None,
                # Cómo se llama en WhatsApp. Lía lo tiene delante en el chat y
                # por eso nunca se lo pregunta a ciegas; el bot tampoco debería
                # (ver `_proponer_su_nombre`).
                m.sender_name or "",
            )
            self._avisar_lo_importante(m, turno, pago_antes)

            for linea in turno.respuesta.traza:
                log.info("  %s", linea)
            self._guardar_decision(turno)

            mensajes = a_mensajes(
                turno.respuesta,
                channel=m.channel,
                to=m.sender_id,
                conversation_id=m.conversation_id,
                # La clave lleva el id del mensaje entrante Y el índice de la
                # pieza. Sin el índice, un turno de cuatro mensajes se
                # deduplicaría a uno cuando Meta reenvíe el webhook.
                clave_base=f"resp:{m.external_message_id}",
                url_publica=self.settings.url_publica,
                carpetas_de_media=self.settings.carpetas_de_media,
            )
            for mensaje in mensajes:
                self.outbox.enqueue(mensaje)

            self._copiar_al_crm(m, turno, mensajes)

            # Lo que hace BUSCABLE una traza. Sin esto es una lista de
            # turnos; con esto se puede pedir «enséñame las conversaciones
            # que acabaron pidiendo un humano».
            self._anotar_traza(m, turno, mensajes)

            if turno.respuesta.escalar:
                log.warning("ESCALADO: esta conversación necesita una persona")
            log.info("encoladas %s pieza(s)", len(mensajes))
            return mensajes

    def _anotar_anuncio(self, m: InboundMessage) -> None:
        """Si el mensaje vino de un anuncio, se le anota a la clienta (ADR 0028).

        En una ráfaga el anuncio viene en el PRIMER mensaje y la ráfaga se
        funde sobre el último: por eso se miran las partes. Nunca tumba el
        turno: perder el dato del anuncio es malo; perder la respuesta, peor.
        """
        for parte in m.partes or [m]:
            if parte.referido is None:
                continue
            try:
                self.bot._mundo.anotar_anuncio(m.conversation_id, parte.referido)
                log.info("llegó por el anuncio %s", parte.referido.anuncio_id)
            except Exception as exc:
                log.warning("no se pudo anotar el anuncio (%s)", exc)

    def _anotar_traza(self, m: InboundMessage, turno, mensajes) -> None:
        """Lo que hace AUDITABLE una traza en LangSmith (si está encendida).

        `thread_id` agrupa los turnos por conversación: en la pestaña «Threads»
        se lee cada charla entera, turno por turno, con lo que entendió el
        modelo, lo que Python corrigió y cuánto costó. Las etiquetas permiten
        filtrar («escalado», «corregido», «potente», la etapa…).
        """
        jugada = getattr(turno, "jugada", None)
        ctx = turno.contexto
        b = (ctx.borrador or {}) if ctx is not None else {}
        rechazos = [r for r in turno.respuesta.traza if "no pasó" in r]
        registro = getattr(turno, "registro", None)
        pedido = self._pedido_de(m.conversation_id)
        anotar(
            thread_id=m.conversation_id,
            conversacion=m.conversation_id,
            capa=getattr(turno, "capa", "") or "gestor",
            lectura=jugada.lectura if jugada else "",
            acciones=[a.value for a in jugada.acciones] if jugada else [],
            confianza=jugada.confianza.value if jugada else "",
            accion=turno.decision.accion.value if turno.decision else "",
            interpretacion=(
                turno.interpretacion.resumen() if turno.interpretacion else ""
            ),
            corregido_por_python=[r.strip() for r in rechazos],
            falta_para_el_pedido=b.get("pedido_id") is None
            and bool(b)
            and ", ".join(_falta(b)),
            pedido=pedido.codigo if pedido else "",
            estado_pedido=pedido.estado if pedido else "",
            escalado=turno.respuesta.escalar,
            piezas=len(mensajes),
            costo_usd=getattr(registro, "cost_usd", None),
        )
        etiquetar(
            f"capa:{getattr(turno, 'capa', '') or 'gestor'}",
            "escalado" if turno.respuesta.escalar else "",
            "corregido" if rechazos else "",
            f"pedido:{pedido.estado}" if pedido else "",
            "nota-de-voz" if getattr(turno, "transcripciones", None) else "",
        )

    def _llego_atrasado(self, m: InboundMessage) -> None:
        """A Chatwoot con una nota de cuándo lo escribió, y la plantilla sola."""
        from app.domain.plantilla_de_emergencia import COMANDO

        escrito = (m.timestamp - timedelta(hours=5)).strftime("%d/%m a las %H:%M")
        log.info("atrasado: lo escribió el %s; no se le contesta libre", escrito)
        self._copiar_entrante_al_crm(m)
        if self.crm is not None:
            try:
                self.crm.nota(
                    m.conversation_id,
                    f"📩 Mensaje ATRASADO: ella lo escribió el {escrito} y Meta lo "
                    "entregó hasta ahora. WhatsApp ya no deja contestarle con texto "
                    f"normal: para escribirle, manda {COMANDO}.",
                )
            except Exception as exc:  # pragma: no cover - el CRM nunca tumba nada
                log.warning("no se pudo dejar la nota del atrasado (%s)", exc)
        self._retomar_sola(m)

    #: Cuánto se cree lo que dijo Meta de la plantilla de emergencia: aprobada,
    #: un día; todavía no, 10 minutos (para enterarse pronto cuando la aprueben).
    CACHE_APROBADA = timedelta(hours=24)
    CACHE_NO_APROBADA = timedelta(minutes=10)

    def _emergencia_aprobada(self) -> str | None:
        """La plantilla de emergencia que Meta ya aprobó (la principal o la de
        respaldo, en ese orden), o None. Se pregunta poco."""
        from app.domain.plantilla_de_emergencia import PLANTILLAS

        return self._primera_aprobada(PLANTILLAS, "_emergencia")

    def _asesora_aprobada(self) -> str | None:
        """La de `#asesora` (19/10) que Meta ya aprobó, o None."""
        from app.domain.plantilla_de_emergencia import PLANTILLAS_ASESORA

        return self._primera_aprobada(PLANTILLAS_ASESORA, "_asesora")

    def descartar_lo_que_espera_la_ventana(self, destinatario: str, motivo: str) -> int:
        """Lo que se le escribió libre y espera a que ella abra la ventana: ya
        no sale (llegaría tarde y fuera de lugar). Por su número: lo que Lía
        escribe en Chatwoot se encola sin conversación. Devuelve cuántos."""
        consultar = getattr(getattr(self, "db", None), "consultar", None)
        if consultar is None:
            return 0
        filas = consultar(
            "SELECT idempotency_key FROM outbox WHERE sent_at IS NULL "
            "AND destinatario = ? AND error LIKE 'ventana de 24 h cerrada%'",
            (destinatario,),
        )
        claves = [f["idempotency_key"] for f in filas]
        for clave in claves:
            self.outbox.descartar(clave, motivo)
        return len(claves)

    # -- el banco de plantillas por situación (22/10) --------------------------

    #: Cuánto se cree lo que dijo Meta de los estados: poco, porque una plantilla
    #: «en revisión» se aprueba en cualquier momento.
    CACHE_DE_ESTADOS = timedelta(minutes=15)
    _estados_banco: Any = None
    _banco: Any = None

    def banco_de_plantillas(self):
        """El banco (grupos y plantillas), o None si el archivo no está."""
        from app.domain.banco_de_plantillas import Banco

        if self._banco is None:
            try:
                self._banco = Banco.desde_json(self.settings.banco_plantillas_json)
            except (OSError, ValueError, KeyError) as exc:
                log.warning("no se pudo leer el banco de plantillas (%s)", exc)
                return None
        return self._banco

    def estados_de_las_plantillas(self) -> dict[str, str]:
        """El estado en Meta de TODAS las plantillas, con memoria de 15 min."""
        ahora = datetime.now(UTC)
        if self._estados_banco is not None:
            cuando, estados = self._estados_banco
            if ahora - cuando < self.CACHE_DE_ESTADOS:
                return estados
        waba = self.settings.wa_business_account_id
        listar = getattr(self.whatsapp, "estados_de_plantillas", None)
        if not waba or listar is None:
            return {}
        try:
            estados = listar(waba)
        except Exception as exc:  # sin respuesta de Meta: se pregunta en la próxima
            log.warning("no se pudo preguntar por las plantillas (%s)", exc)
            return {}
        self._estados_banco = (ahora, estados)
        return estados

    def plantilla_del_grupo(
        self, grupo: str, valores: dict[str, str], *, conv: str, to: str, clave: str
    ) -> OutboundMessage | None:
        """La plantilla de ESTA situación, lista para `enviar_a_la_clienta`.

        None si el grupo no está prendido (`activos.json`; por defecto ninguno),
        si está bloqueado o si ninguna plantilla aprobada sirve con los datos que
        hay. NO la manda: quien llama decide. Así que, mientras Camilo no prenda un
        grupo, el banco no cambia ningún envío."""
        from app.domain.banco_de_plantillas import grupos_activos

        banco = self.banco_de_plantillas()
        if banco is None or grupo not in grupos_activos(
            self.settings.banco_plantillas_activos
        ):
            return None
        escogida = banco.escoger(grupo, self.estados_de_las_plantillas(), valores)
        if escogida is None:
            log.info(
                "banco: nada para %s (%s)",
                grupo,
                banco.por_que_no(grupo, self.estados_de_las_plantillas(), valores),
            )
            return None
        return OutboundMessage(
            channel=Channel.WHATSAPP,
            to=to,
            kind="template",
            text=escogida.texto,
            template_name=escogida.plantilla.nombre,
            template_params=escogida.parametros,
            conversation_id=conv,
            idempotency_key=clave,
        )

    def _primera_aprobada(self, plantillas, cache: str) -> str | None:
        """La primera de `plantillas` que Meta ya aprobó. Se le pregunta poco:
        aprobada, se cree un día; todavía no, 10 minutos."""
        ahora = datetime.now(UTC)
        if getattr(self, cache) is not None:
            cuando, aprobada = getattr(self, cache)
            vigencia = self.CACHE_APROBADA if aprobada else self.CACHE_NO_APROBADA
            if ahora - cuando < vigencia:
                return aprobada
        waba = self.settings.wa_business_account_id
        consultar = getattr(self.whatsapp, "estado_de_plantilla", None)
        if not waba or consultar is None:
            return None
        try:
            aprobada = next(
                (n for n in plantillas if consultar(waba, n) == "APPROVED"), None
            )
        except Exception as exc:  # sin respuesta de Meta: se pregunta en la próxima
            log.warning("no se pudo preguntar por la plantilla (%s)", exc)
            return None
        setattr(self, cache, (ahora, aprobada))
        return aprobada

    def _retomar_sola(self, m: InboundMessage) -> bool:
        """La plantilla de emergencia, sola, a quien llegó atrasada (Camilo, 16/10).

        Solo si Meta ya la aprobó (si no, esperan a `vb retomar --enviar`, que
        corre la vigilancia el día que la aprueben). De noche no sale ya: queda
        programada para las 8 a. m. Una por clienta y por día
        (`emergencia.clave`): aunque Meta entregue tres mensajes atrasados
        suyos o se corra `vb retomar`, le llega una sola disculpa. Queda en
        Chatwoot como mensaje saliente (`enviar_a_la_clienta`).
        """
        from app.domain import plantilla_de_emergencia as emergencia

        if solo_respuesta_inmediata(m.conversation_id):
            return False  # pruebas y números de la casa: nada automático (19/10)
        nombre = self._emergencia_aprobada() if m.channel.value == "whatsapp" else None
        if nombre is None:
            return False
        conv = m.conversation_id
        ahora = datetime.now(UTC)
        despues = emergencia.cuando_mandarla(ahora)
        mensaje = OutboundMessage(
            channel=m.channel,
            to=m.sender_id,
            kind="template",
            text=emergencia.PLANTILLAS[nombre],
            template_name=nombre,
            conversation_id=conv,
            idempotency_key=emergencia.clave(conv, despues or ahora),
        )
        if not self.enviar_a_la_clienta(conv, mensaje, enviar_despues=despues):
            log.info("plantilla de emergencia: ya tenía la de hoy")
            return True
        if despues is not None and self.crm is not None:
            hora = (despues - timedelta(hours=5)).strftime("%d/%m a las %H:%M")
            try:
                self.crm.nota(conv, f"🕗 La plantilla de emergencia sale el {hora}.")
            except Exception as exc:  # pragma: no cover - el CRM nunca tumba nada
                log.warning("no se pudo dejar la nota de la plantilla (%s)", exc)
        log.info("plantilla de emergencia para el atrasado (%s)", despues or "ya")
        return True

    def _copiar_entrante_al_crm(self, m: InboundMessage) -> None:
        """Lo que ella escribió, a Chatwoot. Una ráfaga va mensaje por mensaje."""
        if self.crm is None:
            return
        try:
            for parte in m.partes or [m]:
                self.crm.registrar(
                    m.conversation_id,
                    parte.text or "[adjunto]",
                    entrante=True,
                    nombre=m.sender_name or "",
                    adjuntos=tuple(x.model_dump() for x in parte.media),
                )
        except Exception as exc:  # pragma: no cover - el CRM nunca tumba nada
            log.warning("no se pudo copiar al CRM (%s)", exc)

    def _pago_por_verificar(self, conv: str) -> bool:
        """¿Hay un pago esperando que Lía lo verifique en el banco?"""
        try:
            pedido = self._pedido_de(conv)
            if pedido is not None and pedido.estado == "EN_REVISION_PAGO":
                return True
            b = self.bot._mundo.contexto(conv).borrador or {}
            return bool(b.get("pagado_sin_pedido") or b.get("abono_reportado"))
        except Exception:  # pragma: no cover - avisar nunca tumba el turno
            return False

    def _avisar_lo_importante(self, m: InboundMessage, turno, pago_antes: bool) -> None:
        """Al celular de Camilo (ntfy), lo que no puede esperar (14/10): un pago
        nuevo por verificar y una clienta que pide una persona."""
        numero = m.conversation_id.rsplit(":", 1)[-1]
        if solo_respuesta_inmediata(numero):
            return
        quien = f"{m.sender_name or 'Una clienta'} (…{numero[-4:]})"
        dijo = (m.text or "").strip()[:140]
        if not pago_antes and self._pago_por_verificar(m.conversation_id):
            self._avisar(
                "💰 Llegó un pago por verificar",
                f"{quien} mandó el comprobante. Míralo en el banco y confírmalo en "
                "el panel.",
                f"pago:{m.conversation_id}",
            )
        if getattr(turno.respuesta, "escalar", False):
            self._avisar(
                "🙋 Una clienta te necesita",
                f"{quien}" + (f": «{dijo}»" if dijo else "") + " · Mírala en Chatwoot.",
                f"persona:{m.conversation_id}",
            )

    def informar_que_no_llego(
        self, conv: str, texto: str, motivo: str, definitivo: bool = True
    ) -> None:
        """Lo que se le mandó y NO le llegó (o quedó esperando), dicho (16/10).

        Chatwoot muestra el mensaje como enviado apenas se encola, lo mande el
        bot o Lía. Si después no sale (24 h vencidas, plantilla sin aprobar,
        Meta no lo entregó…), queda una nota en esa conversación y llega al
        celular, con quién, qué se le quiso decir y por qué no le llegó.
        """
        numero = conv.rsplit(":", 1)[-1]
        if solo_respuesta_inmediata(numero):
            return
        try:
            cliente = self.bot._mundo.cliente_de(conv)
            nombre = (getattr(cliente, "nombre", "") or "").strip()
        except Exception:  # pragma: no cover - el nombre es lo de menos
            nombre = ""
        quien = f"{nombre or 'Una clienta'} (…{numero[-4:]})"
        corto = " ".join((texto or "").split())[:90]
        if definitivo:
            icono, que = "❌", "NO le llegó"
        else:
            icono, que = "⏳", "todavía NO le llega"
        if self.crm is not None:
            try:
                self.crm.nota(conv, f"{icono} Este mensaje {que}: «{corto}». {motivo}.")
            except Exception as exc:  # pragma: no cover - el CRM nunca tumba nada
                log.warning("no se pudo dejar la nota de lo que no llegó (%s)", exc)
        self._avisar(
            f"{icono} A {quien} un mensaje {que}",
            f"«{corto}» · {motivo}. Mira la nota en Chatwoot.",
            f"no-llego:{conv}:{definitivo}",
        )

    def no_llego_segun_meta(self, wamid: str, motivo: str) -> bool:
        """El acuse «failed» de Meta: aceptó el mensaje y no lo entregó."""
        mensaje = getattr(self.outbox, "por_external_id", lambda _w: None)(wamid)
        if mensaje is None:
            log.warning("Meta no entregó %s y no está en la outbox: %s", wamid, motivo)
            return False
        conv = mensaje.conversation_id or conversation_id(mensaje.channel, mensaje.to)
        texto = mensaje.text or (
            f"plantilla {mensaje.template_name}" if mensaje.template_name else ""
        )
        log.warning("Meta no entregó un mensaje: %s", motivo)
        self.informar_que_no_llego(conv, texto or f"[{mensaje.kind}]", motivo)
        return True

    def _solo_reacciona(self, m: InboundMessage) -> bool:
        """¿Todo lo que mandó es una reacción a un mensaje? (ver `solo_reacciona`)"""
        from app.conversacion.asesora import solo_reacciona

        partes = m.partes or [m]
        media = [x.model_dump() for p in partes for x in p.media]
        texto = " ".join(p.text or "" for p in partes)
        try:
            charla = self.bot._mundo.contexto(m.conversation_id).charla
        except Exception:
            return False
        if not charla:
            return False  # el primer mensaje lleva la apertura, como siempre
        ultimo = next(
            (x.get("texto", "") for x in reversed(charla) if x.get("de") == "lia"), ""
        )
        return solo_reacciona(media, texto, ultimo)

    def _media_para_el_bot(self, m: InboundMessage) -> list[dict]:
        """Los adjuntos que ve el turno.

        Los que no traen archivo (una reacción, una ubicación, lo que WhatsApp
        no deja ver) se le describen al modelo, salvo en el PRIMER turno: ahí
        antes llegaban como «nada» y salía la apertura fija, y eso no se toca.
        """
        media = [x.model_dump() for x in m.media]
        con_archivo = [x for x in media if x.get("kind") not in _SIN_ARCHIVO]
        if len(con_archivo) == len(media):
            return media
        try:
            primer_turno = not self.bot._mundo.contexto(m.conversation_id).charla
        except Exception:
            primer_turno = False
        return con_archivo if primer_turno else media

    def es_primer_mensaje(self, m: InboundMessage) -> bool:
        """¿Esta conversación no tiene NADA todavía? Entonces no hay ventana:
        la apertura sale al instante, como siempre."""
        return not self.conversaciones.historial(m.conversation_id, limite=1)

    def _guardar_decision(self, turno) -> None:
        """Guarda por qué se decidió lo que se decidió. Nunca tumba el turno."""
        if self.decisiones is None or getattr(turno, "registro", None) is None:
            return
        try:
            self.decisiones.guardar(turno.registro)
        except Exception as exc:  # pragma: no cover - la observabilidad no rompe nada
            log.warning("no se pudo guardar el registro de la decisión (%s)", exc)

    def enviar_a_la_clienta(
        self,
        conv: str,
        mensaje: OutboundMessage,
        *,
        enviar_despues: datetime | None = None,
    ) -> bool:
        """LA puerta para escribirle a una clienta fuera de un turno del bot.

        Sale por la outbox (con reintentos) y queda copiado en Chatwoot como
        mensaje saliente. Las respuestas del bot en la conversación ya se
        copian en `_copiar_al_crm`; esto es para todo lo demás: mover un
        pedido, lo que Lía escribe en el panel, «repreguntar», el auxilio,
        los recordatorios y el pago confirmado.

        Por qué existe (26/09): Lía verificó un abono desde el panel, a la
        clienta le llegó «tu anillo ya entró al taller» y en Chatwoot no
        aparecía. La auditoría encontró cinco caminos más con el mismo hueco:
        cada uno encolaba por su lado. Chatwoot es donde Lía atiende; si le
        falta un mensaje, atiende a ciegas.

        Si Chatwoot falla, el mensaje sale igual: copiar nunca bloquea.

        17/10: las 28 disculpas de las 8 a. m. salieron por WhatsApp y en
        Chatwoot no estaban (el script encolaba por su lado). Ahora la
        plantilla de emergencia también pasa por aquí, programada o no. Si la
        clave ya estaba (Meta reintentó), no se copia otra vez: devuelve False.
        """
        if enviar_despues is not None:
            # Programado: se copia cuando sale (el despachador), no ahora.
            mensaje = mensaje.model_copy(update={"copiar_al_salir": True})
        nuevo = self.outbox.enqueue(mensaje, enviar_despues=enviar_despues)
        if nuevo is not False and enviar_despues is None:
            self._copiar_salientes_al_crm(conv, [mensaje])
        return nuevo is not False

    def _copiar_salientes_al_crm(self, conv: str, mensajes) -> None:
        if self.crm is None:
            return
        try:
            for salida in mensajes:
                self.crm.registrar(
                    conv,
                    salida.text or _etiqueta_de_media(salida),
                    entrante=False,
                    adjuntos=self._adjunto_de(salida),
                )
        except Exception as exc:  # pragma: no cover - el CRM no rompe nada
            log.warning("no se pudo copiar a Chatwoot lo que se le mandó (%s)", exc)

    def _copiar_al_crm(self, m: InboundMessage, turno, mensajes) -> None:
        """Copia el turno al CRM y lo pone al día. Nunca falla, nunca bloquea.

        Va DESPUÉS de encolar la respuesta, a propósito: lo primero es que la
        clienta reciba su mensaje.
        """
        if self.crm is None:
            return
        try:
            self._copiar_entrante_al_crm(m)
            self._copiar_salientes_al_crm(m.conversation_id, mensajes)
            self._notas_del_turno(m.conversation_id, turno)
            self.actualizar_seguimiento(
                m.conversation_id, escalada=bool(turno.respuesta.escalar)
            )
        except Exception as exc:  # pragma: no cover - el CRM no rompe nada
            log.warning("no se pudo copiar al CRM (%s)", exc)

    def _adjunto_de(self, salida) -> tuple[dict, ...]:
        """El ARCHIVO de una foto o un video del bot, para que se vea en el CRM.

        Antes en Chatwoot salía «[📷 muestrario circones]» y había que
        imaginárselo: Lía no veía el prototipo que el bot acababa de mandarle a
        la clienta, ni las fotos del anillo terminado. Y desde el celular, menos.

        Se manda la RUTA en disco, no la URL: son los mismos megas que ya
        salieron hacia WhatsApp y no tienen por qué volver a pasar por el túnel.
        """
        url = getattr(salida, "media_url", "") or ""
        if not url:
            return ()
        nombre = url.rsplit("/", 1)[-1]
        ruta = None
        if "/panel/foto/" in url:
            almacen = getattr(self, "fotos", None) or _almacen_de_fotos(self.settings)
            ruta = almacen.ruta_de(nombre) if almacen is not None else None
        else:
            from app.conversacion.salida import ruta_de_media

            ruta = ruta_de_media(self.settings.carpetas_de_media, nombre)
        if ruta is None:
            return ()
        tipo = "video/mp4" if salida.kind == "video" else "image/jpeg"
        if str(ruta).lower().endswith(".png"):
            tipo = "image/png"
        elif str(ruta).lower().endswith(".webp"):
            tipo = "image/webp"
        return ({"ruta": str(ruta), "mime_type": tipo},)

    def _notas_del_turno(self, conv: str, turno) -> None:
        """Lo que Lía tiene que SABER va como nota privada en Chatwoot.

        Cada cosa se anota UNA vez: qué se anotó queda en el contexto
        (`crm_hecho`), así un reinicio del servidor no repite notas viejas.
        """
        mundo = self.bot._mundo
        ctx = mundo.contexto(conv)
        hecho = set(ctx.crm_hecho)
        notas: list[tuple[str, str]] = []
        if turno.respuesta.escalar and "persona" not in hecho:
            dijo = (getattr(turno, "texto", "") or "").strip()[:300]
            notas.append(
                ("persona", "🙋 Te necesita" + (f". Dijo: «{dijo}»" if dijo else ""))
            )
        dijo = (getattr(turno, "texto", "") or "").strip()
        if dijo:
            from app.domain.recordatorios import pide_que_le_escriban, pospone

            if pospone(dijo) and pide_que_le_escriban(dijo):
                # «Escríbeme el otro mes» (09/10): el bot no tiene recordatorios a
                # un mes ni los inventa; se lo deja a Lía, que es quien decide.
                notas.append(
                    (
                        "",
                        f"📅 Pidió que le escriban más adelante: «{dijo[:300]}». "
                        "El bot no programa eso: escríbele tú cuando toque.",
                    )
                )
        for d in getattr(turno, "transcripciones", None) or []:
            notas.append(
                ("", "🎤 " + d.replace("una nota de voz en la que dice", "Nota de voz:"))
            )
        b = ctx.borrador or {}
        if b.get("pedido_codigo") and f"pedido:{b['pedido_codigo']}" not in hecho:
            from app.domain.asesora import Borrador

            resumen = Borrador.model_validate(b).resumen()
            notas.append(
                (
                    f"pedido:{b['pedido_codigo']}",
                    f"🧾 Pedido {b['pedido_codigo']} tomado\n\n{resumen}",
                )
            )
        for i, motivo in enumerate(ctx.revisar):
            clave = f"rev:{i}:{motivo[:40]}"
            if clave in hecho:
                continue
            icono = (
                "💰"
                if motivo.lower().startswith("verificar")
                else "🙋"
                if motivo.startswith("Pasar a Lía")
                else "📝"
            )
            notas.append((clave, f"{icono} {motivo}"))
        for clave, texto in notas:
            self.crm.nota(conv, texto)
            if clave:
                hecho.add(clave)
        if hecho != set(ctx.crm_hecho):
            mundo.guardar_contexto(ctx.model_copy(update={"crm_hecho": sorted(hecho)}))

    def actualizar_seguimiento(self, conv: str, *, escalada: bool = False) -> None:
        """Etapa, alertas, ficha y estado de la conversación en el CRM."""
        if self.crm is None:
            return
        from app.domain.asesora import Borrador
        from app.domain.seguimiento import seguimiento

        mundo = self.bot._mundo
        ctx = mundo.contexto(conv)
        if escalada and not ctx.necesita_persona:
            ctx = ctx.model_copy(update={"necesita_persona": True})
            mundo.guardar_contexto(ctx)
        b = Borrador.model_validate(ctx.borrador) if ctx.borrador else Borrador()
        pedido = self._pedido_de(conv)
        estado = pedido.estado if pedido is not None else ""
        antes_del_taller = estado in ("", "ESPERANDO_ANTICIPO", "EN_REVISION_PAGO")
        talla_dudosa = pedido is not None and any(
            i.personalizacion.talla_revisar for i in pedido.items
        )
        s = seguimiento(
            estado_pedido=estado,
            anticipo_pagado=bool(pedido and pedido.anticipo_pagado_cop),
            diseno_empezado=bool(b.cantidad or b.huellitas or b.grabado),
            escalada=ctx.necesita_persona,
            pagado_sin_pedido=b.pagado_sin_pedido and pedido is None,
            por_confirmar=(bool(b.notas) and antes_del_taller) or talla_dudosa,
            fecha_limite=bool(b.fecha_deseada),
            falta_direccion=bool(b.falta_para_despachar()),
        )
        self.crm.seguimiento(
            conv,
            s,
            self._ficha(b, pedido),
            nombre=b.nombre_clienta,
            persona_atendiendo=mundo.la_atiende_una_persona(conv),
        )

    @staticmethod
    def _ficha(b, pedido) -> dict:
        """La ficha de la derecha en Chatwoot: lo que Lía quiere ver sin leer."""
        from app.domain.asesora import unir_grabado

        n = b.cantidad or len(b.huellitas)
        colores = " | ".join(h.describir() for h in b.huellitas[: n or None])
        destino = ", ".join(p for p in (b.direccion, b.ciudad) if p)
        ficha = {
            "pedido": b.pedido_codigo,
            "huellitas": str(b.cantidad or ""),
            "colores": colores,
            "grabado": unir_grabado(b.grabado)
            if b.grabado
            else ("sin grabado" if b.sin_grabado else ""),
            "talla": talla_texto(b.talla),
            "envio": " · ".join(p for p in (b.nombre_clienta, destino) if p),
            "falta": ", ".join(
                b.falta_para_abono() if pedido is None else b.falta_para_despachar()
            ),
            "entrega": "La recoge en Floridablanca" if b.recoge else "Envío",
            # Uno por uno, para que Lía los pueda corregir en Chatwoot y se
            # copien al pedido (29/09). Del pedido si ya existe; si no, del bot.
            **_datos_de_la_guia(b, pedido),
            "por_confirmar": " · ".join(b.notas)[:400],
            "fecha_limite": b.fecha_deseada,
        }
        if b.varios or b.anillos:
            # Varios anillos (02/10): cada dato con el número de su anillo.
            vistas = list(enumerate(b.vistas(), 1))
            ficha.update(
                {
                    "huellitas": " | ".join(
                        f"A{k}: {v.cantidad or '?'}" for k, v in vistas
                    ),
                    "colores": " | ".join(
                        f"A{k}: " + " / ".join(h.describir() for h in v.huellitas)
                        for k, v in vistas
                    ),
                    "grabado": " | ".join(
                        f"A{k}: "
                        + (
                            unir_grabado(v.grabado)
                            if v.grabado
                            else ("sin grabado" if v.sin_grabado else "")
                        )
                        for k, v in vistas
                    ),
                    "talla": " | ".join(
                        f"A{k}: {talla_texto(v.talla) or '?'}" for k, v in vistas
                    ),
                }
            )
        if pedido is not None:
            pendiente = max(0, pedido.saldo_cop - pedido.saldo_pagado_cop)
            ficha.update(
                {
                    "total": formatear_cop(pedido.total_cop),
                    "abonado": formatear_cop(pedido.anticipo_pagado_cop),
                    "saldo_pendiente": formatear_cop(pendiente),
                }
            )
        return ficha

    def accion_desde_crm(self, conv: str, etiqueta: str) -> str:
        """Lía puso una etiqueta `hacer-…` en Chatwoot: se ejecuta aquí.

        Pasa por `mover_pedido`, así que hace exactamente lo mismo que el botón
        del panel (reglas, aviso a la clienta, memoria del bot, ERP). Al final
        quita la etiqueta y deja una nota con lo que pasó. Devuelve esa nota.
        """
        from app.domain.operacion import PedidoIncompleto
        from app.domain.order_state import TransicionInvalida
        from app.domain.seguimiento import DESTINOS_DE_ACCION

        if self.crm is None:
            return ""
        if etiqueta == "hacer-preguntar-lo-que-falta":
            return self._repreguntar(conv, etiqueta)
        if etiqueta == "hacer-devolver-al-bot":
            from app.infra.quien_atiende import devolver_al_bot

            self.crm.quitar_etiqueta(conv, etiqueta)
            devolver_al_bot(self, conv)
            nota = "🤖 De vuelta con VentaBot: el bot sigue atendiendo esta conversación."
            self.crm.nota(conv, nota)
            return nota
        destinos = DESTINOS_DE_ACCION.get(etiqueta)
        if not destinos:
            return ""
        with self._candado_de(conv):
            pedido = self._pedido_de(conv)
            if pedido is not None and any(
                e.estado_nuevo == destinos[-1] for e in self.orders.eventos(pedido.id)
            ):
                # Ya se hizo: esto es el eco de un cambio de etiquetas (cada cambio
                # vuelve por webhook con la etiqueta todavía puesta). Solo se quita.
                self.crm.quitar_etiqueta(conv, etiqueta)
                return ""
            if pedido is None:
                nota = f"⚠️ «{etiqueta}»: esta conversación no tiene pedido."
            else:
                nota = f"✅ {pedido.codigo}: listo ({etiqueta})."
                for destino in destinos:
                    pedido = self.orders.get(pedido.id)
                    if pedido.estado == destino:
                        continue
                    try:
                        pedido = self.mover_pedido(
                            pedido, destino, actor="chatwoot", motivo=etiqueta
                        )
                    except PedidoIncompleto as exc:
                        nota = (
                            f"⚠️ {exc.codigo} no puede entrar al taller: falta "
                            f"{', '.join(exc.faltan)}. Pídeselo y vuelve a poner "
                            f"«{etiqueta}»."
                        )
                        break
                    except TransicionInvalida:
                        nota = (
                            f"⚠️ «{etiqueta}» no aplica: {pedido.codigo} está en "
                            f"{pedido.estado}."
                        )
                        break
            self.crm.quitar_etiqueta(conv, etiqueta)
            self.crm.nota(conv, nota)
            self.actualizar_seguimiento(conv)
            return nota

    def _repreguntar(self, conv: str, etiqueta: str) -> str:
        """«hacer-preguntar-lo-que-falta»: el bot vuelve a pedir lo que falta.

        ════════════════════════════════════════════════════════════════════
        POR QUÉ HACE FALTA ESTO
        ════════════════════════════════════════════════════════════════════
        El bot puede quedarse dando vueltas en un paso: la clienta ya dijo el
        grabado pero Python lo rechazó y no se guardó, y desde fuera lo único
        que se ve es que no avanza. Lía no sabe qué falta, y la clienta tampoco
        —el bot le pregunta de formas distintas cada vez—, así que la
        conversación se muere ahí.

        Con esta etiqueta, en un toque: a la clienta le llega la lista exacta,
        y a Lía una nota con TODO lo que el pedido tiene guardado hoy. Si lo
        que ella dijo no aparece en la nota, es que no se guardó, y ahí se ve.

        Esta etiqueta no mueve el pedido: solo habla.
        """
        from app.domain.asesora import Borrador

        with self._candado_de(conv):
            mundo = getattr(self.bot, "_mundo", None)
            crudo = mundo.contexto(conv).borrador if mundo is not None else None
            borrador = Borrador.model_validate(crudo) if crudo else None
            if borrador is None:
                nota = (
                    f"⚠️ «{etiqueta}»: esta conversación todavía no tiene un "
                    "pedido en curso, no hay nada que preguntar."
                )
                self.crm.quitar_etiqueta(conv, etiqueta)
                self.crm.nota(conv, nota)
                return nota

            falta = borrador.falta_para_abono() or borrador.falta_para_despachar()
            cliente = self._cliente_de(conv)
            if falta and cliente is not None:
                lista = "\n".join(f"• {q}" for q in falta)
                texto = (
                    "¡Hola! 🥰 Para poder seguir con tu anillito me falta:\n\n"
                    f"{lista}\n\n"
                    "¿Me lo confirmas? 💍"
                )
                self.enviar_a_la_clienta(
                    conv,
                    OutboundMessage(
                        channel=cliente.channel,
                        to=cliente.channel_user_id,
                        text=texto,
                        conversation_id=conv,
                        idempotency_key=f"repreguntar:{conv}:{borrador.turnos}",
                    ),
                )
                if mundo is not None:
                    mundo.anotar_aviso_del_sistema(conv, texto)

            tiene = borrador.resumen() or "(nada todavía)"
            nota = (
                "🔁 Le volví a pedir: "
                + (", ".join(falta) if falta else "NADA, el pedido está completo")
                + "\n\nLo que tengo guardado ahora mismo:\n"
                + tiene
                + "\n\nSi algo que ella ya dijo no aparece aquí, es que no se "
                "guardó: escríbelo tú en el chat y el bot lo toma."
            )
            self.crm.quitar_etiqueta(conv, etiqueta)
            self.crm.nota(conv, nota)
            self.actualizar_seguimiento(conv)
            return nota

    def _cliente_de(self, conv: str):
        """La clienta de una conversación «wa:573…», o None si no está."""
        canal, _, usuario = conv.partition(":")
        with __import__("contextlib").suppress(Exception):
            return self.customers.get_by_channel_user(canal, usuario)
        return None

    def _pedido_de(self, conv: str):
        """El pedido de la conversación: el del borrador o, si no hay, el último
        abierto de la clienta (pedidos creados a mano o por el motor viejo)."""
        mundo = self.bot._mundo
        b = mundo.contexto(conv).borrador or {}
        pedido = mundo.pedido(b["pedido_id"]) if b.get("pedido_id") else None
        if pedido is None:
            pedidos = mundo.pedidos_de(conv)
            pedido = pedidos[0] if pedidos else None
        return pedido

    def _candado_de(self, conv: str):
        with self._candados_lock:
            return self._candados.setdefault(conv, threading.Lock())

    def anotar_nota_interna(self, conv: str, nota: dict) -> None:
        """Una nota interna de Lía: memoria de la asesora + nota privada en
        Chatwoot. La clienta no la ve. Nunca tumba nada."""
        from app.domain.notas_internas import para_chatwoot

        if not (nota.get("texto") or "").strip():
            return
        try:
            mundo = getattr(self.bot, "_mundo", None)
            if mundo is not None:
                mundo.anotar_nota_interna(conv, nota)
            if self.crm is not None:
                self.crm.nota(conv, para_chatwoot(nota))
        except Exception as exc:  # pragma: no cover - una nota no tumba nada
            log.warning("no se pudo guardar la nota interna (%s)", exc)

    def escribirle_de_parte_de_lia(self, conv: str, texto: str, clave: str) -> None:
        """Un mensaje que Lía escribió en el panel: sale por WhatsApp, queda en
        Chatwoot y en la memoria del bot (sin eso, el bot lo contradiría)."""
        from app.domain.models import Channel

        texto = (texto or "").strip()
        if not texto:
            return
        canal, _, numero = conv.partition(":")
        mensaje = OutboundMessage(
            channel=Channel.INSTAGRAM if canal == "ig" else Channel.WHATSAPP,
            to=numero,
            kind="text",
            text=texto[:4000],
            conversation_id=conv,
            idempotency_key=clave,
        )
        self.enviar_a_la_clienta(conv, mensaje)
        mundo = getattr(self.bot, "_mundo", None)
        if mundo is not None:
            mundo.anotar_mensaje_de_humano(conv, texto)

    #: Más de esto sin IA y ya no se retoma solo: WhatsApp no deja escribirle
    #: libre después de 24 h, y a esas alturas le toca a una persona.
    HORAS_MAXIMAS_PENDIENTE = 23

    def reintentar_turnos_pendientes(self) -> int:
        """Lo que ninguna IA pudo contestar, otra vez, hasta que alguna vuelva.

        29/09: Anthropic se cayó, la clienta recibió «dame un momentico» y nadie
        le volvió a escribir. Esto corre cada poco en segundo plano: cuando la
        IA contesta, le llega la respuesta a todo lo pendiente, se quita la
        alerta de Chatwoot y a Camilo le llega «la IA volvió». Si alguien la
        tomó a mano (le escribió o la asignó en Chatwoot), el bot no se mete.
        Devuelve a cuántas les contestó.
        """
        from datetime import UTC, datetime, timedelta

        if not getattr(self.bot, "reintenta_pendientes", False):
            return 0
        if not hasattr(self.contexto, "recientes"):
            return 0
        mundo = self.bot._mundo
        ahora = datetime.now(UTC)
        contestadas = 0
        for ctx in self.contexto.recientes(500):
            pendiente = ctx.pendiente_ia
            if not pendiente:
                continue
            conv = ctx.conversation_id
            desde = datetime.fromisoformat(pendiente["desde"])
            if mundo.la_atiende_una_persona(conv):
                self._soltar_pendiente(
                    conv, "La tomó una persona: el bot no retoma lo pendiente."
                )
                continue
            if ahora - desde > timedelta(hours=self.HORAS_MAXIMAS_PENDIENTE):
                self._soltar_pendiente(
                    conv,
                    f"Pasaron {self.HORAS_MAXIMAS_PENDIENTE} h sin que la IA volviera: "
                    "contéstale tú (WhatsApp ya no deja escribirle libre).",
                )
                self._avisar("Una clienta sigue sin respuesta", conv, f"ia-23h:{conv}")
                continue
            proximo = pendiente.get("proximo")
            if proximo and datetime.fromisoformat(proximo) > ahora:
                continue
            if self._reintentar_uno(conv, pendiente, desde):
                contestadas += 1
        return contestadas

    @traza("turno_pendiente")
    def _reintentar_uno(self, conv: str, pendiente: dict, desde) -> bool:
        """Un turno que la IA no pudo contestar, otra vez. Con su propia traza en
        LangSmith (etiqueta «pendiente»), como cualquier turno."""
        from app.conversacion.salida import a_mensajes
        from app.domain.models import Channel

        anotar(conversacion=conv, intentos=pendiente.get("intentos"))
        etiquetar("pendiente")
        turno = self.bot.ejecutar(conv, None, None, reintento=True)
        if getattr(turno, "capa", "") in ("sin_modelo", "nada"):
            return False
        canal, _, numero = conv.partition(":")
        for mensaje in a_mensajes(
            turno.respuesta,
            channel=Channel.INSTAGRAM if canal == "ig" else Channel.WHATSAPP,
            to=numero,
            conversation_id=conv,
            clave_base=f"reintento:{conv}:{pendiente['desde']}",
            url_publica=self.settings.url_publica,
            carpetas_de_media=self.settings.carpetas_de_media,
        ):
            self.enviar_a_la_clienta(conv, mensaje)
        self._guardar_decision(turno)
        self._la_ia_volvio(conv, desde)
        return True

    def _soltar_pendiente(self, conv: str, nota: str) -> None:
        mundo = self.bot._mundo
        ctx = mundo.contexto(conv)
        mundo.guardar_contexto(ctx.model_copy(update={"pendiente_ia": None}))
        if self.crm is not None:
            self.crm.nota(conv, nota)

    def _la_ia_volvio(self, conv: str, desde) -> None:
        """Contestó lo pendiente: fuera la alerta de Chatwoot, y aviso a Camilo."""
        mundo = self.bot._mundo
        ctx = mundo.contexto(conv)
        if ctx.necesita_persona:
            mundo.guardar_contexto(ctx.model_copy(update={"necesita_persona": False}))
        try:
            if self.crm is not None:
                self.crm.quitar_etiqueta(conv, "necesita-persona")
                self.crm.nota(
                    conv, "✅ La IA volvió y le contestó lo que estaba pendiente."
                )
            self.actualizar_seguimiento(conv)
        except Exception as exc:  # pragma: no cover - avisar nunca tumba nada
            log.warning("no se pudo quitar la alerta (%s)", exc)
        self._avisar(
            "✅ La IA volvió",
            f"Le contestó a {conv} lo que estaba pendiente.",
            f"ia-volvio:{conv}:{desde.isoformat()}",
        )

    def _avisar(self, titulo: str, detalle: str, clave: str) -> None:
        try:
            if self.avisos is not None:
                self.avisos.avisar(titulo, detalle, clave)
        except Exception as exc:  # pragma: no cover - avisar nunca tumba nada
            log.warning("no se pudo avisar (%s)", exc)

    def refrescar_analitica(self) -> int:
        """Vuelve a aplanar los pedidos en `pedidos_analitica`. Nunca falla."""
        if self.analitica is None:
            return 0
        try:
            return self.analitica.reconstruir()
        except Exception as exc:  # pragma: no cover - el análisis no tumba nada
            log.warning("no se pudo actualizar la tabla de análisis (%s)", exc)
            return 0

    def editar_pedido(self, pedido, datos: dict, *, actor: str = "panel") -> list[str]:
        """Lía cambia datos del pedido a mano (29/09). Lleno en uno, lleno en todos.

        Queda igual en el pedido, en la memoria del bot (si no, el bot volvería
        a lo de antes), en Chatwoot (ficha y nota) y en el ERP. Devuelve lo que
        cambió; lanza `EdicionInvalida` si algo no se puede guardar.
        """
        _, cambios = self._guardar_edicion(pedido, datos, actor=actor)
        return cambios

    def editar_conversacion(
        self, conv: str, datos: dict, *, actor: str = "chatwoot"
    ) -> list[str]:
        """Lo mismo, cuando todavía no hay pedido (solo la memoria del bot)."""
        from app.domain.asesora import Borrador
        from app.domain.edicion import aplicar_edicion

        mundo = self.bot._mundo
        ctx = mundo.contexto(conv)
        b = Borrador.model_validate(ctx.borrador) if ctx.borrador else Borrador()
        _, nuevo, cambios = aplicar_edicion(None, b, datos)
        if not cambios:
            return []
        mundo.guardar_contexto(
            ctx.model_copy(update={"borrador": nuevo.model_dump(mode="json")})
        )
        self._avisar_edicion(conv, "", cambios, actor)
        return cambios

    def _guardar_edicion(self, pedido, datos: dict, *, actor: str, avisar: bool = True):
        from app.domain.asesora import Borrador
        from app.domain.edicion import aplicar_edicion

        cliente = self.customers.get(pedido.customer_id)
        conv = (
            conversation_id(cliente.channel, cliente.channel_user_id) if cliente else ""
        )
        mundo = getattr(self.bot, "_mundo", None)
        ctx = mundo.contexto(conv) if (mundo is not None and conv) else None
        b = Borrador.model_validate(ctx.borrador) if ctx and ctx.borrador else None
        nuevo_pedido, nuevo_b, cambios = aplicar_edicion(pedido, b, datos)
        if not cambios:
            return pedido, []
        pedido = self.orders.guardar_pedido(nuevo_pedido)
        if ctx is not None and b is not None:
            # La memoria del bot queda igual al pedido: si no, el turno
            # siguiente le devolvería al pedido lo que había antes.
            mundo.guardar_contexto(
                ctx.model_copy(update={"borrador": nuevo_b.model_dump(mode="json")})
            )
        if avisar and conv:
            self._avisar_edicion(conv, pedido.codigo, cambios, actor)
        elif conv and self.crm is not None:
            self.crm.nota(conv, f"✏️ {pedido.codigo}: {'; '.join(cambios)}")
        try:
            if self.erp is not None:
                self.erp.pedido_movido(pedido, pedido.estado)
        except Exception as exc:  # pragma: no cover - el ERP no tumba una edición
            log.warning("no se pudo avisar la edición al ERP (%s)", exc)
        self.refrescar_analitica()
        return pedido, cambios

    def _avisar_edicion(self, conv: str, codigo: str, cambios: list[str], actor: str):
        quien = {"panel": "desde el panel", "chatwoot": "desde Chatwoot"}.get(
            actor, f"por {actor}"
        )
        try:
            if self.crm is not None:
                cabeza = f"✏️ Datos editados {quien}" + (f" · {codigo}" if codigo else "")
                self.crm.nota(conv, cabeza + "\n" + "\n".join(f"• {c}" for c in cambios))
            self.actualizar_seguimiento(conv)
        except Exception as exc:  # pragma: no cover - avisar nunca tumba nada
            log.warning("no se pudo avisar la edición (%s)", exc)

    def desde_chatwoot(self, conv: str, atributos: dict) -> list[str]:
        """Lía cambió la ficha en Chatwoot: se copia al pedido y al panel.

        Solo lo que es DISTINTO de lo que el bot puso: el eco de nuestra propia
        ficha no cambia nada (y así no hay un ida y vuelta sin fin).
        """
        from app.domain.asesora import Borrador
        from app.domain.edicion import DESDE_CHATWOOT

        mundo = self.bot._mundo
        ctx = mundo.contexto(conv)
        b = Borrador.model_validate(ctx.borrador) if ctx.borrador else Borrador()
        pedido = self.orders.get(b.pedido_id) if b.pedido_id else None
        actual = self._ficha(b, pedido)
        datos = {
            clave: str(atributos[clave]).strip()
            for clave in DESDE_CHATWOOT
            if clave in atributos
            and str(atributos[clave] or "").strip()
            and str(atributos[clave]).strip() != str(actual.get(clave) or "").strip()
        }
        if b.varios or b.anillos:
            # Con varios anillos la talla y el grabado de la ficha son de todos
            # («A1: … | A2: …»): no se sabe de cuál es el cambio. Van por el panel.
            datos.pop("talla", None)
            datos.pop("grabado", None)
        if not datos:
            return []
        if pedido is not None:
            return self.editar_pedido(pedido, datos, actor="chatwoot")
        return self.editar_conversacion(conv, datos, actor="chatwoot")

    def confirmar_talla_de_conversacion(
        self, conv: str, talla: float, *, nota: str = "", mensaje: str = "", actor="panel"
    ) -> None:
        """Regla de Lía (29/09): Lía confirma la talla ANTES del abono.

        Todavía no hay pedido (nace al pedir el abono), así que se confirma en
        la conversación. A la clienta le llega su talla —el mensaje de Lía si
        escribió uno, o `TALLA_CONFIRMADA`— y el flujo sigue: si ya estaba todo,
        el resumen para que diga que sí y se le mande el abono como siempre.
        """
        from app.conversacion.asesora import TALLA_CONFIRMADA
        from app.conversacion.salida import a_mensajes
        from app.domain.asesora import Borrador
        from app.domain.models import Channel
        from app.domain.notas_internas import nota_de_talla
        from app.domain.tallas import DIAMETRO_MM

        talla = float(talla)
        if talla not in DIAMETRO_MM:
            raise ValueError(f"la talla {talla:g} no existe en el mandril")
        mundo = self.bot._mundo
        ctx = mundo.contexto(conv)
        b = Borrador.model_validate(ctx.borrador) if ctx.borrador else Borrador()
        if b.pedido_id and (pedido := self.orders.get(b.pedido_id)) is not None:
            # Ya pidió el abono (o pagó): la talla se confirma en el pedido.
            self.confirmar_talla(pedido, talla, nota=nota, mensaje=mensaje, actor=actor)
            return
        quien = "Lía" if actor == "panel" else actor
        # Con varios anillos, la que se confirma es la del que la esperaba.
        b.talla_exige_lia = True
        pendiente = b.pendiente_de_talla()
        v = b.vista(len(b.anillos) if pendiente is None else pendiente)
        if v.talla is None:
            motivo = f"Puesta por {quien} (la IA no la pudo leer)"
        elif v.talla == talla:
            motivo = f"Confirmada por {quien}"
        else:
            motivo = f"Corregida por {quien} (la IA sugería {talla_texto(v.talla)})"
        mundo.fijar_talla_de_lia(conv, talla, motivo)
        self.anotar_nota_interna(
            conv,
            nota_de_talla(
                f"Talla {talla_texto(talla)}: {motivo.lower()}. {nota}".strip(),
                autor=actor,
            ),
        )
        texto = (mensaje or "").strip() or TALLA_CONFIRMADA.format(
            talla=talla_texto(talla)
        )
        clave = f"talla:{conv}:{talla:g}:{_huella(texto)}"
        self.escribirle_de_parte_de_lia(conv, texto, clave)
        siguiente = getattr(self.bot, "tras_confirmar_talla", None)
        if siguiente is not None:
            respuesta = siguiente(conv)
            canal, _, numero = conv.partition(":")
            for pieza in a_mensajes(
                respuesta,
                channel=Channel.INSTAGRAM if canal == "ig" else Channel.WHATSAPP,
                to=numero,
                conversation_id=conv,
                clave_base=f"talla-sigue:{conv}:{_huella(respuesta.texto_plano)}",
                url_publica=self.settings.url_publica,
                carpetas_de_media=self.settings.carpetas_de_media,
            ):
                self.enviar_a_la_clienta(conv, pieza)
        try:
            self.actualizar_seguimiento(conv)
        except Exception as exc:  # pragma: no cover - nunca tumba la confirmación
            log.warning("no se pudo poner al día Chatwoot (%s)", exc)

    def confirmar_talla(
        self,
        pedido,
        talla: float,
        *,
        nota: str = "",
        mensaje: str = "",
        actor="panel",
        anillo: int | None = None,
    ):
        """Lía confirma o corrige la talla. Desde ahí ESA es la referencia.

        La estimación de la IA era preliminar (27/09). Nada esperó por esto: la
        conversación siguió y el pedido llegó al abono igual. Aquí la talla
        queda firme en el pedido, en la memoria de la conversación (para que
        el bot no vuelva a la estimación) y en Chatwoot.
        """
        from app.domain.notas_internas import nota_de_talla
        from app.domain.tallas import DIAMETRO_MM, talla_texto

        talla = float(talla)
        if talla not in DIAMETRO_MM:
            raise ValueError(f"la talla {talla:g} no existe en el mandril")
        # `anillo` (1, 2…) en un pedido de varios anillos; None = todos.
        indice = anillo - 1 if anillo and len(pedido.items) > 1 else None
        antes = next(
            (
                i.personalizacion.talla
                for k, i in enumerate(pedido.items)
                if i.personalizacion and indice in (None, k)
            ),
            None,
        )
        quien = "Lía" if actor == "panel" else actor
        motivo = (
            f"Confirmada por {quien}"
            if antes == talla
            else f"Corregida por {quien} (antes {talla_texto(antes) or 'sin talla'})"
        )
        items = [
            i.model_copy(
                update={
                    "personalizacion": i.personalizacion.model_copy(
                        update={
                            "talla": talla,
                            "talla_revisar": False,
                            "talla_motivo": motivo,
                        }
                    )
                }
            )
            if i.personalizacion and indice in (None, k)
            else i
            for k, i in enumerate(pedido.items)
        ]
        pedido = self.orders.guardar_pedido(pedido.model_copy(update={"items": items}))
        cliente = self.customers.get(pedido.customer_id)
        if cliente is None:
            return pedido
        conv = conversation_id(cliente.channel, cliente.channel_user_id)
        mundo = getattr(self.bot, "_mundo", None)
        if mundo is not None:
            mundo.fijar_talla_de_lia(conv, talla, motivo, indice)
        encabezado = f"Talla {talla_texto(talla)}: {motivo.lower()}."
        self.anotar_nota_interna(
            conv,
            nota_de_talla(
                f"{encabezado} {nota}".strip(), codigo=pedido.codigo, autor=actor
            ),
        )
        self.escribirle_de_parte_de_lia(
            conv, mensaje, f"talla:{pedido.id}:{talla:g}:{_huella(mensaje)}"
        )
        try:
            self.actualizar_seguimiento(conv)
            if self.erp is not None:
                self.erp.pedido_movido(pedido, pedido.estado)
        except Exception as exc:  # pragma: no cover - nunca tumba la confirmación
            log.warning("no se pudo avisar la talla confirmada (%s)", exc)
        return pedido

    def mover_pedido(
        self,
        pedido,
        destino,
        *,
        actor: str,
        motivo: str = "",
        mensaje: str = "",
        nota: str = "",
        guia: str = "",
        transportadora: str = "",
    ):
        """EL camino para mover un pedido desde fuera de la conversación.

        Panel, Chatwoot o quien sea: todos pasan por aquí, así que todos hacen lo
        mismo en el mismo orden:
          1. la regla del 100 %: sin datos completos no entra al taller;
          2. la transición (valida la tabla y deja auditoría);
          3. lo que queda pagado al confirmar abono o saldo;
          4. el aviso a la clienta (fotos primero), por la outbox;
          5. ese aviso entra en la memoria del bot: sin esto, tras «tu anillo
             ya está listo» el bot seguía diciendo «está en el taller» (19/09);
          6. Chatwoot y el ERP se enteran (nunca bloquean): Chatwoot recibe los
             mensajes tal cual le llegaron a la clienta (`enviar_a_la_clienta`)
             y una nota para Lía.
          7. Lo que Lía escribió en el panel al moverlo (27/09), las dos cosas
             opcionales: `mensaje` le llega a la clienta después del aviso;
             `nota` es INTERNA (Chatwoot privada + memoria de la asesora).
        """
        from app.domain.operacion import (
            PedidoIncompleto,
            SinFotosDelAnillo,
            falta_para_despachar,
            falta_para_taller,
            mensaje_de_aviso,
            mensajes_con_fotos,
            montos_al_llegar,
        )
        from app.domain.order_state import OrderState
        from app.domain.services import transicionar

        destino = OrderState(destino)
        # La guía se escribe junto al botón «Despachado» (29/09): se guarda
        # ANTES de mirar qué falta, porque es justo lo que faltaba.
        if (guia or "").strip() or (transportadora or "").strip():
            pedido, _ = self._guardar_edicion(
                pedido,
                {"guia": guia, "transportadora": transportadora},
                actor=actor,
                avisar=False,
            )
        # Un movimiento que la tabla no permite es ilegal ANTES que incompleto:
        # si no, «PRODUCCION_LISTA -> DESPACHADO» se quejaría de la dirección en
        # vez de decir que ese salto no existe. `transicionar` es quien la lanza.
        from app.domain.order_state import TRANSICIONES

        legal = destino in TRANSICIONES[OrderState(pedido.estado)]
        if legal and destino is OrderState.EN_PRODUCCION:
            huellitas = {p.sku: p.huellitas for p in self.products.list_active()}
            faltan = falta_para_taller(pedido, huellitas_por_sku=huellitas)
            if faltan:
                raise PedidoIncompleto(pedido.codigo, faltan)
        # Sin dirección (o sin que diga que lo recoge) no hay a dónde mandarlo.
        if (
            legal
            and destino is OrderState.DESPACHADO
            and (faltan := falta_para_despachar(pedido))
        ):
            raise PedidoIncompleto(pedido.codigo, faltan)
        # «Ya está listo» sin fotos no se manda: el mensaje ES las fotos.
        if legal and destino is OrderState.ESPERANDO_SALDO and not pedido.fotos:
            raise SinFotosDelAnillo(pedido.codigo)

        pedido = transicionar(self.orders, pedido, destino, actor=actor, motivo=motivo)
        if montos := montos_al_llegar(pedido, destino):
            pedido = self.orders.guardar_pedido(pedido.model_copy(update=montos))

        cliente = self.customers.get(pedido.customer_id)
        if cliente is None:
            return pedido
        conv = conversation_id(cliente.channel, cliente.channel_user_id)
        if destino is OrderState.ANTICIPO_PAGADO:
            self.avisar_venta_a_meta(pedido, conv)
        # El aviso del anillo terminado va PARTIDO: saludo y pedida de datos,
        # luego las fotos, luego el cobro. Así lo manda Lía, y así se lee: ve
        # su anillo entre el «ya está listo» y el número (Camilo, 20/09).
        aviso = mensaje_de_aviso(pedido, cliente, destino)
        mundo = getattr(self.bot, "_mundo", None)
        if aviso is not None:
            self.enviar_a_la_clienta(conv, aviso)
            if mundo is not None:
                mundo.anotar_aviso_del_sistema(conv, aviso.text or "")
        for foto in mensajes_con_fotos(
            pedido, cliente, destino, base_url=self.settings.url_publica
        ):
            self.enviar_a_la_clienta(conv, foto)
        if destino is OrderState.ESPERANDO_SALDO and aviso is not None:
            from app.domain.guion import aviso_de_cierre, para_las_piezas

            cierre = para_las_piezas(
                aviso_de_cierre(
                    envio_cop=pedido.envio_contraentrega_cop
                    or (
                        mundo.envio_a(pedido.envio.ciudad if pedido.envio else None)
                        if mundo
                        else None
                    ),
                    recoge=bool(pedido.envio and pedido.envio.recoge),
                    saldo_cop=max(0, pedido.saldo_cop - pedido.saldo_pagado_cop),
                    envio_con_saldo=bool(pedido.envio and pedido.envio.envio_con_saldo),
                ),
                [i.personalizacion.pieza for i in pedido.items],
            )
            cobro = aviso.model_copy(
                update={
                    "text": cierre,
                    "idempotency_key": f"cierre:{pedido.id}:{destino.value}",
                }
            )
            self.enviar_a_la_clienta(conv, cobro)
            if mundo is not None:
                mundo.anotar_aviso_del_sistema(conv, cierre)
        if (nota or "").strip():
            from app.domain.notas_internas import nota_de_pedido

            self.anotar_nota_interna(
                conv,
                nota_de_pedido(nota, codigo=pedido.codigo, destino=destino, autor=actor),
            )
        self.escribirle_de_parte_de_lia(
            conv,
            mensaje,
            f"lia:{pedido.id}:{destino.value}:{_huella(mensaje)}",
        )
        try:
            if self.crm is not None:
                from app.domain.seguimiento import seguimiento as calcular

                etapa = calcular(
                    estado_pedido=destino.value,
                    anticipo_pagado=bool(pedido.anticipo_pagado_cop),
                ).etapa
                quien = {"panel": "desde el panel", "chatwoot": "desde Chatwoot"}.get(
                    actor, f"por {actor}"
                )
                self.crm.nota(conv, f"📦 {pedido.codigo} → {etapa} ({quien})")
                self.actualizar_seguimiento(conv)
            if self.erp is not None:
                self.erp.pedido_movido(pedido, destino.value)
        except Exception as exc:  # pragma: no cover - nunca tumba el movimiento
            log.warning("no se pudo avisar el movimiento (%s)", exc)
        self.refrescar_analitica()
        return pedido

    def avisar_venta_a_meta(self, pedido, conv: str) -> bool:
        """El abono confirmado, a Meta, unido al clic del anuncio (13/10).

        Solo si vino de un anuncio (su primer mensaje trae `ctwa_clid`) y no es
        un número de prueba. Nunca lanza: el pedido se mueve igual."""
        if self.conversiones is None or solo_respuesta_inmediata(conv):
            return False
        try:
            import json

            filas = self.db.consultar(
                "SELECT payload FROM messages WHERE conversation_id = ? AND "
                "direccion = 'IN' AND payload LIKE '%ctwa_clid%' ORDER BY id LIMIT 1",
                (conv,),
            )
            if not filas:
                log.info("venta %s sin clic de anuncio: no va a Meta", pedido.codigo)
                return False
            referral = (json.loads(filas[0]["payload"] or "{}") or {}).get(
                "referral"
            ) or {}
            return self.conversiones.compra(
                codigo=pedido.codigo,
                valor_cop=pedido.total_cop,
                ctwa_clid=referral.get("ctwa_clid") or "",
                cuando=datetime.now(UTC),
            )
        except Exception as exc:  # pragma: no cover - nunca tumba el movimiento
            log.warning("no se pudo avisar la venta a Meta (%s)", exc)
            return False

    def notificar_pago_confirmado(self, pedido, pago) -> None:
        """Se llama desde el webhook de pago, FUERA de toda conversación.

        Si pasaron más de 24 h desde el último mensaje del cliente, el
        despachador verá la ventana cerrada y avisará de que hace falta una
        plantilla aprobada.
        """
        cliente = self.customers.get(pedido.customer_id)
        if cliente is None:
            log.warning("pago de %s sin clienta: no se le avisa", pedido.codigo)
            return
        # Al NÚMERO de la clienta. Antes iba a `customer_id`, que es el id
        # interno: Meta lo habría rechazado (auditoría del 26/09; los pagos
        # por pasarela están aparcados y nunca llegó a pasar).
        conv = conversation_id(cliente.channel, cliente.channel_user_id)
        self.enviar_a_la_clienta(
            conv,
            OutboundMessage(
                channel=cliente.channel,
                to=cliente.channel_user_id,
                kind="template",
                template_name="pago_confirmado_anticipo",
                template_params={"codigo": pedido.codigo},
                text=f"Pago confirmado del pedido {pedido.codigo}.",
                conversation_id=conv,
                idempotency_key=f"pago-ok:{pago.id}",
            ),
        )

    def gateway_parse_event(self, raw: bytes) -> dict:
        return BoldGateway.parse_event(raw)

    def cerrar(self) -> None:
        self.db.cerrar()


def _falta(borrador: dict) -> list[str]:
    from app.domain.asesora import Borrador

    try:
        return Borrador.model_validate(borrador).falta_para_abono()
    except Exception:  # pragma: no cover - un borrador viejo no rompe la traza
        return []


def _modelos_con_respaldo(s, *, claude_basico_modelo: str = "", para: str = "IA"):
    """Los modelos de la asesora, cada uno con su respaldo y su paciencia (29/09).

    Con `IA_PRINCIPAL=openai` (producción): básico GPT → Claude (Haiku), en
    vueltas; potente GPT (su fuerte) → Claude (Sonnet). Con `anthropic`, al
    revés. Sin GPT configurado, cada cadena tiene solo a Claude, pero igual
    insiste unos segundos. Los OJOS usan lo mismo con su modelo de Claude
    (`claude_basico_modelo`): medido el 29/09, luna leyó bien un comprobante
    de $60.000 que Haiku leyó como $60.000.000.
    """
    from app.adapters.llm.anthropic_client import ClaudeLLM
    from app.adapters.llm.cadena import CadenaDeModelos

    gpt_basico = gpt_fuerte = None
    if s.llm_respaldo_backend == "openai":
        if s.openai_api_key and s.openai_modelo:
            from app.adapters.llm.openai_client import OpenAILLM

            gpt_basico = OpenAILLM(
                s.openai_modelo, s.openai_api_key, esfuerzo=s.openai_esfuerzo
            )
            gpt_fuerte = OpenAILLM(
                s.openai_modelo_fuerte or s.openai_modelo,
                s.openai_api_key,
                esfuerzo=s.openai_esfuerzo_fuerte or s.openai_esfuerzo,
            )
        else:
            log.error(
                "LLM_RESPALDO_BACKEND=openai necesita OPENAI_API_KEY y OPENAI_MODELO: "
                "sin GPT, solo Anthropic"
            )
    claude_basico = ClaudeLLM(
        claude_basico_modelo or s.llm_basico_model, s.anthropic_api_key
    )
    claude_fuerte = (
        ClaudeLLM(s.llm_fuerte_model, s.anthropic_api_key)
        if s.llm_fuerte_model.startswith("claude")
        else None
    )
    gpt_primero = s.ia_principal == "openai" and gpt_basico is not None

    def en_orden(claude, gpt) -> list:
        modelos = [m for m in ((gpt, claude) if gpt_primero else (claude, gpt)) if m]
        return modelos

    basico = CadenaDeModelos(
        en_orden(claude_basico, gpt_basico), paciencia_s=s.ia_paciencia_s
    )
    fuerte = None
    if claude_fuerte is not None or gpt_fuerte is not None:
        # El potente ya llega tarde (después del básico): poca paciencia extra.
        fuerte = CadenaDeModelos(
            en_orden(claude_fuerte, gpt_fuerte), paciencia_s=min(10.0, s.ia_paciencia_s)
        )
    log.info(
        "%s: %s · cuando duda: %s",
        para,
        basico.model,
        fuerte.model if fuerte else "(nadie)",
    )
    return basico, fuerte


def _guardar_foto_de(settings):
    """Cómo guarda la asesora la foto de la regla para el panel (29/09)."""
    almacen = _almacen_de_fotos(settings)
    if almacen is None:
        return None
    return lambda datos: almacen.guardar(datos).nombre


def _almacen_de_fotos(settings):
    """El almacén de las fotos del anillo terminado, o None si no hay."""
    from contextlib import suppress

    with suppress(Exception):
        from app.adapters.almacen_fotos import AlmacenDeFotos

        return AlmacenDeFotos(settings.fotos_dir)
    return None


def _datos_de_la_guia(b, pedido) -> dict:
    """Los datos de envío de la ficha: del pedido si existe, si no del borrador."""
    envio = pedido.envio if pedido is not None and pedido.envio else None
    return {
        "destinatario": (envio.nombre if envio else "")
        or b.destinatario
        or b.nombre_clienta,
        "ciudad": (envio.ciudad if envio else "") or b.ciudad,
        "direccion": (envio.direccion if envio else "") or b.direccion,
        "barrio": (envio.barrio if envio else "") or b.barrio,
        "cedula": (envio.cedula if envio else "") or b.cedula,
        "celular": (envio.celular if envio else "") or b.celular,
        "transportadora": envio.transportadora if envio else "",
        "guia": envio.guia if envio else "",
    }


def _huella(texto: str) -> str:
    """Corta y ESTABLE entre procesos (`hash()` cambia en cada arranque): es la
    clave de idempotencia de un mensaje escrito a mano; dos clics, un envío."""
    import hashlib

    return hashlib.sha256((texto or "").encode("utf-8")).hexdigest()[:10]


#: Los adjuntos que no traen archivo (ver `MediaRef.kind`).
_SIN_ARCHIVO = frozenset({"unsupported", "reaction", "location", "contacts"})


def _etiqueta_de_media(salida) -> str:
    """Cómo se ve en Chatwoot una foto o un video que mandó el bot.

    «[image]» no le dice nada a Lía; «📷 muestrario circones» sí.
    """
    nombre = (salida.media_url or "").rsplit("/", 1)[-1].rsplit(".", 1)[0]
    nombre = nombre.replace("_", " ").replace("-", " ").strip()
    icono = {"image": "📷", "video": "🎬"}.get(salida.kind, "📎")
    return f"[{icono} {nombre}]" if nombre else f"[{icono} {salida.kind}]"


def _kind_de(final: dict) -> str:
    if final.get("reply_cta_url"):
        return "cta_url"
    if final.get("reply_options"):
        return "options"
    return "text"


# ---------------------------------------------------------------------------


def _por_dias(s: Settings, products):
    """Lo que el modo por días necesita del negocio (13/10): la URL de las fotos,
    los precios, el abono y las cuentas."""
    from app.domain.faq import datos_para_transferir
    from app.workers.recordatorios import PorDias

    activos = products.list_active()
    anillos = sorted(
        (p for p in activos if p.categoria == "anillos" and p.huellitas),
        key=lambda p: p.huellitas,
    )
    partes = [
        f"{formatear_cop(p.precio_cop)} ({p.huellitas} huellita"
        f"{'s' if p.huellitas > 1 else ''})"
        if i == 0
        else f"{formatear_cop(p.precio_cop)} ({p.huellitas})"
        for i, p in enumerate(anillos)
    ]
    precios = (
        ", ".join(partes[:-1]) + f" o {partes[-1]}"
        if len(partes) > 1
        else "".join(partes)
    )

    def abono(categoria: str, defecto: int) -> int:
        return next(
            (
                p.anticipo_fijo_cop
                for p in activos
                if p.categoria == categoria and p.anticipo_fijo_cop
            ),
            defecto,
        )

    raiz = (s.url_publica or "").rstrip("/")
    return PorDias(
        url_de_media=lambda nombre: f"{raiz}/media/{nombre}" if raiz else "",
        precios=precios,
        abono_anillo=abono("anillos", 60_000),
        abono_cadena=abono("cadenas", 65_000),
        cuentas=datos_para_transferir(),
    )


def _filas_de_accesos(s: Settings) -> list[list[str]]:
    """Lo que el bot escribe de sí mismo en la hoja CENTRO DE MANDO del ERP.

    Se calcula en cada vuelta y no una vez al arrancar: la hora de «visto vivo»
    es justamente lo que dice si el bot sigue encendido.
    """
    import socket

    return filas_del_centro_de_mando(
        publico=(s.url_publica_override or s.public_url or "").rstrip("/"),
        local="http://127.0.0.1:8000",
        token=s.panel_token or "",
        chatwoot_local=s.chatwoot_url or "",
        chatwoot_publico=s.chatwoot_url_publica,
        arrancado=ARRANCADO,
        ahora=datetime.now(UTC),
        maquina=socket.gethostname(),
        carpeta=Path(__file__).resolve().parents[2],
        excel=str(s.ventas_excel),
    )


def _avisar_todo_error(avisos) -> None:
    """Todo ERROR del registro al celular: el del bot y el de uvicorn (que no
    llega a la raíz). Una sola vez aunque el contenedor se arme de nuevo."""
    from app.adapters.avisos import AvisarLosErrores

    for nombre in ("", "uvicorn"):
        registro = logging.getLogger(nombre)
        for viejo in [h for h in registro.handlers if isinstance(h, AvisarLosErrores)]:
            registro.removeHandler(viejo)
        registro.addHandler(AvisarLosErrores(avisos))


def build_container(settings: Settings | None = None) -> Container:
    s = settings or get_settings()

    # --- transporte: SIEMPRE persistente ---
    db = SqliteDB(s.sqlite_path)
    idempotency = SqliteIdempotencyStore(db)
    outbox = SqliteOutbox(db)
    conversaciones = SqliteConversaciones(db)

    # --- negocio ---
    if s.repository_backend == "memory":
        products = InMemoryProductRepository(cargar_catalogo(s))
        customers = InMemoryCustomerRepository()
        orders = InMemoryOrderRepository()
        payments = InMemoryPaymentRepository()
    elif s.repository_backend == "sqlite":
        # El catálogo sigue viniendo del CSV versionado en Git: es un archivo
        # que se revisa en un pull request, y eso vale más que una tabla que
        # cualquiera edita sin dejar rastro. Lo que va a SQLite es lo que
        # CAMBIA con cada conversación: clientas y pedidos.
        products = InMemoryProductRepository(cargar_catalogo(s))
        customers = SqliteCustomerRepository(db)
        orders = SqliteOrderRepository(db)
        payments = InMemoryPaymentRepository()
    elif s.repository_backend == "sheets":
        raise NotImplementedError(
            "Fase 2: cablear SheetsProductRepository y SheetsOrderRepository "
            "(ver app/adapters/repositories/sheets.py)"
        )
    elif s.repository_backend == "sql":
        raise NotImplementedError("Fase 6: cablear SqlOrderRepository")
    else:
        raise ValueError(f"REPOSITORY_BACKEND desconocido: {s.repository_backend}")

    # --- LLM: la PRIMERA capa de modelo ---
    #
    # Las reglas de Python van SIEMPRE delante (ver `Interprete`); esto es lo
    # que entra cuando no bastan. Con `claude` y sin clave no se arranca a
    # ciegas: se cae al modelo local y se avisa en claro.
    if s.llm_backend == "fake":
        llm = FakeLLM()
    elif s.llm_backend == "claude" and s.anthropic_api_key:
        from app.adapters.llm.anthropic_client import ClaudeLLM

        llm = ClaudeLLM(s.llm_basico_model, s.anthropic_api_key)
    elif s.llm_backend == "claude":
        # Sin clave NO se cae a un modelo local: el negocio trabaja solo con
        # modelos en línea (decisión de Camilo, 17/09/2026). Contestan las
        # reglas de Python y se avisa fuerte.
        log.error(
            "LLM_BACKEND=claude necesita ANTHROPIC_API_KEY en el .env: mientras "
            "tanto contestan solo las reglas, sin modelo."
        )
        llm = FakeLLM()
    else:
        llm = OllamaLLM(model=s.ollama_model, host=s.ollama_host)

    # --- los OJOS: su propio modelo, su propia decisión de apagarlo ---
    #
    # Separado del modelo de texto a propósito (ver `app/domain/vision.py`).
    # Sin `OLLAMA_VISION_MODEL` el bot sigue funcionando: reconoce que llegó
    # una foto, la marca para que la mire una persona, y continúa. Es mejor
    # arranque por defecto que adivinar.
    from app.adapters.llm.ojos_ollama import OjosCiegos, OjosDeOllama

    prompt_vision = (
        Path(__file__).resolve().parents[1] / "prompts" / "vision_v1.txt"
    ).read_text(encoding="utf-8")
    con_claude = bool(s.anthropic_api_key) and s.llm_backend != "fake"
    # `OjosDeOllama` no sabe de proveedores: recibe cualquier LLMPort que acepte
    # imágenes (aquí, la misma cadena GPT ↔ Claude de la asesora). El nombre
    # es histórico.
    vista = vista_fuerte = None
    if con_claude and (
        s.llm_vision_model.startswith("claude") or s.llm_fuerte_model.startswith("claude")
    ):
        vista, vista_fuerte = _modelos_con_respaldo(
            s, claude_basico_modelo=s.llm_vision_model, para="Ojos"
        )
    if s.llm_backend == "fake":
        ojos = OjosCiegos()
    elif s.llm_vision_model.startswith("claude") and vista is not None:
        ojos = OjosDeOllama(vista, prompt_vision)
    elif not s.ollama_vision_model or s.llm_backend != "ollama":
        # El lector local solo si se eligió Ollama a propósito. Con Claude sin
        # lector configurado, la foto se marca para que la mire una persona.
        ojos = OjosCiegos()
    else:
        ojos = OjosDeOllama(
            OllamaLLM(
                model=s.ollama_model,
                host=s.ollama_host,
                vision_model=s.ollama_vision_model,
            ),
            prompt=prompt_vision,
        )
    # El lector POTENTE: solo relee las fotos que importan y no se entendieron.
    ojos_fuertes = None
    if s.llm_fuerte_model.startswith("claude") and vista_fuerte is not None:
        ojos_fuertes = OjosDeOllama(vista_fuerte, prompt_vision)

    # --- pasarela ---
    if s.payment_backend == "fake":
        gateway = FakeGateway()
    else:
        gateway = BoldGateway(
            identity_key=s.bold_identity_key,
            secret_key=s.bold_secret_key,
            callback_url=s.bold_callback_url,
        )

    # --- canales ---
    whatsapp = WhatsAppAdapter(
        phone_number_id=s.wa_phone_number_id,
        access_token=s.wa_access_token,
        app_secret=s.app_secret_efectivo,
        verify_token=s.meta_verify_token or "sin-configurar",
    )
    salida = ConsoleChannel() if s.channel_backend == "console" else whatsapp
    canales = {"whatsapp": salida, "instagram": salida}

    # Bajar adjuntos SIEMPRE va por WhatsApp aunque la salida sea la consola:
    # los mensajes entrantes son reales incluso cuando las respuestas se
    # imprimen en pantalla, y es el único que tiene el token.
    from app.adapters.media.whatsapp_media import MediaDeWhatsApp

    media = FakeMedia() if not s.wa_access_token else MediaDeWhatsApp(whatsapp)

    # --- grafo con checkpoints en disco ---
    deps = Deps(
        products=products,
        customers=customers,
        orders=orders,
        payments=payments,
        gateway=gateway,
        llm=llm,
        media=media,
    )
    graph = build_graph(deps, checkpointer=_checkpointer(s))

    # --- Avisos: que Camilo se entere si algo se rompe ---
    avisos = None
    if s.avisos_backend == "ntfy" and s.ntfy_tema:
        from app.adapters.avisos import AvisosPorNtfy

        avisos = AvisosPorNtfy(s.ntfy_tema, s.ntfy_servidor)
        log.info("avisos por ntfy al tema %s…", s.ntfy_tema[:6])
        _avisar_todo_error(avisos)
    elif s.avisos_backend == "telegram" and s.telegram_bot_token and s.telegram_chat_id:
        from app.adapters.avisos import AvisosPorTelegram

        avisos = AvisosPorTelegram(s.telegram_bot_token, s.telegram_chat_id)
        log.info("avisos por Telegram")
    elif s.avisos_backend != "ninguno":
        log.error(
            "AVISOS_BACKEND=%s sin configurar: los fallos solo quedarán en el log",
            s.avisos_backend,
        )

    # --- CRM: para que Lía vea las conversaciones en un solo sitio ---
    #
    # Vacío = no se copia nada. El bot es idéntico sin esto: el CRM es para
    # mirar, no para atender.
    crm = None
    if s.chatwoot_url and s.chatwoot_token and s.chatwoot_inbox_id:
        from app.adapters.crm.chatwoot import ChatwootCRM
        from app.adapters.crm.cola import ColaEnSqlite

        crm = ChatwootCRM(
            base_url=s.chatwoot_url,
            token=s.chatwoot_token,
            account_id=s.chatwoot_account_id,
            inbox_id=s.chatwoot_inbox_id,
            descargar=deps.media.download,
            bot_token=s.chatwoot_bot_token,
            # La cola en la base: si Chatwoot se cae por horas o el bot se
            # reinicia, cada copia espera ahí y llega después (07/10).
            cola=ColaEnSqlite(db),
            avisar=avisos.avisar if avisos is not None else None,
        )
        log.info("CRM: copiando conversaciones a %s", s.chatwoot_url)

    # --- el gestor conversacional (Fase 3) ---
    #
    # Sustituye al grafo como quien contesta. El grafo se conserva un tiempo
    # para poder comparar los dos con el mismo mensaje si algo se comporta
    # raro; cuando lleve unas semanas en producción, se retira.
    from app.conversacion.ejecutor import Ejecutor
    from app.conversacion.interprete import Interprete
    from app.conversacion.mundo import Mundo
    from app.conversacion.ojos import Ojos
    from app.conversacion.pipeline import Pipeline
    from app.conversacion.redactor import Redactor

    contexto = SqliteContexto(db)

    # El dibujante de previsualizaciones. Si falta la foto base o las
    # máscaras, se queda en None y el bot sigue sin enseñarle cómo queda —
    # peor conversación, ninguna caída.
    from app.adapters.render.huellita import RenderDeHuellitas

    base = s.imagenes_fuentes_dir / "huellita_base.jpg"
    mascaras = s.imagenes_fuentes_dir / "huellita_mascaras.png"
    render = (
        RenderDeHuellitas(base, mascaras, s.renders_dir)
        if base.is_file() and mascaras.is_file()
        else None
    )
    if render is None:
        log.warning("sin foto base: el bot no podrá enseñar cómo queda el anillo")

    # La tabla de envíos por ciudad. Si el CSV no está, se cobra el nacional
    # por defecto y nadie se entera: un pedido no se cae por un archivo.
    fletes = None
    try:
        from app.adapters.repositories.fletes_sqlite import SqliteFletes

        # En la base, editable desde el panel (29/09). El CSV es la semilla
        # de la primera vez; desde ahí manda la tabla.
        fletes = SqliteFletes(db, s.fletes_csv)
    except Exception as exc:  # pragma: no cover - depende del entorno
        log.warning("sin tabla de fletes (%s): se cobra el envío nacional", exc)

    # Los colores de circón: nombre, tinte y acabado editables en el panel
    # (30/09). Se aplican ANTES de armar la asesora: su prompt lleva los nombres.
    colores = None
    try:
        from app.adapters.repositories.colores_sqlite import SqliteColores

        colores = SqliteColores(db)
    except Exception as exc:  # pragma: no cover - depende del entorno
        log.warning("sin tabla de colores (%s): se usan los de fábrica", exc)

    mundo = Mundo(orders, customers, products, contexto, render=render, fletes=fletes)
    prompt = (
        Path(__file__).resolve().parents[1] / "prompts" / "interpretacion_v1.txt"
    ).read_text(encoding="utf-8")
    catalogo_txt = "\n".join(
        f"- {p.sku}: {p.nombre} ({p.precio_cop} COP, {p.huellitas} huellitas)"
        for p in products.list_active()
        if p.categoria == "anillos"  # la cadena no se ofrece (03/10)
    )
    # EL MODELO GRANDE, solo para los turnos que el pequeño no entendió.
    #
    # Vacío = no hay segundo intento y todo funciona como siempre. Se construye
    # con el MISMO adaptador, solo cambiando el nombre del modelo: un modelo más
    # fuerte no es una pieza nueva del sistema, es el mismo puerto con otro peso
    # detrás. El día que sea un modelo hospedado, lo único que cambia es esta
    # línea. Ver `Settings.llm_fuerte_model`.
    llm_fuerte = None
    if s.llm_fuerte_model and s.llm_backend != "fake":
        # El proveedor se decide por el nombre del modelo, sin otra variable.
        if s.llm_fuerte_model.startswith("claude"):
            if not s.anthropic_api_key:
                log.error(
                    "LLM_FUERTE_MODEL=%s necesita ANTHROPIC_API_KEY en el .env. "
                    "Sin ella no hay segundo intento.",
                    s.llm_fuerte_model,
                )
            else:
                from app.adapters.llm.anthropic_client import ClaudeLLM

                llm_fuerte = ClaudeLLM(s.llm_fuerte_model, s.anthropic_api_key)
        elif s.llm_backend == "ollama":
            llm_fuerte = OllamaLLM(model=s.llm_fuerte_model, host=s.ollama_host)
        else:
            log.error(
                "LLM_FUERTE_MODEL=%s no es un modelo en línea: sin segundo intento.",
                s.llm_fuerte_model,
            )
        if llm_fuerte is not None:
            log.info(
                "segundo intento con %s cuando no se entienda nada",
                s.llm_fuerte_model,
            )

    def _historial(conv_id: str) -> list[dict]:
        """Los últimos mensajes RECIENTES, del más viejo al más nuevo.

        Se le pasa al modelo grande SOLO en los turnos de rescate. La forma se
        traduce aquí —`direccion` es del adaptador— para que el gestor
        conversacional no sepa cómo está guardada una conversación.

        Con VENTANA DE TIEMPO: los mensajes de hace tres días hablan de otro
        momento, muchas veces de otro anillo. Dárselos al modelo para entender
        el mensaje de ahora es justo la contaminación que se quiere evitar.
        """
        from datetime import UTC, datetime, timedelta

        desde = datetime.now(UTC) - timedelta(hours=s.ventana_reciente_horas)
        recientes = []
        for m in conversaciones.historial(conv_id, limite=12):
            try:
                cuando = datetime.fromisoformat(m.get("created_at") or "")
            except ValueError:
                cuando = None
            if cuando is not None and cuando < desde:
                continue
            recientes.append(
                {
                    # 'OUT' en mayúscula: es lo que guarda `registrar_saliente`.
                    "de": "bot"
                    if (m.get("direccion") or "").upper() == "OUT"
                    else "clienta",
                    "texto": m.get("texto"),
                }
            )
        return recientes

    from app.conversacion.desempate import DesempateHistorico

    bot = Pipeline(
        interprete=Interprete(
            llm,
            prompt,
            catalogo_txt,
            ojos=Ojos(vision=ojos, media=media, vision_fuerte=ojos_fuertes),
            llm_fuerte=llm_fuerte,
            historial=_historial,
        ),
        mundo=mundo,
        ejecutor=Ejecutor(
            mundo, desempate=DesempateHistorico(llm_fuerte) if llm_fuerte else None
        ),
        # La redacción libre viene APAGADA. Es la única fase que puede decir
        # algo falso, y no se enciende sin el validador de hechos midiendo.
        redactor=Redactor(),
    )

    # --- la asesora (ADR 0014) ---
    #
    # Lee la conversación entera y propone una jugada que Python valida. Solo
    # con IA en línea y clave: sin ellas, el gestor por etiquetas sigue siendo
    # quien contesta. Si ninguna IA contesta a mitad de un turno, el turno
    # queda pendiente y se reintenta solo (ADR 0027).
    if (
        s.conversacion_motor == "asesora"
        and s.llm_backend == "claude"
        and s.anthropic_api_key
    ):
        from app.adapters.llm.anthropic_client import ClaudeLLM
        from app.adapters.repositories.csv_files import cargar_promociones_csv
        from app.conversacion.asesora import Asesora, HechosDelNegocio

        hechos = HechosDelNegocio.del_catalogo(products.list_active())
        hechos.promociones = tuple(cargar_promociones_csv(s.promociones_csv))
        prompt_asesora = (
            Path(__file__).resolve().parents[1] / "prompts" / "asesora_v1.txt"
        ).read_text(encoding="utf-8")

        def _descargar(adjunto: dict) -> bytes | None:
            referencia_media = adjunto.get("media_id") or adjunto.get("url")
            return media.download(referencia_media) if referencia_media else None

        # Los oídos: sin ellos, una nota de voz se contesta pidiéndole que lo
        # escriba. Con ellos, la venta sigue sin que la clienta teclee nada.
        oidos = None
        if s.transcripcion_backend == "groq" and s.groq_api_key:
            from app.adapters.llm.oidos import OidosDeGroq

            oidos = OidosDeGroq(s.groq_api_key, s.groq_modelo_audio)
            log.info("notas de voz: se transcriben con %s", s.groq_modelo_audio)
        elif s.transcripcion_backend == "groq":
            log.error(
                "TRANSCRIPCION_BACKEND=groq necesita GROQ_API_KEY: las notas de "
                "voz se seguirán contestando con «¿me lo escribes?»"
            )

        basico, fuerte = _modelos_con_respaldo(s)
        bot = Asesora(
            mundo,
            basico,
            prompt_asesora,
            hechos,
            llm_fuerte=fuerte,
            # Sin gestor de reglas: si Claude falla, frase amable + Lía + aviso
            # (Asesora._si_falla_la_ia). Decidido para producción el 25/09.
            respaldo=None,
            descargar=_descargar,
            oidos=oidos,
            avisar=avisos.avisar if avisos is not None else None,
            talla_la_confirma_lia=s.talla_la_confirma_lia,
            guardar_foto=_guardar_foto_de(s),
            apertura_peludito=s.apertura_peludito,
        )
        log.info("conversación: asesora con %s", s.llm_basico_model)

    from app.workers.vigia_del_tunel import VigiaDelTunel

    c = Container(
        settings=s,
        db=db,
        products=products,
        customers=customers,
        orders=orders,
        payments=payments,
        gateway=gateway,
        llm=llm,
        media=deps.media,
        idempotency=idempotency,
        outbox=outbox,
        conversaciones=conversaciones,
        avisos=avisos,
        bot=bot,
        crm=crm,
        contexto=contexto,
        canales=canales,
        whatsapp=whatsapp,
        graph=graph,
    )
    c.decisiones = SqliteDecisiones(db) if s.registrar_decisiones else None
    c.colores = colores
    c.render = render
    try:
        from app.adapters.repositories.analitica_sqlite import SqliteAnalitica

        c.analitica = SqliteAnalitica(db)
    except Exception as exc:  # pragma: no cover - el análisis no tumba el bot
        log.warning("sin tabla de análisis (%s)", exc)
    # Se entera de que no está entrando nada. Solo con canal de verdad: en
    # consola no hay webhooks que esperar.
    if s.channel_backend == "whatsapp":
        from app.adapters.repositories.webhook_log import ultimo as ultimo_webhook

        registro = s.sqlite_path.parent / "webhook_log.jsonl"
        c.vigia = VigiaDelTunel(
            conversaciones.ultimo_saliente,
            lambda: ultimo_webhook(registro),
            avisos=avisos,
        )
    c.dispatcher = OutboxDispatcher(
        outbox,
        canales,
        conversaciones,
        intervalo_s=s.dispatcher_interval_s,
        avisos=avisos,
        informar=c.informar_que_no_llego,
        copiar=lambda conv, m: c._copiar_salientes_al_crm(conv, [m]),
        anotar=lambda conv, texto: c.crm.nota(conv, texto) if c.crm else None,
    )

    # --- el Excel de ventas (ADR 0015) ---
    if s.repository_backend == "sqlite" and s.ventas_cada_s > 0:
        from app.adapters.excel.libro_ventas import LibroDeVentas
        from app.adapters.repositories.ventas import BaseDeVentas
        from app.workers.ventas import SincronizadorDeVentas

        c.ventas = SincronizadorDeVentas(
            BaseDeVentas(db),
            LibroDeVentas(s.ventas_excel),
            s.ventas_cada_s,
            despues=c.refrescar_analitica,
        )
    # --- el ERP en Google Sheets: se llena solo (app.domain.erp) ---
    credenciales = s.google_service_account_json
    if (
        s.repository_backend == "sqlite"
        and s.sheets_spreadsheet_id
        and credenciales
        and Path(credenciales).is_file()
    ):
        from app.adapters.erp.finanzas import guardar as guardar_finanzas
        from app.adapters.erp.sheets import ErpEnSheets, SheetsDeGoogle
        from app.adapters.repositories.ventas import BaseDeVentas
        from app.domain import erp as erp_dominio

        base = BaseDeVentas(db)
        try:
            c.erp = ErpEnSheets(
                SheetsDeGoogle(s.sheets_spreadsheet_id, Path(credenciales)),
                # Desde «Pasar a real» solo los pedidos de verdad (01/10).
                pedidos=lambda: erp_dominio.solo_reales(
                    base.pedidos(), s.ventas_reales_desde
                ),
                cuando=base.cuando,
                cada_s=s.erp_cada_s,
                accesos=lambda: _filas_de_accesos(s),
                hoja_de_accesos=NOMBRE_DE_LA_HOJA,
                foto=lambda hoja: guardar_finanzas(hoja, s.finanzas_foto_del_erp),
            )
            log.info("ERP: Google Sheets conectado (se llena solo)")
        except Exception as exc:  # una credencial rota no tumba el bot
            log.warning("ERP apagado: no se pudo abrir la credencial (%s)", exc)

    # --- la venta a Meta (13/10): `META_DATASET_MENSAJES` ---
    if s.meta_dataset_mensajes and s.wa_access_token and s.wa_business_account_id:
        from app.adapters.conversiones_meta import ConversionesDeMeta

        c.conversiones = ConversionesDeMeta(
            s.meta_dataset_mensajes, s.wa_access_token, s.wa_business_account_id
        )
        log.info("ventas a Meta: ENCENDIDAS (dataset %s)", s.meta_dataset_mensajes)

    # --- recordatorios (04/10): `RECORDATORIOS=true` ---
    if s.recordatorios and s.repository_backend == "sqlite":
        from app.adapters.repositories.recordatorios import (
            CharlasParaRecordar,
            RegistroDeRecordatorios,
        )
        from app.workers.recordatorios import Recordador, juez_con

        def _nombre_de(conv: str) -> str:
            from app.domain.models import Channel

            clienta = customers.get_by_channel_user(
                Channel.WHATSAPP.value, conv.rsplit(":", 1)[-1]
            )
            return (clienta.nombre or "") if clienta is not None else ""

        c.recordador = Recordador(
            mundo,
            CharlasParaRecordar(db),
            RegistroDeRecordatorios(db),
            c.enviar_a_la_clienta,
            nombre_de=_nombre_de,
            anotar_en_la_charla=mundo.anotar_mensaje_de_humano,
            intervalo_s=s.recordatorios_cada_s,
            en_el_hilo=lambda f: c.agrupador.en_el_hilo(f),
            ocupada=lambda conv: c.agrupador is not None and c.agrupador.ocupada(conv),
            ventana_abierta=conversaciones.ventana_abierta,
            con_plantilla=s.recordatorio_con_plantilla,
            # La IA lee la charla antes de cada uno (10/10): si hubo desinterés,
            # por pequeño que sea, no sale.
            juez=juez_con(bot._llm) if getattr(bot, "_llm", None) is not None else None,
            por_dias=_por_dias(s, products) if s.recordatorios_modo == "dias" else None,
        )
        log.info(
            "recordatorios ENCENDIDOS (%s; plantillas: %s)",
            "por días, de 10 a. m. a 7 p. m."
            if s.recordatorios_modo == "dias"
            else "solo 9 a. m. y 5 p. m.",
            "sí" if s.recordatorio_con_plantilla else "no",
        )

    c.agrupador = Agrupador(
        c.procesar_mensaje,
        espera_s=s.agrupar_segundos,
        tope_s=s.agrupar_tope_segundos,
        inmediato=c.es_primer_mensaje,
    )
    if c.agrupador.activo:
        log.info(
            "agrupando mensajes: %.1f s de calma (máximo %.0f s) por si sigue "
            "escribiendo; el primer mensaje no espera",
            s.agrupar_segundos,
            s.agrupar_tope_segundos,
        )
    log.info(
        "capas de modelo · básico=%s · potente=%s · fotos=%s",
        getattr(llm, "model", s.llm_backend),
        s.llm_fuerte_model or "(ninguno)",
        s.llm_vision_model or s.ollama_vision_model or "(sin lector)",
    )
    log.info(
        "contenedor listo · repo=%s llm=%s canal=%s pago=%s · db=%s",
        s.repository_backend,
        s.llm_backend,
        s.channel_backend,
        s.payment_backend,
        s.sqlite_path.name,
    )
    return c


def _checkpointer(s: Settings):
    """Checkpoints de LangGraph en el mismo archivo SQLite.

    Con esto la conversación sobrevive a un reinicio del servidor: el cliente
    sigue donde iba en vez de empezar de cero.

    En la Fase 6 esto pasa a `PostgresSaver`, que además permite varios workers.
    """
    import sqlite3

    try:
        from langgraph.checkpoint.sqlite import SqliteSaver
    except ModuleNotFoundError as exc:  # pragma: no cover - depende del entorno
        # Un ModuleNotFoundError enterrado en una traza de 40 líneas no le dice
        # a nadie qué hacer. Este mensaje sí.
        raise RuntimeError(
            "Falta la librería de checkpoints en disco. Instálala con:\n\n"
            "    pip install langgraph-checkpoint-sqlite\n\n"
            "(o, para poner al día todo el entorno de una vez:\n"
            "    pip install -r requirements-dev.txt )"
        ) from exc

    con = sqlite3.connect(str(s.sqlite_path), check_same_thread=False)
    saver = SqliteSaver(con)
    saver.setup()
    return saver


_singleton: Container | None = None


def get_container() -> Container:
    global _singleton
    if _singleton is None:
        _singleton = build_container()
    return _singleton


def reset_container() -> None:
    """Solo para tests: fuerza que el próximo `get_container()` construya uno nuevo."""
    global _singleton
    if _singleton is not None:
        _singleton.cerrar()
    _singleton = None
