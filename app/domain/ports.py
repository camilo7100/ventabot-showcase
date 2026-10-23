"""PUERTOS: las interfaces que el dominio necesita del mundo exterior.

Este archivo es el corazón de la arquitectura hexagonal (puertos y adaptadores).
Son ~80 líneas de `Protocol` y son literalmente lo que te va a permitir:

    - correr con Google Sheets hoy
    - migrar a PostgreSQL cambiando UNA variable de entorno
    - enchufar SAP en v3 sin tocar una línea de lógica de negocio
    - testear todo el dominio con adaptadores en memoria, en milisegundos

Usamos `typing.Protocol` (structural typing) en vez de `abc.ABC`: los
adaptadores NO necesitan heredar de nada, solo tener los métodos correctos.
Eso significa que el adaptador tampoco tiene que importar el dominio para
"registrarse", y el acoplamiento queda en cero.
"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol, runtime_checkable

from pydantic import BaseModel

from app.domain.models import (
    Customer,
    InboundMessage,
    Order,
    OrderEvent,
    OutboundMessage,
    Payment,
    Product,
)
from app.domain.order_state import OrderState
from app.domain.personalizacion import Huellita, Personalizacion
from app.domain.vision import LecturaDeImagen


class TokenDelCanalCaducado(Exception):
    """Las credenciales del canal ya no sirven: renovarlas es trabajo HUMANO.

    Vive en el dominio, y no en el adaptador de WhatsApp, porque el
    despachador es genérico: Instagram tendrá exactamente el mismo problema y
    debe tratarse igual.

    Se separa del resto de errores de red por una razón práctica: los demás
    son transitorios y merecen reintento con espera creciente; este no mejora
    solo. Reintentarlo cinco veces llena el log de ruido idéntico y esconde
    lo único que importa, que es "ve al panel y genera un token nuevo".
    """


class ConflictoDeEstado(Exception):
    """Bloqueo optimista: otro proceso ya cambió el estado del pedido.

    Se lanza cuando `update_status(..., expected_current=X)` no encuentra el
    pedido en el estado X. Es la señal de que un webhook duplicado o un worker
    concurrente llegó primero. Casi siempre la respuesta correcta es: releer el
    pedido y decidir de nuevo (o simplemente no hacer nada, porque el otro
    proceso ya hizo el trabajo).
    """


# ---------------------------------------------------------------------------
# Repositorios
# ---------------------------------------------------------------------------


@runtime_checkable
class ProductRepository(Protocol):
    def list_active(self) -> list[Product]: ...
    def get(self, sku: str) -> Product | None: ...
    def search(self, query: str, limit: int = 10) -> list[Product]: ...


@runtime_checkable
class CustomerRepository(Protocol):
    def get(self, customer_id: str) -> Customer | None:
        """Por id. Es lo único que trae un pedido: `Order.customer_id`.

        Sin esto, para avisarle a la clienta que su anillo está listo habría
        que adivinar su canal y su número, que es justo lo que el pedido no
        guarda —a propósito, para no duplicar el dato en dos sitios.
        """
        ...

    def get_by_channel_user(self, channel: str, user_id: str) -> Customer | None:
        """Por (canal, id del canal). Es como llega un mensaje entrante."""
        ...

    def upsert(self, customer: Customer) -> Customer: ...


@runtime_checkable
class OrderRepository(Protocol):
    """Siete métodos. Toda la superficie que el dominio necesita.

    Cualquier backend que implemente estos siete es intercambiable:
    Sheets, PostgreSQL, SAP, o un dict en memoria para tests.
    """

    def get(self, order_id: str) -> Order | None: ...
    def get_by_code(self, codigo: str) -> Order | None: ...
    def get_active_for_customer(self, customer_id: str) -> Order | None: ...
    def create(self, order: Order, idem_key: str) -> Order: ...

    def update_status(
        self, order_id: str, nuevo: OrderState, *, expected_current: OrderState
    ) -> Order:
        """Actualiza con BLOQUEO OPTIMISTA.

        En SQL esto es:
            UPDATE orders SET estado=%s WHERE id=%s AND estado=%s RETURNING *

        Si afecta 0 filas -> ConflictoDeEstado. Sin esto, un webhook duplicado
        puede saltar estados y despachar sin cobrar.
        """
        ...

    def guardar_personalizacion(
        self, order_id: str, personalizacion: Personalizacion, indice: int | None = None
    ) -> Order:
        """Guarda lo que la clienta eligió: colores, grabado, talla.

        Es un método aparte de `update_status` a propósito: cambiar de color
        no es cambiar de estado, y meterlo ahí obligaría a inventar
        transiciones falsas cada vez que alguien corrige un nombre.

        `indice` es la línea (el anillo, desde 0) de un pedido de VARIOS
        anillos (02/10); None = todas, que en un pedido de uno es lo mismo.

        A diferencia de `update_status`, esto NO lleva bloqueo optimista: dos
        mensajes seguidos de la misma clienta corrigiendo el color no son un
        conflicto, son una corrección. El último gana, que es justo lo que
        ella espera.
        """
        ...

    def guardar_pedido(self, order: Order) -> Order:
        """Guarda cambios que NO son de estado ni de personalización.

        Hoy: las fotos del anillo terminado. Sin bloqueo optimista, por lo
        mismo que `guardar_personalizacion`: subir dos fotos seguidas no es
        un conflicto, es subir dos fotos.

        Lo que NUNCA debe pasar por aquí es el `estado`: para eso está
        `update_status`, que es el único con el `WHERE estado = ?` que impide
        despachar sin cobrar. Un método genérico de guardado que también
        escribiera el estado dejaría esa puerta abierta.
        """
        ...

    def append_event(self, event: OrderEvent) -> None:
        """APPEND-ONLY. `idempotency_key` es UNIQUE: reinsertar es no-op."""
        ...


@runtime_checkable
class PaymentRepository(Protocol):
    def get(self, payment_id: str) -> Payment | None: ...
    def get_by_reference(self, reference: str) -> Payment | None: ...
    def create(self, payment: Payment) -> Payment: ...
    def update(self, payment: Payment) -> Payment: ...


@runtime_checkable
class IdempotencyStore(Protocol):
    def mark_processed(self, source: str, external_id: str) -> bool:
        """True si es la PRIMERA vez que se ve este evento; False si ya se procesó.

        Implementación SQL:
            INSERT INTO processed_events (source, external_id)
            VALUES (%s,%s) ON CONFLICT DO NOTHING RETURNING 1
        """
        ...


@runtime_checkable
class Outbox(Protocol):
    """Patrón outbox: nunca envíes directamente.

    Escribe el mensaje saliente en la misma transacción que el cambio de
    negocio; un proceso aparte lo despacha. Así "el negocio cambió" y "el
    cliente se enteró" son atómicos.
    """

    def enqueue(
        self, message: OutboundMessage, *, enviar_despues: datetime | None = None
    ) -> bool:
        """`enviar_despues`: no sale antes de esa hora (la plantilla de emergencia
        de noche espera a las 8 a. m., 16/10).

        True si entró; False si esa clave ya estaba (no se duplica). Con eso la
        copia a Chatwoot no sale dos veces cuando Meta reintenta (17/10)."""
        ...

    def pending(self, limit: int = 50) -> list[OutboundMessage]: ...

    def mark_sent(self, idempotency_key: str, external_id: str | None = None) -> None:
        """`external_id` es el id que devuelve el canal (el `wamid` de Meta).

        Guardarlo no es cosmético: es lo único que permite cruzar "yo mandé
        esto" con "Meta dice que pasó aquello" cuando hay que reclamar un
        mensaje que no llegó. El puerto no lo declaraba y el adaptador sí lo
        recibía; lo encontró el test de contratos.
        """
        ...

    def mark_failed(self, idempotency_key: str, error: str) -> bool:
        """Reintenta más tarde; True si se rindió y ese mensaje ya no sale."""
        ...

    def descartar(self, idempotency_key: str, motivo: str) -> None:
        """No sale nunca, y no es un fallo: ya no hacía falta (la disculpa
        programada a una clienta que volvió a escribir antes, 17/10)."""
        ...

    def posponer(self, idempotency_key: str, segundos: int, motivo: str) -> None:
        """Reintentar más tarde SIN gastar un intento.

        Para esperas legítimas, no para errores. La ventana de 24 h de
        WhatsApp es el caso: puede estar cerrada días y se abre sola cuando
        la clienta escribe. Tratarla como fallo abandona el mensaje a los
        cinco intentos, que son unos minutos.
        """
        ...


# ---------------------------------------------------------------------------
# Servicios externos
# ---------------------------------------------------------------------------


@runtime_checkable
class LLMPort(Protocol):
    """La ÚNICA puerta por la que entra un LLM al sistema.

    Nota deliberada: no hay un método `chat()` que devuelva texto libre.
    Solo `extract()`, que devuelve un modelo Pydantic validado. Eso obliga
    estructuralmente a que todo uso del LLM pase por un schema cerrado.
    """

    def extract(
        self,
        system_prompt: str,
        user_text: str,
        schema: type[BaseModel],
        *,
        images: list[bytes] | None = None,
    ) -> BaseModel:
        """Extrae información estructurada. Debe validar contra `schema`.

        La implementación debe usar constrained decoding real
        (Ollama: `format=<json_schema>`), no prompt + parseo esperanzado.
        """
        ...


@runtime_checkable
class AvisosPort(Protocol):
    """Avisarle a QUIEN OPERA que algo se rompió. No a la clienta.

    Lo que más duele no es fallar: es fallar y que nadie se entere. Un token
    vencido se ve igual que un día tranquilo hasta que hay tres clientas sin
    respuesta.

    El aviso dice QUÉ se rompió, nunca a quién: viaja por un servicio de
    terceros. Puede no existir; entonces el problema solo queda en el log.
    """

    def avisar(self, titulo: str, detalle: str = "", clave: str = "") -> bool:
        """`clave` agrupa avisos iguales para no repetirlos cada minuto."""
        ...


@runtime_checkable
class OidosPort(Protocol):
    """Los OÍDOS: pasar una nota de voz a texto.

    Aparte de los ojos y del que conversa, por lo mismo: oír, mirar y entender
    son tres problemas distintos que se cambian por razones distintas.

    Puede no existir. Sin oídos, una nota de voz se contesta pidiéndole con
    cariño que lo escriba, que es lo que se hacía hasta ahora: transcribir
    ayuda a vender, pero nunca puede ser lo que tumbe un turno.
    """

    def transcribir(self, datos: bytes, mime: str = "") -> str | None:
        """El texto de la nota de voz, o None si no se pudo."""
        ...


@runtime_checkable
class VisionPort(Protocol):
    """Los OJOS. Un modelo aparte del que lee texto, y a propósito.

    Leer «quiero un anillo de dos huellitas» y mirar un anillo apoyado en una
    regla son dos problemas distintos, se resuelven con modelos distintos y
    se cambian por razones distintas. Con un solo puerto, mejorar la lectura
    de fotos obligaría a tocar la conversación entera.

    Devuelve una `LecturaDeImagen`: lo que VE. Qué hacer con eso lo decide
    `vision.entender()`, que es Python puro y no tiene opinión probabilística.

    Puede no existir: cuando no hay ojos configurados, las fotos se guardan y
    se marcan para que las mire una persona, y la conversación sigue igual.
    """

    def leer(self, imagen: bytes, *, pista: str = "") -> LecturaDeImagen:
        """Mira UNA imagen. `pista` dice qué estamos esperando ver.

        La pista no obliga a nada —una clienta puede mandar el comprobante
        cuando le pedías la talla— pero sube mucho el acierto de un modelo
        pequeño: mirar buscando algo es más fácil que mirar a ver qué hay.
        """
        ...


@runtime_checkable
class CrmPort(Protocol):
    """Copia la conversación a donde una persona pueda mirarla.

    El bot atiende; el CRM es para que Lía pueda ver, buscar y meterse cuando
    haga falta. Son dos cosas distintas y por eso hay un puerto: hoy es
    Chatwoot, mañana puede ser otra cosa o nada.

    NUNCA puede bloquear ni fallar hacia arriba. Copiar a un CRM es lo menos
    importante que pasa en un turno: si el CRM está caído, la clienta no se
    puede quedar esperando por eso.
    """

    def registrar(
        self,
        conversation_id: str,
        texto: str,
        *,
        entrante: bool,
        nombre: str = "",
        etiquetas: tuple[str, ...] = (),
        atributos: dict | None = None,
        adjuntos: tuple[dict, ...] = (),
    ) -> None: ...

    def marcar_estado(self, conversation_id: str, estado: str) -> None:
        """«pending» = la lleva el bot; «open» = necesita (o tiene) a una persona."""
        ...

    def es_eco(self, conversation_id: str, texto: str) -> bool:
        """¿Este mensaje «de Lía» es en realidad una copia que hizo el bot?"""
        ...

    def seguimiento(
        self,
        conversation_id: str,
        seguimiento,
        atributos: dict | None = None,
        *,
        nombre: str = "",
        persona_atendiendo: bool = False,
    ) -> None:
        """Pone la conversación al día: etapa, alertas, ficha y estado."""
        ...

    def nota(self, conversation_id: str, texto: str) -> None:
        """Una nota privada para Lía, que la clienta no ve."""
        ...

    def quitar_etiqueta(self, conversation_id: str, etiqueta: str) -> None: ...

    def asignar(self, conversation_id: str, quien: str | int) -> None:
        """Quién la lleva en el CRM: `"bot"` = VentaBot; un número = esa persona."""
        ...


@runtime_checkable
class RenderPort(Protocol):
    """Dibuja cómo va a quedar la huellita con unos colores.

    Devuelve el NOMBRE LÓGICO de la imagen, igual que el resto del material:
    qué archivo es y bajo qué URL se sirve lo resuelve el adaptador.

    Puede devolver None. Una previsualización es un regalo, no un requisito:
    si no sale, la conversación sigue exactamente igual y la clienta no se
    entera de nada.
    """

    def previsualizar(self, huellitas: list[Huellita]) -> str | None: ...


class PaymentLink(BaseModel):
    url: str
    reference: str
    gateway_id: str | None = None


@runtime_checkable
class PaymentGateway(Protocol):
    def create_link(
        self,
        *,
        reference: str,
        amount_cop: int,
        description: str,
        expires_in_hours: int = 72,
    ) -> PaymentLink: ...

    def verify_webhook(self, raw_body: bytes, signature: str) -> bool:
        """HMAC sobre el BODY CRUDO, con `hmac.compare_digest`."""
        ...

    def fetch_transaction(self, transaction_id: str) -> dict:
        """Re-consulta la API. NUNCA confíes solo en el payload del webhook.

        Es la defensa contra replay y contra webhooks falsificados.
        """
        ...


@runtime_checkable
class ChannelClient(Protocol):
    """Adaptador de salida de un canal: traduce OutboundMessage a la API real."""

    def send(self, message: OutboundMessage) -> str:
        """Envía y devuelve el id externo del mensaje."""
        ...

    def parse_webhook(self, payload: dict) -> list[InboundMessage]: ...
    def verify_signature(self, raw_body: bytes, signature: str) -> bool: ...


@runtime_checkable
class MediaPort(Protocol):
    def download(self, media_id_or_url: str) -> bytes:
        """Descarga INMEDIATA.

        WhatsApp: 2 pasos con token, la URL expira en 5 minutos.
        Instagram: URL de CDN directa, sin token, efímera.
        """
        ...

    def store(self, data: bytes, *, filename: str) -> str:
        """Guarda en tu storage y devuelve una URL estable. Devuelve también el hash."""
        ...
