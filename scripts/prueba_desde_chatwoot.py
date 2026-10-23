#!/usr/bin/env python3
"""Lía contesta DESDE Chatwoot y se comprueba que sale hacia WhatsApp de verdad.

    python scripts/prueba_desde_chatwoot.py

El ensayo (`scripts/ensayo_chatwoot.py`) prueba esto contra un bot de mentira en
:8001, sin Meta. Aqui se prueba contra el bot REAL en :8000 y contra la API de
Meta: lo unico que demuestra que un mensaje escrito en Chatwoot llega al
telefono de la clienta es que Meta devuelva un `wamid`.

Numero de prueba, nunca una clienta real. Al final se borra el contacto.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))
os.chdir(RAIZ)

import httpx
from dotenv import dotenv_values

NUMERO = "570000000077"
CONV = f"wa:{NUMERO}"
REGISTRO = RAIZ / "logs" / "servidor.log"

e = dotenv_values(RAIZ / ".env")
BASE = e["CHATWOOT_URL"].rstrip("/")
CUENTA = e["CHATWOOT_ACCOUNT_ID"]
API = f"{BASE}/api/v1/accounts/{CUENTA}"
H = {"api_access_token": e["CHATWOOT_TOKEN"]}


def paso(n, texto):
    print(f"\n{n}. {texto}")


def ok(texto):
    print(f"    OK  {texto}")


def mal(texto):
    print(f"    MAL {texto}")
    raise SystemExit(1)


def cola_del_registro(desde: int) -> str:
    """Lo escrito DESPUES de `desde`. En bytes: el registro no es ASCII y
    cortar una cadena ya decodificada por un tamaño en bytes devuelve vacío."""
    return REGISTRO.read_bytes()[desde:].decode("utf-8", errors="replace")


def esperar(condicion, segundos=40, cada=2):
    limite = time.time() + segundos
    while time.time() < limite:
        if r := condicion():
            return r
        time.sleep(cada)
    return None


def buscar_conversacion() -> int | None:
    r = httpx.get(f"{API}/contacts/search", headers=H, params={"q": NUMERO}, timeout=20)
    r.raise_for_status()
    for c in r.json().get("payload", []):
        cs = httpx.get(f"{API}/contacts/{c['id']}/conversations", headers=H, timeout=20)
        for conv in cs.json().get("payload", []):
            return conv["id"]
    return None


def contacto() -> int | None:
    r = httpx.get(f"{API}/contacts/search", headers=H, params={"q": NUMERO}, timeout=20)
    for c in r.json().get("payload", []):
        return c["id"]
    return None


def devolver_al_bot() -> None:
    """Suelta el número de prueba, por si una corrida anterior quedó a medias.

    Sin esto, una corrida cortada antes del paso 6 deja al bot creyendo que
    Lía atiende ese número, y la siguiente falla en el paso 1 con «el bot no
    contestó». Solo toca ESTE número, por el mismo botón del panel.
    """
    httpx.post(
        "http://127.0.0.1:8000/panel/devolver",
        params={"token": e.get("PANEL_TOKEN", "")},
        data={"conv": CONV},
        timeout=20,
    )


def main() -> int:
    print("LIA CONTESTA DESDE CHATWOOT  (bot real en :8000, Meta de verdad)")
    devolver_al_bot()
    marca = REGISTRO.stat().st_size

    paso(1, "La clienta de prueba escribe por WhatsApp")
    subprocess.run(
        [
            str(RAIZ / ".venv/Scripts/python.exe"),
            "scripts/simular_whatsapp.py",
            "--numero",
            NUMERO,
            "hola, cuanto vale el anillo?",
        ],
        check=True,
        capture_output=True,
    )
    if not esperar(lambda: "encoladas" in cola_del_registro(marca)):
        mal("el bot no contestó")
    ok("el bot contestó")

    conv = esperar(buscar_conversacion, 120, cada=4)
    if not conv:
        mal("la conversación no apareció en Chatwoot")
    ok(f"aparece en Chatwoot (conversación {conv})")

    paso(2, "Lía se la asigna (el bot debe callarse)")
    yo = httpx.get(f"{BASE}/api/v1/profile", headers=H, timeout=20).json()["id"]
    httpx.post(
        f"{API}/conversations/{conv}/assignments",
        headers=H,
        json={"assignee_id": yo},
        timeout=20,
    ).raise_for_status()
    ok("asignada")

    paso(3, "Lía escribe desde Chatwoot")
    marca = REGISTRO.stat().st_size
    texto = "Hola! Te escribe Lía en persona 💜 el anillo de una huellita vale $200.000"
    r = httpx.post(
        f"{API}/conversations/{conv}/messages",
        headers=H,
        json={"content": texto, "message_type": "outgoing"},
        timeout=30,
    )
    r.raise_for_status()
    ok("Chatwoot aceptó el mensaje")

    paso(4, "¿Salió hacia WhatsApp? (lo prueba el wamid que devuelve Meta)")

    def salio():
        c = cola_del_registro(marca)
        return c if "wamid." in c else None

    cola = esperar(salio, 60)
    if not cola:
        print(cola_del_registro(marca)[-1500:])
        mal("no salió: Meta nunca devolvió un wamid")
    lineas = [ln for ln in cola.splitlines() if "wamid." in ln]
    ok(f"Meta lo aceptó · {lineas[-1].split('enviado')[-1].strip()[:60]}")
    if "Chatwoot en" not in cola and "chatwoot" not in cola.lower():
        print("    (aviso) no se vio la traza de Chatwoot en el registro")

    paso(5, "El bot sigue callado (la atiende Lía)")
    marca = REGISTRO.stat().st_size
    subprocess.run(
        [
            str(RAIZ / ".venv/Scripts/python.exe"),
            "scripts/simular_whatsapp.py",
            "--numero",
            NUMERO,
            "y de dos huellitas?",
        ],
        check=True,
        capture_output=True,
    )
    time.sleep(12)
    cola = cola_del_registro(marca)
    if "asesora" in cola:
        mal("el bot contestó encima de Lía")
    ok("el bot no contestó encima")

    paso(6, "Se limpia")
    # Primero se devuelve al bot, como haría Lía al terminar (la etiqueta de
    # «🤖 Devolver al bot»; resolver ya NO devuelve, 09/10). Borrar el contacto
    # sin devolverla dejaba al número «atendido por una persona» y la segunda
    # corrida del día fallaba en el paso 1 (21/09).
    marca = REGISTRO.stat().st_size
    httpx.post(
        f"{API}/conversations/{conv}/labels",
        headers=H,
        json={"labels": ["hacer-devolver-al-bot"]},
        timeout=20,
    )
    if not esperar(lambda: "devuelta al bot" in cola_del_registro(marca), 30):
        devolver_al_bot()
        ok("el bot la recuperó por el panel")
    else:
        ok("devuelta al bot desde Chatwoot")
    if (c := contacto()) is not None:
        httpx.delete(f"{API}/contacts/{c}", headers=H, timeout=30)
    ok("contacto de prueba borrado (no se tocan las demás charlas)")

    print("\nTODO BIEN · lo escrito en Chatwoot llegó a WhatsApp")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
