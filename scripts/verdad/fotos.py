"""Las fotos que manda la clienta en la prueba de verdad (04/10).

Los comprobantes se DIBUJAN aquí (texto sobre fondo blanco, como un pantallazo
de Nequi o Bancolombia): nada de datos de nadie. La foto de la regla es la del
catálogo (`anillo_ejemplo_3`: un anillo sobre una regla). Todo en memoria.
"""

from __future__ import annotations

import io
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]


def _pantallazo(renglones: list[tuple[str, int]], formato: str = "JPEG") -> bytes:
    from PIL import Image, ImageDraw, ImageFont

    imagen = Image.new("RGB", (720, 1280), "white")
    lapiz = ImageDraw.Draw(imagen)
    y = 80
    for texto, tamano in renglones:
        try:
            fuente = ImageFont.truetype("DejaVuSans.ttf", tamano)
        except OSError:
            fuente = ImageFont.load_default()
        lapiz.text((60, y), texto, fill="black", font=fuente)
        y += int(tamano * 1.9)
    salida = io.BytesIO()
    imagen.save(salida, formato)
    return salida.getvalue()


def comprobante(valor: str, para: str, banco: str = "Nequi", formato="JPEG") -> bytes:
    return _pantallazo(
        [
            (banco, 44),
            ("¡Envío exitoso!", 40),
            ("Para", 26),
            (para, 32),
            ("¿Cuánto?", 26),
            (f"$ {valor}", 54),
            ("Fecha", 26),
            ("4 de octubre de 2026, 1:20 p. m.", 28),
            ("Referencia", 26),
            ("M8812345", 28),
            ("Número del destino", 26),
            ("300 111 0003", 28),
        ],
        formato,
    )


def regla() -> bytes:
    return (RAIZ / "data" / "imagenes" / "anillo_ejemplo_3.jpg").read_bytes()


def foto_de_un_anillo() -> bytes:
    """Una foto que NO es comprobante ni regla: «mira, quiero uno así»."""
    return (RAIZ / "data" / "imagenes" / "anillo_ejemplo_1.jpg").read_bytes()


#: nombre → (tipo de adjunto, cómo se hace). Se generan una vez por corrida.
FOTOS = {
    "comprobante_60000": ("image", lambda: comprobante("60.000", "LÍA GÓMEZ")),
    # El caso del 04/10: el valor con el costo del envío y el nombre tapado.
    "comprobante_59700": ("image", lambda: comprobante("59.700", "PAU*** MAN***")),
    "comprobante_65000": ("image", lambda: comprobante("65.000", "LÍA GÓMEZ")),
    "comprobante_120000": (
        "image",
        lambda: comprobante("120.000", "LÍA GÓMEZ", "Bancolombia"),
    ),
    "comprobante_saldo_140000": (
        "image",
        lambda: comprobante("140.000", "LÍA GÓMEZ", "Daviplata"),
    ),
    "comprobante_pdf_60000": (
        "document",
        lambda: comprobante("60.000", "LÍA GÓMEZ", "Bancolombia", "PDF"),
    ),
    "regla": ("image", regla),
    "anillo_que_vi": ("image", foto_de_un_anillo),
}


def bytes_de(nombre: str) -> bytes:
    return FOTOS[nombre][1]()


def tipo_de(nombre: str) -> str:
    return FOTOS[nombre][0]
