"""La base de ventas: una fila por pedido, con dueño por columna (ADR 0015).

════════════════════════════════════════════════════════════════════════════
LAS REGLAS DE GOBIERNO, EN CUATRO LÍNEAS
════════════════════════════════════════════════════════════════════════════
  1. La VERDAD es la base de datos (SQLite). El Excel es una vista que se
     reescribe entera en cada sincronización.
  2. Cada columna tiene DUEÑO. Las del SISTEMA (estado, montos, colores) solo
     las escribe el sistema: lo que se toque ahí en Excel se pisa en la
     siguiente sincronización. Las de CAMILO (costos, notas, fuente) solo las
     escribe él: el sistema las lee del Excel, las guarda en la base y nunca
     las pisa.
  3. Cada fila se identifica por `id_venta` (el id del pedido, no cambia jamás)
     y cada clienta por `id_clienta`. El código PED-2026-0417 es para leer; el
     id es para cruzar.
  4. Los datos personales (nombre, teléfono, ciudad) están aquí porque son la
     operación del negocio. El archivo vive en el equipo de Camilo, no se
     comparte ni se sube a la nube sin cuidarlo (Ley 1581 de 2012).

Todo en este módulo es puro: sin archivos, sin base de datos, sin Excel.
"""

# ruff: noqa: E501  (tablas de datos: una columna por línea se lee mejor)

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from app.domain.anuncios import VENTANA_DE_ATRIBUCION_DIAS, dias_desde
from app.domain.personalizacion import NOMBRE_COLOR

SISTEMA = "sistema"
CAMILO = "Camilo"

#: Estados en los que la clienta YA puso plata (o dice que la puso).
CON_ABONO = {
    "EN_REVISION_PAGO",
    "ANTICIPO_PAGADO",
    "EN_PRODUCCION",
    "PRODUCCION_LISTA",
    "ESPERANDO_SALDO",
    "SALDO_PAGADO",
    "DESPACHADO",
    "ENTREGADO",
}
CERRADOS_SIN_VENTA = {"CANCELADO", "REEMBOLSO"}


@dataclass(frozen=True)
class Columna:
    clave: str
    titulo: str
    dueno: str
    tipo: str  # texto | numero | pesos | fecha
    descripcion: str


