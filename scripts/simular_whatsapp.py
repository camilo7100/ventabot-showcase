#!/usr/bin/env python3
"""Simula un mensaje de WhatsApp contra tu propio servidor.

    python scripts/simular_whatsapp.py "hola"
    python scripts/simular_whatsapp.py "quiero 2 CAM-PRE-001"
    python scripts/simular_whatsapp.py            # modo conversación

POR QUÉ ESTO EXISTE
===================
Cuando algo no funcione, la primera pregunta va a ser "¿es mi código o es
Meta?". Con este script la respondes en cinco segundos: construye un webhook
con la MISMA forma que manda Meta, lo FIRMA con tu mismo META_APP_SECRET, y lo
manda a tu servidor. Si el flujo funciona aquí y falla con Meta, el problema
está en la configuración de Meta, no en tu código.

También te ahorra los mensajes reales mientras desarrollas: el número de prueba
de Meta solo admite 5 destinatarios y hay límites de envío.
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import sys
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx

from app.infra.consola import preparar_salida
from app.infra.settings import get_settings

# UTF-8 y color solo si hay terminal: sin esto, redirigir la salida a un
# archivo revienta en Windows al imprimir un ✔ (cp1252 no lo soporta).
_C = preparar_salida()
V, A, R, G, C, RST = (_C.ok, _C.aviso, _C.error, _C.tenue, _C.titulo, _C.fin)

NUMERO_DEMO = "573001112233"
NOMBRE_DEMO = "Camilo"


def construir_payload(
    texto: str, *, numero: str, nombre: str, message_id: str, phone_number_id: str
) -> dict:
    """Réplica exacta de la forma que manda Meta.

    Si algún día cambias el parser, este payload es tu red de seguridad: está
    copiado de la documentación de Meta, no inventado.
    """
    return {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": "WABA_ID_DE_PRUEBA",
                "changes": [
                    {
                        "field": "messages",
                        "value": {
                            "messaging_product": "whatsapp",
                            "metadata": {
                                "display_phone_number": "573000000000",
                                "phone_number_id": phone_number_id,
                            },
                            "contacts": [{"profile": {"name": nombre}, "wa_id": numero}],
                            "messages": [
                                {
                                    "from": numero,
                                    "id": message_id,
                                    "timestamp": str(int(time.time())),
                                    "type": "text",
                                    "text": {"body": texto},
                                }
                            ],
                        },
                    }
                ],
            }
        ],
    }


def firmar(cuerpo: bytes, app_secret: str) -> str:
    """La firma va sobre los BYTES EXACTOS que se envían.

    Por eso aquí primero serializamos a bytes y firmamos ESOS bytes, y luego
    mandamos los mismos. Si serializáramos dos veces, la firma no cuadraría —
    que es exactamente el bug nº1 del que habla app/api/main.py.
    """
    return "sha256=" + hmac.new(app_secret.encode(), cuerpo, hashlib.sha256).hexdigest()


def enviar(
    texto: str,
    *,
    url: str,
    secreto: str,
    numero: str,
    nombre: str,
    phone_number_id: str,
    message_id: str | None = None,
    verbose: bool = False,
) -> tuple[int, dict]:
    mid = message_id or f"wamid.SIM{uuid.uuid4().hex[:16].upper()}"
    payload = construir_payload(
        texto,
        numero=numero,
        nombre=nombre,
        message_id=mid,
        phone_number_id=phone_number_id,
    )
    cuerpo = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    cabeceras = {
        "Content-Type": "application/json",
        "X-Hub-Signature-256": firmar(cuerpo, secreto),
    }
    if verbose:
        print(f"{G}POST {url}")
        print(f"     X-Hub-Signature-256: {cabeceras['X-Hub-Signature-256'][:26]}…")
        print(f"     message_id: {mid}{RST}")
    r = httpx.post(url, content=cuerpo, headers=cabeceras, timeout=60)
    try:
        return r.status_code, r.json()
    except Exception:
        return r.status_code, {"body": r.text[:200]}


def main() -> int:
    s = get_settings()
    ap = argparse.ArgumentParser(description="Simula mensajes de WhatsApp")
    ap.add_argument(
        "texto", nargs="*", help="el mensaje; sin nada entra en modo conversación"
    )
    ap.add_argument("--url", default="http://127.0.0.1:8000/webhook/whatsapp")
    ap.add_argument("--numero", default=NUMERO_DEMO)
    ap.add_argument("--nombre", default=NOMBRE_DEMO)
    ap.add_argument(
        "--repetir",
        type=int,
        default=1,
        help="manda el MISMO message_id N veces, para probar la deduplicación",
    )
    ap.add_argument(
        "--firma-mala",
        action="store_true",
        help="manda una firma incorrecta; el servidor debe responder 403",
    )
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    secreto = s.app_secret_efectivo
    if args.firma_mala:
        secreto = "secreto-equivocado"

    def una(texto: str) -> None:
        mid = f"wamid.SIM{uuid.uuid4().hex[:16].upper()}"
        for i in range(args.repetir):
            print(
                f"\n{C}👤 TÚ → {args.numero}{RST}  {G}{texto}{RST}"
                + (
                    f"  {A}(envío {i + 1} de {args.repetir}, mismo id){RST}"
                    if args.repetir > 1
                    else ""
                )
            )
            try:
                codigo, cuerpo = enviar(
                    texto,
                    url=args.url,
                    secreto=secreto,
                    numero=args.numero,
                    nombre=args.nombre,
                    phone_number_id=s.wa_phone_number_id or "TEST",
                    message_id=mid,
                    verbose=args.verbose,
                )
            except httpx.ConnectError:
                print(f"{R}   ✘ No hay nadie escuchando en {args.url}{RST}")
                print(f"{A}     Arranca el servidor en OTRA ventana con:  vb server{RST}")
                raise SystemExit(1) from None
            color = V if codigo == 200 else R
            cuerpo_txt = json.dumps(cuerpo, ensure_ascii=False)
            print(f"{color}   ← HTTP {codigo}  {cuerpo_txt}{RST}")
            if codigo == 200 and cuerpo.get("encolados") == 0 and i > 0:
                print(f"{V}   ✔ deduplicado: el servidor NO volvió a responder{RST}")
        print(f"{G}   (la respuesta del bot sale en la ventana del servidor){RST}")

    if args.texto:
        una(" ".join(args.texto))
        return 0

    print(f"\n{C}Modo conversación.{RST} Escribe mensajes; Enter vacío para salir.")
    print(f"{G}Las respuestas del bot aparecen en la ventana del servidor.{RST}")
    while True:
        try:
            texto = input(f"\n{C}👤 tú> {RST}").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if not texto:
            return 0
        una(texto)


if __name__ == "__main__":
    raise SystemExit(main())
