"""Adaptadores en memoria.

No son "solo para tests": son la PRUEBA de que la arquitectura funciona.
Si el dominio corre igual contra estos que contra Postgres, entonces el
dominio de verdad no sabe nada del almacenamiento — y la migración a SQL o
a SAP es cambiar una línea de configuración.

Además dan tests que corren en milisegundos, sin Docker y sin red.
"""

from __future__ import annotations

from app.domain.anuncios import toques_que_se_conservan
from app.domain.models import (
    Customer,
    Order,
    OrderEvent,
    OutboundMessage,
    Payment,
    Product,
    now_utc,
)
from app.domain.order_state import OrderState
from app.domain.ports import ConflictoDeEstado


class InMemoryProductRepository:
    def __init__(self, productos: list[Product] | None = None) -> None:
        self._p: dict[str, Product] = {p.sku: p for p in (productos or [])}

    def add(self, p: Product) -> None:
        self._p[p.sku] = p

    def list_active(self) -> list[Product]:
        return [p for p in self._p.values() if p.activo]

    def get(self, sku: str) -> Product | None:
        return self._p.get(sku)

    def search(self, query: str, limit: int = 10) -> list[Product]:
        q = query.lower()
        return [
            p
            for p in self.list_active()
            if q in p.nombre.lower() or q in p.descripcion.lower()
        ][:limit]


class InMemoryCustomerRepository:
    def __init__(self) -> None:
        self._c: dict[str, Customer] = {}

    @staticmethod
    def _k(channel: str, user_id: str) -> str:
        return f"{channel}:{user_id}"

    def get(self, customer_id: str) -> Customer | None:
        return next((c for c in self._c.values() if c.id == customer_id), None)

    def get_by_channel_user(self, channel: str, user_id: str) -> Customer | None:
        return self._c.get(self._k(channel, user_id))

    def upsert(self, customer: Customer) -> Customer:
        clave = self._k(customer.channel.value, customer.channel_user_id)
        # Igual que en SQLite: guardar otra cosa no borra de qué anuncio llegó.
        conservar = toques_que_se_conservan(self._c.get(clave), customer)
        if conservar:
            customer = customer.model_copy(update=conservar)
        self._c[clave] = customer
        return customer


class InMemoryOrderRepository:
    def __init__(self) -> None:
        self._o: dict[str, Order] = {}
        self._eventos: list[OrderEvent] = []
        self._idem: set[str] = set()

    def get(self, order_id: str) -> Order | None:
        return self._o.get(order_id)

    def get_by_code(self, codigo: str) -> Order | None:
        return next((o for o in self._o.values() if o.codigo == codigo), None)

    def get_active_for_customer(self, customer_id: str) -> Order | None:
        activos = [
            o
            for o in self._o.values()
            if o.customer_id == customer_id
            and OrderState(o.estado)
            not in {OrderState.ENTREGADO, OrderState.CANCELADO, OrderState.REEMBOLSO}
        ]
        return max(activos, key=lambda o: o.created_at) if activos else None

    def create(self, order: Order, idem_key: str) -> Order:
        """Upsert idempotente por `idem_key`.

        Importante: LangGraph re-ejecuta nodos completos al reanudar, así que
        `create` DEBE poder llamarse dos veces sin duplicar.
        """
        if idem_key in self._idem and order.id in self._o:
            return self._o[order.id]
        self._idem.add(idem_key)
        self._o[order.id] = order
        return order

    def abiertos(self) -> list[Order]:
        return [
            o
            for o in self._o.values()
            if OrderState(o.estado)
            not in {OrderState.ENTREGADO, OrderState.CANCELADO, OrderState.REEMBOLSO}
        ]

    def de_cliente(
        self, customer_id: str, *, solo_activos: bool = False, limite: int = 50
    ) -> list[Order]:
        """Los pedidos de una clienta, del más reciente al más viejo."""
        cerrados = {OrderState.ENTREGADO, OrderState.CANCELADO, OrderState.REEMBOLSO}
        suyos = [
            o
            for o in self._o.values()
            if o.customer_id == customer_id
            and not (solo_activos and OrderState(o.estado) in cerrados)
        ]
        return sorted(suyos, key=lambda o: o.created_at, reverse=True)[:limite]

    def contar_cerrados(self, customer_id: str) -> int:
        cerrados = {OrderState.ENTREGADO, OrderState.CANCELADO, OrderState.REEMBOLSO}
        return sum(
            1
            for o in self._o.values()
            if o.customer_id == customer_id and OrderState(o.estado) in cerrados
        )

    def guardar_pedido(self, order: Order) -> Order:
        actual = self._o.get(order.id)
        if actual is None:
            raise ConflictoDeEstado(f"pedido {order.id} no existe")
        # El estado NO se toca: viene de `update_status`, que es el que lleva
        # el candado. Aceptarlo aquí seria una puerta trasera al bloqueo.
        guardado = order.model_copy(
            update={"estado": actual.estado, "updated_at": now_utc()}
        )
        self._o[order.id] = guardado
        return guardado

    def guardar_personalizacion(
        self, order_id: str, personalizacion, indice: int | None = None
    ) -> Order:
        pedido = self._o.get(order_id)
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
                "updated_at": now_utc(),
            }
        )
        self._o[order_id] = actualizado
        return actualizado

    def update_status(
        self, order_id: str, nuevo: OrderState, *, expected_current: OrderState
    ) -> Order:
        actual = self._o.get(order_id)
        if actual is None:
            raise ConflictoDeEstado(f"pedido {order_id} no existe")
        # Bloqueo optimista: equivalente a
        #   UPDATE ... WHERE id=%s AND estado=%s
        if OrderState(actual.estado) is not expected_current:
            raise ConflictoDeEstado(
                f"esperaba {expected_current.value}, encontró {actual.estado}"
            )
        nuevo_pedido = actual.model_copy(
            update={"estado": nuevo.value, "updated_at": now_utc()}
        )
        self._o[order_id] = nuevo_pedido
        return nuevo_pedido

    def append_event(self, event: OrderEvent) -> None:
        # `idempotency_key` es UNIQUE: reinsertar es no-op, no error.
        if any(e.idempotency_key == event.idempotency_key for e in self._eventos):
            return
        self._eventos.append(event)

    # --- helpers de test ---
    def eventos(self, order_id: str) -> list[OrderEvent]:
        return [e for e in self._eventos if e.order_id == order_id]