COLUMNAS_VENTAS: tuple[Columna, ...] = (
    Columna(
        "id_venta",
        "ID venta",
        SISTEMA,
        "texto",
        "Identificador único del pedido. Nunca cambia. Úsalo para cruzar datos.",
    ),
    Columna(
        "codigo",
        "Código",
        SISTEMA,
        "texto",
        "Código legible del pedido (PED-AAAA-NNNN). Es la referencia que ve la clienta.",
    ),
    Columna(
        "fecha_pedido",
        "Fecha pedido",
        SISTEMA,
        "fecha",
        "Cuándo se creó el pedido (hora de Colombia).",
    ),
    Columna(
        "estado", "Estado", SISTEMA, "texto", "Estado actual del pedido en el sistema."
    ),
    Columna(
        "es_venta",
        "¿Venta?",
        SISTEMA,
        "texto",
        "SÍ si ya hay abono pagado o reportado; POR COBRAR si se pidió abono y no ha llegado; NO si se canceló.",
    ),
    Columna(
        "id_clienta", "ID clienta", SISTEMA, "texto", "Identificador único de la clienta."
    ),
    Columna(
        "clienta",
        "Clienta",
        SISTEMA,
        "texto",
        "Nombre que dio para el pedido (dato personal).",
    ),
    Columna(
        "telefono",
        "Teléfono",
        SISTEMA,
        "texto",
        "WhatsApp de la clienta (dato personal).",
    ),
    Columna("ciudad", "Ciudad", SISTEMA, "texto", "Ciudad de envío."),
    Columna(
        "canal", "Canal", SISTEMA, "texto", "Por dónde compró (WhatsApp, Instagram)."
    ),
    Columna(
        "anuncio",
        "Anuncio",
        SISTEMA,
        "texto",
        f"ID del anuncio de Meta (Click to WhatsApp) al que se le cuenta esta venta: el último que tocó la clienta antes del pedido, si fue hace menos de {VENTANA_DE_ATRIBUCION_DIAS} días. Vacío = no llegó por un anuncio. Se cruza con el ID del anuncio en el Administrador de anuncios.",
    ),
    Columna(
        "anuncio_titulo",
        "Anuncio (titular)",
        SISTEMA,
        "texto",
        "El titular de ese anuncio, para reconocerlo sin abrir Meta.",
    ),
    Columna(
        "dias_desde_anuncio",
        "Días desde el anuncio",
        SISTEMA,
        "numero",
        "Días entre el clic en el anuncio y el pedido. Filtra a 7 o menos para comparar con la ventana por defecto de Meta.",
    ),
    Columna(
        "primer_anuncio",
        "Primer anuncio",
        SISTEMA,
        "texto",
        "ID del PRIMER anuncio por el que llegó esta clienta (no cambia aunque después toque otros).",
    ),
    Columna("producto", "Producto", SISTEMA, "texto", "Producto del catálogo."),
    Columna(
        "huellitas", "Huellitas", SISTEMA, "numero", "Cantidad de huellitas del anillo."
    ),
    Columna(
        "colores",
        "Colores",
        SISTEMA,
        "texto",
        "Colores de cada huellita (corazón / deditos).",
    ),
    Columna(
        "grabado", "Grabado", SISTEMA, "texto", "Lo que se graba en el interior del aro."
    ),
    Columna("talla", "Talla", SISTEMA, "numero", "Talla del anillo (vacía si falta)."),
    Columna("precio", "Precio", SISTEMA, "pesos", "Valor total del anillo, sin envío."),
    Columna(
        "abono", "Abono", SISTEMA, "pesos", "Abono pedido para iniciar la fabricación."
    ),
    Columna(
        "abono_pagado",
        "Abono pagado",
        SISTEMA,
        "pesos",
        "Abono confirmado por una persona.",
    ),
    Columna(
        "saldo", "Saldo", SISTEMA, "pesos", "Saldo que se cobra al terminar el anillo."
    ),
    Columna(
        "saldo_pagado",
        "Saldo pagado",
        SISTEMA,
        "pesos",
        "Saldo confirmado por una persona.",
    ),
    Columna(
        "envio",
        "Envío (contraentrega)",
        SISTEMA,
        "pesos",
        "Lo que la clienta paga a la transportadora al recibir.",
    ),
    Columna(
        "fecha_abono", "Fecha abono", SISTEMA, "fecha", "Cuándo se confirmó el abono."
    ),
    Columna("fecha_despacho", "Fecha despacho", SISTEMA, "fecha", "Cuándo se despachó."),
    Columna(
        "fecha_entrega",
        "Fecha entrega",
        SISTEMA,
        "fecha",
        "Cuándo se marcó como entregado.",
    ),
    Columna(
        "dias_hasta_despacho",
        "Días hasta despacho",
        SISTEMA,
        "numero",
        "Días entre el abono y el despacho.",
    ),
    Columna(
        "notas_sistema",
        "Notas del sistema",
        SISTEMA,
        "texto",
        "Notas del pedido que dejó el bot o el panel.",
    ),
    Columna(
        "costo_material",
        "Costo material",
        CAMILO,
        "pesos",
        "EDITABLE. Lo que costó fabricar el anillo (plata, circones, taller).",
    ),
    Columna(
        "costo_envio_real",
        "Costo envío real",
        CAMILO,
        "pesos",
        "EDITABLE. Lo que realmente costó el envío, si lo asumió el negocio.",
    ),
    Columna(
        "fuente",
        "Fuente",
        CAMILO,
        "texto",
        "EDITABLE. De dónde llegó la clienta (Instagram, TikTok, referida, pauta…).",
    ),
    Columna(
        "etiqueta",
        "Etiqueta",
        CAMILO,
        "texto",
        "EDITABLE. Etiqueta libre para agrupar (regalo, duelo, mayorista…).",
    ),
    Columna(
        "notas_camilo",
        "Notas de Camilo",
        CAMILO,
        "texto",
        "EDITABLE. Notas propias. El sistema nunca las cambia.",
    ),
)

COLUMNAS_CLIENTAS: tuple[Columna, ...] = (
    Columna(
        "id_clienta", "ID clienta", SISTEMA, "texto", "Identificador único de la clienta."
    ),
    Columna(
        "clienta", "Clienta", SISTEMA, "texto", "Último nombre que dio (dato personal)."
    ),
    Columna("telefono", "Teléfono", SISTEMA, "texto", "WhatsApp (dato personal)."),
    Columna("ciudad", "Ciudad", SISTEMA, "texto", "Última ciudad de envío."),
    Columna(
        "primera_compra",
        "Primera compra",
        SISTEMA,
        "fecha",
        "Fecha del primer pedido con abono.",
    ),
    Columna(
        "ultima_compra",
        "Última compra",
        SISTEMA,
        "fecha",
        "Fecha del último pedido con abono.",
    ),
    Columna("pedidos", "Pedidos", SISTEMA, "numero", "Cantidad de pedidos con abono."),
    Columna(
        "total_comprado",
        "Total comprado",
        SISTEMA,
        "pesos",
        "Suma del precio de los pedidos con abono.",
    ),
)

EDITABLES = tuple(c.clave for c in COLUMNAS_VENTAS if c.dueno == CAMILO)


