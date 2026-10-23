#!/usr/bin/env python3
"""La conversación real de Lía, en tu terminal, en dos segundos.

    vb lia

Sin WhatsApp, sin Ollama, sin base de datos, sin internet. Reproduce la venta
de Ángela y su perro Rocky —la del chat de septiembre— para que veas el guion
funcionando y puedas cambiar textos y ver el efecto al instante.

Es la forma más rápida de probar un cambio en `app/domain/guion.py`: editas el
texto, corres esto, y lo ves.
"""

from __future__ import annotations

import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

from app.adapters.repositories.csv_files import cargar_catalogo_csv
from app.adapters.repositories.memory import InMemoryOrderRepository
from app.domain.guion import Paso
from app.domain.models import Order, OrderItem
from app.domain.order_state import OrderState
from app.domain.personalizacion import Personalizacion
from app.graph.nodes.personalizar import make_personalizar
from app.infra.consola import preparar_salida

_C = preparar_salida()
V, R, A, G, C, RST = (_C.ok, _C.error, _C.aviso, _C.tenue, _C.titulo, _C.fin)


class Catalogo:
    def __init__(self, productos):
        self._p = productos

    def list_active(self):
        return self._p


def main() -> int:
    productos = cargar_catalogo_csv(RAIZ / "data" / "catalogo.csv")
    orders = InMemoryOrderRepository()
    nodo = make_personalizar(Catalogo(productos), orders)

    pedido = Order(
        codigo="PED-2026-0417",
        customer_id="c1",
        estado=OrderState.COTIZADO.value,
        items=[
            OrderItem(
                sku="ANI-HUE-1",
                nombre="Anillo huellita x1",
                cantidad=1,
                precio_unitario_cop=200_000,
            )
        ],
        total_cop=200_000,
        anticipo_cop=60_000,
        saldo_cop=140_000,
    )
    orders.create(pedido, idem_key="demo")

    estado: dict = {
        "conversation_id": "wa:573001112233",
        "active_order": pedido.model_dump(mode="json"),
        "customer": {"nombre": "Ángela"},
        "entities": {},
    }

    print(f"\n{C}{'=' * 72}")
    print("  LUNA JOYAS — la venta de Ángela y Rocky")
    print(f"{'=' * 72}{RST}")
    print(f"{G}  Anillo huellita x1 · $200.000 · abono $60.000{RST}")

    guion = [
        (None, "llega al paso de diseño"),
        ("quiero corazón lila y dedos morados", None),
        ("Nombre rocky", None),
        ("__ABONO__", None),
        ("soy talla 7", None),
    ]

    for mensaje, nota in guion:
        if mensaje == "__ABONO__":
            print(f"\n{A}{'—' * 72}")
            print("  [webhook de la pasarela: abono de $60.000 aprobado]")
            print(f"{'—' * 72}{RST}")
            estado["active_order"]["anticipo_pagado_cop"] = 60_000
            mensaje = None
        elif mensaje is not None:
            print(f"\n{C}👤 Ángela:{RST} {mensaje}")
        elif nota:
            print(f"\n{G}   ({nota}){RST}")

        salida = nodo({**estado, "inbound_text": mensaje})
        estado = {**estado, **salida, "inbound_text": mensaje}

        for linea in salida.get("trace", []):
            print(f"{G}   · {linea}{RST}")
        print(f"\n{V}🤖 Bot:{RST}")
        for linea in (salida.get("reply_text") or "").splitlines():
            print(f"   {linea}")
        if salida.get("reply_imagen"):
            print(f"{A}   🖼  [{salida['reply_imagen']}]{RST}")
        for o in salida.get("reply_options", []):
            desc = f" — {o['description']}" if o.get("description") else ""
            print(f"{G}      [{o['title']}]{desc}{RST}")

    # --- lo que quedó guardado ---
    final = orders.get(pedido.id)
    p: Personalizacion = final.items[0].personalizacion
    print(f"\n{C}{'=' * 72}")
    print("  LO QUE LLEGA AL TALLER")
    print(f"{'=' * 72}{RST}")
    for linea in p.describir().splitlines():
        print(f"  {linea}")
    marca = (
        f"{R}⚠ revisar: {p.talla_motivo}{RST}"
        if p.talla_revisar
        else f"{V}✔ talla clara{RST}"
    )
    print(f"  {marca}")
    print(f"\n{G}  paso final del guion: {estado['paso']}{RST}")
    assert estado["paso"] == Paso.LISTO.value
    print(f"{C}{'=' * 72}{RST}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
