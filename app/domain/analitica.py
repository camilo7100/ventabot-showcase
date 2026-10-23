"""Una fila por pedido, con todo separado y bien nombrado: para analizar (29/09).

Pedido de Camilo: «imagina que le vas a hacer análisis de datos en unos años».
El pedido de verdad vive como un documento (JSON) en `orders`: perfecto para
el bot, incómodo para contar. Esto es su versión PLANA —una columna por dato,
ciudad aparte de la dirección, cada huellita en su columna, una fecha por
etapa— que se reconstruye sola desde los pedidos, así nunca queda desfasada.

La llave es el CÓDIGO del pedido (PED-2026-0417): es único, es el que se lee
en el panel, en Chatwoot y en el ERP, y el que dice la clienta.

Las columnas NUNCA se renombran ni se quitan (un análisis viejo se rompería):
solo se agregan al final.
"""

from __future__ import annotations

from datetime import datetime

from app.domain.models import Order
from app.domain.order_state import ETIQUETA_CLIENTE, OrderState
from app.domain.personalizacion import NOMBRE_COLOR
from app.domain.tallas import talla_texto

#: (columna, tipo SQL, qué es). El orden es el de la tabla y el del Excel.
COLUMNAS: tuple[tuple[str, str, str], ...] = (
    ("codigo", "TEXT", "Código del pedido (la llave)"),
    ("pedido_id", "TEXT", "Identificador interno"),
    ("estado", "TEXT", "Estado (código)"),
    ("estado_legible", "TEXT", "Estado, como lo lee una persona"),
    ("creado", "TEXT", "Cuándo nació el pedido (se pidió el abono)"),
    ("actualizado", "TEXT", "Último cambio"),
    ("cliente_id", "TEXT", "Identificador de la clienta"),
    ("canal", "TEXT", "whatsapp / instagram"),
    ("telefono_whatsapp", "TEXT", "Su número de WhatsApp"),
    ("nombre_clienta", "TEXT", "Nombre de la clienta"),
    ("producto", "TEXT", "Producto"),
    ("sku", "TEXT", "SKU"),
    ("cantidad_huellitas", "INTEGER", "1, 2 o 3"),
    ("talla", "REAL", "Talla (número, 7.75 = 7¾)"),
    ("talla_texto", "TEXT", "Talla como se escribe (7¾)"),
    ("talla_origen", "TEXT", "confirmada por Lía / la dijo ella / por revisar"),
    ("huellita_1_corazon", "TEXT", "Color del corazón, huellita 1"),
    ("huellita_1_dedos", "TEXT", "Color de los deditos, huellita 1"),
    ("huellita_2_corazon", "TEXT", "Color del corazón, huellita 2"),
    ("huellita_2_dedos", "TEXT", "Color de los deditos, huellita 2"),
    ("huellita_3_corazon", "TEXT", "Color del corazón, huellita 3"),
    ("huellita_3_dedos", "TEXT", "Color de los deditos, huellita 3"),
    ("grabado", "TEXT", "Lo que se graba (Luna ♡ Rocky)"),
    ("nombres_grabados", "INTEGER", "Cuántos nombres"),
    ("sin_grabado", "INTEGER", "1 si va liso"),
    ("precio_total_cop", "INTEGER", "Precio del anillo"),
    ("abono_cop", "INTEGER", "Abono pedido"),
    ("abono_pagado_cop", "INTEGER", "Abono confirmado"),
    ("saldo_cop", "INTEGER", "Saldo del anillo"),
    ("saldo_pagado_cop", "INTEGER", "Saldo confirmado"),
    ("pendiente_cop", "INTEGER", "Lo que falta por pagar"),
    ("envio_cotizado_cop", "INTEGER", "Envío que se le cotizó"),
    ("envio_con_saldo", "INTEGER", "1 si pagó el envío con el saldo"),
    ("entrega", "TEXT", "envío / recoge"),
    ("destinatario", "TEXT", "A nombre de quién va la guía"),
    ("ciudad", "TEXT", "Ciudad de entrega"),
    ("barrio", "TEXT", "Barrio"),
    ("direccion", "TEXT", "Dirección completa"),
    ("cedula", "TEXT", "Cédula para la guía"),
    ("celular_guia", "TEXT", "Celular para la guía"),
    ("transportadora", "TEXT", "Con quién se mandó"),
    ("guia", "TEXT", "Número de guía"),
    ("fotos_del_anillo", "INTEGER", "Cuántas fotos del anillo terminado"),
    ("fecha_pago_por_verificar", "TEXT", "Primera vez que mandó un comprobante"),
    ("fecha_abono_confirmado", "TEXT", "Cuándo se confirmó el abono"),
    ("fecha_en_taller", "TEXT", "Cuándo entró al taller"),
    ("fecha_listo", "TEXT", "Cuándo quedó listo"),
    ("fecha_cobro_saldo", "TEXT", "Cuándo se le cobró el saldo (con fotos)"),
    ("fecha_saldo_confirmado", "TEXT", "Cuándo se confirmó el saldo"),
    ("fecha_despachado", "TEXT", "Cuándo se despachó"),
    ("fecha_entregado", "TEXT", "Cuándo se entregó"),
    ("fecha_cancelado", "TEXT", "Cuándo se canceló"),
    ("dias_hasta_abono", "REAL", "Días entre nacer el pedido y confirmar el abono"),
    ("dias_en_taller", "REAL", "Días entre entrar al taller y quedar listo"),
    ("dias_hasta_despacho", "REAL", "Días entre nacer el pedido y despacharlo"),
)

