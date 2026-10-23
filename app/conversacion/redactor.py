"""Tramo 8: cómo suena. Textos de WhatsApp, no de formulario.

════════════════════════════════════════════════════════════════════════════
TODO ESTO SON DATOS
════════════════════════════════════════════════════════════════════════════
Para cambiar lo que dice el bot se edita el texto de abajo. No hay que tocar
el pipeline, ni el ejecutor, ni los tests. Es el mismo principio que
`guion.py`, aplicado a la conversación nueva.

Las plantillas son la respuesta POR DEFECTO, no el plan B: cuestan cero
tokens, cero latencia y no pueden decir nada falso. El modelo redacta solo
cuando se le enciende, y aun así lo que escriba pasa por `hechos.revisar()`
antes de salir.

════════════════════════════════════════════════════════════════════════════
CÓMO SE ESCRIBEN
════════════════════════════════════════════════════════════════════════════
Como escribe Lía, no como escribe un sistema. Nada de «seleccione una
opción», «proceso completado» ni «datos registrados correctamente».

Y ninguna respuesta termina en un callejón: cuando el bot no sabe algo o hace
falta decidir, la frase invita a seguir escribiendo. La conversación tiene que
poder continuar solo con texto, sin un botón que pulsar — ese es el requisito,
no una preferencia estética.
"""

from __future__ import annotations

from app.domain.acciones import Accion
from app.domain.hechos import Ficha, redactar_con_red
from app.domain.respuesta import Respuesta, Tipo
from app.domain.tallas import talla_texto
from app.domain.validacion import Decision, Veredicto

#: Un archivo adjunto: qué es, cómo se llama y qué pie lleva.
#:
#: El nombre es LÓGICO ("anillo_video_1"). Qué archivo es y bajo qué URL se
#: sirve lo resuelve el adaptador del canal, porque esa URL cambia cada vez
#: que se reinicia el túnel.
Adjunto = tuple[Tipo, str, str]


def _foto(nombre: str, pie: str = "") -> Adjunto:
    return (Tipo.IMAGEN, nombre, pie)


def _video(nombre: str, pie: str = "") -> Adjunto:
    return (Tipo.VIDEO, nombre, pie)


#: EL MATERIAL DE VENTA. Lo que se manda con cada cosa.
#:
#: ════════════════════════════════════════════════════════════════════════
#: POR QUÉ LOS VIDEOS NO SON UN EXTRA
#: ════════════════════════════════════════════════════════════════════════
#: Un anillo de plata con circones no se ve en una foto fija: se ve cuando le
#: da la luz y gira. Lía los manda a mano en cada cotización porque son lo
#: que más vende de todo el material, y el bot que no los mandaba estaba
#: enseñando menos producto que ella.
#:
#: Y las fotos de la regla van con el catálogo, no solo al final: la clienta
#: tiene que saber DESDE EL PRINCIPIO cómo se toma la medida, porque esa foto
#: es la que después lee el modelo de visión. Enseñársela cuando ya le
#: pediste la talla es tarde: para entonces ya mandó la foto mal hecha.
ADJUNTOS: dict[Accion, tuple[Adjunto, ...]] = {
    Accion.MOSTRAR_PRODUCTO: (
        _foto("anillo_ejemplo_1"),
        _video("anillo_video_1"),
        _video("anillo_video_2"),
        _foto(
            "medir_talla_guia",
            "📏 Así se toma la medida: con un anillo tuyo que conserve su "
            "forma redonda y una regla, lo mides por la mitad.",
        ),
        _foto("medir_talla_ejemplo_2", "Y así te queda la foto que me mandas 😊"),
    ),
    Accion.MOSTRAR_IMAGENES: (
        _foto("anillo_ejemplo_1"),
        _video("anillo_video_1"),
        _video("anillo_video_2"),
    ),
}

#: Lo que acompaña a cada PREGUNTA. No depende de la acción sino del hueco:
#: preguntar por los colores sin enseñar el muestrario es pedirle a la
#: clienta que adivine cuáles catorce existen.
ADJUNTOS_DEL_HUECO: dict[str, tuple[Adjunto, ...]] = {
    # Una sola: la del muestrario CON los nombres de cada color (02/10). La segunda
    # que iba era la misma foto vieja, sin nombres.
    "colores": (_foto("muestrario_circones"),),
    "color_suelto": (_foto("muestrario_circones"),),
    "media_pareja": (_foto("muestrario_circones"),),
    "talla": (
        _foto("medir_talla_guia"),
        _foto("medir_talla_ejemplo_2", "Así de fácil 😊"),
    ),
}

CATALOGO = (
    "🎀 *Anillo personalizado huellita* 💍🐾\n\n"
    "🪄 Precios según la cantidad de huellitas:\n"
    "• 1 huellita: {precio_1}\n"
    "• 2 huellitas: {precio_2}\n"
    "• 3 huellitas: {precio_3}\n\n"
    "✨ Está elaborado en Plata Ley 925 y circones.\n"
    "📏 Lo fabricamos completamente en tu medida.\n"
    "🎨 Puedes escoger el color o combinación que quieras para las huellitas.\n"
    "🖊️ También puedes grabar hasta 5 nombres de tus peluditos 🐱🐶 en el "
    "interior del anillo.\n\n"
    "💰 Para iniciar la fabricación solo necesitas abonar {abono}.\n"
    "⏳ El tiempo de fabricación es de aproximadamente {dias} a {dias_max} "
    "días calendario.\n\n"
    "Cuando esté listo 💍✨ te enviamos fotos para que veas cómo quedó. "
    "Después realizas el pago del saldo y enviamos tu pedido hasta la puerta "
    "de tu casa 🏡✨\n\n"
    "¿Te gustaría pedir el tuyo? 🥰"
)

