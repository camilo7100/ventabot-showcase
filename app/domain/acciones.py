"""Qué hace el sistema. El modelo propone; esta tabla decide.

════════════════════════════════════════════════════════════════════════════
LA FRONTERA
════════════════════════════════════════════════════════════════════════════
Todo lo que el sistema es capaz de hacer está en el enum `Accion`. Nada más.
Un modelo de lenguaje —el de hoy o el que exista en tres años— no puede
inventar una acción que no esté aquí, porque no elige acciones: describe lo
que oyó, y `planificar()` traduce.

Esa traducción es un `dict.get` sobre (acto, entidad, atributo). Se lee de un
vistazo, se prueba en microsegundos, y se puede auditar entera. Es
deliberadamente aburrida: aquí es donde no debe pasar nada interesante.

════════════════════════════════════════════════════════════════════════════
DOS COSAS QUE LA TABLA CODIFICA, Y NO SE PUEDEN SALTAR
════════════════════════════════════════════════════════════════════════════
1. QUÉ NECESITA cada acción (`NECESITA`). Si falta, no se ejecuta: se
   pregunta. Es lo que impide consultar «el saldo» sin saber de cuál.

2. CUÁLES CUESTAN DINERO (`CRITICAS`). Ahí la ambigüedad se resuelve
   preguntando, siempre, aunque el contexto parezca claro. En el resto se
   elige lo más reciente y se sigue: un bot que pregunta de más cansa tanto
   como uno que asume de más.

Nótese lo que NO existe: `CONFIRMAR_PAGO`. Que la clienta diga «ya pagué» no
mueve un peso. Lo más lejos que llega es `REGISTRAR_PAGO_REPORTADO`, que abre
un caso para que alguien lo verifique. Esa regla vive aquí, en la tabla, y no
en el criterio de nadie.
"""

from __future__ import annotations

from enum import Enum

from app.domain.interpretacion import Acto, Atributo, Entidad


class Accion(str, Enum):
    """Todo lo que el sistema sabe hacer. La lista completa."""

    # --- conversar ---
    SALUDAR = "SALUDAR"
    CHARLAR = "CHARLAR"
    NO_ENTENDI = "NO_ENTENDI"
    LLAMAR_HUMANO = "LLAMAR_HUMANO"

    # --- informar (solo lectura, nunca cuestan dinero) ---
    MOSTRAR_PRODUCTO = "MOSTRAR_PRODUCTO"
    MOSTRAR_IMAGENES = "MOSTRAR_IMAGENES"
    RESPONDER_DUDA = "RESPONDER_DUDA"
    LISTAR_PEDIDOS = "LISTAR_PEDIDOS"
    CONSULTAR_PEDIDO = "CONSULTAR_PEDIDO"
    #: Un pedido del PASADO, que la clienta señaló a propósito. Solo lee: un
    #: pedido cerrado no recibe pagos, ni cambios, ni comprobantes desde aquí.
    CONSULTAR_HISTORIAL = "CONSULTAR_HISTORIAL"
    EXPLICAR_COMO_MEDIR = "EXPLICAR_COMO_MEDIR"
    #: «¿Y ahora qué hago?». Es la pregunta que se hace justo antes de pagar,
    #: y caía en «no te entendí» — en el peor momento posible de la venta.
    EXPLICAR_QUE_SIGUE = "EXPLICAR_QUE_SIGUE"
    #: «¿Cuál me recomiendas?». Ayudarla a escoger es servicio, y es donde se
    #: cae media venta: delante de 196 combinaciones mucha gente no elige.
    SUGERIR_COMBINACION = "SUGERIR_COMBINACION"

    # --- construir un pedido ---
    INICIAR_COMPRA = "INICIAR_COMPRA"
    ANOTAR_DATOS = "ANOTAR_DATOS"
    PEDIR_LO_QUE_FALTA = "PEDIR_LO_QUE_FALTA"
    RESUMIR_Y_COBRAR_ABONO = "RESUMIR_Y_COBRAR_ABONO"
    RETOMAR_PROCESO = "RETOMAR_PROCESO"

    # --- dinero: nada de esto confirma un pago por sí solo ---
    EXPLICAR_COMO_PAGAR = "EXPLICAR_COMO_PAGAR"
    REGISTRAR_PAGO_REPORTADO = "REGISTRAR_PAGO_REPORTADO"
    PEDIR_COMPROBANTE = "PEDIR_COMPROBANTE"
    RECIBIR_COMPROBANTE = "RECIBIR_COMPROBANTE"

    # --- cosas que no se deshacen ---
    PEDIR_CANCELACION = "PEDIR_CANCELACION"
    QUITAR_DEL_PEDIDO = "QUITAR_DEL_PEDIDO"


