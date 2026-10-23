#!/usr/bin/env python3
"""Mira lo que ve el lector de imágenes. Con la foto delante, no de fe.

    vb ojos                        <- las fotos de ejemplo del proyecto
    vb ojos C:\\ruta\\a\\una\\foto.jpg  <- una foto tuya
    vb ojos C:\\ruta\\a\\una\\carpeta   <- todas las de una carpeta

════════════════════════════════════════════════════════════════════════════
PARA QUÉ SIRVE ESTO
════════════════════════════════════════════════════════════════════════════
El lector de imágenes decide cosas caras: una talla mal leída es un anillo
que no entra, y un comprobante mal leído es una conversación de cobro que
empieza torcida. Antes de fiarse hay que ver qué contesta con FOTOS REALES,
que es distinto de que pasen los tests — los tests prueban la política, no la
puntería del modelo.

Lo que sale por pantalla es exactamente lo que vería el sistema: la lectura
en crudo del modelo y, debajo, lo que el dominio hace con ella (`entender`).
Si la lectura es buena y la decisión es mala, el fallo es nuestro y se
arregla en `app/domain/vision.py`. Si la lectura es mala, el fallo es del
modelo y se arregla cambiando OLLAMA_VISION_MODEL.

Esa distinción es toda la razón de que la lectura y la decisión estén
separadas, y este comando es donde se ve.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

from app.infra.consola import preparar_salida

# UTF-8 pase lo que pase: sin esto, redirigir la salida a un archivo (o
# leerla desde otro proceso) revienta en Windows al imprimir un ✔.
preparar_salida()


from app.domain.vision import entender
from app.infra.settings import get_settings

C, V, R, A, B, RST = (
    "\033[36m",
    "\033[32m",
    "\033[31m",
    "\033[33m",
    "\033[1m",
    "\033[0m",
)

FOTOS = (".jpg", ".jpeg", ".png", ".webp")


def _que_mirar(destino: str | None) -> list[Path]:
    if not destino:
        carpeta = RAIZ / "data" / "imagenes"
        return sorted(p for p in carpeta.iterdir() if p.suffix.lower() in FOTOS)
    ruta = Path(destino).expanduser()
    if ruta.is_dir():
        return sorted(p for p in ruta.iterdir() if p.suffix.lower() in FOTOS)
    return [ruta] if ruta.is_file() else []


def _ojos():
    s = get_settings()
    if not s.ollama_vision_model:
        print(
            f"\n  {R}No hay lector de imágenes configurado.{RST}\n"
            f"  Pon OLLAMA_VISION_MODEL en tu .env (por ejemplo qwen3-vl:8b)\n"
            f"  y bájalo con:  ollama pull qwen3-vl:8b\n"
        )
        return None

    from app.adapters.llm.ojos_ollama import OjosDeOllama
    from app.adapters.llm.ollama_client import OllamaLLM

    prompt = (RAIZ / "app" / "prompts" / "vision_v1.txt").read_text(encoding="utf-8")
    return OjosDeOllama(
        OllamaLLM(
            model=s.ollama_model,
            host=s.ollama_host,
            vision_model=s.ollama_vision_model,
        ),
        prompt=prompt,
    )


def main() -> int:
    ap = argparse.ArgumentParser(description="Prueba el lector de imágenes")
    ap.add_argument("ruta", nargs="?", help="una foto o una carpeta")
    ap.add_argument(
        "--pista",
        default="",
        choices=["", "talla", "colores", "comprobante"],
        help="qué le decimos al lector que estamos esperando",
    )
    args = ap.parse_args()

    fotos = _que_mirar(args.ruta)
    if not fotos:
        print(f"\n  {R}No encontré ninguna foto ahí.{RST}\n")
        return 1

    ojos = _ojos()
    if ojos is None:
        return 1

    s = get_settings()
    print(f"\n{C}{'=' * 74}")
    print(f"  LECTOR DE IMÁGENES · {s.ollama_vision_model}")
    print(f"{'=' * 74}{RST}")
    print(f"  {len(fotos)} foto(s)" + (f" · pista: {args.pista}" if args.pista else ""))

    tiempos = []
    for foto in fotos:
        arranque = time.perf_counter()
        lectura = ojos.leer(foto.read_bytes(), pista=args.pista)
        ms = int((time.perf_counter() - arranque) * 1000)
        tiempos.append(ms)
        hallazgo = entender(lectura)

        seguro = f"{V}seguro{RST}" if lectura.seguro else f"{A}con dudas{RST}"
        print(f"\n{B}{foto.name}{RST}  ({ms} ms)")
        print(f"  ve: {B}{lectura.tipo.value}{RST} · {seguro}")
        if lectura.descripcion:
            print(f"      «{lectura.descripcion}»")

        detalles = {
            "monto": lectura.monto_cop,
            "banco": lectura.banco,
            "referencia": lectura.referencia,
            "diámetro mm": lectura.diametro_mm,
            "foto clara": lectura.foto_clara,
            "corazón": lectura.color_corazon and lectura.color_corazon.value,
            "dedos": lectura.color_dedos and lectura.color_dedos.value,
        }
        for nombre, valor in detalles.items():
            if valor is not None:
                print(f"      {nombre}: {valor}")

        if hallazgo.datos:
            print(f"  {V}guarda:{RST} {hallazgo.datos}")
        else:
            print(f"  {A}no guarda nada{RST}")
        for nota in hallazgo.revisar:
            print(f"  {A}para Lía:{RST} {nota}")

    if tiempos:
        tiempos.sort()
        print(f"\n{C}{'=' * 74}{RST}")
        print(f"  mediana {tiempos[len(tiempos) // 2]} ms · peor {tiempos[-1]} ms")
        print(
            f"\n  {B}Cómo leer esto:{RST} si la lectura es buena y la decisión es\n"
            f"  mala, el fallo es nuestro (app/domain/vision.py). Si la lectura\n"
            f"  es mala, cambia OLLAMA_VISION_MODEL por uno más grande.\n"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