#: Cómo se pregunta cada hueco. Nunca en el mismo orden por obligación: se
#: pregunta el que falte, y si faltan varios se elige uno y ya.
PREGUNTAS: dict[str, str] = {
    "huellitas": (
        "¡Claro que sí! 🥰 ¿Cuántas huellitas te gustaría llevar en tu anillo? "
        "Puedes elegir 1, 2 o 3 💍🐾"
    ),
    "colores": (
        "¡Me encanta! 💕 Estos son los colores de circón que manejamos 🩵🩷\n\n"
        "¿De qué color quieres el *corazón* y de qué color los *deditos*?\n\n"
        "_Por ejemplo: «corazón lila y dedos morados»_"
    ),
    #: Cuando el anillo lleva varias huellitas hay que decir de CUÁL se
    #: pregunta. Sin el número, pedir el segundo par parece que no la
    #: escucharon la primera vez, que es justo lo que enfada.
    "colores_n": (
        "¡Divina! 💕 Ahora la *huellita {n}*: ¿de qué color el *corazón* y de "
        "qué color los *deditos*?"
    ),
    "grabado": (
        "¡Quedó divina! 🥹 ¿Qué nombre grabamos al interior del aro? 🐶🐱\n\n"
        "_Puedes poner hasta 5 nombres, o decirme que lo dejemos liso._"
    ),
    #: LOS DATOS DE ENVÍO. Van DESPUÉS del anillo y ANTES del precio.
    #:
    #: Ese orden es la venta. Pedir el abono en cuanto se sabe el color se
    #: siente como que están cobrando, no atendiendo — y la clienta
    #: desconfía. Terminar de armar el pedido primero hace lo contrario:
    #: cada dato que da es una inversión suya, y para cuando llega el precio
    #: ya está dentro.
    "nombre": (
        "¡Quedó precioso! 🥹 Ya casi terminamos de armarlo.\n\n"
        "¿A nombre de quién enviamos el pedido? 💌"
    ),
    "ciudad": "¿Y a qué ciudad te lo mandamos? 🚚💕",
    "direccion": (
        "Perfecto 🥰 ¿Cuál es la dirección de entrega?\n\n"
        "_Con barrio y apartamento si aplica, para que no se pierda 🏡_"
    ),
    "talla": (
        "Ya casi 🥰 Solo me falta tu talla 💍\n\n"
        "Si la sabes, me la escribes. Si no, con un anillo que conserve su "
        "forma redonda y una regla, lo mides en toda la mitad del anillo y me "
        "mandas la foto — yo te reviso qué talla sería 😊\n\n"
        "_Y si ahorita no tienes regla, me dices «después te la mando» y "
        "seguimos igual 💕_"
    ),
}

#: Cómo se pregunta cuando la respuesta llegó A MEDIAS.
#:
#: Estas dos frases son la diferencia entre un bot y un formulario. La
#: clienta dijo «morado»; volver a soltarle «¿de qué color el corazón y de
#: qué color los deditos?» le dice que no la leyeron. Aquí se le repite lo
#: que sí se entendió y se pregunta SOLO lo que falta.
MEDIA_RESPUESTA: dict[str, str] = {
    "color_suelto": (
        "¡Divino el {color_suelto}! 😍 ¿Lo quieres en el *corazón* o en los "
        "*deditos*?\n\n_Y me dices también de qué color va la otra parte 💕_"
    ),
    "media_pareja": (
        "¡Anotado, {media_color} en {media_parte}! ✨\n\n"
        "¿Y de qué color quieres {media_falta}?"
    ),
}

#: La segunda vez NO se pregunta igual. Nunca.
#:
#: Un bot que repite el mismo párrafo tres veces es un bot que la clienta
#: cierra. La segunda vez se pregunta más corto y más concreto; la tercera se
#: ofrece una persona, porque a la tercera el problema ya no es la pregunta.
INSISTIR: dict[str, tuple[str, ...]] = {
    "pregunta:huellitas": (
        "Perdona 🙈 ¿me confirmas si lo quieres de *1*, *2* o *3* huellitas?",
        "¿Me escribes solamente el número de huellitas —1, 2 o 3— y seguimos? 💍",
    ),
    "pregunta:colores": (
        "Para no equivocarme con tu anillo 🥺 dime los dos colores así: "
        "*«corazón lila, deditos morados»* 💕",
        "¿Prefieres que te ayude una de las chicas a escoger los colores? "
        "Dime que sí y te paso con ella 💓",
    ),
    "pregunta:color_suelto": (
        "¿Ese color va en el *corazón* (la piedra grande) o en los *deditos* "
        "(los cuatro chiquitos)? 🐾",
        "Si prefieres te paso con una persona del equipo para escoger juntas "
        "los colores 💓",
    ),
    "pregunta:media_pareja": (
        "Solo me falta el color de la otra partecita 🥰 ¿cuál te gusta?",
        "¿Te paso con alguien del equipo para terminar de escoger? 💓",
    ),
    "pregunta:grabado": (
        "¿Qué nombre quieres por dentro del aro? 🐶 Si no quieres ninguno, "
        "escríbeme *«sin grabado»* y seguimos 💕",
        "Me escribes el nombre tal cual quieres que quede grabado, o "
        "*«sin grabado»* 🥰 Si prefieres, te paso con una persona 💓",
    ),
    "pregunta:nombre": (
        "¿Me confirmas el nombre de quien recibe el pedido? 💌",
        "Solo me falta el nombre para la guía de envío 🥰 ¿Me lo escribes?",
    ),
    "pregunta:ciudad": (
        "¿En qué ciudad estás? Así calculo bien el envío 🚚",
        "Me falta la ciudad para poder despacharlo 💕 ¿Cuál es?",
    ),
    "pregunta:direccion": (
        "¿Me pasas la dirección? Con barrio y apto si aplica 🏡",
        "Sin dirección no puedo despachar 🥺 ¿Me la escribes y seguimos?",
    ),
    "pregunta:talla": (
        "Me falta tu talla 💍 Si no la sabes, mándame la foto del anillo con "
        "la regla y yo te la reviso 🥰",
        # La salida de emergencia del sitio donde más ventas se pierden.
        # Quien no tiene una regla a mano no la va a conseguir por insistir:
        # o se le deja seguir, o se enfría. Y el negocio cobra el abono antes
        # de tener la talla de todas formas.
        "¿No tienes una regla a la mano? 🥺 No te preocupes: escríbeme "
        "*«después te la mando»* y seguimos con tu pedido — la talla la "
        "confirmamos mientras se fabrica 💕",
    ),
}

#: Cuando ya se insistió y sigue sin salir. Se pasa a una persona, y punto.
#:
#: No hay una cuarta forma de preguntar lo mismo: si tres no bastaron, el
#: problema no es la frase. Insistir otra vez no consigue el dato, consigue
#: que cierre el chat — y esta clienta ya escribió cuatro veces, así que
#: quiere comprar.
OFRECER_PERSONA = (
    "Si prefieres, te paso con una persona del equipo y lo terminamos juntas 💓"
)

