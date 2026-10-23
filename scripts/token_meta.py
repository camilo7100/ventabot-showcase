#!/usr/bin/env python3
"""Comprueba el token de Meta: si sirve, cuánto le queda y cómo renovarlo.

    vb token

POR QUÉ EXISTE
==============
El token que Meta te regala en «WhatsApp → Configuración de la API» es
TEMPORAL: dura 24 horas. Cuando caduca, el bot sigue RECIBIENDO mensajes
perfectamente y deja de poder RESPONDER. Desde fuera parece que se rompió
todo, pero solo se rompió la mitad, y la que se rompió no es la difícil.

El síntoma en el log es este, repetido:

    fallo al enviar: Client error '401 Unauthorized' ...

Ese mensaje no dice ni que sea el token, ni que sea normal, ni qué hacer.
Este comando sí.

CÓMO NO VOLVER A PASAR POR AQUÍ
===============================
Con `--permanente` te explica el token de usuario del sistema, que no caduca
nunca. Son cinco minutos una sola vez, y te ahorra este rato cada mañana.
"""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime
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

PERMANENTE = """
CÓMO CONSEGUIR UN TOKEN QUE NO CADUQUE (5 minutos, una sola vez)
================================================================
El token del panel de WhatsApp dura 24 horas A PROPÓSITO: es para probar.
El de verdad se saca de un «usuario del sistema», que es una cuenta que no
es una persona y por eso no tiene sesión que expire.

  1. Entra a  https://business.facebook.com/settings/system-users
     (Configuración del negocio → Usuarios → Usuarios del sistema)

  2. «Agregar» → ponle un nombre (por ejemplo: ventabot) → rol
     «Administrador» → Crear.

  3. Con el usuario seleccionado: «Agregar activos» → pestaña «Cuentas de
     WhatsApp» → marca tu cuenta → activa «Control total» → Guardar.
     SIN ESTE PASO el token se genera pero no sirve para nada.

  4. «Generar nuevo token»:
       · aplicación: la tuya (la misma de siempre)
       · caducidad: «Nunca»
       · permisos: marca  whatsapp_business_messaging
                          whatsapp_business_management
     → Generar.

  5. Cópialo AHORA. Meta no vuelve a enseñarlo nunca más.
     Pégalo en tu .env, en WA_ACCESS_TOKEN, y reinicia el servidor.

  6. Compruébalo:   vb token

Ese token no caduca. Trátalo como una contraseña: no lo subas a git
(.env ya está en .gitignore) y no lo pegues en un chat.
"""


def pedir(ruta: str, token: str, params: dict | None = None) -> tuple[int, dict]:
    try:
        r = httpx.get(
            f"{API}/{ruta}",
            headers={"Authorization": f"Bearer {token}"},
            params=params or {},
            timeout=20,
        )
    except Exception as exc:
        return 0, {"error": {"message": f"no pude llegar a Meta: {exc}"}}
    try:
        return r.status_code, r.json()
    except Exception:
        return r.status_code, {"error": {"message": r.text[:200]}}


def humanizar(segundos: float) -> str:
    if segundos <= 0:
        return "ya caducó"
    horas = segundos / 3600
    if horas < 1:
        return f"{segundos / 60:.0f} minutos"
    if horas < 48:
        return f"{horas:.0f} horas"
    return f"{horas / 24:.0f} días"


def main() -> int:
    ap = argparse.ArgumentParser(description="Comprueba el token de Meta")
    ap.add_argument(
        "--permanente",
        action="store_true",
        help="explica cómo sacar un token que no caduca nunca",
    )
    args = ap.parse_args()

    if args.permanente:
        print(PERMANENTE)
        return 0

    s = get_settings()
    token = (s.wa_access_token or "").strip()

    print(f"\n{C}{'=' * 74}\n  TOKEN DE META\n{'=' * 74}{RST}")

    if not token:
        print(f"\n  {NO} WA_ACCESS_TOKEN está VACÍO en tu .env.")
        print("      El bot puede RECIBIR mensajes pero no puede responder ninguno.\n")
        print(f"      {A}→{RST} Genéralo en: WhatsApp → Configuración de la API →")
        print("          botón «Generar» junto a «Token de acceso».\n")
        return 1

    print(f"\n{G}[1]{RST} Forma del token")
    print(f"      longitud: {len(token)} caracteres · empieza por {token[:4]}…")
    if not token.startswith("EAA"):
        print(f"  {A}⚠ los tokens de Meta empiezan por «EAA». ¿Copiaste otra cosa?{RST}")

    # ---- 2. ¿sirve? La prueba real: preguntar por TU número. ----
    print(f"\n{G}[2]{RST} Si Meta lo acepta")
    if not s.wa_phone_number_id:
        print(f"  {DUDA} WA_PHONE_NUMBER_ID vacío: no puedo hacer la prueba real.")
        return 1
    codigo, cuerpo = pedir(
        s.wa_phone_number_id, token, {"fields": "display_phone_number,verified_name"}
    )
    if codigo == 200:
        print(
            f"  {OK} sirve · número {cuerpo.get('display_phone_number', '?')} "
            f"({cuerpo.get('verified_name', '?')})"
        )
    else:
        err = cuerpo.get("error") or {}
        print(f"  {NO} Meta lo rechaza: {err.get('message', '?')}")
        if codigo == 401 or err.get("code") == 190:
            print(f"\n{C}{'=' * 74}\n  QUÉ HACER (2 minutos)\n{'=' * 74}{RST}")
            print("""
  El token CADUCÓ. Es lo normal: el del panel dura 24 horas.
  No se rompió nada más — los mensajes te siguen llegando.

    1. Abre:  https://developers.facebook.com/apps
    2. Tu app → WhatsApp → Configuración de la API
    3. En «Token de acceso», botón «Generar». Cópialo.
    4. Abre el archivo .env de tu proyecto y pégalo en:

           WA_ACCESS_TOKEN=EAA...

       (pégalo TAL CUAL, sin comillas y sin comentarios en esa línea)

    5. Cierra el servidor con Ctrl+C y vuelve a abrirlo:   vb server
       El .env solo se lee al arrancar.

    6. Comprueba:   vb token

  Para no repetir esto cada día:   vb token --permanente
""")
        return 1

    # ---- 3. ¿cuánto le queda? ----
    print(f"\n{G}[3]{RST} Cuánto le queda de vida")
    codigo, cuerpo = pedir("debug_token", token, {"input_token": token})
    datos = cuerpo.get("data") if codigo == 200 else None
    if not datos:
        print(f"  {DUDA} Meta no me deja consultarlo con este tipo de token.")
        print("      No pasa nada: el paso [2] ya demostró que sirve AHORA.")
    else:
        expira = datos.get("expires_at", 0)
        if not expira:
            print(f"  {OK} {V}NO CADUCA.{RST} Es un token permanente: no vuelves a")
            print("      pasar por esto.")
        else:
            restante = expira - datetime.now(UTC).timestamp()
            cuando = datetime.fromtimestamp(expira, UTC).astimezone()
            marca = OK if restante > 6 * 3600 else NO if restante <= 0 else DUDA
            print(f"  {marca} caduca en {humanizar(restante)} ({cuando:%d/%m %H:%M})")
            if restante < 24 * 3600:
                print(f"\n      {A}Este es el token temporal de 24 horas.{RST}")
                print("      Mañana vuelves a estar aquí. Para acabar con eso:")
                print(f"          {G}vb token --permanente{RST}")

    print(f"\n{C}{'=' * 74}{RST}")
    print(f"  {V}El bot puede responder.{RST}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
