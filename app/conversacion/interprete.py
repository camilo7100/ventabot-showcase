"""Tramo 2: el único sitio donde el modelo mira el mensaje.

Tres capas, de la más barata a la más cara:

  1. ATAJOS      un puñado de frases exactas («hola», «gracias») se resuelven
                 sin llamar a nadie. Son una fracción enorme del tráfico real
                 y cuestan cero.
  2. PYTHON      los colores y la talla los lee un parser determinista que ya
                 existe y no se equivoca. Lo que Python puede sacar, se saca
                 antes y no se le pregunta al modelo.
  3. MODELO      lo demás, con esquema cerrado y decodificación restringida.

El orden importa: cada capa que resuelve algo es una llamada menos, medio
segundo menos de espera y una oportunidad menos de equivocarse. Y con un
modelo hospedado, es dinero.

FALLO SEGURO
============
Si el modelo no responde o devuelve algo inválido, no se revienta ni se
inventa: se devuelve OTRO, que la tabla de acciones convierte en «no entendí,
¿te paso con alguien?». Una caída del proveedor degrada la conversación; no
la rompe.
"""

from __future__ import annotations

import contextlib
import logging
import re
import unicodedata

from app.domain import consumo
from app.domain.colores_texto import (
    PALABRAS_CORAZON,
    PALABRAS_DEDOS,
    PALABRAS_TODO,
    SINONIMOS,
    alternativa_de_colores,
    leer_colores,
    leer_varias,
    sinonimos_vigentes,
)
from app.domain.contexto import ContextoConversacional, TipoProceso
from app.domain.historial import es_referencia_historica, leer_filtro
from app.domain.interpretacion import (
    Acto,
    Atributo,
    DatosSueltos,
    Entidad,
    Interpretacion,
    PropuestaDelModelo,
    Referencia,
    RutaDeInterpretacion,
    TipoReferencia,
)

log = logging.getLogger("ventabot.interprete")

#: Frases que no necesitan un modelo. Se comparan normalizadas y completas,
#: no por contención: «hola» es un saludo, «hola quiero saber el precio» no.
ATAJOS: dict[str, tuple[Acto, Entidad]] = {
    "hola": (Acto.SALUDAR, Entidad.NINGUNA),
    "buenas": (Acto.SALUDAR, Entidad.NINGUNA),
    "buenos dias": (Acto.SALUDAR, Entidad.NINGUNA),
    "buenas tardes": (Acto.SALUDAR, Entidad.NINGUNA),
    "buenas noches": (Acto.SALUDAR, Entidad.NINGUNA),
    "gracias": (Acto.CONVERSAR, Entidad.NINGUNA),
    "muchas gracias": (Acto.CONVERSAR, Entidad.NINGUNA),
    "ok": (Acto.CONVERSAR, Entidad.NINGUNA),
    "bendiciones": (Acto.CONVERSAR, Entidad.NINGUNA),
    "que lindos": (Acto.CONVERSAR, Entidad.NINGUNA),
    "que lindo": (Acto.CONVERSAR, Entidad.NINGUNA),
    "listo": (Acto.CONFIRMAR, Entidad.NINGUNA),
    "si": (Acto.CONFIRMAR, Entidad.NINGUNA),
    "si porfa": (Acto.CONFIRMAR, Entidad.NINGUNA),
    "confirmo": (Acto.CONFIRMAR, Entidad.NINGUNA),
    "listo confirmo": (Acto.CONFIRMAR, Entidad.NINGUNA),
    "lo quiero": (Acto.CONFIRMAR, Entidad.NINGUNA),
    "dale": (Acto.CONFIRMAR, Entidad.NINGUNA),
    "dale hagamoslo": (Acto.CONFIRMAR, Entidad.NINGUNA),
    "perfecto": (Acto.CONFIRMAR, Entidad.NINGUNA),
    # RETOMAR es de las que peor le salen a un modelo pequeño, y son cuatro
    # frases fijas: se resuelven aquí y dejan de ser un problema.
    "continuemos": (Acto.RETOMAR, Entidad.NINGUNA),
    "sigamos": (Acto.RETOMAR, Entidad.NINGUNA),
    "continuamos": (Acto.RETOMAR, Entidad.NINGUNA),
    "#humano": (Acto.HUMANO, Entidad.NINGUNA),
    "#asesor": (Acto.HUMANO, Entidad.NINGUNA),
}

#: Ordinales como los escribe la gente. Se leen en Python porque son un hecho,
#: no una interpretación.
ORDINALES: dict[str, int] = {
    "primero": 1,
    "primer": 1,
    "primera": 1,
    "1": 1,
    "1o": 1,
    "segundo": 2,
    "segunda": 2,
    "2": 2,
    "2o": 2,
    "tercero": 3,
    "tercer": 3,
    "tercera": 3,
    "3": 3,
    "3o": 3,
    "cuarto": 4,
    "cuarta": 4,
    "4": 4,
    "quinto": 5,
    "quinta": 5,
    "5": 5,
}

#: «talla 8», «talla es 7.5», «mi talla seria la 6». Las muletillas entre
#: medias son opcionales: sin ellas, «mi talla es 7.5» no se leía y el bot
#: volvía a preguntar algo que la clienta acababa de decir.
TALLA = re.compile(
    r"\btalla\s*(?:es|de|la|seria|sería)?\s*(?:la\s*)?(\d{1,2}(?:[.,]5)?)\b",
    re.IGNORECASE,
)
#: La talla SIN la palabra «talla»: «soy 5», «creo que soy la 7», «uso 6».
#:
#: Sale de una conversación real —«aunque creo que soy 5»— que el bot contestó
#: con «no te entendí». Es como dice la gente su talla cuando ya la sabe, y el
#: verbo («soy», «uso», «gasto», «calzo») es lo que la convierte en un dato y
#: no en un número cualquiera. Se valida contra el rango de tallas de verdad,
#: así que «somos 20» no puede colarse.
TALLA_SIN_LA_PALABRA = re.compile(
    r"\b(?:soy|uso|gasto|calzo|utilizo)\s+(?:la\s+|talla\s+|una\s+)?(\d{1,2}(?:[.,]5)?)\b",
    re.IGNORECASE,
)
#: Un número suelto, sin nada más. Solo se lee como talla cuando hay un
#: proceso esperándola: fuera de ese contexto, «8» puede ser cualquier cosa.
SOLO_UN_NUMERO = re.compile(r"^\s*(\d{1,2}(?:[.,]5)?)\s*$")

#: «1,80 cm», «18 mm», «mide 1.8 centímetros». La medida del anillo sobre la
#: regla, ESCRITA en vez de fotografiada.
#:
#: Sale de una conversación real: el bot le explicó cómo medir, ella contestó
#: «1,80 cm» y el bot le dijo «no te entendí» — justo al dato que más cuesta
#: conseguir de toda la venta. La medida se lee, se convierte con la tabla de
#: `domain.tallas` y queda marcada para que alguien la confirme con la foto,
#: que es lo que hace Lía.
MEDIDA_ESCRITA = re.compile(
    r"(\d{1,2}(?:[.,]\d{1,2})?)\s*(cm|mm|cent[ií]metros?|mil[ií]metros?)\b",
    re.IGNORECASE,
)


def leer_medida_mm(texto: str) -> float | None:
    """La medida que escribió, en MILÍMETROS. None si no escribió ninguna.

    Se aceptan las dos unidades porque la gente usa las dos: «1,8 cm» y «18
    mm» son el mismo anillo. Fuera del rango de un dedo humano se devuelve
    None: es un error de tecleo, y convertirlo en una talla sería inventarla.
    """
    m = MEDIDA_ESCRITA.search(texto or "")
    if m is None:
        return None
    try:
        valor = float(m.group(1).replace(",", "."))
    except ValueError:
        return None
    mm = valor * 10 if m.group(2).lower().startswith("c") else valor
    # El mismo rango que acepta `DatosSueltos.diametro_mm`: fuera de ahí, no
    # es la medida de un anillo.
    return mm if 5 <= mm <= 60 else None


HUELLITAS = re.compile(
    r"\b(\d|una|dos|tres)\s*(?:huellit|huell|patit|pat)", re.IGNORECASE
)
PALABRA_NUM = {"una": 1, "dos": 2, "tres": 3}

#: «Una huellita negra», «1 huella color morado», «2 huella verde oscuro».
#:
#: ════════════════════════════════════════════════════════════════════════════
#: EL NÚMERO DICE CUÁL PATITA, NO CUÁNTAS LLEVA EL ANILLO
#: ════════════════════════════════════════════════════════════════════════════
#: Este era el fallo más caro del lote, y sale en las conversaciones reales dos
#: veces:
#:
#:   · «Son dos huellitas» … «Una huellita negra por mi panterita»
#:     El «una» se leía como la cantidad y pisaba el dos. El anillo pasaba de
#:     $250.000 a $200.000 y se fabricaba con una patita en vez de dos.
#:
#:   · «Quiero el de dos huellitas / 1 huella morado… / 2 huella verde…»
#:     Aquí «1 huella» y «2 huella» son ordinales —la primera y la segunda—, y
#:     se leían como dos anillos distintos: se abría un segundo pedido fantasma.
#:
#: La señal que los separa es el COLOR pegado detrás. «Dame dos huellitas» es
#: una cantidad; «una huellita negra» es la descripción de una patita. La lista
#: de colores sale de `sinonimos_vigentes`, así que agregar un color nuevo —o
#: rebautizarlo en el panel— no vuelve a abrir este agujero.
_DESCRIBE: dict[str, re.Pattern[str]] = {}


def describe_una_huellita() -> re.Pattern[str]:
    alternativa = alternativa_de_colores()
    if (patron := _DESCRIBE.get(alternativa)) is None:
        _DESCRIBE.clear()
        patron = _DESCRIBE[alternativa] = re.compile(
            r"\b(?:\d|una|dos|tres)\s*(?:huellit|huell|patit|pat)\w*\s*"
            r"[,:;.-]?\s*(?:de\s+)?(?:color(?:es)?\s+)?"
            rf"(?:{alternativa})\b",
            re.IGNORECASE,
        )
    return patron


CODIGO = re.compile(r"\bPED-\d{4}-\d{3,5}\b", re.IGNORECASE)

#: Una queja SIEMPRE va a una persona. No es una clasificación: es una regla
#: de seguridad. Un modelo de 3B leyó «me llegó partido» como INFORMAR y «se
#: le cayó una piedra» como PREGUNTAR — las dos habrían dejado a una clienta
#: enfadada hablando con un bot. Eso no se deja al criterio de nadie.
#: Ojo con los límites de palabra: «devolver» con `\b` al final no casa dentro
#: de «devolverlo», y «se cayó» hay que dejarlo con el pronombre en medio («se
#: LE cayó»). Los dos fallaron en la primera versión, y son justo las frases
#: de una clienta enfadada.
QUEJA = re.compile(
    r"(\bpartid[oa]|\brot[oa]\b|\bquebrad[oa]|se\s+\w{0,3}\s*cay[oó]|"
    r"\bda[nñ]ad[oa]|se\s+da[nñ][oó]|\bdevolv|\bdevoluci|\breclam|"
    r"no\s+me\s+ha\s+llegado|nunca\s+lleg|\bestafa|mal\s+hecho|"
    r"no\s+sirve|\bequivocad[oa])",
    re.IGNORECASE,
)
#: «Envío» es un SUSTANTIVO y un VERBO, y las dos cosas aparecen a diario.
#:
#: «Ya te envío la foto del comprobante» disparaba la pista del flete y el bot
#: contestaba el párrafo del costo del envío a una clienta que le estaba
#: avisando de un pago. Los pronombres de delante —«te», «le», «se», «me»— y
#: el «ya» son lo único que separa el verbo del sustantivo, y no hace falta
#: nada más: el sustantivo lleva artículo («el envío», «los envíos»).
#:
#: Se define una vez y se usa en los dos sitios que hablan de envíos, para que
#: no puedan tener dos ideas distintas de qué es un envío.
_ENVIO_SUSTANTIVO = (
    r"\b(?<!te\s)(?<!le\s)(?<!se\s)(?<!me\s)(?<!ya\s)env[ií]os?\b|\b(flete|domicilio)\b"
)

PIDE_HUMANO = re.compile(
    r"\b(humano|asesor|una\s+persona|con\s+alguien|me\s+pueden\s+llamar|"
    r"hay\s+(un|algun)\s+asesor|hablar\s+con)\b",
    re.IGNORECASE,
)

#: Palabras con las que la gente dice que YA pagó. Solo cuentan como reporte
#: de pago si la frase NO es una pregunta (ver abajo).
DIJO_QUE_PAGO = re.compile(
    r"\b(ya\s+pagu[eé]|ya\s+aboné|ya\s+abone|acabo\s+de\s+(pagar|consignar|"
    r"transferir)|hice\s+la\s+transferencia|ya\s+(hice|realic[eé])\s+el\s+(pago|abono)|"
    r"ya\s+consign|ya\s+transfer)\b",
    re.IGNORECASE,
)

#: Cómo empieza una PREGUNTA sobre pagos, que no es lo mismo que un pago.
#:
#: «¿puedo pagar cuando lo reciba?» lo leyó el modelo como INFORMAR·PAGO, y
#: eso abre un caso de pago reportado por una clienta que no ha pagado nada.
#: Es el fallo más caro del lote y no se arregla con un ejemplo en el prompt:
#: se arregla no dejando que una frase interrogativa sea nunca un reporte.
PREGUNTA_DE_PAGO = re.compile(
    r"^\s*(¿|puedo|se\s+puede|puedes|aceptan|manejan|tienen|reciben|hay\s+)",
    re.IGNORECASE,
)


#: Letras que en español NUNCA van dobles. Si aparecen dos seguidas, es
#: alargamiento: «siii», «holaaa», «porfaaa», «listooo».
#:
#: Las que sí van dobles se dejan en paz: cc (acción), ee (leer), ll, nn
#: (innato), rr, oo (cooperar). Colapsarlas rompería palabras de verdad.
_NUNCA_DOBLES = "abdfghijkmpqstuvwxyz"
_ALARGADAS = re.compile(rf"([{_NUNCA_DOBLES}])\1+|(.)\2{{2,}}")


def _colapsar(texto: str) -> str:
    """«siiii» -> «si». El entusiasmo no debería impedir entender."""
    return _ALARGADAS.sub(lambda m: m.group(1) or m.group(2), texto)


def normalizar(texto: str) -> str:
    sin_tildes = "".join(
        c
        for c in unicodedata.normalize("NFD", texto or "")
        if unicodedata.category(c) != "Mn"
    )
    limpio = re.sub(r"[^a-z0-9# ]+", " ", sin_tildes.lower()).strip()
    return _colapsar(limpio)