RENDIRSE = (
    "Mejor te paso con una personita del equipo para terminar tu anillo "
    "juntas 💓 En un momentico te escribe por aquí 🥰"
)

#: Lo que se contesta cuando hace falta algo que todavía no existe.
#:
#: Antes esto caía en «no te entendí», que es mentira y además no ayuda: la
#: clienta sí se explicó, lo que pasa es que aún no hay un pedido. Decirlo tal
#: cual, y ofrecer el paso siguiente, es lo que salva la conversación.
SIN_PEDIDO = (
    "Todavía no me aparece ningún pedido tuyo 🙈\n\n"
    "¿Quieres que armemos tu anillo ahora? Me dices cuántas huellitas quieres "
    "—1, 2 o 3— y seguimos 💍🐾"
)
SIN_COMPRA = (
    "No tenemos ninguna compra a medias por ahora 🥰\n\n"
    "¿Te cuento cómo funciona el anillo de huellitas? 💍🐾"
)
SIN_DATOS = "Perdona, no alcancé a entender qué dato me diste 🙈 ¿me lo repites? 💓"

#: Un medio de pago concreto. Va con el titular SIEMPRE: es lo que la clienta
#: compara antes de darle a enviar.
CUENTA = (
    "¡Claro que sí! 🥰 Estos son los datos 💳\n\n{cuenta}\n\n"
    "Cuando hagas el pago me mandas el comprobante por aquí y seguimos 💓"
)

#: Todavía sin números reales. Se dice la verdad; NUNCA se inventa una cuenta.
CUENTA_PENDIENTE = (
    "¡Claro que sí! 🥰 Ya te paso los datos de {medio} — déjame confirmarlos "
    "con el equipo y en un momentico te los mando 💓"
)

#: Cómo se confirma que se anotó algo. Cuatro formas, no una.
#:
#: ════════════════════════════════════════════════════════════════════════
#: POR QUÉ ESTO NO ES UN CAPRICHO
#: ════════════════════════════════════════════════════════════════════════
#: Un bot que empieza CINCO mensajes seguidos con «¡Perfecto! Anoté:» se
#: delata en el tercero. La clienta deja de leer y empieza a contestar por
#: encima, y ahí se pierden los datos.
#:
#: La variedad se elige por el número de turno, no al azar: el mismo turno da
#: siempre la misma frase, así que los tests siguen siendo deterministas y un
#: fallo se puede reproducir. Aleatorio sería más «natural» y no se podría
#: depurar nunca.
ECOS: tuple[str, ...] = (
    "¡Perfecto! Anoté: {que} ✨",
    "¡Listo! Ya tengo {que} 💕",
    "Anotado: {que} 🥰",
    "¡Genial! Me guardo {que} ✨",
)

#: Lo mismo para cuando corrige algo. Nunca se le dice «anotado» a una
#: corrección: se le dice que se cambió, que es lo que ella quiere oír.
ECOS_CORRECCION: tuple[str, ...] = (
    "¡Listo, lo cambié! Queda: {que} ✨",
    "¡Corregido! Ahora es: {que} 💕",
)


def variar(opciones: tuple[str, ...], ctx) -> str:
    """Una de las formas de decirlo, elegida por el turno.

    Determinista a propósito (ver `ECOS`). Sin contexto —tests unitarios,
    camino propositivo— sale siempre la primera, que es la mejor.
    """
    turno = getattr(ctx, "turnos", 0) or 0
    return opciones[turno % len(opciones)]


#: Acciones que están armando el anillo. Todas salen por el mismo sitio:
#: se pregunta lo que falte y, cuando no falta nada, se pasa al cobro.
COMPRANDO: frozenset[Accion] = frozenset(
    {
        Accion.INICIAR_COMPRA,
        Accion.ANOTAR_DATOS,
        Accion.PEDIR_LO_QUE_FALTA,
        Accion.RETOMAR_PROCESO,
        Accion.QUITAR_DEL_PEDIDO,
        Accion.RESUMIR_Y_COBRAR_ABONO,
    }
)

#: Qué se le dice a la clienta según la foto que mandó.
#:
#: Ninguno de estos textos le cuenta que dudamos de su foto. Eso va al panel,
#: no al chat: para ella la conversación tiene que fluir, y si la talla hay
#: que confirmarla lo hace Lía antes de fabricar. Decirle «no te entendí la
#: foto» la manda a repetirla tres veces y a cansarse.
ACUSE_FOTO: dict[str, str] = {
    "MASCOTA": "¡Ay, qué belleza! 😍🐾 Va a quedar divina en tu anillo 💍",
    "ANILLO_CON_REGLA": (
        "¡Gracias por la foto! 📸 Ya la tengo, la reviso con calma para "
        "tomarte bien la medida 💍"
    ),
    "CIRCONES_SENALADOS": (
        "¡Recibí tu foto del muestrario! 💕 Para no equivocarme con tu anillo, "
        "¿me escribes el color tal cual lo quieres?"
    ),
    "OTRA": "¡Gracias, ya me llegó tu foto! 💕",
}

#: Qué se le dice al recibir un comprobante, según de qué pago sea.
#:
#: El mismo texto para los dos era un error visible: «pasamos tu pedido a
#: producción» cuando lo que acaba de pagar es el saldo de un anillo YA HECHO
#: la deja pensando que empieza otra vez.
COMPROBANTE_DE: dict[str, str] = {
    "abono": (
        "¡Recibí tu comprobante! 🥹 Muchas gracias 💕\n\n"
        "Lo estamos verificando y apenas quede confirmado pasamos tu pedido "
        "*{codigo}* al taller 💍✨\n\n"
        "⏳ Te escribo en cuanto esté listo para mandarte las fotos."
    ),
    "saldo": (
        "¡Recibí tu comprobante! 🥹 Muchas gracias 💕\n\n"
        "Lo verificamos y despachamos tu pedido *{codigo}* por Coordinadora "
        "🚚 Recuerda que el envío se cancela al recibirlo.\n\n"
        "¡Ya casi lo tienes en tus manos! ✨"
    ),
}

#: Cómo se ofrecen las tres combinaciones.
#:
#: Termina SIEMPRE devolviéndole la decisión. Una sugerencia que suena a
#: decisión tomada se lleva puesto lo que la clienta quería y encima la deja
#: sin ganas de corregir.
SUGERENCIAS = (
    "¡Claro que sí, con muchísimo gusto! 🥰\n\n"
    "Te muestro tres que quedan divinas 👇\n\n"
    "{opciones}\n\n"
    "Dime cuál te gusta —«la elegante», «la segunda»— y seguimos 💕\n\n"
    "_Y si prefieres otra combinación, me la escribes tal cual y la hacemos: "
    "tenemos 14 colores para escoger 🎨_"
)

