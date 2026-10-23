#!/usr/bin/env python3
"""Actualiza el Excel de ventas ahora mismo.

    vb ventas            <- lee tus columnas verdes, guarda en la base y reescribe
    vb ventas --abrir    <- y además lo abre

El servidor ya lo hace solo cada dos minutos (VENTAS_CADA_S). Esto es para
cuando lo quieres YA, o con el servidor apagado.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))


def main() -> int:
    ap = argparse.ArgumentParser(description="Actualiza el Excel de ventas")
    ap.add_argument("--abrir", action="store_true", help="abre el Excel al terminar")
    args = ap.parse_args()

    from app.adapters.excel.libro_ventas import LibroDeVentas
    from app.adapters.repositories.sqlite_store import SqliteDB
    from app.adapters.repositories.ventas import BaseDeVentas
    from app.infra.consola import preparar_salida
    from app.infra.settings import get_settings
    from app.workers.ventas import sincronizar

    preparar_salida()
    s = get_settings()
    base = BaseDeVentas(SqliteDB(s.sqlite_path))
    libro = LibroDeVentas(s.ventas_excel)
    informe = sincronizar(base, libro)

    print(f"\n  Excel de ventas: {libro.ruta}")
    print(f"  {informe.ventas} pedidos · {informe.clientas} clientas con compra")
    print(f"  {informe.anotaciones_guardadas} anotaciones tuyas guardadas en la base")
    print(f"  {'✔' if informe.escrito else '✘'} {informe.detalle}\n")
    if args.abrir and libro.ruta.is_file() and hasattr(os, "startfile"):
        os.startfile(libro.ruta)
    return 0 if informe.escrito else 1


if __name__ == "__main__":
    raise SystemExit(main())