def leer_referencia(texto: str) -> Referencia:
    """Qué señala la clienta. Determinista: son palabras, no matices."""
    t = normalizar(texto)
    if not t:
        return Referencia()

    if m := CODIGO.search(texto or ""):
        return Referencia(tipo=TipoReferencia.CODIGO, texto=m.group(0))

    # «el segundo», «la primera». Se exige el artículo o la palabra pedido
    # delante para no confundir «quiero 2 huellitas» con un ordinal.
    for palabra, pos in ORDINALES.items():
        if re.search(rf"\b(el|la|los|las|mi|del)\s+{palabra}\b", t):
            return Referencia(tipo=TipoReferencia.ORDINAL, posicion=pos)

    if re.search(r"\bel\s+(otro|anterior)\b|\bla\s+(otra|anterior)\b", t):
        return Referencia(tipo=TipoReferencia.OTRO)
    if re.search(r"\bel\s+ultimo\b|\bla\s+ultima\b|\bel\s+mas\s+reciente\b", t):
        return Referencia(tipo=TipoReferencia.ULTIMO)
    if re.search(r"\bes[ae]\b|\bes[ao]s\b|\bese\s+pedido\b|\beste\b", t):
        return Referencia(tipo=TipoReferencia.ESE)
    return Referencia()


#: Cómo se dan los nombres del grabado. Son cuatro formas y no más.
#:
#: Esto era un hueco de verdad, no un fallo del modelo: NADIE extraía los
#: nombres. El modelo leyó «Nombre rocky» como PREGUNTAR·CLIENTE y «que diga
#: Luna y Simba» como CONVERSAR, y aunque hubiera acertado el acto, el nombre
#: se habría perdido igual. Es el dato que se graba en plata y no se deshace.
GRABADO = re.compile(
    r"(?:se\s+llaman?|que\s+diga[n]?|nombres?\s*:?|grabado\s*:?|"
    r"grabar|el\s+nombre\s+es|que\s+lleve"
    # «Y adentro: Lukas ♥ Simón ♥ Orión» — así es como una clienta de verdad
    # dijo qué grabar, y el bot contestó «no te entendí».
    #
    # LOS DOS PUNTOS SON OBLIGATORIOS y no es un descuido: sin ellos, «dentro
    # de cuánto llega?» sacaría «llega» y lo grabaría en plata. Cuando la
    # frase no lleva dos puntos, que la lea el modelo; equivocarse aquí no se
    # arregla con otro mensaje, se arregla fundiendo el anillo otra vez.
    r"|(?:a?dentro|al\s+interior|por\s+dentro)\s*:"
    r")\s+(.{2,60})",
    re.IGNORECASE,
)
#: Palabras que nunca son el nombre de una mascota, aunque queden dentro del
#: trozo capturado.
NO_ES_NOMBRE = {
    "de",
    "la",
    "el",
    "los",
    "las",
    "un",
    "una",
    "mi",
    "mis",
    "su",
    "porfa",
    "por",
    "favor",
    "gracias",
    "en",
    "al",
    "del",
    "anillo",
    "aro",
    "interior",
    "adentro",
    "dentro",
    "peludito",
    "peluditos",
    "perro",
    "gato",
    "mascota",
    "seria",
    "sería",
    "es",
    "son",
    "y",
    "e",
    "con",
    "para",
    "que",
    "diga",
    "nombre",
    "nombres",
    "grabado",
    "grabar",
    "llame",
    "llama",
    "lleve",
    # «quiero nombre Roberto y color rosado todo» grababa «Roberto, color»:
    # salió textual en la conversación de prueba con Meta.
    "color",
    "colores",
    "todo",
    "toda",
    "todos",
}
#: Cómo separa la gente los nombres del grabado. La coma y la «y», sí — pero
#: sobre todo los ADORNOS: en las conversaciones reales los nombres van
#: separados por corazones y emojis, no por comas.
#:
#:     «Lukas ♥ Simón ♥ Orión»      tres peluditos
#:     «🐱 Gordo & Pan 🍞»           dos, con su emoji cada uno
#:
#: Con la lista corta de separadores eso era UN nombre de quince caracteres
#: cortado por la mitad («Lukas ♥ Simón ♥» -> «Lukas Simon Ori»). Cualquier
#: carácter que no pueda estar dentro de un nombre separa: un corazón no es
#: parte de cómo se llama un gato.
#:
#: [POSTERIOR] Los adornos se usan para separar y luego se tiran, igual que
#: las fechas («Paz ♡ 05/01/2025»). Lía SÍ los graba. Guardarlos pide un campo
#: nuevo en `Personalizacion`, no un parche aquí.
SEPARA_NOMBRES = re.compile(r"[,;&]+|\s+y\s+|[^0-9A-Za-zÁÉÍÓÚÜÑáéíóúüñ'.\s-]+")

SIN_GRABADO = re.compile(
    r"\b(sin\s+grabado|ning[uú]n\s+nombre|nada\s+grabado|liso|"
    r"as[ií]\s+est[aá]\s+bien|no\s+quiero\s+grabado)\b",
    re.IGNORECASE,
)


#: «Los que te mandé», «los del mensaje anterior», «los que te dije».
#:
#: No está dando nombres: está SEÑALANDO unos que ya dio. Sacar palabras de
#: una frase así graba «te mandé mensaje» en plata — y eso no se deshace.
#: Si aparece esto, mejor no entender nada y volver a preguntar.
SENALA_LO_DE_ANTES = re.compile(
    r"(los?\s+que\s+te\s+(mand|dij|escrib|puse)|mensaje\s+anterior|"
    r"lo\s+de\s+(arriba|antes)|ya\s+te\s+(los?\s+)?(mand|dij)|"
    r"los?\s+mismos?\s+de)",
    re.IGNORECASE,
)


def leer_grabado(texto: str) -> tuple[list[str], bool]:
    """(nombres, no quiere grabado). Determinista, como los colores.

    Se corta por comas y por «y», se quitan las muletillas, y se conserva la
    mayúscula como la escribió: se graba en plata, y ella sabe mejor que
    nosotros cómo se escribe el nombre de su mascota.
    """
    if SIN_GRABADO.search(texto or ""):
        return [], True
    if SENALA_LO_DE_ANTES.search(texto or ""):
        return [], False
    m = GRABADO.search(texto or "")
    if not m:
        return [], False
    trozo = m.group(1).strip(" .,;:!¡?¿\"'")
    nombres = []
    for parte in re.split(SEPARA_NOMBRES, trozo):
        # Se filtra con la lista LARGA (colores, atajos, interrogativas,
        # verbos…), no con la corta. «Esos son los nombres que quiero los que
        # te mandé» sacaba «quiero te mandé» y lo grababa en plata.
        palabras = [
            w
            for w in parte.split()
            if normalizar(w.strip(".,")) not in _no_es_un_nombre()
        ]
        if not palabras:
            continue
        candidato = " ".join(palabras)[:15].strip()
        # Un nombre de mascota no lleva números ni signos raros: eso descarta
        # que se cuele media frase por un «que diga» suelto.
        if candidato and re.fullmatch(r"[A-Za-zÁÉÍÓÚÜÑáéíóúüñ .'-]+", candidato):
            nombres.append(candidato)
    return nombres[:5], False


#: Palabras que apuntan a un atributo sin lugar a dudas.
#:
#: SOLO se usan para RELLENAR cuando el modelo dejó el atributo en NINGUNO.
#: Nunca para pisarlo: si él eligió uno, sabe algo del contexto que estas
#: palabras sueltas no.
#:
#: Es la tercera capa de la misma idea de todo el proyecto: lo que se puede
#: resolver con una lista, no se le pregunta a un modelo. «Tienen nequi» no
#: necesita comprensión del lenguaje, necesita saber que Nequi es un medio de
#: pago — y eso lo sabemos nosotros, no él.
PISTAS_ATRIBUTO: tuple[tuple[str, str], ...] = (
    (
        r"\b(nequi|daviplata|bancolombia|davivienda|llave|tarjeta|"
        r"transferir|transferencia|efectivo)\b",
        "MEDIOS_DE_PAGO",
    ),
    (
        r"(c[oó]mo\s+(te\s+)?(pago|pagar|puedo\s+pagar|hago\s+el\s+pago)|"
        r"d[oó]nde\s+(pago|consigno|deposito|abono)|datos\s+de\s+pago|"
        r"n[uú]mero\s+de\s+cuenta|a\s+qu[eé]\s+cuenta|"
        # «A qué número te envío los 60?» y «¿cómo hago el adelanto?» son la
        # misma pregunta y las dos salen textuales de conversaciones reales, en
        # el momento exacto en que la clienta decidió comprar. Contestarlas con
        # cualquier otra cosa es perder la venta con la clienta ya convencida.
        r"a\s+qu[eé]\s+n[uú]mero|"
        r"c[oó]mo\s+hago\s+(el|la)\s+(adelanto|abono|anticipo|transferencia))",
        "MEDIOS_DE_PAGO",
    ),
    (r"\b(regla|medir|mido|talla\s+soy|que\s+talla|mi\s+medida)\b", "COMO_MEDIR"),
    (r"\b(garantia|garant[ií]a|se\s+da[nñ]a)\b", "GARANTIA"),
    (r"\b(material|plata|ley\s*925)\b", "MATERIAL"),
    (rf"{_ENVIO_SUSTANTIVO}|\b(coordinadora|despacho)\b", "COSTO_ENVIO"),
    (r"\b(contraentrega|contra\s+entrega|al\s+recibir)\b", "CONTRAENTREGA"),
    # «Son días hábiles o calendario??» es la pregunta que sale DESPUÉS de
    # pagar, y salía textual en una conversación real. No la cazaba nada: el
    # bot estaba atascado pidiendo otro dato y la despachó con «mejor te paso
    # con una personita» — a una clienta que ya había pagado el abono.
    (
        r"\b(demora|demoran|tarda|cuantos\s+dias|d[ií]as\s+h[aá]biles|"
        r"calendario|cu[aá]nto\s+tiempo|cu[aá]ndo\s+(llega|est[aá]\s+listo))\b",
        "TIEMPO",
    ),
    (r"\b(dorado|oro|enchapad|ba[nñ][oa]|que\s+colores)\b", "COLOR_DISPONIBLE"),
)

#: Frases con las que se pregunta por el estado de un pedido. El modelo leyó
#: «ya está listo mi anillo» como CONFIRMAR, y eso le habría mostrado la
#: pantalla de cobro a alguien que solo preguntaba. Suena a afirmación y es
#: una pregunta.
PREGUNTA_ESTADO = re.compile(
    r"\b(ya\s+(esta|está|quedo|quedó|salio|salió|lo\s+enviaron|"
    r"lo\s+despacharon|viene|llego|llegó)|como\s+va|c[oó]mo\s+va|"
    r"alguna\s+novedad|novedades)\b",
    re.IGNORECASE,
)

#: «No tengo regla», «después te la mando», «estoy en la calle».
#:
#: ════════════════════════════════════════════════════════════════════════
#: DONDE SE PIERDEN MÁS VENTAS
#: ════════════════════════════════════════════════════════════════════════
#: La talla es el último dato y el que más cuesta: la clienta está en la
#: calle, no tiene una regla a mano, dice «ahorita te la mando» y vuelve a
#: escribir a los tres días. O no vuelve.
#:
#: Insistir ahí no consigue la medida: consigue que se enfríe. Reconocer que
#: no la tiene AHORA y seguir sin ella —el negocio cobra el abono antes de
#: tener la talla de todas formas— es la diferencia entre una venta y un
#: «déjame ver».
NO_TIENE_TALLA = re.compile(
    r"(no\s+(tengo|s[eé])\s+(la|mi|una|el)?\s*(regla|talla|medida|cu[aá]l|idea)|"
    r"no\s+tengo\s+(c[oó]mo|con\s+qu[eé])\s+medir|"
    r"(despu[eé]s|luego|ahorita|m[aá]s\s+tarde|ma[nñ]ana|en\s+la\s+noche)\s+"
    r"(te\s+)?(la|lo|los)?\s*(mando|env[ií]o|digo|paso|aviso|miro|reviso)|"
    r"estoy\s+en\s+la\s+calle|no\s+estoy\s+en\s+(la\s+)?casa|"
    r"ahorita\s+no\s+puedo|luego\s+la\s+mido|la\s+mido\s+(despu[eé]s|luego)|"
    r"no\s+la\s+s[eé])",
    re.IGNORECASE,
)

#: «¿Cuál me recomiendas?». Pedir ayuda para escoger.
#:
#: No es una duda del negocio ni un dato: es una clienta bloqueada delante de
#: ciento noventa y seis combinaciones. Contestarle «no te entendí» —o peor,
#: repetirle la lista de catorce colores— es dejarla justo donde estaba.
PIDE_AYUDA = re.compile(
    r"(qu[eé]\s+me\s+recomiend|cu[aá]l\s+me\s+recomiend|recomi[eé]ndame|"
    r"me\s+recomiendas|qu[eé]\s+me\s+sugier|ay[uú]dame\s+a\s+(escoger|elegir)|"
    r"no\s+s[eé]\s+(cu[aá]l|qu[eé]|como|cual)|no\s+tengo\s+idea|"
    r"cu[aá]l\s+(se\s+ve|queda|es)\s+(mejor|m[aá]s\s+bonit)|"
    r"el\s+que\s+t[uú]\s+(digas|quieras|veas)|lo\s+que\s+t[uú]\s+(digas|creas)|"
    r"sorpr[eé]ndeme|qu[eé]\s+colores\s+(quedan|combinan|se\s+ven)|"
    r"cu[aá]l\s+me\s+aconsej|dame\s+ideas|alguna\s+idea|"
    r"qu[eé]\s+combinaci[oó]n)",
    re.IGNORECASE,
)

#: «¿Y ahora qué hago?». La pregunta más importante de toda la venta.
#:
#: Se hace justo después del resumen, cuando ya decidió comprar y solo quiere
#: saber cómo pagar. Caía en RESPONDER_DUDA sin ninguna FAQ que responder, y
#: de ahí en «no te entendí, ¿te paso con alguien?» — en el peor momento
#: posible. Es una frase fija y se resuelve con una lista, no con un modelo.
QUE_SIGUE = re.compile(
    r"(qu[eé]\s+(m[aá]s\s+)?(debo|tengo\s+que|hago|har[ií]a|falta|sigue|hay\s+que)|"
    r"qu[eé]\s+m[aá]s\s+necesit|c[oó]mo\s+(sigo|seguimos|continuamos)|"
    r"y\s+ahora\s+qu[eé]|qu[eé]\s+necesitas\s+de\s+m[ií]|"
    r"c[oó]mo\s+hacemos|qu[eé]\s+viene\s+ahora)",
    re.IGNORECASE,
)