#: El pie de la foto de SU anillo. Corto: la foto habla sola.
PIE_DE_VISTA = "Así se te va a ver 😍💍"

#: «¿Y ahora qué hago?», contestado según dónde esté el pedido.
QUE_SIGUE: dict[str, str] = {
    "abono": (
        "¡Ya está todo listo de tu parte! 🥰\n\n"
        "Solo falta el abono de *{cuanto}* para que tu anillo entre al "
        "taller 💍\n\n{cuentas}\n\n"
        "Cuando lo hagas me mandas el comprobante por aquí y arrancamos 💓"
    ),
    "saldo": (
        "¡Tu anillo ya está listo! 🥹💍\n\n"
        "Para despacharlo solo falta el saldo de *{cuanto}*.\n\n{cuentas}\n\n"
        "Apenas me mandes el comprobante lo llevo a Coordinadora 🚚"
    ),
    "nada": (
        "¡Ya no tienes que hacer nada más! 🥰 Tu pedido *{codigo}* está: "
        "{estado} 💓\n\nTe escribo apenas haya novedades ✨"
    ),
}

TEXTOS: dict[Accion, str] = {
    Accion.SALUDAR: (
        "¡Hola! 🥰 Bienvenida a Luna Joyas 💍✨\n\n"
        "Hacemos anillos personalizados con las huellitas de tus peluditos, en "
        "Plata Ley 925 🐾\n\n"
        "¿Te cuento cómo funciona?"
    ),
    Accion.CHARLAR: "¡Con mucho gusto! 🥰 Cualquier cosa me escribes por aquí 💓",
    Accion.NO_ENTENDI: (
        "Ay, no te entendí bien 🙈 ¿Me lo dices de otra forma?\n\n"
        "También puedo pasarte con una persona del equipo si prefieres 💓"
    ),
    Accion.LLAMAR_HUMANO: (
        "¡Claro que sí! 🥰 Ya le paso tu mensaje a una persona del equipo, en "
        "un momentico te escribe 💓"
    ),
    Accion.EXPLICAR_COMO_MEDIR: "",  # sale literal de la ficha
    Accion.RESPONDER_DUDA: "",
    Accion.EXPLICAR_COMO_PAGAR: "",
    Accion.MOSTRAR_IMAGENES: (
        "¡Claro! 🥰 Mira algunos ejemplos de cómo puede quedar tu anillo 💍🐾"
    ),
    Accion.CONSULTAR_PEDIDO: (
        "Tu pedido *{codigo}* está: {estado} 💓\n\n"
        "Total {total} · te queda por pagar {debe}"
    ),
    Accion.RECIBIR_COMPROBANTE: (
        "¡Recibí tu comprobante! 🥹 Muchas gracias 💕\n\n"
        "Lo estamos verificando y te confirmo en cuanto quede listo 💓"
    ),
    Accion.REGISTRAR_PAGO_REPORTADO: (
        "¡Gracias! 🥹 Para confirmarlo y seguir con tu pedido *{codigo}*, "
        "¿me compartes el comprobante por aquí? 💓"
    ),
    Accion.PEDIR_CANCELACION: (
        "Entiendo 🥺 Déjame pasarle tu mensaje a una persona del equipo para "
        "que revise tu pedido *{codigo}* y te ayude, ¿va? 💓"
    ),
    Accion.RESUMIR_Y_COBRAR_ABONO: (
        "¡Listo! Te confirmo tu anillo 💍\n\n"
        "{diseno}\n\n"
        "*Total: {total}*\n"
        "Para iniciar la fabricación solo necesitas abonar *{abono}* 💰\n"
        "El saldo de {saldo} lo cancelas cuando esté listo.\n\n"
        "⏳ Fabricación: {dias} a {dias_max} días calendario.\n\n"
        "💓 No manejamos contraentrega en joyas personalizadas, así que "
        "trabajamos con abono para que puedas ver *fotos de cómo quedó tu "
        "anillo* y solo después, con más confianza, cancelar el saldo.\n\n"
        "✨ Plata Ley 925 garantizada, contramarcada, con *6 meses de "
        "garantía* por defectos de fabricación.\n\n"
        "🚚 El envío nacional cuesta {envio} y lo cancelas al recibirlo.\n\n"
        "Cuando quieras me dices y te paso los datos para el abono — sin "
        "prisa, y cualquier cosa que quieras cambiar me la escribes 💕"
    ),
}

#: Cuando hay que elegir entre varios. Se nombran, nunca se numera a secas:
#: «¿cuál?» obliga a la clienta a repetir todo lo que ya dijo.
ELEGIR = (
    "¡Claro! 🥰 Veo que tienes varios pedidos. ¿Me dices cuál?\n\n"
    "{opciones}\n\n"
    "_Puedes decirme, por ejemplo, «el primero» o «el del anillo»._"
)

#: ════════════════════════════════════════════════════════════════════════
#: EL HISTORIAL: pedidos del pasado, a petición de la clienta
#: ════════════════════════════════════════════════════════════════════════
#: Solo LEEN. Ninguno ofrece pagar ni cambiar nada: un pedido cerrado ya no
#: recibe cambios desde el chat.
HISTORIAL_UNO = (
    "¡Claro! 🥰 Encontré tu pedido *{codigo}*, del {fecha} 💍\n\n"
    "Está: {estado}{movimiento}"
)
HISTORIAL_VARIOS = (
    "¡Con gusto! 🥰 Estos son tus pedidos:\n\n{lista}\n\n"
    "¿De cuál quieres saber más? Me dices, por ejemplo, «el segundo» 💓"
)
HISTORIAL_NINGUNO = (
    "Mmm, no encuentro un pedido tuyo con esos datos 🙈\n\n"
    "¿Me das alguna pista más, como el mes en que lo pediste o el código "
    "(empieza por *PED-*)? 💓"
)
HISTORIAL_VACIO = (
    "Todavía no me aparece ningún pedido tuyo anterior 🙈 ¿Quieres que te "
    "cuente cómo pedir el tuyo? 💍"
)

