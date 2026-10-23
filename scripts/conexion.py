#!/usr/bin/env python3
"""Revisa la CADENA COMPLETA entre Meta y tu servidor, eslabón por eslabón.

    vb conexion

Meta -> ngrok -> tu servidor es una cadena de cuatro eslabones, y cuando algo
no llega, el síntoma es siempre el mismo: silencio. Este script prueba cada
eslabón por separado y te dice cuál está roto, en vez de dejarte adivinar.

El eslabón que más se rompe, con diferencia: **la URL del túnel no es la que
Meta tiene guardada**. Pasa si ngrok arranca sin el dominio fijo (sin
`--url=...`) y le toca una dirección al azar: Meta sigue generando los eventos
(los ves en su panel) pero los entrega a una dirección muerta. Desde tu lado se
ve idéntico a "no funciona nada". Arráncalo siempre con el dominio de PUBLIC_URL.
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
V, R, A, G, C, RST = (_C.ok, _C.error, _C.aviso, _C.tenue, _C.titulo, _C.fin)
OK, NO, DUDA = f"{V}✔{RST}", f"{R}✘{RST}", f"{A}○{RST}"

#: ngrok expone una API local sin autenticación. Es la forma fiable de saber
#: qué URL tiene AHORA MISMO, en vez de leerla a ojo de la terminal.
NGROK_API = "http://127.0.0.1:4040/api/tunnels"

problemas: list[str] = []


def paso(n: int, t: str) -> None:
    print(f"\n{G}[{n}]{RST} {t}")


def fallo(msg: str, *ayuda: str) -> None:
    print(f"  {NO} {msg}")
    for a in ayuda:
        print(f"      {A}→{RST} {a}")
    problemas.append(msg)


def main() -> int:
    ap = argparse.ArgumentParser(description="Revisa la cadena Meta → túnel → servidor")
    ap.add_argument(
        "--url",
        default=None,
        help="URL pública a comprobar. Por defecto la lee de ngrok. Úsala si "
        "usas Cloudflare Tunnel u otro túnel que no sea ngrok.",
    )
    args = ap.parse_args()
    s = get_settings()
    print(f"\n{C}{'=' * 74}\n  CADENA: Meta → ngrok → tu servidor\n{'=' * 74}{RST}")

    # ---- 1. servidor local ----
    paso(1, "Tu servidor está corriendo")
    try:
        salud = httpx.get("http://127.0.0.1:8000/health", timeout=5).json()
        print(f"  {OK} responde · canal={salud['canal']} llm={salud['llm']}")
    except Exception:
        fallo(
            "no responde en http://127.0.0.1:8000",
            "Arráncalo en OTRA ventana con:  vb server",
        )
        return veredicto(None)

    # ---- 2. el túnel ----
    paso(2, "El túnel está corriendo y qué URL tiene AHORA")
    publica = None
    if args.url:
        publica = args.url.rstrip("/")
        print(f"  {OK} {publica}  {G}(indicada a mano){RST}")
        return _resto(s, publica)
    try:
        tuneles = httpx.get(NGROK_API, timeout=5).json().get("tunnels", [])
        # Los endpoints internos del enrutado por rutas (ventabot.internal,
        # chatwoot.internal) NO se resuelven desde fuera: son el destino del
        # reparto, no la puerta. Si se coge el primero de la lista, el
        # diagnóstico dice «el túnel no llega» con el túnel perfecto (19/09).
        publicas = [
            t["public_url"]
            for t in tuneles
            if t["public_url"].startswith("https")
            and not t["public_url"].endswith(".internal")
        ]
        # Y entre las de verdad, la que Meta tiene guardada manda.
        de_settings = get_settings().url_publica
        if de_settings in publicas:
            publicas = [de_settings]
        if not publicas:
            fallo(
                "ngrok corre pero no tiene ningún túnel https",
                "Arráncalo con:  ngrok http 8000",
            )
        else:
            publica = publicas[0]
            print(f"  {OK} {publica}")
    except Exception:
        fallo(
            "ngrok no está corriendo (o su panel local no responde)",
            "Arráncalo en una TERCERA ventana con:  ngrok http 8000",
        )

    return _resto(s, publica)


def _resto(s, publica: str | None) -> int:
    # ---- 3. ¿el túnel llega hasta aquí? ----
    if publica:
        paso(3, "El túnel llega de verdad hasta tu servidor")
        try:
            r = httpx.get(
                f"{publica}/health",
                timeout=15,
                headers={"ngrok-skip-browser-warning": "1"},
            )
            if r.status_code == 200:
                print(f"  {OK} una petición desde internet llega a tu máquina")
            else:
                fallo(f"el túnel responde {r.status_code}, no 200")
        except Exception as exc:
            fallo(f"el túnel no llega a tu servidor: {exc}")

        # ---- 4. el handshake, tal cual lo hace Meta ----
        paso(4, "El handshake de Meta funciona A TRAVÉS del túnel")
        try:
            r = httpx.get(
                f"{publica}/webhook/whatsapp",
                params={
                    "hub.mode": "subscribe",
                    "hub.verify_token": s.meta_verify_token,
                    "hub.challenge": "1234567",
                },
                timeout=15,
                headers={"ngrok-skip-browser-warning": "1"},
            )
            if r.status_code == 200 and r.text.strip() == "1234567":
                print(f"  {OK} Meta podría verificar esta URL sin problema")
            else:
                fallo(f"el handshake devolvió {r.status_code}: {r.text[:80]}")
        except Exception as exc:
            fallo(f"el handshake falló: {exc}")

    # ---- 5. ¿la cuenta de WhatsApp está suscrita a tu app? ----
    paso(5, "Tu cuenta de WhatsApp está suscrita a tu app")
    if not (s.wa_access_token and s.wa_business_account_id):
        print(
            f"  {DUDA} no puedo comprobarlo: falta WA_ACCESS_TOKEN o "
            f"WA_BUSINESS_ACCOUNT_ID en el .env"
        )
    else:
        try:
            r = httpx.get(
                f"https://graph.facebook.com/v21.0/"
                f"{s.wa_business_account_id}/subscribed_apps",
                headers={"Authorization": f"Bearer {s.wa_access_token}"},
                timeout=15,
            )
            datos = r.json()
            if r.status_code != 200:
                err = (datos.get("error") or {}).get("message", r.text[:120])
                fallo(
                    f"Meta respondió {r.status_code}: {err}",
                    "Si dice que el token caducó, genera uno nuevo en el panel",
                )
            elif not datos.get("data"):
                fallo(
                    "tu WABA NO está suscrita a ninguna app",
                    "Es el fallo silencioso nº1: Meta genera los eventos pero",
                    "tiene a quién entregárselos. Arréglalo con:  vb registrar",
                )
            else:
                apps = ", ".join(
                    a.get("whatsapp_business_api_data", {}).get("name", "?")
                    for a in datos["data"]
                )
                print(f"  {OK} suscrita a: {apps}")
        except Exception as exc:
            fallo(f"no pude consultar a Meta: {exc}")

    return veredicto(publica)


def veredicto(publica: str | None) -> int:
    print(f"\n{C}{'=' * 74}\n  VEREDICTO\n{'=' * 74}{RST}")
    if problemas:
        print(f"  {R}{len(problemas)} eslabón(es) roto(s):{RST}")
        for p in problemas:
            print(f"     · {p}")
        print()
        return 1

    print(f"  {V}La cadena está completa.{RST}\n")
    if publica:
        print("  Ahora comprueba que Meta apunte EXACTAMENTE a esta dirección.")
        print("  (Si ngrok arrancó sin tu dominio fijo, será una al azar):\n")
        print(f"      {C}{publica}/webhook/whatsapp{RST}\n")
        print("  En Meta: WhatsApp → Configuración → Webhook → Editar.")
        print("  Si la que hay guardada es distinta, ESE es el problema: Meta")
        print("  genera los eventos y los entrega a una dirección muerta.\n")
        print(
            f"  {A}Y en «Administrar», la casilla `messages` debe estar MARCADA.{RST}\n"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