#: «También quiero otro» es sumar a lo que ya hay, no empezar de cero.
SUMA_ALGO = re.compile(
    r"\b(tambi[eé]n\s+quiero|uno\s+m[aá]s|otro\s+m[aá]s|"
    r"agr[eé]game|agr[eé]gale|adem[aá]s\s+quiero)\b",
    re.IGNORECASE,
)

#: «¿Cuánto vale?». La pregunta más frecuente de todas, con diferencia.
#:
#: Es una frase fija y se resuelve con una lista: pedírsela a un modelo es
#: gastar medio segundo y una oportunidad de fallar en lo que más se
#: pregunta. La respuesta es el catálogo, con los tres precios.
#: Cosas que también tienen precio y NO son el anillo.
#:
#: «¿Cuánto vale el envío?» y «¿cuánto vale el anillo?» empiezan igual y son
#: preguntas distintas. Esta lista es la que las separa, y es corta a
#: propósito: solo cosas que de verdad se cotizan aparte. Meter aquí «plata»
#: convertiría «¿cuánto vale el anillo de plata?» en una pregunta sobre el
#: material, que es peor que el fallo que arregla.
PRECIO_DE_OTRA_COSA = re.compile(
    r"\b(env[ií]o|env[ií]os|envios|domicilio|flete|coordinadora|despacho)\b",
    re.IGNORECASE,
)


#: «¿El envío se puede pagar de una vez?», «¿te puedo mandar el pago del envío
#: cuando esté listo?».
#:
#: Sale en dos conversaciones reales, y las dos veces junta las dos palabras
#: que el sistema tiene separadas: PAGAR y ENVÍO. El modelo se queda con
#: «pagar» y contesta la lista de bancos, que no es lo que preguntó. La
#: respuesta está en la FAQ del envío, que ya dice cuándo se paga: al recibir.
PAGO_DEL_ENVIO = re.compile(
    rf"(?:{_ENVIO_SUSTANTIVO})[^?.]{{0,40}}\b(?:pag|cancel|abon)"
    rf"|\b(?:pag|cancel|abon)\w*[^?.]{{0,40}}(?:{_ENVIO_SUSTANTIVO})",
    re.IGNORECASE,
)


PIDE_PRECIO = re.compile(
    r"(cu[aá]nto\s+(vale|cuesta|sale|es|cobran|estan|est[aá]n)|"
    r"qu[eé]\s+precio|precios?\b|qu[eé]\s+valor|valor\s+del\s+anillo|"
    r"a\s+c[oó]mo\s+(est[aá]|sale|son))",
    re.IGNORECASE,
)

#: Pedir información del producto, sin nombrarlo. Es como empieza media
#: conversación real de Lía.
PIDE_INFO = re.compile(
    r"\b(info|informaci[oó]n|me\s+cuentas|cu[eé]ntame|me\s+explicas|"
    r"como\s+funciona)\b",
    re.IGNORECASE,
)


#: Los medios de pago, tal como los nombra la gente. Nombrar uno DESPUÉS de
#: ver la lista no es volver a preguntar por los medios: es elegir uno.
MEDIOS: dict[str, str] = {
    "bancolombia": "BANCOLOMBIA",
    "nequi": "NEQUI",
    "davivienda": "DAVIVIENDA",
    "daviplata": "DAVIPLATA",
    "llave": "LLAVE",
    "tarjeta": "TARJETA",
    "credito": "TARJETA",
    "debito": "TARJETA",
}
MEDIO_PAGO = re.compile(
    r"\b(bancolombia|nequi|daviplata|davivienda|llave|tarjeta|"
    r"cr[eé]dito|d[eé]bito)\b",
    re.IGNORECASE,
)


#: Palabras que señalan el corazón Y NADA MÁS.
#:
#: Ojo: `PALABRAS_CORAZON` incluye «huella» y «huellita», porque en «huellita
#: lila» el color va al corazón. Pero aquí se pregunta otra cosa —«¿a qué
#: parte se refiere este mensaje?»— y con esa lista, «dame uno de una huella»
#: contestaba «al corazón». Un color pendiente se habría ido a la parte
#: equivocada sin que nadie lo viera.
SOLO_EL_CORAZON = (
    "corazon",
    "corazoncito",
    "centro",
    "piedra grande",
    "la del medio",
    "principal",
)


def leer_parte(texto: str) -> str | None:
    """«El corazón» / «los deditos», sin color. La otra mitad de la respuesta.

    Solo tiene sentido cuando ya hay un color esperando parte: la clienta
    dijo «morado», el bot preguntó «¿corazón o deditos?», y ella contesta con
    la parte a secas. Sin esto, esa respuesta no lleva ningún dato y la
    conversación se queda dando vueltas en el mismo sitio.
    """
    from app.domain.colores_texto import normalizar as _n

    t = _n(texto)
    corazon = any(re.search(rf"\b{re.escape(w)}(?:e?s)?\b", t) for w in SOLO_EL_CORAZON)
    dedos = any(re.search(rf"\b{re.escape(w)}(?:e?s)?\b", t) for w in PALABRAS_DEDOS)
    if corazon and not dedos:
        return "CORAZON"
    if dedos and not corazon:
        return "DEDOS"
    return None


def _cuantos_anillos(texto: str) -> list[int]:
    """Cuántas huellitas pidió, en orden, si nombró más de un anillo.

    «Dame uno de una huella y otro de 2 huellas» son DOS anillos. Antes se
    leía el primero y el segundo desaparecía sin que nadie lo notara — el
    peor tipo de fallo, porque la clienta cree que la escucharon.

    Aquí no se monta un carrito: se devuelve la lista y quien la reciba
    decide. Un carrito para un negocio de un solo producto es complejidad
    que se paga todos los días y se usa una vez al mes.
    """
    vistos: list[int] = []
    descriptores = {m.start() for m in describe_una_huellita().finditer(texto or "")}
    for m in HUELLITAS.finditer(texto or ""):
        # «1 huella morado» no es un anillo de una huellita: es la primera
        # patita del anillo que ya pidió. Contarla abría un pedido fantasma.
        if m.start() in descriptores:
            continue
        crudo = m.group(1).lower()
        n = PALABRA_NUM.get(crudo) or (int(crudo) if crudo.isdigit() else None)
        if n is not None and 1 <= n <= 3 and n not in vistos:
            vistos.append(n)
    return vistos


#: LAS TRES OBJECIONES QUE APARECEN JUSTO ANTES DE PAGAR.
#:
#: No son dudas técnicas: son miedo. Y van por delante de lo que diga el
#: modelo, no solo rellenando huecos, porque el error aquí es carísimo:
#: «me da miedo pagar por adelantado» contestado con una lista de cuentas
#: bancarias es tan sordo que cierra la conversación.
#:
#: Son frases concretas y no palabras sueltas, así que pisar la lectura del
#: modelo cuando una de estas aparece es seguro.
OBJECIONES: tuple[tuple[str, str], ...] = (
    (
        r"(est[aá]\s+car|muy\s+car|es\s+car[oa]|por\s+qu[eé]\s+(tan|es\s+tan)\s+car|"
        r"no\s+tengo\s+tanto|se\s+me\s+sale\s+del\s+presupuesto|"
        r"hacen\s+descuento|hay\s+descuento|precio\s+especial|me\s+lo\s+deja)",
        "VALOR",
    ),
    (
        r"(es\s+confiable|son\s+confiables|es\s+seguro|me\s+da\s+(miedo|cosa|"
        r"desconfianza)|c[oó]mo\s+s[eé]\s+que|y\s+si\s+no\s+me\s+llega|"
        r"desconf[ií]|no\s+me\s+fio|ustedes\s+son\s+de\s+d[oó]nde|"
        r"tienen\s+(local|tienda|direcci[oó]n))",
        "CONFIANZA",
    ),
    (
        r"(y\s+si\s+no\s+me\s+queda|si\s+me\s+queda\s+(grande|peque|chico)|"
        r"se\s+puede\s+(cambiar|ajustar)\s+(la\s+)?talla|"
        r"si\s+la\s+talla\s+(no\s+)?(esta|est[aá])\s+mal|"
        r"puedo\s+cambiar\s+la\s+talla)",
        "AJUSTE",
    ),
)


def leer_datos(texto: str) -> DatosSueltos:
    """Lo que Python puede sacar solo. Todo esto no se le pregunta al modelo."""
    datos = DatosSueltos()

    if m := TALLA.search(texto or ""):
        with contextlib.suppress(ValueError):
            datos.talla = float(m.group(1).replace(",", "."))

    # «Creo que soy 5». Solo si cae dentro de las tallas que existen: el rango
    # es lo que impide que «soy 30» se anote como una talla imposible.
    if datos.talla is None and (m := TALLA_SIN_LA_PALABRA.search(texto or "")):
        with contextlib.suppress(ValueError):
            candidata = float(m.group(1).replace(",", "."))
            if 3 <= candidata <= 15:
                datos.talla = candidata

    # ESCRIBIÓ LA MEDIDA EN VEZ DE MANDAR LA FOTO.
    #
    # «1,80 cm» es la respuesta a «mide el anillo por la mitad», y el bot
    # contestaba «no te entendí» — al dato que más cuesta conseguir de toda la
    # venta. Se lee aquí, y no solo cuando hay una compra esperando la talla,
    # porque la medida suele llegar ANTES de que exista la compra: ella
    # pregunta el precio, le explican cómo medir, y manda la medida.
    #
    # En este negocio una medida en centímetros solo puede ser una cosa. La
    # talla se calcula con la tabla de `domain.tallas`, y queda marcada para
    # confirmarla con la foto: es lo que hace Lía, y nadie funde plata con una
    # medida que no revisó nadie.
    if datos.talla is None and (mm := leer_medida_mm(texto or "")) is not None:
        from app.domain.tallas import medir

        datos.diametro_mm = mm
        datos.talla = medir(mm).talla

    # La cantidad de huellitas, SALVO que el número esté describiendo una
    # patita concreta («una huellita negra»). Ver `describe_una_huellita`.
    if (m := HUELLITAS.search(texto or "")) and not describe_una_huellita().match(
        texto or "", m.start()
    ):
        crudo = m.group(1).lower()
        datos.huellitas = PALABRA_NUM.get(crudo) or (
            int(crudo) if crudo.isdigit() else None
        )
        if datos.huellitas and not 1 <= datos.huellitas <= 3:
            datos.huellitas = None

    # Los colores se guardan AUNQUE VENGAN A MEDIAS.
    #
    # Antes solo se anotaban si la pareja estaba completa, y «dedos morados»
    # se tiraba entera: la clienta contestaba, el dato desaparecía y el bot
    # volvía a preguntar lo mismo palabra por palabra. Media respuesta no es
    # ruido; es la mitad del trabajo ya hecho.
    varias = leer_varias(texto or "")
    if varias.parejas:
        datos.parejas = list(varias.parejas)
        # La primera también va suelta: es lo que miran las reglas que solo
        # entienden de una huellita cada vez.
        datos.color_corazon, datos.color_dedos = varias.parejas[0]
    else:
        media = dict(varias.media)
        datos.color_corazon = media.get("corazon")
        datos.color_dedos = media.get("dedos")
    if varias.sueltos:
        datos.colores_sueltos = list(varias.sueltos)

    if not (varias.parejas or varias.media or varias.sueltos):
        datos.parte = leer_parte(texto or "")

    if m := MEDIO_PAGO.search(texto or ""):
        datos.medio_pago = MEDIOS[normalizar(m.group(0))]

    # Dos anillos distintos en una sola frase. No se arma un carrito: se
    # atiende uno y se deja el otro apuntado (ver `huellitas_extra`).
    pedidos = _cuantos_anillos(texto or "")
    if len(pedidos) > 1:
        datos.huellitas = pedidos[0]
        datos.huellitas_extra = pedidos[1:]

    nombres, sin_grabado = leer_grabado(texto or "")
    if nombres:
        datos.nombres = nombres
    if sin_grabado:
        datos.sin_grabado = True

    if ciudad := mencionar_ciudad(texto or ""):
        datos.ciudad = ciudad

    # «Cambio la dirección a calle 18a #29 30 Girón». En la conversación de
    # prueba se contestó con el tiempo de FABRICACIÓN y la dirección se perdió.
    # Solo con la frase explícita de cambiarla: una dirección suelta no se
    # reconoce por su forma, sino porque se acaba de preguntar.
    if m := CAMBIA_DIRECCION.search(texto or ""):
        direccion = m.group("dir").strip(" .,;:!¿?\"'")
        if 5 <= len(direccion) <= 120:
            datos.direccion = direccion

    if EMPEZAR_DE_CERO.search(texto or ""):
        datos.empezar_de_cero = True

    return datos


#: «cambio la dirección a …», «la nueva dirección es …».
CAMBIA_DIRECCION = re.compile(
    r"(?:cambi\w*|nueva|otra|actualiz\w*|corrig\w*)\s+(?:la\s+|mi\s+)?"
    r"direcci[oó]n(?:\s+de\s+(?:env[ií]o|entrega))?\s*(?:a|es|por|:|para)?\s+"
    r"(?P<dir>.{5,120})$",
    re.IGNORECASE,
)

#: «Comencemos de 0», «quiero hacer uno diferente», «empecemos de nuevo».
#:
#: Salió textual en la conversación de prueba: «Okey quiero hacer uno diferente
#: comencemos de 0» y el bot le volvió a mostrar el anillo YA DESPACHADO.
EMPEZAR_DE_CERO = re.compile(
    r"(?:comenc|empec|empez|arranc|inici)\w*\s+(?:de\s+)?(?:cero|0|nuevo)(?!\w)"
    r"|(?<!\w)desde\s+(?:cero|0)(?!\w)"
    r"|(?<!\w)(?:uno|otro|un\s+anillo)\s+(?:diferente|distinto|nuevo)(?!\w)"
    r"|(?<!\w)(?:hacer|pedir|armar)\s+otro\s+anillo(?!\w)",
    re.IGNORECASE,
)


