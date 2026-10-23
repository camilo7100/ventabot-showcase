"""Cómo está decidiendo el bot: capas, escaladas, historial, errores, latencia y costo.

    vb metricas               <- todo lo registrado
    vb metricas --horas 24    <- solo las últimas 24 horas
    vb metricas --ultimas 20  <- además, las últimas 20 decisiones una por una

Lee la tabla `decisiones` de la base de datos local. No hay textos de clientas
ni teléfonos: cada fila dice qué capa respondió, por qué, con qué contexto, si
buscó en el historial y cuánto costó.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))


def main() -> int:
    ap = argparse.ArgumentParser(description="Métricas del routing de VentaBot")
    ap.add_argument("--horas", type=float, default=None, help="solo las últimas N horas")
    ap.add_argument(
        "--ultimas", type=int, default=0, help="muestra las N últimas decisiones"
    )
    args = ap.parse_args()

    from app.adapters.repositories.sqlite_store import SqliteDB, SqliteDecisiones
    from app.infra.consola import preparar_salida
    from app.infra.settings import get_settings

    c = preparar_salida()
    s = get_settings()
    db = SqliteDB(s.sqlite_path)
    registro = SqliteDecisiones(db)
    desde = (
        (datetime.now(UTC) - timedelta(hours=args.horas)).isoformat(timespec="seconds")
        if args.horas
        else None
    )
    m = registro.metricas(desde)

    print(f"\n{c.titulo}{'=' * 64}")
    print(f"  MÉTRICAS DE DECISIÓN · {s.sqlite_path.name}")
    print(f"{'=' * 64}{c.fin}")
    if not m.get("turnos"):
        print("  Todavía no hay decisiones registradas. Habla con el bot y vuelve.\n")
        return 0

    filas = [
        ("Turnos", m["turnos"]),
        ("Resueltos sin IA", f"{m['sin_ia_pct']} %"),
        ("Modelo básico", f"{m['basico_pct']} %"),
        ("Modelo potente", f"{m['potente_pct']} %"),
        ("Escaladas al potente", m["escaladas"]),
        ("Consultas históricas", m["consultas_historicas"]),
        ("Pasados a una persona", m["a_una_persona"]),
        ("Acciones corregidas por Python", m["acciones_corregidas"]),
        ("Errores", m["errores"]),
        ("Latencia p50 / p95", f"{m['latencia_p50_ms']} ms / {m['latencia_p95_ms']} ms"),
        ("Costo total", f"USD {m['costo_total_usd']}"),
        ("Costo por turno", f"USD {m['costo_por_turno_usd']}"),
    ]
    for nombre, valor in filas:
        print(f"  {nombre:<32} {valor}")

    if args.ultimas:
        print(f"\n{c.titulo}  Últimas {args.ultimas} decisiones{c.fin}")
        for fila in db.consultar(
            "SELECT payload FROM decisiones ORDER BY id DESC LIMIT ?", (args.ultimas,)
        )[::-1]:
            d = json.loads(fila["payload"])
            print(
                f"  {d['ts'][11:19]} {d['routing_layer']:<7} {d['action']:<26} "
                f"{d['context_source']:<16} conf={d['confidence']:<5} "
                f"{'ESCALÓ:' + d['escalation_reason'] if d['escalated'] else ''} "
                f"{'HIST' if d['historical_lookup'] else ''} "
                f"{d['latency_ms']}ms ${d['cost_usd']}"
            )
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
