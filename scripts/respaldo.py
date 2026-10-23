#!/usr/bin/env python3
"""Respalda la base de datos y el Excel de ventas. Sin servicios, sin cuentas.

    vb respaldo              <- copia la base y el Excel a Documents\\Respaldos
    vb respaldo --listar     <- qué copias hay y cuánto pesan

POR QUÉ ASÍ
===========
La base `data/ventabot.db` tiene TODOS los pedidos y las clientas: si se pierde,
se perdió el negocio. Hasta hoy la copia se hacía a mano, que es como decir que
no se hacía.

Esto copia en caliente y sin corromper nada: SQLite tiene `VACUUM INTO`, que
escribe una copia consistente aunque el bot esté atendiendo en ese momento
(copiar el archivo a pelo mientras se escribe sí lo puede partir).

Se guardan las últimas COPIAS copias y se borran las viejas, para que la carpeta
no crezca sin control. Todo local: no sube nada a ningún lado. Si algún día se
quiere copia fuera del equipo, el plan (`docs/MANUAL-VIVO.md`) dice
cómo, y se apunta a esta misma carpeta.
"""

from __future__ import annotations

import argparse
import os
import shutil
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

#: La hora con la que se nombran las copias: la de Camilo, no UTC.
COLOMBIA = timezone(timedelta(hours=-5), "America/Bogota")

#: Cuántas copias se conservan de cada cosa.
COPIAS = 14


def carpeta_de_respaldos() -> Path:
    """En el portátil, Documentos; en el servidor, el volumen (`RESPALDOS_DIR`)."""
    propia = os.environ.get("RESPALDOS_DIR", "").strip()
    if propia:
        return Path(propia)
    return Path.home() / "Documents" / "Respaldos" / "VentaBot" / "automatico"


def _peso(ruta: Path) -> str:
    mb = ruta.stat().st_size / 1_000_000
    return f"{mb:.1f} MB" if mb >= 1 else f"{ruta.stat().st_size / 1000:.0f} KB"


def copiar_base(origen: Path, destino: Path) -> Path | None:
    """Copia consistente aunque el bot esté escribiendo (VACUUM INTO)."""
    if not origen.exists():
        return None
    salida = destino / f"ventabot-{datetime.now(COLOMBIA):%Y%m%d-%H%M}.db"
    with sqlite3.connect(f"file:{origen}?mode=ro", uri=True) as cx:
        cx.execute("VACUUM INTO ?", (str(salida),))
    return salida


def copiar_excel(origen: Path, destino: Path) -> Path | None:
    if not origen.exists():
        return None
    salida = destino / f"Ventas-{datetime.now(COLOMBIA):%Y%m%d-%H%M}.xlsx"
    shutil.copy2(origen, salida)
    return salida


def limpiar_viejas(destino: Path, patron: str, cuantas: int = COPIAS) -> int:
    copias = sorted(destino.glob(patron), reverse=True)
    for vieja in copias[cuantas:]:
        vieja.unlink()
    return max(0, len(copias) - cuantas)


def main() -> int:
    ap = argparse.ArgumentParser(description="Respalda la base y el Excel")
    ap.add_argument("--listar", action="store_true", help="solo mostrar qué hay")
    args = ap.parse_args()

    from app.infra.consola import preparar_salida
    from app.infra.settings import get_settings

    preparar_salida()
    s = get_settings()
    destino = carpeta_de_respaldos()
    destino.mkdir(parents=True, exist_ok=True)

    if args.listar:
        copias = sorted(destino.iterdir(), reverse=True)
        if not copias:
            print("No hay copias todavía. Corre  vb respaldo")
            return 0
        print(f"{len(copias)} copia(s) en {destino}\n")
        for copia in copias[:20]:
            print(f"  {copia.name:<34} {_peso(copia)}")
        return 0

    base = copiar_base(Path(s.sqlite_path), destino)
    excel = copiar_excel(Path(s.ventas_excel), destino)
    borradas = limpiar_viejas(destino, "ventabot-*.db") + limpiar_viejas(
        destino, "Ventas-*.xlsx"
    )

    print(f"Respaldo en {destino}")
    print(f"  base   {base.name if base else 'no había base todavía'}")
    print(f"  excel  {excel.name if excel else 'no había Excel todavía'}")
    if borradas:
        print(
            f"  se borraron {borradas} copia(s) vieja(s); se guardan las {COPIAS} últimas"
        )
    if base is None:
        print("\n⚠️  No se encontró la base: ¿es la primera vez que corres el bot?")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