#: Palabras que jamás son el nombre de una mascota. Se juntan de sitios que
#: ya existen —los colores, las partes del anillo, los atajos— más las
#: interrogativas y los verbos con los que empieza una pregunta.
#:
#: Construirla a partir de las tablas de siempre y no a mano es lo que hace
#: que agregar un color nuevo no abra un agujero aquí.
_NO_ES_UN_NOMBRE: frozenset[str] = frozenset(
    {
        *NO_ES_NOMBRE,
        *SINONIMOS,
        *PALABRAS_CORAZON,
        *PALABRAS_DEDOS,
        *PALABRAS_TODO,
        *ATAJOS,
        *MEDIOS,
        # interrogativas y verbos de pregunta
        "que",
        "qué",
        "cual",
        "cuál",
        "como",
        "cómo",
        "cuando",
        "cuándo",
        "cuanto",
        "cuánto",
        "cuanta",
        "donde",
        "dónde",
        "quien",
        "quién",
        "por",
        "porque",
        "puedo",
        "puedes",
        "podemos",
        "tienen",
        "tiene",
        "hay",
        "sirve",
        "vale",
        "cuesta",
        "manejan",
        "aceptan",
        "reciben",
        "quiero",
        "queria",
        "necesito",
        "muestrame",
        "mandame",
        "envia",
        "envio",
        "pago",
        "pagar",
        "abono",
        "abonar",
        "talla",
        "tallas",
        "precio",
        "precios",
        "anillo",
        "anillos",
        "huellita",
        "huellitas",
        "pedido",
        "pedidos",
        "gracias",
        "hola",
        "buenas",
        "ok",
        "no",
        "si",
        "espera",
        "esperame",
        "ya",
        "listo",
        "bueno",
        "ahorita",
        "mas",
        "menos",
        "otro",
        "otra",
        "todo",
        "nada",
        "algo",
        "tambien",
        "asi",
        "esta",
        "este",
        "bien",
        # Palabras de «señalar hacia atrás». Salieron de una conversación
        # real: «los que te mandé en el mensaje anterior» acabó grabado.
        "te",
        "me",
        "le",
        "se",
        "mande",
        "mando",
        "dije",
        "dijiste",
        "escribi",
        "puse",
        "mensaje",
        "anterior",
        "arriba",
        "antes",
        "esos",
        "esas",
        "estos",
        "estas",
        "nombres",
        "son",
        "eran",
        "mismo",
        "misma",
        "mismos",
        "igual",
        "muy",
        "solo",
        "sola",
        "claro",
    }
)


_NO_ES_UN_NOMBRE_HOY: dict[str, frozenset[str]] = {}


def _no_es_un_nombre() -> frozenset[str]:
    """La lista de arriba más el nombre que tiene HOY cada color en el panel:
    si Lía rebautiza una bolsita, su nombre nuevo tampoco se graba en plata."""
    clave = alternativa_de_colores()
    if (lista := _NO_ES_UN_NOMBRE_HOY.get(clave)) is None:
        _NO_ES_UN_NOMBRE_HOY.clear()
        lista = _NO_ES_UN_NOMBRE_HOY[clave] = _NO_ES_UN_NOMBRE | frozenset(
            sinonimos_vigentes()
        )
    return lista


#: Un nombre de mascota: letras y, como mucho, las comas que los separan.
#:
#: Las comas estaban fuera y costaron tres nombres de verdad: «Reborta, luna,
#: Cleopatra» —tres peluditos, contestando a «¿qué nombre grabamos?»— se leyó
#: como charla y se perdió entero. Así es como escribe la gente una lista.
_PARECE_NOMBRE = re.compile(r"^[A-Za-zÁÉÍÓÚÜÑáéíóúüñ',. -]{2,60}$")


def parece_nombre_de_mascota(crudo: str) -> list[str]:
    """Los nombres que hay en una respuesta SUELTA, o vacío.

    Solo se usa cuando el bot acaba de preguntar el grabado. Fuera de ese
    momento, «Carmen» es una palabra cualquiera; justo después de «¿qué
    nombre grabamos?», es la respuesta — y leerla como una petición de
    asesor humano, que es lo que pasaba, deja la conversación tirada en el
    último dato que faltaba.
    """
    texto = (crudo or "").strip()
    if not texto or "?" in texto or "¿" in texto:
        return []
    if not _PARECE_NOMBRE.match(texto):
        return []
    palabras = [w for w in re.split(r"[,;]+|\s+y\s+|\s+", texto) if w]
    # Hasta cinco: es el tope de nombres que caben grabados en el aro, y una
    # lista de cinco («Reborta, Luna, Cleopatra») sigue siendo una lista de
    # nombres, no una frase.
    if not 1 <= len(palabras) <= 5:
        return []
    if any(normalizar(w) in _no_es_un_nombre() for w in palabras):
        return []
    # «Luna y Simba» son dos nombres; «Maria Lía» es uno. Se corta por la
    # «y» y por comas, nunca por el espacio.
    nombres = [t.strip()[:15] for t in re.split(r"[,;]+|\s+y\s+", texto) if t.strip()]
    return nombres[:5]


#: Cómo se dice que sí. Se comparan ya normalizadas, así que «siiii», «sii» y
#: «SÍ!!» son la misma palabra antes de llegar aquí.
AFIRMACIONES: frozenset[str] = frozenset(
    {
        "si",
        "sí",
        "sip",
        "sipi",
        "sisas",
        "claro",
        "claro que si",
        "obvio",
        "obvio si",
        "dale",
        "listo",
        "de una",
        "por supuesto",
        "porfa",
        "porfis",
        "por favor",
        "si porfa",
        "si porfis",
        "si por favor",
        "si gracias",
        "claro que si por favor",
        "si me cuentas",
        "cuentame",
        "si cuentame",
        "bueno",
        "va",
        "hagamoslo",
        "me encanta",
        "perfecto",
        "vale",
        "ok",
        "oki",
        "okey",
        "de acuerdo",
        "quiero",
        "lo quiero",
        "si quiero",
        "si claro",
        "yes",
        # Las de confirmar una compra. Van aquí y no solo en ATAJOS porque
        # después del resumen «confirmo» no significa «vuélveme a enseñar el
        # resumen»: significa «voy a pagar, dime dónde».
        "confirmo",
        "confirmado",
        "confirmar",
        "listo confirmo",
        "confirmo si",
        "sale",
        "sale pues",
        "hagalo",
        "de una si",
        "listo entonces",
    }
)

#: A QUÉ le está diciendo que sí.
#:
#: ════════════════════════════════════════════════════════════════════════
#: EL PROBLEMA QUE RESUELVE
#: ════════════════════════════════════════════════════════════════════════
#: Un «sí» no significa nada por sí solo. Significa lo que significaba la
#: pregunta anterior. El bot terminaba su saludo con «¿te cuento cómo
#: funciona?», la clienta contestaba «siii», y como el mensaje no decía nada
#: del anillo, salía un «¡con mucho gusto! cualquier cosa me escribes» —
#: cortés, vacío, y la conversación muerta en el segundo mensaje.
#:
#: La clave es la MISMA que usa el guardián de repeticiones (`Respuesta.
#: clave`). Una sola noción de «de qué iba lo último» para las dos cosas:
#: si un día se agrega una pregunta nueva, aparece aquí y allá a la vez.
RESPUESTA_A_SI: dict[str, tuple[Acto, Entidad, Atributo]] = {
    # «¿Te cuento cómo funciona?»
    "accion:SALUDAR": (Acto.CONSULTAR, Entidad.PRODUCTO, Atributo.NINGUNO),
    # «¿Te gustaría pedir el tuyo?»
    "accion:MOSTRAR_PRODUCTO": (Acto.COMPRAR, Entidad.PRODUCTO, Atributo.NINGUNO),
    # «…solo necesitas abonar $60.000». Que diga que sí es que va a pagar:
    # lo siguiente que necesita son los datos, no otro resumen.
    "accion:RESUMIR_Y_COBRAR_ABONO": (
        Acto.PREGUNTAR,
        Entidad.PAGO,
        Atributo.MEDIOS_DE_PAGO,
    ),
    "accion:EXPLICAR_COMO_PAGAR": (
        Acto.PREGUNTAR,
        Entidad.PAGO,
        Atributo.MEDIOS_DE_PAGO,
    ),
    # «¿Quieres que te cuente cómo pedir el tuyo?»
    "accion:CONSULTAR_PEDIDO": (Acto.CONSULTAR, Entidad.PRODUCTO, Atributo.NINGUNO),
    "falta:pedido": (Acto.COMPRAR, Entidad.PRODUCTO, Atributo.NINGUNO),
    "falta:proceso": (Acto.CONSULTAR, Entidad.PRODUCTO, Atributo.NINGUNO),
}

#: Números escritos con letra, para cuando contesta «una» a cuántas huellitas.
NUMERO_SUELTO: dict[str, int] = {
    "1": 1,
    "una": 1,
    "uno": 1,
    "un": 1,
    "2": 2,
    "dos": 2,
    "3": 3,
    "tres": 3,
}


def leer_afirmacion(
    crudo: str, contexto: ContextoConversacional
) -> Interpretacion | None:
    """«Siii» a secas. Vale lo que valía la pregunta de antes, y nada más.

    Si no sabemos a qué le dijo que sí, se devuelve None a propósito: el
    camino normal acaba volviendo a preguntar, que es exactamente lo que
    haría una persona («¿me confirmas…?»). Adivinar aquí es empezar una
    compra que nadie pidió.
    """
    base = normalizar(crudo)
    if base not in AFIRMACIONES:
        return None
    destino = RESPUESTA_A_SI.get(contexto.ultima_clave or "")
    if destino is None:
        return None
    acto, entidad, atributo = destino
    return Interpretacion(acto=acto, entidad=entidad, atributo=atributo, confianza="ALTA")


#: Claves de mensajes que TERMINAN preguntando cuántas huellitas quiere.
#:
#: Dos de ellas ni siquiera abren una compra («todavía no me aparece ningún
#: pedido tuyo… ¿me dices cuántas huellitas?»), y por eso el «1» que llegaba
#: después no lo entendía nadie: la expectativa vivía en el proceso abierto y
#: ahí no había ninguno. La pregunta la hace el MENSAJE, no el proceso.
PREGUNTAN_HUELLITAS = frozenset(
    {
        "pregunta:huellitas",
        "falta:pedido",
        "falta:proceso",
        # El catálogo también las nombra: «1 huellita $200.000, 2 huellitas…
        # ¿te gustaría pedir el tuyo?». Contestar «1» ahí es elegir.
        "accion:MOSTRAR_PRODUCTO",
    }
)


#: Muletillas con las que la gente da su nombre, su ciudad o su dirección.
#: Se quitan del principio y lo que queda es el dato.
MULETILLAS = re.compile(
    r"^\s*(mi\s+nombre\s+es|me\s+llamo|soy|a\s+nombre\s+de|para|"
    r"vivo\s+en|estoy\s+en|es\s+en|desde|la\s+direcci[oó]n\s+es|"
    r"direcci[oó]n\s*:?|ciudad\s*:?|nombre\s*:?|en)\s+",
    re.IGNORECASE,
)

#: Un nombre de persona: letras y espacios, de una a cinco palabras.
NOMBRE_DE_PERSONA = re.compile(r"^[A-Za-zÁÉÍÓÚÜÑáéíóúüñ' .-]{3,60}$")


def _sin_muletillas(texto: str) -> str:
    return MULETILLAS.sub("", (texto or "").strip()).strip(" .,;:")


def leer_nombre_de_persona(crudo: str) -> str | None:
    """«Carlos Pérez», «soy María», «a nombre de Lía Gómez».

    Solo se usa cuando el bot acaba de preguntar a nombre de quién va el
    envío. Fuera de ese momento, dos palabras con mayúscula pueden ser
    cualquier cosa.
    """
    limpio = _sin_muletillas(crudo)
    if not limpio or "?" in limpio or "¿" in limpio:
        return None
    if not NOMBRE_DE_PERSONA.match(limpio):
        return None
    palabras = limpio.split()
    if not 1 <= len(palabras) <= 5:
        return None
    if any(normalizar(w) in _no_es_un_nombre() for w in palabras):
        return None
    return limpio[:60]


def leer_ciudad(crudo: str) -> str | None:
    """«Bucaramanga», «vivo en Medellín», «para Cali»."""
    limpio = _sin_muletillas(crudo)
    if not limpio or "?" in limpio or "¿" in limpio:
        return None
    if not NOMBRE_DE_PERSONA.match(limpio) or len(limpio.split()) > 4:
        return None
    return limpio[:60]


#: «Soy de Bogotá», «vivo en Medellín», «me lo envías a Cali».
#:
#: DOS LECTORES DE CIUDAD, Y NO SOBRA NINGUNO
#: ------------------------------------------
#: `leer_ciudad` de arriba se usa cuando el bot ACABA DE PREGUNTAR la ciudad:
#: ahí el mensaje entero es la respuesta y hay que ser permisivo («Bucaramanga»
#: a secas es una ciudad).
#:
#: Este otro se usa cuando la clienta la suelta en medio de cualquier cosa
#: —«hola, soy de Bogotá, cuánto vale el envío?»— y ahí hay que ser estricto:
#: la frase trae muchas palabras y casi ninguna es una ciudad. Sin este,
#: «para mi mamá» se anotaba como ciudad y se cotizaba un flete inventado.
#:
#: NO lleva lista de ciudades, y es deliberado: Colombia tiene 1.100
#: municipios y cualquier lista nace incompleta. Se saca el NOMBRE que dijo;
#: quien decide si existe y cuánto cuesta es `data/fletes.csv`.
DICE_CIUDAD = re.compile(
    r"\b(?:soy\s+de|vivo\s+en|estoy\s+en|me\s+encuentro\s+en|"
    # «mand\w*» y no «mandar\w*»: la gente conjuga. «Me lo mandas a Cali» no
    # casaba con «mandar» y la ciudad se perdía — y de la ciudad sale el flete.
    r"env[ií]a\w*\s+(?:lo\s+|melo\s+)?a|env[ií]o\s+a|mand\w*\s+a|"
    r"desde|para|hasta|hacia)\s+"
    r"(?:la\s+ciudad\s+de\s+)?"
    r"((?:[A-ZÁÉÍÓÚÜÑ][\wÁÉÍÓÚÜÑáéíóúüñ]*)(?:\s+(?:de|del|la|las|los)\s+"
    r"[A-ZÁÉÍÓÚÜÑ]?[\wÁÉÍÓÚÜÑáéíóúüñ]*|\s+[A-ZÁÉÍÓÚÜÑ][\wÁÉÍÓÚÜÑáéíóúüñ]*)*)",
)

#: Igual pero sin exigir mayúscula: mucha gente escribe «soy de bucaramanga».
#: Se prueba DESPUÉS y coge una sola palabra, porque sin mayúsculas no hay
#: forma de saber dónde termina el nombre propio.
DICE_CIUDAD_MINUSCULA = re.compile(
    r"\b(?:soy\s+de|vivo\s+en|estoy\s+en|env[ií]a\w*\s+a|env[ií]o\s+a)\s+"
    r"([a-záéíóúüñ]{4,20})\b",
    re.IGNORECASE,
)