#: Un cambio que el bot NO puede aplicar solo: el anillo ya está pagado o en
#: fabricación. No se promete nada: se pasa a una persona con la petición.
CAMBIO_PARA_PERSONA = (
    "Tu anillo *{cambio_para_persona}* ya está {estado_pedido} 🥺 así que ese "
    "cambio lo tiene que revisar una persona del equipo antes de tocar nada.\n\n"
    "Ya le dejé tu mensaje y te escriben por aquí en un momentico 💓"
)
CAMBIO_VARIOS = (
    "¡Claro! 🥰 Como tienes varios pedidos activos, le paso tu cambio a una "
    "persona del equipo para aplicarlo en el correcto y te confirman por aquí 💓"
)
#: Se vuelve a una compra de antes sin que se la acabemos de preguntar.
RETOMADA = (
    "Retomo el anillo que estabas armando 💕 _(si prefieres empezar uno nuevo, "
    "escríbeme «empecemos de cero»)_"
)
#: «Quiero cambiar la talla», sin decir cuál.
TALLA_NUEVA = (
    "¡Claro que sí! 💍 ¿Qué talla quieres{para}?\n\n"
    "Si no la sabes, mándame la foto de un anillo tuyo sobre una regla y yo te "
    "la reviso 😊"
)

VARIOS_PEDIDOS = (
    "¡Con gusto! 🥰 Estos son tus pedidos:\n\n{lista}\n\n¿De cuál quieres saber más? 💓"
)


#: La clave de una pregunta es «pregunta:<hueco>». Se escribe una sola vez.
PREFIJO_PREGUNTA = "pregunta:"


def _del_hueco(clave: str) -> tuple[Adjunto, ...]:
    """Los adjuntos que acompañan a una pregunta, por su clave."""
    if not clave.startswith(PREFIJO_PREGUNTA):
        return ()
    return ADJUNTOS_DEL_HUECO.get(clave[len(PREFIJO_PREGUNTA) :], ())


def _mostrar_vistas(r: Respuesta, ficha: Ficha) -> None:
    """Las previsualizaciones que haya en la ficha, en orden.

    Van SIEMPRE, sin pasar por el guardián de repeticiones: no son material
    de catálogo que ya tiene arriba, son la foto de SU anillo con los colores
    que acaba de escoger. Si cambia un color, la foto es otra.
    """
    # La foto de SU anillo solo cuando acaba de cambiar algún color, o
    # cuando ya está todo y toca el resumen. Mandarla en cada mensaje —
    # también al anotar la talla o el grabado— la convierte en ruido.
    recien = ficha.datos.get("recien") or ""
    if (vista := ficha.datos.get("vista")) and (
        "colores" in recien or not ficha.datos.get("falta")
    ):
        r.mostrar(vista, pie=PIE_DE_VISTA)
    for n in (1, 2, 3):
        if nombre := ficha.datos.get(f"vista_{n}"):
            r.mostrar(nombre, pie=ficha.datos.get(f"combo_{n}", "").split(" — ")[0])


def _adjuntar(
    r: Respuesta, adjuntos: tuple[Adjunto, ...], clave: str = "", ctx=None
) -> None:
    """Cuelga fotos y videos de la respuesta, en orden.

    NO se reenvían al insistir. Si acabamos de mandar el muestrario y ella no
    contestó, mandárselo otra vez no la ayuda: ya lo tiene ahí arriba, y tres
    veces la misma foto es lo que hace que la gente silencie un chat.
    """
    if ctx is not None and clave and getattr(ctx, "ultima_clave", "") == clave:
        return
    for tipo, nombre, pie in adjuntos:
        if tipo is Tipo.VIDEO:
            r.reproducir(nombre, pie=pie)
        else:
            r.mostrar(nombre, pie=pie)


