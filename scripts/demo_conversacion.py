"""Una venta completa, sin red y sin modelo real.

El «modelo» de este demo es de madera: solo reconoce el VERBO de la frase
(«quiero», «pagar»…). Ni colores, ni tallas, ni nombres. Todo lo demás —la talla,
los colores, el grabado, el precio, el abono, las cuentas, el resumen— lo saca y
lo decide Python. Esa es la tesis del proyecto: el modelo lee, las reglas deciden.

    python scripts/demo_conversacion.py             # imprime la conversación
    python scripts/demo_conversacion.py --markdown  # lista para pegar en un README
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.adapters.repositories.memory import (
    InMemoryCustomerRepository,
    InMemoryOrderRepository,
    InMemoryProductRepository,
)
from app.conversacion.ejecutor import Ejecutor
from app.conversacion.interprete import Interprete
from app.conversacion.mundo import Mundo
from app.conversacion.pipeline import Pipeline
from app.conversacion.redactor import Redactor
from app.domain.contexto import ContextoConversacional
from app.domain.interpretacion import (
    Acto,
    Atributo,
    Entidad,
    Interpretacion,
)
from app.domain.models import Channel, Customer, Product

CONV = "wa:573001110001"
CLIENTA = [
    "Hola, quiero un anillo de 2 huellitas",
    "corazón lila y dedos morados",
    "corazón rosa y dedos fucsia",
    "Luna y Mateo",
    "talla 7",
    "Camila Torres",
    "bancolombia",
    "ya pagué",
]


class ContextoEnMemoria:
    def __init__(self) -> None:
        self._d: dict[str, ContextoConversacional] = {}

    def cargar(self, conv_id: str) -> ContextoConversacional:
        return self._d.get(conv_id) or ContextoConversacional(conversation_id=conv_id)

    def guardar(self, ctx: ContextoConversacional) -> None:
        self._d[ctx.conversation_id] = ctx


class ModeloDeMadera:
    """Acierta el verbo y nada más."""

    PISTAS = (
        ("anillo", Acto.COMPRAR, Entidad.PRODUCTO),
        ("quiero", Acto.COMPRAR, Entidad.PRODUCTO),
        ("pagar", Acto.PREGUNTAR, Entidad.PAGO),
        ("pago", Acto.PREGUNTAR, Entidad.PAGO),
    )

    def extract(self, prompt, texto, esquema):
        bajo = (texto or "").lower()
        for pista, acto, entidad in self.PISTAS:
            if pista in bajo:
                atributo = (
                    Atributo.MEDIOS_DE_PAGO
                    if entidad is Entidad.PAGO
                    else Atributo.NINGUNO
                )
                return Interpretacion(
                    acto=acto, entidad=entidad, atributo=atributo, confianza="MEDIA"
                )
        return Interpretacion(acto=Acto.OTRO, confianza="BAJA")


def construir() -> Pipeline:
    productos = InMemoryProductRepository(
        [
            Product(
                sku=f"ANI-HUE-{n}",
                nombre=f"Anillo huellita x{n}",
                precio_cop=150_000 + 50_000 * n,
                iva_pct=0,
                dias_produccion=10,
                dias_produccion_max=15,
                anticipo_fijo_cop=60_000,
                huellitas=n,
            )
            for n in (1, 2, 3)
        ]
    )
    clientes = InMemoryCustomerRepository()
    clientes.upsert(
        Customer(
            id="c1",
            channel=Channel.WHATSAPP,
            channel_user_id="573001110001",
            nombre="Camila",
        )
    )
    mundo = Mundo(InMemoryOrderRepository(), clientes, productos, ContextoEnMemoria())
    return Pipeline(
        Interprete(ModeloDeMadera(), prompt="", catalogo_txt=""),
        mundo,
        Ejecutor(mundo),
        Redactor(),
    )


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):  # la consola de Windows arranca en cp1252
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument(
        "--markdown", action="store_true", help="salida lista para pegar en un README"
    )
    markdown = ap.parse_args().markdown
    bot = construir()
    for mensaje in CLIENTA:
        respuesta = bot.ejecutar(CONV, mensaje).respuesta.texto_plano
        if markdown:
            print(
                f"**👤 Clienta:** {mensaje}\n\n> **🤖 Bot:** "
                + respuesta.strip().replace("\n", "\n> ")
                + "\n"
            )
        else:
            print(
                f"\n👤 Clienta: {mensaje}\n🤖 Bot:     "
                + respuesta.strip().replace("\n", "\n           ")
            )


if __name__ == "__main__":
    main()
