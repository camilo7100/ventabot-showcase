#!/usr/bin/env python3
"""Abre el centro de mando en el navegador, con el token ya puesto.

    python scripts/ver_todo.py          <- en este PC
    python scripts/ver_todo.py --enlace <- solo escribe el enlace, para el celular

El token vive en el `.env` y se pega aqui en el momento. Nunca se escribe en
un archivo que alguien pueda abrir por encima del hombro: `--enlace` lo
imprime porque es justo lo que hace falta para pasarlo al telefono, y ahi
Camilo decide.
"""

from __future__ import annotations

import sys
import webbrowser
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

from app.infra.settings import get_settings

LOCAL = "http://127.0.0.1:8000"


def main() -> int:
    s = get_settings()
    if not s.panel_token:
        print()
        print("  El panel esta apagado: no hay PANEL_TOKEN en el .env.")
        print("  Enciendelo con:  vb panel")
        print()
        return 1

    camino = f"/panel/todo?token={s.panel_token}"
    if "--enlace" in sys.argv:
        publico = (s.url_publica_override or s.public_url or "").rstrip("/")
        print()
        print("  Para el celular (guardalo en la pantalla de inicio):")
        print()
        print(f"    {publico or LOCAL}{camino}")
        print()
        print("  Ese enlace lleva la llave del panel: no lo publiques.")
        print()
        return 0

    webbrowser.open(f"{LOCAL}{camino}")
    print()
    print("  Centro de mando abierto en el navegador.")
    print("  Para el celular:   VER-TODO.cmd --enlace")
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
