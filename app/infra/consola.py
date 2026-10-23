"""Salida por terminal que no se rompe en Windows ni al redirigir a un archivo.

DOS PROBLEMAS REALES QUE RESUELVE
=================================

1. UnicodeEncodeError al redirigir en Windows.
   La consola de Windows usa cp1252 cuando la salida va a una tubería o a un
   archivo. Un simple `print("✔")` levanta:

       UnicodeEncodeError: 'charmap' codec can't encode character '\\u2714'

   El script MUERE, aunque su trabajo ya estuviera hecho. Fue exactamente lo
   que hizo fallar a `test_crea_el_env_desde_el_ejemplo`: el `.env` se creaba
   bien y el proceso terminaba con código 1.

2. Códigos de color en los archivos.
   Al hacer `python script.py > salida.txt`, los códigos ANSI se guardan como
   basura (`ESC[92m`) y el archivo queda ilegible. Justo cuando más falta hace
   leerlo, porque uno redirige a un archivo para pedir ayuda con un error.

Uso:

    from app.infra.consola import preparar_salida
    C = preparar_salida()
    print(f"{C.ok}✔ listo{C.fin}")

Con terminal: sale en color. Redirigido a archivo: sale en texto limpio y en
UTF-8. En los dos casos, no revienta.
"""

from __future__ import annotations

import contextlib
import os
import sys
from dataclasses import dataclass


@dataclass(frozen=True)
class Colores:
    ok: str = ""
    error: str = ""
    aviso: str = ""
    tenue: str = ""
    titulo: str = ""
    fuerte: str = ""
    fin: str = ""

    @property
    def hay_color(self) -> bool:
        return bool(self.fin)


CON_COLOR = Colores(
    ok="\033[92m",
    error="\033[91m",
    aviso="\033[93m",
    tenue="\033[90m",
    titulo="\033[96m",
    fuerte="\033[1m",
    fin="\033[0m",
)
SIN_COLOR = Colores()


def soporta_color(stream=None) -> bool:
    """Color solo si hay una terminal de verdad al otro lado.

    Respeta las convenciones habituales: NO_COLOR desactiva, FORCE_COLOR fuerza.
    """
    if os.environ.get("NO_COLOR"):
        return False
    if os.environ.get("FORCE_COLOR"):
        return True
    s = stream or sys.stdout
    try:
        return bool(s.isatty())
    except Exception:
        return False


def preparar_salida(stream=None) -> Colores:
    """Deja stdout y stderr en UTF-8 y devuelve la paleta que toque.

    `errors="replace"` es deliberado: si algún carácter no se puede
    representar, se sustituye por «?» y el programa SIGUE. Un script de
    diagnóstico que muere por un adorno tipográfico es peor que uno feo.
    """
    for s in (sys.stdout, sys.stderr):
        reconfigurar = getattr(s, "reconfigure", None)
        if reconfigurar is not None:
            # Un stream ya cerrado o simulado no debe tumbar el script.
            with contextlib.suppress(Exception):
                reconfigurar(encoding="utf-8", errors="replace")
    return CON_COLOR if soporta_color(stream) else SIN_COLOR
