"""Las preguntas que se repiten en cada conversación, con su respuesta exacta.

POR QUÉ ESTO NO LO REDACTA EL LLM
=================================
Son respuestas sobre GARANTÍA, MATERIAL y DINERO. Si el modelo las redacta,
un día va a decir "un año de garantía" o "sí manejamos contraentrega", y eso
no es un bug de software: es una promesa comercial que alguien tendrá que
cumplir o romper.

Así que el modelo hace lo único que hace bien y no puede hacer mal: elegir
cuál de las N preguntas es. La respuesta sale de aquí, palabra por palabra,
tal como Lía las escribe hoy. Es la misma idea que el resto del sistema —el
LLM clasifica, Python decide— aplicada al texto.

CÓMO CRECE
==========
Cada vez que aparezca una pregunta nueva en las conversaciones, se agrega una
entrada aquí y una línea al golden dataset. Nada más. Ni prompt, ni
reentrenamiento, ni tocar el grafo.

[POR DEFINIR] Los textos son los de Lía a septiembre de 2026. Cuando cambie
un precio de envío o una política, se cambia AQUÍ y en ningún otro sitio.
"""

from __future__ import annotations

import re
import unicodedata
from enum import Enum


class Pregunta(str, Enum):
    """Dominio cerrado. El LLM elige una de estas o dice NINGUNA."""

    MATERIAL = "MATERIAL"
    GARANTIA = "GARANTIA"
    ENVIO = "ENVIO"
    MEDIOS_DE_PAGO = "MEDIOS_DE_PAGO"
    COLOR_DORADO = "COLOR_DORADO"
    CONTRAENTREGA = "CONTRAENTREGA"
    TIEMPO_ENTREGA = "TIEMPO_ENTREGA"
    COMO_MEDIR_TALLA = "COMO_MEDIR_TALLA"
    POR_QUE_VALE = "POR_QUE_VALE"
    ES_CONFIABLE = "ES_CONFIABLE"
    SI_NO_ME_QUEDA = "SI_NO_ME_QUEDA"
    UBICACION = "UBICACION"
    NINGUNA = "NINGUNA"


# ════════════════════════════════════════════════════════════════════════════
# EL FLETE NO VIVE AQUÍ
# ════════════════════════════════════════════════════════════════════════════
# Los fletes de verdad están en `data/fletes.csv`, una fila por ciudad más una
# fila `(DEFECTO)`. Ese archivo es el único sitio donde se cambia un precio de
# envío, y se cambia con Excel, sin tocar código.
#
# Esta constante es el ÚLTIMO RECURSO: el valor que se usa si ese archivo no
# se pudo leer (no existe, está corrupto, alguien lo movió). Tiene que existir
# porque un bot que no sabe cotizar el envío no puede vender, y quedarse mudo
# por un CSV sería peor que cobrar el valor nacional y que un humano lo ajuste.
#
# Si estos dos números se separan algún día, manda el CSV.
#
# 20/09: Lía cobra UNA tarifa nacional. El bot llegó a cotizarle $8.000 a una
# clienta de Bogotá (la fila vieja del CSV) y $14.000 a otra el mismo día.
ENVIO_NACIONAL_COP = 17_500

#: Lo que dice el mensaje de «tu anillo ya está listo» cuando no hay un pedido
#: con su propio flete (ayudas y ejemplos). Desde el 29/09 es la MISMA cifra
#: que se cotiza (antes había $16.500 en el mensaje y otra en la tabla): cada
#: pedido usa el flete que se le cotizó (`operacion.py`), y este es su respaldo.
ENVIO_EN_EL_MENSAJE_COP = ENVIO_NACIONAL_COP

#: Dónde se puede recoger el anillo en vez de enviarlo. Fuente única: lo usan el
#: bot, los avisos y el resumen.
#:
#: REGLA (Camilo, 09/10): es la CASA de Lía. NUNCA se dice la dirección, la
#: torre ni el apartamento: solo el nombre del conjunto, donde se deja el anillo
#: para que lo recojan (sin costo de envío). Antes aquí iba la dirección completa
#: con torre y apartamento, y el bot se la daba a cualquiera. `vigilar` borra
#: cualquier frase que la tenga, por si el modelo la sacara de otro lado.
PUNTO_DE_RECOGIDA = "el conjunto Conjunto Ejemplo, en Floridablanca"
#: Ciudades desde donde tiene sentido ofrecer recogerlo (el área metropolitana).
CIUDADES_CERCA = ("bucaramanga", "floridablanca", "giron", "girón", "piedecuesta")
CIUDAD_ORIGEN = "Floridablanca, Santander"

