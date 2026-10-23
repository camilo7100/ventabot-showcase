"""El catálogo que la clienta ve en el perfil de WhatsApp (03/10).

Meta lo arma desde Commerce Manager leyendo una lista de productos en CSV. Esa
lista sale de `data/catalogo.csv`, el mismo de donde el bot saca los precios:
si el catálogo de WhatsApp tuviera su propia copia, a la primera subida de
precio la clienta vería $200.000 en el catálogo y el bot le cobraría otra
cosa. Commerce Manager la vuelve a leer sola cada día.

`imagen_url` del catálogo puede ser una dirección completa o el nombre de una
imagen de `data/imagenes` (`anillos_inspirado_en_tu_mascota`), que se sirve en `/media/`.
"""

from __future__ import annotations

import csv
import io

from app.domain.models import InboundMessage, Product

#: Las columnas que pide Meta para un catálogo de productos.
COLUMNAS = (
    "id",
    "title",
    "description",
    "availability",
    "condition",
    "price",
    "link",
    "image_link",
    "brand",
)
MARCA = "Luna Joyas"
#: Cómo empieza el texto cuando escribe desde un producto (lo lee la asesora).
NOTA_DE_LA_VITRINA = "[Escribe desde la vitrina de WhatsApp, mirando: "
SITIO = "https://lunajoyas.example/"


def titulo(p: Product) -> str:
    """«Anillo de 2 huellitas»: el nombre interno («x2») no es para la clienta."""
    if p.categoria == "anillos" and p.huellitas:
        n = p.huellitas
        return f"Anillo de {n} huellita{'s' if n > 1 else ''}"
    return p.nombre


def imagen(p: Product, publico: str) -> str:
    nombre = (p.imagen_url or "").strip()
    if not nombre or nombre.startswith(("http://", "https://")):
        return nombre
    return f"{publico.rstrip('/')}/media/{nombre}"


def catalogo_csv(productos: list[Product], publico: str) -> str:
    """El CSV para Commerce Manager. Sin foto no hay producto: Meta lo rechaza."""
    salida = io.StringIO()
    w = csv.writer(salida, lineterminator="\n")
    w.writerow(COLUMNAS)
    for p in productos:
        foto = imagen(p, publico)
        if not foto:
            continue
        w.writerow(
            (
                p.sku,
                titulo(p),
                p.descripcion,
                "in stock",
                "new",
                f"{p.precio_cop} COP",
                SITIO,
                foto,
                MARCA,
            )
        )
    return salida.getvalue()


def producto_que_mira(m: InboundMessage) -> str | None:
    """El SKU del producto del catálogo desde el que escribe, si escribe desde uno.

    Meta lo manda en `context.referred_product` cuando la clienta toca «Enviar
    mensaje» en un producto del catálogo del perfil.
    """
    ref = (m.raw.get("context") or {}).get("referred_product") or {}
    return ref.get("product_retailer_id") or None


def con_el_producto(m: InboundMessage, productos: list[Product]) -> InboundMessage:
    """Le antepone al texto qué producto del catálogo estaba mirando.

    Sin esto, «¿cuánto se demora?» escrito desde la cadena le llega al bot
    como una pregunta suelta, y el bot no habla de la cadena si ella no la
    nombra (R2p). Lía también lo ve así en Chatwoot.
    """
    sku = producto_que_mira(m)
    if not sku:
        return m
    p = next((p for p in productos if p.sku == sku), None)
    nota = f"{NOTA_DE_LA_VITRINA}{titulo(p) if p else sku}]"
    texto = f"{nota}\n{m.text}" if m.text else nota
    return m.model_copy(update={"text": texto})