#: (acto, entidad, atributo) -> acción. El atributo `None` en la clave
#: significa «cualquiera»: se busca primero la clave exacta y luego la
#: general, para poder afinar un caso sin duplicar toda la fila.
_MAPA: dict[tuple, Accion] = {
    # conversar
    (Acto.SALUDAR, None, None): Accion.SALUDAR,
    (Acto.CONVERSAR, None, None): Accion.CHARLAR,
    (Acto.HUMANO, None, None): Accion.LLAMAR_HUMANO,
    (Acto.OTRO, None, None): Accion.NO_ENTENDI,
    # dudas del negocio: el atributo dice cuál
    (Acto.PREGUNTAR, None, None): Accion.RESPONDER_DUDA,
    # Sin atributo también: preguntar «por la talla» solo puede ser una cosa.
    (Acto.PREGUNTAR, Entidad.TALLA, None): Accion.EXPLICAR_COMO_MEDIR,
    (Acto.CONSULTAR, Entidad.TALLA, None): Accion.EXPLICAR_COMO_MEDIR,
    (Acto.PREGUNTAR, Entidad.PRODUCTO, None): Accion.MOSTRAR_PRODUCTO,
    (Acto.PREGUNTAR, Entidad.IMAGEN, None): Accion.MOSTRAR_IMAGENES,
    (Acto.PREGUNTAR, Entidad.PAGO, Atributo.MEDIOS_DE_PAGO): Accion.EXPLICAR_COMO_PAGAR,
    # consultar
    (Acto.PREGUNTAR, Entidad.COLOR, None): Accion.SUGERIR_COMBINACION,
    (Acto.CONSULTAR, Entidad.COLOR, None): Accion.SUGERIR_COMBINACION,
    (Acto.PREGUNTAR, Entidad.PEDIDO, Atributo.ABONO): Accion.EXPLICAR_QUE_SIGUE,
    (Acto.CONSULTAR, Entidad.PEDIDO, Atributo.ABONO): Accion.EXPLICAR_QUE_SIGUE,
    (Acto.CONSULTAR, Entidad.PEDIDO, None): Accion.CONSULTAR_PEDIDO,
    (Acto.CONSULTAR, Entidad.PEDIDO, Atributo.HISTORIAL): Accion.CONSULTAR_HISTORIAL,
    (Acto.PREGUNTAR, Entidad.PEDIDO, Atributo.HISTORIAL): Accion.CONSULTAR_HISTORIAL,
    (Acto.CONSULTAR, Entidad.PRODUCTO, None): Accion.MOSTRAR_PRODUCTO,
    (Acto.CONSULTAR, Entidad.IMAGEN, None): Accion.MOSTRAR_IMAGENES,
    (Acto.CONSULTAR, Entidad.PAGO, None): Accion.CONSULTAR_PEDIDO,
    (Acto.CONSULTAR, Entidad.ENVIO, None): Accion.CONSULTAR_PEDIDO,
    (Acto.CONSULTAR, Entidad.NINGUNA, None): Accion.RESPONDER_DUDA,
    # comprar
    (Acto.COMPRAR, None, None): Accion.INICIAR_COMPRA,
    (Acto.AGREGAR, None, None): Accion.ANOTAR_DATOS,
    (Acto.MODIFICAR, None, None): Accion.ANOTAR_DATOS,
    (Acto.INFORMAR, None, None): Accion.ANOTAR_DATOS,
    (Acto.RETOMAR, None, None): Accion.RETOMAR_PROCESO,
    (Acto.CONFIRMAR, None, None): Accion.RESUMIR_Y_COBRAR_ABONO,
    # dinero
    (Acto.INFORMAR, Entidad.PAGO, None): Accion.REGISTRAR_PAGO_REPORTADO,
    (Acto.INFORMAR, Entidad.COMPROBANTE, None): Accion.RECIBIR_COMPROBANTE,
    (Acto.CONFIRMAR, Entidad.PAGO, None): Accion.REGISTRAR_PAGO_REPORTADO,
    (Acto.COMPRAR, Entidad.PAGO, None): Accion.EXPLICAR_COMO_PAGAR,
    (Acto.CONSULTAR, Entidad.PAGO, Atributo.MEDIOS_DE_PAGO): Accion.EXPLICAR_COMO_PAGAR,
    # deshacer
    (Acto.CANCELAR, None, None): Accion.PEDIR_CANCELACION,
    (Acto.ELIMINAR, None, None): Accion.QUITAR_DEL_PEDIDO,
}


