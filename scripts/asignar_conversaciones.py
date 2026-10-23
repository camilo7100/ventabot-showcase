"""Deja cada conversación de Chatwoot asignada a quien de verdad la atiende.

    python scripts/asignar_conversaciones.py            <- solo muestra qué haría
    python scripts/asignar_conversaciones.py --aplicar  <- lo hace

Para el cambio del 09/10 (un solo criterio: quien está asignado es quien
atiende). Las conversaciones que ya existían quedaron «sin asignar» (el «None»
del celular). Esto las pone al día una vez:

- si el bot la atiende → VentaBot;
- si una persona la atiende y ya está asignada a una persona → no se toca;
- si una persona la atiende y no está asignada a nadie → a la persona del panel
  (CHATWOOT_PERSONA_DEL_PANEL), y si no hay, se deja como está y se avisa.

Solo cambia la ASIGNACIÓN: no le escribe a nadie ni cambia el estado del bot.
Las resueltas no se tocan.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main() -> int:
    import httpx

    from app.infra.container import get_container

    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--aplicar", action="store_true", help="hacer los cambios")
    args = ap.parse_args()

    c = get_container()
    s = c.settings
    api = f"{s.chatwoot_url}/api/v1/accounts/{s.chatwoot_account_id}"
    h = {"api_access_token": s.chatwoot_token}
    bot = (
        httpx.get(f"{api}/inboxes/{s.chatwoot_inbox_id}/agent_bot", headers=h, timeout=20)
        .json()
        .get("agent_bot")
        or {}
    ).get("id")
    if not bot:
        print("El buzón no tiene agente bot: nada que hacer.")
        return 1
    mundo = c.bot._mundo
    cambios: list[tuple[int, dict]] = []
    for estado in ("open", "pending", "snoozed"):
        pagina = 1
        while True:
            r = httpx.get(
                f"{api}/conversations",
                params={
                    "status": estado,
                    "assignee_type": "all",
                    "inbox_id": s.chatwoot_inbox_id,
                    "page": pagina,
                },
                headers=h,
                timeout=30,
            ).json()
            filas = r["data"]["payload"]
            if not filas:
                break
            for x in filas:
                meta = x.get("meta") or {}
                conv = (meta.get("sender") or {}).get("identifier") or ""
                if ":" not in conv:
                    continue
                tipo = meta.get("assignee_type")
                persona = mundo.la_atiende_una_persona(conv)
                if not persona:
                    if tipo == "AgentBot":
                        continue
                    cuerpo = {"assignee_id": bot, "assignee_type": "AgentBot"}
                    destino = "VentaBot"
                elif tipo == "User":
                    continue
                elif s.chatwoot_persona_del_panel:
                    cuerpo = {"assignee_id": s.chatwoot_persona_del_panel}
                    destino = "la persona del panel"
                else:
                    print(f"  #{x['id']}: la atiende una persona y no se sabe quién")
                    continue
                cambios.append((x["id"], cuerpo))
                print(f"  #{x['id']} ({estado}, {tipo or 'sin asignar'}) → {destino}")
            pagina += 1
    # Primero se junta todo y DESPUÉS se asigna: asignar a VentaBot la pasa a
    # «Pendiente» y la lista de «Abiertas» se corre de página mientras se lee
    # (la primera vez quedaron 25 de 67 sin asignar, 09/10).
    if args.aplicar:
        for conversacion, cuerpo in cambios:
            httpx.post(
                f"{api}/conversations/{conversacion}/assignments",
                headers=h,
                json=cuerpo,
                timeout=30,
            ).raise_for_status()
    hecho = "asignadas" if args.aplicar else "por asignar (usa --aplicar)"
    print(f"\n{len(cambios)} conversación(es) {hecho}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