NOMBRES = tuple(c for c, _, _ in COLUMNAS)

#: La primera vez que el pedido llegó a cada estado -> columna de fecha.
_FECHAS = {
    OrderState.EN_REVISION_PAGO: "fecha_pago_por_verificar",
    OrderState.ANTICIPO_PAGADO: "fecha_abono_confirmado",
    OrderState.EN_PRODUCCION: "fecha_en_taller",
    OrderState.PRODUCCION_LISTA: "fecha_listo",
    OrderState.ESPERANDO_SALDO: "fecha_cobro_saldo",
    OrderState.SALDO_PAGADO: "fecha_saldo_confirmado",
    OrderState.DESPACHADO: "fecha_despachado",
    OrderState.ENTREGADO: "fecha_entregado",
    OrderState.CANCELADO: "fecha_cancelado",
}


def _dias(desde: str | None, hasta: str | None) -> float | None:
    if not desde or not hasta:
        return None
    try:
        delta = datetime.fromisoformat(hasta) - datetime.fromisoformat(desde)
    except ValueError:
        return None
    return round(delta.total_seconds() / 86_400, 2)


def _color(c) -> str:
    return NOMBRE_COLOR.get(c, str(c)) if c is not None else ""


def fila_de_pedido(
    pedido: Order,
    *,
    nombre_clienta: str = "",
    canal: str = "",
    telefono: str = "",
    eventos: tuple | list = (),  # (estado_nuevo, fecha ISO), en orden
) -> dict:
    """El pedido aplanado: una columna por dato (ver `COLUMNAS`)."""
    from app.domain.personalizacion import texto_del_grabado

    item = pedido.items[0] if pedido.items else None
    p = item.personalizacion if item else None
    envio = pedido.envio
    estado = OrderState(pedido.estado)
    fila: dict = dict.fromkeys(NOMBRES)
    fila.update(
        codigo=pedido.codigo,
        pedido_id=pedido.id,
        estado=estado.value,
        estado_legible=ETIQUETA_CLIENTE.get(estado, estado.value),
        creado=pedido.created_at.isoformat(timespec="seconds"),
        actualizado=pedido.updated_at.isoformat(timespec="seconds"),
        cliente_id=pedido.customer_id,
        canal=canal,
        telefono_whatsapp=telefono,
        nombre_clienta=nombre_clienta,
        producto=item.nombre if item else "",
        sku=item.sku if item else "",
        precio_total_cop=pedido.total_cop,
        abono_cop=pedido.anticipo_cop,
        abono_pagado_cop=pedido.anticipo_pagado_cop,
        saldo_cop=pedido.saldo_cop,
        saldo_pagado_cop=pedido.saldo_pagado_cop,
        pendiente_cop=max(
            0, pedido.total_cop - pedido.anticipo_pagado_cop - pedido.saldo_pagado_cop
        ),
        envio_cotizado_cop=pedido.envio_contraentrega_cop,
        envio_con_saldo=int(bool(envio and envio.envio_con_saldo)),
        entrega="recoge" if envio and envio.recoge else "envío",
        destinatario=envio.nombre if envio else "",
        ciudad=envio.ciudad if envio else "",
        barrio=envio.barrio if envio else "",
        direccion=envio.direccion if envio else "",
        cedula=envio.cedula if envio else "",
        celular_guia=(envio.celular or envio.telefono) if envio else "",
        transportadora=(envio.transportadora if envio and not envio.recoge else ""),
        guia=envio.guia if envio else "",
        fotos_del_anillo=len(pedido.fotos),
    )
    if p is not None:
        fila["cantidad_huellitas"] = len(p.huellitas) or None
        fila["talla"] = p.talla
        fila["talla_texto"] = talla_texto(p.talla)
        motivo = (p.talla_motivo or "").lower()
        if p.talla is None:
            fila["talla_origen"] = ""
        elif p.talla_revisar:
            fila["talla_origen"] = "por revisar"
        elif "lia" in motivo:
            fila["talla_origen"] = "confirmada por Lía"
        else:
            fila["talla_origen"] = "la dijo ella"
        for i, h in enumerate(p.huellitas[:3], 1):
            fila[f"huellita_{i}_corazon"] = _color(h.corazon)
            fila[f"huellita_{i}_dedos"] = _color(h.dedos)
        fila["grabado"] = texto_del_grabado(p.grabados, p.pieza)
        fila["nombres_grabados"] = len(p.grabados)
        fila["sin_grabado"] = int(p.sin_grabado)
    for estado_nuevo, fecha in eventos:
        try:
            columna = _FECHAS.get(OrderState(estado_nuevo))
        except ValueError:
            continue
        if columna and not fila[columna]:
            fila[columna] = fecha
    fila["dias_hasta_abono"] = _dias(fila["creado"], fila["fecha_abono_confirmado"])
    fila["dias_en_taller"] = _dias(fila["fecha_en_taller"], fila["fecha_listo"])
    fila["dias_hasta_despacho"] = _dias(fila["creado"], fila["fecha_despachado"])
    return fila
