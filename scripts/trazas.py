#!/usr/bin/env python3
"""¿Están las trazas encendidas y llegando? Con una prueba, no con una creencia.

    vb trazas

Manda UNA traza de mentira y dice si llegó. Es el equivalente de `vb token`
para la observabilidad: enterarse de que no se estaba grabando nada JUSTO
cuando hace falta mirar una conversación es la peor forma de descubrirlo.
"""

from __future__ import annotations

import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

from app.infra.consola import preparar_salida

# UTF-8 pase lo que pase: sin esto, redirigir la salida a un archivo (o
# leerla desde otro proceso) revienta en Windows al imprimir un ✔.
preparar_salida()


from app.infra.settings import get_settings
from app.infra.trazas import activar_desde_settings, anotar, traza

C, V, R, A, B, RST = (
    "\033[36m",
    "\033[32m",
    "\033[31m",
    "\033[33m",
    "\033[1m",
    "\033[0m",
)


@traza("prueba_de_trazas")
def _turno_de_mentira(mensaje: str) -> str:
    anotar(conversacion="wa:prueba", accion="SALUDAR", veredicto="EJECUTAR")
    return f"eco: {mensaje}"


def main() -> int:
    s = get_settings()
    print(f"\n{C}{'=' * 74}")
    print("  TRAZAS · LangSmith")
    print(f"{'=' * 74}{RST}\n")

    try:
        import langsmith

        print(f"  {V}✔{RST} librería langsmith {langsmith.__version__}")
    except ImportError:
        print(f"  {R}✘{RST} falta la librería:  pip install langsmith\n")
        return 1

    if not s.langsmith_tracing:
        print(f"  {A}○{RST} LANGSMITH_TRACING está en false: no se graba nada.")
        print(f"      {A}→{RST} pon LANGSMITH_TRACING=true en tu .env\n")
        return 1
    if not s.langsmith_api_key:
        print(f"  {R}✘{RST} falta LANGSMITH_API_KEY.")
        print(f"      {A}→{RST} sácala en https://smith.langchain.com (Settings)")
        print(f"      {A}→{RST} o, con un LangSmith propio, la que hayas puesto\n")
        return 1

    destino = s.langsmith_endpoint or "https://api.smith.langchain.com (la nube)"
    print(f"  {V}✔{RST} proyecto: {s.langsmith_project}")
    print(f"  {V}✔{RST} destino:  {destino}")

    activar_desde_settings(s)
    print(f"\n{B}Mandando una traza de prueba…{RST}")
    try:
        _turno_de_mentira("hola")
        from langsmith import Client

        Client().flush()
    except Exception as exc:
        print(f"  {R}✘{RST} no se pudo mandar: {exc}\n")
        print("  Si usas un LangSmith propio, comprueba que está levantado")
        print("  y que LANGSMITH_ENDPOINT apunta a su dirección.\n")
        return 1

    print(f"  {V}✔{RST} enviada.\n")
    print(f"  Ábrela en el proyecto {B}{s.langsmith_project}{RST}: tiene que")
    print("  aparecer una llamada «prueba_de_trazas». Si no está, el problema")
    print("  es la clave o el destino, no el código.\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
