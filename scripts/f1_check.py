#!/usr/bin/env python3
"""CRITERIO DE ACEPTACIÓN DE LA FASE 1 — el walking skeleton.

    "Un mensaje entra por el webhook y sale una respuesta. Mandas el mismo
     webhook dos veces y el bot responde UNA sola vez."

Uso (con el servidor corriendo en OTRA ventana):

    vb server          <- en una ventana
    vb f1-check        <- en otra

Comprueba, en orden y parando en el primer fallo:

  1. El servidor responde.
  2. El handshake de Meta acepta el token bueno y RECHAZA el malo.
  3. Un webhook con firma inválida se rechaza con 403.
  4. Un mensaje entra, el grafo corre y la respuesta sale por el canal.
  5. El MISMO mensaje repetido no genera una segunda respuesta.
  6. Todo quedó guardado en disco: sobrevive a un reinicio.
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx

from app.infra.consola import preparar_salida
from app.infra.settings import get_settings
from scripts.simular_whatsapp import enviar

# UTF-8 y color solo si hay terminal: sin esto, redirigir la salida a un
# archivo revienta en Windows al imprimir un ✔ (cp1252 no lo soporta).
_C = preparar_salida()
V, R, A, G, C, RST = (_C.ok, _C.error, _C.aviso, _C.tenue, _C.titulo, _C.fin)
OK, FAIL = f"{V}✔{RST}", f"{R}✘{RST}"

fallos: list[str] = []


def paso(n: int, texto: str) -> None:
    print(f"\n{G}[{n}]{RST} {texto}")


def check(cond: bool, ok_msg: str, fail_msg: str, ayuda: list[str] | None = None) -> bool:
    if cond:
        print(f"  {OK} {ok_msg}")
        return True
    print(f"  {FAIL} {fail_msg}")
    for a in ayuda or []:
        print(f"      {A}→{RST} {a}")
    fallos.append(fail_msg)
    return False


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8000")
    args = ap.parse_args()
    s = get_settings()
    url_hook = f"{args.base}/webhook/whatsapp"

    print(f"\n{C}{'=' * 72}\n  FASE 1 — walking skeleton\n{'=' * 72}{RST}")
    print(f"  servidor : {args.base}")
    print(f"  canal    : {s.channel_backend}")
    print(f"  base     : {s.sqlite_path}")

    # ---- 1. servidor ----
    paso(1, "El servidor responde")
    try:
        salud = httpx.get(f"{args.base}/health", timeout=5).json()
    except Exception as exc:
        check(
            False,
            "",
            f"no responde en {args.base}: {exc}",
            ["Arranca el servidor en OTRA ventana con:  vb server"],
        )
        return veredicto()
    check(True, f"responde · canal={salud['canal']} llm={salud['llm']}", "")
    enviados_antes = salud.get("enviados", 0)

    # ---- 2. handshake de Meta ----
    paso(2, "Handshake de Meta (el GET que hace una sola vez al registrar la URL)")
    reto = "9876543"
    r_ok = httpx.get(
        url_hook,
        params={
            "hub.mode": "subscribe",
            "hub.verify_token": s.meta_verify_token,
            "hub.challenge": reto,
        },
        timeout=10,
    )
    check(
        r_ok.status_code == 200 and r_ok.text.strip() == reto,
        "con el token correcto devuelve el challenge",
        f"con el token correcto devolvió HTTP {r_ok.status_code}: {r_ok.text[:80]}",
        ["Revisa META_VERIFY_TOKEN en tu .env"],
    )
    r_mal = httpx.get(
        url_hook,
        params={
            "hub.mode": "subscribe",
            "hub.verify_token": "token-equivocado",
            "hub.challenge": reto,
        },
        timeout=10,
    )
    check(
        r_mal.status_code == 403,
        "con un token falso responde 403",
        f"con un token falso respondió {r_mal.status_code} en vez de 403",
        ["Cualquiera podría registrar tu webhook. Revisa verify_challenge()"],
    )

    # ---- 3. firma ----
    paso(3, "Un webhook con firma falsa se rechaza")
    codigo, _ = enviar(
        "intento de intrusión",
        url=url_hook,
        secreto="secreto-malo",
        numero="573009999999",
        nombre="Intruso",
        phone_number_id=s.wa_phone_number_id or "TEST",
    )
    check(
        codigo == 403,
        "firma inválida rechazada con 403",
        f"aceptó una firma inválida (HTTP {codigo})",
        [
            "Es una vulnerabilidad: cualquiera podría inyectar mensajes.",
            "Revisa verify_signature() y que se firme el BODY CRUDO.",
        ],
    )

    # ---- 4. mensaje real ----
    paso(4, "Un mensaje entra y la respuesta sale")
    numero = f"5730011{uuid.uuid4().int % 100000:05d}"
    mid = f"wamid.F1{uuid.uuid4().hex[:14].upper()}"
    codigo, cuerpo = enviar(
        "hola buenas",
        url=url_hook,
        secreto=s.app_secret_efectivo,
        numero=numero,
        nombre="Prueba F1",
        phone_number_id=s.wa_phone_number_id or "TEST",
        message_id=mid,
    )
    check(
        codigo == 200 and cuerpo.get("encolados") == 1,
        f"aceptado y encolado (HTTP {codigo})",
        f"HTTP {codigo}, respuesta {cuerpo}",
        ["Revisa META_APP_SECRET: tiene que ser el mismo en el .env y en Meta"],
    )

    # Con LLM_BACKEND=ollama cada mensaje tarda ~3 s, y la primera llamada tras
    # cargar el modelo puede irse a 15 s. Con 12 s de espera esto daba un falso
    # negativo justo en la máquina donde todo funcionaba bien.
    espera_s = 60 if s.llm_backend == "ollama" else 15
    print(f"  {G}   esperando al despachador (hasta {espera_s}s)…{RST}")
    salida_ok = False
    for i in range(espera_s * 2):
        time.sleep(0.5)
        salud = httpx.get(f"{args.base}/health", timeout=5).json()
        if salud.get("enviados", 0) > enviados_antes:
            salida_ok = True
            break
        if i and i % 20 == 0:
            print(f"  {G}   … {i // 2}s (el modelo local puede tardar){RST}")
    check(
        salida_ok,
        "la respuesta salió por el canal",
        f"el despachador no envió nada en {espera_s} segundos",
        [
            "Mira la ventana del servidor: ¿hay algún error?",
            "¿Arrancó el despachador? Debe decir 'despachador de outbox arrancado'",
        ],
    )

    # ---- 5. deduplicación ----
    paso(5, "El mismo mensaje repetido NO genera otra respuesta")
    enviados_antes = httpx.get(f"{args.base}/health", timeout=5).json()["enviados"]
    codigo2, cuerpo2 = enviar(
        "hola buenas",
        url=url_hook,
        secreto=s.app_secret_efectivo,
        numero=numero,
        nombre="Prueba F1",
        phone_number_id=s.wa_phone_number_id or "TEST",
        message_id=mid,
    )  # MISMO message_id
    check(
        codigo2 == 200 and cuerpo2.get("encolados") == 0,
        "el duplicado se descartó (encolados=0)",
        f"el duplicado SÍ se encoló: {cuerpo2}",
        [
            "Meta reintenta sus webhooks. Sin esto, el cliente recibe la",
            "misma respuesta varias veces. Revisa mark_processed().",
        ],
    )
    time.sleep(2.5)
    despues = httpx.get(f"{args.base}/health", timeout=5).json()["enviados"]
    check(
        despues == enviados_antes,
        "no salió ningún mensaje extra",
        f"salieron {despues - enviados_antes} mensajes de más",
    )

    # ---- 6. persistencia ----
    paso(6, "Todo quedó guardado en disco (sobrevive a un reinicio)")
    if not s.sqlite_path.exists():
        check(False, "", f"no existe {s.sqlite_path}")
    else:
        con = sqlite3.connect(str(s.sqlite_path))
        try:

            def cuenta(t: str) -> int:
                return con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]

            ev, out, msg, conv = (
                cuenta("processed_events"),
                cuenta("outbox"),
                cuenta("messages"),
                cuenta("conversations"),
            )
            check(
                ev > 0,
                f"processed_events: {ev} evento(s) — la dedup. es duradera",
                "processed_events está vacía",
            )
            check(out > 0, f"outbox: {out} mensaje(s)", "outbox está vacía")
            check(msg > 0, f"messages: {msg} en el historial", "messages está vacía")
            check(
                conv > 0,
                f"conversations: {conv} conversación(es) con ventana de 24 h",
                "conversations está vacía",
            )
            pend = con.execute(
                "SELECT COUNT(*) FROM outbox WHERE sent_at IS NULL"
            ).fetchone()[0]
            check(
                pend == 0,
                "no quedan mensajes sin enviar",
                f"{pend} mensaje(s) atascados en la outbox",
                ["Mira la columna `error` de la tabla outbox"],
            )
        finally:
            con.close()

    return veredicto()


def veredicto() -> int:
    print(f"\n{C}{'=' * 72}{RST}")
    if fallos:
        print(f"  {R}✘ FASE 1 NO SUPERADA — {len(fallos)} fallo(s):{RST}")
        for f in fallos:
            print(f"     · {f}")
        print(f"\n  {A}Copia esta pantalla completa si necesitas ayuda.{RST}")
        print(f"{C}{'=' * 72}{RST}\n")
        return 1
    print(f"  {V}✔ FASE 1 SUPERADA — el esqueleto camina.{RST}")
    print("""
  Lo que acabas de demostrar:
    · el webhook rechaza a quien no es Meta (firma y token)
    · un mensaje recorre webhook → grafo → outbox → canal
    · los reintentos de Meta no duplican respuestas
    · nada de eso vive en memoria: sobrevive a un reinicio

  Siguiente: cambiar CHANNEL_BACKEND a whatsapp y hablar con Meta de verdad.""")
    print(f"{C}{'=' * 72}{RST}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
