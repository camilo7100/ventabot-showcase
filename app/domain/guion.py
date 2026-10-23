"""EL GUION: qué dice el bot, en qué orden y por qué. TODO ES DATO EDITABLE.

════════════════════════════════════════════════════════════════════════════
SI SOLO VAS A LEER UN ARCHIVO DEL PROYECTO, QUE SEA ESTE
════════════════════════════════════════════════════════════════════════════

Aquí está la conversación entera. Para cambiar lo que dice el bot, cambia el
texto de abajo y ya: no hay que tocar el grafo, ni los nodos, ni los tests.
Para cambiar el ORDEN de las preguntas, mueve una línea en `ORDEN`. Eso es
todo lo que hay que hacer.

Cada texto es una plantilla con `{huecos}`. Los huecos se rellenan con números
que calculó Python —nunca el modelo—, así que un precio en pantalla no puede
ser un precio inventado.

────────────────────────────────────────────────────────────────────────────
POR QUÉ EL ORDEN ES ESTE
────────────────────────────────────────────────────────────────────────────
El negocio tiene un número que duele: 1.200 conversaciones al mes, 50 ventas.
De cada 24 personas que escriben, 23 se van.

En las conversaciones reales se ve dónde se van. Es aquí:

    Lía:     ¿Sabes tu talla de anillo o te comparto la guía?
    Clienta: no sé mi talla
    Lía:     [manda la guía: consigue un anillo y una regla]
    ...silencio...

La clienta está en la calle, en el bus, en el trabajo. No tiene un anillo ni
una regla a la mano. Dice "ahorita lo hago" y no vuelve. Es el único paso de
toda la conversación que exige objetos físicos, y estaba puesto ANTES de
pedir la plata.

Así que el guion invierte eso:

    1. ELIGE cuántas huellitas       (un toque)
    2. DISEÑA colores y grabado      (escribe dos palabras; es la parte
                                      divertida y la que la hace sentir que
                                      el anillo ya es suyo)
    3. CONFIRMA y ABONA              (aquí ya está enganchada)
    4. TALLA                         (con calma, con el pedido ya pagado;
                                      si se demora dos días no se pierde
                                      nada, porque ya hay abono)

No se le pide un peso hasta que ha diseñado su anillo, y no se le pide un
esfuerzo físico hasta que ya pagó.

────────────────────────────────────────────────────────────────────────────
POR QUÉ EL MOMENTO DEL ABONO DICE LO QUE DICE
────────────────────────────────────────────────────────────────────────────
Pedir $60.000 por transferencia a una desconocida de Instagram es el momento
de máxima desconfianza de toda la conversación. El mensaje de ese paso está
construido para responder, sin que ella tenga que preguntarlas, las tres
dudas que aparecen una y otra vez en las conversaciones reales:

  «¿y si no me llega?»      -> se le explica que el abono existe justo para
                               que vea fotos ANTES de pagar el resto. Es el
                               argumento de Lía, con sus palabras.
  «¿será plata de verdad?»  -> plata Ley 925, contramarcada, 6 meses de
                               garantía. Dicho ANTES de pedir el dinero.
  «¿y cuándo me llega?»     -> la fecha, y qué pasa exactamente después.

Ninguna de esas frases es un adorno: cada una es una objeción real que hoy
Lía contesta a mano, una por una, y que aquí se contesta antes de que exista.

────────────────────────────────────────────────────────────────────────────
CÓMO EDITARLO
────────────────────────────────────────────────────────────────────────────
· Cambiar lo que dice        -> edita el texto en TEXTOS
· Cambiar el orden           -> mueve una línea en ORDEN
· Agregar una pregunta nueva -> agrega un Paso, su texto y su línea en ORDEN
· Cambiar los botones        -> edita OPCIONES

Los tests comprueban que cada paso tenga texto, que los huecos existan y que
el orden no deje ningún dato sin pedir. Si rompes algo, te avisa CI, no una
clienta.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from app.domain.faq import datos_para_transferir
from app.domain.personalizacion import MAX_GRABADOS, Personalizacion


class Paso(str, Enum):
    """Cada momento de la conversación. El orden real lo manda `ORDEN`."""

    #: Aún no eligió cuántas huellitas.
    ELEGIR_PRODUCTO = "ELEGIR_PRODUCTO"
    #: Falta el color de alguna huellita.
    COLORES = "COLORES"
    #: Faltan los nombres del grabado.
    GRABADO = "GRABADO"
    #: Ya está todo el diseño: se le muestra y se le pide el abono.
    CONFIRMAR_Y_ABONAR = "CONFIRMAR_Y_ABONAR"
    #: Abono recibido. Ahora sí, la talla.
    TALLA = "TALLA"
    #: No falta nada: a producción.
    LISTO = "LISTO"


#: EL ORDEN DE LA CONVERSACIÓN. Mover una línea aquí cambia el flujo entero.
#:
#: Ojo con TALLA: está DESPUÉS de CONFIRMAR_Y_ABONAR a propósito (ver arriba).
#: Si algún día se quiere volver al orden de antes, se sube esta línea y el
#: sistema entero obedece — el bot, los tests y el panel.
ORDEN: tuple[Paso, ...] = (
    Paso.ELEGIR_PRODUCTO,
    Paso.COLORES,
    Paso.GRABADO,
    Paso.CONFIRMAR_Y_ABONAR,
    Paso.TALLA,
)

#: Pasos que solo se piden cuando el abono YA está pagado. Es una lista, no un
#: `if` escondido en un nodo: se ve de un vistazo qué se cobra por adelantado.
DESPUES_DEL_ABONO: frozenset[Paso] = frozenset({Paso.TALLA})


@dataclass(frozen=True)
class Opcion:
    """Un botón. `id` es lo que viaja; `titulo` es lo que la clienta ve."""

    id: str
    titulo: str
    descripcion: str = ""


TEXTOS: dict[Paso, str] = {
    Paso.ELEGIR_PRODUCTO: (
        "🎀 *Anillo personalizado huellita* 💍 🐾\n\n"
        "✨ Elaborado en Plata Ley 925 y circones.\n"
        "📏 Se fabrica en tu medida.\n"
        "🎨 Escoge el color que quieras para cada huellita.\n"
        "🖊️ Puedes grabar hasta {max_grabados} nombres de tus peluditos "
        "🐱🐶 al interior del anillo.\n\n"
        "¿Cuántas huellitas te gustaría llevar? 🥰"
    ),
    Paso.COLORES: (
        "¡Me encanta! 💕\n\n"
        "Estos son los colores de circón que manejamos 🩵🩷\n\n"
        "Para la *huellita {numero}*, ¿de qué color quieres el "
        "*corazón* y de qué color los *deditos*?\n\n"
        "_Por ejemplo: «corazón lila y dedos morados»_"
    ),
    Paso.GRABADO: (
        "¡Quedó divina! 🥹\n\n"
        "¿Qué nombre grabamos al interior del aro? 🐶🐱\n\n"
        "_Puedes poner hasta {max_grabados} nombres._"
    ),
    Paso.CONFIRMAR_Y_ABONAR: (
        "Te confirmo tu anillo 💍\n\n"
        "{resumen}\n\n"
        "*Total: {total}*\n"
        "Para iniciar la fabricación solo necesitas abonar *{anticipo}* 💰\n"
        "El saldo de {saldo} lo cancelas cuando esté listo.\n\n"
        "⏳ Tiempo de fabricación: {dias} a {dias_max} días calendario.\n\n"
        "💓 *Por qué solo el abono:* no manejamos contraentrega en joyas "
        "personalizadas, así que trabajamos con abono para que puedas ver "
        "*fotos de cómo quedó tu anillo* y solo después, con más confianza, "
        "cancelar el saldo.\n\n"
        "✨ Plata Ley 925 garantizada, contramarcada, con *6 meses de "
        "garantía* por defectos de fabricación.\n\n"
        "🚚 El envío nacional cuesta {envio_contraentrega} por Coordinadora "
        "y lo cancelas al recibir tu anillo."
    ),
    Paso.TALLA: (
        "¡Recibido! 🥳 Ya tomé tu pedido *{codigo}*.\n\n"
        "Solo me falta un dato para empezar: *tu talla* 💍\n\n"
        "Si la sabes, me la escribes. Si no, con un anillo que conserve su "
        "forma redonda y una regla, lo mides en toda la mitad del anillo y "
        "me mandas la foto — yo te reviso qué talla sería 😊\n\n"
        "_Sin afán: tu pedido ya está apartado._"
    ),
    Paso.LISTO: (
        "¡Perfecto {nombre}! 🫶🏻\n\n"
        "Ya tomé tu pedido *{codigo}*. Tan pronto esté listo "
        "({dias}-{dias_max} días o antes), te comparto las fotos de cómo "
        "quedó tu anillo, y tomamos tus datos para el envío 🙌🏻💓\n\n"
        "¡Mil gracias por tu confianza! ❣️ Te va a encantar ✨"
    ),
}

#: Botones por paso. Solo donde hay opciones cerradas: los colores son 14 y
#: WhatsApp no deja mostrar tantos, así que ahí se manda la foto del
#: muestrario y se lee lo que escriba (ver `app.domain.colores_texto`).
OPCIONES: dict[Paso, tuple[Opcion, ...]] = {
    Paso.ELEGIR_PRODUCTO: (
        Opcion("ANI-HUE-1", "1 huellita", "$200.000"),
        Opcion("ANI-HUE-2", "2 huellitas", "$250.000"),
        Opcion("ANI-HUE-3", "3 huellitas", "$300.000"),
    ),
    Paso.GRABADO: (Opcion("SIN_GRABADO", "Sin grabado", "El aro va liso"),),
}

#: Imagen que acompaña al paso. La clave es un nombre lógico; a qué archivo o
#: `media_id` de WhatsApp corresponde se resuelve en el adaptador del canal.
#: El dominio no sabe de archivos, y por eso esto sigue siendo dominio.
IMAGENES: dict[Paso, str] = {
    Paso.ELEGIR_PRODUCTO: "catalogo_anillo",
    Paso.COLORES: "muestrario_circones",
}


# ══════════════════════════════════════════════════════════════════════════
#  AVISOS: lo que el bot le escribe a la clienta cuando Lía mueve el pedido
# ══════════════════════════════════════════════════════════════════════════
#
# Esto es lo que convierte el panel en una herramienta de VENTA y no en una
# lista de tareas. Lía toca «Ya quedó listo» en el celular y la clienta recibe
# el cobro del saldo en el mismo segundo, sin que nadie escriba nada.
#
# En la operación de hoy ese aviso lo escribe Lía a mano, uno por uno, cuando
# se acuerda. Cada día de retraso ahí es un día más de plata sin cobrar sobre
# un anillo que ya se fabricó y ya se pagó en material.
#
# NO todos los estados avisan. Los que no están en esta tabla se mueven en
# silencio, y está bien: a la clienta no le importa la diferencia entre
# «producción lista» y «esperando saldo», que para nosotros son dos estados y
# para ella es un solo momento.
#
# PARA EDITAR UN AVISO: cambia el texto. Para que un estado deje de avisar,
# bórralo de aquí. Para que uno nuevo avise, agrégalo. Nada más.

AVISOS: dict[str, str] = {
    "EN_PRODUCCION": (
        "¡Buenas noticias! 🥳 Tu anillo *{codigo}* ya entró al taller.\n\n"
        "Te escribo apenas esté listo para mostrarte cómo quedó 💍✨"
    ),
    # El de Lía, palabra por palabra (Camilo, 20/09). Los datos de envío se
    # piden AQUÍ, no al principio: es cuando ella los manda junto con la
    # transferencia del saldo. Ver `AVISO_LISTO_PARTE_2`, que va después de
    # las fotos.
    "ESPERANDO_SALDO": (
        "Hola 🌷\n"
        "¡Tu anillo ya está listo! ✨\n\n"
        "Te compartimos la foto, gracias por tu paciencia y por confiar en "
        "nuestro trabajo, para nosotros es un honor crear piezas tan "
        "especiales. 🫶\n\n"
        "Para poder hacer el envío, por favor regálanos los siguientes "
        "datos:\n\n"
        "📍 Ciudad:\n"
        "🙋‍♀️ Nombre completo:\n"
        "🪪 Cédula:\n"
        "📱 Celular:\n"
        "🏡 Dirección completa con barrio y nomenclatura:\n\n"
        "El valor del envío nacional es de {envio_del_mensaje} 🚚 Si deseas "
        "incluirlo en la transferencia del restante del anillo."
    ),
    # La guía es obligatoria para despacharlo y va aquí: es lo primero que
    # ella quiere para saber por dónde va su anillo (Camilo, 29/09).
    "DESPACHADO": (
        "¡Tu anillo va en camino! 🚚💓\n\n"
        "Pedido *{codigo}* despachado por {transportadora}.\n"
        "Número de guía: *{guia}*\n"
        "Recuerda que el envío ({envio_contraentrega}) se cancela al recibir.\n\n"
        "¡Gracias por tu confianza! Cuéntame cuando te llegue 🥰"
    ),
}

#: La segunda mitad del aviso del anillo terminado: va DESPUÉS de las fotos,
#: porque el número tiene que llegar cuando ella ya vio su anillo, no antes.
#: Si va sola —sin la parte 1 y sin fotos— no tiene sentido: por eso el pedido
#: no puede pasar a ESPERANDO_SALDO sin fotos (`SinFotosDelAnillo`).
AVISO_LISTO_PARTE_2 = (
    "*Pedidos que cancelen el día de hoy, mañana estaremos compartiendo las "
    "guías de envío.*\n\n"
    "El valor restante de tu anillo es de {saldo_con_envio} con envío incluido "
    "o {saldo} sin envío (puedes pagarlo contraentrega).\n\n"
    "Puedes realizar el pago por:\n{datos_de_pago}"
)

#: Para quien pidió pagar el envío POR ADELANTADO (no está en casa, que se lo
#: dejen en portería): va con el saldo, sin la opción de «sin envío» — lo que se
#: acordó con ella es no pagar nada al recibir (Camilo, 21/09).
AVISO_LISTO_PARTE_2_ENVIO_INCLUIDO = (
    "*Pedidos que cancelen el día de hoy, mañana estaremos compartiendo las "
    "guías de envío.*\n\n"
    "El valor restante de tu anillo es de {saldo_con_envio} con el envío "
    "incluido, como lo acordamos 🚚 Así no tienes que pagar nada al recibirlo.\n\n"
    "Puedes realizar el pago por:\n{datos_de_pago}"
)

#: Lo mismo para quien lo RECOGE: ni envío ni guías, solo el saldo.
AVISO_LISTO_PARTE_2_RECOGE = (
    "El valor restante de tu anillo es de {saldo}.\n\n"
    "Puedes realizar el pago por:\n{datos_de_pago}\n\n"
    "Apenas me confirmes, lo puedes pasar a recoger 🥰"
)

#: Los mismos avisos cuando la clienta lo RECOGE en Floridablanca: nada de
#: «lo llevo a Coordinadora» ni «va en camino» (Camilo, 19/09).
AVISOS_RECOGE: dict[str, str] = {
    "ESPERANDO_SALDO": (
        "Hola 🌷\n"
        "¡Tu anillo ya está listo! ✨\n\n"
        "Te compartimos la foto, gracias por tu paciencia y por confiar en "
        "nuestro trabajo, para nosotros es un honor crear piezas tan "
        "especiales. 🫶"
    ),
    "DESPACHADO": (
        "¡Tu anillo ya te está esperando! 💍💓\n\n"
        "Pedido *{codigo}* listo para recoger en {punto_de_recogida} 🐾\n\n"
        "Avísame cuándo puedes pasar y te lo dejo listo en la portería del "
        "conjunto 🥰"
    ),
}

#: Los avisos que cambian cuando el envío se paga JUNTO CON EL SALDO: ni «si
#: deseas incluirlo» (ya se acordó) ni «el envío se cancela al recibir» (ya
#: lo pagó). Decirle lo segundo es cobrarle dos veces (21/09).
AVISOS_ENVIO_CON_SALDO: dict[str, str] = {
    "ESPERANDO_SALDO": (
        "Hola 🌷\n"
        "¡Tu anillo ya está listo! ✨\n\n"
        "Te compartimos la foto, gracias por tu paciencia y por confiar en "
        "nuestro trabajo, para nosotros es un honor crear piezas tan "
        "especiales. 🫶\n\n"
        "Para poder hacer el envío, por favor regálanos los siguientes "
        "datos:\n\n"
        "📍 Ciudad:\n"
        "🙋‍♀️ Nombre completo:\n"
        "🪪 Cédula:\n"
        "📱 Celular:\n"
        "🏡 Dirección completa con barrio y nomenclatura:\n\n"
        "Como lo acordamos, el envío ({envio_del_mensaje}) va incluido en la "
        "transferencia del restante del anillo 🚚"
    ),
    "DESPACHADO": (
        "¡Tu anillo va en camino! 🚚💓\n\n"
        "Pedido *{codigo}* despachado por {transportadora}.\n"
        "Número de guía: *{guia}*\n"
        "El envío ya quedó pago con tu saldo: no tienes que pagar nada al "
        "recibirlo.\n\n"
        "¡Gracias por tu confianza! Cuéntame cuando te llegue 🥰"
    ),
}

#: Dónde consignar. Sale de `faq.CUENTAS`, que es la fuente única.
#:
#: Antes estaba escrito aquí a mano Y otra vez en la FAQ. Dos copias de un
#: número de cuenta es la clase de cosa que un día se cambia en un sitio y no
#: en el otro, y entonces una clienta transfiere adonde ya no hay nadie.
DATOS_DE_PAGO = datos_para_transferir()


# ── Plantillas aprobadas por Meta ────────────────────────────────────────
#
# WhatsApp solo deja escribir texto libre dentro de las 24 h siguientes al
# último mensaje de la clienta. Pasado eso, exige una PLANTILLA que Meta haya
# revisado y aprobado a mano (tarda entre unas horas y dos días).
#
# Como la fabricación son 10-15 días, la ventana está CERRADA casi siempre
# justo cuando hay que mandar el mensaje que más importa: el cobro del saldo.
# Sin plantilla, ese cobro se queda esperando a que ella escriba primero.
#
# Cada entrada dice: cómo se llama la plantilla en Meta, y qué valores van en
# sus {{1}}, {{2}}… EN ORDEN. El orden es el del `params`, y tiene que ser el
# mismo con el que se registró la plantilla o Meta manda los datos cambiados
# de sitio: el código del pedido donde va el monto.
#
# El texto EXACTO que hay que pegar en el panel de Meta lo imprime:
#     vb plantillas
#
# Mientras Meta no las apruebe, no pasa nada malo: el mensaje se queda en la
# outbox y sale en cuanto la clienta escriba. Con plantilla, sale ya.

PLANTILLAS_META: dict[str, tuple[str, tuple[str, ...]]] = {
    "EN_PRODUCCION": ("pedido_en_produccion", ("codigo",)),
    "ESPERANDO_SALDO": ("pedido_listo_cobro_saldo", ("codigo", "saldo")),
    "DESPACHADO": ("pedido_despachado", ("codigo",)),
}

#: El cuerpo que hay que registrar en Meta, con sus {{1}}, {{2}}.
#:
#: Se escribe aquí, al lado del texto libre, para que nadie cambie uno y se
#: olvide del otro: la clienta recibiría dos mensajes distintos según la hora
#: a la que Lía tocara el botón. Un test comprueba que los dos digan lo mismo
#: en lo que importa (el monto, el código, el flete aparte).
CUERPOS_META: dict[str, str] = {
    "pedido_en_produccion": (
        "¡Buenas noticias! 🥳 Tu anillo {{1}} ya entró al taller.\n\n"
        "Te escribo apenas esté listo para mostrarte cómo quedó 💍✨"
    ),
    "pedido_listo_cobro_saldo": (
        "¡Tu anillo ya está listo! 🥹💍\n\n"
        "Pedido {{1}}. Para despacharlo solo falta el saldo de {{2}}.\n\n"
        "Escríbeme por aquí y te paso los datos para transferir 💓"
    ),
    "pedido_despachado": (
        "¡Tu anillo va en camino! 🚚💓\n\n"
        "Pedido {{1}} despachado por Coordinadora. Recuerda que el envío se "
        "cancela al recibir.\n\n"
        "¡Gracias por tu confianza! Cuéntame cuando te llegue 🥰"
    ),
}

#: Meta clasifica cada plantilla. UTILITY es "información sobre un pedido que
#: el cliente ya hizo" — se aprueba fácil y cuesta menos. MARKETING es
#: promoción, se aprueba con lupa y cuesta más. Estas son todas UTILITY, y
#: por eso NINGUNA puede ofrecer un descuento ni invitar a comprar otra cosa:
#: eso la convertiría en MARKETING y Meta la rechazaría.
CATEGORIA_META = "UTILITY"
IDIOMA_META = "es"


def plantilla_de(
    estado: str, *, recoge: bool = False, envio_con_saldo: bool = False
) -> tuple[str, tuple[str, ...]] | None:
    """La plantilla de Meta para un estado, o None si no hay una que diga la
    verdad para este pedido.

    `pedido_despachado` dice «despachado por Coordinadora» y «el envío se
    cancela al recibir». A quien ya pagó el envío con el saldo le cobraría dos
    veces, y a quien recoge le hablaría de una transportadora (visto el 29/09).
    Sin plantilla, el aviso correcto (el texto libre) espera en la outbox y sale
    en cuanto ella escriba: tarde, pero nunca falso.
    """
    if estado == "DESPACHADO" and (recoge or envio_con_saldo):
        return None
    return PLANTILLAS_META.get(estado)


def aviso(
    estado: str,
    *,
    recoge: bool = False,
    envio_con_saldo: bool = False,
    **huecos: object,
) -> str | None:
    """El mensaje para un estado, o None si ese estado se mueve en silencio."""
    from app.domain.faq import ENVIO_EN_EL_MENSAJE_COP, PUNTO_DE_RECOGIDA

    if recoge:
        especial = AVISOS_RECOGE.get(estado)
    elif envio_con_saldo:
        especial = AVISOS_ENVIO_CON_SALDO.get(estado)
    else:
        especial = None
    plantilla = especial or AVISOS.get(estado)
    if plantilla is None:
        return None
    huecos.setdefault("envio_del_mensaje", _pesos(ENVIO_EN_EL_MENSAJE_COP))
    huecos.setdefault("transportadora", "Coordinadora")
    huecos.setdefault("guia", "(te la comparto en un momento)")
    return plantilla.format(
        datos_de_pago=DATOS_DE_PAGO, punto_de_recogida=PUNTO_DE_RECOGIDA, **huecos
    )


def _pesos(valor: int) -> str:
    return f"${valor:,.0f}".replace(",", ".")


def aviso_de_cierre(
    *,
    recoge: bool,
    saldo_cop: int,
    envio_con_saldo: bool = False,
    envio_cop: int | None = None,
) -> str:
    """La segunda mitad del aviso del anillo terminado (después de las fotos).

    El «con envío incluido» sale de `ENVIO_EN_EL_MENSAJE_COP`, que hoy NO es el
    mismo número que se cotiza (`ENVIO_NACIONAL_COP`): Camilo quiso conservar
    el texto de Lía tal cual. Están los dos porque son, de verdad, dos cifras.
    """
    from app.domain.faq import ENVIO_EN_EL_MENSAJE_COP

    if recoge:
        plantilla = AVISO_LISTO_PARTE_2_RECOGE
    elif envio_con_saldo:
        plantilla = AVISO_LISTO_PARTE_2_ENVIO_INCLUIDO
    else:
        plantilla = AVISO_LISTO_PARTE_2
    return plantilla.format(
        saldo=_pesos(saldo_cop),
        # El flete del PEDIDO (el que se le cotizó); el general si no lo trae.
        saldo_con_envio=_pesos(
            saldo_cop + (envio_cop if envio_cop is not None else ENVIO_EN_EL_MENSAJE_COP)
        ),
        datos_de_pago=DATOS_DE_PAGO,
    )


def huecos_de_aviso(estado: str) -> set[str]:
    """Qué `{huecos}` necesita un aviso. Lo usan los tests y el panel."""
    import string

    plantilla = AVISOS.get(estado)
    if plantilla is None:
        return set()
    return {c for _, c, _, _ in string.Formatter().parse(plantilla) if c}


def siguiente_paso(
    personalizacion: Personalizacion,
    *,
    huellitas_esperadas: int,
    abono_pagado: bool,
) -> Paso:
    """El único lugar que decide qué se pregunta ahora. Función pura.

    Sin red, sin base de datos, sin LLM: entra el estado, sale un paso. Por
    eso se puede probar entero en microsegundos y por eso el flujo es
    reproducible — dos veces el mismo estado dan dos veces el mismo paso.

    Args:
        personalizacion: lo que la clienta ya decidió.
        huellitas_esperadas: 1, 2 o 3 según el producto. 0 = aún no eligió.
        abono_pagado: si ya entraron los $60.000.
    """
    if huellitas_esperadas <= 0:
        return Paso.ELEGIR_PRODUCTO

    falta = personalizacion.falta(huellitas_esperadas)

    for paso in ORDEN:
        # Lo que va después del abono no se pregunta antes. Esta es LA regla
        # de conversión del guion, y está aquí, en una línea, y no repartida
        # por los nodos.
        if paso in DESPUES_DEL_ABONO and not abono_pagado:
            continue

        if paso is Paso.ELEGIR_PRODUCTO:
            continue
        if paso is Paso.COLORES and "colores" in falta:
            return Paso.COLORES
        if paso is Paso.GRABADO and "grabado" in falta:
            return Paso.GRABADO
        if paso is Paso.CONFIRMAR_Y_ABONAR and not abono_pagado:
            return Paso.CONFIRMAR_Y_ABONAR
        if paso is Paso.TALLA and "talla" in falta:
            return Paso.TALLA

    return Paso.LISTO


def texto(paso: Paso, **huecos: object) -> str:
    """Rellena la plantilla del paso.

    Falla ruidosamente si falta un hueco: es preferible un error en los tests
    a mandarle a una clienta un mensaje con `{anticipo}` sin rellenar.
    """
    base = TEXTOS[paso]
    return base.format(max_grabados=MAX_GRABADOS, **huecos)


def huecos_de(paso: Paso) -> set[str]:
    """Qué `{huecos}` usa la plantilla de un paso. Lo usan los tests."""
    import string

    return {campo for _, campo, _, _ in string.Formatter().parse(TEXTOS[paso]) if campo}


#: Los avisos están escritos para UN anillo. Para la cadena (03/10) o para un
#: pedido de varias piezas se cambian las palabras, no el mensaje.
_DE_LA_CADENA: tuple[tuple[str, str], ...] = (
    ("Tu anillo", "Tu cadena"),
    ("tu anillo", "tu cadena"),
    ("del anillo", "de la cadena"),
    ("su anillo", "su cadena"),
    ("el anillo", "la cadena"),
    ("ya está listo", "ya está lista"),
    ("esté listo", "esté lista"),
)
_DEL_PEDIDO: tuple[tuple[str, str], ...] = (
    ("Tu anillo", "Tu pedido"),
    ("tu anillo", "tu pedido"),
    ("del anillo", "del pedido"),
    ("su anillo", "su pedido"),
    ("el anillo", "el pedido"),
)


def para_las_piezas(texto: str, piezas: list[str]) -> str:
    """El aviso con la pieza que es: «Tu cadena ya está lista», «Tu pedido…»."""
    if not texto or not piezas:
        return texto
    if len(piezas) == 1 and piezas[0] == "cadena":
        cambios = _DE_LA_CADENA
    elif len(piezas) > 1:
        cambios = _DEL_PEDIDO
    else:
        return texto
    for de, a in cambios:
        texto = texto.replace(de, a)
    return texto
