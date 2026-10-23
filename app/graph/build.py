"""Construcción del StateGraph.

Este archivo es el mapa completo del sistema en ~60 líneas legibles.
Cuando alguien pregunte "¿cómo funciona el bot?", se le muestra esto.

Nota deliberada: NO se usa `create_agent` ni `create_react_agent`. Un agente
libre tiene un espacio de decisión combinatorio; esta FSM tiene 7 destinos.
Cuando el error cuesta dinero real, el espacio de decisión debe ser enumerable.
"""

from __future__ import annotations

from dataclasses import dataclass

from langgraph.graph import END, START, StateGraph

from app.domain.ports import (
    CustomerRepository,
    LLMPort,
    MediaPort,
    OrderRepository,
    PaymentGateway,
    PaymentRepository,
    ProductRepository,
)
from app.graph.nodes.business import (
    handoff,
    make_cargar_contexto,
    make_catalogo,
    make_cotizar,
    make_crear_pedido,
    make_estado_pedido,
)
from app.graph.nodes.faq import faq
from app.graph.nodes.nlu import make_nlu_node
from app.graph.nodes.personalizar import make_personalizar
from app.graph.nodes.receipt import make_comprobante
from app.graph.nodes.respond import redactar
from app.graph.router import router
from app.graph.state import ConvState


@dataclass(frozen=True)
class Deps:
    """Inyección de dependencias explícita. Todo son PUERTOS, no implementaciones.

    En producción: SqlOrderRepository + OllamaLLM + BoldGateway.
    En tests:      InMemory* + FakeLLM + FakeGateway.
    Mismo grafo, mismo código, resultados verificables en milisegundos.
    """

    products: ProductRepository
    customers: CustomerRepository
    orders: OrderRepository
    payments: PaymentRepository
    gateway: PaymentGateway
    llm: LLMPort
    media: MediaPort


def build_graph(deps: Deps, checkpointer=None):
    """Arma y compila el grafo.

    Args:
        deps: los puertos.
        checkpointer: en dev `InMemorySaver()`; en producción
            `PostgresSaver.from_conn_string(DSN)` (requiere `.setup()` una vez).
            OJO: `thread_id` debe medir menos de 255 caracteres.
    """
    g = StateGraph(ConvState)

    g.add_node("cargar_contexto", make_cargar_contexto(deps.customers, deps.orders))
    g.add_node("nlu", make_nlu_node(deps.llm, deps.products))
    g.add_node("catalogo", make_catalogo(deps.products))
    g.add_node("cotizar", make_cotizar(deps.products, deps.orders, deps.customers))
    g.add_node(
        "crear_pedido",
        make_crear_pedido(deps.orders, deps.payments, deps.gateway),
    )
    g.add_node("estado_pedido", make_estado_pedido(deps.orders))
    g.add_node(
        "comprobante",
        make_comprobante(deps.llm, deps.media, deps.orders, deps.payments),
    )
    g.add_node("faq", faq)
    g.add_node("personalizar", make_personalizar(deps.products, deps.orders))
    g.add_node("handoff", handoff)
    g.add_node("redactar", redactar)

    g.add_edge(START, "cargar_contexto")
    g.add_edge("cargar_contexto", "nlu")

    # El router es Python puro: un dict.get con default. Ver app/graph/router.py.
    g.add_conditional_edges(
        "nlu",
        router,
        {
            "catalogo": "catalogo",
            "cotizar": "cotizar",
            "crear_pedido": "crear_pedido",
            "estado_pedido": "estado_pedido",
            "comprobante": "comprobante",
            "faq": "faq",
            "personalizar": "personalizar",
            "handoff": "handoff",
            "redactar": "redactar",
        },
    )

    for nodo in (
        "catalogo",
        "cotizar",
        "crear_pedido",
        "estado_pedido",
        "comprobante",
        "faq",
        "personalizar",
        "handoff",
    ):
        g.add_edge(nodo, "redactar")

    g.add_edge("redactar", END)

    return g.compile(checkpointer=checkpointer)
