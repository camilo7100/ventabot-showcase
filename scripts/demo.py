#!/usr/bin/env python3
"""Demo de una venta completa en la terminal, SIN WhatsApp y SIN LLM real.

    python scripts/demo.py

Sirve para tres cosas:
  1. Ver el flujo entero funcionando en 2 segundos.
  2. Entender qué hace cada nodo (imprime el `trace` del grafo).
  3. Probar cambios en la lógica sin depender de Meta ni de Ollama.

Para probarlo contra Ollama de verdad:
    OLLAMA_CONTEXT_LENGTH=32000 ollama serve      # en otra terminal
    LLM_BACKEND=ollama python scripts/demo.py
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from langgraph.checkpoint.memory import InMemorySaver

from app.adapters.llm.ollama_client import FakeLLM, OllamaLLM
from app.adapters.payments.bold import FakeGateway
from app.adapters.repositories.memory import (
    InMemoryCustomerRepository,
    InMemoryOrderRepository,
    InMemoryPaymentRepository,
    InMemoryProductRepository,
)
from app.domain.models import Channel, Customer, PaymentKind
from app.domain.order_state import ETIQUETA_CLIENTE, OrderState
from app.domain.pricing import formatear_cop
from app.domain.services import confirmar_pago, transicionar
from app.graph.build import Deps, build_graph
from app.graph.state import initial_state
from app.infra.consola import preparar_salida
from app.infra.container import cargar_catalogo

# UTF-8 y color solo si hay terminal: sin esto, redirigir la salida a un
# archivo revienta en Windows al imprimir un ✔ (cp1252 no lo soporta).
_C = preparar_salida()
VERDE, AZUL, GRIS, AMARILLO, RESET = (_C.ok, _C.titulo, _C.tenue, _C.aviso, _C.fin)

CONV = "wa:573001112233"


class FakeMedia:
    def download(self, x: str) -> bytes:
        return b"fake"

    def store(self, data: bytes, *, filename: str) -> str:
        return f"https://storage.test/{filename}"


def construir():
    # Catálogo REAL desde data/catalogo.csv, no una constante incrustada:
    # el mismo archivo que en la Fase 2 servirá Google Sheets.
    productos = InMemoryProductRepository(cargar_catalogo())
    customers = InMemoryCustomerRepository()
    customers.upsert(
        Customer(
            channel=Channel.WHATSAPP, channel_user_id="573001112233", nombre="Camilo"
        )
    )
    llm = (
        OllamaLLM(model=os.getenv("OLLAMA_MODEL", "gemma4:12b"))
        if os.getenv("LLM_BACKEND") == "ollama"
        else FakeLLM()
    )
    deps = Deps(
        products=productos,
        customers=customers,
        orders=InMemoryOrderRepository(),
        payments=InMemoryPaymentRepository(),
        gateway=FakeGateway(),
        llm=llm,
        media=FakeMedia(),
    )
    return deps, build_graph(deps, checkpointer=InMemorySaver())


#: El campo `trace` usa el reducer `add`, así que se ACUMULA entre turnos
#: dentro del mismo thread. Eso es exactamente lo que hace el checkpointer de
#: LangGraph: el estado sobrevive de un mensaje al siguiente. Aquí solo
#: imprimimos las líneas nuevas de cada turno.
_trace_vistas = 0


def turno(graph, texto: str, media=None) -> dict:
    global _trace_vistas
    print(f"\n{AZUL}👤 Cliente:{RESET} {texto or '[imagen de comprobante]'}")
    estado = initial_state(
        conversation_id=CONV,
        channel="whatsapp",
        sender_id="573001112233",
        text=texto,
        media=media,
    )
    r = graph.invoke(estado, {"configurable": {"thread_id": CONV}})
    traza = r.get("trace", [])
    for linea in traza[_trace_vistas:]:
        print(f"{GRIS}   · {linea}{RESET}")
    _trace_vistas = len(traza)
    print(f"{VERDE}🤖 Bot:{RESET} {r.get('reply_text', '')}")
    if r.get("reply_options"):
        for o in r["reply_options"]:
            desc = f" — {o['description']}" if o.get("description") else ""
            print(f"{GRIS}      [{o['title']}]{desc}{RESET}")
    if r.get("reply_cta_url"):
        print(f"{AMARILLO}      🔗 {r['reply_cta_url']}{RESET}")
    return r


def main() -> None:
    # Antes este script ignoraba los argumentos, así que `demo.py --help`
    # ejecutaba la demo COMPLETA. Un test que la llamaba con --help acababa
    # golpeando Ollama durante casi un minuto y agotando su tiempo límite.
    # Un script que no respeta --help es hostil, y además irrepetible en tests.
    ap = argparse.ArgumentParser(
        description="Una venta completa en la terminal, sin red ni WhatsApp."
    )
    ap.add_argument(
        "--llm",
        choices=["fake", "ollama"],
        default=None,
        help="qué modelo usar; por defecto, el LLM_BACKEND de tu .env",
    )
    args = ap.parse_args()
    if args.llm:
        os.environ["LLM_BACKEND"] = args.llm

    deps, graph = construir()
    modo = os.getenv("LLM_BACKEND", "fake")
    print(f"{GRIS}{'=' * 68}{RESET}")
    print(f"  DEMO — venta completa   ·   LLM_BACKEND={modo}")
    print(f"{GRIS}{'=' * 68}{RESET}")

    turno(graph, "hola buenas")
    turno(graph, "quiero 2 CAM-PRE-001")
    r = turno(graph, "listo confirmo")

    pedido_id = r["active_order"]["id"]
    pago = deps.payments.all()[0]

    # --- El cliente paga. Esto llega por WEBHOOK, fuera de la conversación. ---
    print(
        f"\n{GRIS}{'—' * 68}\n  [webhook de la pasarela: pago aprobado]\n"
        f"{'—' * 68}{RESET}"
    )
    pedido = confirmar_pago(
        deps.orders,
        deps.payments,
        pago,
        monto_recibido_cop=pago.monto_esperado_cop,
        transaction_id="TX-DEMO-001",
    )
    print(
        f"{VERDE}   ✓ {pedido.codigo}: {ETIQUETA_CLIENTE[OrderState(pedido.estado)]}"
        f"  ({formatear_cop(pago.monto_esperado_cop)}){RESET}"
    )

    # --- Operación mueve el pedido por producción ---
    print(f"\n{GRIS}{'—' * 68}\n  [panel de operación]\n{'—' * 68}{RESET}")
    for destino in (
        OrderState.EN_PRODUCCION,
        OrderState.PRODUCCION_LISTA,
        OrderState.ESPERANDO_SALDO,
    ):
        pedido = transicionar(
            deps.orders,
            pedido,
            destino,
            actor="operador:demo",
            motivo="avance manual",
        )
        print(f"{VERDE}   ✓ {pedido.codigo} → {destino.value}{RESET}")

    turno(graph, "cómo va mi pedido")

    # --- Se cobra el saldo ---
    from app.domain.services import generar_cobro

    saldo = generar_cobro(deps.payments, deps.gateway, pedido, PaymentKind.SALDO)
    print(
        f"\n{AMARILLO}   💸 Cobro del saldo: {formatear_cop(saldo.monto_esperado_cop)}"
        f"  {saldo.payment_link_url}{RESET}"
    )

    pedido = confirmar_pago(
        deps.orders,
        deps.payments,
        saldo,
        monto_recibido_cop=saldo.monto_esperado_cop,
        transaction_id="TX-DEMO-002",
    )
    pedido = transicionar(
        deps.orders,
        pedido,
        OrderState.DESPACHADO,
        actor="operador:demo",
        motivo="guía 1234567",
    )
    print(f"{VERDE}   ✓ {pedido.codigo} → DESPACHADO{RESET}")

    # --- Auditoría: la razón por la que puedes dormir tranquilo ---
    print(f"\n{GRIS}{'=' * 68}\n  LOG DE AUDITORÍA (append-only)\n{'=' * 68}{RESET}")
    for e in deps.orders.eventos(pedido_id):
        print(
            f"{GRIS}  {e.created_at:%H:%M:%S}  "
            f"{(e.estado_anterior or '—'):>20} → {e.estado_nuevo:<20} "
            f"{e.actor:<18} {e.motivo}{RESET}"
        )

    print(f"\n{GRIS}{'=' * 68}{RESET}")
    print("  Total facturado:", formatear_cop(pedido.total_cop))
    print("  Pagos registrados:", len(deps.payments.all()))
    print(f"{GRIS}{'=' * 68}{RESET}\n")


if __name__ == "__main__":
    main()