#: Palabras que van detrás de «para»/«desde» y NO son una ciudad. Sin esto,
#: «para mí», «para el corazón» o «desde ayer» se anotaban como ciudad.
NO_ES_CIUDAD: frozenset[str] = frozenset(
    {
        "mi",
        "mí",
        "ti",
        "el",
        "la",
        "los",
        "las",
        "un",
        "una",
        "unos",
        "unas",
        "corazon",
        "corazón",
        "dedos",
        "deditos",
        "dedo",
        "ambos",
        "todo",
        "todos",
        "ayer",
        "hoy",
        "mañana",
        "manana",
        "ahora",
        "cuando",
        "que",
        "qué",
        "regalo",
        "regalar",
        "navidad",
        "cumpleaños",
        "cumpleanos",
        "aniversario",
        "mamá",
        "mama",
        "papá",
        "papa",
        "hermana",
        "hermano",
        "amiga",
        "amigo",
        "esposa",
        "esposo",
        "novia",
        "novio",
        "hija",
        "hijo",
        "perrita",
        "perrito",
        "gata",
        "gato",
        "perro",
        "perra",
        "mascota",
        "peludito",
        "peludita",
        "anillo",
        "anillos",
        "talla",
        "medida",
        "plata",
        "envio",
        "envío",
        "usted",
        "ustedes",
        "nosotros",
        "ella",
        "él",
        "eso",
        "esto",
        "acá",
        "aca",
        "allá",
        "alla",
        "aquí",
        "aqui",
    }
)


def mencionar_ciudad(texto: str) -> str | None:
    """La ciudad que nombró de pasada, o None. De aquí sale su flete.

    Devolver None es lo correcto la mayoría de las veces: no dijo de dónde es
    y se cotiza con el valor por defecto. Inventar una ciudad es peor —cotiza
    un flete que no es— así que ante la duda, None.
    """
    for patron in (DICE_CIUDAD, DICE_CIUDAD_MINUSCULA):
        m = patron.search(texto or "")
        if not m:
            continue
        # Se corta en el primer conector: «Bogotá y quiero…» → «Bogotá».
        crudo = re.split(
            r"\s+(?:y|pero|porque|que|con|si|cuando|aunque)\s+", m.group(1).strip()
        )[0]
        crudo = crudo.strip(" ,.;:!?¿¡\"'").strip()
        if not crudo or len(crudo) < 4:
            continue
        if normalizar(crudo.split()[0]) in NO_ES_CIUDAD:
            continue
        return crudo[:60]
    return None


def leer_direccion(crudo: str) -> str | None:
    """Lo que sea que conteste a «¿cuál es la dirección?».

    Aquí se es GENEROSO a propósito. Una dirección colombiana puede ser
    «Calle 45 #12-30 apto 301» o «finca La Esperanza, a 10 minutos del
    pueblo», y rechazar la segunda por no tener forma de dirección es
    llamar mentirosa a quien está contestando lo que le preguntaron.
    Quien despacha lo lee y decide; el bot solo lo guarda.
    """
    limpio = _sin_muletillas(crudo)
    if not limpio or "?" in limpio or "¿" in limpio:
        return None
    if not 5 <= len(limpio) <= 120:
        return None
    return limpio


def leer_de_un_tiron(crudo: str) -> dict:
    """«Carlos Pérez, Bucaramanga, Calle 45 #12-30»: los tres de una vez.

    Mucha gente contesta así en cuanto huele que le van a pedir los datos de
    envío, y hacerle tres preguntas después de eso es no haber leído su
    mensaje.
    """
    from app.domain.envio import parece_direccion

    partes = [p.strip() for p in (crudo or "").split(",") if p.strip()]
    if len(partes) < 3 or not parece_direccion(partes[-1]):
        return {}
    nombre = leer_nombre_de_persona(partes[0])
    ciudad = leer_ciudad(partes[-2])
    if not (nombre and ciudad):
        return {}
    return {
        "nombre_envio": nombre,
        "ciudad": ciudad,
        "direccion": ", ".join([*partes[1:-1], partes[-1]])[:120]
        if len(partes) > 3
        else partes[-1][:120],
    }


def cuantas_huellitas(crudo: str) -> int | None:
    """El número que contesta a «¿1, 2 o 3?». Generoso a propósito.

    Vale «1», «una», «1 huellita» y hasta «P1» —que es lo que escribió una
    clienta de verdad—: cuando la pregunta acaba de decir «puedes elegir 1, 2
    o 3», un mensaje de tres letras con un dígito dentro no puede ser otra
    cosa. Fuera de ese momento esto no se usa nunca.
    """
    base = normalizar(crudo)
    if (n := NUMERO_SUELTO.get(base)) is not None:
        return n
    if (m := HUELLITAS.search(crudo or "")) is not None:
        crudo_num = m.group(1).lower()
        n = PALABRA_NUM.get(crudo_num) or (
            int(crudo_num) if crudo_num.isdigit() else None
        )
        if n and 1 <= n <= 3:
            return n
    if len(base) <= 3:
        digitos = [c for c in base if c.isdigit()]
        if len(digitos) == 1 and digitos[0] in "123":
            return int(digitos[0])
    return None


def leer_eleccion(crudo: str, contexto: ContextoConversacional) -> Interpretacion | None:
    """«La segunda», «la elegante», «me gusta la roja».

    Solo se mira justo después de haberle enseñado las tres. Fuera de ese
    momento, «la segunda» habla de un pedido y no de una combinación — y por
    eso esto vive detrás de una clave y no de una lista de palabras sueltas.
    """
    from app.domain.sugerencias import por_nombre, por_posicion

    if contexto.ultima_clave != "accion:SUGERIR_COMBINACION":
        return None

    base = normalizar(crudo)
    elegida = por_nombre(base)
    if elegida is None:
        # «La segunda», «la 2», «me quedo con la primera».
        posicion = leer_referencia(crudo).posicion
        if posicion is None and base in ORDINALES:
            posicion = ORDINALES[base]
        if posicion is not None:
            elegida = por_posicion(posicion)
    if elegida is None:
        # ¿Nombró un color de los tres? «La verde», «la lila».
        for palabra in base.split():
            if (elegida := por_nombre(palabra)) is not None:
                break
    if elegida is None:
        return None

    return Interpretacion(
        acto=Acto.INFORMAR,
        entidad=Entidad.COLOR,
        datos=DatosSueltos(
            color_corazon=elegida.corazon,
            color_dedos=elegida.dedos,
            parejas=[(elegida.corazon, elegida.dedos)],
        ),
        confianza="ALTA",
    )


def leer_respuesta_esperada(
    crudo: str, contexto: ContextoConversacional
) -> Interpretacion | None:
    """Lo que el bot acaba de preguntar cambia lo que significa la respuesta.

    ════════════════════════════════════════════════════════════════════════
    ESTA ES LA PIEZA QUE FALTABA
    ════════════════════════════════════════════════════════════════════════
    El intérprete miraba el mensaje como si llegara solo. Pero una
    conversación no es una lista de mensajes independientes: si acabo de
    preguntar «¿qué nombre grabamos?», la palabra suelta que llegue después
    es un nombre, no una petición de hablar con una persona.

    No hace falta ni un modelo más grande ni distancias entre vectores: hace
    falta que la pregunta pendiente entre en la interpretación. Es contexto,
    no clasificación — y por eso se resuelve con un `if`, en microsegundos,
    y no con otra llamada al modelo.

    Devuelve None cuando no aplica, y entonces todo sigue como antes.
    """
    # «¿Qué talla quieres ahora?» después de «quiero cambiar la talla». Aquí
    # un número suelto SÍ es la talla: es exactamente lo que se preguntó.
    if contexto.ultima_clave == "pregunta:talla_nueva":
        datos = leer_datos(crudo)
        if datos.talla is None and (m := SOLO_UN_NUMERO.match(crudo.strip())):
            with contextlib.suppress(ValueError):
                candidata = float(m.group(1).replace(",", "."))
                if 3 <= candidata <= 15:
                    datos.talla = candidata
        if datos.talla is not None:
            return Interpretacion(
                acto=Acto.MODIFICAR, entidad=Entidad.TALLA, datos=datos, confianza="ALTA"
            )

    # Lo primero: ¿acabo de preguntarle cuántas huellitas quiere?
    #
    # Va antes que los procesos porque hay mensajes que preguntan eso SIN
    # abrir ninguna compra, y ahí es donde se rompía: ella contestaba «1» y
    # el bot repetía la misma pregunta.
    if (
        contexto.ultima_clave in PREGUNTAN_HUELLITAS
        and (cuantas := cuantas_huellitas(crudo)) is not None
    ):
        datos = leer_datos(crudo)
        datos.huellitas = cuantas
        return Interpretacion(
            # COMPRAR abre una compra; INFORMAR le pega el dato a la que
            # ya está abierta. Elegir mal aquí duplica el pedido.
            acto=(
                Acto.INFORMAR if contexto.abiertos(TipoProceso.COMPRA) else Acto.COMPRAR
            ),
            entidad=Entidad.PRODUCTO,
            datos=datos,
            confianza="ALTA",
        )

    abiertos = contexto.abiertos(TipoProceso.COMPRA)
    if not abiertos:
        return None
    # `pendientes` y no `faltan`: si ya dijo que la talla la manda después,
    # lo que se está preguntando es lo siguiente, no la talla otra vez.
    faltan = abiertos[0].pendientes
    if not faltan:
        return None
    espero = faltan[0]
    datos = leer_datos(crudo)

    # Esperaba colores y dice que no sabe cuáles. Se le proponen.
    if espero == "colores" and PIDE_AYUDA.search(crudo):
        return Interpretacion(
            acto=Acto.PREGUNTAR, entidad=Entidad.COLOR, confianza="ALTA"
        )

    # Esperaba colores y nombró alguno, aunque sea a medias.
    if espero == "colores":
        lectura = leer_colores(crudo)
        if lectura.corazon or lectura.dedos or lectura.sueltos or datos.parte:
            return Interpretacion(
                acto=Acto.INFORMAR,
                entidad=Entidad.COLOR,
                datos=datos,
                confianza="ALTA",
            )

    # Esperaba la talla y la escribió. «Talla 8» —o simplemente «8»—
    # contestando a «me falta tu talla» no necesita que nadie lo interprete:
    # es la respuesta. Fuera de este momento, un «8» suelto puede ser
    # cualquier cosa y por eso no se lee así en ningún otro sitio.
    if espero == "talla":
        # No la tiene a mano. Se sigue sin ella: insistir no consigue la
        # medida, consigue que se enfríe.
        if NO_TIENE_TALLA.search(crudo) and datos.talla is None:
            datos.talla_despues = True
            return Interpretacion(
                acto=Acto.INFORMAR,
                entidad=Entidad.TALLA,
                datos=datos,
                confianza="ALTA",
            )
        if datos.talla is None and (m := SOLO_UN_NUMERO.match(crudo.strip())):
            with contextlib.suppress(ValueError):
                datos.talla = float(m.group(1).replace(",", "."))
        if datos.talla is not None:
            return Interpretacion(
                acto=Acto.INFORMAR,
                entidad=Entidad.TALLA,
                datos=datos,
                confianza="ALTA",
            )

    # Los datos de envío. Lo que conteste a «¿a nombre de quién?» es el
    # nombre: no hace falta reconocer un nombre en el vacío, hace falta saber
    # qué se acaba de preguntar.
    if espero in ("nombre", "ciudad", "direccion"):
        if juntos := leer_de_un_tiron(crudo):
            for campo, valor in juntos.items():
                setattr(datos, campo, valor)
            return Interpretacion(
                acto=Acto.INFORMAR,
                entidad=Entidad.ENVIO,
                datos=datos,
                confianza="ALTA",
            )
        leido = {
            "nombre": ("nombre_envio", leer_nombre_de_persona),
            "ciudad": ("ciudad", leer_ciudad),
            "direccion": ("direccion", leer_direccion),
        }[espero]
        campo, leer = leido
        if (valor := leer(crudo)) is not None:
            setattr(datos, campo, valor)
            return Interpretacion(
                acto=Acto.INFORMAR,
                entidad=Entidad.ENVIO,
                datos=datos,
                confianza="ALTA",
            )

    if espero == "huellitas":
        # «1» a secas contestando «¿cuántas huellitas?» es una huellita. Sin
        # esto había que escribir «1 huellita» para que se entendiera, y nadie
        # contesta así a una pregunta que acaba de decir «puedes elegir 1, 2
        # o 3».
        cuantas = datos.huellitas or cuantas_huellitas(crudo)
        if cuantas:
            datos.huellitas = cuantas
            return Interpretacion(
                acto=Acto.INFORMAR,
                entidad=Entidad.PRODUCTO,
                datos=datos,
                confianza="ALTA",
            )

    # Esperaba el grabado y llegó una palabra que solo puede ser un nombre.
    if espero == "grabado":
        if SIN_GRABADO.search(crudo):
            return Interpretacion(
                acto=Acto.INFORMAR,
                entidad=Entidad.GRABADO,
                datos=DatosSueltos(sin_grabado=True),
                confianza="ALTA",
            )
        if datos.nombres:
            return Interpretacion(
                acto=Acto.INFORMAR,
                entidad=Entidad.GRABADO,
                datos=datos,
                confianza="ALTA",
            )
        if nombres := parece_nombre_de_mascota(crudo):
            return Interpretacion(
                acto=Acto.INFORMAR,
                entidad=Entidad.GRABADO,
                datos=datos.model_copy(update={"nombres": nombres}),
                confianza="ALTA",
            )

    return None