class Requisito(str, Enum):
    """Qué le hace falta a una acción para poder ejecutarse."""

    PEDIDO = "PEDIDO"  # saber de QUÉ pedido se habla
    PROCESO = "PROCESO"  # una compra abierta a la que pegar los datos
    PRODUCTO = "PRODUCTO"  # saber qué producto
    DATOS = "DATOS"  # que el mensaje traiga algún dato aprovechable


NECESITA: dict[Accion, tuple[Requisito, ...]] = {
    #: El comprobante SÍ necesita saber de qué pedido: es lo que va a mirar
    #: quien verifique la transferencia. Pero no es crítica, porque recibir
    #: una foto no mueve dinero — solo deja constancia.
    Accion.RECIBIR_COMPROBANTE: (Requisito.PEDIDO,),
    Accion.CONSULTAR_PEDIDO: (Requisito.PEDIDO,),
    Accion.EXPLICAR_QUE_SIGUE: (Requisito.PEDIDO,),
    Accion.REGISTRAR_PAGO_REPORTADO: (Requisito.PEDIDO,),
    Accion.PEDIR_CANCELACION: (Requisito.PEDIDO,),
    Accion.QUITAR_DEL_PEDIDO: (Requisito.PROCESO,),
    Accion.ANOTAR_DATOS: (Requisito.DATOS,),
    Accion.RESUMIR_Y_COBRAR_ABONO: (Requisito.PROCESO,),
    Accion.RETOMAR_PROCESO: (Requisito.PROCESO,),
    Accion.MOSTRAR_IMAGENES: (Requisito.PRODUCTO,),
}

#: Acciones donde equivocarse cuesta dinero, un anillo o una clienta.
#:
#: Aquí la ambigüedad SIEMPRE se pregunta, aunque el contexto parezca claro.
#: En todo lo demás se elige lo más reciente y se sigue: preguntar de más
#: cansa tanto como asumir de más, pero solo una de las dos cobra mal.
CRITICAS: frozenset[Accion] = frozenset(
    {
        Accion.REGISTRAR_PAGO_REPORTADO,
        Accion.PEDIR_CANCELACION,
        Accion.QUITAR_DEL_PEDIDO,
        Accion.RESUMIR_Y_COBRAR_ABONO,
    }
)

