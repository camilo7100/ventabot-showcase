"""Cuándo un cambio del chat puede tocar un pedido que YA EXISTE.

════════════════════════════════════════════════════════════════════════════
POR QUÉ HACE FALTA
════════════════════════════════════════════════════════════════════════════
Mientras el anillo se está armando, «mejor rosado» se anota y ya: no hay nada
fabricado. Pero la conversación de prueba con Meta mostró el otro extremo: el
bot le cambió los colores a un pedido DESPACHADO porque la clienta dijo «me
puedes montar cómo quedaría uno azul». Ningún modelo, ni ninguna regla de
lenguaje, puede ser la única defensa de eso.

Esta tabla es la validación determinística que va entre «el modelo entendió un
cambio» y «se escribe en el pedido». Mira SOLO el estado del pedido, que es un
hecho, no una interpretación.

NO es política comercial nueva: no decide si Lía acepta o no un cambio de talla
a mitad de fabricación. Decide que el BOT no lo aplica solo cuando ya hay plata
fundida, y que se lo pasa a una persona con la petición anotada. La persona
decide lo mismo que decidía antes.
"""

from __future__ import annotations

from enum import Enum

from app.domain.order_state import TERMINALES, OrderState

S = OrderState


class Permiso(str, Enum):
    #: Se escribe en el pedido, sin más. Aún no se fabrica nada.
    APLICAR = "APLICAR"
    #: Se escribe, y se deja una nota para que alguien lo confirme antes de
    #: fundir (el abono ya está pagado; el taller puede tenerlo en cola).
    APLICAR_Y_REVISAR = "APLICAR_Y_REVISAR"
    #: NO se escribe. Se anota la petición y se pasa a una persona.
    PEDIR_A_PERSONA = "PEDIR_A_PERSONA"
    #: El pedido está cerrado: no se toca nunca desde el chat.
    NUNCA = "NUNCA"


#: Antes de pagar el abono: nada está fabricado y todo se puede cambiar.
SIN_FABRICAR = frozenset(
    {S.BORRADOR, S.COTIZADO, S.CONFIRMADO, S.ESPERANDO_ANTICIPO, S.EN_REVISION_PAGO}
)

#: Lo que hace falta para la GUÍA, no para el anillo.
#:
#: Estos datos no tocan nada fabricado: son para la transportadora. Y desde el
#: 20/09 el sistema los pide **cuando el anillo ya está listo**, en el mismo
#: mensaje que lleva las fotos y el cobro del saldo (ADR 0020). Así que en esa
#: parte del proceso no son un «cambio» que alguien tenga que autorizar: son
#: la respuesta a una pregunta que acabamos de hacer.
#:
#: Faltaban `cedula` y `celular` —campos nuevos de ese mismo día— y por eso el
#: conjunto no encajaba: una clienta mandó sus datos completos, se rechazaron
#: enteros y la conversación se escaló a una persona.
DATOS_DE_LA_GUIA = frozenset(
    {"nombre", "destinatario", "ciudad", "direccion", "barrio", "cedula", "celular"}
)


def permiso(
    estado: OrderState | str,
    campos: set[str] | frozenset[str],
    *,
    sobrescribe: set[str] | frozenset[str] = frozenset(),
) -> Permiso:
    """¿Puede el chat escribir estos campos en un pedido en este estado?

    `campos` usa los nombres del proceso de compra: talla, colores, grabado,
    huellitas, nombre, ciudad, direccion. Un conjunto vacío no cambia nada y
    siempre se permite. `sobrescribe` son los que YA tenían un valor: no es lo
    mismo mandar la talla que faltaba que cambiar la que ya se está fundiendo.
    """
    estado = OrderState(estado)
    if estado in TERMINALES:
        return Permiso.NUNCA
    if not campos:
        return Permiso.APLICAR
    if estado in SIN_FABRICAR:
        return Permiso.APLICAR
    if estado is S.ANTICIPO_PAGADO:
        # Pagó y todavía no entra al taller: se aplica, pero Lía lo tiene que
        # ver antes de empezar, porque puede haberlo puesto ya en la cola.
        return Permiso.APLICAR_Y_REVISAR
    if estado is S.EN_PRODUCCION:
        # La talla es la excepción que el negocio YA acepta: «me la mandas
        # cuando puedas, la fabricación son 10 a 15 días». Cambiar colores o
        # nombres con el anillo en el torno, no.
        if campos <= {"talla"} | DATOS_DE_LA_GUIA and "talla" not in sobrescribe:
            return Permiso.APLICAR_Y_REVISAR
        return Permiso.PEDIR_A_PERSONA

    # Listo, cobrando el saldo o por despachar: el anillo ya existe, pero los
    # datos de la guía son justo lo que el sistema le acaba de pedir. Se
    # escriben sin molestar a nadie: pedirle un dato y luego mandárselo a Lía
    # para que lo autorice es no haberlo pedido.
    if campos <= DATOS_DE_LA_GUIA and estado is not S.DESPACHADO:
        return Permiso.APLICAR
    # Ya despachado: la guía está impresa y el paquete va en camino. Cambiar la
    # dirección ahí es una llamada a Coordinadora, no una edición.
    return Permiso.PEDIR_A_PERSONA