#: «¿Dónde están ubicados?» (Camilo, 09/10). No hay punto físico: es un taller de
#: joyería en casa. Se puede recoger en el conjunto (sin envío); en Bucaramanga
#: hay domicilio y su valor depende del domicilio (NUNCA una cifra exacta); al
#: resto del país, Coordinadora.
UBICACION = (
    "Estamos en Floridablanca, Santander 💓 No tenemos punto físico: somos un "
    "taller de joyería en casa, donde hacemos cada anillo a mano ✨\n\n"
    "Si te queda cerca, lo puedes recoger en el conjunto Conjunto Ejemplo "
    "(Floridablanca) y así no pagas envío 🥰 En Bucaramanga también te lo podemos "
    "llevar a domicilio; el valor depende del domicilio de ese día. Y a cualquier "
    "parte del país te lo enviamos por Coordinadora 🚚🐾"
)

RESPUESTAS: dict[Pregunta, str] = {
    Pregunta.MATERIAL: (
        "Nuestras joyas son en Plata Ley 925 garantizada, se entregan "
        "contramarcadas y tienen garantía."
    ),
    Pregunta.GARANTIA: (
        "Tu anillo incluye 6 meses de garantía por defectos de fabricación, "
        "que cubre:\n"
        "• Caída o desprendimiento de piedras.\n"
        "• Rupturas o fracturas en la estructura del anillo "
        "(no provocadas por mal uso).\n"
        "• Cualquier falla relacionada con el proceso de fabricación.\n\n"
        "La garantía no cubre daños por golpes, rayones, mal uso ni el "
        "oscurecimiento natural de la plata, ya que este material puede "
        "requerir limpieza y mantenimiento con el paso del tiempo."
    ),
    #: El valor va como HUECO `{envio}`, no escrito. Quien contesta ya sabe la
    #: ciudad de la clienta (si la dijo) y mete el flete de SU ciudad. Escribir
    #: aquí un número sería volver a tener el precio en dos sitios.
    Pregunta.UBICACION: UBICACION,
    Pregunta.ENVIO: (
        f"Estamos ubicados en {CIUDAD_ORIGEN}.\n\n"
        "Los envíos nacionales tienen un valor de {envio} por "
        f"COORDINADORA, y ese valor lo puedes cancelar al recibir tu anillo."
    ),
    Pregunta.MEDIOS_DE_PAGO: (
        "Puedes pagar por:\n"
        "• Bancolombia\n"
        "• Nequi\n"
        "• Davivienda\n"
        "• Llave\n"
        "• Tarjeta (en este caso se cancela el valor total del anillo y te "
        "generamos link de pago)"
    ),
    Pregunta.COLOR_DORADO: (
        "Nuestras joyas las trabajamos solo en plata Ley 925 💍✨ No les hacemos baños "
        "de oro ni de otros colores porque con el tiempo se pelan, y queremos que la "
        "tuya te dure toda la vida tal como la recibes 🫶"
    ),
    Pregunta.CONTRAENTREGA: (
        "No manejamos contraentrega en joyas personalizadas. Por eso "
        "trabajamos con un abono de $60.000: así puedes ver cómo quedó tu "
        "joya y después, con más confianza, cancelar el saldo restante."
    ),
    Pregunta.TIEMPO_ENTREGA: (
        "El tiempo de fabricación es de 10 a 15 días calendario. Cuando esté "
        "listo te enviamos fotos de cómo quedó, cancelas el saldo y lo "
        "enviamos hasta tu puerta."
    ),
    #: «Está caro». No se rebaja: se cuenta qué lleva dentro.
    #:
    #: Bajar el precio delante de una objeción enseña que el precio era
    #: mentira, y la siguiente clienta también va a pedir rebaja. Lo que sí
    #: cambia una objeción de precio es entender que no es un anillo de
    #: catálogo: es uno que se funde para ella, con su medida y sus nombres.
    Pregunta.POR_QUE_VALE: (
        "Te cuento qué lleva 💍✨\n\n"
        "Cada anillo se fabrica desde cero para ti: no es de catálogo. Va en "
        "Plata Ley 925 contramarcada (la de verdad, la que no se pone verde), "
        "con circones puestos uno por uno a mano, en tu medida exacta y con "
        "los nombres de tus peluditos grabados por dentro.\n\n"
        "Son entre 10 y 15 días de trabajo, y va con 6 meses de garantía.\n\n"
        "Por eso para empezar solo se abona $60.000: ves las fotos de cómo "
        "quedó el tuyo y solo después cancelas el resto 💕"
    ),
    #: La objeción más cara del negocio, y la que casi nadie dice en voz alta.
    #: Se contesta con hechos comprobables, no con «confía en nosotros».
    Pregunta.ES_CONFIABLE: (
        "Te entiendo perfectamente 🥺 Comprar por internet da nervios.\n\n"
        "Por eso trabajamos así: abonas solo $60.000 para que empecemos, y "
        "cuando tu anillo está listo te mando *fotos del tuyo* antes de que "
        "pagues el resto. Si algo no te gustó, no has pagado el saldo.\n\n"
        "Somos un taller de joyería en Floridablanca, llevamos años haciendo esto, y "
        "cada anillo "
        "sale contramarcado en Plata Ley 925 con 6 meses de garantía 💓"
    ),
    #: [POR DEFINIR] Camilo: pon aquí la política REAL de ajuste (si se cobra,
    #: cuánto, y hasta cuándo). Mientras tanto se responde con la verdad —que
    #: se mira caso por caso— y no se promete nada que no se pueda cumplir.
    Pregunta.SI_NO_ME_QUEDA: (
        "Tranquila, por eso insisto tanto con la medida 😊\n\n"
        "Lo tomamos con la talla que me des y lo fabricamos exacto. Si al "
        "recibirlo no te queda bien, me escribes y lo miramos contigo — "
        "siempre buscamos la forma de que te quede perfecto 💕\n\n"
        "Si quieres, te ayudo a tomar la medida antes de empezar: es un "
        "minuto y nos ahorra el problema."
    ),
    Pregunta.COMO_MEDIR_TALLA: (
        "Con un anillo que conserve su forma redonda y una regla, lo vas a "
        "medir en toda la mitad del anillo. Me regalas por favor una foto "
        "para revisarte qué talla sería :)"
    ),
}

