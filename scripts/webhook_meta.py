#!/usr/bin/env python3
"""A dónde manda Meta los mensajes de WhatsApp: verlo y cambiarlo sin entrar al panel.

    python scripts/webhook_meta.py --ver
    python scripts/webhook_meta.py --apuntar https://bot.lunajoyas.example
    python scripts/webhook_meta.py --quitar

CÓMO FUNCIONA
=============
Meta tiene DOS direcciones de webhook:

  1. La de la APP (panel de Meta → WhatsApp → Configuración). Es la del ngrok
     del PC, la de siempre.
  2. Una propia de la CUENTA DE WHATSAPP (`override_callback_uri` en
     `POST /{WABA}/subscribed_apps`), que manda por encima de la primera.

Producción usa la 2 para `bot.lunajoyas.example` (25/09/2026). El plan B —el
bot atendiendo desde el PC porque el servidor se cayó— es `--quitar`: Meta
vuelve sola a la 1, el ngrok del PC. Cuando el servidor vuelve, `--apuntar`.

Al apuntar, Meta verifica en el acto la dirección nueva (le manda el reto con
META_VERIFY_TOKEN): si el bot no contesta ahí, Meta no cambia nada y lo dice.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

import httpx

from app.infra.consola import preparar_salida
from app.infra.settings import get_settings

_C = preparar_salida()
V, R, G, RST = _C.ok, _C.error, _C.tenue, _C.fin
API = "https://graph.facebook.com/v21.0"
RUTA = "/webhook/whatsapp"


def _llamar(metodo: str, url: str, token: str, datos: dict | None = None) -> dict:
    r = httpx.request(
        metodo, url, headers={"Authorization": f"Bearer {token}"}, json=datos, timeout=30
    )
    cuerpo = r.json() if r.content else {}
    if r.status_code >= 400:
        error = cuerpo.get("error", {}).get("message", r.text[:200])
        raise SystemExit(f"{R}✘ Meta dijo que no:{RST} {error}")
    return cuerpo


def ver(s) -> str:
    """La dirección propia de la cuenta, o '' si usa la de la app."""
    datos = _llamar(
        "GET", f"{API}/{s.wa_business_account_id}/subscribed_apps", s.wa_access_token
    )
    for app in datos.get("data", []):
        nombre = app.get("whatsapp_business_api_data", {}).get("name", "¿?")
        propia = app.get("override_callback_uri", "")
        print(f"  app suscrita: {nombre}")
        if propia:
            print(f"  webhook de la cuenta: {V}{propia}{RST}")
        else:
            ninguno = "(ninguno: usa el de la app, el ngrok del PC)"
            print(f"  webhook de la cuenta: {G}{ninguno}{RST}")
        return propia
    print(f"  {R}✘ ninguna app suscrita a la cuenta de WhatsApp{RST}")
    return ""


def apuntar(s, base: str) -> None:
    url = base.rstrip("/") + RUTA
    _llamar(
        "POST",
        f"{API}/{s.wa_business_account_id}/subscribed_apps",
        s.wa_access_token,
        {"override_callback_uri": url, "verify_token": s.meta_verify_token},
    )
    print(f"  {V}✔ Meta verificó y ahora entrega a {url}{RST}")


def quitar(s) -> None:
    _llamar(
        "POST", f"{API}/{s.wa_business_account_id}/subscribed_apps", s.wa_access_token
    )
    print(f"  {V}✔ quitado: Meta vuelve al webhook de la app (el ngrok del PC){RST}")


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--ver", action="store_true")
    g.add_argument("--apuntar", metavar="URL_BASE")
    g.add_argument("--quitar", action="store_true")
    a = p.parse_args()
    s = get_settings()
    if not (s.wa_access_token and s.wa_business_account_id):
        raise SystemExit("Faltan WA_ACCESS_TOKEN o WA_BUSINESS_ACCOUNT_ID en el .env")
    if a.apuntar:
        apuntar(s, a.apuntar)
    elif a.quitar:
        quitar(s)
    ver(s)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