class Redactor:
    """Convierte una acción y su ficha en lo que la clienta lee.

    `llm` es opcional a propósito. Sin él, todo sale de plantillas: es el modo
    en que arranca y el que se usa mientras no haya un golden dataset que diga
    que la redacción libre mejora algo. Con él, lo que escriba pasa por
    `hechos.revisar()` y, si mete un dato inventado, sale la plantilla y la
    clienta no se entera.
    """

    def __init__(self, llm=None, redaccion_libre: bool = False) -> None:
        self._llm = llm
        self._libre = redaccion_libre and llm is not None

    def redactar(self, decision: Decision, ficha: Ficha, interp, ctx) -> Respuesta:
        r = Respuesta()
        if decision.veredicto is Veredicto.PREGUNTAR:
            return self._preguntar(decision, ficha, ctx, r, interp)

        plantilla = self._plantilla(decision.accion, ficha, ctx)
        plantilla = self._acusar_foto(plantilla, decision.accion, interp)
        r.clave = self._clave(decision.accion, ficha, interp)
        plantilla = self._sin_repetirse(r, plantilla, ctx)
        texto = self._con_modelo(plantilla, ficha, r)
        r.decir(texto)
        _adjuntar(r, ADJUNTOS.get(decision.accion, ()), r.clave, ctx)
        _mostrar_vistas(r, ficha)
        hueco = (ficha.datos.get("falta") or "").split(", ")[0]
        if hueco:
            _adjuntar(r, _del_hueco(self._hueco(hueco, ficha)[1]), r.clave, ctx)
        if decision.accion is Accion.LLAMAR_HUMANO:
            r.escalar = True
        if ficha.datos.get("cambio_para_persona") or ficha.datos.get("cambio_varios"):
            r.escalar = True
        return r.anotar(f"accion={decision.accion.value}")

    def _acusar_foto(self, plantilla: str, accion: Accion, interp) -> str:
        """Si mandó una foto, lo primero es decirle que llegó.

        Nadie manda una foto y quiere leer un párrafo de precios sin más: el
        silencio sobre lo que acaba de enviar se lee como que no llegó, y
        vuelve a mandarla. Cuando la foto ES la respuesta —el comprobante, la
        talla leída— el texto de la acción ya lo dice y no se acusa dos veces.
        """
        tipo = getattr(interp, "foto", "") if interp is not None else ""
        if not tipo or accion is Accion.RECIBIR_COMPROBANTE:
            return plantilla
        # No se supo qué era la foto y cabían varias cosas: la pregunta es TODO
        # el mensaje. Seguirla con «con mucho gusto» o con otra pregunta la
        # dejaría sin saber qué contestar primero.
        if tipo == "AMBIGUA":
            return getattr(interp, "foto_dice", "") or plantilla
        if tipo == "YA_LLEGO" and accion in (Accion.CHARLAR, Accion.NO_ENTENDI):
            return "¡Sí, ya me llegó! 🥰 Muchas gracias 💕"
        # Cuando la foto parecía decir algo concreto, se le enseña ESO en vez
        # del acuse genérico: «me parece que señalaste el corazón en lila…».
        # Es lo que convierte una lectura de la que no nos fiamos en una
        # pregunta útil, en lugar de tirarla.
        if dice := getattr(interp, "foto_dice", ""):
            return f"{dice}\n\n{plantilla}" if plantilla else dice
        # Si de la foto SÍ salió el dato, el eco ya se lo cuenta («con tu foto
        # me da talla 8»). Acusarla otra vez suena a dos personas hablando.
        if tipo == "ANILLO_CON_REGLA" and getattr(interp.datos, "talla", None):
            return plantilla
        acuse = ACUSE_FOTO.get(tipo)
        if not acuse or acuse in plantilla:
            return plantilla
        return f"{acuse}\n\n{plantilla}" if plantilla else acuse

    # -- preguntar ----------------------------------------------------------

    def _preguntar(self, decision, ficha, ctx, r: Respuesta, interp=None) -> Respuesta:
        opciones = [v for k, v in ficha.datos.items() if k.startswith("opcion_")]
        if opciones:
            lista = "\n".join(f"{i}. {o}" for i, o in enumerate(opciones, start=1))
            r.clave = "pregunta:cual_pedido"
            return r.decir(
                self._sin_repetirse(r, ELEGIR.format(opciones=lista), ctx)
            ).anotar(f"pregunta: {decision.motivo}")

        hueco = (ficha.datos.get("falta") or "").split(", ")[0]
        if hueco:
            texto, clave = self._hueco(hueco, ficha)
            texto = self._acusar_foto(texto, decision.accion, interp)
            if texto:
                r.clave = clave
                r.decir(self._sin_repetirse(r, texto, ctx))
                _mostrar_vistas(r, ficha)
                _adjuntar(r, _del_hueco(clave), r.clave, ctx)
                return r.anotar(f"pregunta hueco: {hueco}")

        # No hay hueco que preguntar: falta algo que todavía NO EXISTE.
        # Decirlo tal cual es infinitamente mejor que «no te entendí», que
        # además es falso: la clienta se explicó perfectamente.
        texto, clave = self._falta_algo(decision, interp, ctx)
        texto = self._acusar_foto(texto, decision.accion, interp)
        r.clave = clave
        return r.decir(self._sin_repetirse(r, texto, ctx)).anotar(
            f"falta {decision.falta}: {decision.motivo}"
        )

    def _falta_algo(self, decision, interp=None, ctx=None) -> tuple[str, str]:
        """Qué contestar cuando el requisito que falla no es un dato del anillo."""
        from app.domain.acciones import Requisito
        from app.domain.interpretacion import Entidad

        # «Quiero cambiar la talla» sin decir cuál: se pregunta la talla nueva,
        # nombrando el pedido si solo hay uno vivo.
        if (
            decision.falta is Requisito.DATOS
            and interp is not None
            and interp.entidad is Entidad.TALLA
        ):
            operativo = getattr(ctx, "operativo", None)
            para = ""
            if operativo is not None and len(operativo.activos) == 1:
                para = f" para tu pedido *{operativo.activos[0].codigo}*"
            return TALLA_NUEVA.format(para=para), "pregunta:talla_nueva"
        if decision.falta is Requisito.PEDIDO:
            return SIN_PEDIDO, "falta:pedido"
        if decision.falta is Requisito.PROCESO:
            return SIN_COMPRA, "falta:proceso"
        if decision.falta is Requisito.DATOS:
            return SIN_DATOS, "falta:datos"
        return TEXTOS[Accion.NO_ENTENDI], "no_entendi"

    def _hueco(self, hueco: str, ficha: Ficha) -> tuple[str, str]:
        """La pregunta para un hueco, afinada con lo que YA se entendió.

        Aquí es donde media respuesta deja de perderse. Si la clienta dijo un
        color sin decir la parte, no se le vuelve a soltar la pregunta larga:
        se le nombra su color y se le pregunta solo lo que falta.
        """
        if hueco == "colores":
            if ficha.datos.get("media_color"):
                return (
                    MEDIA_RESPUESTA["media_pareja"].format(**ficha.datos),
                    "pregunta:media_pareja",
                )
            if ficha.datos.get("color_suelto"):
                return (
                    MEDIA_RESPUESTA["color_suelto"].format(**ficha.datos),
                    "pregunta:color_suelto",
                )
            if n := ficha.datos.get("colores_puestos"):
                return (
                    PREGUNTAS["colores_n"].format(n=int(n) + 1),
                    "pregunta:colores",
                )
        if hueco in PREGUNTAS:
            return PREGUNTAS[hueco], f"pregunta:{hueco}"
        return "", ""

    # -- no repetirse --------------------------------------------------------

    def _clave(self, accion: Accion, ficha: Ficha, interp=None) -> str:
        """De qué va este mensaje. Es lo que SE DIJO, no la acción que entró.

        La distinción importa: anotar la última talla y confirmar la compra
        entran por acciones distintas y salen por el MISMO párrafo, el del
        cobro. Si la clave fuera la acción, el «siii» que viene después
        buscaría a qué contestar y no encontraría la pregunta que acaba de
        leer — que es justo la más importante de la conversación.

        ════════════════════════════════════════════════════════════════════
        UNA DUDA DEL NEGOCIO NO ES «LA MISMA DUDA»
        ════════════════════════════════════════════════════════════════════
        Todas las respuestas de FAQ salían por `RESPONDER_DUDA`, así que tres
        preguntas DISTINTAS compartían clave y la cuenta de insistencias subía
        como si el bot se estuviera repitiendo. En una conversación real:
        «¿es de plata de verdad?», «¿cuánto demora?», «¿hacen envíos a Girón?»
        — tres respuestas distintas, tres preguntas distintas, y a la tercera
        el bot contestó «mejor te paso con una personita».
        """
        hueco = (ficha.datos.get("falta") or "").split(", ")[0]
        if hueco:
            return self._hueco(hueco, ficha)[1] or f"pregunta:{hueco}"
        if accion in COMPRANDO and "abono" in ficha.datos:
            return f"accion:{Accion.RESUMIR_Y_COBRAR_ABONO.value}"
        # El atributo es LO QUE SE PREGUNTÓ: el material, el envío, el tiempo.
        # Con él en la clave, cada duda cuenta por separado y la escalera de
        # insistencias vuelve a medir lo que dice medir.
        atributo = getattr(interp, "atributo", None) if interp is not None else None
        if accion is Accion.RESPONDER_DUDA and atributo is not None:
            return f"accion:{accion.value}:{atributo.value}"
        # Tres preguntas distintas sobre el pasado («el de agosto», «qué talla
        # tenía», «el otro») pueden dar el mismo pedido. No es insistir: en la
        # prueba E2E eso acabó en «mejor te paso con una personita». El criterio
        # de búsqueda separa una pregunta de otra; la misma pregunta repetida
        # sí sigue contando.
        if accion is Accion.CONSULTAR_HISTORIAL:
            return f"accion:{accion.value}:{ficha.datos.get('criterio', '')}"
        return f"accion:{accion.value}"

    def _sin_repetirse(self, r: Respuesta, texto: str, ctx) -> str:
        """El MISMO mensaje, dos veces seguidas, no sale nunca.

        En la conversación real el bot mandó cuatro veces el mismo párrafo,
        byte por byte. No es un detalle de estilo: es lo que le dice a la
        clienta que del otro lado no hay nadie leyendo, y es donde se cierra
        la ventana de WhatsApp.

        A la tercera insistencia se ofrece una persona. Si a la tercera
        todavía no nos entendemos, el problema ya no lo arregla otra frase.
        """
        from app.domain.contexto import huella_de

        r.huella = huella_de(texto)
        if ctx is None or ctx.ultima_clave != r.clave:
            return texto
        # Mismo asunto Y mismas palabras. Si el texto cambió por su cuenta
        # (otro pedido, otro color), no hay nada que esquivar.
        if ctx.ultimo_texto != r.huella:
            return texto
        veces = ctx.veces + 1
        # Sin variantes escritas a mano, la variante es el mismo texto con un
        # ofrecimiento detrás: distinto, honesto y sin inventar nada.
        alternativas = INSISTIR.get(r.clave) or (f"{texto}\n\n{OFRECER_PERSONA}",)

        # Se acabaron las formas de decirlo. No se insiste una vez más: se
        # pasa a una persona. Insistir otra vez no consigue el dato, consigue
        # que cierre el chat.
        if veces > len(alternativas):
            r.escalar = True
            return RENDIRSE

        r.escalar = veces >= 2
        return alternativas[veces - 1]

    # -- plantillas ---------------------------------------------------------

    def _plantilla(self, accion: Accion, ficha: Ficha, ctx) -> str:
        if accion is Accion.MOSTRAR_PRODUCTO:
            return self._catalogo(ficha)
        if accion is Accion.EXPLICAR_COMO_PAGAR and ficha.datos.get("medio"):
            if ficha.datos.get("cuenta_sin_definir"):
                return CUENTA_PENDIENTE.format(medio=ficha.datos["medio"].title())
            return CUENTA.format(cuenta="\n".join(ficha.literales))
        if accion in (
            Accion.RESPONDER_DUDA,
            Accion.EXPLICAR_COMO_MEDIR,
            Accion.EXPLICAR_COMO_PAGAR,
        ):
            return "\n\n".join(ficha.literales) or TEXTOS[Accion.NO_ENTENDI]
        if accion is Accion.RECIBIR_COMPROBANTE and "codigo" in ficha.datos:
            plantilla = COMPROBANTE_DE.get(ficha.datos.get("momento", "abono"))
            if plantilla:
                return plantilla.format(**ficha.datos)
        if accion is Accion.SUGERIR_COMBINACION:
            opciones = [
                f"{n}. {ficha.datos[f'combo_{n}']}"
                for n in (1, 2, 3)
                if f"combo_{n}" in ficha.datos
            ]
            if not opciones:
                return TEXTOS[Accion.NO_ENTENDI]
            return SUGERENCIAS.format(opciones="\n\n".join(opciones))
        if accion is Accion.EXPLICAR_QUE_SIGUE:
            plantilla = QUE_SIGUE.get(ficha.datos.get("que_falta", ""), "")
            if not plantilla:
                return self._pedidos(ficha)
            return plantilla.format(
                cuentas="\n".join(ficha.literales[-1:]), **ficha.datos
            )
        if accion in (Accion.CONSULTAR_PEDIDO, Accion.LISTAR_PEDIDOS):
            return self._pedidos(ficha)
        if accion is Accion.CONSULTAR_HISTORIAL:
            return self._historial(ficha)
        if ficha.datos.get("cambio_varios"):
            return CAMBIO_VARIOS
        if ficha.datos.get("cambio_para_persona"):
            return CAMBIO_PARA_PERSONA.format(**ficha.datos)
        if accion in COMPRANDO:
            texto = self._compra(ficha, ctx)
            if ficha.datos.get("retomada"):
                texto = f"{RETOMADA}\n\n{texto}"
            return texto
        if accion is Accion.RESUMIR_Y_COBRAR_ABONO:
            return self._cobro(ficha)

        base = TEXTOS.get(accion, TEXTOS[Accion.NO_ENTENDI])
        try:
            return base.format(**ficha.datos)
        except KeyError:
            # Falta un dato para rellenar. Mejor una respuesta honesta que un
            # «{codigo}» en pantalla.
            return TEXTOS[Accion.NO_ENTENDI]

    def _catalogo(self, ficha: Ficha) -> str:
        faltan = {"precio_1", "precio_2", "precio_3", "abono", "dias", "dias_max"} - set(
            ficha.datos
        )
        if faltan:
            return TEXTOS[Accion.NO_ENTENDI]
        return CATALOGO.format(**ficha.datos)

    def _pedidos(self, ficha: Ficha) -> str:
        varios = sorted(k for k in ficha.datos if k.startswith("pedido_"))
        if varios:
            lista = "\n".join(
                f"{i}. {ficha.datos[k]}" for i, k in enumerate(varios, start=1)
            )
            return VARIOS_PEDIDOS.format(lista=lista)
        if "codigo" not in ficha.datos:
            return (
                "Todavía no te encuentro ningún pedido 🙈 ¿Quieres que te cuente "
                "cómo pedir el tuyo? 💍"
            )
        texto = TEXTOS[Accion.CONSULTAR_PEDIDO].format(**ficha.datos)
        if ficha.literales:
            texto += "\n\n" + "\n".join(ficha.literales)
        return texto

    def _historial(self, ficha: Ficha) -> str:
        """Lo que se encontró en el pasado. Solo lo que dice la base de datos."""
        cual = ficha.datos.get("historial")
        if cual == "uno":
            movimiento = ""
            if entregado := ficha.datos.get("entregado"):
                movimiento = f"\n📦 Se entregó el {entregado}."
            elif despachado := ficha.datos.get("despachado"):
                movimiento = f"\n🚚 Se despachó el {despachado}."
            texto = HISTORIAL_UNO.format(movimiento=movimiento, **ficha.datos)
            if ficha.literales:
                texto += "\n\n" + "\n".join(ficha.literales)
            return texto
        if cual == "varios":
            varios = sorted(
                (k for k in ficha.datos if k.startswith("pedido_")),
                key=lambda k: int(k.split("_")[1]),
            )
            lista = "\n".join(
                f"{n}. {ficha.datos[k]}" for n, k in enumerate(varios, start=1)
            )
            return HISTORIAL_VARIOS.format(lista=lista)
        if ficha.datos.get("total_pedidos") == "0":
            return HISTORIAL_VACIO
        return HISTORIAL_NINGUNO

    def _compra(self, ficha: Ficha, ctx=None) -> str:
        """Pregunta lo que falta. Solo eso, y sin repetir lo que ya sabe."""
        falta = (ficha.datos.get("falta") or "").split(", ")[0]
        confirmacion = self._eco(ficha, ctx)
        if falta:
            pregunta, _ = self._hueco(falta, ficha)
            if pregunta:
                return (confirmacion + "\n\n" if confirmacion else "") + pregunta
        # Ya no falta nada: toca el resumen. El eco va DELANTE igual, porque
        # el último dato también hay que confirmárselo — sobre todo cuando
        # salió de una foto y ella no sabe si se leyó bien.
        return (confirmacion + "\n\n" if confirmacion else "") + self._cobro(ficha)

    def _eco(self, ficha: Ficha, ctx=None) -> str:
        """Repite lo que acaba de entender EN ESTE MENSAJE. Corto.

        Es lo que hace que la clienta sepa que la escucharon, y lo que le
        permite corregir antes de que se funda nada.

        Solo lo nuevo, nunca todo lo acumulado: repetir «Anoté: 2 huellitas,
        talla 8» en cada turno hace que el bot suene a formulario leyendo su
        propio estado en voz alta. Se nota enseguida hablando con él.
        """
        recien = (ficha.datos.get("recien") or "").split(", ")
        partes = []
        if "huellitas" in recien and (h := ficha.datos.get("huellitas")):
            partes.append(f"{h} huellita{'s' if h != '1' else ''}")
        if "talla" in recien and (t := ficha.datos.get("talla")):
            t = talla_texto(float(t))
            # Si salió de la foto se dice, porque es lo que ella quiere saber
            # («¿pudieron medirlo?»). Que además haya que confirmarla es
            # asunto del taller, no suyo.
            # Se dice de dónde salió: es lo que ella quiere saber después de
            # mandar la foto («¿pudieron medirlo?»). Entre paréntesis para que
            # encaje en cualquiera de las formas de arriba sin sonar raro.
            if "talla_de_foto" in recien:
                partes.append(f"talla {t} (la saqué de tu foto)")
            elif "talla_de_medida" in recien:
                # Escribió la medida en vez de mandar la foto. Se le dice de
                # dónde salió la talla —es lo que quiere comprobar— y se le
                # pide la foto igual, que es lo que hace Lía.
                # Es una referencia, no una talla confirmada (27/09).
                partes.append(f"más o menos talla {t} (por la medida que me diste)")
            else:
                partes.append(f"talla {t}")
        if "colores" in recien and ficha.literales:
            # Si llegaron dos huellitas en un mismo mensaje, se le repiten las
            # dos: repetirle solo la última parece que la otra se perdió.
            cuantas = int(ficha.datos.get("cuantas_colores") or 1)
            partes.append(" · ".join(ficha.literales[0].split(" · ")[-cuantas:]))
        if "talla_despues" in recien:
            partes.append("que la talla me la mandas después")
        if "grabado" in recien and len(ficha.literales) > 1:
            partes.append(f"grabado {ficha.literales[-1]}")
        if not partes:
            return ""
        pool = ECOS_CORRECCION if "correccion" in recien else ECOS
        return variar(pool, ctx).format(que=", ".join(partes))

    def _cobro(self, ficha: Ficha) -> str:
        faltan = {"total", "abono", "saldo", "dias", "dias_max", "envio"} - set(
            ficha.datos
        )
        if faltan:
            return TEXTOS[Accion.NO_ENTENDI]
        diseno = "\n".join(ficha.literales) or ficha.datos.get("producto", "")
        texto = TEXTOS[Accion.RESUMIR_Y_COBRAR_ABONO].format(diseno=diseno, **ficha.datos)
        # Pidió más de un anillo en el mismo mensaje. Que no parezca que se
        # nos olvidó: se dice explícitamente que el otro va después.
        if destino := ficha.datos.get("envio_a"):
            texto += (
                f"\n\n📦 *Lo enviamos a:*\n{destino}\n"
                "_Si algo está mal, me lo dices y lo cambio 💕_"
            )
        if ficha.datos.get("talla_pendiente"):
            texto += (
                "\n\n📏 Y tranquila con la talla: me la mandas cuando puedas, "
                "que la fabricación son 10 a 15 días y da tiempo de sobra 💕"
            )
        if siguiente := ficha.datos.get("siguiente"):
            plural = "s" if siguiente != "1" else ""
            texto += (
                f"\n\n🐾 Y apenas confirmes este, armamos el de *{siguiente} "
                f"huellita{plural}* que también me pediste 💕"
            )
        return texto

    # -- modelo, con red ----------------------------------------------------

    def _con_modelo(self, plantilla: str, ficha: Ficha, r: Respuesta) -> str:
        if not self._libre or not plantilla:
            return plantilla
        try:
            propuesta = self._llm.redactar(plantilla, ficha)
        except Exception:
            return plantilla
        texto, revision = redactar_con_red(propuesta, plantilla, ficha)
        if not revision.aprobado:
            # Que el fallback quede en el log importa: uno silencioso se traga
            # todas las respuestas el día que el modelo deje de servir, y
            # nadie se entera de que lleva una semana sin usarse.
            r.anotar(f"redacción descartada: {revision.motivo}")
        return texto
