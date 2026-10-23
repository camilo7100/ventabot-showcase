"""Nodos de negocio: Python puro, cero LLM, 100% deterministas.

Estos nodos son la mayor parte del sistema. Se testean sin red y sin modelo.
Si alguna vez necesitas un LLM aquí, párate y pregúntate por qué.
"""

from __future__ import annotations

from app.domain.models import (
    Channel,
    Order,
    PaymentKind,
    new_id,
)
from app.domain.order_state import ETIQUETA_CLIENTE, OrderState
from app.domain.ports import (
    ConflictoDeEstado,
    CustomerRepository,
    OrderRepository,
    PaymentGateway,
    PaymentRepository,
    ProductRepository,
)
from app.domain.pricing import cotizar, formatear_cop
from app.domain.services import (
    aplicar_cotizacion,
    generar_cobro,
    siguiente_codigo,
    transicionar,
)
from app.graph.state import ConvState

ENVIO_POR_DEFECTO_COP = 15_000


# ---------------------------------------------------------------------------


def make_cargar_contexto(customers: CustomerRepository, orders: OrderRepository):
    """Primer nodo del grafo: hidrata el estado con datos reales."""

    def cargar_contexto(state: ConvState) -> dict:
        customer = customers.get_by_channel_user(state["channel"], state["sender_id"])
        pedido = orders.get_active_for_customer(customer.id) if customer else None
        return {
            "customer_id": customer.id if customer else None,
            "customer": customer.model_dump(mode="json") if customer else None,
            "active_order": pedido.model_dump(mode="json") if pedido else None,
            "step": "contexto_cargado",
            "trace": [
                f"contexto: customer={'sí' if customer else 'no'} "
                f"pedido={'sí' if pedido else 'no'}"
            ],
        }

    return cargar_contexto


# ---------------------------------------------------------------------------


def make_catalogo(products: ProductRepository, limite: int = 10):
    """Muestra el portafolio.

    Devuelve OPCIONES abstractas. El adaptador de canal decide si eso se
    renderiza como lista interactiva (WhatsApp) o texto numerado (Instagram).
    """

    def catalogo(state: ConvState) -> dict:
        # Solo los anillos: la cadena no se ofrece (03/10).
        activos = [p for p in products.list_active() if p.categoria == "anillos"][:limite]
        return {
            "reply_kind": "catalogo",
            "reply_options": [
                {
                    "id": p.sku,
                    "title": p.nombre[:24],
                    "description": (
                        f"{formatear_cop(p.precio_cop)} · {p.dias_produccion} días"
                    ),
                }
                for p in activos
            ],
            "reply_slots": {"n_productos": len(activos)},
            "step": "catalogo",
            "trace": [f"catalogo: {len(activos)} productos"],
        }

    return catalogo


# ---------------------------------------------------------------------------


def make_cotizar(
    products: ProductRepository,
    orders: OrderRepository,
    customers: CustomerRepository,
):
    def cotizar_node(state: ConvState) -> dict:
        ent = state.get("entities") or {}
        sku = ent.get("sku")
        cantidad = int(ent.get("cantidad") or 1)

        if not sku:
            return {
                "reply_kind": "falta_sku",
                "reply_slots": {},
                "step": "cotizar_incompleto",
                "trace": ["cotizar: falta sku -> pedir producto"],
            }

        catalogo = {p.sku: p for p in products.list_active()}
        try:
            cot = cotizar(catalogo, [(sku, cantidad)], envio_cop=ENVIO_POR_DEFECTO_COP)
        except (KeyError, ValueError) as exc:
            return {
                "reply_kind": "error_cotizacion",
                "error": str(exc),
                "needs_human": True,
                "step": "cotizar_error",
                "trace": [f"cotizar: error {exc}"],
            }

        # Crea o actualiza el pedido en BORRADOR/COTIZADO.
        customer_id = state.get("customer_id")
        if customer_id is None:
            cliente = customers.upsert(_nuevo_cliente(state))
            customer_id = cliente.id

        activo = state.get("active_order")
        if activo is None:
            pedido = Order(
                codigo=siguiente_codigo(2026, abs(hash(new_id())) % 10_000),
                customer_id=customer_id,
                estado=OrderState.BORRADOR.value,
            )
            pedido = orders.create(pedido, idem_key=f"draft:{state['conversation_id']}")
        else:
            pedido = Order(**activo)

        pedido = aplicar_cotizacion(pedido, cot)
        orders.create(pedido, idem_key=f"quote:{pedido.id}:{cot.total_cop}")  # upsert

        if OrderState(pedido.estado) is not OrderState.COTIZADO:
            pedido = transicionar(
                orders,
                pedido,
                OrderState.COTIZADO,
                actor="bot",
                motivo="cotización enviada",
                idem_key=f"cot:{pedido.id}:{cot.total_cop}",
            )

        return {
            "active_order": pedido.model_dump(mode="json"),
            "reply_kind": "cotizacion",
            "reply_slots": {
                **cot.slots(),
                "codigo": pedido.codigo,
                "sku": sku,
                "cantidad": cantidad,
            },
            "reply_options": [
                {"id": "confirmar", "title": "Confirmar pedido"},
                {"id": "cambiar", "title": "Cambiar cantidad"},
                {"id": "humano", "title": "Hablar con alguien"},
            ],
            "step": "cotizado",
            "trace": [f"cotizar: {sku} x{cantidad} = {cot.total_cop}"],
        }

    return cotizar_node