# ════════════════════════════════════════════════════════════════════════════
# LOS DATOS DE CADA CUENTA
# ════════════════════════════════════════════════════════════════════════════
# Cuando la clienta dice «bancolombia» después de ver la lista de medios, NO
# quiere la lista otra vez: quiere el número de esa cuenta. Repetirle los
# cinco medios es la respuesta más robótica posible, y es la que da un
# sistema que solo sabe contestar preguntas y no sabe seguir una.
#
# [POR DEFINIR] Los números son de Lía y hay que ponerlos aquí. Mientras
# tanto el bot lo dice honestamente y ofrece una persona: nunca inventa una
# cuenta, porque una cifra equivocada aquí es plata que se va a otro lado y
# no vuelve.
#
# El nombre del titular va SIEMPRE, en todas: es lo que la clienta compara
# antes de darle a enviar, y no verlo es la razón número uno por la que una
# transferencia no se hace.
CUENTA_SIN_DEFINIR = "[POR DEFINIR]"

#: LOS DATOS DE CADA CUENTA. Fuente única.
#:
#: Estos mismos números los usa el aviso de cobro del saldo (`guion.py`), que
#: los tenía copiados. Dos copias de un número de cuenta es la clase de cosa
#: que un día se cambia en un sitio y no en el otro, y entonces una clienta
#: transfiere a una cuenta que ya no existe.
#:
#: El titular va SIEMPRE en todas: es lo que ella compara antes de darle a
#: enviar, y no verlo es la razón número uno por la que una transferencia no
#: se hace.
CUENTAS: dict[str, dict[str, str]] = {
    "BANCOLOMBIA": {
        "titulo": "Bancolombia",
        "detalle": "Ahorros 12345678901\nA nombre de LÍA GÓMEZ",
    },
    "NEQUI": {
        "titulo": "Nequi",
        "detalle": "3001110003\nA nombre de LÍA GÓMEZ",
    },
    "DAVIPLATA": {
        "titulo": "Daviplata",
        "detalle": "3001110003\nA nombre de LÍA GÓMEZ",
    },
    "DAVIVIENDA": {
        "titulo": "Davivienda",
        "detalle": f"Ahorros {CUENTA_SIN_DEFINIR}\nA nombre de {CUENTA_SIN_DEFINIR}",
    },
    # Llave y Nequi son el mismo número: así lo manda Lía en su mensaje del
    # anillo terminado («Llave/Nequi: 3001110003»), 20/09.
    "LLAVE": {
        "titulo": "Llave/Nequi",
        "detalle": "3001110003\nA nombre de LÍA GÓMEZ",
    },
    # La tarjeta no es una cuenta: es un link que se genera por pedido. Se
    # responde distinto a propósito.
    "TARJETA": {
        "titulo": "Tarjeta",
        "detalle": (
            "Con tarjeta se cancela el valor total del anillo y te generamos "
            "el link de pago."
        ),
    },
}