#: Acciones que solo LEEN. Nunca escriben en la base de datos, así que un
#: error aquí se corrige con otro mensaje y no con una devolución.
#: Se declara explícito para que un test pueda comprobar que ninguna acción
#: de escritura se cuela en el camino rápido.
SOLO_LEEN: frozenset[Accion] = frozenset(
    {
        Accion.SALUDAR,
        Accion.CHARLAR,
        Accion.NO_ENTENDI,
        Accion.LLAMAR_HUMANO,
        Accion.MOSTRAR_PRODUCTO,
        Accion.MOSTRAR_IMAGENES,
        Accion.RESPONDER_DUDA,
        Accion.LISTAR_PEDIDOS,
        Accion.CONSULTAR_PEDIDO,
        Accion.CONSULTAR_HISTORIAL,
        Accion.EXPLICAR_COMO_MEDIR,
        Accion.EXPLICAR_COMO_PAGAR,
        Accion.EXPLICAR_QUE_SIGUE,
        Accion.SUGERIR_COMBINACION,
        Accion.PEDIR_COMPROBANTE,
        Accion.PEDIR_LO_QUE_FALTA,
    }
)


#: Atributos que son HECHOS DEL NEGOCIO, no de un pedido concreto.
#:
#: Cuánto cuesta el envío, de qué material es, cuánta garantía tiene: la
#: respuesta es la misma para todo el mundo, salga de la boca de quien salga.
#: Si el atributo es uno de estos, el ACTO da igual — «¿cuánto cuesta el
#: envío?» y «cuéntame del envío» merecen el mismo párrafo.
#:
#: Esto sale de medir. El modelo decía CONSULTAR·ENVIO·COSTO_ENVIO donde la
#: etiqueta ponía PREGUNTAR, y la tabla lo mandaba a consultar un pedido. Las
#: dos lecturas eran razonables y la rígida era la tabla, no el modelo:
#: exigir que acertara el verbo Y el sustantivo Y el atributo multiplica por
#: tres las formas de fallar sin ganar nada.
HECHOS_DEL_NEGOCIO: dict[Atributo, Accion] = {
    Atributo.MATERIAL: Accion.RESPONDER_DUDA,
    Atributo.GARANTIA: Accion.RESPONDER_DUDA,
    Atributo.COSTO_ENVIO: Accion.RESPONDER_DUDA,
    Atributo.CONTRAENTREGA: Accion.RESPONDER_DUDA,
    Atributo.TIEMPO: Accion.RESPONDER_DUDA,
    Atributo.COLOR_DISPONIBLE: Accion.RESPONDER_DUDA,
    Atributo.MEDIOS_DE_PAGO: Accion.EXPLICAR_COMO_PAGAR,
    Atributo.COMO_MEDIR: Accion.EXPLICAR_COMO_MEDIR,
    Atributo.VALOR: Accion.RESPONDER_DUDA,
    Atributo.CONFIANZA: Accion.RESPONDER_DUDA,
    Atributo.AJUSTE: Accion.RESPONDER_DUDA,
}

#: Atributos que solo puede saber el negocio, nunca la clienta.
#:
#: Nadie «informa» en qué estado está su propio pedido: eso solo lo sabemos
#: nosotros. Cuando el modelo dice INFORMAR sobre uno de estos, se equivocó de
#: verbo y acertó todo lo demás — que es el fallo más común de un modelo
#: pequeño, y el más fácil de arreglar sin tocarlo.
SOLO_LOS_SABEMOS_NOSOTROS: frozenset[Atributo] = frozenset(
    {
        Atributo.ESTADO,
        Atributo.SALDO,
        Atributo.TOTAL,
        Atributo.FECHA,
    }
)

#: Entidades sobre las que la clienta no puede informar nada: solo pedirlas.
SOLO_SE_PIDEN: frozenset[Entidad] = frozenset({Entidad.IMAGEN})


