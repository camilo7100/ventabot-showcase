#!/usr/bin/env python3
"""Mide el color de cada circón en la foto del muestrario (30/09/2026).

    python -m scripts.medir_muestrario              <- imprime los 14 colores
    python -m scripts.medir_muestrario --hoja X.png <- y una hoja para mirarla

De aquí salen los números de `HEX_COLOR` (app/domain/personalizacion.py), que
tiñen la previsualización «así se te va a ver». Antes estaban puestos a ojo; si
Lía compra un color nuevo, se agrega su caja abajo y se mide igual.

CÓMO MIDE (y por qué así)
=========================
1. **Balance de blancos con la cartulina**: la foto sale cálida (la cartulina
   blanca mide 223/219/206). Se corrige cada canal para que la cartulina quede
   neutra, y así no se corren todos los tonos hacia el naranja.
2. En el recorte de cada bolsita se quedan los píxeles de PIEDRA: ni el
   plástico ni la cartulina (saturación > 0,15) y del **tono dominante** (así se
   va la línea roja del cierre o una piedra de la bolsa vecina).
3. El color sale de tres medidas distintas, porque cada una sola falla:
   - tono: la mediana (el tono se mide bien en la foto);
   - saturación: el percentil 90 (el reflejo del plástico la baja);
   - brillo: el percentil 80 (la piedra iluminada, no la sombra de la faceta).
   El previsualizador usa solo tono y saturación: el brillo lo pone la foto.
4. Negro y blanco no tienen tono: el negro es la mediana de lo oscuro y el
   blanco (transparente) no se tiñe en el previsualizador.
"""

from __future__ import annotations

import argparse
import colorsys
import statistics
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

from app.domain.personalizacion import ColorCircon

#: La foto SIN nombres encima (la que se le manda a la clienta los lleva, 30/09):
#: las letras de encima ensuciarían la medida.
FOTO = RAIZ / "data" / "imagenes" / "fuentes" / "muestrario_circones_original.jpg"

#: Zonas de cartulina limpia (sin bolsas) para el balance de blancos.
CARTULINA = ((700, 250, 900, 380), (80, 1120, 300, 1220))

#: (color, caja x0, y0, x1, y1) dentro de las piedras de cada bolsita, sobre la
#: foto de 960x1280. Columnas de la foto: izquierda lila → negro; centro blanco
#: → naranja; derecha amarillo → verde esmeralda.
CAJAS: tuple[tuple[ColorCircon, int, int, int, int], ...] = (
    (ColorCircon.LILA, 60, 640, 230, 665),
    (ColorCircon.MORADO, 120, 700, 260, 745),
    (ColorCircon.CELESTE, 110, 800, 190, 870),
    (ColorCircon.AZUL_REY, 150, 900, 320, 945),
    (ColorCircon.NEGRO, 180, 975, 390, 1060),
    (ColorCircon.BLANCO, 350, 640, 530, 690),
    (ColorCircon.ROSADO, 380, 715, 560, 760),
    (ColorCircon.FUCSIA, 410, 790, 590, 845),
    (ColorCircon.ROJO, 470, 860, 580, 882),
    (ColorCircon.NARANJA, 440, 905, 620, 960),
    (ColorCircon.AMARILLO, 620, 630, 800, 660),
    (ColorCircon.DURAZNO, 640, 680, 810, 710),
    (ColorCircon.VERDE_OLIVA, 660, 725, 830, 790),
    (ColorCircon.VERDE_ESMERALDA, 690, 800, 870, 870),
)


def _hsv(p) -> tuple[float, float, float]:
    return colorsys.rgb_to_hsv(*(c / 255 for c in p))


def foto_balanceada():
    """La foto del muestrario con la cartulina llevada a gris neutro."""
    from PIL import Image

    foto = Image.open(FOTO).convert("RGB")
    carton = [p for caja in CARTULINA for p in foto.crop(caja).get_flattened_data()]
    ref = [statistics.median(p[i] for p in carton) for i in range(3)]
    gris = sum(ref) / 3
    canales = [
        c.point(lambda v, g=gris / r: min(255, round(v * g)))
        for c, r in zip(foto.split(), ref, strict=True)
    ]
    return Image.merge("RGB", canales)


def medir(foto, color: ColorCircon, caja: tuple[int, int, int, int]) -> str | None:
    """El color de una bolsita, en hexadecimal, o None si no hay piedra."""
    pix = list(foto.crop(caja).get_flattened_data())
    if color is ColorCircon.NEGRO:
        sel = sorted((p for p in pix if _hsv(p)[2] < 0.3), key=lambda p: _hsv(p)[2])
        banda = sel[len(sel) // 4 : len(sel) * 3 // 4]
        if not banda:
            return None
        med = [int(statistics.median(p[i] for p in banda)) for i in range(3)]
        return "#{:02X}{:02X}{:02X}".format(*med)
    if color is ColorCircon.BLANCO:
        return None  # transparente: no se tiñe (ver `huellita.SIN_TENIR`)
    sel = [p for p in pix if _hsv(p)[1] > 0.15 and _hsv(p)[2] > 0.2]
    cubetas = [0] * 36
    for p in sel:
        cubetas[int(_hsv(p)[0] * 36) % 36] += 1
    top = max(
        range(36), key=lambda i: cubetas[i - 1] + cubetas[i] + cubetas[(i + 1) % 36]
    )

    def del_tono(p) -> bool:
        d = abs(_hsv(p)[0] * 36 - (top + 0.5))
        return min(d, 36 - d) <= 2.5

    sel = [p for p in sel if del_tono(p)]
    if not sel:
        return None
    tonos = sorted(_hsv(p)[0] for p in sel)
    saturaciones = sorted(_hsv(p)[1] for p in sel)
    brillos = sorted(_hsv(p)[2] for p in sel)
    r, g, b = colorsys.hsv_to_rgb(
        tonos[len(tonos) // 2],
        saturaciones[len(saturaciones) * 9 // 10],
        brillos[len(brillos) * 8 // 10],
    )
    return f"#{int(r * 255):02X}{int(g * 255):02X}{int(b * 255):02X}"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--hoja", default="", help="guardar una hoja de control (PNG)")
    args = ap.parse_args()

    from app.domain.personalizacion import HEX_COLOR

    foto = foto_balanceada()
    medidos = {}
    for color, *caja in CAJAS:
        medidos[color] = medir(foto, color, tuple(caja))  # type: ignore[arg-type]
        print(f"{color.value:16} medido {medidos[color]}  ·  hoy {HEX_COLOR[color]}")

    if args.hoja:
        from PIL import Image, ImageDraw, ImageFont

        fuente = ImageFont.load_default(size=18)
        hoja = Image.new("RGB", (900, 70 * len(CAJAS)), "white")
        d = ImageDraw.Draw(hoja)
        for i, (color, *caja) in enumerate(CAJAS):
            y = i * 70
            hoja.paste(foto.crop(tuple(caja)).resize((300, 60)), (5, y + 5))
            d.rectangle((320, y + 5, 420, y + 65), fill=medidos[color] or "white")
            d.rectangle((430, y + 5, 530, y + 65), fill=HEX_COLOR[color])
            d.text((545, y + 20), color.value, fill="black", font=fuente)
        hoja.save(args.hoja)
        print(f"hoja: {args.hoja}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