#: Las que se le enseñan cuando pregunta «¿dónde pago?». En este orden.
ORDEN_PARA_COBRAR = ("BANCOLOMBIA", "NEQUI", "DAVIPLATA")


def datos_para_transferir() -> str:
    """Las cuentas que sirven HOY, listas para pegar en un mensaje.

    Se saltan las que siguen sin definir: enseñarle a una clienta un
    «[POR DEFINIR]» es peor que no enseñarle esa cuenta.
    """
    lineas = []
    for medio in ORDEN_PARA_COBRAR:
        cuenta = CUENTAS[medio]
        if CUENTA_SIN_DEFINIR in cuenta["detalle"]:
            continue
        detalle = cuenta["detalle"].replace("\n", " · ")
        lineas.append(f"✨ {cuenta['titulo']}: {detalle}")
    return "\n".join(lineas)


def datos_de_cuenta(medio: str) -> str | None:
    """Los datos de UN medio de pago, o None si no lo conocemos.

    None no es un fallo: es «esto no lo sé», y quien llama lo convierte en
    una respuesta honesta. Devolver una cuenta inventada sería peor que no
    contestar.
    """
    cuenta = CUENTAS.get((medio or "").strip().upper())
    if cuenta is None:
        return None
    return f"{cuenta['titulo']}\n{cuenta['detalle']}"


def cuentas_sin_definir() -> list[str]:
    """Qué cuentas siguen con el marcador puesto. Lo usa el panel y un test.

    Existe para que el día que salga a producción se vea de un vistazo qué
    falta por llenar, en vez de descubrirlo cuando una clienta pregunte.
    """
    return [
        medio
        for medio, cuenta in CUENTAS.items()
        if CUENTA_SIN_DEFINIR in cuenta["detalle"]
    ]


#: Lo que se pone en `{envio}` si quien pregunta no supo calcular el flete.
#: Es el valor nacional de último recurso, formateado — el mismo que usaría
#: la cotización en ese caso. Que la respuesta y la cotización digan cifras
#: distintas es peor que que las dos digan la de último recurso.
ENVIO_SIN_CALCULAR = f"${ENVIO_NACIONAL_COP:,.0f}".replace(",", ".")


def responder(pregunta: Pregunta, **datos: object) -> str | None:
    """La respuesta exacta, o None si no era una de las preguntas conocidas.

    Devolver None es una respuesta legítima: significa "esto no es FAQ, que
    siga el flujo normal". Inventar una respuesta aquí sería justo lo que
    este módulo existe para impedir.

    `datos` rellena los huecos del texto (hoy solo `{envio}`). Si quien llama
    no los pasa, la respuesta SALE IGUAL con el valor nacional en el hueco:
    una excepción aquí dejaría al bot mudo delante de la clienta por un
    detalle de formato, y eso no puede pasar en la mitad de una venta.
    """
    if pregunta is Pregunta.NINGUNA:
        return None
    texto = RESPUESTAS.get(pregunta)
    if texto is None:
        return None
    try:
        return texto.format(**datos)
    except (KeyError, IndexError):
        return texto.replace("{envio}", ENVIO_SIN_CALCULAR)


def sin_respuesta() -> list[Pregunta]:
    """Preguntas del Enum a las que se les olvidó escribir el texto.

    Se comprueba en un test: agregar un miembro al Enum y olvidar la respuesta
    haría que el bot se quedara mudo justo cuando cree que entendió.
    """
    return [p for p in Pregunta if p is not Pregunta.NINGUNA and p not in RESPUESTAS]


# ═══════════════════════════════════════════════════════════════════════════
#  SOLO EN PLATA (Camilo, 05/10)
# ═══════════════════════════════════════════════════════════════════════════
# Real (05/10): «Solo en plata? No hay dorado?». La regla: no se hacen baños de
# oro ni de otros colores porque se pelan; para que la joya dure toda la vida,
# se trabaja solo en plata. Lo dice el SISTEMA, siempre igual (es material y
# garantía: no lo redacta el modelo).

#: Es la misma respuesta de la pregunta frecuente: un solo texto.
SOLO_EN_PLATA = RESPUESTAS[Pregunta.COLOR_DORADO]