def _colores(personalizacion) -> str:
    partes = []
    for i, h in enumerate(personalizacion.huellitas, 1):
        corazon, dedos = NOMBRE_COLOR[h.corazon], NOMBRE_COLOR[h.dedos]
        partes.append(f"H{i}: {corazon}/{dedos}")
    return " · ".join(partes)


def _es_venta(estado: str) -> str:
    if estado in CON_ABONO:
        return "SÍ"
    if estado in CERRADOS_SIN_VENTA:
        return "NO"
    return "POR COBRAR"


def fila_de_venta(
    pedido,
    clienta,
    cuando: dict[str, datetime],
    anotaciones: dict[str, str] | None = None,
) -> dict:
    """Una fila de la hoja Ventas. `cuando` = estado -> primera vez que se llegó."""
    item = pedido.items[0] if pedido.items else None
    p = item.personalizacion if item else None
    abono_en = cuando.get("ANTICIPO_PAGADO")
    despacho_en = cuando.get("DESPACHADO")
    fila = {
        "id_venta": pedido.id,
        "codigo": pedido.codigo,
        "fecha_pedido": pedido.created_at,
        "estado": pedido.estado,
        "es_venta": _es_venta(pedido.estado),
        "id_clienta": pedido.customer_id,
        "clienta": (pedido.envio.nombre or getattr(clienta, "nombre", "") or "").strip(),
        "telefono": pedido.envio.telefono or getattr(clienta, "channel_user_id", ""),
        "ciudad": pedido.envio.ciudad,
        "canal": getattr(getattr(clienta, "channel", None), "value", ""),
        "anuncio": pedido.anuncio.anuncio_id if pedido.anuncio else "",
        "anuncio_titulo": pedido.anuncio.titulo if pedido.anuncio else "",
        "dias_desde_anuncio": dias_desde(pedido.anuncio, pedido.created_at),
        "primer_anuncio": getattr(
            getattr(clienta, "primer_anuncio", None), "anuncio_id", ""
        ),
        "producto": item.nombre if item else "",
        "huellitas": len(p.huellitas) if p else 0,
        "colores": _colores(p) if p else "",
        "grabado": _grabado(p),
        "talla": p.talla if p else None,
        "precio": pedido.total_cop,
        "abono": pedido.anticipo_cop,
        "abono_pagado": pedido.anticipo_pagado_cop,
        "saldo": pedido.saldo_cop,
        "saldo_pagado": pedido.saldo_pagado_cop,
        "envio": pedido.envio_contraentrega_cop,
        "fecha_abono": abono_en,
        "fecha_despacho": despacho_en,
        "fecha_entrega": cuando.get("ENTREGADO"),
        "dias_hasta_despacho": (despacho_en - abono_en).days
        if abono_en and despacho_en
        else None,
        "notas_sistema": pedido.notas,
    }
    if len(pedido.items) > 1:
        # Varios anillos en una compra (02/10): una fila, cada anillo descrito.
        anillos = [i.personalizacion for i in pedido.items]
        fila["producto"] = " + ".join(i.nombre for i in pedido.items)
        fila["huellitas"] = sum(len(q.huellitas) for q in anillos)
        fila["colores"] = " | ".join(
            f"Anillo {k}: {_colores(q)}" for k, q in enumerate(anillos, 1)
        )
        fila["grabado"] = " | ".join(
            f"Anillo {k}: {_grabado(q)}" for k, q in enumerate(anillos, 1)
        )
    for clave in EDITABLES:
        fila[clave] = (anotaciones or {}).get(clave, "")
    return fila


def filas_de_clientas(filas_ventas: list[dict]) -> list[dict]:
    """Resumen por clienta, solo con pedidos que ya son venta."""
    por_clienta: dict[str, dict] = {}
    for f in sorted(filas_ventas, key=lambda x: x["fecha_pedido"]):
        if f["es_venta"] != "SÍ":
            continue
        c = por_clienta.setdefault(
            f["id_clienta"],
            {
                "id_clienta": f["id_clienta"],
                "primera_compra": f["fecha_pedido"],
                "pedidos": 0,
                "total_comprado": 0,
            },
        )
        c.update(
            clienta=f["clienta"] or c.get("clienta", ""),
            telefono=f["telefono"],
            ciudad=f["ciudad"] or c.get("ciudad", ""),
        )
        c["ultima_compra"] = f["fecha_pedido"]
        c["pedidos"] += 1
        c["total_comprado"] += f["precio"] or 0
    return list(por_clienta.values())


def valor_editable(texto) -> str:
    """Lo que Camilo escribió, normalizado para guardarlo. Vacío = sin dato."""
    if texto is None:
        return ""
    if isinstance(texto, float) and texto.is_integer():
        return str(int(texto))
    return str(texto).strip()[:500]


def _grabado(p) -> str:
    from app.domain.personalizacion import texto_del_grabado

    return texto_del_grabado(p.grabados, p.pieza, p.sin_grabado) if p else ""
