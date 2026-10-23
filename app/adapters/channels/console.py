"""Canal de consola: imprime en vez de enviar por WhatsApp.

No es un juguete. Es lo que te permite probar TODO el camino —webhook, firma,
deduplicación, grafo, outbox, despachador— sin depender de Meta, sin túnel y
sin gastar mensajes.

Cuando algo falle en producción, lo primero que vas a querer saber es "¿es mi
código o es Meta?". Con este canal esa pregunta se responde en 5 segundos:
pones CHANNEL_BACKEND=console y si el flujo funciona, el problema es Meta.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from app.domain.models import InboundMessage, OutboundMessage
from app.infra.consola import preparar_salida

log = logging.getLogger("ventabot.console")

# El servidor se suele arrancar redirigiendo la salida a un archivo de log.
# Sin esto, el primer mensaje del bot con un ✔ o un 🤖 tumbaría el servidor
# entero en Windows.
_C = preparar_salida()
VERDE, GRIS, AMARILLO, RST = _C.ok, _C.tenue, _C.aviso, _C.fin


class ConsoleChannel:
    """Implementa la parte de envío de `ChannelClient`."""

    def __init__(self) -> None:
        self.enviados: list[OutboundMessage] = []

    def send(self, m: OutboundMessage, *, ventana_abierta: bool = True) -> str:
        self.enviados.append(m)
        n = len(self.enviados)

        print(f"\n{GRIS}{'─' * 66}{RST}")
        print(f"{VERDE}🤖 BOT → {m.to}{RST}   {GRIS}({m.kind}){RST}")
        print(f"{GRIS}{'─' * 66}{RST}")
        for linea in (m.text or "").split("\n"):
            print(f"   {linea}")
        for o in m.options:
            desc = f"  {GRIS}— {o.description}{RST}" if o.description else ""
            print(f"   {AMARILLO}[ {o.title} ]{RST}{desc}")
        if m.cta_url:
            print(f"   {AMARILLO}🔗 {m.cta_label or 'Abrir'}: {m.cta_url}{RST}")
        if not ventana_abierta:
            print(
                f"   {AMARILLO}⚠ ventana de 24 h cerrada: en WhatsApp real "
                f"esto exigiría una plantilla aprobada{RST}"
            )
        print(f"{GRIS}{'─' * 66}{RST}\n")

        log.info("mensaje impreso en consola (#%s)", n)
        return f"console-{n}"

    # --- lado de entrada: solo para completar el Protocol ---

    def parse_webhook(self, payload: dict) -> list[InboundMessage]:  # pragma: no cover
        return []

    def verify_signature(
        self, raw_body: bytes, signature: str
    ) -> bool:  # pragma: no cover
        return True

    @staticmethod
    def ahora() -> datetime:
        return datetime.now(UTC)
