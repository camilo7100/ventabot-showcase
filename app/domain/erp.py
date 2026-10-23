"""El ERP del negocio (HUELLAS_ERP_v1, en Google Sheets): qué escribe el bot.

════════════════════════════════════════════════════════════════════════════
LA REGLA DEL ERP: cada dato se escribe UNA vez, en UNA hoja
════════════════════════════════════════════════════════════════════════════
El ERP de Camilo tiene tres capas: CAPTURA (Ventas, Pagos, Produccion…),
CATÁLOGOS y PROCESAMIENTO (Inventario, Mensual, Dashboard), y todo lo que no es
captura se calcula solo con fórmulas. El bot respeta eso al pie de la letra:

  · escribe SOLO en las columnas de captura (las amarillas);
  · nunca toca una fórmula, un catálogo ni el tablero;
  · usa los mismos nombres de las listas desplegables (producto, canal, estado),
    para que las validaciones del ERP no marquen «REVISAR».

QUÉ SE LLENA SOLO
  · VENTAS: una fila por pedido cuando el abono queda verificado (antes es un
    prospecto, no una venta). Su «Estado» se va moviendo con el pedido.
  · PAGOS: el saldo, cuando queda verificado (el abono ya va en Ventas).
  · PRODUCCIÓN: una fila (un «lote» de 1) cuando el anillo queda listo: el
    inventario descuenta la plata y los insumos solo, según la receta (BOM).

Cada fila lleva el código del pedido (PED-2026-…) para que sea auditable: del
ERP se llega a la conversación en Chatwoot y al revés.

Todo en este módulo es puro: sin red, se prueba en milisegundos.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.domain.models import Order
from app.domain.order_state import ANTICIPO_OK, OrderState

S = OrderState

#: Hoja de Ventas: columnas que escribe el bot (los nombres son los encabezados
#: de la fila 3 del ERP; se buscan por nombre, no por letra).
COLUMNAS_VENTA = (
    "Venta_ID",
    "Fecha",
    "Producto",
    "Celular_Cliente",
    "Canal",
    "Ciudad",
    "Talla",
    "Color_Detalle",
    "Grabado",
    "Cantidad",
    "Precio_Unit",
    "Abono_Inicial",
    "Medio_Pago",
    "Estado",
)
#: Columna nueva que agrega el bot al final de Ventas: el código del pedido.
REFERENCIA = "Pedido_Ref"
COLUMNAS_PAGO = ("Fecha", "Venta_ID", "Monto", "Medio_Pago", "Nota")
COLUMNAS_PRODUCCION = (
    "Fecha",
    "Lote",
    "Producto",
    "Cantidad",
    "Tiempo_Total_Min",
    "Nota",
)

#: Los nombres EXACTOS de Cat_Productos. Otro nombre = «Producto inválido».
PRODUCTO_ERP = {1: "Anillos 1 huella", 2: "Anillos 2 huella", 3: "Anillos 3 huella"}
#: Canal de Cat_Canales. El bot atiende WhatsApp; de dónde vino (un anuncio de
#: Instagram) no lo sabe, y Lía lo puede corregir en la celda.
CANAL = "WhatsApp"
#: Minutos de terminación por unidad (Config!B8 del ERP). Se usa en Producción.
MINUTOS_POR_UNIDAD = 80

#: Estado del pedido -> la lista «Estado_Venta» de Config del ERP.
ESTADO_ERP: dict[OrderState, str] = {
    S.ANTICIPO_PAGADO: "Pedido",
    S.EN_PRODUCCION: "Producción",
    S.PRODUCCION_LISTA: "Pendiente pago",
    S.ESPERANDO_SALDO: "Pendiente pago",
    S.EN_REVISION_PAGO: "Pendiente pago",
    S.SALDO_PAGADO: "Producción",
    S.DESPACHADO: "Enviado",
    S.ENTREGADO: "Entregado",
    S.CANCELADO: "Cancelado",
    S.REEMBOLSO: "Cancelado",
}


def es_venta(pedido: Order) -> bool:
    """¿Ya es una venta? Solo con el abono verificado (antes es un prospecto).

    Un pedido cancelado o en revisión cuenta si el abono YA había entrado: esa
    plata existió y el ERP tiene que verla.
    """
    estado = S(pedido.estado)
    if estado in ANTICIPO_OK:
        return True
    return bool(pedido.anticipo_pagado_cop) and estado in (
        S.EN_REVISION_PAGO,
        S.CANCELADO,
        S.REEMBOLSO,
    )


def por_anillo(pedido: Order) -> list[Order]:
    """El pedido como lo ve el ERP: UNA fila por anillo (02/10).

    Un pedido de varios anillos es una compra (un abono, un saldo), pero en el
    ERP cada anillo es una venta: así se cuentan las piezas, se costea la plata
    de cada una y la Producción descuenta lo que de verdad se fundió. Cada
    anillo sale como un pedido de una línea con código «PED-…-A1», «-A2», y su
    parte de la plata (el abono es fijo por anillo; el saldo, lo que falta de
    su precio). Un pedido de un anillo sale tal cual.
    """
    if len(pedido.items) <= 1:
        return [pedido]
    n = len(pedido.items)
    abono = pedido.anticipo_cop // n
    salida = []
    for k, item in enumerate(pedido.items, 1):
        precio = item.subtotal_cop
        saldo = max(0, precio - abono)
        salida.append(
            pedido.model_copy(
                update={
                    "codigo": f"{pedido.codigo}-A{k}",
                    "items": [item],
                    "subtotal_cop": precio,
                    "total_cop": precio,
                    "anticipo_cop": abono,
                    "saldo_cop": saldo,
                    "anticipo_pagado_cop": abono if pedido.anticipo_pagado_cop else 0,
                    "saldo_pagado_cop": saldo if pedido.saldo_pagado_cop else 0,
                }
            )
        )
    return salida


def huellitas_de(pedido: Order) -> int:
    item = pedido.items[0] if pedido.items else None
    if item is None:
        return 1
    n = len(item.personalizacion.huellitas)
    if n:
        return n
    digitos = [c for c in item.sku if c.isdigit()]
    return int(digitos[-1]) if digitos else 1


def producto_erp(pedido: Order) -> str:
    """El nombre de Cat_Productos: «Cadena» (03/10) o el anillo por sus huellitas."""
    item = pedido.items[0] if pedido.items else None
    if item is not None and item.personalizacion.pieza == "cadena":
        return "Cadena"
    if item is not None and item.personalizacion.pieza == "corazon":
        # El anillo de corazón (17/10) todavía no está en Cat_Productos (faltan
        # sus gramos de plata): cuesta lo mismo que el de 1 huella y va como
        # ese; «Anillo de corazón» queda en el detalle del color.
        return PRODUCTO_ERP[1]
    return PRODUCTO_ERP.get(huellitas_de(pedido), PRODUCTO_ERP[1])


def celular(telefono: str) -> str:
    """Los 10 dígitos colombianos, como los tiene el ERP («3001110012»)."""
    solo = "".join(c for c in telefono or "" if c.isdigit())
    return solo[-10:] if len(solo) >= 10 else solo


def color_detalle(pedido: Order) -> str:
    """Como los escribe Lía en el ERP: «♡ Negro / Dedos: Blanco»."""
    from app.domain.personalizacion import NOMBRE_COLOR

    item = pedido.items[0] if pedido.items else None
    if item is None:
        return ""
    huellitas = item.personalizacion.huellitas
    if item.personalizacion.pieza == "corazon":
        color = NOMBRE_COLOR[huellitas[0].corazon].capitalize() if huellitas else "?"
        return f"Anillo de corazón · ♡ {color}"
    partes = []
    for i, h in enumerate(huellitas, 1):
        corazon = NOMBRE_COLOR[h.corazon].capitalize()
        dedos = NOMBRE_COLOR[h.dedos].capitalize()
        texto = f"♡ {corazon} / Dedos: {dedos}"
        partes.append(f"HUELLA {i}: {texto}" if len(huellitas) > 1 else texto)
    return " | ".join(partes)


def grabado(pedido: Order) -> str:
    item = pedido.items[0] if pedido.items else None
    if item is None:
        return ""
    from app.domain.personalizacion import texto_del_grabado

    p = item.personalizacion
    if p.sin_grabado and not p.grabados:
        return "Sin grabado"
    # El formato de la hoja de Lía: «Rocky♡Luna», sin espacios (la cadena, por lado).
    return texto_del_grabado(p.grabados, p.pieza).replace(" ♡ ", "♡")


def fila_de_venta(pedido: Order, *, venta_id: str, fecha: datetime) -> dict:
    item = pedido.items[0] if pedido.items else None
    talla = item.personalizacion.talla if item else None
    return {
        "Venta_ID": venta_id,
        "Fecha": fecha.date().isoformat(),
        "Producto": producto_erp(pedido),
        "Celular_Cliente": celular(pedido.envio.telefono if pedido.envio else ""),
        "Canal": CANAL,
        "Ciudad": pedido.envio.ciudad if pedido.envio else "",
        # En la hoja va con decimal (6.5, 7.75): una fracción no se ordena ni se filtra.
        "Talla": f"TALLA {talla:g}" if talla is not None else "",
        "Color_Detalle": color_detalle(pedido),
        "Grabado": grabado(pedido),
        "Cantidad": 1,
        "Precio_Unit": pedido.total_cop,
        "Abono_Inicial": pedido.anticipo_pagado_cop or pedido.anticipo_cop,
        "Medio_Pago": "",
        "Estado": ESTADO_ERP.get(S(pedido.estado), "Pedido"),
        REFERENCIA: pedido.codigo,
    }


def necesita_pago(pedido: Order) -> bool:
    """El saldo ya quedó verificado: va una fila en Pagos."""
    return bool(pedido.saldo_pagado_cop)


def fila_de_pago(pedido: Order, *, venta_id: str, fecha: datetime) -> dict:
    return {
        "Fecha": fecha.date().isoformat(),
        "Venta_ID": venta_id,
        "Monto": pedido.saldo_pagado_cop,
        "Medio_Pago": "",
        "Nota": f"Saldo {pedido.codigo} (VentaBot)",
    }


#: Desde aquí el anillo ya existe: va su fila de Producción.
YA_PRODUCIDO = frozenset(
    {
        S.PRODUCCION_LISTA,
        S.ESPERANDO_SALDO,
        S.SALDO_PAGADO,
        S.DESPACHADO,
        S.ENTREGADO,
    }
)


def necesita_produccion(pedido: Order) -> bool:
    estado = S(pedido.estado)
    if estado in YA_PRODUCIDO:
        return True
    # En revisión del SALDO el anillo ya está hecho.
    return estado is S.EN_REVISION_PAGO and bool(pedido.anticipo_pagado_cop)


def fila_de_produccion(pedido: Order, *, fecha: datetime) -> dict:
    return {
        "Fecha": fecha.date().isoformat(),
        "Lote": pedido.codigo,
        "Producto": producto_erp(pedido),
        "Cantidad": 1,
        "Tiempo_Total_Min": MINUTOS_POR_UNIDAD,
        "Nota": "Anillo de VentaBot (1 unidad); tiempo estándar de Config",
    }


def siguiente_venta_id(existentes: list[str]) -> str:
    """V0142 -> V0143. Sigue la numeración que ya tiene el ERP."""
    numeros = [int(v[1:]) for v in existentes if v and v[:1] == "V" and v[1:].isdigit()]
    return f"V{(max(numeros) if numeros else 0) + 1:04d}"


#: Colombia (UTC−5, sin horario de verano): el día de un pedido es el de Lía.
_COLOMBIA = timezone(timedelta(hours=-5))


def de_prueba(pedido: Order, reales_desde: str) -> bool:
    """¿Es un pedido de antes del día de «Pasar a real» (`VENTAS_REALES_DESDE`)?

    Vacío = no hay día todavía: nada se considera de prueba (todo se copia).
    """
    if not reales_desde:
        return False
    creado = pedido.created_at
    if creado.tzinfo is not None:
        creado = creado.astimezone(_COLOMBIA)
    return creado.date().isoformat() < reales_desde


def solo_reales(pedidos: list[Order], reales_desde: str) -> list[Order]:
    """Lo que el bot copia al ERP: desde el día real (01/10: las pruebas del 29
    y 30/09 se quedan en la base del bot, pero no entran a la hoja de verdad)."""
    return [p for p in pedidos if not de_prueba(p, reales_desde)]
