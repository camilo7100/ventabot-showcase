"""Persistencia en SQLite para la Fase 1.

Por qué SQLite y no seguir en memoria: si el proceso se reinicia y la
deduplicación vivía en un `set()` de Python, Meta reenvía los webhooks y el
cliente recibe la misma respuesta dos veces. La memoria RAM no es un lugar
donde guardar "esto ya lo hice".

Por qué SQLite y todavía no Postgres: en la Fase 1 no hay concurrencia real
(un solo proceso) y SQLite es cero infraestructura — un archivo. En la Fase 6
se cambia por Postgres, que es lo único que aguanta varios workers a la vez.
Las dos implementan los mismos Protocols, así que la migración es cambiar
`REPOSITORY_BACKEND`.

⚠️ SQLite tiene UN SOLO ESCRITOR a la vez, incluso con WAL. Con dos workers
concurrentes verías `database is locked`. Es exactamente la razón por la que
Postgres es obligatorio en producción.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path

from app.domain.anuncios import toques_que_se_conservan
from app.domain.contexto import ContextoConversacional
from app.domain.models import (
    Channel,
    Customer,
    Order,
    OrderEvent,
    OutboundMessage,
)
from app.domain.order_state import OrderState
from app.domain.personalizacion import Personalizacion
from app.domain.ports import ConflictoDeEstado

ESQUEMA = """
PRAGMA journal_mode=WAL;
PRAGMA busy_timeout=5000;

-- Deduplicación: la defensa contra los reintentos de Meta y de las pasarelas.
CREATE TABLE IF NOT EXISTS processed_events (
    source       TEXT NOT NULL,
    external_id  TEXT NOT NULL,
    processed_at TEXT NOT NULL,
    PRIMARY KEY (source, external_id)
);

