#!/usr/bin/env python3
"""Habla con el bot desde la terminal, como si fueras una clienta.

    vb hablar                 <- con el modelo de tu .env
    vb hablar --llm fake      <- sin Ollama, instantáneo

Es la forma más rápida de probar un cambio: escribes, y ves lo que le
llegaría por WhatsApp, con las imágenes marcadas y la traza de qué decidió el
sistema en cada tramo.

Sin red, sin WhatsApp y sin tocar tus pedidos de verdad: usa una base de datos
temporal que se borra al salir.
"""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))


def main() -> int:
    ap = argparse.ArgumentParser(description="Conversa con el bot")
    ap.add_argument("--llm", choices=("fake", "ollama"), default=None)
    ap.add_argument("--limpio", action="store_true", help="empieza sin memoria")
    args = ap.parse_args()

    tmp = Path(tempfile.mkdtemp()) / "conversar.db"
    os.environ.update(
        REPOSITORY_BACKEND="sqlite",
        CHANNEL_BACKEND="console",
        SQLITE_PATH=str(tmp),
        URL_PUBLICA="https://ejemplo.local",
    )
    if args.llm:
        os.environ["LLM_BACKEND"] = args.llm

    import logging

    from app.infra.consola import preparar_salida
    from app.infra.container import get_container

    logging.disable(logging.INFO)
    _C = preparar_salida()
    V, R, A, G, C, RST = (_C.ok, _C.error, _C.aviso, _C.tenue, _C.titulo, _C.fin)

    c = get_container()
    conv = "wa:573001112233"
    c.bot._mundo.asegurar_cliente(conv)

    print(f"\n{C}{'=' * 72}")
    print("  HABLA CON VENTABOT   ·   llm=" + c.settings.llm_backend)
    print(f"{'=' * 72}{RST}")
    print(f"{G}  Escribe como escribiría una clienta. Ctrl+C para salir.")
    print("  Prueba: «me pasas info», «quiero dos huellitas talla 8»,")
    print(f"          «¿y el segundo?», «ya pagué», «quiero ver ejemplos»{RST}\n")

    n = 0
    while True:
        try:
            texto = input(f"{C}👤 tú:{RST} ").strip()
        except (EOFError, KeyboardInterrupt):
            print(f"\n{G}  hasta luego 👋{RST}\n")
            return 0
        if not texto:
            continue
        n += 1
        turno = c.bot.ejecutar(conv, texto)

        print(f"{G}   · {turno.resumen()}{RST}")
        for linea in turno.respuesta.traza:
            print(f"{G}   · {linea}{RST}")

        for pieza in turno.respuesta.piezas:
            if pieza.imagen:
                print(f"{A}   🖼  [{pieza.imagen}]{RST}")
                continue
            print(f"\n{V}🤖 bot:{RST}")
            for linea in pieza.texto.splitlines():
                print(f"   {linea}")
        if turno.respuesta.escalar:
            print(f"{R}   ⚠ escalado: esta conversación necesita una persona{RST}")

        abiertos = turno.contexto.abiertos()
        if abiertos:
            for pr in abiertos:
                falta = ", ".join(pr.faltan) or "nada"
                print(
                    f"{G}   · proceso {pr.tipo.value}: {pr.datos} · falta: {falta}{RST}"
                )
        print()


if __name__ == "__main__":
    raise SystemExit(main())