class Interprete:
    """Convierte texto en `Interpretacion`. El modelo es el último recurso."""

    def __init__(
        self,
        llm,
        prompt: str,
        catalogo_txt: str = "",
        ojos=None,
        llm_fuerte=None,
        historial=None,
    ) -> None:
        self._llm = llm
        self._prompt = prompt
        self._catalogo = catalogo_txt
        #: El lector de imágenes. Puede no existir: sin él las fotos se
        #: reconocen como fotos, se marcan para que las mire una persona, y
        #: la conversación sigue igual de bien.
        self._ojos = ojos
        #: El modelo GRANDE, para el segundo intento. Puede no existir: sin él
        #: todo funciona como siempre y los turnos que no se entienden acaban
        #: en «no te entendí», que es lo que hacía hasta ahora.
        self._llm_fuerte = llm_fuerte
        #: `(conversation_id) -> [{"de": "clienta"|"bot", "texto": …}, …]`, del
        #: más viejo al más nuevo. Se inyecta como función y no como
        #: repositorio: el gestor conversacional no conoce adaptadores, y ese
        #: contrato lo vigila import-linter.
        self._historial = historial

    def calentar(self) -> None:
        """Una llamada de arranque a cada capa de modelo, para que la primera
        clienta no pague la espera.

        Medido contra la API: con un esquema nuevo, la PRIMERA llamada tardó
        más de 8 s (el proveedor compila la gramática del esquema y escribe la
        caché del prompt) y se agotó el tiempo; las siguientes, 2,4 s. Con
        Ollama pasa lo mismo al cargar el modelo en la GPU. Nunca falla hacia
        arriba: si no hay red, la primera clienta simplemente espera como antes.
        """
        prompt = self._prompt.replace("{{CATALOGO}}", self._catalogo)
        for nombre, llm in (("basico", self._llm), ("fuerte", self._llm_fuerte)):
            if llm is None:
                continue
            try:
                with consumo.capa(f"calentar_{nombre}"):
                    llm.extract(prompt, "hola", PropuestaDelModelo)
            except Exception as exc:
                log.warning(
                    "no se pudo calentar el modelo %s (%s)", nombre, type(exc).__name__
                )

    def interpretar(
        self,
        texto: str | None,
        media: list[dict] | None,
        contexto: ContextoConversacional,
    ) -> Interpretacion:
        # UNA FOTO. Se mira de verdad, con su propio modelo.
        #
        # Antes se adivinaba por contexto: «si la compra espera la talla, la
        # foto es la talla». Adivinaba mal la mitad de las veces y, sobre
        # todo, no sacaba NADA de la imagen — ni la medida, ni el monto del
        # comprobante, ni el color señalado.
        mirada = self._ojos.mirar(media or [], contexto) if self._ojos else None

        crudo = (texto or "").strip()
        if mirada is not None and not crudo:
            return mirada
        base = normalizar(crudo)

        # 0. CONTESTA A «¿ES EL COMPROBANTE O LA FOTO DE LA TALLA?».
        #    La foto llegó en un turno anterior y no se supo qué era. Lo que
        #    diga ahora decide, y la foto se vuelve a mirar con esa pista.
        if (sobre_la_foto := self._sobre_la_foto_pendiente(crudo, contexto)) is not None:
            return sobre_la_foto

        # 1. GUARDAS DE SEGURIDAD. Primero de todo, siempre. No son
        #    clasificación: son reglas del negocio que no se delegan, y no
        #    hay contexto que valga por delante de una clienta enfadada.
        if QUEJA.search(crudo) or PIDE_HUMANO.search(crudo):
            return _marcar(
                _fundir(
                    Interpretacion(
                        acto=Acto.HUMANO,
                        entidad=Entidad.PEDIDO
                        if QUEJA.search(crudo)
                        else Entidad.NINGUNA,
                        confianza="ALTA",
                    ),
                    mirada,
                ),
                "queja_o_persona",
            )

        if DIJO_QUE_PAGO.search(crudo) and not PREGUNTA_DE_PAGO.match(crudo):
            return _marcar(
                Interpretacion(
                    acto=Acto.INFORMAR,
                    entidad=Entidad.PAGO,
                    referencia=leer_referencia(crudo),
                    confianza="ALTA",
                ),
                "dijo_que_pago",
            )

        # 1b. EL PASADO SE PIDE, NO SE CARGA.
        #     «¿Qué pasó con mi pedido de agosto?», «la vez pasada», «el otro
        #     pedido». Va antes de la expectativa: si el bot acababa de pedir
        #     la dirección, «el pedido de agosto» NO es una dirección.
        #     No se aplica si la frase quiere HACER algo (cancelar, pagar,
        #     cambiar): eso lo decide el modelo, y el historial viaja de paso.
        if (
            mirada is None
            and es_referencia_historica(crudo)
            and not QUIERE_ACTUAR.search(crudo)
        ):
            return _marcar(
                Interpretacion(
                    acto=Acto.CONSULTAR,
                    entidad=Entidad.PEDIDO,
                    atributo=Atributo.HISTORIAL,
                    historial=leer_filtro(crudo),
                    confianza="ALTA",
                ),
                "referencia_historica",
            )

        # 1c. «YA TE MANDÉ LA FOTO» SIN FOTO. Se lee contra lo que está VIVO
        #     (el pedido activo y la compra en curso), nunca contra un pedido
        #     cerrado, que ya no está en el contexto.
        if mirada is None and (aviso := leer_aviso_de_foto(crudo, contexto)) is not None:
            return _marcar(aviso, "aviso_de_foto")

        # 2. LO QUE YO ACABO DE PREGUNTAR.
        #
        #    Va ANTES de los atajos, y ese orden es la corrección: «sí» en la
        #    tabla de atajos vale siempre lo mismo, y un «sí» de verdad vale
        #    lo que valía la pregunta anterior. La tabla no sabe de qué
        #    estábamos hablando; el contexto sí.
        if (eleccion := leer_eleccion(crudo, contexto)) is not None:
            return _marcar(_fundir(eleccion, mirada), "expectativa")
        if (afirmacion := leer_afirmacion(crudo, contexto)) is not None:
            return _marcar(_fundir(afirmacion, mirada), "expectativa")
        if (esperada := leer_respuesta_esperada(crudo, contexto)) is not None:
            return _marcar(_fundir(esperada, mirada), "expectativa")

        # 3. Atajos: frases que valen lo mismo en cualquier conversación.
        if base in ATAJOS:
            acto, entidad = ATAJOS[base]
            return _marcar(
                _fundir(
                    Interpretacion(acto=acto, entidad=entidad, confianza="ALTA"), mirada
                ),
                "atajo",
            )

        # 4. Lo que Python saca solo, antes de gastar una llamada.
        referencia = leer_referencia(crudo)
        datos = leer_datos(crudo)

        # 4b. «Comencemos de 0»: una compra nueva, limpia. Es una frase fija.
        if datos.empezar_de_cero and not QUIERE_ACTUAR.search(crudo):
            return _marcar(
                _fundir(
                    Interpretacion(
                        acto=Acto.COMPRAR,
                        entidad=Entidad.PRODUCTO,
                        datos=datos,
                        confianza="ALTA",
                    ),
                    mirada,
                ),
                "empezar_de_cero",
            )

        # 4c. REGLAS DECISIVAS: las que mandan sobre el modelo diga lo que diga.
        #
        #     Antes se llamaba al modelo y DESPUÉS estas reglas pisaban su
        #     respuesta: «¿cuánto vale el anillo?» costaba una llamada cuyo
        #     resultado se tiraba entero. Si la regla va a decidir igual, el
        #     modelo sobra — en dinero y en segundos de espera.
        if (decidida := _decisiva(crudo, datos, referencia)) is not None:
            return _fundir(decidida, mirada)

        # 4d. «Quiero cambiar la talla» sin decir cuál: hay que preguntarla,
        #     sobre el pedido que esté vivo. No hace falta un modelo para eso.
        if PIDE_CAMBIAR_TALLA.search(crudo) and datos.talla is None:
            return _marcar(
                _fundir(
                    Interpretacion(
                        acto=Acto.MODIFICAR, entidad=Entidad.TALLA, confianza="ALTA"
                    ),
                    mirada,
                ),
                "pide_cambiar_talla",
            )

        # 5. El modelo, para lo que de verdad es lenguaje.
        try:
            with consumo.capa("basico"):
                dicho = self._llm.extract(
                    self._prompt.replace("{{CATALOGO}}", self._catalogo),
                    self._para_el_modelo(crudo, contexto, self._llm),
                    PropuestaDelModelo,
                )
            # Un doble de prueba puede devolver ya la interpretación entera;
            # el modelo de verdad devuelve solo su parte.
            propuesta = (
                dicho if isinstance(dicho, Interpretacion) else dicho.a_interpretacion()
            )
        except Exception as exc:
            # Sin traceback: esto puede pasar 107 veces seguidas (midiendo la
            # línea base, o con Ollama caído) y el volcado de pila repetido
            # entierra la información útil bajo mil líneas iguales.
            log.warning("el modelo no interpretó (%s); se degrada a OTRO", exc)
            # OJO: se pasa por `_corregir` igual que el camino normal.
            #
            # Antes no, y era un error grande: TODAS las reglas
            # deterministas —el precio, las objeciones, los nombres del
            # grabado, «ya está listo mi anillo»— viven ahí. Sin ellas, un
            # rato de Ollama caído dejaba al bot contestando «no te entendí»
            # a cosas que Python entiende perfectamente. Y además hundía la
            # línea base de `vb golden --solo-python`, que es justo la
            # medida de cuánto aporta el modelo.
            degradado = _corregir(
                Interpretacion(
                    acto=Acto.OTRO,
                    referencia=referencia,
                    datos=datos,
                    confianza="BAJA",
                ),
                crudo,
            )
            # El modelo básico cayó: si hay modelo potente y el turno quedó
            # sin entender, se intenta con él. Una caída de Ollama o de la
            # cuenta no debería dejar a nadie en «no te entendí».
            if self._sirve_un_rescate(degradado) and (
                (rescatado := self._rescatar(crudo, contexto)) is not None
            ):
                return _fundir(
                    _marcar(rescatado, "rescate", capa="fuerte", escalada="basico_fallo"),
                    mirada,
                )
            return _fundir(_marcar(degradado, "modelo_caido"), mirada)

        # Lo de Python GANA sobre lo del modelo, EN LAS DOS DIRECCIONES.
        #
        # Que Python encuentre un ordinal y el modelo no, se corrige. Pero que
        # el modelo se invente uno que Python no ve, también: en «quiero el de
        # 2 huellitas» el modelo leyó el 2 como «el segundo pedido» y mandó la
        # compra a otro sitio. La primera versión solo pisaba en un sentido y
        # dejaba pasar justamente el error más raro de depurar.
        #
        # Un ordinal es un hecho: o la frase lo dice o no lo dice.
        propuesta.referencia = referencia
        # `diametro_mm` va en la lista porque la medida la lee Python de la
        # frase («1,80 cm») y el modelo no la devuelve nunca: sin esto llegaba
        # la talla pero se perdía de dónde salía, y con ella la nota que le
        # dice a Lía que hay que confirmarla antes de fundir.
        for campo in (
            "talla",
            "diametro_mm",
            "huellitas",
            "color_corazon",
            "color_dedos",
        ):
            valor = getattr(datos, campo)
            if valor is not None:
                setattr(propuesta.datos, campo, valor)

        # Los nombres del grabado son listas y banderas, no valores sueltos:
        # el bucle de arriba los saltaba. Python los sacaba de la frase y se
        # perdían justo antes de llegar al pedido — el dato que se graba en
        # plata. Lo cazó la medición: eran los dos últimos fallos de 107.
        if datos.nombres:
            propuesta.datos.nombres = datos.nombres
        if datos.sin_grabado:
            propuesta.datos.sin_grabado = True
        # Estos tres los saca Python entero o no los saca nadie: el modelo no
        # tiene ni el muestrario, ni la lista de bancos, ni forma de contar
        # cuántos anillos pidió.
        propuesta.datos.colores_sueltos = datos.colores_sueltos
        propuesta.datos.parejas = datos.parejas
        propuesta.datos.parte = datos.parte
        propuesta.datos.medio_pago = datos.medio_pago
        propuesta.datos.huellitas_extra = datos.huellitas_extra
        # La CIUDAD también la decide Python, y en las dos direcciones.
        #
        # De la ciudad sale el flete que se le cotiza y la dirección de envío
        # que ve quien empaca. Un modelo de 3B que "deduce" que alguien es de
        # Bogotá porque saludó con «quiubo» cotiza mal un envío real. Si la
        # frase nombra una ciudad, ahí está; si no, no hay ciudad.
        propuesta.datos.ciudad = datos.ciudad
        # La dirección nueva y «empezar de cero» también son hechos de la frase.
        propuesta.datos.direccion = datos.direccion
        propuesta.datos.empezar_de_cero = datos.empezar_de_cero

        # Un color es una palabra del muestrario: está en la frase o no está.
        # Si Python no vio ninguna, el modelo no pudo verla — y un color
        # inventado aquí es un anillo fundido del color equivocado.
        if (
            datos.color_corazon is None
            and datos.color_dedos is None
            and not datos.colores_sueltos
        ):
            propuesta.datos.color_corazon = None
            propuesta.datos.color_dedos = None

        # Si Python NO vio una talla, el modelo no puede haberla visto: es un
        # número en la frase o no lo es. «Continuemos» salía con talla 8.
        if datos.talla is None:
            propuesta.datos.talla = None
            propuesta.datos.diametro_mm = None
        if datos.huellitas is None and not HUELLITAS.search(crudo):
            propuesta.datos.huellitas = None

        dijo = f"{propuesta.acto.value}·{propuesta.entidad.value}"
        confianza_modelo = propuesta.confianza
        leido = _corregir(propuesta, crudo)
        corregido = (leido.acto, leido.entidad) != (propuesta.acto, propuesta.entidad)
        leido = _marcar(leido, "modelo", capa="basico")
        leido.ruta.dijo_el_modelo = dijo
        leido.ruta.corregido = corregido

        # SEGUNDO INTENTO, con el modelo potente, el hilo reciente y el estado.
        #
        # No se escala por número de mensajes ni por costumbre: se escala por
        # un MOTIVO que se puede auditar (ver `_por_que_escalar`).
        if motivo := self._por_que_escalar(leido, confianza_modelo, corregido):
            rescatado = self._rescatar(crudo, contexto, motivo=motivo, previo=leido)
            if rescatado is not None:
                rescatado = _marcar(rescatado, "rescate", capa="fuerte", escalada=motivo)
                rescatado.ruta.dijo_el_modelo = dijo
                rescatado.ruta.corregido = corregido
                leido = rescatado
            else:
                leido.ruta.motivo_escalada = f"{motivo}:sin_mejora"

        # El pasado lo filtra Python aunque lo haya detectado el modelo.
        if leido.atributo is Atributo.HISTORIAL and leido.historial is None:
            leido.historial = leer_filtro(crudo)

        return _fundir(leido, mirada)

    # -- el segundo intento -------------------------------------------------

    @staticmethod
    def _por_que_escalar(
        i: Interpretacion, confianza_modelo: str, corregido: bool
    ) -> str:
        """El MOTIVO para gastar el modelo potente, o "" si no hay ninguno.

        Tres, y ninguno es «ya van N mensajes»:

          sin_entender     ni el modelo ni Python sacaron nada de la frase: el
                           turno acabaría en «no te entendí».
          confianza_baja   el propio modelo dice que está adivinando, y lo que
                           adivinó no lo corrigió ninguna regla.
          accion_sensible  cancelar, quitar o modificar algo sin confianza
                           alta. Equivocarse ahí no se arregla con otro
                           mensaje.

        Si Python ya corrigió la lectura, NO se escala: la corrección es un
        hecho de la frase (un color, una talla, una pregunta de precio) y el
        modelo potente no puede verlo mejor.
        """
        if i.acto is Acto.OTRO and not i.datos.hay_algo():
            return "sin_entender"
        if corregido:
            return ""
        if i.acto in (Acto.CANCELAR, Acto.ELIMINAR, Acto.MODIFICAR) and (
            confianza_modelo != "ALTA"
        ):
            return "accion_sensible"
        if confianza_modelo == "BAJA" and i.acto not in (Acto.SALUDAR, Acto.CONVERSAR):
            return "confianza_baja"
        return ""

    @staticmethod
    def _sirve_un_rescate(i: Interpretacion) -> bool:
        """¿Merece la pena gastar el modelo grande en este turno?

        Solo si el turno se quedó sin nada: acto OTRO y ni un dato que Python
        haya podido sacar de la frase. Si hay un dato, la conversación avanza
        igual y el modelo grande no cambiaría nada — costaría tiempo y se
        notaría en la espera de la clienta.
        """
        return i.acto is Acto.OTRO and not i.datos.hay_algo()

    def _rescatar(
        self,
        crudo: str,
        contexto: ContextoConversacional,
        *,
        motivo: str = "sin_entender",
        previo: Interpretacion | None = None,
    ) -> Interpretacion | None:
        """Vuelve a preguntar, con el modelo grande y el hilo de la charla.

        Devuelve None cuando no hay modelo grande, cuando falla, o cuando
        tampoco entendió nada: en los tres casos vale lo que ya teníamos y la
        conversación sigue igual que antes. Un rescate que no rescata no puede
        costar un turno.

        Lo que devuelve pasa por `_corregir` igual que el camino normal, así que
        NINGUNA de las reglas se salta — incluida la que impide que un modelo
        llame a una persona por su cuenta. El modelo grande describe mejor; no
        decide más.
        """
        if self._llm_fuerte is None:
            return None

        try:
            with consumo.capa("fuerte"):
                dicho = self._llm_fuerte.extract(
                    self._prompt.replace("{{CATALOGO}}", self._catalogo),
                    self._con_historial(crudo, contexto),
                    PropuestaDelModelo,
                )
            propuesta = (
                dicho if isinstance(dicho, Interpretacion) else dicho.a_interpretacion()
            )
        except Exception as exc:
            # Solo el TIPO, no el error entero: el adaptador ya explicó en
            # claro qué pasa y qué hacer. Repetir aquí el volcado de JSON en
            # cada turno de cada clienta entierra el aviso que sí servía.
            log.warning("sin rescate en este turno (%s)", type(exc).__name__)
            return None

        # Los datos los sigue sacando Python de la frase, no el modelo grande.
        # Un modelo mejor entiende mejor la INTENCIÓN; un color o una talla
        # siguen siendo palabras que están en el mensaje o no están.
        propuesta.datos = leer_datos(crudo)
        propuesta.referencia = leer_referencia(crudo)
        confianza = propuesta.confianza
        rescatado = _corregir(propuesta, crudo)

        if self._sirve_un_rescate(rescatado):
            return None
        # Cuando se escaló por DUDA (no por no entender), el potente solo manda
        # si él sí está razonablemente seguro. Si también duda, se queda la
        # primera lectura: dos dudas no hacen una certeza.
        if motivo != "sin_entender" and previo is not None and confianza == "BAJA":
            return None
        log.info("resuelto por el modelo potente (%s): %s", motivo, rescatado.resumen())
        return rescatado

    #: Cuántos mensajes de atrás se le dan al modelo grande. Seis son tres
    #: turnos: suficiente para que «el segundo» o «ese» signifiquen algo, y
    #: poco para que no se diluya el mensaje que hay que entender.
    VENTANA_HISTORIAL = 6

    def _con_historial(self, crudo: str, contexto: ContextoConversacional) -> str:
        """El mensaje a interpretar, con los anteriores delante, en orden.

        El mensaje de AHORA va al final y marcado, porque es el que hay que
        describir: lo de arriba es solo para entenderlo. Sin esa separación el
        modelo describe cualquiera de los seis.
        """
        lineas: list[str] = []
        if self._historial is not None:
            try:
                previos = self._historial(contexto.conversation_id) or []
            except Exception as exc:
                log.warning("no se pudo leer el historial (%s)", exc)
                previos = []
            for m in previos[-self.VENTANA_HISTORIAL :]:
                texto = (m.get("texto") or "").strip()
                if not texto:
                    continue
                quien = "CLIENTA" if m.get("de") != "bot" else "TIENDA"
                lineas.append(f"{quien}: {texto[:300]}")

        estado = (
            _estado_para_modelo(contexto) if _acepta_contexto(self._llm_fuerte) else ""
        )
        if not lineas and not estado:
            return crudo
        cabecera = f"ESTADO ACTUAL (solo para entender): {estado}\n\n" if estado else ""
        if not lineas:
            return f"{cabecera}DESCRIBE SOLAMENTE ESTE MENSAJE DE LA CLIENTA:\n{crudo}"
        return (
            cabecera + "Estos son los mensajes anteriores, del más viejo al más nuevo, "
            "solo para que entiendas el contexto:\n"
            + "\n".join(lineas)
            + "\n\nDESCRIBE SOLAMENTE ESTE ÚLTIMO MENSAJE DE LA CLIENTA:\n"
            + crudo
        )

    def _para_el_modelo(self, crudo: str, contexto: ContextoConversacional, llm) -> str:
        """El mensaje para la PRIMERA capa: el texto y, si el modelo lo aprovecha,
        una línea de estado. Nunca el historial ni los pedidos cerrados.

        Solo a los adaptadores que declaran `acepta_contexto`. El modelo local
        de 3B se midió SIN esta línea y ahí se queda: meterle contexto a un
        modelo pequeño suele desordenarle la clasificación, y el acierto que
        tiene hoy está medido con el golden dataset.
        """
        if not _acepta_contexto(llm):
            return crudo
        estado = _estado_para_modelo(contexto)
        if not estado:
            return crudo
        return (
            f"ESTADO ACTUAL (solo para entender, NO lo describas): {estado}\n\n"
            f"MENSAJE DE LA CLIENTA:\n{crudo}"
        )

    # -- la foto por la que se le preguntó -----------------------------------

    def _sobre_la_foto_pendiente(
        self, crudo: str, contexto: ContextoConversacional
    ) -> Interpretacion | None:
        """«Es el comprobante» / «es la de la talla», contestando a la pregunta.

        Solo se mira si de verdad hay una foto pendiente. El comprobante se da
        por recibido (queda EN REVISIÓN: nunca pagado). La talla obliga a volver
        a mirar la foto buscando la regla, que es para lo que se guardó.
        """
        pendiente = contexto.foto_pendiente
        if not pendiente or not crudo:
            return None
        t = normalizar(crudo)
        if re.search(r"\b(comprobante|pago|transferencia|abono|saldo|consignacion)\b", t):
            return _marcar(
                Interpretacion(
                    acto=Acto.INFORMAR,
                    entidad=Entidad.COMPROBANTE,
                    datos=DatosSueltos(comprobante=True),
                    confianza="MEDIA",
                    foto="COMPROBANTE",
                    notas=[
                        "La clienta dijo que la foto que mandó es el COMPROBANTE "
                        "(el lector no la pudo clasificar): verificar el pago en la "
                        "cuenta."
                    ],
                ),
                "foto_aclarada",
            )
        if re.search(r"\b(talla|regla|medida|anillo)\b", t) and self._ojos is not None:
            mirada = self._ojos.mirar([pendiente], contexto, pista="talla")
            if mirada is not None:
                return _marcar(mirada, "foto_aclarada")
        return None


