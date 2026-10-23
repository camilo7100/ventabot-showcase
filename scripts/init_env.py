#!/usr/bin/env python3
"""Crea el archivo `.env` a partir de `.env.example`.

    vb init-env          (Windows)
    make init-env        (Mac / Linux)

Por qué hace falta un script para copiar un archivo:

  · En Windows, el Explorador no deja crear fácilmente archivos que empiezan
    por punto, y `copy .env.example .env` es fácil de escribir mal.
  · `META_VERIFY_TOKEN` es un valor que inventas TÚ, no te lo da Meta. Mejor
    generarlo con un generador criptográfico que teclear "12345".
  · Nunca sobrescribe un `.env` que ya existe: ahí viven tus credenciales.
"""

from __future__ import annotations

import secrets
import shutil
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

from app.infra.consola import preparar_salida

EJEMPLO = RAIZ / ".env.example"
DESTINO = RAIZ / ".env"

# UTF-8 y color solo si hay terminal. Sin esto, `python init_env.py > log.txt`
# revienta en Windows al imprimir el ✔.
_C = preparar_salida()
V, R, A, G, RST = _C.ok, _C.error, _C.aviso, _C.tenue, _C.fin


def main() -> int:
    forzar = "--force" in sys.argv

    if not EJEMPLO.exists():
        print(f"{R}✘ No encuentro {EJEMPLO.name}. ¿Estás en la carpeta?{RST}")
        return 1

    if DESTINO.exists() and not forzar:
        print(f"\n{A}El .env ya existe. No lo toco: ahí van tus credenciales.{RST}")
        print(f"{G}   Empezar de cero: python scripts/init_env.py --force{RST}")
        print(f"{G}   (antes haz una copia, se pierde todo lo que hayas puesto){RST}\n")
        return 0

    if DESTINO.exists():
        respaldo = RAIZ / ".env.anterior"
        shutil.copy2(DESTINO, respaldo)
        print(f"{A}   Copia de seguridad en {respaldo.name}{RST}")

    contenido = EJEMPLO.read_text(encoding="utf-8")

    # META_VERIFY_TOKEN lo inventas tú: es la contraseña con la que Meta te
    # demuestra que es él quien llama a tu webhook. Se genera con `secrets`,
    # que usa el generador criptográfico del sistema operativo.
    token = secrets.token_urlsafe(24)
    contenido = contenido.replace("META_VERIFY_TOKEN=", f"META_VERIFY_TOKEN={token}", 1)

    DESTINO.write_text(contenido, encoding="utf-8")

    vacias = [
        ln.split("=")[0]
        for ln in contenido.splitlines()
        if "=" in ln and not ln.strip().startswith("#") and ln.split("=", 1)[1] == ""
    ]

    print(f"\n{V}✔ Creado el archivo .env{RST}")
    print(f"{G}   ubicación: {DESTINO}{RST}")
    print(f"{V}✔ META_VERIFY_TOKEN generado{RST}  {G}({token[:10]}…){RST}")
    print(f"\n   Quedan {len(vacias)} valores vacíos. NO los necesitas todavía:")
    print(f"{G}   · los de Meta      -> Fase 1, parte B{RST}")
    print(f"{G}   · los de Bold      -> Fase 3{RST}")
    print(f"{G}   · los de Sheets    -> Fase 2{RST}")
    print(f"\n{A}   Al llenarlos: NUNCA pongas un comentario en la misma línea.{RST}")
    print(f"{A}   WA_ACCESS_TOKEN=EAAxx  # mi token  <- el valor sería eso.{RST}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