#: Pregunta por el METAL de la joya (no por el color de una piedra).
_OTRO_METAL = re.compile(
    r"\bsolo\s+(?:en\s+|de\s+)?plata\b"
    r"|\b(?:en|de)\s+oro\b|\boro\s+(?:rosa|rosado|blanco|laminado|golfi)\b"
    r"|\brose\s*gold\b|\bgolfi\b|\bacero\b"
    # «baño» sin tilde es «bano»; nunca «ban\w*», que es también Bancolombia.
    r"|\b(?:banos?|banad[oa]s?|banar\w*|chapad\w*|enchapad\w*|laminad\w*)\b"
    r"|\botr[oa]s?\s+(?:metal\w*|material\w*)\b"
    r"|\b(?:anillo|aro|argolla|cadena|joya)s?\s+(?:en\s+|de\s+(?:color\s+)?)?dorad"
)
#: «dorado» suelto es del metal… salvo que hable de una piedra: «el corazón
#: dorado» es el circón amarillo (`colores_texto`).
_DORADO = re.compile(r"\b(?:dorad[oa]s?|en\s+oro|de\s+oro|oro)\b")
_DE_UNA_PIEDRA = re.compile(
    r"\b(?:coraz\w*|ded\w*|huellit\w*|piedr\w*|circ\w*|almohad\w*)"
)


def _plano(texto: str) -> str:
    t = unicodedata.normalize("NFD", (texto or "").lower())
    return "".join(c for c in t if not unicodedata.combining(c))


#: «¿Dónde están ubicados?», «tienen tienda?», «dnd qdan», «de donde son?».
#: Solo PREGUNTAS por dónde estamos: «mi dirección es…» no entra.
_UBICACION = re.compile(
    # En plural: «dónde están» habla de ustedes; «dónde está mi anillo», no.
    r"\b(?:donde|dnd|onde|en\s+que\s+(?:parte|ciudad|lugar))\s+(?:es\s+que\s+)?"
    r"(?:estan|stan|quedan|kedan|qdan|se\s+ubican|los\s+(?:encuentro|ubico)"
    r"|las\s+encuentro|atienden)\b"
    r"|\b(?:donde|dnd|onde)\s+(?:queda|esta|kda|qda)\s+(?:la\s+tienda|el\s+local"
    r"|el\s+taller|el\s+punto)\b"
    r"|\bubicad[oa]s\b|\bubica(?:cion|sion|cio)\b"
    r"|\b(?:tienen|hay)\s+(?:una?\s+)?(?:tienda|local|punto\s+fisico|almacen|oficina)\b"
    r"|\bde\s+(?:donde|dnd|que\s+ciudad)\s+(?:son|eres|es\s+la\s+tienda)\b"
    r"|\b(?:puedo|se\s+puede)\s+(?:visitar\w*|ir\s+a\s+(?:la\s+tienda|el\s+local))"
    r"|\bdireccion\s+de\s+(?:ustedes|la\s+tienda|el\s+local|su\s+tienda)\b"
)
#: Lo que NO es preguntar por nosotros: está dando SUS datos.
_SU_DIRECCION = re.compile(r"\b(?:mi|su)\s+direcci|\bvivo\s+en\b|\benvi\w*\s+a\b")


def pregunta_por_la_ubicacion(texto: str | None) -> bool:
    """¿Pregunta dónde estamos (ubicación, tienda, punto físico)?"""
    plano = _plano(texto or "")
    return bool(_UBICACION.search(plano)) and not _SU_DIRECCION.search(plano)


#: La casa de Lía: su número de la calle, o la torre y el apartamento. Ninguna
#: frase del bot puede tenerla (`vigilar`). Estrecha a propósito: la dirección
#: de una CLIENTA («Calle 45 apto 301», «vivo sobre el Anillo Vial») sí se puede
#: repetir para confirmarle el envío.
DIRECCION_DE_CASA = re.compile(
    r"21\s*-\s*462"
    r"|provv?idenza\W+(?:\w+\W+){0,3}?(?:torre|apto|apartamento|apt)\b"
    r"|\btorre\s*1\W+(?:apto|apartamento|apt)\.?\s*301\b",
    re.IGNORECASE,
)


def pregunta_por_otro_metal(texto: str | None) -> bool:
    """¿Pregunta si la joya viene en dorado, oro, con baño u otro metal?"""
    plano = _plano(texto or "")
    if _OTRO_METAL.search(plano):
        return True
    return bool(_DORADO.search(plano)) and not _DE_UNA_PIEDRA.search(plano)