#: Verbos de HACER algo sobre un pedido. Si aparecen, la frase no es una
#: consulta del historial ni una compra nueva: la decide el modelo, con toda
#: la validación de las acciones críticas detrás.
QUIERE_ACTUAR = re.compile(
    r"\b(cancel\w*|anul\w*|devolv\w*|reembols\w*|pagu[eé]|pagar|abon\w*|"
    r"cambi\w*|quit\w*|elimin\w*|modific\w*)\b",
    re.IGNORECASE,
)

#: «Quiero cambiar la talla», «me equivoqué de talla».
PIDE_CAMBIAR_TALLA = re.compile(
    r"(cambi\w*|corregir|modificar|otra)\s+(la\s+|mi\s+|de\s+)?talla|"
    r"me\s+equivoqu\w*\s+(con\s+la\s+|de\s+)?talla",
    re.IGNORECASE,
)

#: «Ya te mandé la foto», «te envié el comprobante». EN PASADO: «ya te mando»
#: es una promesa y se contesta cuando llegue.
AVISA_FOTO = re.compile(
    r"\b(ya\s+)?(te\s+|les?\s+)?(mand[eé]|envi[eé]|pas[eé]|adjunt[eé]|sub[ií])\s+"
    r"(la|el|una|un|las|los)?\s*(foto|fotos|imagen|captura|pantallazo|comprobante)\b",
    re.IGNORECASE,
)
_ES_COMPROBANTE = re.compile(r"\b(comprobante|captura|pantallazo)\b", re.IGNORECASE)

#: Cuánto tiempo después de una foto «ya te la mandé» se refiere a ELLA.
MINUTOS_FOTO_RECIENTE = 30


def leer_aviso_de_foto(
    crudo: str, contexto: ContextoConversacional
) -> Interpretacion | None:
    """«Ya te mandé la foto» cuando en ESTE mensaje no viene ninguna.

    ════════════════════════════════════════════════════════════════════════
    SE LEE CONTRA LO QUE ESTÁ VIVO
    ════════════════════════════════════════════════════════════════════════
    Qué foto es lo decide el estado, no el modelo: si la compra espera la talla
    es la de la talla; si un pedido activo espera el abono, es el comprobante.
    Un pedido cerrado no cuenta: ya salió del contexto (ver `domain/operativo`).

    Y hay que ser honesta con lo que llegó. Si la foto entró hace un momento,
    se le dice que sí llegó; si no entró ninguna, se le pide que la reenvíe en
    vez de dar por recibido algo que nadie vio.
    """
    if not AVISA_FOTO.search(crudo or "") or "?" in (crudo or ""):
        return None
    from datetime import UTC, datetime, timedelta

    from app.domain.operativo import compra_en_curso

    ultima = contexto.ultima_foto_en
    if ultima is not None:
        ultima = ultima if ultima.tzinfo else ultima.replace(tzinfo=UTC)
        if datetime.now(UTC) - ultima < timedelta(minutes=MINUTOS_FOTO_RECIENTE):
            return Interpretacion(
                acto=Acto.CONVERSAR,
                confianza="ALTA",
                foto="YA_LLEGO",
                foto_dice="¡Sí, ya me llegó! 🥰",
            )

    operativo = contexto.operativo
    compra = compra_en_curso(contexto)
    espera_talla = bool(compra and "talla" in compra.pendientes) or bool(
        operativo and any(p.falta_talla for p in operativo.activos)
    )
    espera_pago = bool(operativo and operativo.espera_comprobante()) or bool(
        contexto.abiertos(TipoProceso.PAGO_REPORTADO)
    )
    no_llego = (
        "Uy, no me alcanzó a llegar ninguna foto por aquí 🙈 ¿Me la reenvías porfa?"
    )

    if _ES_COMPROBANTE.search(crudo) or (espera_pago and not espera_talla):
        # Que diga que mandó el comprobante es decir que pagó: se registra como
        # pago REPORTADO sobre el pedido activo (nunca como pagado) y se le pide
        # la foto que no llegó.
        return Interpretacion(
            acto=Acto.INFORMAR,
            entidad=Entidad.PAGO,
            confianza="MEDIA",
            foto="NO_LLEGO",
            foto_dice=no_llego,
        )
    return Interpretacion(
        acto=Acto.OTRO, confianza="MEDIA", foto="NO_LLEGO", foto_dice=no_llego
    )


def _decisiva(
    crudo: str, datos: DatosSueltos, referencia: Referencia
) -> Interpretacion | None:
    """Las reglas de `_corregir` que deciden SIN importar lo que diga el modelo.

    Solo aplica a frases sin datos y sin referencia: en esas, las reglas de
    abajo mandan sobre cualquier acto del modelo, así que llamarlo era pagar
    por una respuesta que se iba a tirar. El orden es el mismo de `_corregir`,
    para que el camino con modelo y el camino sin él no puedan contestar
    distinto a la misma frase.
    """
    if datos.hay_algo() or referencia.tipo is not TipoReferencia.NINGUNA:
        return None

    def listo(motivo: str, **kw) -> Interpretacion:
        return _marcar(Interpretacion(confianza="ALTA", **kw), motivo)

    if PREGUNTA_ESTADO.search(crudo):
        return listo(
            "estado_del_pedido",
            acto=Acto.CONSULTAR,
            entidad=Entidad.PEDIDO,
            atributo=Atributo.ESTADO,
        )
    for patron, atributo in OBJECIONES:
        if re.search(patron, crudo, re.IGNORECASE):
            return listo("objecion", acto=Acto.PREGUNTAR, atributo=Atributo(atributo))
    if PAGO_DEL_ENVIO.search(crudo):
        return listo(
            "pago_del_envio",
            acto=Acto.PREGUNTAR,
            entidad=Entidad.ENVIO,
            atributo=Atributo.COSTO_ENVIO,
        )
    if PIDE_AYUDA.search(crudo):
        return listo("pide_sugerencia", acto=Acto.PREGUNTAR, entidad=Entidad.COLOR)
    if QUE_SIGUE.search(crudo):
        return listo(
            "que_sigue",
            acto=Acto.PREGUNTAR,
            entidad=Entidad.PEDIDO,
            atributo=Atributo.ABONO,
        )
    if PIDE_PRECIO.search(crudo) and not PRECIO_DE_OTRA_COSA.search(crudo):
        return listo("precio", acto=Acto.CONSULTAR, entidad=Entidad.PRODUCTO)
    return None


def _marcar(
    i: Interpretacion, motivo: str, *, capa: str = "reglas", escalada: str = ""
) -> Interpretacion:
    """Apunta por qué capa salió la interpretación. No cambia nada más."""
    i.ruta = RutaDeInterpretacion(
        capa=capa,
        motivo=motivo,
        escalado=bool(escalada),
        motivo_escalada=escalada,
        dijo_el_modelo=i.ruta.dijo_el_modelo,
        corregido=i.ruta.corregido,
        candidatos=i.ruta.candidatos,
    )
    return i


def _acepta_contexto(llm) -> bool:
    return bool(getattr(llm, "acepta_contexto", False))


