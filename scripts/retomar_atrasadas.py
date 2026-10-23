#!/usr/bin/env python3
"""Las clientas que se quedaron sin respuesta por un mensaje ATRASADO de Meta.

    python scripts/retomar_atrasadas.py            # quiénes son (no manda nada)
    python scripts/retomar_atrasadas.py --enviar   # les manda la plantilla

En el servidor: `sudo docker compose exec -T ventabot python
scripts/retomar_atrasadas.py`.

Del 9 al 15/10 Meta no pudo entregar los mensajes de las clientas sin número
y los reintentó días después. Lo escrito hace más de 24 h ya no se contesta
libre (WhatsApp no deja): queda en Chatwoot con la nota «📩 Mensaje
ATRASADO». Esto le manda a cada una la plantilla de emergencia
(`retomar_conversacion`, la misma de `#retomar` en Chatwoot): la disculpa y
«¿seguimos?». Lo que contesten lo atiende el bot.

Una por clienta y por día (la misma clave que usa el bot solo). Solo a
quien sigue sin respuesta: si ya le escribió el bot o una persona después de
su último mensaje, o ella volvió a escribir, no va. Solo de 8 a. m. a 8 p. m.
(hora de Colombia): de noche quedan programadas en la outbox para las 8 a. m.
(salen aunque el PC esté apagado); `--ya` las manda en el acto. La plantilla
tiene que estar APPROVED en Meta (`vb recordatorios --plantillas`): si no, no
se manda nada.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

from app.domain import plantilla_de_emergencia as emergencia
from app.domain.models import Channel, OutboundMessage
from app.domain.numeros_propios import solo_respuesta_inmediata
from app.infra.container import build_container

#: Más que esto entre que lo escribió y que llegó: atrasado.
ATRASO = timedelta(hours=24)
COLOMBIA = timedelta(hours=-5)


def _cuando(texto: str) -> datetime:
    momento = datetime.fromisoformat(texto)
    return momento if momento.tzinfo else momento.replace(tzinfo=UTC)


def atrasadas_sin_atender(c) -> list[dict]:
    """Por conversación: su ÚLTIMO mensaje llegó atrasado y nadie le contestó."""
    ultimo: dict[str, dict] = {}
    for f in c.db.consultar(
        "SELECT id, conversation_id, created_at, payload FROM messages "
        "WHERE direccion='IN' ORDER BY id"
    ):
        ultimo[f["conversation_id"]] = dict(f)
    salida = []
    for conv, f in ultimo.items():
        if solo_respuesta_inmediata(conv):
            continue  # números de prueba y de la casa
        try:
            escrito = datetime.fromtimestamp(
                int(json.loads(f["payload"] or "{}")["timestamp"]), tz=UTC
            )
        except (KeyError, TypeError, ValueError):
            continue
        llego = _cuando(f["created_at"])
        if llego - escrito <= ATRASO:
            continue
        contestada = c.db.consultar(
            "SELECT 1 FROM messages WHERE conversation_id=? AND direccion='OUT' "
            "AND id > ? LIMIT 1",
            (conv, f["id"]),
        )
        if contestada:
            continue
        salida.append({"conv": conv, "id": f["id"], "escrito": escrito})
    return salida


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--enviar", action="store_true", help="mandar (sin esto, solo lista)")
    ap.add_argument("--ya", action="store_true", help="aunque sea de noche")
    args = ap.parse_args()

    # De noche no se niega: quedan programadas en la outbox del servidor para
    # las 8 a. m. (Camilo, 16/10: «que quede fijo que salen mañana a las 8»).
    ahora = datetime.now(UTC)
    despues = None if args.ya else emergencia.cuando_mandarla(ahora)

    # Sin `c.cerrar()`: el CRM suelta su cola al salir y necesita la base abierta.
    c = build_container()
    lista = atrasadas_sin_atender(c)
    print(f"{len(lista)} clienta(s) con mensaje atrasado y sin respuesta:")
    for a in lista:
        cuando = (a["escrito"] + COLOMBIA).strftime("%d/%m %H:%M")
        print(f"  …{a['conv'][-4:]} · lo escribió el {cuando}")
    if not args.enviar:
        print("\n(No se mandó nada. Con --enviar les llega la plantilla.)")
        return 0
    nombre = c._emergencia_aprobada()
    if nombre is None:
        print("\nMeta todavía no aprueba ninguna plantilla de emergencia: no se manda.")
        return 1
    print(f"\nVa la plantilla «{nombre}».")
    for a in lista:
        conv = a["conv"]
        # Por la puerta de siempre: sale Y queda en Chatwoot como mensaje
        # saliente (17/10: las 28 de las 8 a. m. salieron y no se veían).
        c.enviar_a_la_clienta(
            conv,
            OutboundMessage(
                channel=Channel.WHATSAPP,
                to=conv.split(":", 1)[1],
                kind="template",
                text=emergencia.PLANTILLAS[nombre],
                template_name=nombre,
                conversation_id=conv,
                # La misma clave que usa el bot solo: una por clienta y por
                # día, aunque se corra dos veces o el bot ya la haya programado.
                idempotency_key=emergencia.clave(conv, despues or ahora),
            ),
            enviar_despues=despues,
        )
        if c.crm is not None:
            cuando = (
                ""
                if despues is None
                else (despues + COLOMBIA).strftime(" el %d/%m a las %H:%M")
            )
            c.crm.nota(
                conv,
                f"🆘 Plantilla de emergencia (disculpa por el mensaje atrasado): "
                f"sale{cuando or ' ya'}. Si responde, la atiende el bot.",
            )
    if c.crm is not None and hasattr(c.crm, "vaciar"):
        c.crm.vaciar()
    if despues is None:
        print(f"\nEncoladas {len(lista)}: el bot las manda en segundos.")
    else:
        hora = (despues + COLOMBIA).strftime("%d/%m a las %H:%M")
        print(f"\nProgramadas {len(lista)} para el {hora}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