def planificar(
    acto: Acto,
    entidad: Entidad,
    atributo: Atributo,
    *,
    trae_datos: bool = False,
    hay_proceso: bool = False,
) -> Accion:
    """(acto, entidad, atributo) -> una acción. Sin sorpresas y sin defaults raros.

    Busca de lo más específico a lo más general. Si nada encaja, devuelve
    NO_ENTENDI, que ofrece una persona — el único final honesto cuando el
    sistema no sabe qué le están pidiendo.

    `trae_datos` dice si el mensaje traía información aprovechable (un color,
    una talla, un nombre). Es lo que distingue «¿lo tienen en rosado?» de
    «que sea rosado», que para el modelo se parecen mucho.
    """
    # 1. Un hecho del negocio se contesta igual lo pregunte quien lo pregunte.
    #    Va PRIMERO, antes que el acto, y por eso perdona que el modelo dude
    #    entre PREGUNTAR y CONSULTAR: la respuesta es la misma.
    #
    #    PERO NO si el mensaje trae datos. Una respuesta de FAQ nunca necesita
    #    un color ni una talla: si vienen, la clienta está DANDO información,
    #    no pidiéndola. Sin esta salvedad, «corazón rojo dedos blancos» salía
    #    con atributo COLOR_DISPONIBLE y el bot contestaba el párrafo de «no
    #    manejamos dorado» en vez de anotar los colores. Lo encontró la
    #    medición: cuatro de once fallos eran esta regla mordiéndose la cola.
    if (
        atributo in HECHOS_DEL_NEGOCIO
        and not trae_datos
        and acto not in (Acto.CANCELAR, Acto.HUMANO)
    ):
        return HECHOS_DEL_NEGOCIO[atributo]

    # 2. «Informar» algo que solo sabemos nosotros es consultarlo.
    #    «Ya está listo mi anillo» suena a afirmación y es una pregunta.
    if acto is Acto.INFORMAR and (
        atributo in SOLO_LOS_SABEMOS_NOSOTROS or entidad in SOLO_SE_PIDEN
    ):
        acto = Acto.CONSULTAR

    # 2b. HABLAR DEL PASADO ES CONSULTAR EL HISTORIAL, diga el verbo que diga.
    #    «Ya me habías despachado el rosado» suena a INFORMAR y es preguntar
    #    por un pedido. Nunca abre una compra ni mueve un pago: solo lee.
    if atributo is Atributo.HISTORIAL and acto not in (
        Acto.COMPRAR,
        Acto.CANCELAR,
        Acto.HUMANO,
    ):
        return Accion.CONSULTAR_HISTORIAL

    # 3. NO ENTENDER CON UNA COMPRA A MEDIAS NO ES NO ENTENDER.
    #
    #    Si estábamos escogiendo colores y llega algo indescifrable, la
    #    respuesta útil no es «no te entendí, ¿te paso con alguien?»: es
    #    volver a lo que estábamos y preguntarlo de otra manera. El guardián
    #    de repeticiones se encarga de que la segunda vez suene distinta y de
    #    que a la tercera aparezca una persona.
    #
    #    Sin esto, un «mmm» dejaba la compra tirada. Y la clienta que tiene
    #    que volver a empezar casi nunca vuelve.
    if acto is Acto.OTRO and hay_proceso:
        return Accion.PEDIR_LO_QUE_FALTA

    for clave in (
        (acto, entidad, atributo),
        (acto, entidad, None),
        (acto, None, None),
    ):
        accion = _MAPA.get(clave)
        if accion is not None:
            return accion

    return Accion.PEDIR_LO_QUE_FALTA if hay_proceso else Accion.NO_ENTENDI


def acciones_alcanzables() -> set[Accion]:
    """Las acciones a las que la tabla puede llegar. Lo usan los tests.

    Una acción inalcanzable es código que nunca corre y que nadie sabe que no
    corre; una que falta en el mapa es una petición que siempre cae en
    NO_ENTENDI.
    """
    return set(_MAPA.values())