#: Lo que el bot acaba de preguntar, en palabras para el modelo.
_PREGUNTO: dict[str, str] = {
    "pregunta:huellitas": "cuántas huellitas",
    "pregunta:colores": "los colores",
    "pregunta:media_pareja": "el color que falta",
    "pregunta:color_suelto": "a qué parte va el color",
    "pregunta:grabado": "el nombre para grabar",
    "pregunta:talla": "la talla",
    "pregunta:talla_nueva": "la talla nueva",
    "pregunta:nombre": "a nombre de quién va el envío",
    "pregunta:ciudad": "la ciudad",
    "pregunta:direccion": "la dirección",
    "pregunta:cual_pedido": "de cuál pedido habla",
    "accion:RESUMIR_Y_COBRAR_ABONO": "si confirma el pedido",
}


def _estado_para_modelo(contexto: ContextoConversacional) -> str:
    """Estado operativo + lo último que se preguntó. Sin datos personales."""
    partes = []
    operativo = contexto.operativo
    if operativo is not None and (resumen := operativo.resumen_para_modelo()):
        partes.append(resumen)
    if pregunta := _PREGUNTO.get(contexto.ultima_clave or ""):
        partes.append(f"la tienda acaba de preguntar {pregunta}")
    return "; ".join(partes)


def _fundir(texto: Interpretacion, foto: Interpretacion | None) -> Interpretacion:
    """Un mensaje con foto Y texto es UN mensaje. Se suman, no compiten.

    Quién manda: la FOTO, cuando dice algo concreto. Un pie de foto («aquí te
    mando») describe; la imagen es la prueba. Al revés se leía «te mando el
    comprobante» como una promesa y el comprobante se quedaba sin registrar.

    Los datos se suman siempre: el texto puede traer la talla y la foto el
    monto, y las dos cosas hacen falta.
    """
    if foto is None:
        return texto

    datos = texto.datos.model_copy()
    for campo, valor in foto.datos.model_dump().items():
        if valor in (None, [], False):
            continue
        # Lo que el TEXTO dijo explícitamente gana: si escribió «talla 8» y
        # la foto se leyó 7.5, manda ella. Escribirlo es más deliberado que
        # apoyar un anillo en una regla.
        if getattr(datos, campo) in (None, [], False):
            setattr(datos, campo, getattr(foto.datos, campo))

    manda_la_foto = foto.acto is not Acto.OTRO
    # La ruta de la foto gana si la foto pasó por un modelo: es lo que costó.
    ruta = foto.ruta if foto.ruta.capa != "reglas" or foto.ruta.escalado else texto.ruta
    return texto.model_copy(
        update={
            "ruta": ruta,
            "foto_pendiente": foto.foto_pendiente,
            "acto": foto.acto if manda_la_foto else texto.acto,
            "entidad": foto.entidad if manda_la_foto else texto.entidad,
            "datos": datos,
            "foto": foto.foto,
            "notas": foto.notas,
            "foto_dice": foto.foto_dice,
            "confianza": foto.confianza if manda_la_foto else texto.confianza,
        }
    )


def _corregir(i: Interpretacion, crudo: str) -> Interpretacion:
    """Dos correcciones que son gramática del negocio, no clasificación.

    Ninguna adivina nada: las dos aplican una verdad que el modelo no puede
    saber y nosotros sí. Salieron de medir el dataset, y son la diferencia
    entre pedirle a un modelo pequeño que acierte siempre y darle un sistema
    que aguanta cuando no acierta.
    """
    # 0. A UNA PERSONA NO LA LLAMA EL MODELO. LA LLAMAN LAS PALABRAS.
    #
    # ════════════════════════════════════════════════════════════════════════
    # EL FALLO QUE LO TRAJO
    # ════════════════════════════════════════════════════════════════════════
    # Cuarto mensaje de una conversación de verdad por WhatsApp:
    #
    #     «Hola» · «Si» · «Quiero pedir uno» · «Paco»
    #
    # «Paco» es el nombre del peludito. El modelo lo leyó como HUMANO y la
    # conversación se acabó ahí: LLAMAR_HUMANO escala, y escalar es la única
    # acción de la que el bot no vuelve solo.
    #
    # Las señales de que alguien quiere una persona son PALABRAS concretas
    # —«asesor», «una persona», «hablar con», y las de una queja— y ya están en
    # `PIDE_HUMANO` y `QUEJA`, que se miran ANTES del modelo y cortan de una.
    # Así que si ninguna de las dos apareció y el modelo dice HUMANO, se lo
    # inventó: en un mensaje de una palabra no cabe una petición de asesor.
    #
    # Es la misma regla que ya se aplica a los colores y a la talla —lo que
    # Python no ve, el modelo no pudo verlo— y aquí importa más que en ningún
    # otro sitio, porque el precio de equivocarse no es una frase rara: es la
    # venta entera.
    #
    # Se degrada a OTRO y NO se devuelve todavía: las reglas de abajo siguen
    # mirando la frase, así que si Python le saca un dato («negro», «talla 7»)
    # acaba en INFORMAR y se anota igual. Y con una compra a medias, OTRO se
    # convierte en «volvamos a lo que falta», que es lo que haría una persona.
    if i.acto is Acto.HUMANO and not (PIDE_HUMANO.search(crudo) or QUEJA.search(crudo)):
        i = i.model_copy(update={"acto": Acto.OTRO, "confianza": "BAJA"})

    # 1. UNA PREGUNTA NUNCA ES UN REPORTE DE PAGO.
    #    El modelo leyó «¿puedo pagar cuando lo reciba?» como INFORMAR·PAGO, y
    #    eso abre un caso de pago reportado por alguien que no ha pagado nada.
    #    Es el fallo más caro de todo el lote.
    if (
        i.acto is Acto.INFORMAR
        and i.entidad is Entidad.PAGO
        and PREGUNTA_DE_PAGO.match(crudo)
        and not DIJO_QUE_PAGO.search(crudo)
    ):
        return i.model_copy(update={"acto": Acto.PREGUNTAR, "confianza": "MEDIA"})

    # 2. SEÑALAR ALGO SIN DAR UN DATO ES PREGUNTAR POR ELLO.
    #    «Como va ese», «el anterior como va», «y el otro?»: el modelo dijo
    #    INFORMAR o CONVERSAR, pero acertó la referencia. Nadie «informa» sobre
    #    un pedido que señala y sobre el que no aporta nada.
    if (
        i.referencia.tipo is not TipoReferencia.NINGUNA
        and i.acto in (Acto.INFORMAR, Acto.CONVERSAR, Acto.OTRO)
        and not i.datos.hay_algo()
    ):
        return i.model_copy(
            update={
                "acto": Acto.CONSULTAR,
                "entidad": Entidad.PEDIDO,
                "confianza": "MEDIA",
            }
        )

    # 3. PREGUNTAR POR EL ESTADO SUENA A AFIRMACIÓN.
    #    «Ya está listo mi anillo» salió como CONFIRMAR, y eso le habría
    #    mostrado la pantalla de cobro a alguien que solo preguntaba.
    if PREGUNTA_ESTADO.search(crudo) and not i.datos.hay_algo():
        return i.model_copy(
            update={
                "acto": Acto.CONSULTAR,
                "entidad": Entidad.PEDIDO,
                "atributo": Atributo.ESTADO,
            }
        )

    # 4. DAR NOMBRES ES DAR EL GRABADO.
    #    Python los sacó de la frase, así que el dato es un hecho. El modelo
    #    leyó «Nombre rocky» como PREGUNTAR·CLIENTE y «que diga Luna y Simba»
    #    como CONVERSAR: acertó que no era una compra y se perdió el resto.
    #
    #    No se toca cuando la frase ES una compra («quiero un anillo que diga
    #    Rocky»): ahí manda lo que pide, y el nombre viaja de paso.
    if (i.datos.nombres or i.datos.sin_grabado) and i.acto in (
        Acto.PREGUNTAR,
        Acto.CONVERSAR,
        Acto.OTRO,
        Acto.INFORMAR,
    ):
        return i.model_copy(update={"acto": Acto.INFORMAR, "entidad": Entidad.GRABADO})

    # 4b. TRAER UN DATO ES INFORMARLO.
    #     Nadie escribe «talla 9» por gusto. Cuando el modelo no supo qué
    #     hacer con la frase pero Python sí le sacó un dato del anillo, el
    #     dato manda: se anota. Antes se caía en NO_ENTENDI y la corrección
    #     de la clienta se perdía — justo la corrección, que es el mensaje
    #     que más cuesta que escriba.
    if i.acto is Acto.OTRO and i.datos.hay_algo():
        return i.model_copy(update={"acto": Acto.INFORMAR, "confianza": "MEDIA"})

    # 4a-bis. UNA OBJECIÓN SE CONTESTA COMO OBJECIÓN.
    #         Manda sobre lo que dijera el modelo: si ella dice que le da
    #         miedo pagar por adelantado, la respuesta no puede ser la lista
    #         de cuentas por más que la frase contenga «pagar».
    if not i.datos.hay_algo():
        for patron, atributo in OBJECIONES:
            if re.search(patron, crudo, re.IGNORECASE):
                return i.model_copy(
                    update={
                        "acto": Acto.PREGUNTAR,
                        "atributo": Atributo(atributo),
                        "confianza": "ALTA",
                    }
                )

    # 4a-bis-2. SI LA FRASE DICE «ENVÍO», LA RESPUESTA ES LA DEL ENVÍO.
    #
    # «¿Hacen envíos a Girón?» lo leyó el modelo como PREGUNTAR·ENVIO·TIEMPO y
    # el bot contestó el párrafo de los 10 a 15 días de FABRICACIÓN. Ella no
    # preguntó cuánto tarda el taller: preguntó si le llega y cuánto cuesta.
    #
    # El sustantivo está en la frase o no está, así que esto lo decide Python,
    # igual que los colores y la talla.
    #
    # Y SIN EXCEPCIÓN PARA LAS PALABRAS DE TIEMPO, a propósito. La primera
    # versión respetaba el TIEMPO cuando la frase traía «demora», y eso dejaba
    # dos caminos contestando distinto a la MISMA frase: por aquí salía el
    # tiempo y por `PISTAS_ATRIBUTO` —donde el envío se mira antes— salía el
    # envío. Dos ideas distintas de qué se preguntó es el tipo de fallo que
    # solo aparece cuando cambia el modelo.
    #
    # [POSTERIOR] La respuesta del envío no dice CUÁNTOS DÍAS tarda, y
    # `data/fletes.csv` tiene los días de transporte de cada ciudad. Ponerlos
    # ahí es lo que contestaría de verdad a «¿cuánto demora el envío?».
    if i.atributo is Atributo.TIEMPO and re.search(
        _ENVIO_SUSTANTIVO, crudo, re.IGNORECASE
    ):
        return i.model_copy(
            update={"atributo": Atributo.COSTO_ENVIO, "confianza": "ALTA"}
        )

    # 4a-ter. PREGUNTAR CUÁNDO SE PAGA EL ENVÍO ES PREGUNTAR POR EL ENVÍO.
    #         Manda sobre el modelo por la misma razón que las objeciones: él
    #         ve «pagar» y contesta la lista de bancos, y la pregunta era otra.
    #         La FAQ del envío ya dice cuándo se paga —al recibir— y es la
    #         única respuesta que la deja tranquila.
    if PAGO_DEL_ENVIO.search(crudo) and not i.datos.hay_algo():
        return i.model_copy(
            update={
                "acto": Acto.PREGUNTAR,
                "entidad": Entidad.ENVIO,
                "atributo": Atributo.COSTO_ENVIO,
                "confianza": "ALTA",
            }
        )

    # 4b-bis. PEDIR AYUDA PARA ESCOGER ES PEDIR UNA SUGERENCIA.
    #         Es la petición de servicio más común y la que más venta salva:
    #         quien no sabe qué elegir no elige, y quien no elige no compra.
    if PIDE_AYUDA.search(crudo) and not i.datos.hay_algo():
        return i.model_copy(
            update={
                "acto": Acto.PREGUNTAR,
                "entidad": Entidad.COLOR,
                "atributo": Atributo.NINGUNO,
                "confianza": "ALTA",
            }
        )

    # 4c. «¿Y AHORA QUÉ HAGO?» ES PREGUNTAR POR EL SIGUIENTE PASO.
    #     Va antes de las pistas de atributo porque la frase entera lo dice:
    #     no hay que deducir nada de una palabra suelta.
    if QUE_SIGUE.search(crudo) and not i.datos.hay_algo():
        return i.model_copy(
            update={
                "acto": Acto.PREGUNTAR,
                "entidad": Entidad.PEDIDO,
                "atributo": Atributo.ABONO,
                "confianza": "ALTA",
            }
        )

    # 5. SUMAR NO ES EMPEZAR DE CERO.
    if SUMA_ALGO.search(crudo) and i.acto is Acto.COMPRAR:
        return i.model_copy(update={"acto": Acto.AGREGAR})

    # 5b. PREGUNTAR EL PRECIO ES PEDIR EL CATÁLOGO.
    #     Lo más preguntado del negocio, resuelto sin modelo.
    #
    #     PERO «¿cuánto vale el envío?» NO es preguntar el precio del anillo.
    #     Contestarlo con la lista de precios entera —$200.000, $250.000,
    #     $300.000— es no haber escuchado la pregunta, y era lo que hacía:
    #     «cuánto vale» disparaba esta regla antes de que nadie mirara que la
    #     frase decía «envío».
    if (
        PIDE_PRECIO.search(crudo)
        and not PRECIO_DE_OTRA_COSA.search(crudo)
        and not i.datos.hay_algo()
    ):
        return i.model_copy(
            update={
                "acto": Acto.CONSULTAR,
                "entidad": Entidad.PRODUCTO,
                "confianza": "ALTA",
            }
        )

    # 6. PEDIR INFORMACIÓN, SIN MÁS, ES PEDIR EL PRODUCTO.
    if (
        i.acto in (Acto.PREGUNTAR, Acto.CONSULTAR, Acto.OTRO)
        and i.entidad is Entidad.NINGUNA
        and i.atributo is Atributo.NINGUNO
        and PIDE_INFO.search(crudo)
    ):
        return i.model_copy(update={"acto": Acto.CONSULTAR, "entidad": Entidad.PRODUCTO})

    # 7. RELLENAR EL ATRIBUTO, NUNCA PISARLO.
    #    Si el modelo eligió uno, sabe algo del contexto que una lista de
    #    palabras sueltas no. Aquí solo se completa el hueco.
    if i.atributo is Atributo.NINGUNO and not i.datos.hay_algo():
        for patron, atributo in PISTAS_ATRIBUTO:
            if re.search(patron, crudo, re.IGNORECASE):
                return i.model_copy(update={"atributo": Atributo(atributo)})

    return i
