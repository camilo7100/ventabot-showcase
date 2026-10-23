#!/usr/bin/env python3
"""Activa el número en la Cloud API: los DOS pasos que el panel no hace solo.

    vb registrar

EL PROBLEMA QUE RESUELVE
========================
Puedes tener el webhook verificado, la URL correcta, la firma perfecta... y no
recibir NADA. Meta genera los eventos (los ves en su panel) pero no se los
entrega a nadie, porque falta una suscripción que el panel no crea sola.

Son dos llamadas a la API que casi ninguna guía menciona:

  1. POST /{phone_number_id}/register
     Registra el número en la Cloud API con un PIN de verificación en dos
     pasos. Sin esto el número existe en el panel pero no está "activo" para
     enviar ni recibir.

  2. POST /{WABA_ID}/subscribed_apps
     Suscribe TU APP a la cuenta de WhatsApp. Este es el que falta casi
     siempre. Sin él Meta produce los eventos y no tiene a quién dárselos.

El botón «Probar» del panel sí funciona sin esto, porque hace un POST directo
a tu URL saltándose la suscripción. Por eso engaña tanto: parece que la mitad
funciona.
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
OK, NO = f"{V}✔{RST}", f"{R}✘{RST}"

API = "https://graph.facebook.com/v21.0"

#: Errores de Meta traducidos a algo accionable. El mensaje crudo de Graph
#: rara vez dice qué hacer.
EXPLICACIONES = {
    190: (
        "Tu token de acceso caducó o no es válido.",
        "Genera uno nuevo: WhatsApp → Configuración de la API → «Generar».",
        "El token temporal dura 24 horas.",
    ),
    100: (
        "Un identificador no existe o no te pertenece.",
        "Revisa WA_PHONE_NUMBER_ID y WA_BUSINESS_ACCOUNT_ID en tu .env.",
        "Cópialos otra vez de WhatsApp → Configuración de la API.",
    ),
    200: (
        "Al token le faltan permisos.",
        "Genéralo de nuevo desde el panel de WhatsApp, no desde otra sección.",
    ),
    133005: (
        "El PIN de verificación en dos pasos no coincide.",
        "Si alguna vez pusiste un PIN a este número, pásalo con:",
        "    vb registrar --pin TU_PIN",
    ),
    133016: (
        "El número ya fue registrado hace poco; Meta pide esperar.",
        "Espera unos minutos y vuelve a intentarlo.",
    ),
}


def es_numero_de_prueba(info: dict) -> bool:
    """Los números que regala Meta ya vienen registrados por ellos.

    Llamar a /register sobre uno de ellos falla con «Two step verification PIN
    Mismatch», y ese error asusta sin motivo: no hay nada que arreglar. Ese
    endpoint es para TU número real, en producción.
    """
    nombre = (info.get("verified_name") or "").strip().lower()
    numero = (info.get("display_phone_number") or "").replace(" ", "").replace("-", "")
    return nombre == "test number" or numero.startswith("+1555")


def explicar(cuerpo: dict) -> list[str]:
    err = cuerpo.get("error") or {}
    codigo = err.get("code")
    lineas = [err.get("message", "sin mensaje")]
    if codigo in EXPLICACIONES:
        lineas += ["", *EXPLICACIONES[codigo]]
    return lineas


def llamar(
    metodo: str, url: str, token: str, datos: dict | None = None
) -> tuple[bool, dict]:
    try:
        r = httpx.request(
            metodo,
            url,
            headers={"Authorization": f"Bearer {token}"},
            json=datos,
            timeout=30,
        )
    except Exception as exc:
        return False, {"error": {"message": f"no pude llegar a Meta: {exc}"}}
    try:
        cuerpo = r.json()
    except Exception:
        cuerpo = {"error": {"message": r.text[:200]}}
    return r.status_code == 200, cuerpo


def main() -> int:
    ap = argparse.ArgumentParser(description="Activa el número en la Cloud API")
    ap.add_argument(
        "--pin",
        default="000000",
        help="PIN de verificación en dos pasos (6 dígitos). Si nunca pusiste "
        "uno, deja el que viene por defecto.",
    )
    ap.add_argument(
        "--solo-comprobar",
        action="store_true",
        help="mira cómo está todo sin cambiar nada",
    )
    args = ap.parse_args()
    s = get_settings()

    print(f"\n{C}{'=' * 74}\n  ACTIVAR EL NÚMERO EN LA CLOUD API\n{'=' * 74}{RST}")

    faltan = [
        n
        for n, v in {
            "WA_ACCESS_TOKEN": s.wa_access_token,
            "WA_PHONE_NUMBER_ID": s.wa_phone_number_id,
            "WA_BUSINESS_ACCOUNT_ID": s.wa_business_account_id,
        }.items()
        if not v
    ]
    if faltan:
        print(f"\n  {NO} Faltan en tu .env: {', '.join(faltan)}\n")
        print("  Los tres están en Meta → WhatsApp → Configuración de la API.")
        print("  El token se genera con el botón «Generar» de esa misma pantalla.\n")
        return 1

    tok = s.wa_access_token
    print(f"  número (phone_number_id): {s.wa_phone_number_id}")
    print(f"  cuenta  (WABA id):        {s.wa_business_account_id}")

    # ---- estado actual ----
    print(f"\n{G}[1]{RST} Cómo está el número ahora")
    ok, cuerpo = llamar("GET", f"{API}/{s.wa_phone_number_id}", tok)
    info_numero = cuerpo
    if not ok:
        print(f"  {NO} " + "\n      ".join(explicar(cuerpo)))
        return 1
    print(
        f"  {OK} {cuerpo.get('display_phone_number', '?')} · "
        f"nombre: {cuerpo.get('verified_name', '?')}"
    )
    estado_num = cuerpo.get("status") or cuerpo.get("code_verification_status") or "?"
    print(f"      estado: {estado_num} · calidad: {cuerpo.get('quality_rating', '?')}")

    print(f"\n{G}[2]{RST} Qué apps están suscritas a tu cuenta de WhatsApp")
    ok, cuerpo = llamar("GET", f"{API}/{s.wa_business_account_id}/subscribed_apps", tok)
    if not ok:
        print(f"  {NO} " + "\n      ".join(explicar(cuerpo)))
        return 1
    suscritas = cuerpo.get("data") or []
    if suscritas:
        for a in suscritas:
            d = a.get("whatsapp_business_api_data", {})
            print(f"  {OK} {d.get('name', '?')}  (id {d.get('id', '?')})")
    else:
        print(f"  {NO} NINGUNA app está suscrita.")
        print(f"      {A}Esta es la causa de que no te lleguen los webhooks.{RST}")
        print("      Meta genera los eventos y no tiene a quién entregárselos.")

    if args.solo_comprobar:
        print(f"\n  {G}(--solo-comprobar: no cambié nada){RST}\n")
        return 0 if suscritas else 1

    # ---- paso 1: registrar el número ----
    print(f"\n{G}[3]{RST} Registrando el número en la Cloud API")
    if es_numero_de_prueba(info_numero):
        print(f"  {OK} es un número de PRUEBA de Meta: ya viene registrado")
        print(
            f"      {G}Este paso solo hace falta con tu número real, en la Fase 4.{RST}"
        )
    else:
        ok, cuerpo = llamar(
            "POST",
            f"{API}/{s.wa_phone_number_id}/register",
            tok,
            {"messaging_product": "whatsapp", "pin": args.pin},
        )
        if ok:
            print(f"  {OK} registrado")
        else:
            msg = (cuerpo.get("error") or {}).get("message", "")
            if "already" in msg.lower():
                print(f"  {OK} ya estaba registrado (no hace falta hacer nada)")
            else:
                print(f"  {NO} " + "\n      ".join(explicar(cuerpo)))

    # ---- paso 2: suscribir la app ----
    print(f"\n{G}[4]{RST} Suscribiendo tu app a la cuenta de WhatsApp")
    ok, cuerpo = llamar("POST", f"{API}/{s.wa_business_account_id}/subscribed_apps", tok)
    if ok and cuerpo.get("success"):
        print(f"  {OK} suscrita")
    else:
        print(f"  {NO} " + "\n      ".join(explicar(cuerpo)))
        return 1

    # ---- confirmación ----
    print(f"\n{G}[5]{RST} Comprobando que quedó")
    ok, cuerpo = llamar("GET", f"{API}/{s.wa_business_account_id}/subscribed_apps", tok)
    ahora = (cuerpo.get("data") or []) if ok else []
    if not ahora:
        print(f"  {NO} sigue sin aparecer ninguna app suscrita")
        return 1
    for a in ahora:
        d = a.get("whatsapp_business_api_data", {})
        print(f"  {OK} {d.get('name', '?')}")

    print(f"\n{C}{'=' * 74}{RST}")
    print(f"  {V}Listo. Ahora escríbele «Hola» al número desde tu celular{RST}")
    print(f"  {V}y mira la ventana del servidor.{RST}")
    print(f"\n  Si no aparece nada, comprueba la cadena con:  {C}vb conexion{RST}")
    print(f"{C}{'=' * 74}{RST}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
