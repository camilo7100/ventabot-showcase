"""El taller: qué hay pendiente y qué se puede hacer con cada pedido.

QUÉ ES ESTO
===========
Todo lo que Lía necesita saber para trabajar, calculado en Python puro. Sin
base de datos, sin HTTP, sin pantalla: entran pedidos, salen colas de trabajo
y botones. Por eso se puede probar entero en milisegundos, y por eso el día
que el panel sea una app de celular en vez de una página web no habrá que
reescribir ni una regla.

LAS DOS COSAS QUE RESUELVE
==========================
1. QUÉ MIRAR PRIMERO. Con cuarenta pedidos abiertos, la pregunta no es "¿cómo
   va todo?" sino "¿qué se me está quedando?". `bandejas()` ordena el día:
   tallas dudosas primero, luego lo que se puede empezar a fabricar, luego lo
   que ya está listo y falta cobrar.

2. QUÉ SE PUEDE HACER. Los botones de cada pedido salen de la MISMA tabla de
   transiciones que usa el bot (`app.domain.order_state`). Eso significa que
   el botón "Despachar" no existe si no se ha cobrado el saldo — no porque
   alguien se acuerde de esconderlo, sino porque la transición no está en la
   tabla. La regla de negocio y la interfaz no pueden desincronizarse porque
   son la misma fuente.

CÓMO EDITARLO
=============
· Cambiar el orden del día        -> mueve una línea en BANDEJAS
· Cambiar el texto de un botón    -> edita ACCIONES
· Prohibir un movimiento          -> quítalo de TRANSICIONES en order_state.py
                                     (y el botón desaparece solo)
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from app.domain.faq import ENVIO_NACIONAL_COP
from app.domain.guion import AVISOS, aviso, para_las_piezas, plantilla_de
from app.domain.models import (
    Customer,
    Order,
    OutboundMessage,
    conversation_id,
)
from app.domain.order_state import TERMINALES, TRANSICIONES, OrderState
from app.domain.pricing import formatear_cop

S = OrderState


@dataclass(frozen=True)
class Accion:
    """Un botón del panel."""

    destino: OrderState
    titulo: str
    #: `peligro` pinta el botón de rojo y pide confirmación: son los que no
    #: se deshacen (cancelar, reembolsar) o los que mueven plata.
    peligro: bool = False


#: Cómo se le dice a Lía cada movimiento. El texto es de taller, no de manual:
#: ella no piensa en "transicionar a PRODUCCION_LISTA", piensa en "ya quedó".
ACCIONES: dict[OrderState, str] = {
    S.EN_PRODUCCION: "Empezar a fabricar",
    S.PRODUCCION_LISTA: "Ya quedó listo",
    S.ESPERANDO_SALDO: "Cobrar el saldo",
    S.SALDO_PAGADO: "Saldo recibido",
    S.DESPACHADO: "Despachado",
    S.ENTREGADO: "Entregado",
    S.ANTICIPO_PAGADO: "Abono recibido",
    S.EN_REVISION_PAGO: "Revisar el pago",
    S.ESPERANDO_ANTICIPO: "Volver a cobrar el abono",
    S.CONFIRMADO: "Confirmar",
    S.COTIZADO: "Re-cotizar",
    S.CANCELADO: "Cancelar",
    S.REEMBOLSO: "Reembolsar",
}

#: Movimientos que no se deshacen o que mueven plata: se pintan en rojo y se
#: piden dos veces. Equivocarse aquí cuesta un anillo o una clienta.
PELIGROSOS: frozenset[OrderState] = frozenset({S.CANCELADO, S.REEMBOLSO})


def es_pago_del_saldo(pedido: Order) -> bool:
    """¿El pago que se está revisando es el del SALDO (el abono ya entró)?"""
    return pedido.anticipo_pagado_cop > 0


def acciones_de(pedido: Order) -> list[Accion]:
    """Los botones de UN pedido, sacados de la tabla de transiciones.

    Ojo con lo que NO aparece nunca, y por qué: desde PRODUCCION_LISTA la
    tabla solo permite ESPERANDO_SALDO. No hay botón "Despachar" porque no
    hay transición. No se puede despachar sin cobrar ni queriendo.

    Con un pago EN REVISIÓN la tabla deja ir a «abono recibido» y a «saldo
    recibido»; aquí se muestra solo el que corresponde. Con los dos botones a
    la vista, un dedo equivocado da por pagado el saldo de un anillo que ni se
    ha empezado.
    """
    actual = OrderState(pedido.estado)
    destinos = TRANSICIONES.get(actual, set()) - {actual}
    titulos = dict(ACCIONES)
    if actual is S.EN_REVISION_PAGO:
        if es_pago_del_saldo(pedido):
            destinos -= {S.ANTICIPO_PAGADO, S.ESPERANDO_ANTICIPO}
            titulos[S.ESPERANDO_SALDO] = "El saldo no ha llegado"
        else:
            destinos -= {S.SALDO_PAGADO, S.ESPERANDO_SALDO}
            titulos[S.ESPERANDO_ANTICIPO] = "El abono no ha llegado"
    return [
        Accion(
            destino=d,
            titulo=titulos.get(d, d.value.replace("_", " ").capitalize()),
            peligro=d in PELIGROSOS,
        )
        for d in sorted(destinos, key=lambda x: x.value)
    ]


class PedidoIncompleto(Exception):
    """Regla de Camilo (19/09): sin el 100 % de los datos, no entra al taller."""

    def __init__(self, codigo: str, faltan: list[str]) -> None:
        self.codigo, self.faltan = codigo, faltan
        super().__init__(f"{codigo}: falta {', '.join(faltan)}")


def falta_para_taller(pedido: Order, *, huellitas_por_sku: dict[str, int]) -> list[str]:
    """Lo que le falta al pedido para FABRICARLO: el anillo completo, con talla.

    La dirección no entra aquí: se pide después del abono y se exige al
    despachar (`falta_para_despachar`). Regla de Camilo, 19/09.
    """
    return falta_por_fabricar(pedido, huellitas_por_sku=huellitas_por_sku)


class SinFotosDelAnillo(Exception):
    """Se quiso decir «tu anillo ya está listo» sin una sola foto.

    Regla de Camilo (20/09): ese mensaje ES las fotos. Sin ellas se le está
    pidiendo a alguien que transfiera $140.000 por algo que no ha visto, y
    encima se le promete una foto que no llega. Pasó la noche del 19/09: salió
    «Te comparto las fotos de cómo quedó» y no salió ninguna imagen.
    """

    def __init__(self, codigo: str) -> None:
        self.codigo = codigo
        super().__init__(
            f"El pedido {codigo} no tiene fotos del anillo terminado. Súbelas "
            "en el panel del taller y vuelve a marcarlo listo: el mensaje que "
            "le llega a la clienta lleva las fotos dentro."
        )


def falta_para_despachar(pedido: Order) -> list[str]:
    """Lo que le falta para ENTREGARLO: nombre y dirección, o que lo recoge."""
    nombres = {
        "nombre": "nombre completo",
        "ciudad": "ciudad",
        "cedula": "cédula",
        "celular": "celular",
        "direccion": "dirección completa con barrio y nomenclatura",
    }
    if pedido.envio is None:
        return ["los datos de envío (o si lo recoge)"]
    faltan = [nombres.get(f, f) for f in pedido.envio.falta()]
    # La guía la pone Lía al despacharlo, y es obligatoria: va en el mensaje a
    # la clienta para que sepa por dónde va su anillo (Camilo, 29/09).
    if not pedido.envio.recoge and not pedido.envio.guia.strip():
        faltan.append("número de guía")
    return faltan


def montos_al_llegar(pedido: Order, destino: OrderState) -> dict[str, int]:
    """Lo que queda PAGADO al confirmar un pago. Sin esto el panel decía
    «abonado $0» de un pedido con el abono confirmado (19/09), y el ERP no
    tendría con qué llenar sus cobros."""
    if destino is S.ANTICIPO_PAGADO and not pedido.anticipo_pagado_cop:
        return {"anticipo_pagado_cop": pedido.anticipo_cop}
    if destino is S.SALDO_PAGADO and not pedido.saldo_pagado_cop:
        return {"saldo_pagado_cop": pedido.saldo_cop}
    return {}


@dataclass(frozen=True)
class Bandeja:
    """Una cola de trabajo del día."""

    clave: str
    titulo: str
    #: Qué hay que hacer con estos. Se muestra debajo del título.
    ayuda: str
    pedidos: tuple[Order, ...] = ()

    @property
    def cuantos(self) -> int:
        return len(self.pedidos)


#: EL ORDEN DEL DÍA. La primera bandeja es lo primero que Lía ve al abrir el
#: panel, así que aquí se decide qué es urgente.
#:
#: `talla_por_revisar` va primera a propósito: es la única cola donde una
#: demora se convierte en un anillo mal fabricado. Todas las demás solo
#: retrasan; esa daña.
BANDEJAS: tuple[tuple[str, str, str], ...] = (
    # Primero lo que tiene plata esperando: una clienta que ya pagó no puede
    # quedar escondida entre los que no han pagado. El 28/09 un SALDO en
    # revisión salía en «Esperando el abono» (Camilo).
    (
        "pagos_por_verificar",
        "💰 Pagos por verificar",
        "Mandaron el comprobante. Míralo en el banco y confírmalo: el botón dice si "
        "es el abono o el saldo.",
    ),
    (
        "talla_por_revisar",
        "Tallas por confirmar",
        "El bot leyó la foto pero la medida quedó dudosa. Míralas antes de fundir.",
    ),
    (
        "para_fabricar",
        "Listos para fabricar",
        "Abono pagado y diseño completo. Se pueden empezar hoy.",
    ),
    (
        "en_produccion",
        "En el taller",
        "En fabricación. Cuando queden, manda las fotos y cobra el saldo.",
    ),
    (
        "por_cobrar",
        "Por cobrar el saldo",
        "Ya están listos. Falta el saldo para poder despachar.",
    ),
    (
        "por_despachar",
        "Por despachar",
        "Saldo cobrado. Llévalos a la transportadora y escribe el número de guía "
        "en el recuadro 🚚 de cada pedido: sin guía no se despacha.",
    ),
    (
        "esperando_abono",
        "Esperando el abono",
        "Diseñaron su anillo y no han abonado. Vale la pena un recordatorio.",
    ),
)

#: Qué estados caen en cada bandeja. Un estado puede no estar en ninguna: es
#: lo que le pasa a BORRADOR, que no es trabajo de nadie todavía.
ESTADOS_DE_BANDEJA: dict[str, frozenset[OrderState]] = {
    "para_fabricar": frozenset({S.ANTICIPO_PAGADO}),
    "en_produccion": frozenset({S.EN_PRODUCCION}),
    "por_cobrar": frozenset({S.PRODUCCION_LISTA, S.ESPERANDO_SALDO}),
    "por_despachar": frozenset({S.SALDO_PAGADO}),
    "pagos_por_verificar": frozenset({S.EN_REVISION_PAGO}),
    "esperando_abono": frozenset({S.ESPERANDO_ANTICIPO}),
}


def talla_dudosa(pedido: Order) -> bool:
    return any(i.personalizacion.talla_revisar for i in pedido.items)


def falta_por_fabricar(pedido: Order, *, huellitas_por_sku: dict[str, int]) -> list[str]:
    """Qué datos le faltan al pedido para poder entrar al taller.

    Es la comprobación que evita la peor llamada posible: la de preguntarle a
    una clienta que ya pagó de qué color quería su anillo.
    """
    faltan: set[str] = set()
    for item in pedido.items:
        faltan.update(item.personalizacion.falta(huellitas_por_sku.get(item.sku, 1)))
    return sorted(faltan)


def bandejas(pedidos: list[Order], *, ahora: datetime | None = None) -> list[Bandeja]:
    """Reparte los pedidos abiertos en las colas del día.

    Un pedido puede salir en DOS bandejas (por ejemplo, en el taller y con la
    talla dudosa). Es intencional: la bandeja de tallas es un aviso, no una
    etapa, y esconderlo porque "ya está en otra lista" es justo cómo se cuela
    un anillo mal medido.
    """
    ahora = ahora or datetime.now(UTC)
    abiertos = [p for p in pedidos if OrderState(p.estado) not in TERMINALES]

    def por_antiguedad(ps):
        return tuple(sorted(ps, key=lambda p: p.created_at))

    salida = []
    for clave, titulo, ayuda in BANDEJAS:
        if clave == "talla_por_revisar":
            elegidos = [p for p in abiertos if talla_dudosa(p)]
        else:
            estados = ESTADOS_DE_BANDEJA[clave]
            elegidos = [p for p in abiertos if OrderState(p.estado) in estados]
        salida.append(
            Bandeja(
                clave=clave, titulo=titulo, ayuda=ayuda, pedidos=por_antiguedad(elegidos)
            )
        )
    return salida


def dias_esperando(pedido: Order, *, ahora: datetime | None = None) -> int:
    """Días desde la última vez que este pedido se movió.

    Es la métrica que hace visible lo que se está quedando atrás. Un pedido
    lleva semanas en el sistema con toda normalidad; lo que no es normal es
    que lleve nueve días sin que nadie lo toque.
    """
    ahora = ahora or datetime.now(UTC)
    referencia = pedido.updated_at or pedido.created_at
    if referencia.tzinfo is None:
        referencia = referencia.replace(tzinfo=UTC)
    return max(0, (ahora - referencia).days)


#: A partir de aquí, el pedido se pinta en ámbar en el panel. [POR DEFINIR]
#: La fabricación son 10-15 días, así que tres días sin moverse todavía es
#: normal; cinco ya es una pregunta.
DIAS_PARA_ALERTAR = 5


# ══════════════════════════════════════════════════════════════════════════
#  AVISAR A LA CLIENTA CUANDO EL PEDIDO SE MUEVE
# ══════════════════════════════════════════════════════════════════════════


def mensaje_de_aviso(
    pedido: Order,
    cliente: Customer,
    estado_nuevo: OrderState,
    *,
    envio_contraentrega_cop: int | None = None,
) -> OutboundMessage | None:
    """El mensaje que se le manda a la clienta al mover el pedido, o None.

    Función PURA: no envía nada, no toca la base de datos. Devuelve el mensaje
    y quien la llama decide qué hacer con él. Así se puede probar el texto
    exacto de cada aviso sin levantar un servidor ni tocar WhatsApp.

    Los números salen del PEDIDO, nunca de un cálculo nuevo: el saldo que se
    le cobra es el que quedó guardado cuando se cotizó. Recalcularlo aquí
    abriría la puerta a que el precio cambie entre que ella confirmó y que
    se le cobra, y eso es una discusión con una clienta que ya pagó un abono.
    """
    # El flete también sale del PEDIDO. Es un cobro: si aquí dice una cifra y
    # en la cotización decía otra, es una discusión con alguien que ya abonó.
    # Solo se cae al nacional cuando el pedido es viejo y no lo lleva guardado.
    flete = (
        envio_contraentrega_cop
        if envio_contraentrega_cop is not None
        else (pedido.envio_contraentrega_cop or ENVIO_NACIONAL_COP)
    )
    recoge = bool(pedido.envio and pedido.envio.recoge)
    texto = aviso(
        estado_nuevo.value,
        recoge=recoge,
        envio_con_saldo=bool(pedido.envio and pedido.envio.envio_con_saldo),
        codigo=pedido.codigo,
        saldo=formatear_cop(pedido.saldo_cop - pedido.saldo_pagado_cop),
        total=formatear_cop(pedido.total_cop),
        envio_contraentrega=formatear_cop(flete),
        # Un solo número de envío en todos los mensajes: el del pedido.
        envio_del_mensaje=formatear_cop(flete),
        transportadora=(pedido.envio.transportadora if pedido.envio else "")
        or "Coordinadora",
        guia=(pedido.envio.guia if pedido.envio else "")
        or "(te la comparto en un momento)",
    )
    if texto is None:
        return None
    # La cadena (03/10) o varias piezas: el aviso habla de lo que es.
    texto = para_las_piezas(texto, [i.personalizacion.pieza for i in pedido.items])

    # El mensaje lleva SIEMPRE las dos versiones: el texto libre y la
    # plantilla. Quién de las dos sale lo decide el despachador, que es el
    # único que sabe si la ventana de 24 h está abierta — y lo sabe en el
    # momento del envío, que puede ser horas después de este.
    #
    # Decidirlo aquí sería adivinar el futuro: se calcularía con la ventana de
    # ahora y se enviaría con la de dentro de un rato.
    valores = {
        "codigo": pedido.codigo,
        "saldo": formatear_cop(pedido.saldo_cop - pedido.saldo_pagado_cop),
        "total": formatear_cop(pedido.total_cop),
    }
    plantilla = plantilla_de(
        estado_nuevo.value,
        recoge=recoge,
        envio_con_saldo=bool(pedido.envio and pedido.envio.envio_con_saldo),
    )
    nombre_plantilla, params = (None, {})
    if plantilla is not None:
        nombre_plantilla = plantilla[0]
        # Las claves son "1", "2"… porque así se numeran los huecos de Meta
        # ({{1}}, {{2}}). El ORDEN de esta tupla es el orden con el que se
        # registró la plantilla: cambiarlo manda el código donde va el monto.
        params = {str(i): valores[campo] for i, campo in enumerate(plantilla[1], 1)}

    return OutboundMessage(
        channel=cliente.channel,
        to=cliente.channel_user_id,
        kind="text",
        text=texto,
        template_name=nombre_plantilla,
        template_params=params,
        conversation_id=conversation_id(cliente.channel, cliente.channel_user_id),
        # La clave de idempotencia incluye el estado destino: si alguien toca
        # el botón dos veces, o si el panel se recarga, el aviso sale UNA vez.
        # Es la misma defensa que usa el webhook de pagos.
        idempotency_key=f"aviso:{pedido.id}:{estado_nuevo.value}",
    )


#: Estados cuyo aviso vale la pena acompañar de las fotos del anillo.
#:
#: Solo el cobro del saldo. Es el mensaje donde se le piden $140.000 a alguien
#: que lleva dos semanas esperando, y la foto es lo que lo convierte de "un
#: cobro" en "aquí está tu anillo". Mandarlas también al despachar sería
#: repetirle lo que ya vio.
CON_FOTOS: frozenset[OrderState] = frozenset({OrderState.ESPERANDO_SALDO})


def mensajes_con_fotos(
    pedido: Order,
    cliente: Customer,
    estado_nuevo: OrderState,
    *,
    base_url: str,
) -> list[OutboundMessage]:
    """Las fotos del anillo, una por mensaje, ANTES del cobro.

    WhatsApp manda una imagen por mensaje. Van primero y el texto después,
    porque así es como se lee: primero ve su anillo, después el monto. Al
    revés, el número llega antes que el motivo.

    `base_url` es la dirección pública desde la que Meta baja las imágenes.
    Si está vacía —no hay túnel levantado— no se manda ninguna foto y el
    cobro sale solo: es preferible un cobro sin fotos a un cobro que no sale.
    """
    if estado_nuevo not in CON_FOTOS or not pedido.fotos or not base_url:
        return []

    raiz = base_url.rstrip("/")
    return [
        OutboundMessage(
            channel=cliente.channel,
            to=cliente.channel_user_id,
            kind="image",
            media_url=f"{raiz}/panel/foto/{nombre}",
            text="",
            conversation_id=conversation_id(cliente.channel, cliente.channel_user_id),
            # El nombre del archivo ya es único e irrepetible, así que sirve
            # de clave: subir la misma foto dos veces daría dos archivos
            # distintos, y mandar dos veces la misma, un solo mensaje.
            idempotency_key=f"foto:{pedido.id}:{nombre}",
        )
        for nombre in pedido.fotos
    ]


def avisa_este_estado(estado: OrderState) -> bool:
    """Si mover a este estado le escribe algo a la clienta.

    El panel lo usa para decirle a Lía, ANTES de que toque el botón, si eso
    va a mandar un mensaje. Un botón que a veces escribe y a veces no, sin
    avisar cuál es cuál, se usa con miedo.

    Se consulta la tabla AVISOS directamente y no `aviso()`, porque esa
    función RELLENA la plantilla y revienta sin los datos del pedido. Preguntar
    "¿existe este aviso?" no debería obligar a tener un pedido a mano.
    """
    return estado.value in AVISOS