class InMemoryPaymentRepository:
    def __init__(self) -> None:
        self._p: dict[str, Payment] = {}

    def get(self, payment_id: str) -> Payment | None:
        return self._p.get(payment_id)

    def get_by_reference(self, reference: str) -> Payment | None:
        return next(
            (p for p in self._p.values() if p.gateway_reference == reference), None
        )

    def create(self, payment: Payment) -> Payment:
        self._p[payment.id] = payment
        return payment

    def update(self, payment: Payment) -> Payment:
        self._p[payment.id] = payment
        return payment

    def all(self) -> list[Payment]:
        return list(self._p.values())


class InMemoryIdempotencyStore:
    def __init__(self) -> None:
        self._seen: set[tuple[str, str]] = set()

    def mark_processed(self, source: str, external_id: str) -> bool:
        key = (source, external_id)
        if key in self._seen:
            return False
        self._seen.add(key)
        return True


class InMemoryOutbox:
    def __init__(self) -> None:
        self._q: list[OutboundMessage] = []
        self._sent: set[str] = set()
        self._ultimo_pospuesto: tuple[str, int, str] | None = None

    def enqueue(self, message: OutboundMessage, *, enviar_despues=None) -> bool:
        if any(m.idempotency_key == message.idempotency_key for m in self._q):
            return False
        self._q.append(message)
        return True

    def pending(self, limit: int = 50) -> list[OutboundMessage]:
        return [m for m in self._q if m.idempotency_key not in self._sent][:limit]

    def mark_sent(self, idempotency_key: str, external_id: str | None = None) -> None:
        self._sent.add(idempotency_key)

    def descartar(self, idempotency_key: str, motivo: str) -> None:
        self._sent.add(idempotency_key)

    def mark_failed(self, idempotency_key: str, error: str) -> bool:
        return False  # en producción: incrementa intentos y programa reintento

    def posponer(self, idempotency_key: str, segundos: int, motivo: str) -> None:
        """En memoria no hay reloj: el mensaje simplemente se queda pendiente.

        Es suficiente para los tests, que es para lo que existe este
        adaptador. Lo que sí importa comprobar aquí es que el mensaje NO
        desaparezca, y eso se cumple.
        """
        self._ultimo_pospuesto = (idempotency_key, segundos, motivo)
