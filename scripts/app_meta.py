#!/usr/bin/env python3
"""Averigua QUÉ APLICACIÓN de Meta firma tus webhooks, y si tu secreto es de esa.

    vb app

POR QUÉ EXISTE
==============
Cuando `vb firma` dice «ninguna hipótesis encaja», ya sabes que el código está
bien y que el cuerpo llegó intacto. Lo único que queda es que el App Secret no
sea el de la aplicación que manda el webhook.

Pero eso, hasta ahora, había que comprobarlo A OJO en el panel de Meta: abrir
cada app, mirar el identificador en la URL, comparar. Si creaste dos o tres
apps mientras peleabas con la integración —que es lo normal— es facilísimo
copiar el secreto de la equivocada, y el síntoma es idéntico.

Este script lo MIDE, con dos llamadas a Meta:

  1. `GET /app` con tu token → Meta te dice de qué aplicación es ese token.
  2. La misma llamada firmada con `appsecret_proof`, que es HMAC-SHA256 del
     token usando el App Secret como clave. Si el secreto NO es el de esa
     aplicación, Meta responde «Invalid appsecret_proof» y queda demostrado.

  3. Y aparte, `GET /{WABA}/subscribed_apps` dice qué aplicación está suscrita
     a tu cuenta de WhatsApp. Esa es la que entrega —y firma— los webhooks.

Si las tres coinciden, tu secreto es el correcto. Si no, el script te da la
URL exacta de la página donde está el secreto que sí sirve.

SEGURIDAD
=========
Nunca imprime el secreto ni el token. El `appsecret_proof` que se manda a Meta
es un HMAC: no se puede volver atrás para sacar el secreto.
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
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

API = "https://graph.facebook.com/v21.0"

#: Aplicaciones internas de Meta que aparecen suscritas a casi todas las
#: cuentas. No entregan nada a TU servidor: su URL es de Meta. Ignorarlas
#: evita el falso positivo de «hay dos apps, cuál es».
APPS_DE_META = ("wa devx webhook events", "whatsapp business", "1p app")


def huella(secreto: str) -> str:
    """Los 12 primeros del SHA-256. Compara secretos sin revelarlos."""
    return hashlib.sha256(secreto.encode()).hexdigest()[:12]


def proof(token: str, secreto: str) -> str:
    """appsecret_proof de Meta: HMAC-SHA256 del token con el secreto de clave."""
    return hmac.new(secreto.encode(), token.encode(), hashlib.sha256).hexdigest()


def pedir(url: str, token: str, params: dict | None = None) -> tuple[bool, dict]:
    try:
        r = httpx.get(
            url,
            headers={"Authorization": f"Bearer {token}"},
            params=params or {},
            timeout=30,
        )
    except Exception as exc:
        return False, {"error": {"message": f"no pude llegar a Meta: {exc}"}}
    try:
        cuerpo = r.json()
    except Exception:
        cuerpo = {"error": {"message": r.text[:200]}}
    return r.status_code == 200, cuerpo


def url_del_secreto(app_id: str) -> str:
    return f"https://developers.facebook.com/apps/{app_id}/settings/basic/"


def es_de_meta(nombre: str) -> bool:
    n = (nombre or "").lower()
    return any(marca in n for marca in APPS_DE_META)


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Identifica la app de Meta que firma tus webhooks"
    )
    ap.add_argument(
        "--secreto",
        default=None,
        metavar="SECRETO",
        help="prueba ESTE secreto en vez del de tu .env (no se imprime nunca). "
        "Sirve para ir pegando el de cada app hasta dar con la buena.",
    )
    args = ap.parse_args()
    s = get_settings()

    print(f"\n{C}{'=' * 74}\n  ¿DE QUÉ APLICACIÓN ES TU SECRETO?\n{'=' * 74}{RST}")

    token = (s.wa_access_token or "").strip()
    secreto = (args.secreto or s.app_secret_efectivo).strip()

    if not token:
        print(f"\n  {NO} WA_ACCESS_TOKEN está vacío: sin token no puedo preguntarle")
        print("      nada a Meta. Genéralo en WhatsApp → Configuración de la API.\n")
        return 1
    if s.usando_secreto_de_desarrollo and not args.secreto:
        print(f"\n  {NO} META_APP_SECRET está vacío: se está usando el de desarrollo.")
        print("      Meta nunca va a coincidir con ese.\n")
        return 1

    origen = "el que pegaste" if args.secreto else "el de tu .env"
    print(f"\n{G}[1]{RST} Secreto que voy a comprobar ({origen})")
    print(f"      longitud: {len(secreto)} caracteres · huella: {huella(secreto)}")

    # ---- 2. ¿de qué app es el token? ----
    print(f"\n{G}[2]{RST} De qué aplicación es tu token de acceso")
    ok, cuerpo = pedir(f"{API}/app", token, {"fields": "id,name,link"})
    if not ok:
        msg = (cuerpo.get("error") or {}).get("message", "?")
        print(f"  {NO} Meta no me deja preguntarlo: {msg}")
        print(f"      {A}→{RST} Si dice que el token caducó, genera uno nuevo en")
        print("          WhatsApp → Configuración de la API → «Generar».")
        print("          El token temporal dura 24 horas.\n")
        return 1
    app_id = str(cuerpo.get("id", ""))
    app_nombre = cuerpo.get("name", "(sin nombre)")
    print(f"  {OK} {app_nombre}   (id {app_id})")

    # ---- 3. ¿el secreto es de ESA app? ----
    print(f"\n{G}[3]{RST} Si el secreto pertenece a esa misma aplicación")
    ok_proof, cuerpo_proof = pedir(
        f"{API}/app",
        token,
        {"fields": "id", "appsecret_proof": proof(token, secreto)},
    )
    if ok_proof:
        print(f"  {OK} sí: el secreto es de «{app_nombre}»")
    else:
        msg = (cuerpo_proof.get("error") or {}).get("message", "?")
        if "appsecret_proof" in msg:
            print(f"  {NO} NO: ese secreto es de OTRA aplicación")
        else:
            print(f"  {DUDA} Meta respondió otra cosa: {msg}")
            print("      No puedo concluir nada de este paso.")

    # ---- 4. ¿qué app entrega los webhooks? ----
    print(f"\n{G}[4]{RST} Qué aplicación entrega los webhooks de tu cuenta")
    suscrita_id, suscrita_nombre = None, None
    if not s.wa_business_account_id:
        print(f"  {DUDA} WA_BUSINESS_ACCOUNT_ID está vacío: no puedo comprobarlo.")
    else:
        ok_sub, cuerpo_sub = pedir(
            f"{API}/{s.wa_business_account_id}/subscribed_apps", token
        )
        if not ok_sub:
            msg = (cuerpo_sub.get("error") or {}).get("message", "?")
            print(f"  {DUDA} Meta no me dejó consultarlo: {msg}")
        else:
            propias = []
            for fila in cuerpo_sub.get("data", []):
                info = fila.get("whatsapp_business_api_data", {})
                nid, nom = str(info.get("id", "?")), info.get("name", "?")
                marca = f" {G}(app interna de Meta, no entrega a tu servidor){RST}"
                print(f"      · {nom}  (id {nid}){marca if es_de_meta(nom) else ''}")
                if not es_de_meta(nom):
                    propias.append((nid, nom))
            if len(propias) == 1:
                suscrita_id, suscrita_nombre = propias[0]
            elif len(propias) > 1:
                print(f"\n  {A}⚠ Hay MÁS DE UNA aplicación tuya suscrita.{RST}")
                print("      Meta le manda el webhook a todas, cada una firmado")
                print("      con SU propio secreto. Quita las que no uses en")
                print("      su panel, o quédate con la que tenga tu URL.")
            elif not propias:
                print(f"\n  {NO} Ninguna aplicación TUYA está suscrita.")
                print(f"      {A}→{RST} Corre:  vb registrar")

    # ---- veredicto ----
    print(f"\n{C}{'=' * 74}\n  VEREDICTO\n{'=' * 74}{RST}")

    if suscrita_id and app_id and suscrita_id != app_id:
        print(f"  {R}Tu token y tu webhook son de aplicaciones DISTINTAS.{RST}\n")
        print(
            f"      el webhook lo entrega y lo firma : {suscrita_nombre} ({suscrita_id})"
        )
        print(f"      tu token (y tu secreto) son de   : {app_nombre} ({app_id})\n")
        print("  Por eso la firma nunca cuadra: estás validando con el secreto")
        print("  de una app que no es la que firma. Coge el secreto de LA QUE")
        print("  FIRMA, aquí:\n")
        print(f"      {G}{url_del_secreto(suscrita_id)}{RST}\n")
        print("  «Clave secreta de la aplicación» → «Mostrar» → cópiala, y")
        print("  compruébala sin tocar el .env con:\n")
        print(f"      {G}vb app --secreto PEGA_AQUI_LA_NUEVA{RST}\n")
        return 1

    if not ok_proof:
        print(f"  {R}El secreto no es de la aplicación de tu token.{RST}\n")
        print("  Cógelo de la página correcta de esa aplicación:\n")
        print(f"      {G}{url_del_secreto(app_id)}{RST}\n")
        print("  «Configuración → Básica» → «Clave secreta de la aplicación» →")
        print("  «Mostrar». Pégalo en META_APP_SECRET del .env, reinicia el")
        print("  servidor y manda un «Hola» nuevo.")
        print("\n  Para comprobarlo ANTES de tocar el .env:\n")
        print(f"      {G}vb app --secreto PEGA_AQUI_EL_SECRETO{RST}\n")
        return 1

    print(f"  {V}El secreto es el correcto y es de la app que firma.{RST}\n")
    print("  Si aun así el servidor rechaza la firma, ya no es el secreto:")
    print("    1. ¿Reiniciaste el servidor después de cambiar el .env? Se lee")
    print("       una sola vez, al arrancar.")
    print("    2. Comprueba que la huella de arriba sea la misma que muestra")
    print(f"       {G}vb firma{RST} en su paso [1].\n")
    if args.secreto and huella(args.secreto) != huella(s.app_secret_efectivo):
        print(f"  {A}⚠ OJO: el secreto que pegaste NO es el que tiene tu .env.{RST}")
        print("      Este es el bueno: pégalo en META_APP_SECRET y reinicia.\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
