#!/usr/bin/env python3
"""Muestra los últimos webhooks que llegaron, válidos o no.

    vb webhooks            los últimos 20
    vb webhooks --todos    los 500 que guarda

Responde de un vistazo las preguntas que importan cuando algo no funciona:

    ¿está llegando ALGO?      -> si la tabla está vacía, Meta no te alcanza
    ¿de qué cuenta viene?     -> compara el WABA id con el de tu panel
    ¿la firma cuadró?         -> separa "no llega" de "llega y se rechaza"
    ¿era el ejemplo de Meta?  -> el botón «Probar» no prueba nada
    ¿se encoló una respuesta? -> separa "no entiende" de "no responde"

Cada una de esas cuatro preguntas apunta a un arreglo distinto. Sin esta tabla
se confunden entre sí y se depura a ciegas.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

from app.adapters.repositories.webhook_log import leer
from app.infra.consola import preparar_salida
from app.infra.settings import get_settings

_C = preparar_salida()
V, R, A, G, C, RST = (_C.ok, _C.error, _C.aviso, _C.tenue, _C.titulo, _C.fin)


def main() -> int:
    ap = argparse.ArgumentParser(description="Últimos webhooks recibidos")
    ap.add_argument("--todos", action="store_true")
    ap.add_argument("-n", type=int, default=20)
    args = ap.parse_args()

    s = get_settings()
    ruta = s.sqlite_path.parent / "webhook_log.jsonl"
    filas = leer(ruta, 500 if args.todos else args.n)

    print(f"\n{C}{'=' * 78}\n  WEBHOOKS RECIBIDOS\n{'=' * 78}{RST}")
    print(f"  {G}{ruta}{RST}\n")

    if not filas:
        print(f"  {A}No ha llegado NINGÚN webhook a este servidor.{RST}\n")
        print("  Eso no es un problema de firma ni de código: Meta no te alcanza.")
        print("  Revisa, en este orden:\n")
        print("    1. ¿Está corriendo ngrok? ¿La URL que muestra es la MISMA que")
        print("       tienes configurada en Meta? Con el plan gratis CAMBIA cada")
        print("       vez que lo reinicias, y hay que actualizarla en el panel.")
        print("    2. ¿Tu app está SUSCRITA a tu cuenta de WhatsApp? Meta entrega")
        print("       los webhooks solo a las apps suscritas, y el panel NO crea")
        print("       esa suscripción solo. Compruébalo con:")
        print("           vb registrar --solo-comprobar")
        print("    3. En Meta -> WhatsApp -> Configuración -> Webhook -> «Administrar»,")
        print("       ¿está MARCADA la casilla del campo `messages`?")
        print("    4. ¿La URL termina en /webhook/whatsapp?\n")
        return 1

    print(f"  {'hora':<10} {'firma':<7} {'qué':<22} {'de':<14} {'texto':<24}")
    print(f"  {G}{'─' * 76}{RST}")
    for f in filas:
        hora = f.get("cuando", "")[11:19]
        ok = f.get("firma_valida")
        firma = f"{V}válida{RST}" if ok else f"{R}NO{RST}    "

        if f.get("es_ejemplo_de_meta"):
            que = f"{A}ejemplo «Probar»{RST}     "
        elif f.get("n_mensajes"):
            que = f"{V}mensaje{RST}               "
        elif f.get("n_estados"):
            que = f"{G}acuse: {f.get('estado', '?')}{RST}".ljust(31)
        else:
            que = f"{G}otro{RST}                  "

        de = (f.get("de") or "—")[:13]
        texto = (f.get("texto") or "")[:23]
        enc = f.get("encolados")
        marca = (
            ""
            if enc is None
            else (f"  {G}→ encolado{RST}" if enc else f"  {A}→ nada encolado{RST}")
        )
        print(f"  {hora:<10} {firma} {que} {de:<14} {texto:<24}{marca}")

    # --- lectura automática de la tabla ---
    print(f"\n{C}{'=' * 78}\n  QUÉ SIGNIFICA{RST}")
    reales = [f for f in filas if f.get("n_mensajes") and not f.get("es_ejemplo_de_meta")]
    ejemplos = [f for f in filas if f.get("es_ejemplo_de_meta")]
    rechazados = [f for f in filas if not f.get("firma_valida")]
    wabas = {f.get("waba_id") for f in filas if f.get("waba_id") not in (None, "0")}

    print(
        f"  · {len(filas)} webhook(s) · {len(reales)} mensaje(s) real(es) · "
        f"{len(ejemplos)} del botón «Probar» · {len(rechazados)} rechazado(s)"
    )
    if wabas:
        print(f"  · cuentas de WhatsApp vistas: {', '.join(sorted(map(str, wabas)))}")

    print()
    if not reales:
        print(f"  {A}No ha llegado ni un solo mensaje real.{RST}")
        print("  Escríbele al número de prueba desde tu celular. Si aun así no")
        print("  aparece aquí, el campo `messages` no está marcado en Meta o la")
        print("  URL de ngrok cambió.")
    elif all(not f.get("firma_valida") for f in reales):
        print(f"  {R}Llegan mensajes reales pero TODOS se rechazan por firma.{RST}")
        print("  Lo bueno: la conexión funciona. Solo falta el secreto correcto.")
        print("  En este orden, y para cuando el primero te responda:")
        print("      vb app      <- le pregunta a Meta CUÁL es el secreto bueno")
        print("      vb firma    <- analiza byte a byte el webhook rechazado")
    elif any(f.get("firma_valida") and not f.get("encolados") for f in reales):
        print(f"  {A}Llegan y la firma cuadra, pero no se encola respuesta.{RST}")
        print("  El problema está DESPUÉS del webhook. Mira el log del servidor.")
    else:
        print(f"  {V}Llegan mensajes reales, la firma cuadra y se encolan.{RST}")
        print("  Si el cliente no recibe nada, el problema es al ENVIAR:")
        print("  revisa que WA_ACCESS_TOKEN esté puesto y no haya caducado.")
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
