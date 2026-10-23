#!/usr/bin/env python3
"""¿De qué anuncios le están llegando clientas al bot? (16/10)

    python scripts/anuncios.py               # últimas 48 h
    python scripts/anuncios.py --horas 6     # las últimas 6 h
    python scripts/anuncios.py --dias 14     # las últimas dos semanas

En el servidor: `vb anuncios` (o `sudo docker compose exec -T ventabot python
scripts/anuncios.py`).

Por qué existe: del 13 al 16/10 la campaña «B · VentaBot 300» mandó a las
clientas al WhatsApp 317 (su conjunto se creó sin el número del bot) y nadie
lo vio en tres días: Meta Ads contaba «conversaciones iniciadas» y el bot no
recibía ninguna. La prueba de que un anuncio llega al bot es que su id aparezca
aquí. Después de lanzar o cambiar una campaña: a las 2-3 h, cada anuncio que
debe ir al bot tiene que estar en esta lista (ver docs/adr/0030).
"""

from __future__ import annotations

import argparse
import collections
import json
import sqlite3
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

from app.domain.numeros_propios import solo_respuesta_inmediata
from app.infra.settings import get_settings

COLOMBIA = timedelta(hours=-5)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--horas", type=float, default=None)
    ap.add_argument("--dias", type=float, default=None)
    args = ap.parse_args()
    horas = args.horas if args.horas is not None else (args.dias or 2) * 24
    desde = datetime.now(UTC) - timedelta(hours=horas)

    db = sqlite3.connect(f"file:{get_settings().sqlite_path}?mode=ro", uri=True)
    por_anuncio: dict[str, dict] = collections.defaultdict(
        lambda: {"clientas": set(), "primera": None, "ultima": None, "titulo": ""}
    )
    sin_anuncio = set()
    for conv, payload, creado in db.execute(
        "SELECT conversation_id, payload, created_at FROM messages "
        "WHERE direccion='IN' AND created_at >= ? ORDER BY id",
        (desde.isoformat(),),
    ):
        if solo_respuesta_inmediata(conv):
            continue
        ref = json.loads(payload or "{}").get("referral")
        if not ref:
            sin_anuncio.add(conv)
            continue
        a = por_anuncio[ref.get("source_id") or "¿sin id?"]
        a["clientas"].add(conv)
        a["titulo"] = (ref.get("headline") or ref.get("body") or "")[:40]
        cuando = datetime.fromisoformat(creado)
        cuando = cuando if cuando.tzinfo else cuando.replace(tzinfo=UTC)
        a["primera"] = a["primera"] or cuando
        a["ultima"] = cuando

    inicio = (desde + COLOMBIA).strftime("%d/%m %H:%M")
    print(f"Últimas {horas:g} h · desde {inicio} (hora Colombia)\n")
    if not por_anuncio:
        print("NINGUNA clienta llegó desde un anuncio en ese tiempo.")
        print("Si hay campañas al bot corriendo, revisa su número de WhatsApp")
        print("en el Administrador de anuncios (ADR 0030).")
    else:
        print("anuncio (source_id)    clientas  primera        última         título")
        for ad, a in sorted(por_anuncio.items(), key=lambda kv: -len(kv[1]["clientas"])):
            print(
                f"{ad:22} {len(a['clientas']):8}  "
                f"{(a['primera'] + COLOMBIA):%d/%m %H:%M}    "
                f"{(a['ultima'] + COLOMBIA):%d/%m %H:%M}    {a['titulo']}"
            )
    print(f"\nsin anuncio (escribieron directo o ya venían): {len(sin_anuncio)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
