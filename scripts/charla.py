#!/usr/bin/env python3
"""Un turno de una charla de prueba con el bot de verdad (la IA real).

    python scripts/charla.py --conv ana --nombre Ana --texto "hola"
    python scripts/charla.py --conv ana --reaccion "❤️"

En el servidor, con el código a probar copiado en /tmp/vv (como la prueba de
verdad):

    sudo docker compose run --rm --no-deps -T -v /tmp/vv:/app ventabot \\
        python scripts/charla.py --conv ana --texto "hola"

Cada llamada es UN mensaje de ella; la charla sigue donde quedó (misma
`--conv`). Sirve para conversar como una clienta y juzgar cada respuesta antes
de desplegar (Camilo, 13/10). Aislado como la prueba de verdad: base temporal
por charla en `charlas_prueba/`, sin WhatsApp, sin Chatwoot, sin ERP, sin
avisos, sin recordatorios. Números 5700000001xx. Imprime lo que le llegaría y
lo que quedó anotado.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import sys
import tempfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

ap = argparse.ArgumentParser()
ap.add_argument("--conv", required=True)
ap.add_argument("--nombre", default="Clienta")
ap.add_argument("--texto", default=None)
ap.add_argument("--reaccion", default=None)
ap.add_argument("--traza", action="store_true", help="lo que decidió y recortó")
args = ap.parse_args()

BASE = RAIZ / "charlas_prueba"
try:
    BASE.mkdir(exist_ok=True)
except PermissionError:
    # En la imagen del servidor /app no se escribe: `vb charla` monta esta
    # carpeta desde el servidor para que la charla siga entre mensajes.
    BASE = Path(tempfile.gettempdir()) / "charlas_prueba"
    BASE.mkdir(exist_ok=True)
os.environ.update(
    REPOSITORY_BACKEND="sqlite",
    SQLITE_PATH=str(BASE / f"{args.conv}.db"),
    VENTAS_EXCEL=str(BASE / f"{args.conv}.xlsx"),
    CHANNEL_BACKEND="console",
    WA_ACCESS_TOKEN="",
    CHATWOOT_URL="",
    CHATWOOT_TOKEN="",
    SHEETS_SPREADSHEET_ID="",
    AVISOS_BACKEND="ninguno",
    NTFY_TEMA="",
    LANGSMITH_TRACING="false",
    RECORDATORIOS="false",
)
if args.traza:
    # Lo que el turno anota (la jugada, lo que Python corrigió o recortó).
    logging.basicConfig(level=logging.INFO, format="   ~ %(message)s")
else:
    logging.disable(logging.WARNING)

from app.domain.models import Channel, InboundMessage, MediaRef, conversation_id
from app.infra.container import get_container

numero = "5700000001" + str(
    int(hashlib.md5(args.conv.encode()).hexdigest(), 16) % 90 + 10
)
c = get_container()
conv = conversation_id(Channel.WHATSAPP, numero)
antes = c.db.consultar("SELECT COALESCE(MAX(rowid),0) AS n FROM outbox")[0]["n"]
n = antes + 1
media = []
if args.reaccion:
    media.append(MediaRef(kind="reaction", detalle=args.reaccion))  # type: ignore[arg-type]
m = InboundMessage(
    channel=Channel.WHATSAPP,
    external_message_id=f"wamid.charla.{args.conv}.{n}.{os.getpid()}",
    conversation_id=conv,
    sender_id=numero,
    sender_name=args.nombre,
    text=args.texto,
    media=media,
    raw={"type": "reaction" if args.reaccion else "text"},
)
c.procesar_mensaje(m)
for f in c.db.consultar(
    "SELECT payload FROM outbox WHERE destinatario = ? AND rowid > ? ORDER BY rowid",
    (numero, antes),
):
    p = json.loads(f["payload"] or "{}")
    if p.get("media_url"):
        print(f"   [{p.get('kind')}: {str(p['media_url']).rsplit('/', 1)[-1]}]")
    t = p.get("text") or p.get("caption") or ""
    if t:
        print("   BOT: " + t.replace("\n", "\n        "))
if not c.db.consultar(
    "SELECT 1 FROM outbox WHERE destinatario = ? AND rowid > ?", (numero, antes)
):
    print("   (el bot no contestó)")
b = c.bot._mundo.contexto(conv).borrador or {}
otros = b.get("otros_anillos") or b.get("anillos") or []
print(
    "   · anotado: "
    + json.dumps(
        {
            k: b.get(k)
            for k in (
                "cantidad",
                "talla",
                "huellitas",
                "grabado",
                "nombre_clienta",
                "lo_manda_despues",
                "anillos_total",
            )
            if b.get(k) not in (None, [], {}, "")
        }
        | ({"otros": len(otros)} if otros else {}),
        ensure_ascii=False,
    )[:300]
)
os._exit(0)