def _nuevo_cliente(state: ConvState):
    from app.domain.models import Customer

    return Customer(
        channel=Channel(state["channel"]),
        channel_user_id=state["sender_id"],
    )


# ---------------------------------------------------------------------------


def make_crear_pedido(
    orders: OrderRepository,
    payments: PaymentRepository,
    gateway: PaymentGateway,
):
    """Confirma el pedido y genera el link del ANTICIPO.

    IDEMPOTENTE de punta a punta. Esto es obligatorio, no opcional:
    LangGraph re-ejecuta el nodo COMPLETO al reanudar tras un interrupt, y las
    pasarelas reintentan sus webhooks. Sin idempotencia aquí, generas dos links
    y cobras dos veces.
    """

    def crear_pedido(state: ConvState) -> dict:
        activo = state.get("active_order")
        if activo is None:
            return {
                "reply_kind": "sin_pedido",
                "step": "confirmar_sin_pedido",
                "trace": ["crear_pedido: no hay pedido activo"],
            }

        pedido = Order(**activo)
        try:
            if OrderState(pedido.estado) is OrderState.COTIZADO:
                pedido = transicionar(
                    orders,
                    pedido,
                    OrderState.CONFIRMADO,
                    actor="bot",
                    motivo="cliente confirmó",
                    idem_key=f"conf:{pedido.id}",
                )
            if OrderState(pedido.estado) is OrderState.CONFIRMADO:
                pedido = transicionar(
                    orders,
                    pedido,
                    OrderState.ESPERANDO_ANTICIPO,
                    actor="bot",
                    motivo="link de anticipo generado",
                    idem_key=f"esp-ant:{pedido.id}",
                )
        except ConflictoDeEstado:
            # Otro proceso ya avanzó el pedido. Relee y sigue: no es un error.
            pedido = orders.get(pedido.id) or pedido

        pago = generar_cobro(payments, gateway, pedido, PaymentKind.ANTICIPO)

        return {
            "active_order": pedido.model_dump(mode="json"),
            "reply_kind": "link_anticipo",
            "reply_cta_url": pago.payment_link_url,
            "reply_slots": {
                "codigo": pedido.codigo,
                "anticipo": pago.monto_esperado_cop,
                "saldo": pedido.saldo_cop,
                "total": pedido.total_cop,
            },
            "step": "esperando_anticipo",
            "trace": [f"crear_pedido: {pedido.codigo} link generado"],
        }

    return crear_pedido


# ---------------------------------------------------------------------------


def make_estado_pedido(orders: OrderRepository):
    def estado_pedido(state: ConvState) -> dict:
        activo = state.get("active_order")
        if activo is None:
            return {
                "reply_kind": "sin_pedido",
                "step": "estado_sin_pedido",
                "trace": ["estado: sin pedido activo"],
            }
        pedido = Order(**activo)
        estado = OrderState(pedido.estado)
        return {
            "reply_kind": "estado",
            "reply_slots": {
                "codigo": pedido.codigo,
                "estado": ETIQUETA_CLIENTE[estado],
                "total": pedido.total_cop,
                "anticipo": pedido.anticipo_cop,
                "saldo": pedido.saldo_cop,
            },
            "step": "estado_consultado",
            "trace": [f"estado: {pedido.codigo} = {estado.value}"],
        }

    return estado_pedido


# ---------------------------------------------------------------------------


def handoff(state: ConvState) -> dict:
    """Escala a un humano y CALLA al bot.

    Mientras `handoff` está activo, el worker no debe volver a correr el grafo
    para esta conversación (se controla en la tabla `conversations`, con
    `handoff_hasta`). Si no lo haces, el bot le sigue escribiendo encima al
    asesor humano y queda ridículo.

    En Instagram, este es el momento de usar el tag HUMAN_AGENT: extiende la
    ventana de respuesta de 24 horas a 7 días.
    """
    return {
        "needs_human": True,
        "reply_kind": "handoff",
        "reply_slots": {},
        "step": "handoff",
        "trace": ["handoff: escalado a humano"],
    }