-- Patrón outbox: el mensaje saliente se ESCRIBE aquí, no se envía en caliente.
-- Así "el negocio cambió" y "el cliente se enteró" pueden ser atómicos.
CREATE TABLE IF NOT EXISTS outbox (
    idempotency_key TEXT PRIMARY KEY,
    channel         TEXT NOT NULL,
    destinatario    TEXT NOT NULL,
    payload         TEXT NOT NULL,
    intentos        INTEGER NOT NULL DEFAULT 0,
    enviar_despues  TEXT,
    sent_at         TEXT,
    external_id     TEXT,
    error           TEXT,
    created_at      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_outbox_pendientes
    ON outbox (sent_at, enviar_despues);

-- Historial de mensajes. Son datos personales: ver retención en reglas.yaml.
CREATE TABLE IF NOT EXISTS messages (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id TEXT NOT NULL,
    direccion       TEXT NOT NULL,          -- IN | OUT
    channel         TEXT NOT NULL,
    external_id     TEXT,
    texto           TEXT,
    payload         TEXT,
    created_at      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_messages_conv ON messages (conversation_id, id);

-- Estado de la conversación. `ventana_24h_hasta` es lo que decide si podemos
-- mandar texto libre o si Meta solo acepta una plantilla aprobada.
CREATE TABLE IF NOT EXISTS conversations (
    conversation_id   TEXT PRIMARY KEY,
    channel           TEXT NOT NULL,
    channel_user_id   TEXT NOT NULL,
    ultimo_entrante   TEXT,
    ventana_24h_hasta TEXT,
    handoff_hasta     TEXT,
    created_at        TEXT NOT NULL
);

-- Clientas. Se identifican por (canal, id del canal): el mismo número puede
-- escribir por WhatsApp y por Instagram y son la misma persona, pero eso se
-- resuelve más adelante; hoy son dos filas y no pasa nada.
CREATE TABLE IF NOT EXISTS customers (
    id              TEXT PRIMARY KEY,
    channel         TEXT NOT NULL,
    channel_user_id TEXT NOT NULL,
    payload         TEXT NOT NULL,
    created_at      TEXT NOT NULL,
    UNIQUE (channel, channel_user_id)
);

-- PEDIDOS. La fuente de verdad del negocio.
--
-- El pedido se guarda como JSON en `payload`, y las columnas de al lado son
-- solo lo que hace falta para BUSCAR y para el bloqueo optimista. Es una
-- decisión deliberada para la Fase 2: el modelo del pedido todavía se está
-- moviendo (esta semana le crecieron la personalización y el abono fijo), y
-- una tabla con veinte columnas obligaría a una migración por cada cambio.
--
-- `estado` SÍ es columna propia, y no un campo dentro del JSON, porque de eso
-- depende el UPDATE ... WHERE estado=? que impide despachar sin cobrar.
-- Un candado no puede vivir dentro de un blob.
--
-- En la Fase 6, con el modelo ya estable, esto pasa a Postgres con columnas
-- de verdad. El puerto no se entera: son los mismos siete métodos.
CREATE TABLE IF NOT EXISTS orders (
    id          TEXT PRIMARY KEY,
    codigo      TEXT NOT NULL UNIQUE,
    customer_id TEXT NOT NULL,
    estado      TEXT NOT NULL,
    payload     TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_orders_cliente ON orders (customer_id, created_at);
CREATE INDEX IF NOT EXISTS ix_orders_estado  ON orders (estado);

-- Idempotencia de creación: `create(pedido, idem_key)` se puede llamar dos
-- veces porque LangGraph re-ejecuta nodos enteros al reanudar.
CREATE TABLE IF NOT EXISTS order_idem (
    idem_key   TEXT PRIMARY KEY,
    order_id   TEXT NOT NULL,
    created_at TEXT NOT NULL
);

-- AUDITORÍA. Append-only: aquí no hay UPDATE ni DELETE, nunca.
-- Es lo que permite responder "¿por qué este pedido está despachado?" seis
-- meses después, y es lo que exige cualquier auditoría de plata.
CREATE TABLE IF NOT EXISTS order_events (
    idempotency_key TEXT PRIMARY KEY,
    order_id        TEXT NOT NULL,
    estado_anterior TEXT,
    estado_nuevo    TEXT NOT NULL,
    actor           TEXT NOT NULL,
    motivo          TEXT,
    created_at      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_eventos_pedido ON order_events (order_id, created_at);

-- CONTEXTO CONVERSACIONAL. Lo que la conversación recuerda: qué se le mostró,
-- de qué se está hablando, qué quedó a medias.
--
-- Vive aquí y NO en el checkpoint de LangGraph a propósito. Un checkpoint solo
-- se puede leer desde dentro de su propia conversación; esta tabla se puede
-- consultar entera. El día que haya recordatorios («lleva cuatro días sin
-- mandar la talla»), ese trabajo va a preguntar por TODOS los procesos
-- abiertos de TODAS las clientas, y necesita justamente esto.
CREATE TABLE IF NOT EXISTS conv_contexto (
    conversation_id TEXT PRIMARY KEY,
    payload         TEXT NOT NULL,
    actualizado     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_contexto_fecha ON conv_contexto (actualizado);

-- DECISIONES. Por qué el bot hizo lo que hizo en cada turno: qué capa
-- respondió (reglas, modelo básico, modelo potente), con qué contexto, si
-- buscó en el historial, cuánto tardó y cuánto costó. SIN textos ni teléfonos:
-- la conversación va como una huella. Append-only, como la auditoría.
CREATE TABLE IF NOT EXISTS decisiones (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    ts            TEXT NOT NULL,
    conversacion  TEXT NOT NULL,
    capa          TEXT NOT NULL,
    accion        TEXT,
    escalado      INTEGER NOT NULL DEFAULT 0,
    historial     INTEGER NOT NULL DEFAULT 0,
    persona       INTEGER NOT NULL DEFAULT 0,
    corregido     INTEGER NOT NULL DEFAULT 0,
    error         TEXT,
    costo_usd     REAL NOT NULL DEFAULT 0,
    latencia_ms   INTEGER NOT NULL DEFAULT 0,
    payload       TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_decisiones_ts ON decisiones (ts);
"""


log = logging.getLogger("ventabot.sqlite")


def _ahora() -> str:
    return datetime.now(UTC).isoformat()


def _cuando_lo_escribio(payload: dict | None) -> datetime | None:
    """La hora en que la clienta escribió (el `timestamp` de Meta), si viene."""
    try:
        return datetime.fromtimestamp(int((payload or {})["timestamp"]), tz=UTC)
    except (KeyError, TypeError, ValueError):
        return None


class SqliteDB:
    """Conexión compartida y con lock. Un solo archivo, un solo escritor."""

    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        # check_same_thread=False porque FastAPI atiende en varios hilos.
        # El lock de abajo es lo que hace que sea seguro.
        self._con = sqlite3.connect(str(path), check_same_thread=False)
        self._con.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        with self._lock:
            self._con.executescript(ESQUEMA)
            self._con.commit()

    def ejecutar(self, sql: str, params: tuple = ()) -> sqlite3.Cursor:
        with self._lock:
            cur = self._con.execute(sql, params)
            self._con.commit()
            return cur

    def consultar(self, sql: str, params: tuple = ()) -> list[sqlite3.Row]:
        with self._lock:
            return list(self._con.execute(sql, params))

    def cerrar(self) -> None:
        with self._lock:
            self._con.close()


class SqliteIdempotencyStore:
    """Implementa `IdempotencyStore`.

    `INSERT ... ON CONFLICT DO NOTHING` es atómico: si dos webhooks idénticos
    llegan a la vez, solo uno "gana" y el otro se descarta. Esa atomicidad es
    justo lo que un `set()` en memoria no te puede dar.
    """

    def __init__(self, db: SqliteDB) -> None:
        self._db = db

    def mark_processed(self, source: str, external_id: str) -> bool:
        cur = self._db.ejecutar(
            "INSERT INTO processed_events (source, external_id, processed_at) "
            "VALUES (?, ?, ?) ON CONFLICT DO NOTHING",
            (source, external_id, _ahora()),
        )
        return cur.rowcount > 0

    def vistos(self, source: str) -> int:
        return self._db.consultar(
            "SELECT COUNT(*) c FROM processed_events WHERE source = ?", (source,)
        )[0]["c"]


class SqliteOutbox:
    """Implementa `Outbox`. El despachador lee de aquí y envía."""

    def __init__(self, db: SqliteDB) -> None:
        self._db = db

    def enqueue(
        self, message: OutboundMessage, *, enviar_despues: datetime | None = None
    ) -> bool:
        cur = self._db.ejecutar(
            "INSERT INTO outbox (idempotency_key, channel, destinatario, payload, "
            "created_at, enviar_despues) VALUES (?, ?, ?, ?, ?, ?) "
            "ON CONFLICT DO NOTHING",
            (
                message.idempotency_key,
                message.channel.value,
                message.to,
                message.model_dump_json(),
                _ahora(),
                enviar_despues.isoformat() if enviar_despues else None,
            ),
        )
        return cur.rowcount > 0

    def pending(self, limit: int = 50) -> list[OutboundMessage]:
        filas = self._db.consultar(
            "SELECT payload FROM outbox WHERE sent_at IS NULL "
            "AND (enviar_despues IS NULL OR enviar_despues <= ?) "
            "ORDER BY created_at LIMIT ?",
            (_ahora(), limit),
        )
        return [OutboundMessage.model_validate_json(f["payload"]) for f in filas]

    def mark_sent(self, idempotency_key: str, external_id: str | None = None) -> None:
        self._db.ejecutar(
            "UPDATE outbox SET sent_at = ?, external_id = ?, error = NULL "
            "WHERE idempotency_key = ?",
            (_ahora(), external_id, idempotency_key),
        )

    def descartar(self, idempotency_key: str, motivo: str) -> None:
        self._db.ejecutar(
            "UPDATE outbox SET sent_at = ?, error = ? WHERE idempotency_key = ?",
            (_ahora(), f"descartado: {motivo}", idempotency_key),
        )

    def posponer(self, idempotency_key: str, segundos: int, motivo: str) -> None:
        """Vuelve a intentarlo más tarde SIN gastar un intento.

        Es distinto de `mark_failed`: ahí cada fallo cuenta, y a los cinco el
        mensaje se abandona. Eso está bien para un error —Meta caída, red mala—
        pero es exactamente lo contrario de lo que hay que hacer cuando la
        ventana de 24 h está cerrada.

        Una ventana cerrada no es un fallo: es una espera. Puede durar días, y
        se abre sola en cuanto la clienta escribe. Contarla como fallo
        abandonaría el cobro del saldo a los pocos minutos, en silencio, y
        nadie se enteraría hasta que la clienta preguntara por su anillo.
        """
        espera = datetime.now(UTC) + timedelta(seconds=segundos)
        self._db.ejecutar(
            "UPDATE outbox SET enviar_despues = ?, error = ? WHERE idempotency_key = ?",
            (espera.isoformat(), motivo[:500], idempotency_key),
        )

    def mark_failed(self, idempotency_key: str, error: str) -> bool:
        """Reintento con espera creciente: 30 s, 60 s, 120 s… hasta 5 intentos.

        Devuelve True si se rindió (el quinto): ese mensaje ya NO va a salir."""
        fila = self._db.consultar(
            "SELECT intentos FROM outbox WHERE idempotency_key = ?", (idempotency_key,)
        )
        intentos = (fila[0]["intentos"] if fila else 0) + 1
        if intentos >= 5:
            # Se rinde y lo marca como enviado-con-error para no reintentar
            # eternamente. Queda el `error` para que un humano lo revise.
            self._db.ejecutar(
                "UPDATE outbox SET intentos = ?, error = ?, sent_at = ? "
                "WHERE idempotency_key = ?",
                (intentos, error[:500], _ahora(), idempotency_key),
            )
            return True
        espera = datetime.now(UTC) + timedelta(seconds=30 * 2 ** (intentos - 1))
        self._db.ejecutar(
            "UPDATE outbox SET intentos = ?, error = ?, enviar_despues = ? "
            "WHERE idempotency_key = ?",
            (intentos, error[:500], espera.isoformat(), idempotency_key),
        )
        return False

    def por_external_id(self, external_id: str) -> OutboundMessage | None:
        """El mensaje que Meta conoce por ese `wamid` (para su acuse «failed»)."""
        filas = self._db.consultar(
            "SELECT payload FROM outbox WHERE external_id = ? LIMIT 1", (external_id,)
        )
        return OutboundMessage.model_validate_json(filas[0]["payload"]) if filas else None

    def atascados(self) -> list[dict]:
        """Mensajes que fallaron 5 veces. Deberías alertar sobre esto."""
        return [
            dict(f)
            for f in self._db.consultar(
                "SELECT idempotency_key, destinatario, intentos, error FROM outbox "
                "WHERE intentos >= 5"
            )
        ]


class SqliteConversaciones:
    """Registra la ventana de 24 h de Meta y el historial de mensajes."""

    VENTANA_HORAS = 24

    def __init__(self, db: SqliteDB) -> None:
        self._db = db

    def registrar_entrante(
        self,
        conversation_id: str,
        channel: str,
        user_id: str,
        external_id: str,
        texto: str | None,
        payload: dict,
    ) -> None:
        ahora = datetime.now(UTC)
        # La ventana cuenta desde que ELLA lo escribió, no desde que llegó: un
        # mensaje que Meta reintenta dos días después (14/10) ya no la abre.
        escrito = min(_cuando_lo_escribio(payload) or ahora, ahora)
        hasta = (escrito + timedelta(hours=self.VENTANA_HORAS)).isoformat()
        self._db.ejecutar(
            "INSERT INTO conversations (conversation_id, channel, channel_user_id, "
            "ultimo_entrante, ventana_24h_hasta, created_at) VALUES (?,?,?,?,?,?) "
            "ON CONFLICT(conversation_id) DO UPDATE SET "
            "ultimo_entrante = excluded.ultimo_entrante, "
            "ventana_24h_hasta = MAX(COALESCE(ventana_24h_hasta, ''), "
            "excluded.ventana_24h_hasta)",
            (
                conversation_id,
                channel,
                user_id,
                ahora.isoformat(),
                hasta,
                ahora.isoformat(),
            ),
        )
        self._db.ejecutar(
            "INSERT INTO messages (conversation_id, direccion, channel, external_id, "
            "texto, payload, created_at) VALUES (?,'IN',?,?,?,?,?)",
            (
                conversation_id,
                channel,
                external_id,
                texto,
                json.dumps(payload, ensure_ascii=False)[:20000],
                ahora.isoformat(),
            ),
        )

    def registrar_saliente(
        self,
        conversation_id: str,
        channel: str,
        texto: str,
        external_id: str | None,
        payload: dict | None = None,
    ) -> None:
        """Guarda lo que salió. `payload` lleva la foto o el video, si lo hubo.

        Sin eso, en el panel una foto era la palabra «[image]»: Lía no podía
        ver el prototipo que el bot le acababa de mandar a la clienta.
        """
        import json

        self._db.ejecutar(
            "INSERT INTO messages (conversation_id, direccion, channel, external_id, "
            "texto, payload, created_at) VALUES (?,'OUT',?,?,?,?,?)",
            (
                conversation_id,
                channel,
                external_id,
                texto,
                json.dumps(payload or {}, ensure_ascii=False),
                _ahora(),
            ),
        )

    def ultimo_saliente(self):
        """Cuándo salió el último mensaje, o None si no ha salido ninguno.

        Lo usa el vigía: si acabamos de responder y Meta no ha acusado recibo
        de nada, el camino de entrada está roto.
        """
        from datetime import UTC, datetime

        fila = self._db.consultar(
            "SELECT created_at FROM messages WHERE direccion='OUT' "
            "ORDER BY id DESC LIMIT 1"
        )
        if not fila:
            return None
        try:
            momento = datetime.fromisoformat(fila[0]["created_at"])
        except (TypeError, ValueError):
            return None
        return momento if momento.tzinfo else momento.replace(tzinfo=UTC)

    def ventana_abierta(self, conversation_id: str) -> bool:
        """Fuera de la ventana de 24 h, Meta SOLO acepta plantillas aprobadas.

        El despachador consulta esto antes de enviar. Es el chequeo que evita
        el error `(#131047) Message failed to send because more than 24 hours
        have passed`, que es de los más comunes al empezar.
        """
        filas = self._db.consultar(
            "SELECT ventana_24h_hasta FROM conversations WHERE conversation_id = ?",
            (conversation_id,),
        )
        if not filas or not filas[0]["ventana_24h_hasta"]:
            return False
        return datetime.fromisoformat(filas[0]["ventana_24h_hasta"]) > datetime.now(UTC)

    def recientes(self, limite: int = 30) -> list[dict]:
        """Las conversaciones con actividad más reciente, para el panel.

        Trae el último mensaje de cada una y de qué lado vino, que es lo único
        que hace falta para decidir a cuál entrar.
        """
        filas = self._db.consultar(
            "SELECT c.conversation_id, c.channel_user_id, c.ultimo_entrante, "
            "       c.ventana_24h_hasta, m.direccion, m.texto, m.payload, m.created_at "
            "FROM conversations c "
            "LEFT JOIN messages m ON m.id = ("
            "    SELECT id FROM messages WHERE conversation_id = c.conversation_id "
            "    ORDER BY id DESC LIMIT 1) "
            "ORDER BY COALESCE(m.created_at, c.ultimo_entrante) DESC LIMIT ?",
            (limite,),
        )
        return [dict(f) for f in filas]

    def historial(self, conversation_id: str, limite: int = 20) -> list[dict]:
        return [
            dict(f)
            for f in self._db.consultar(
                "SELECT direccion, texto, payload, created_at FROM messages "
                "WHERE conversation_id = ? ORDER BY id DESC LIMIT ?",
                (conversation_id, limite),
            )
        ][::-1]


class SqliteCustomerRepository:
    """Implementa `CustomerRepository` sobre SQLite."""

    def __init__(self, db: SqliteDB) -> None:
        self._db = db

    def get(self, customer_id: str) -> Customer | None:
        filas = self._db.consultar(
            "SELECT payload FROM customers WHERE id = ?", (customer_id,)
        )
        return Customer.model_validate_json(filas[0]["payload"]) if filas else None

    def get_by_channel_user(self, channel: str, user_id: str) -> Customer | None:
        """La firma es la del PUERTO: `channel` es un `str`, no un `Channel`.

        La primera versión de este adaptador recibía un `Channel`, y por eso
        no cumplía `CustomerRepository` aunque pareciera correcta. El sistema
        arrancaba en verde y reventaba con un AttributeError el día que
        alguien lo usara de verdad. Ahora hay un test que comprueba que los
        dos adaptadores cumplan el mismo contrato.
        """
        valor = channel.value if isinstance(channel, Channel) else str(channel)
        filas = self._db.consultar(
            "SELECT payload FROM customers WHERE channel = ? AND channel_user_id = ?",
            (valor, user_id),
        )
        return Customer.model_validate_json(filas[0]["payload"]) if filas else None

    def upsert(self, customer: Customer) -> Customer:
        """Si ya existe alguien con ese (canal, id), se CONSERVA su id.

        Sin esto, cada mensaje crearía una clienta nueva y sus pedidos
        quedarían repartidos entre varias personas que en realidad son una.
        """
        existente = self.get_by_channel_user(
            customer.channel.value, customer.channel_user_id
        )
        if existente is not None:
            customer = customer.model_copy(
                update={
                    "id": existente.id,
                    # Ni de qué anuncio llegó (ADR 0028).
                    **toques_que_se_conservan(existente, customer),
                }
            )
        self._db.ejecutar(
            "INSERT INTO customers (id, channel, channel_user_id, payload, "
            "created_at) VALUES (?,?,?,?,?) "
            "ON CONFLICT(channel, channel_user_id) "
            "DO UPDATE SET payload = excluded.payload",
            (
                customer.id,
                customer.channel.value,
                customer.channel_user_id,
                customer.model_dump_json(),
                _ahora(),
            ),
        )
        return customer


#: Estados en los que un pedido ya no está "en curso". Se listan aquí, junto a
#: la consulta que los usa, para que no haya que ir a buscarlos a otro archivo.
ESTADOS_CERRADOS = ("ENTREGADO", "CANCELADO", "REEMBOLSO")

# Las dos consultas que filtran por ESTADOS_CERRADOS van escritas COMPLETAS y
# literales, con sus tres `?` a mano.
#
# La versión anterior las armaba con un f-string. Funcionaba —solo se
# interpolaban interrogantes— pero deja SQL construido con cadenas, que es la
# forma que tiene la inyección, y obliga a quien lo lea (o al linter) a
# demostrar que en este caso concreto no lo es. Escribirlas literales quita la
# duda de un vistazo. Un test comprueba que la cantidad de `?` siga cuadrando
# con ESTADOS_CERRADOS si alguien agrega un estado.
SQL_PEDIDO_ACTIVO = (
    "SELECT payload FROM orders WHERE customer_id = ? "
    "AND estado NOT IN (?,?,?) "
    "ORDER BY created_at DESC LIMIT 1"
)
SQL_PEDIDOS_ABIERTOS = "SELECT payload FROM orders WHERE estado NOT IN (?,?,?)"


class SqliteOrderRepository:
    """Implementa `OrderRepository`. Los siete métodos, sobre un archivo.

    LA PIEZA QUE IMPORTA
    ====================
    `update_status` hace `UPDATE ... WHERE id=? AND estado=?` y comprueba
    `rowcount`. Si afecta cero filas, alguien llegó antes y se lanza
    `ConflictoDeEstado`. Eso es lo que impide que un webhook de pago repetido
    —Bold reintenta cinco veces— haga avanzar el pedido dos estados y termine
    despachando un anillo cobrado a medias.

    Es exactamente el mismo SQL que se usará en Postgres. Cambiará el driver,
    no la idea.
    """

    def __init__(self, db: SqliteDB) -> None:
        self._db = db

    # -- lectura ------------------------------------------------------------

    def _de_fila(self, fila) -> Order:
        return Order.model_validate_json(fila["payload"])

    def get(self, order_id: str) -> Order | None:
        filas = self._db.consultar("SELECT payload FROM orders WHERE id = ?", (order_id,))
        return self._de_fila(filas[0]) if filas else None

    def get_by_code(self, codigo: str) -> Order | None:
        filas = self._db.consultar(
            "SELECT payload FROM orders WHERE codigo = ?", (codigo,)
        )
        return self._de_fila(filas[0]) if filas else None

    def get_active_for_customer(self, customer_id: str) -> Order | None:
        filas = self._db.consultar(SQL_PEDIDO_ACTIVO, (customer_id, *ESTADOS_CERRADOS))
        return self._de_fila(filas[0]) if filas else None

    # -- escritura ----------------------------------------------------------

    def create(self, order: Order, idem_key: str) -> Order:
        """Upsert idempotente por `idem_key`.

        LangGraph re-ejecuta el NODO COMPLETO al reanudar, así que esto se
        llama dos veces con normalidad. La tabla `order_idem` es la que hace
        que la segunda vez no cree un pedido nuevo.
        """
        ya = self._db.consultar(
            "SELECT order_id FROM order_idem WHERE idem_key = ?", (idem_key,)
        )
        if ya:
            existente = self.get(ya[0]["order_id"])
            if existente is not None:
                return existente

        self._db.ejecutar(
            "INSERT INTO orders (id, codigo, customer_id, estado, payload, "
            "created_at, updated_at) VALUES (?,?,?,?,?,?,?) "
            "ON CONFLICT(id) DO UPDATE SET "
            "  estado = excluded.estado,"
            "  payload = excluded.payload,"
            "  updated_at = excluded.updated_at",
            (
                order.id,
                order.codigo,
                order.customer_id,
                order.estado,
                order.model_dump_json(),
                order.created_at.isoformat(),
                _ahora(),
            ),
        )
        self._db.ejecutar(
            "INSERT OR IGNORE INTO order_idem (idem_key, order_id, created_at) "
            "VALUES (?,?,?)",
            (idem_key, order.id, _ahora()),
        )
        return order

    def update_status(
        self, order_id: str, nuevo: OrderState, *, expected_current: OrderState
    ) -> Order:
        """Bloqueo optimista. El `WHERE estado = ?` es toda la defensa."""
        actual = self.get(order_id)
        if actual is None:
            raise ConflictoDeEstado(f"pedido {order_id} no existe")

        actualizado = actual.model_copy(
            update={"estado": nuevo.value, "updated_at": datetime.now(UTC)}
        )
        cur = self._db.ejecutar(
            "UPDATE orders SET estado = ?, payload = ?, updated_at = ? "
            "WHERE id = ? AND estado = ?",
            (
                nuevo.value,
                actualizado.model_dump_json(),
                _ahora(),
                order_id,
                expected_current.value,
            ),
        )
        if cur.rowcount == 0:
            # Cero filas = otro proceso ya lo movió. Releer y decidir de nuevo,
            # o no hacer nada porque el otro ya hizo el trabajo.
            raise ConflictoDeEstado(
                f"esperaba {expected_current.value}, encontró {actual.estado}"
            )
        return actualizado

    def guardar_pedido(self, order: Order) -> Order:
        actual = self.get(order.id)
        if actual is None:
            raise ConflictoDeEstado(f"pedido {order.id} no existe")
        guardado = order.model_copy(
            update={"estado": actual.estado, "updated_at": datetime.now(UTC)}
        )
        self._db.ejecutar(
            "UPDATE orders SET payload = ?, updated_at = ? WHERE id = ?",
            (guardado.model_dump_json(), _ahora(), order.id),
        )
        return guardado

    def guardar_personalizacion(
        self, order_id: str, personalizacion: Personalizacion, indice: int | None = None
    ) -> Order:
        pedido = self.get(order_id)
        if pedido is None:
            raise ConflictoDeEstado(f"pedido {order_id} no existe")
        actualizado = pedido.model_copy(
            update={
                "items": [
                    i.model_copy(update={"personalizacion": personalizacion})
                    if indice is None or k == indice
                    else i
                    for k, i in enumerate(pedido.items)
                ],
                "updated_at": datetime.now(UTC),
            }
        )
        # Sin `WHERE estado = ?`: corregir un color no es una transición, y
        # dos correcciones seguidas no son un conflicto. Gana la última.
        self._db.ejecutar(
            "UPDATE orders SET payload = ?, updated_at = ? WHERE id = ?",
            (actualizado.model_dump_json(), _ahora(), order_id),
        )
        return actualizado

    def append_event(self, event: OrderEvent) -> None:
        """APPEND-ONLY. `INSERT OR IGNORE` sobre la clave de idempotencia:
        registrar dos veces la misma transición es un no-op, no un error."""
        self._db.ejecutar(
            "INSERT OR IGNORE INTO order_events (idempotency_key, order_id, "
            "estado_anterior, estado_nuevo, actor, motivo, created_at) "
            "VALUES (?,?,?,?,?,?,?)",
            (
                event.idempotency_key,
                event.order_id,
                event.estado_anterior,
                event.estado_nuevo,
                event.actor,
                event.motivo,
                event.created_at.isoformat(),
            ),
        )

    # -- consultas de operación --------------------------------------------

    def eventos(self, order_id: str) -> list[OrderEvent]:
        return [
            OrderEvent(
                order_id=f["order_id"],
                estado_anterior=f["estado_anterior"],
                estado_nuevo=f["estado_nuevo"],
                actor=f["actor"],
                motivo=f["motivo"] or "",
                idempotency_key=f["idempotency_key"],
                created_at=datetime.fromisoformat(f["created_at"]),
            )
            for f in self._db.consultar(
                "SELECT * FROM order_events WHERE order_id = ? ORDER BY created_at",
                (order_id,),
            )
        ]

    def por_estado(self, estado: OrderState) -> list[Order]:
        """Para el panel de operación: «¿qué hay en producción?»."""
        return [
            self._de_fila(f)
            for f in self._db.consultar(
                "SELECT payload FROM orders WHERE estado = ? ORDER BY created_at",
                (estado.value,),
            )
        ]

    def abiertos(self) -> list[Order]:
        """Todo lo que sigue en curso. Es lo que alimenta el panel del taller.

        Con 53 anillos al mes esto son unas decenas de filas: se traen todas y
        se reparten en Python. Cuando sean miles habrá que paginar, y este
        docstring será el aviso de que llegó el momento.
        """
        return [
            self._de_fila(f)
            for f in self._db.consultar(SQL_PEDIDOS_ABIERTOS, ESTADOS_CERRADOS)
        ]

    def de_cliente(
        self, customer_id: str, *, solo_activos: bool = False, limite: int = 50
    ) -> list[Order]:
        """Los pedidos de UNA clienta, del más reciente al más viejo.

        Usa el índice `ix_orders_cliente`. Es la consulta del contexto
        operativo (`solo_activos=True`, cada turno) y la de la recuperación
        histórica (todos, solo cuando la clienta habla del pasado). Antes el
        turno traía los abiertos de TODAS las clientas y filtraba en Python.
        """
        if solo_activos:
            filas = self._db.consultar(
                "SELECT payload FROM orders WHERE customer_id = ? "
                "AND estado NOT IN (?,?,?) ORDER BY created_at DESC LIMIT ?",
                (customer_id, *ESTADOS_CERRADOS, limite),
            )
        else:
            filas = self._db.consultar(
                "SELECT payload FROM orders WHERE customer_id = ? "
                "ORDER BY created_at DESC LIMIT ?",
                (customer_id, limite),
            )
        return [self._de_fila(f) for f in filas]

    def contar_cerrados(self, customer_id: str) -> int:
        filas = self._db.consultar(
            "SELECT COUNT(*) AS n FROM orders "
            "WHERE customer_id = ? AND estado IN (?,?,?)",
            (customer_id, *ESTADOS_CERRADOS),
        )
        return int(filas[0]["n"]) if filas else 0

    def con_talla_por_revisar(self) -> list[Order]:
        """Pedidos cuya talla salió dudosa de la foto.

        Es la cola de trabajo que hace posible la decisión que tomó el
        negocio: el bot decide siempre y nadie se queda esperando, pero nada
        se funde sin que un humano haya visto las dudosas.
        """
        pedidos = [
            self._de_fila(f)
            for f in self._db.consultar(SQL_PEDIDOS_ABIERTOS, ESTADOS_CERRADOS)
        ]
        return [
            o for o in pedidos if any(i.personalizacion.talla_revisar for i in o.items)
        ]


class SqliteDecisiones:
    """El registro de decisiones y las métricas que salen de él."""

    def __init__(self, db: SqliteDB) -> None:
        self._db = db

    def guardar(self, registro) -> None:
        d = registro.a_dict()
        self._db.ejecutar(
            "INSERT INTO decisiones (ts, conversacion, capa, accion, escalado, "
            "historial, "
            "persona, corregido, error, costo_usd, latencia_ms, payload) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                d["ts"],
                d["conversacion"],
                d["routing_layer"],
                d["action"],
                int(d["escalated"]),
                int(d["historical_lookup"]),
                int(d["human_review"]),
                int(d["corrected"]),
                d["error"] or None,
                float(d["cost_usd"]),
                int(d["latency_ms"]),
                json.dumps(d, ensure_ascii=False),
            ),
        )

    def metricas(self, desde: str | None = None) -> dict:
        """Lo que se quiere saber de un vistazo. `desde` es un ISO opcional."""
        columnas = (
            "SELECT capa, escalado, historial, persona, corregido, error, costo_usd, "
            "latencia_ms FROM decisiones"
        )
        filas = self._db.consultar(
            f"{columnas} WHERE ts >= ?" if desde else columnas,
            (desde,) if desde else (),
        )
        total = len(filas)
        if not total:
            return {"turnos": 0}

        def pct(n: int) -> float:
            return round(100 * n / total, 1)

        capas: dict[str, int] = {}
        for f in filas:
            capas[f["capa"]] = capas.get(f["capa"], 0) + 1
        latencias = sorted(f["latencia_ms"] for f in filas)
        return {
            "turnos": total,
            "sin_ia_pct": pct(capas.get("reglas", 0)),
            "basico_pct": pct(capas.get("basico", 0)),
            "potente_pct": pct(capas.get("fuerte", 0)),
            "escaladas": sum(f["escalado"] for f in filas),
            "consultas_historicas": sum(f["historial"] for f in filas),
            "a_una_persona": sum(f["persona"] for f in filas),
            "acciones_corregidas": sum(f["corregido"] for f in filas),
            "errores": sum(1 for f in filas if f["error"]),
            "latencia_p50_ms": latencias[len(latencias) // 2],
            "latencia_p95_ms": latencias[
                min(len(latencias) - 1, int(len(latencias) * 0.95))
            ],
            "costo_total_usd": round(sum(f["costo_usd"] for f in filas), 4),
            "costo_por_turno_usd": round(sum(f["costo_usd"] for f in filas) / total, 5),
        }


class SqliteContexto:
    """Guarda y recupera el contexto conversacional.

    El objeto entero va como JSON en una columna. Es pequeño (unas menciones y
    unos procesos) y se lee y escribe siempre completo, así que partirlo en
    tablas solo habría añadido joins para nada.

    Lo que SÍ es columna es `actualizado`, porque de ahí colgará la consulta
    del día que el bot tome la iniciativa: «dame las conversaciones con
    procesos abiertos que nadie ha tocado en cuatro días».
    """

    def __init__(self, db: SqliteDB) -> None:
        self._db = db

    def cargar(self, conversation_id: str) -> ContextoConversacional:
        """Nunca devuelve None: si no hay nada, devuelve uno vacío.

        Un `None` aquí obligaría a comprobarlo en cada sitio que lo usa, y
        bastaría olvidarlo una vez para que la primera conversación de una
        clienta reventara.
        """
        filas = self._db.consultar(
            "SELECT payload FROM conv_contexto WHERE conversation_id = ?",
            (conversation_id,),
        )
        if not filas:
            return ContextoConversacional(conversation_id=conversation_id)
        try:
            return ContextoConversacional.model_validate_json(filas[0]["payload"])
        except ValueError:
            # El formato cambió entre versiones. Perder el contexto es
            # molesto; reventar en cada mensaje de esa clienta, mucho peor.
            log.warning("contexto ilegible en %s: se empieza de cero", conversation_id)
            return ContextoConversacional(conversation_id=conversation_id)

    def guardar(self, ctx: ContextoConversacional) -> None:
        self._db.ejecutar(
            "INSERT INTO conv_contexto (conversation_id, payload, actualizado) "
            "VALUES (?,?,?) ON CONFLICT(conversation_id) DO UPDATE SET "
            "payload = excluded.payload, actualizado = excluded.actualizado",
            (ctx.conversation_id, ctx.model_dump_json(), _ahora()),
        )

    def recientes(self, limite: int = 200) -> list[ContextoConversacional]:
        """Las conversaciones con actividad más reciente (para el panel)."""
        return [
            self.cargar(f["conversation_id"])
            for f in self._db.consultar(
                "SELECT conversation_id FROM conv_contexto "
                "ORDER BY actualizado DESC LIMIT ?",
                (limite,),
            )
        ]

    def con_procesos_abiertos(self) -> list[ContextoConversacional]:
        """Todas las conversaciones que tienen algo a medias.

        Todavía no lo llama nadie. Es el gancho para los recordatorios: sin
        una consulta como esta, un bot propositivo tendría que recorrer las
        conversaciones una por una.
        """
        todos = [
            self.cargar(f["conversation_id"])
            for f in self._db.consultar(
                "SELECT conversation_id FROM conv_contexto ORDER BY actualizado DESC"
            )
        ]
        return [c for c in todos if c.abiertos()]
