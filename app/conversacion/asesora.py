"""La asesora: un turno de venta leído entero, con Python de guardia (ADR 0014).

════════════════════════════════════════════════════════════════════════════
EL TURNO
════════════════════════════════════════════════════════════════════════════
    1. CONTEXTO     borrador + charla reciente + pedido activo (de la BD)
    2. JUGADA       [IA] el modelo lee todo y propone: cambios, acciones, mensaje
    3. VALIDAR      `domain.asesora.aplicar`: lo que no cuadra NO se guarda
    4. ACCIONES     Python: fichas, muestrario, guía, pedido, abono, comprobante
    5. VIGILAR      el mensaje no puede traer montos, cuentas ni «pago confirmado»
    6. GUARDAR      borrador, charla, notas para Lía, registro de la decisión

Misma firma que `Pipeline.ejecutar`, así que el servidor no nota la diferencia.
Si el modelo no responde (sin red, sin saldo), la clienta recibe una frase
amable, la conversación pasa a Lía y se avisa al celular (`_si_falla_la_ia`).
El gestor por etiquetas (`respaldo`) queda solo para las pruebas: el 21/09,
con el saldo agotado, sus respuestas fueron bastante peores que dejar que Lía
tome la conversación.
"""

from __future__ import annotations

import json
import logging
import re
import time
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime

from app.conversacion.pipeline import Turno
from app.domain import consumo
from app.domain.asesora import (
    ACCIONES_DE_LOS_ANILLOS,
    ANILLO_SIGUIENTE,
    CHARLA_MAXIMA,
    MAX_ANILLOS,
    MAXIMO_VISTAS,
    PROBLEMAS_GRAVES,
    SUGERENCIAS,
    TALLA_DE_LIA,
    AccionAsesora,
    Borrador,
    Confianza,
    Jugada,
    MensajeReescrito,
    acordar_envio,
    al_dia_lo_que_se_pide,
    anillo_del_mensaje,
    anillos_que_pide,
    aplicar,
    cambia_la_cantidad,
    cantidad_contestada,
    cantidad_de_todos,
    cantidad_respaldada,
    colores_por_anillo,
    contar_anillos,
    contar_lo_pedido,
    cuantas_huellitas_escribio,
    duda_del_comprobante,
    grabado_para_todos,
    habla_de_cadena,
    habla_de_pago,
    habla_de_una_sola_huellita,
    habla_del_corazon,
    llego_un_comprobante,
    lo_que_le_falta,
    otro_anillo_vacio,
    paga_despues,
    parece_un_pago,
    pasar_a_lia_sin_motivo,
    pide_cadena_con_varias,
    pide_las_cuentas,
    pie_de_sugerencia,
    poner_cantidad_a_todos,
    poner_colores,
    poner_grabado_a_todos,
    poner_tallas,
    pregunta_por_cadenas,
    pregunta_por_las_cantidades,
    pregunto_cantidad_con_opciones,
    que_no_se_pide,
    queda_algo_del_anillo,
    quiere_la_cuenta,
    quiere_separar,
    quitar_cadena_no_pedida,
    quitar_pedida_de_envio,
    repite_lo_dicho,
    sin_colores,
    sin_pedir,
    sin_promesas_de_escribir,
    solo_afirma,
    tallas_escritas,
    tallas_para_varios,
    una_sola_pregunta,
    vigilar,
)
from app.domain.catalogo_meta import NOTA_DE_LA_VITRINA
from app.domain.decisiones import registro_del_turno
from app.domain.envio import DatosDeEnvio
from app.domain.faq import (
    CIUDADES_CERCA,
    PUNTO_DE_RECOGIDA,
    SOLO_EN_PLATA,
    UBICACION,
    datos_para_transferir,
    pregunta_por_la_ubicacion,
    pregunta_por_otro_metal,
)
from app.domain.guion import para_las_piezas
from app.domain.personalizacion import (
    EMOJI_COLOR,
    NOMBRE_COLOR,
    Huellita,
    nombres_de_los_colores,
)
from app.domain.pricing import formatear_cop
from app.domain.promociones import linea_del_estado
from app.domain.recordatorios import (
    COLOMBIA,
    el_bot_entendio_que_no,
    no_quiere,
    pide_que_le_escriban,
    pospone,
    quiere_comprar,
    rechaza,
    solo_agradece,
)
from app.domain.respuesta import Respuesta
from app.domain.tallas import (
    no_tiene_anillos,
    pide_la_guia,
    referencia_para_la_clienta,
    talla_dictada,
    talla_texto,
)

log = logging.getLogger("ventabot.asesora")

#: Si la reescritura falla, la pregunta fija de cantidad; nunca dos veces la misma.
PREGUNTAS_DE_CANTIDAD = (
    "¿Me confirmas cuántas huellitas? 😊 ¿De 1 huellita o de 2 huellitas?",
    "¿Lo hacemos de 1 huellita o de 2? 🐾",
    "Para el precio exacto: ¿1, 2 o 3 huellitas? 💍",
)

#: Acciones que no se repiten en dos turnos seguidos. El muestrario y la guía
#: sí se pueden volver a mandar más adelante: Lía lo hace cuando hace falta.
UNA_VEZ = {
    AccionAsesora.MOSTRAR_MUESTRARIO,
    AccionAsesora.MOSTRAR_GUIA_TALLA,
    AccionAsesora.MOSTRAR_EJEMPLOS,
}

#: La presentación va UNA VEZ POR CONVERSACIÓN. Nunca más.
#:
#: En las conversaciones reales de Lía la ficha sale al principio y no vuelve a
#: aparecer: lo que sigue son mensajes de una línea. El bot la reenviaba entera
#: —ficha, dos videos y la foto— cada vez que el modelo pedía MOSTRAR_PRECIOS,
#: y el 20/09 la soltó de nuevo porque la clienta contestó «1». Cinco mensajes
#: con 7 MB de video para responder a un «1».
#:
#: Si más adelante pregunta un precio, se le contesta con una frase: los tres
#: precios están en los hechos que el modelo tiene delante.
SOLO_UNA_VEZ_EN_LA_CHARLA = {
    AccionAsesora.MOSTRAR_PRECIOS,
    AccionAsesora.MOSTRAR_CADENA,
    AccionAsesora.MOSTRAR_CORAZON,
}

#: La cadena (03/10, texto de Camilo tal cual). Solo cuando ELLA pregunta por
#: cadenas o por más productos (`pregunta_por_cadenas`); nunca se ofrece.
MENSAJE_DE_LA_CADENA = (
    "✨ Nuestra cadenita personalizada con la huellita y el nombre de tu mascota tiene "
    "un valor de {precio} ✨\n\n"
    "✅ Hecha en Plata Ley 925.\n"
    "✅ Lleva una huellita, y puedes elegir su color (15 tonos disponibles) y hasta "
    "combinar 🎨🐾.\n"
    "✅ Incluye el nombre de tu mascota grabado.\n\n"
    "Para hacer la tuya, solo necesitas abonar {abono}.\n"
    "Cuando esté lista, te enviamos foto del resultado y luego despachamos 🙌🏼.\n\n"
    "✨ Una joya hecha 100% a mano, personalizada y con mucho amor 💗"
)
#: Las fotos que van con ese mensaje (`data/imagenes/cadena_*.jpg`).
FOTOS_DE_LA_CADENA = ("cadena_1", "cadena_2", "cadena_3")
#: Lo que se le pregunta debajo del mensaje de la cadena.
PREGUNTA_DE_LA_CADENA = "¿Te gustaría hacer la tuya? 💗"

#: Las fotos del anillo de corazón (`data/imagenes/anillo_corazon_*.jpg`).
#: Las dos son del mismo anillo en su estuche: va una, la otra queda de repuesto.
FOTOS_DEL_CORAZON = ("anillo_corazon_1",)
#: Lo que se le pregunta debajo de su presentación.
PREGUNTA_DEL_CORAZON = "¿Te gustaría hacer el tuyo? 💗"
#: Si la pide con más de una huellita (09/10): la cadena lleva UNA, siempre
#: (`HUELLITAS_DE_LA_CADENA`). Lo dice el sistema, no el modelo: sin ambigüedad.
CADENA_CON_UNA = (
    "La cadenita se hace con una sola huellita 🐾 Si quieres más de una, el anillo "
    "sí puede llevar hasta 3 💍"
)
#: La frase del modelo que dice lo mismo («La cadenita lleva una sola huellita,
#: linda 💗»): se quita cuando ya lo dice el sistema.
_UNA_SOLA_HUELLITA = re.compile(
    r"[^.!?\n]*\b(?:una\s+sola|solo\s+una|lleva\s+una|una\s+[uú]nica)\s+huellit"
    r"[^.!?\n]*[.!?]?\s*",
    re.I,
)

#: Cuando no le interesa (10/10): gracias, sin vender, sin preguntar, sin
#: prometer escribirle.
SI_ALGUN_DIA = "¡Gracias por contarme! 🫶 Si algún día te animas, aquí estoy 💓"
#: La IA ya se despidió (13/10, a «uff está como caro»): debajo no va la pregunta
#: de relleno, que la contradice («…aquí estoy 💓» + «¿De cuántas huellitas…?»).
_SE_DESPIDE = re.compile(r"si\s+algun\s+dia\s+te\s+animas|cuando\s+quieras\s+retomarlo")


#: Le da miedo abonar o desconfía (Nora, 13/10: «no me gusta que tiene que dar
#: vueltas lata adelantada»). Ahí se la tranquiliza (prompt, CUANDO LE DA MIEDO
#: ABONAR) y el sistema NO le pega «¿De cuántas huellitas…?» debajo.
_MIEDO_A_ABONAR = re.compile(
    r"\badelantad[oa]s?\b|\bpor\s+adelantado\b"
    r"|\b(?:plata|dinero|pagar|pago|consignar|transferir|abonar|abono|mandar\s+plata)\s+"
    r"(?:antes|primero)\b"
    r"|\b(?:estafa\w*|estafen|robo|roben|fraude|engan\w*|tumbe\w*|tumban)\b"
    r"|\bdesconf\w*|\bconfiar\b|\bconfianza\b|\bmiedo\b|\bme\s+da\s+(?:susto|cosa|nervios)\b"
    r"|\bcomo\s+se\s+que\b|\by\s+si\s+no\s+(?:me\s+)?(?:llega|cumplen|lo\s+hacen|responden)\b"
    r"|\bno\s+(?:los|las|te|la)\s+conozco\b"
)


def teme_abonar(texto: str) -> bool:
    plano = "".join(
        c
        for c in unicodedata.normalize("NFKD", (texto or "").lower())
        if not unicodedata.combining(c)
    )
    return bool(_MIEDO_A_ABONAR.search(plano))


#: Una frase que PROMETE mandar el resumen («En unos minutos te comparto el
#: resumen de tu anillo para confirmar…»). Sobra si el resumen ya salió.
_PROMETE_EL_RESUMEN = re.compile(
    r"[^.!?\n]*\b(?:te\s+)?(?:compart\w*|mand\w*|pas[oa]\w*|env[ií]\w*)"
    r"\s+(?:el|tu)\s+resumen\b[^.!?\n]*[.!?]?[^\S\n]*",
    re.I,
)


def se_despide(texto: str) -> bool:
    plano = "".join(
        c
        for c in unicodedata.normalize("NFKD", (texto or "").lower())
        if not unicodedata.combining(c)
    )
    return bool(_SE_DESPIDE.search(plano))


#: Lo deja para después («apenas lo haga le escribo y elijo el modelo», «el otro
#: mes»): se acepta con cariño y se le ofrece UNA vez dejar el anillo listo, para
#: que lo que hará después sea lo único pendiente (Camilo, 13/10: «que se sienta
#: cordial, que escucha, no un robot hostil»). Clave en `Borrador.mostrado_en`.
OFRECE_DEJARLO_LISTO = "OFRECE_DEJARLO_LISTO"
DEJARLO_LISTO = (
    "¡Claro, sin afán! 🫶 ¿Te gustaría que mientras tanto dejemos tu anillo "
    "personalizado listo? Así solo quedaría{n} pendiente{s} {pendiente}. Y si no, igual "
    "quedo muy atenta {atenta}"
)
#: Ya está diseñando y solo deja la talla para después: se acepta y se sigue.
SEGUIMOS_DISENANDO = (
    "¡Claro, sin afán! 🫶 Mientras tanto vamos dejando listo tu anillo, y así solo "
    "quedaría{n} pendiente{s} {pendiente}. {pregunta}"
)
#: Lo que cuenta como «diseñarlo»: si ya está, no hay nada que dejar listo.
_LO_DEL_DISENO = frozenset({"cantidad de huellitas", "colores", "grabado"})
_HABLA_DE_LA_TALLA = re.compile(
    r"\b(?:talla|medida|medir\w*|mida|mido|regla|joyer[ií]a)\b", re.I
)


#: Ofrecer separarlo con el abono y la talla después (13/10). Clave en
#: `Borrador.mostrado_en`: va UNA vez.
OFRECE_SEPARAR = "OFRECE_SEPARAR"
SEPARAR_SIN_TALLA = (
    "Si quieres, ya lo puedes separar con el abono de {abono} y la talla me la "
    "mandas cuando la tengas 📏💍 ¿Te gustaría?"
)


def ofrecer_separar(b: Borrador, abono: str) -> str:
    """Solo le falta la talla y no la tiene a mano (dijo que la manda después, va
    a la joyería o ya tiene la guía): el ofrecimiento, o "". Lo que la IA iba a
    preguntar sobra: lo único que falta es la talla, que no se le pide (13/10,
    charla de prueba: «¿La tienes o prefieres que te comparta la guía?»)."""
    if (
        b.talla_despues
        or b.talla is not None
        or b.es_cadena
        or OFRECE_SEPARAR in b.mostrado_en
        or b.falta_para_abono() != ["talla"]
    ):
        return ""
    sin_talla_a_mano = (
        "talla" in b.lo_manda_despues
        or SIN_ANILLOS in b.mostrado_en
        or b.mostrado_en.get("MOSTRAR_GUIA_TALLA", b.turnos) < b.turnos
    )
    return SEPARAR_SIN_TALLA.format(abono=abono) if sin_talla_a_mano else ""


def ofrecer_dejarlo_listo(b: Borrador, texto: str) -> str:
    """El ofrecimiento, si toca: lo deja para después, no es un «no», todavía falta
    diseñar y no se le ha ofrecido antes. Si no toca, ""."""
    if (
        "?" in texto
        or not pospone(texto)
        or rechaza(texto)
        or pide_que_le_escriban(texto)
        or OFRECE_DEJARLO_LISTO in b.mostrado_en
        # Tocó «Más adelante» en un recordatorio: ofrecerle algo es insistir.
        or re.fullmatch(r"\W*m[aá]s\s+adelante\W*", texto, re.I)
    ):
        return ""
    falta = b.falta_para_abono()
    if not _LO_DEL_DISENO & set(falta):
        return ""
    talla = "talla" in falta
    # Lo que hará después es medirse si lo dice, si ya lo dejó anotado o si le
    # acaba de llegar la guía («Vale apenas lo haga le escribo», 11/10).
    la_talla = talla and (
        "talla" in b.lo_manda_despues
        or bool(_HABLA_DE_LA_TALLA.search(texto))
        or "MOSTRAR_GUIA_TALLA" in b.mostrado_en
    )
    n, s = ("n", "s") if talla else ("", "")
    pendiente = "la talla y el abono" if talla else "el abono"
    # Ya está diseñando y lo que deja para después es medirse: no se le pide
    # permiso para algo que ya está haciendo; se sigue con lo siguiente.
    empezo = bool(b.cantidad or b.huellitas or b.grabado)
    if empezo and la_talla and not no_quiere(texto):
        siguiente = next(
            q for q in ("cantidad de huellitas", "colores", "grabado") if q in falta
        )
        pregunta = pregunta_de(siguiente, b) or COMO_SE_PREGUNTA[siguiente]
        return SEGUIMOS_DISENANDO.format(n=n, s=s, pendiente=pendiente, pregunta=pregunta)
    return DEJARLO_LISTO.format(
        n=n,
        s=s,
        pendiente=pendiente,
        atenta=(
            "a cuando tengas la foto de la medida 📏💍"
            if la_talla
            else "para cuando quieras 💍"
        ),
    )


#: Con las cuentas ya mandadas y sin pago todavía. Explícito —falta SU
#: comprobante, no lo tenemos— y termina preguntando sin apurarla (Camilo, 21/09).
#: Lo que se le dice al recibir un comprobante que el modelo quiso cuestionar
#: (04/10): el bot no juzga pagos; Lía lo verifica.
COMPROBANTE_RECIBIDO = (
    "¡Recibido! 🙌 Lía revisa tu comprobante y te confirma apenas lo verifique 💓"
)
#: Dijo que pagó sin mandar el comprobante (04/10): se le pide, con cariño.
PIDE_EL_COMPROBANTE = (
    "¡Recibido! 🙌 ¿Me compartes el comprobante, porfa? Así Lía lo verifica más rápido 💓"
)
#: Lo que va UNA vez, debajo de las cuentas. Sin signos de pregunta (Camilo,
#: 07/10: «si acaso le dices que cualquier inquietud se la haces saber, sin que
#: ella con unos signos de interrogación esté obligada a responder»). Antes
#: cerraba con «¿Te puedo ayudar con algo más?» y, en cada «gracias» mientras
#: iba a pagar, rotaba otras preguntas: con Mónica salieron cinco seguidas.
QUEDO_ATENTA = "Quedo atenta a tu comprobante 💓 Cualquier duda, me cuentas 🫶"
QUEDO_ATENTA_SALDO = (
    "Quedo atenta a tu comprobante del saldo 💓 Cualquier duda, me cuentas 🫶"
)

#: El problema del vigilante cuando el modelo escribe una cuenta o un teléfono.
CUENTA_A_MANO = "número de cuenta o teléfono escrito por el modelo"

#: El problema del vigilante que da el anillo por entrado al taller sin abono.
TALLER_SIN_ABONO = "dice que el pedido entra al taller sin el abono"

#: Las que solo dicen CUÁNDO paga el envío (ver `acordar_envio`).
ACCIONES_DEL_ENVIO = {AccionAsesora.ENVIO_CON_SALDO, AccionAsesora.ENVIO_AL_RECIBIR}

GUIA_TALLA = (
    "Con un anillo que conserve su forma redonda y una regla, lo vas a medir "
    "*en toda la mitad del anillo* 📏 Me regalas por favor una foto para "
    "revisarte qué talla sería :)"
)

#: Si no tiene anillos para medir: el contorno del dedo con una tira de papel o
#: un hilo, con el video (Camilo, 13/10: «ir a la joyería para gente que no
#: tenga anillo puede ser un cuello de botella importante»). Es lo que se le dijo
#: a Laura el 05/10 y con eso abonó. Antes (Lía, 05/10) se mandaba a la joyería
#: porque «medir el dedo es muy inexacto»: la talla la sigue confirmando Lía
#: (`tallas.CONTORNO_CM` da las posibles).
TALLA_SIN_ANILLOS = (
    "¡No te preocupes! 🫶 Puedes medir el contorno de tu dedo con una tira de papel "
    "o un hilo: lo pones alrededor del dedo, marcas donde se une y mides esa "
    "longitud con una regla 📏 Te dejo un video cortico de cómo se hace 👇"
)
VIDEO_DEL_DEDO = "medir_talla_dedo"
PIE_DEL_VIDEO_DEL_DEDO = "Cuando lo midas, me cuentas cuántos centímetros te da 💍"
#: Lo que el modelo escribe proponiendo medir el dedo (lo dice el sistema).
_MIDE_EL_DEDO = re.compile(
    r"[^.!?\n]*\b(?:tira\s+de\s+papel|hilo|cinta|contorno\s+de(?:l|\s+tu)\s+dedo"
    r"|alrededor\s+de(?:l|\s+tu)\s+dedo)\b[^.!?\n]*[.!?]?[^\S\n]*",
    re.I,
)
#: Lo que acompaña a la guía del dedo si todavía falta escoger algo del anillo.
MIENTRAS_TANTO = "Mientras tanto, si quieres, vamos armando tu anillo ✨"
#: La pregunta por la medida del dedo que acompaña a «mídete el dedo».
_PIDE_LOS_CM = re.compile(
    r"[^.!?\n]*\b(cent[ií]metros|mil[ií]metros|cu[aá]nto\s+(te\s+)?(da|mide))\b"
    r"[^.!?\n]*[.!?]?",
    re.I,
)
#: En `mostrado_en`: cuándo se le dijo cómo medirse sin anillo (no se repite
#: seguido). El valor viejo se conserva: las charlas guardadas lo traen.
SIN_ANILLOS = "TALLA_EN_JOYERIA"

#: Que habla de pagar (para confiar en que la IA pidió MANDAR_CUENTAS por ella).
_HABLA_DE_PAGAR = re.compile(
    r"pag|abon|transf|consign|cuenta|nequi|daviplata|bancolombia|llave|plata", re.I
)
#: Las frases del modelo que frenan el pago («para poder iniciar me faltan…»):
#: con la cuenta mandada porque ella la pidió, sobran.
_SIN_LO_QUE_FALTA = re.compile(
    r"[^.!?¡¿\n]*\b(falt\w*|necesit\w*|para\s+poder|antes\s+de|primero)\b"
    r"[^.!?\n]*[.!?]?",
    re.I,
)
#: Cómo se nombra, con cariño, cada cosa que falta (debajo de la cuenta).
_LO_QUE_FALTA_EN_PALABRAS = {
    "cantidad de huellitas": "de cuántas huellitas lo quieres",
    "talla": "tu talla",
    "colores": "los colores",
    "grabado": "el nombre que quieres grabar",
    "nombre completo": "tu nombre completo",
}


def lo_que_falta_al_pagar(falta: list[str], b: Borrador) -> str:
    """Debajo de la cuenta, UNA sola cosa: «Cuando puedas, ¿me compartes tu
    talla para dejar tu pedido completo? 🫶». Vacío si lo que falta es de Lía
    (la talla por confirmar).

    Una pregunta útil a la vez (Camilo, 09/10). Antes (06/10) se juntaban hasta
    3 cosas en una pregunta; contestaba una y las otras quedaban en el aire. Lo
    que siga faltando se pregunta en el turno siguiente, una por una."""
    # La talla no, si ya está en eso (le llegó la guía o lo de la joyería): no
    # se le vuelve a pedir mientras mide.
    midiendo = SIN_ANILLOS in b.mostrado_en or (
        AccionAsesora.MOSTRAR_GUIA_TALLA.value in b.mostrado_en
    )
    no_pedir = que_no_se_pide(b)
    for que in falta:
        if que in no_pedir:
            continue
        if que.startswith(ANILLO_SIGUIENTE):
            if not queda_algo_del_anillo(b, que):
                continue
            texto = "lo del otro anillo"
        else:
            texto = _LO_QUE_FALTA_EN_PALABRAS.get(que, "")
            if que == "talla" and midiendo:
                continue
        if texto:
            return (
                f"Cuando puedas, ¿me compartes {texto} para dejar tu pedido completo? 🫶"
            )
    return ""


#: En `mostrado_en`: cuándo se le explicó lo de «solo en plata» (05/10).
PLATA = "SOLO_EN_PLATA"
#: En `mostrado_en`: cuándo se le dijo dónde estamos (09/10).
UBICADOS = "UBICACION"
#: En `mostrado_en`: ya se crearon los anillos que ella dijo que compra (12/10).
ANILLOS_DICHOS = "ANILLOS_DICHOS"
#: Si el mensaje trae OTRA cosa además del metal, lo contesta el modelo (con la
#: regla de la plata dicha por el sistema encima).
_OTRO_TEMA = re.compile(
    r"\b(precio|cu[aá]nto|cuesta|vale|valor|talla|env[ií]\w*|pag\w*|cuenta|abono"
    r"|demora|d[ií]as|cadena|huellit\w*|grab\w*|nombre|coraz\w*|ded\w*)",
    re.I,
)
#: La última pregunta que hizo el bot («¿Sabes tu talla…? 💍💜»).
_PREGUNTA = re.compile(r"¿[^¿?\n]*\?(?:[ \t]*[^\w\s¿?]+)*")
#: La coletilla que vuelve pregunta una frase que no pregunta nada: «…te paso el
#: resumen, ¿te parece?», «…en unos minutos, ¿sí?».
_COLETILLA = re.compile(
    r",?\s*¿\s*(te\s+parece|s[ií]|vale|listo|ok|dale|bien|de\s+acuerdo)\s*\?", re.I
)
#: Ofrece contar lo que ya se le está mandando: «¿Quieres que te cuente cómo
#: es?», «¿Te mando la información?».
_OFRECE_CONTAR = re.compile(
    r"¿[^¿?\n]*\b(cuente|cuento|cont[aá]rte|mande|mando|comparta|comparto|env[ií]e)"
    r"\b[^¿?\n]*\?(?:[ \t]*[^\w\s¿?]+)*",
    re.I,
)
_AGRADECE = re.compile(r"\bgraci|\bmil\s+gracias|\bmuy\s+amable|\bdios\s+te", re.I)


def nada_que_preguntarle(b: Borrador, estado: str = "") -> bool:
    """¿No le falta nada a ELLA? Lo que sigue lo hace Lía (confirmar la talla,
    verificar un pago, el taller, el despacho) o ya pagó. Ahí no se le pregunta
    por preguntar (Camilo, 06/10)."""
    if estado in SIN_NADA_QUE_PREGUNTAR:
        return True
    if b.pagado_sin_pedido:
        # Pagó con el pedido a medias: si todavía falta algo de ella (colores,
        # grabado, su nombre), se le sigue pidiendo (prueba de verdad, 07/10).
        return b.falta_para_abono() in ([], [TALLA_DE_LIA])
    if b.abono_reportado or b.saldo_reportado:
        return True
    # Ya tiene las cuentas y no le falta ningún dato: lo único pendiente es que
    # pague, y eso no se persigue (Mónica, 07/10).
    if (
        b.cuentas_enviadas
        and estado in ("", "ESPERANDO_ANTICIPO")
        and not b.falta_para_abono()
    ):
        return True
    return not b.pedido_id and b.falta_para_abono() == [TALLA_DE_LIA]


#: Pide confirmar lo que ella acaba de decir: «¿Así quedan los dos nombres?»,
#: «¿Will es el nombre que quieres grabar?», «¿Está bien así?».
_CONFIRMA_LO_DICHO = re.compile(
    r"¿[^¿?\n]*\b(as[ií]\s+(quedan?|qued[oó]|est[aá]|lo\s+dejamos|te\s+gusta)"
    r"|es\s+(el|ese)\s+nombre|est[aá]\s+bien\s+as[ií]|confirm\w+|correcto"
    r"|lo\s+dejamos\s+as[ií])\b[^¿?\n]*\?(?:[ \t]*[^\w\s¿?]+)*",
    re.I,
)


#: Las preguntas por la cantidad y por la talla, para no hacerlas si ya están.
_PIDE_LA_CANTIDAD = re.compile(
    r"¿[^¿?\n]*(cu[aá]ntas\s+huellitas|\b1\s*,\s*2\s*o\s*3\b|\bde\s+1\s+o\s+(de\s+)?2\b)"
    r"[^¿?\n]*\?(?:[ \t]*[^\w\s¿?]+)*",
    re.I,
)
_PIDE_LA_TALLA = re.compile(
    r"¿[^¿?\n]*(sabes\s+tu\s+talla|qu[eé]\s+talla\s+(eres|usas|tienes)|cu[aá]l\s+es\s+tu\s+talla)"
    r"[^¿?\n]*\?(?:[ \t]*[^\w\s¿?]+)*",
    re.I,
)


def sin_pedir_lo_anotado(texto: str, b: Borrador) -> str:
    """Sin la pregunta por la cantidad o la talla si ya están anotadas. Real
    (Mónica, 07/10): «De una» quedó anotado y la IA igual preguntó «¿Lo quieres
    de 1, 2 o 3 huellitas?»; dijo su talla y le volvieron a preguntar si la sabía."""
    if b.cantidad is not None:
        texto = _PIDE_LA_CANTIDAD.sub("", texto or "")
    if b.talla is not None:
        texto = _PIDE_LA_TALLA.sub("", texto or "")
    return re.sub(r"[ \t]{2,}", " ", texto or "").strip()


def cambio_anotado(antes: Borrador, despues: Borrador) -> bool:
    """¿Quedó anotado algo de lo que dijo (grabado, colores, talla, cantidad,
    su nombre)? Entonces confirmárselo es preguntar de más."""
    return any(
        getattr(antes, campo) != getattr(despues, campo)
        for campo in ("grabado", "huellitas", "talla", "cantidad", "nombre_clienta")
    )


def sin_confirmar_lo_dicho(texto: str) -> str:
    return re.sub(r"[ \t]{2,}", " ", _CONFIRMA_LO_DICHO.sub("", texto or "")).strip()


#: Una pregunta con lo que la introduce, si va pegado con coma o dos puntos:
#: «Para pasar tu pedido al taller, ¿me compartes…?» se va entera (si no,
#: queda «Para pasar tu pedido al taller,» colgando).
_PREGUNTA_CON_SU_FRASE = re.compile(
    r"(?:[A-Za-zÁÉÍÓÚÜÑáéíóúüñ][^.!?¡¿\n]*[,:][ \t]*)?"
    r"¿[^¿?\n]*\?(?:[ \t]*[^\w\s¿?]+)*"
)
#: Lo que se le sigue pidiendo aunque ya haya pagado: el comprobante.
_PIDE_EL_SOPORTE = re.compile(r"comprobante|soporte|captura|pantallazo", re.I)


def sin_preguntas_de_mas(texto: str) -> str:
    """El mensaje sin sus preguntas (ni la coletilla «¿te parece?»), salvo la
    que pide el comprobante (eso sí le toca a ella)."""

    def mirar(m: re.Match) -> str:
        return m.group(0) if _PIDE_EL_SOPORTE.search(m.group(0)) else ""

    limpio = _PREGUNTA_CON_SU_FRASE.sub(mirar, _COLETILLA.sub("", texto or ""))
    return re.sub(r"[ \t]{2,}", " ", limpio).strip()


def con_comillas(texto: str, grabado: list[str]) -> str:
    """«Bombom 🐾 ¡qué lindo!» -> «"Bombom" 🐾…»: lo que va en el aro, entre
    comillas latinas, para que sepa exactamente qué se graba."""
    nombres = [g.strip() for g in grabado or [] if g.strip()]
    # Primero el grabado entero («Toby ♡ Nala»), después cada renglón. Lo que
    # ya va entre comillas no se toca (Mónica, 07/10: «Campanita ♡ Dulce ♡
    # Eva…» quedaba «Campanita ♡ «Dulce» ♡ «Eva»…»).
    candidatos = ([" ♡ ".join(nombres)] if len(nombres) > 1 else []) + sorted(
        set(nombres), key=len, reverse=True
    )
    for renglon in candidatos:
        trozos = re.split(r"(«[^«»]*»|\"[^\"]*\"|“[^”]*”)", texto or "")
        for i in range(0, len(trozos), 2):  # los pares quedan fuera de comillas
            trozos[i] = re.sub(
                rf"(?<![«\"“'\w]){re.escape(renglon)}(?![»\"”'\w])",
                f"«{renglon}»",
                trozos[i],
                flags=re.I,
            )
        texto = "".join(trozos)
    return texto


#: Las frases del modelo sobre el metal: con la regla dicha por el sistema, se
#: quitan (si no, la clienta lee dos veces lo mismo, con otras palabras).
_HABLA_DEL_METAL = re.compile(
    # «¿» también corta: «…en plata 😊 ¿Sabes tu talla?» deja la pregunta.
    r"[^.!?¡¿\n\x01]*\b(plata|oro|dorad\w*|ba[ñn]os?|metal\w*|enchapad\w*)\b"
    r"[^.!?¿\n\x01]*[.!?]?",
    re.I,
)
#: Un emoji seguido de mayúscula también cierra una frase («…Ley 925 😊 Se
#: demora…»): sin esto, quitar lo del metal se llevaba lo que seguía.
_FIN_CON_EMOJI = re.compile(
    "([\U0001f300-\U0001faff\u2600-\u27bf\u2b50])\\s+(?=[A-ZÁÉÍÓÚÑ¿¡])"
)


def sin_lo_del_metal(texto: str) -> str:
    """El mensaje del modelo sin sus frases sobre el metal (las dice el sistema)."""
    marcado = _FIN_CON_EMOJI.sub("\\1\x01", texto or "")
    limpio = _HABLA_DEL_METAL.sub("", marcado)
    return re.sub(r"[ \t]*\x01[ \t]*", " ", limpio).strip()


def solo_pregunta_por_el_metal(texto: str | None) -> bool:
    """«Solo en plata? No hay dorado?»: corto, sin números y sin nada más."""
    dicho = (texto or "").strip()
    return (
        bool(dicho)
        and len(dicho) <= 70
        and not _TRAE_NUMERO.search(dicho)
        and pregunta_por_otro_metal(dicho)
        and not _OTRO_TEMA.search(dicho)
    )


def pregunta_abierta(ultimo_del_bot: str) -> str:
    """La última pregunta del bot, para volver a ella. Vacío si no hubo."""
    preguntas = _PREGUNTA.findall(ultimo_del_bot or "")
    return preguntas[-1].strip() if preguntas else ""


#: «No sé mi talla», dicho de las formas en que lo dice la gente.
#:
#: Solo se usa cuando lo ÚLTIMO que dijimos fue la pregunta de la talla y el
#: mensaje no trae ningún número: es contestar a una pregunta nuestra, cerrada,
#: hecha un segundo antes. No es adivinar intenciones en general — eso ya se
#: intentó con el gestor por etiquetas y por eso existe la asesora (ADR 0014).
_PIDE_LA_GUIA = re.compile(
    r"^\W*("
    # «no se PUEDE…», «no se HACE…» no es «no sé» (17/10).
    r"(no|ni)\s+(la\s+)?(s[eé](?!\s+(pued|hac|manej|acept|permit|pag|env))|tengo|idea)\b"
    r"|ni\s+idea"
    r"|(me\s+)?(la\s+)?(comp[aá]rt\w*|compart\w*|m[aá]nd\w*|env[ií]\w*"
    r"|p[aá]sa\w*|reg[aá]l\w*)"
    r"|(la|una)\s+gu[ií]a"
    r"|gu[ií]a"
    r"|dale"
    r"|(s[ií]\s+)?porfa(vor)?"
    r")\b",
    re.I,
)
#: Una PREGUNTA solo pide la guía si la nombra («¿me la compartes?»).
_NOMBRA_LA_GUIA = re.compile(
    r"gu[ií]a|comp[aá]rt|m[aá]nd|env[ií][ae]|p[aá]sa|reg[aá]l|talla|medi", re.I
)
#: Si escribe un número, puede ser su talla: eso lo mira el modelo.
_TRAE_NUMERO = re.compile(r"\d")
#: Que ELLA habla de una talla: un número, «talla», «medida», la talla en
#: letras o dictada («gamma seis», «taya siete», «5 y medio»).
_HABLA_DE_UNA_TALLA = re.compile(
    r"\d|\btallas?\b|\btaya\b|\bgamma\b|\bmedid\w*|\bmid[eoaií]\w*|\bmed[ií]\w*"
    r"|\b(?:cuatro|cinco|seis|siete|ocho|nueve|diez|diéz|once|doce|trece)\b",
    re.I,
)

#: Un primer mensaje que no es de alguien que viene a comprar: reclamo,
#: devolución, estafa, insulto, o alguien que YA compró («me llegó el anillo y
#: se le cayó una piedrita», «¿tiene garantía?»). Corto a propósito: una
#: clienta nueva con esto de más se queda sin su apertura gratis y pasa por el
#: modelo (unos segundos y unos pesos), que es poco; una queja con el catálogo
#: encima, no.
_QUEJA_DE_ENTRADA = re.compile(
    r"\b(estaf\w*|ladr[oó]n\w*|rob[oa]\w*|devuel\w*|devoluci[oó]n|reembols\w*"
    r"|reclam\w*|queja\w*|demand\w*|denunci\w*|mierda|hijueputa|hp|gonorrea"
    r"|malparid\w*|idiota\w*|est[uú]pid\w*|no me (lleg[oó]|sirvi[oó]|qued[oó])"
    r"|lleg[oó] (da[nñ]ad|rot|mal)\w*|garant[ií]a\w*"
    r"|me lleg[oó] (el|mi|la) (anillo|pedido|joya|paquete|encomienda)"
    r"|se (le |me )?(cay|rompi|zaf|despeg|pel[oó]|oxid)\w*)\b",
    re.I,
)

#: La frase con la que el modelo le pide SU nombre (el del pedido, no el del
#: grabado): desde el último punto o signo hasta el «?» que la cierra. Así se
#: quita entera, con su «¿dale?» o su «¿sí?» del final.
_PIDE_SU_NOMBRE = re.compile(
    r"[^.!?¡\n]*\b(a\s+nombre\s+de\s+qui[eé]n|tu\s+nombre|nombre\s+completo"
    r"|nombre\s+para\s+el\s+pedido)\b[^?\n]*\?",
    re.I,
)


#: Regla de Lía (29/09): la talla la confirma ELLA antes del abono. Lo que
#: se le dice a la clienta cuando manda la foto de la regla o escribe la medida.
TALLA_EN_REVISION = (
    "¡Gracias por la medida! 📏 En unos minutos te confirmo tu talla 💍 "
    "Mientras tanto seguimos armando tu anillo 🥰"
)
#: Si manda otra foto de la regla con la primera todavía en revisión.
OTRA_MEDIDA = (
    "¡Recibida esta también! 📏 Lía las mira juntas y en unos minutos te confirmo "
    "la talla 💍"
)
#: Cuando ya está todo menos la talla: no se le pide nada, se le dice qué pasa.
TALLA_EN_ESPERA = (
    "¡Ya casi! 🙌 Solo me falta confirmarte la talla. En unos minutos te la "
    "confirmo y te paso el resumen para el abono 💓"
)
#: Lo que le llega cuando Lía la confirma en el panel (si Lía no escribió otro).
TALLA_CONFIRMADA = "¡Listo! 💍 Ya revisé tu medida: tu talla es la {talla}."
#: Lo que dice que una foto es de la regla (lo que el modelo leyó de ella).
_HABLA_DE_TALLA = re.compile(
    r"\b(regla|medid\w*|mide|talla|di[aá]metro|cent[ií]metro)", re.I
)

#: Lo que se le dice cuando ninguna IA contesta. UNA vez por caída (29/09).
MOMENTICO = "¡Hola! 💓 Dame un momentico y ya te atiendo 🙌"

#: Cuántas notas internas de Lía lee el modelo: las últimas, que son las que
#: valen (una talla confirmada deja vieja a la estimación de antes).
NOTAS_INTERNAS_AL_MODELO = 6

#: Lo que se le dice al modelo de lo que llega SIN archivo (27/09). `{}` es el
#: detalle: el emoji, la dirección, el contacto.
_SIN_ARCHIVO = {
    "unsupported": (
        "algo que WhatsApp NO deja ver (una foto o video «de una sola vista», una "
        "encuesta o un evento): no sabes qué era. No adivines; pídele con cariño "
        "que lo mande de nuevo como foto o mensaje normal"
    ),
    "reaction": "una reacción {} a uno de los mensajes (no escribió nada más)",
    "location": "su ubicación: {}",
    "contacts": "un contacto: {}",
}


#: Es un regalo o para otra persona («es para regalarle a mi hija pero ella no
#: vive conmigo», 12/10 y prueba del 13/10): la guía va con lo que le sirve a
#: ELLA, que no tiene el dedo a la mano. «Me regalas la guía» (=dame) no cuenta.
_PARA_OTRA_PERSONA = re.compile(
    r"\bregal(?:o|ar|arle|arselo|arsela|arles)\b|\bsorpresa\b"
    r"|\bpara\s+(?:mi|la|el)\s+(?:hija|hijo|mama|mami|novia|novio|esposa|esposo|hermana"
    r"|hermano|amiga|tia|abuela|prima|suegra|sobrina|nieta|pareja)\b"
)
GUIA_PARA_REGALO = (
    "¡Qué lindo regalo! 🥰 Te comparto la guía para que se la pases: ella puede medir "
    "un anillo suyo con una regla y mandarte la foto, o el contorno de su dedo con una "
    "tira de papel y decirte los centímetros 📏"
)


#: El primer mensaje ya trae datos de SU pedido: cuántas huellitas, la talla, un
#: color o lo que va grabado. «Quiero más información» o «precio?» no.
_TRAE_DATOS = re.compile(
    r"\b(?:1|2|3|una|dos|tres)\s+huellit|\btalla\s*(?:es\s+|de\s+)?\d"
    r"|\bque\s+diga\b|\bgrabad[oa]\b|\bgrabarle\b"
    r"|\b(?:rosad[oa]|rosa|fucsia|lila|morad[oa]|azul|celeste|turquesa|negr[oa]|blanc[oa]"
    r"|roj[oa]|verde|amarill[oa]|naranja|champagne)\b"
)


#: «¿Cuánto vale un anillo con dos huellitas?» pregunta el precio: la apertura de
#: siempre le contesta (y no anota nada que no decidió).
_PREGUNTA_EL_PRECIO = re.compile(
    r"\b(?:cuanto|precio|precios|vale|valor|cuesta|cuestan)\b"
)

#: Lo que trae un primer mensaje «de cajón»: saludos, el texto que pone el
#: anuncio («¡Hola! Quiero más información», «Hello! Can I get more info on
#: this?») y pedir precio. Si quitando esto le queda algo, contó algo suyo.
_RELLENO_DE_ARRANQUE = frozenset(
    [
        "hola",
        "holi",
        "buenas",
        "buenos",
        "buen",
        "dia",
        "dias",
        "tardes",
        "noches",
        "saludos",
        "hello",
        "hi",
        "hey",
        "quiero",
        "quisiera",
        "queria",
        "me",
        "gustaria",
        "gustaria",
        "saber",
        "mas",
        "info",
        "informacion",
        "sobre",
        "acerca",
        "de",
        "del",
        "los",
        "las",
        "el",
        "la",
        "lo",
        "un",
        "una",
        "unos",
        "unas",
        "este",
        "esta",
        "esto",
        "ese",
        "eso",
        "anillo",
        "anillos",
        "huellita",
        "huellitas",
        "producto",
        "productos",
        "precio",
        "precios",
        "cuanto",
        "cuesta",
        "cuestan",
        "vale",
        "valor",
        "y",
        "a",
        "en",
        "por",
        "favor",
        "porfa",
        "gracias",
        "please",
        "can",
        "i",
        "get",
        "more",
        "on",
        "this",
        "about",
        "vi",
        "visto",
        "tu",
        "su",
        "sus",
        "anuncio",
        "publicidad",
        "instagram",
        "insta",
        "facebook",
        "face",
        "pagina",
        "interesa",
        "interesan",
        "dar",
        "puedes",
        "podrias",
        "me",
        "regalas",
        "envias",
        "enviar",
        "pasar",
        "pasas",
        "ok",
        "okey",
        "que",
        "tiene",
        "tienen",
        "hacer",
        "pedido",
        "requiero",
        "necesito",
        "con",
        "uno",
        "dos",
        "tres",
        "llego",
    ]
)


def es_un_arranque_de_cajon(texto: str | None) -> bool:
    """¿El primer mensaje es solo el saludo o el texto del anuncio? (17/10)

    La apertura fija no pasa por la IA: está bien para «Quiero más
    información», pero a «es para mi hermana, se le murió su perrita hace un
    mes» le contestaba «¿Cómo se llama tu peludito?» sin leerla. Si cuenta algo
    suyo, la lee la IA.
    """
    plano = "".join(
        c
        for c in unicodedata.normalize("NFKD", (texto or "").lower())
        if not unicodedata.combining(c)
    )
    palabras = re.findall(r"[a-zñ]+", plano)
    return len([p for p in palabras if p not in _RELLENO_DE_ARRANQUE]) <= 1


#: La apertura de prueba (13/10): la foto de un anillo real con el nombre
#: grabado y la pregunta por su peludito. Clave en `mostrado_en`. 15/10 (Camilo):
#: la foto es el collage «Inspirado en tu mascota» (seis anillos con nombres).
APERTURA_PELUDITO = "APERTURA_PELUDITO"
FOTO_DEL_PELUDITO = "anillos_inspirado_en_tu_mascota"
APERTURA_DEL_PELUDITO = (
    "Así quedan nuestros anillos: con la huellita de tu peludito y su nombre grabado "
    "por dentro 💍🐾\n\n¿Cómo se llama tu peludito? 🐶🐱"
)


def _plano_simple(texto: str) -> str:
    return "".join(
        c
        for c in unicodedata.normalize("NFKD", (texto or "").lower())
        if not unicodedata.combining(c)
    )


def trae_datos_del_pedido(texto: str) -> bool:
    plano = "".join(
        c
        for c in unicodedata.normalize("NFKD", (texto or "").lower())
        if not unicodedata.combining(c)
    )
    return bool(_TRAE_DATOS.search(plano)) and not _PREGUNTA_EL_PRECIO.search(plano)


def es_para_otra_persona(texto: str) -> bool:
    plano = "".join(
        c
        for c in unicodedata.normalize("NFKD", (texto or "").lower())
        if not unicodedata.combining(c)
    )
    return bool(_PARA_OTRA_PERSONA.search(plano))


def pide_la_guia_de_la_talla(texto: str | None, ultimo_de_lia: str) -> bool:
    """¿Está contestando «no sé» a nuestra pregunta de la talla?"""
    dicho = (texto or "").strip()
    if not dicho or len(dicho) > 60 or _TRAE_NUMERO.search(dicho):
        return False
    if PREGUNTA_DE_LA_TALLA[:20] not in (ultimo_de_lia or ""):
        return False
    # «¿No se puede contra entrega?» (17/10) empieza como «no sé» y no lo es:
    # es una pregunta de otra cosa. Una pregunta solo pide la guía si la nombra.
    if "?" in dicho and not _NOMBRA_LA_GUIA.search(dicho):
        return False
    return bool(_PIDE_LA_GUIA.search(dicho)) or "gu" in dicho.lower()[:8]


@dataclass
class HechosDelNegocio:
    """Las verdades que el modelo conoce y que Python escribe con números."""

    precios: dict[int, int]  # huellitas -> precio
    anticipo: int = 60_000
    #: La cadena (03/10): solo se habla de ella si la clienta pregunta. Por eso
    #: NO va en `para_el_prompt`: la ve el modelo cuando ya preguntó.
    precio_cadena: int = 250_000
    anticipo_cadena: int = 65_000
    #: El anillo de corazón (17/10): sí se ofrece; el modelo lo ve siempre.
    precio_corazon: int = 200_000
    anticipo_corazon: int = 60_000
    #: Las promociones cargadas (`data/promociones.csv`, 17/10). Cuáles valen
    #: se mira cada turno, con la fecha de hoy (`promociones_de_hoy`).
    promociones: tuple = ()
    dias: int = 10
    dias_max: int = 15
    ciudad_tienda: str = "Floridablanca (Santander)"

    @classmethod
    def del_catalogo(cls, activos) -> HechosDelNegocio:
        """Del catálogo: los precios de los ANILLOS por huellitas, su abono, y
        la cadena aparte (03/10). Una cadena de 1 huellita no puede pisar el
        precio del anillo de 1."""
        anillos = [p for p in activos if p.categoria == "anillos"]
        cadena = next((p for p in activos if p.categoria == "cadenas"), None)
        corazon = next((p for p in activos if p.categoria == "corazones"), None)
        uno = next((p for p in anillos if p.huellitas == 1), None)
        return cls(
            precios={p.huellitas: p.precio_cop for p in anillos if p.huellitas},
            anticipo=(uno.anticipo_fijo_cop if uno else None) or 60_000,
            precio_cadena=cadena.precio_cop if cadena else 250_000,
            anticipo_cadena=(cadena.anticipo_fijo_cop if cadena else None) or 65_000,
            precio_corazon=corazon.precio_cop if corazon else 200_000,
            anticipo_corazon=(corazon.anticipo_fijo_cop if corazon else None) or 60_000,
            dias=uno.dias_produccion if uno else 10,
            dias_max=(uno.dias_produccion_max if uno else None) or 15,
        )

    def para_el_prompt(self) -> str:
        precios = " · ".join(
            f"{n} huellita{'s' if n > 1 else ''} {formatear_cop(p)}"
            for n, p in sorted(self.precios.items())
        )
        return "\n".join(
            [
                # 20/09: el modelo saludó con «Bienvenida a Anillo Vial». Leyó
                # la dirección del punto de recogida y la tomó por el nombre
                # del negocio. El nombre va primero y en claro.
                f"- El negocio se llama {NOMBRE_DEL_NEGOCIO}. NUNCA lo llames de "
                "otra forma: ni por la dirección, ni por el nombre de la calle.",
                "- Anillo personalizado huellita, hecho a mano en "
                f"{self.ciudad_tienda}. Plata Ley 925 garantizada y circones; se "
                "entrega contramarcado; 6 meses de garantía por defectos de "
                "fabricación. No se pela ni se oxida: es una joya para toda la vida.",
                f"- Precios (la ficha la manda el sistema): {precios}.",
                f"- Abono para iniciar la fabricación: {formatear_cop(self.anticipo)}. "
                "El saldo se paga cuando el anillo está listo y la clienta ya vio "
                "las fotos de cómo quedó.",
                f"- Fabricación: {self.dias} a {self.dias_max} días CALENDARIO "
                "(no hábiles).",
                "- Envío por Coordinadora; el valor depende de la ciudad y se paga "
                "al recibir. Si pregunta cuánto vale, dile la CIFRA que trae el "
                "ESTADO DEL PEDIDO («Envío a …: $…»), nunca solo «depende de la "
                "ciudad». También se puede RECOGER (sin costo de envío) en "
                f"{PUNTO_DE_RECOGIDA}.",
                "- Dónde estamos: Floridablanca, Santander. NO hay punto físico: es "
                "un taller de joyería en casa. Para recoger, SOLO el nombre del "
                f"conjunto ({PUNTO_DE_RECOGIDA}); NUNCA dirección, torre ni "
                "apartamento (es la casa de Lía). En Bucaramanga hay domicilio y su "
                "valor depende del domicilio: NUNCA digas una cifra para eso.",
                "- Envío pagado ANTES de recibir: solo si ELLA lo pregunta o lo "
                "pide (no está en casa, que se lo dejen en portería). Sí se puede: "
                "lo paga JUNTO CON EL SALDO, cuando el anillo esté listo, y así no "
                "paga nada al recibirlo (acción ENVIO_CON_SALDO). NUNCA con el "
                "abono: el abono es solo el del anillo y es lo que hace que entre "
                "al taller. Si no lo pregunta, no lo ofrezcas: lo normal es al "
                "recibir.",
                "- No hay contraentrega en joyas personalizadas: por eso el abono, "
                "para que vea fotos del anillo terminado antes de pagar el saldo.",
                # Camilo, 13/10: lo que da confianza y es verdad. La página dice
                # «Creando piezas especiales desde 2019» (no más de 8 años).
                "- Dónde nos conocen (SOLO para darle confianza si tiene miedo o "
                "desconfía): la página https://lunajoyas.example («creando piezas "
                "especiales desde 2019») y el Instagram @lunajoyas "
                "(https://instagram.com/lunajoyas). Se vende solo en línea. "
                "Ningún otro usuario, enlace, año ni número de clientas.",
                "- Medios de pago: Bancolombia, Nequi y Daviplata (los datos los "
                "manda el sistema). Con tarjeta se paga el total por link: eso lo "
                "gestiona Lía.",
                "- Talla: tallaje estándar de joyería; si ya compró anillos talla X, "
                "sirve. Si no la sabe, la guía: anillo redondo + regla, medir por la "
                "mitad, mandar foto.",
                "- Grabado al interior del aro: hasta 5 nombres; también fechas, "
                "corazones, alitas, infinitos, carita de gatito o de perrito.",
                "- Cada huellita = corazón (la almohadilla, piedra grande) + 4 "
                "deditos. Con 2 o 3 huellitas cada una puede ir de otro color. Dos "
                "huellitas no se pueden poner en la misma posición.",
                "- ANILLO DE CORAZÓN (el otro diseño, 17/10): Plata Ley 925 con UN "
                "corazón de circón del color que ella escoja, en vez de huellitas "
                "(no lleva huellitas ni deditos). Lo demás, igual que el de "
                "huellita: en su talla, hasta 5 nombres grabados por dentro, "
                f"{self.dias} a {self.dias_max} días, fotos antes del saldo, "
                "garantía. Precio "
                f"{formatear_cop(self.precio_corazon)}, abono "
                f"{formatear_cop(self.anticipo_corazon)}, saldo "
                f"{formatear_cop(self.precio_corazon - self.anticipo_corazon)}. Es "
                "ideal como anillo de promesa o para regalar a la pareja, pero no "
                "solo para eso. SÍ lo puedes ofrecer, desde el primer mensaje, "
                "cuando venga al caso (no quiere huellita, pregunta por otros "
                "diseños, es para su pareja, una promesa). Su presentación (precio y "
                "foto) la manda el sistema: acción MOSTRAR_CORAZON. Si lo quiere: "
                "acción ES_CORAZON. OJO: «el corazón rosado» de una huellita es la "
                "piedra grande de la patita, NO este anillo.",
                "- Muestrario (14 colores de circón): blanco (transparente), negro, "
                "lila, morado, celeste, azul rey, rosado, fucsia, rojo, naranja, "
                "durazno, amarillo, verde oliva, verde esmeralda.",
                "- La cotización vale 30 días; el precio puede subir con el precio "
                "internacional de la plata.",
            ]
        )

    def ficha(self) -> str:
        lineas = [
            "🎀*Anillo personalizado huellita* 💍 🐾",
            "",
            "🪄 Precios según la cantidad de huellitas:",
        ]
        for n, p in sorted(self.precios.items()):
            lineas.append(f"• {n} huellita{'s' if n > 1 else ''}: {formatear_cop(p)}")
        lineas += [
            "",
            "✨ *Elaborado en Plata Ley 925 y circones (No se pela, no se oxida, "
            "es una joya para toda la vida)*",
            "",
            "📏 Se fabrica en tu medida.",
            "🎨 Escoge el color/combinación que quieras para la huellita.",
            "🖊️ Puedes grabar hasta 5 nombres de tus peluditos 🐱🐶 al interior "
            "del anillo.",
            "",
            "💰 *Para iniciar la fabricación solo necesitas abonar "
            f"{formatear_cop(self.anticipo)}*",
            "",
            f"⏳ Tiempo de fabricación: {self.dias} a {self.dias_max} días calendario.",
            "",
            "Cuando esté listo 💍 ✅ te enviamos fotos de cómo quedó, realizas el pago "
            "del saldo y luego lo enviamos hasta tu puerta 🏡✨",
        ]
        return "\n".join(lineas)

    def promociones_de_hoy(self) -> list:
        from app.domain.promociones import vigentes

        return vigentes(self.promociones, datetime.now(COLOMBIA).date())

    def ficha_del_corazon(self) -> str:
        """La presentación del anillo de corazón (17/10), con la estructura de la
        ficha de la huellita: lo mismo, con un corazón en vez de huellitas."""
        return "\n".join(
            [
                "🎀*Anillo de corazón* 💍 💗",
                "",
                f"🪄 Precio: {formatear_cop(self.precio_corazon)}",
                "",
                "✨ *Elaborado en Plata Ley 925 y circones (No se pela, no se oxida, "
                "es una joya para toda la vida)*",
                "",
                "📏 Se fabrica en tu medida.",
                "🎨 Escoge el color que quieras para el corazón.",
                "🖊️ Puedes grabar hasta 5 nombres al interior del anillo: los de tus "
                "peluditos 🐱🐶, el de tu pareja o una fecha especial.",
                "💗 Ideal como anillo de promesa o para regalar a quien más quieres.",
                "",
                "💰 *Para iniciar la fabricación solo necesitas abonar "
                f"{formatear_cop(self.anticipo_corazon)}*",
                "",
                f"⏳ Tiempo de fabricación: {self.dias} a {self.dias_max} días "
                "calendario.",
                "",
                "Cuando esté listo 💍 ✅ te enviamos fotos de cómo quedó, realizas el "
                "pago del saldo y luego lo enviamos hasta tu puerta 🏡✨",
            ]
        )


#: Con qué termina la presentación. La manda el sistema, no el modelo: es la
#: misma frase siempre y va de pie del álbum de la apertura.
PREGUNTA_DE_LA_TALLA = "¿Sabes tu talla de anillo o te comparto la guía? 💍💜"
#: La misma, cuando el anillo es un regalo (17/10).
PREGUNTA_DE_LA_TALLA_REGALO = (
    "¿Sabes la talla de quien lo va a usar, o te comparto cómo sacarla? 💍💜"
)

#: Cómo se pregunta cada cosa que falta, con las palabras de Lía.
#:
#: Solo se usa cuando el turno se quedaría mudo (ver `_lo_que_falta`). El resto
#: del tiempo pregunta el modelo, que sí sabe de qué se venía hablando.
#: Con qué empiezan los rechazos de «pedí el abono pero falta algo».
#:
#: Bloquear el abono está bien —sin los datos no nace el pedido—, pero el
#: mensaje del modelo ya prometía las cuentas. Hay que reescribirlo pidiendo lo
#: que falta, o le llega «Te dejo los datos 💓» y ningún dato (20/09).
ABONO_BLOQUEADO = "no se pidió abono: falta "

#: Cuántas veces se pregunta la cantidad antes de llamar a Lía.
VECES_ANTES_DE_LIA = 3

#: Estados en los que NO se pregunta nada: la pelota la tiene otro.
#:
#: Con el comprobante mandado o el anillo en el taller, lo siguiente lo hace
#: una persona —Lía verifica, el taller fabrica— y meterle una pregunta encima
#: es apurarla por algo que no depende de ella.
SIN_NADA_QUE_PREGUNTAR = frozenset(
    {
        "EN_REVISION_PAGO",
        "ANTICIPO_PAGADO",
        "EN_PRODUCCION",
        "PRODUCCION_LISTA",
        "SALDO_PAGADO",
        "DESPACHADO",
        "ENTREGADO",
        "CANCELADO",
        "REEMBOLSO",
    }
)

#: Lo que se pregunta cuando acaba de ver el resumen del pedido.
CONFIRMA_EL_RESUMEN = "¿Así está bien? 🥰"

#: Cómo se pregunta cada cosa que falta, con las palabras de Lía.
COMO_SE_PREGUNTA = {
    "cantidad de huellitas": "¿De cuántas huellitas lo quieres? 🐾",
    "talla": PREGUNTA_DE_LA_TALLA,
    TALLA_DE_LIA: TALLA_EN_ESPERA,
    "colores": "¿De qué colores quieres las huellitas? 🩵🩷",
    "grabado": "¿Quieres grabarle el nombre de tu peludito? 🖊️",
    "nombre completo": "¿Me regalas tu nombre completo, porfa? 🥰",
    "ciudad": "¿Para qué ciudad sería el envío? 📦",
    "cédula": "¿Me regalas tu número de cédula? Es para la guía 📄",
    "celular": "¿Y un número de celular para la transportadora? 📱",
    "dirección completa con barrio y nomenclatura": (
        "¿Me regalas la dirección completa, con barrio y nomenclatura? 🏠"
    ),
}

#: Con el anillo de corazón (17/10) no hay huellitas ni peludito obligado.
COMO_SE_PREGUNTA_DEL_CORAZON = {
    "colores": "¿De qué color quieres el corazón? 💗",
    "grabado": "¿Qué nombre o fecha quieres grabarle por dentro? 🖊️",
}


def pregunta_de(que: str, b: Borrador) -> str | None:
    """La pregunta fija de lo que falta, con las palabras de la pieza."""
    if b.es_corazon and que in COMO_SE_PREGUNTA_DEL_CORAZON:
        return COMO_SE_PREGUNTA_DEL_CORAZON[que]
    if que == "colores" and b.cantidad == 1:
        # Una sola huellita: «¿De qué colores quieres LAS huellitas?» sonaba a
        # formulario (prueba del 13/10).
        return "¿De qué color quieres la huellita? 🩵🩷"
    return COMO_SE_PREGUNTA.get(que)


#: Cuando el anillo que iba quedó listo y falta describir otro (02/10).
OTRO_ANILLO_POR_EMPEZAR = (
    "¡Listo ese! 🫶 Vamos con el siguiente anillo: ¿de cuántas huellitas lo quieres? 🐾"
)

#: Con qué empieza. Corto, como Lía («buen día», «Buen día 🌞»): lo que importa
#: de la apertura es lo que viene detrás.
SALUDO_DE_APERTURA = "¡Hola! Buen día 🌞 Bienvenida a Luna Joyas 💍"
#: El mismo, de tarde y de noche (13/10, auditoría: a las 9:37 p. m. le llegaba
#: «Buen día 🌞», y a quien escribió «Buenas noches» también).
SALUDO_DE_LA_TARDE = "¡Hola! Buenas tardes 🌷 Bienvenida a Luna Joyas 💍"
SALUDO_DE_LA_NOCHE = "¡Hola! Buenas noches 🌙 Bienvenida a Luna Joyas 💍"


def saludo_de_apertura(hora: int) -> str:
    """El saludo de Lía según la hora de Colombia: día hasta las 12, tarde
    hasta las 7 p. m. y noche (también de madrugada, antes de las 5)."""
    if 5 <= hora < 12:
        return SALUDO_DE_APERTURA
    if 12 <= hora < 19:
        return SALUDO_DE_LA_TARDE
    return SALUDO_DE_LA_NOCHE


#: Qué anillo va en cada pieza de la presentación (`_presentacion`), revisado a
#: ojo el 13/10: el PRIMER video son anillos de 2 huellitas (dice «Anillos 2
#: huellitas»), el SEGUNDO de 1 (uno con el grabado por dentro) y la FOTO, la del
#: pie con «¿Sabes tu talla…?», es UN anillo de 3 huellitas en tres ángulos.
#: (Lía, 09/10, había dicho «en los videos, 1 y 2, respectivamente»: van al revés.)
PIEZA_DE_CADA_ANILLO: dict[int, tuple[str, bool]] = {
    1: ("presentacion_video_2", True),
    2: ("presentacion_video_1", True),
    3: ("presentacion_anillo", False),
}
_PIDE_VER = re.compile(
    r"\b(?:muestr\w*|mostr\w*|ensen\w*|ver|veo|mira\w*|foto\w*|video\w*"
    r"|como\s+(?:es|son|se\s+ve|queda))\b",
)
_EL_DE = re.compile(
    r"\b(?:el|la|los|uno|anillo)\s+de\s+(1|una|un|2|dos|3|tres)\b(?!\s*(?:nombre|color))"
    r"|\b(1|una|un|2|dos|3|tres)\s+huellit",
)
_CUANTAS = {"1": 1, "una": 1, "un": 1, "2": 2, "dos": 2, "3": 3, "tres": 3}
#: Compara o no entiende las cantidades: «3 huellitas o una», «¿cuál es la
#: diferencia?». Ahí no se manda una sola pieza (17/10).
_COMPARA_CANTIDADES = re.compile(
    r"\bno\s+entend\w*|\bdiferencia\w*"
    r"|\b(?:1|2|3|una|un|dos|tres)\b[^.?!]{0,30}?\bo\s+(?:de\s+|la\s+de\s+|el\s+de\s+)?"
    r"(?:1|2|3|una|un|dos|tres)\b"
)


def pide_ver_el_de(texto: str | None) -> int | None:
    """«Muéstrame el de 2», «¿cómo es el de una huellita?» -> 2, 1. Si pide ver
    varios a la vez o no pide ver nada, None (13/10)."""
    plano = "".join(
        c
        for c in unicodedata.normalize("NFKD", (texto or "").lower())
        if not unicodedata.combining(c)
    )
    if not _PIDE_VER.search(plano):
        return None
    # «¿Cómo es lo de 3 huellitas o una?» compara: no es «muéstrame el de 3»
    # (17/10). Eso lo contesta el modelo explicando los diseños.
    if _COMPARA_CANTIDADES.search(plano):
        return None
    cuales = {_CUANTAS[a or b] for a, b in _EL_DE.findall(plano)}
    return cuales.pop() if len(cuales) == 1 else None


#: Las preguntas de sí o no que un 👍 contesta: ahí la reacción es la respuesta.
_LA_REACCION_CONTESTA = (CONFIRMA_EL_RESUMEN, "¿Lo dejo a nombre de")


def solo_reacciona(media: list[dict], texto: str | None, ultimo_de_lia: str) -> bool:
    """¿Solo reaccionó con un emoji a un mensaje, sin escribir nada? (13/10)

    Auditoría: un ❤️ a «¿Sabes tu talla…?» o a «ya le aviso a Lía» recibía
    «¡Anotado! 🫶» y «¿De cuántas huellitas lo quieres?». Quien vende no le
    contesta a un corazón: se ve en Chatwoot y ya. Sí se atiende si reacciona a
    la pregunta del resumen o a la de su nombre, porque ahí el 👍 es un «sí».
    """
    if (texto or "").strip() or not media:
        return False
    if any((m or {}).get("kind") != "reaction" for m in media):
        return False
    return not any(p in (ultimo_de_lia or "") for p in _LA_REACCION_CONTESTA)


#: Cómo se llama el negocio. Está aquí y no suelto en un texto porque el
#: modelo se lo inventó: el 20/09 saludó con «Bienvenida a Anillo Vial», que es
#: la calle del punto de recogida.
NOMBRE_DEL_NEGOCIO = "Luna Joyas"

#: Lo que el modelo lee del pedido, en palabras y no en códigos. Pasó 19/09: con
#: «ESPERANDO_SALDO» a secas contestó «ya está en producción» a quien acababa de
#: recibir las fotos de su anillo terminado.
ESTADO_EN_PALABRAS: dict[str, str] = {
    "ESPERANDO_ANTICIPO": "pedido tomado y cuentas enviadas; esperando que pague el "
    "abono",
    "EN_REVISION_PAGO": "mandó un comprobante y Lía lo está verificando; no le pidas "
    "otro pago",
    "ANTICIPO_PAGADO": "abono verificado por Lía; el anillo entra al taller",
    "EN_PRODUCCION": "el anillo se está fabricando en el taller",
    "PRODUCCION_LISTA": "el anillo YA ESTÁ TERMINADO",
    "ESPERANDO_SALDO": "el anillo YA ESTÁ TERMINADO: ya se le mandaron las fotos y el "
    "cobro del saldo; falta que pague el saldo para despacharlo",
    "SALDO_PAGADO": "saldo verificado; se está alistando el envío por Coordinadora",
    "DESPACHADO": "el anillo YA SE DESPACHÓ por Coordinadora y va en camino",
    "ENTREGADO": "el anillo ya le llegó",
    "CANCELADO": "pedido cancelado",
    "REEMBOLSO": "pedido en reembolso",
}


@dataclass
class TurnoDeAsesora(Turno):
    jugada: Jugada | None = None
    capa: str = ""
    #: Lo que se entendió de cada nota de voz: va a Chatwoot como nota privada,
    #: para que Lía vea qué oyó el bot (auditable).
    transcripciones: list[str] | None = None

    def resumen(self) -> str:
        if self.jugada is None:
            return f"asesora[{self.capa}]"
        acciones = ",".join(a.value for a in self.jugada.acciones) or "-"
        capa = f"{self.capa}·{self.jugada.confianza.value}"
        return f"asesora[{capa}] {acciones} | {self.jugada.lectura}"


class Asesora:
    def __init__(
        self,
        mundo,
        llm,
        prompt: str,
        hechos: HechosDelNegocio,
        *,
        llm_fuerte=None,
        respaldo=None,
        descargar: Callable[[dict], bytes | None] | None = None,
        oidos=None,
        avisar: Callable[[str, str, str], object] | None = None,
        talla_la_confirma_lia: bool = False,
        guardar_foto: Callable[[bytes], str] | None = None,
        apertura_peludito: bool = False,
    ) -> None:
        self._mundo = mundo
        #: La prueba de la primera respuesta (13/10, `APERTURA_PELUDITO`).
        self._apertura_peludito = apertura_peludito
        #: Regla de Lía (29/09): ver `Borrador.talla_exige_lia`.
        self._talla_la_confirma_lia = talla_la_confirma_lia
        #: Guarda la foto de la regla para el panel y devuelve su nombre.
        self._guardar_foto = guardar_foto
        #: Las FOTOS (no stickers) de este turno, ya bajadas para el modelo.
        self._fotos_del_turno: list[bytes] = []
        self._llm = llm
        self._fuerte = llm_fuerte
        self._respaldo = respaldo
        self._avisar = avisar
        self._descargar = descargar
        self._oidos = oidos
        self._hechos = hechos
        self._prompt = prompt.replace("{hechos}", hechos.para_el_prompt())
        self._armado: tuple[int, str] | None = None

    @property
    def _system(self) -> str:
        """El prompt con los nombres de colores VIGENTES (panel → Colores).

        Se rehace solo cuando cambia la paleta: mientras tanto es el mismo
        texto, letra por letra, y la caché de la IA lo sigue reutilizando.
        """
        from app.domain import personalizacion as p

        if self._armado is None or self._armado[0] != p.VERSION_PALETA:
            colores = ", ".join(f"{c.value} = {p.NOMBRE_COLOR[c]}" for c in p.ColorCircon)
            nombres = ", ".join(p.nombres_del_muestrario())
            texto = self._prompt.replace("{colores}", colores).replace(
                "{nombres_colores}", nombres
            )
            self._armado = (p.VERSION_PALETA, texto)
        return self._armado[1]

    # -- el turno ----------------------------------------------------------

    #: El contenedor reintenta en segundo plano los turnos que ninguna IA pudo
    #: contestar (`Container.reintentar_turnos_pendientes`).
    reintenta_pendientes = True

    def ejecutar(
        self,
        conversation_id: str,
        texto: str | None,
        media: list[dict] | None = None,
        nombre_de_whatsapp: str = "",
        *,
        reintento: bool = False,
    ) -> Turno:
        inicio = time.perf_counter()
        consumo.abrir_turno()
        guardado = self._mundo.contexto(conversation_id)
        ctx = self._mundo.resolver_contexto(guardado)
        # Lo que quedó sin contestar cuando se cayó la IA (29/09) va DELANTE de
        # lo nuevo: se le contesta todo junto, en orden. Se saca del contexto
        # ya: si el turno sale bien, queda borrado al guardar; si no, se vuelve
        # a guardar (`_si_falla_la_ia`).
        pendiente = ctx.pendiente_ia
        if pendiente:
            ctx = ctx.model_copy(update={"pendiente_ia": None})
            texto = (
                "\n".join(
                    x for x in (pendiente.get("texto") or "", texto or "") if x.strip()
                )
                or None
            )
            media = [*(pendiente.get("media") or []), *(media or [])] or None
        elif reintento:
            # Nada pendiente (lo contestó un turno normal mientras tanto).
            vacio = TurnoDeAsesora(conversation_id=conversation_id, texto=None)
            vacio.respuesta, vacio.contexto, vacio.capa = Respuesta(), ctx, "nada"
            return vacio
        turno = TurnoDeAsesora(conversation_id=conversation_id, texto=texto, media=media)
        borrador = Borrador.model_validate(ctx.borrador) if ctx.borrador else Borrador()
        pedido = self._mundo.pedido(borrador.pedido_id) if borrador.pedido_id else None

        # LA APERTURA NO SE LE PREGUNTA A NADIE. Es la misma siempre, así que
        # se manda sin gastar una llamada ni hacerla esperar. Ver `_apertura`.
        apertura = self._apertura(conversation_id, ctx, borrador, media, texto)
        if apertura is not None:
            return apertura
        borrador.talla_exige_lia = self._talla_la_confirma_lia
        fija = self._respuesta_fija(conversation_id, ctx, borrador, texto, media)
        if fija is not None:
            return fija

        # No acosar (09/10): lo que dejó para después («la medida te la confirmo
        # en la tarde») y lo ya pedido de más quedan anotados ANTES de la IA,
        # para que el estado se lo diga.
        if not borrador.pedido_id:
            al_dia_lo_que_se_pide(
                borrador,
                texto,
                next(
                    (
                        m.get("texto", "")
                        for m in reversed(ctx.charla)
                        if m.get("de") == "lia"
                    ),
                    "",
                ),
            )
        fotos, descripciones = self._fotos(media)
        entrada = self._entrada(
            borrador, pedido, ctx.charla, texto, descripciones, ctx.notas_internas
        )

        jugada, capa = self._jugar(entrada, fotos)
        if jugada is None:
            return self._si_falla_la_ia(
                conversation_id, texto, media, turno, ctx, pendiente, reintento
            )

        cambios = jugada.cambios
        # Varios anillos (02/10): cuántos son y de cuál habla, ANTES de anotar.
        # Lo que dice de otro anillo («talla 6 el de una») va a ESE: durante el
        # turno ocupa el lugar del actual y al final vuelve a su sitio.
        borrador = borrador.model_copy(deep=True)
        ultimo_de_lia = next(
            (m.get("texto", "") for m in reversed(ctx.charla) if m.get("de") == "lia"), ""
        )
        acciones_de_las_piezas = list(jugada.acciones)
        if viene_por_el_corazon(borrador, texto, hay_pedido=pedido is not None):
            # Vino por el anillo de corazón (vio su presentación y no la de la
            # huellita): lo que diga ahora es de ESE anillo, aunque la IA no lo
            # marque (prueba del 17/10: «me encanta, talla 9» -> «¿de qué color
            # quieres la huellita?»).
            acciones_de_las_piezas.append(AccionAsesora.ES_CORAZON)
        rechazos_anillos, nota_anillos, cambios, nuevos = contar_anillos(
            borrador,
            acciones_de_las_piezas,
            texto,
            cambios,
            hay_pedido=pedido is not None or bool(borrador.pedido_id),
            ultimo_de_lia=ultimo_de_lia,
            cadena_mostrada=AccionAsesora.MOSTRAR_CADENA.value in borrador.mostrado_en,
            corazon_mostrado=AccionAsesora.MOSTRAR_CORAZON.value in borrador.mostrado_en,
        )
        # Dijo que COMPRA varios («quiero dos anillos», «serían dos anillos»): se
        # crean aunque la IA no marque OTRO_ANILLO (12/10, prueba de verdad: a
        # veces tardaba y lo del segundo quedaba en el primero o se perdía). Una
        # sola vez: si después quita uno, no se vuelve a sumar.
        if (
            pedido is None
            and not borrador.pedido_id
            and not borrador.es_cadena
            and ANILLOS_DICHOS not in borrador.mostrado_en
        ):
            dichos = [
                n
                for t in (
                    texto,
                    *[m.get("texto", "") for m in ctx.charla if m.get("de") == "clienta"][
                        -6:
                    ],
                )
                if (n := anillos_que_pide(t))
            ]
            total = max(dichos, default=0)
            if total > borrador.anillos_total and total <= MAX_ANILLOS:
                while borrador.anillos_total < total:
                    borrador.agregar_anillo()
                    nuevos += 1
                borrador.mostrado_en[ANILLOS_DICHOS] = borrador.turnos
                rechazos_anillos.append(
                    f"dijo que son {total} anillos: quedaron {total}, de a uno"
                )
        foto_de_talla = any(
            (m or {}).get("kind") == "image" for m in media or []
        ) and bool(
            cambios.medida_cm is not None
            or cambios.talla is not None
            or _HABLA_DE_TALLA.search(jugada.lectura or "")
        )
        # «Una lila y la otra fucsia» (Yulieth, 09/10): un color por anillo, en
        # orden. «La otra» NO es «habla del otro anillo»: sin esto la lila se
        # anotaba en el segundo y al primero se le volvía a preguntar.
        colores_de_todos = (
            colores_por_anillo(borrador, texto) if not borrador.pedido_id else []
        )
        if not borrador.pedido_id:
            foco = (
                None
                if colores_de_todos
                else anillo_del_mensaje(
                    borrador, texto, cambios, foto_de_talla=foto_de_talla, nuevos=nuevos
                )
            )
            if foco is not None:
                borrador.enfocar(foco)
                rechazos_anillos.append(
                    f"lo de este mensaje se anotó en el anillo {foco + 1} (el que ella "
                    f"nombró); el que se está describiendo sigue siendo el "
                    f"{borrador.numero_del_anillo}"
                )
        if (borrador.es_cadena or borrador.es_corazon) and (
            cambios.cantidad_huellitas is not None
        ):
            # La cadena lleva UNA huellita y el anillo de corazón, un corazón: no
            # hay cantidad que cuidar ni preguntar (la guardia de la cantidad le
            # preguntaría «¿1 o 2?»).
            cambios = cambios.model_copy(update={"cantidad_huellitas": None})
        if (
            borrador.cantidad is None
            and cambios.cantidad_huellitas is None
            and habla_de_una_sola_huellita(texto)
        ):
            # Pasó en «Sexta»: «toda la huellita en el mismo tono» y el modelo no
            # anotó la cantidad; siete turnos después seguía preguntándola.
            cambios = cambios.model_copy(update={"cantidad_huellitas": 1})
        elif (
            borrador.cantidad is None
            and cambios.cantidad_huellitas is None
            and (escrita := cuantas_huellitas_escribio(texto)) is not None
        ):
            # Lo mismo con el número escrito: «quisiera un anillo de 2 huellitas
            # pero no sé mi talla» -> «¡Perfecto, dos huellitas!» sin anotarla, y
            # dos turnos después se la volvía a preguntar (chats del 29/09).
            cambios = cambios.model_copy(update={"cantidad_huellitas": escrita})
        elif (
            borrador.cantidad is None
            and cambios.cantidad_huellitas is None
            and (contestada := cantidad_contestada(texto, ultimo_de_lia)) is not None
        ):
            # «De una» a «¿De cuántas huellitas?»: es 1, no se le vuelve a
            # preguntar con opciones (Mónica, 07/10).
            cambios = cambios.model_copy(update={"cantidad_huellitas": contestada})
        if (
            borrador.talla is None
            and cambios.talla is None
            and cambios.medida_cm is None
            # Una nota de voz sí vale (llega transcrita); una foto no: esa es
            # la de la regla y la mira Lía.
            and not any(
                (m or {}).get("kind") in ("image", "document") for m in media or []
            )
            and not borrador.es_cadena
            and (dictada := talla_dictada(texto, ultimo_de_lia)) is not None
        ):
            # Dictada por voz (04/10): «talla seis» llegó como «Gamma seis» y el
            # modelo no la anotó; un turno después la anotó y dudó de ella («¿es
            # la definitiva o te comparto la guía?»). Lo que ella DICE, queda.
            cambios = cambios.model_copy(update={"talla": dictada})
        cambia_cantidad = (
            cambios.cantidad_huellitas is not None
            and cambios.cantidad_huellitas != borrador.cantidad
        )
        previos: list[str] = []
        if (
            cambia_cantidad
            and borrador.cantidad is not None
            and not cambia_la_cantidad(texto)
        ):
            previos.append(
                f"la cantidad ya era {borrador.cantidad}: ese mensaje no la cambia "
                "(solo si ella dice que quiere otra)"
            )
            cambios = cambios.model_copy(update={"cantidad_huellitas": None})
            cambia_cantidad = False
        guardia_cantidad = cambia_cantidad and not cantidad_respaldada(
            cambios.cantidad_huellitas,
            texto,
            ultimo_de_lia,
            [m.get("texto", "") for m in ctx.charla if m.get("de") == "clienta"],
        )
        if guardia_cantidad and pregunta_por_las_cantidades(texto):
            # Solo PREGUNTÓ («¿cuánto vale el de 2?», «¿cómo es lo de 3 o una?»):
            # no se anota, pero tampoco se le cambia la respuesta por «¿me
            # confirmas cuántas?»: ella quiere su respuesta (17/10).
            cambios = cambios.model_copy(update={"cantidad_huellitas": None})
            guardia_cantidad = cambia_cantidad = False
        if guardia_cantidad:
            # La cantidad cambia el precio: un «sí» a «¿1 o 2 huellitas?» no elige.
            cambios = cambios.model_copy(update={"cantidad_huellitas": None})
        if (
            borrador.varios
            and cambios.talla is not None
            and cambios.talla
            in {
                v.talla
                for i, v in enumerate(borrador.vistas())
                if i != borrador.posicion_actual and v.talla is not None
            }
            and cambios.talla != borrador.talla
            and not _HABLA_DE_UNA_TALLA.search(texto or "")
            and not any(
                (m or {}).get("kind") in ("image", "document") for m in media or []
            )
        ):
            # Varios anillos (12/10, prueba de verdad): a «el de ella todo
            # celeste» la IA a veces le copiaba al anillo de la hermana la talla
            # del OTRO anillo. Sin que ella hable de talla, eso no se anota.
            cambios = cambios.model_copy(update={"talla": None})
            previos.append(
                "la talla de otro anillo no se copia: ella no habló de talla aquí"
            )
        nuevo, rechazos = aplicar(borrador, cambios)
        rechazos = previos + rechazos
        # Varios anillos y dio varias tallas de una vez («el mío talla 6 y el de
        # ella talla 8»): cada una a su anillo (prueba de verdad, 04/10).
        # Y si lo dijo ANTES de que existiera el segundo anillo («el mío talla 6
        # y el de ella talla 8» en el turno en que todavía era uno), se busca en
        # sus mensajes anteriores, sin pisar lo que cada anillo ya tiene.
        tallas_de_varios: list[tuple[int, float]] = []
        if nuevo.varios and not nuevo.pedido_id:
            suyos = [m.get("texto", "") for m in ctx.charla if m.get("de") == "clienta"][
                -8:
            ]
            tallas_de_varios = tallas_para_varios(nuevo, texto)
            de_antes = next(
                (a for t in reversed(suyos) if (a := tallas_para_varios(nuevo, t))), []
            )
            if not tallas_de_varios and de_antes:
                poner_tallas(
                    nuevo, [(i, t) for i, t in de_antes if nuevo.vista(i).talla is None]
                )
            for t in (texto, *reversed(suyos)):
                if (n := cantidad_de_todos(t)) is not None:
                    if poner_cantidad_a_todos(nuevo, n):
                        rechazos.append(
                            f"dijo que todos los anillos son de {n} huellita(s): "
                            "quedó en cada uno"
                        )
                    break
            # Lo que dijo para TODOS no se le vuelve a preguntar en el siguiente
            # anillo (Yulieth, 09/10): «una lila y la otra fucsia», «en los dos
            # anillos: Khalifa».
            # Los de este mensaje, a cada anillo en su orden (también el primero:
            # el modelo pudo ponerle otro). Si no, los que dijo antes, cuando
            # todavía no existía el segundo anillo.
            asignados = colores_de_todos or (
                next(
                    (a for t in reversed(suyos) if (a := colores_por_anillo(nuevo, t))),
                    [],
                )
                if nuevo._foco is None
                else []
            )
            if asignados:
                poner_colores(nuevo, asignados)
                rechazos.append(
                    "dijo un color para cada anillo: quedó cada uno en el suyo"
                )
            if (
                nuevo.grabado
                and any(grabado_para_todos(t) for t in (texto, *suyos[-3:]))
                and poner_grabado_a_todos(nuevo, nuevo.grabado)
            ):
                rechazos.append(
                    "dijo que el grabado va en todos los anillos: quedó en cada uno"
                )
        if tallas_de_varios:
            poner_tallas(nuevo, tallas_de_varios)
            rechazos.append(
                "dio las tallas de varios anillos de una vez: quedaron anotadas, "
                "cada una en su anillo"
            )
        if pedido is not None or nuevo.abono_reportado:
            rechazos += self._datos_de_envio_del_mensaje(nuevo, cambios, texto)
        if (
            cambios.talla is not None
            and nuevo.talla != borrador.talla
            and any((m or {}).get("kind") == "image" for m in media or [])
            and not _TRAE_NUMERO.search(texto or "")
        ):
            # La LEYÓ la IA en la foto de la regla, no la escribió ella: es
            # una referencia hasta que Lía la mire (27/09).
            nuevo.talla_revisar = True
            nuevo.talla_motivo = (
                f"Talla {talla_texto(nuevo.talla)} leída por la IA en la foto de la "
                "regla (preliminar): confírmala o corrígela desde el panel"
            )
            if nuevo.talla_motivo not in nuevo.notas:
                nuevo.notas.append(nuevo.talla_motivo)
        if guardia_cantidad:
            nuevo.cantidad_en_duda = True
            nuevo.veces_preguntando_cantidad += 1
            rechazos.append(
                "la clienta no ha escrito cuántas huellitas: la cantidad no se guardó; "
                "pregúntale con opciones"
            )
        elif cambia_cantidad:
            nuevo.cantidad_en_duda = False
            nuevo.veces_preguntando_cantidad = 0
        nuevo.turnos = borrador.turnos + 1
        respuesta = Respuesta()
        notas: list[str] = []
        talla_para_lia = self._talla_la_confirma_lia and self._talla_para_lia(
            conversation_id, borrador, nuevo, jugada, media, descripciones, notas
        )

        acciones = list(dict.fromkeys(jugada.acciones))
        # Cuándo paga el envío: una decisión de plata, se resuelve aquí y no
        # llega al bucle de acciones (no manda nada por sí sola).
        nuevo, rechazos_envio = acordar_envio(nuevo, acciones)
        rechazos += rechazos_envio
        acciones = [a for a in acciones if a not in ACCIONES_DEL_ENVIO]
        # Cuántos anillos compra: se resolvió antes de aplicar (`contar_anillos`).
        rechazos += rechazos_anillos
        if nota_anillos:
            notas.append(nota_anillos)
            respuesta.escalar = True
        acciones = [a for a in acciones if a not in ACCIONES_DE_LOS_ANILLOS]
        nuevo.igualar_tallas()
        # Un comprobante que LLEGÓ no se puede perder. Si el adjunto es una foto
        # o un PDF y lo que el modelo mismo leyó dice que es un comprobante, se
        # registra aunque se le haya olvidado pedirlo (repaso del 21/09).
        adjunto = any((m or {}).get("kind") in ("image", "document") for m in media or [])
        # Con el pago pendiente (las cuentas ya salieron, o el anillo está listo
        # y falta el saldo), una foto con plata ES el comprobante, la describa
        # el modelo como la describa (04/10: «captura de un movimiento…»).
        esperando_pago = (borrador.cuentas_enviadas and not borrador.abono_reportado) or (
            pedido is not None
            and pedido.estado in ("PRODUCCION_LISTA", "ESPERANDO_SALDO")
            and not borrador.saldo_reportado
        )
        if (
            AccionAsesora.RECIBIR_COMPROBANTE not in acciones
            and adjunto
            and (
                llego_un_comprobante(jugada.lectura, descripciones)
                or (esperando_pago and parece_un_pago(jugada.lectura, descripciones))
            )
        ):
            acciones.append(AccionAsesora.RECIBIR_COMPROBANTE)
            rechazos.append(
                "llegó un comprobante y no se había pedido registrarlo: se registra "
                "para que Lía lo verifique"
            )
        elif (
            AccionAsesora.RECIBIR_COMPROBANTE not in acciones
            and esperando_pago
            and habla_de_pago(texto)
        ):
            # «Ya te transferí los 60 mil» con las cuentas ya enviadas: es un
            # pago reportado. Lía tiene que enterarse ya (prueba de verdad,
            # 04/10: el bot pidió el comprobante, bien, pero no avisó a nadie).
            acciones.append(AccionAsesora.RECIBIR_COMPROBANTE)
            rechazos.append(
                "dijo que ya pagó: queda registrado para que Lía lo verifique (si "
                "no mandó el comprobante, pídeselo con cariño)"
            )
        estado = pedido.estado if pedido is not None else ""
        # Regla de Camilo (19/09): apenas quedan los colores, se le manda cómo
        # queda. Ella no tiene que pedirlo.
        if (
            nuevo.huellitas != borrador.huellitas
            and _colores_completos(nuevo)
            and AccionAsesora.MOSTRAR_COMO_QUEDA not in acciones
            and AccionAsesora.MOSTRAR_SUGERENCIAS not in acciones
        ):
            acciones.append(AccionAsesora.MOSTRAR_COMO_QUEDA)
        # Con el pedido al 100 % por primera vez, el resumen completo va solo.
        if (
            not nuevo.pedido_id
            and borrador.falta_para_abono()
            and not nuevo.falta_para_abono()
            and AccionAsesora.MOSTRAR_RESUMEN not in acciones
        ):
            acciones.append(AccionAsesora.MOSTRAR_RESUMEN)
        # Escribe desde la cadena de la vitrina de WhatsApp y nunca la ha visto:
        # se le muestra (precio, fotos), como la apertura del anillo. Prueba de
        # verdad (04/10): preguntó cuánto se demora y le contestaron solo eso.
        if (
            texto
            and texto.startswith(NOTA_DE_LA_VITRINA)
            and pregunta_por_cadenas(texto.split("\n", 1)[0])
            and AccionAsesora.MOSTRAR_CADENA.value not in borrador.mostrado_en
            and AccionAsesora.MOSTRAR_CADENA not in acciones
        ):
            acciones.append(AccionAsesora.MOSTRAR_CADENA)
        # Ya había visto el resumen y cambió algo (el color, el grabado): el
        # resumen nuevo va en ESTE turno, para que su «sí» siguiente sea al
        # resumen de verdad y le lleguen las cuentas. Prueba de verdad (04/10):
        # cambió el color, el bot mandó solo la foto, y a su «ahora sí,
        # perfecto» le respondió con el resumen y otra confirmación.
        elif (
            not nuevo.pedido_id
            and borrador.ultimo_resumen
            and not nuevo.falta_para_abono()
            and nuevo.resumen() != borrador.ultimo_resumen
            and AccionAsesora.MOSTRAR_RESUMEN not in acciones
            and AccionAsesora.PEDIR_ABONO not in acciones
        ):
            acciones.append(AccionAsesora.MOSTRAR_RESUMEN)
        # Con el resumen completo ya mostrado y sin cambios, su «sí / así está
        # bien / perfecto» ES la confirmación: van las cuentas. Prueba de verdad
        # (04/10): tras el resumen el modelo preguntó «¿Simba va en el lado 1?»,
        # ella dijo «así está bien» y le volvieron a preguntar «¿Así está todo
        # bien?» antes de mandarle las cuentas.
        if (
            not nuevo.pedido_id
            and not borrador.cuentas_enviadas
            and borrador.ultimo_resumen
            and borrador.ultimo_resumen == nuevo.resumen()
            and not nuevo.falta_para_abono()
            and solo_afirma(texto)
            and AccionAsesora.PEDIR_ABONO not in acciones
            and AccionAsesora.MANDAR_CUENTAS not in acciones
        ):
            acciones.append(AccionAsesora.PEDIR_ABONO)
            rechazos.append("confirmó el resumen: van las cuentas del abono")
        # Acusar recibo del pago y pedir el pago son incompatibles. La bandera
        # `abono_reportado` no basta: se pone al EJECUTAR RECIBIR_COMPROBANTE,
        # que pasa más abajo, así que cuando las dos acciones vienen en el mismo
        # turno —justo lo que hace el modelo con un «ya transferí»— las cuentas
        # se colaban debajo del «¡Recibido!» (20/09). Se mira la acción.
        ya_pago = (
            nuevo.abono_reportado
            # Pagó antes de terminar de escoger (prueba de verdad, 04/10): al
            # completar el pedido le volvían a llegar las cuentas del abono.
            or nuevo.pagado_sin_pedido
            or borrador.pagado_sin_pedido
            or (
                # Solo si el comprobante es de verdad: el mismo requisito que
                # se le pide más abajo a la acción.
                AccionAsesora.RECIBIR_COMPROBANTE in acciones
                and (media or habla_de_pago(texto))
            )
            or estado not in ("", "ESPERANDO_ANTICIPO")
        )
        for pedir in (AccionAsesora.PEDIR_ABONO, AccionAsesora.MANDAR_CUENTAS):
            if pedir in acciones and ya_pago:
                # Pasó 19/09: dio su nombre DESPUÉS de mandar el comprobante y
                # el bot le volvió a mandar las cuentas del abono.
                acciones.remove(pedir)
                rechazos.append("el abono ya se reportó: no se vuelve a pedir")
        if AccionAsesora.PASAR_A_LIA in acciones and pasar_a_lia_sin_motivo(
            jugada.cambios, texto
        ):
            acciones.remove(AccionAsesora.PASAR_A_LIA)
            rechazos.append("pasar a Lía sin motivo: solo dio su nombre o su ciudad")
        if AccionAsesora.PASAR_A_LIA in acciones:
            respuesta.escalar = True
            notas.append(f"Pasar a Lía: {jugada.lectura}")

        # Un pedido que ya existe solo recibe lo que su ESTADO permite (ADR 0013).
        if pedido is not None:
            self._sincronizar(borrador, nuevo, pedido, respuesta, notas, rechazos)
            if borrador.envio_con_saldo != nuevo.envio_con_saldo:
                self._envio_al_pedido(borrador, nuevo, pedido, respuesta, notas, rechazos)

        # 1. El resumen, si toca, va ANTES del mensaje: «¿así está bien?» lo sigue.
        cabecera = Respuesta()
        # La talla que acaba de salir de una medida la dice el SISTEMA, con el
        # número exacto que quedó guardado. Si se deja en manos del modelo y
        # dice otro (6.5 contra 7), el vigilante le borra la frase y la clienta
        # recibe un «¡Perfecto!» a secas sin saber su talla (20/09).
        if talla_para_lia:
            # Regla de Lía (29/09): ninguna talla calculada se le dice. Lía
            # la confirma en el panel y ahí le llega; mientras, se sigue. Si
            # manda OTRA foto de la regla, no se le repite la misma frase
            # (prueba de verdad, 05/10).
            ya_se_lo_dije = any(
                TALLA_EN_REVISION[:30] in (m.get("texto") or "")
                for m in ctx.charla[-6:]
                if m.get("de") == "lia"
            )
            cabecera.decir(OTRA_MEDIDA if ya_se_lo_dije else TALLA_EN_REVISION)
        elif (
            not self._talla_la_confirma_lia
            and nuevo.talla is not None
            and nuevo.talla != borrador.talla
            and jugada.cambios.talla is None
        ):
            # Si salió de una medida escrita es una REFERENCIA, y así se le
            # dice (27/09: «1.8» salió como «¡Es una talla 8!», y 18 mm cae
            # entre 7½ y 8). Lía la confirma desde el panel; nada se detiene.
            cabecera.decir(
                referencia_para_la_clienta(nuevo.talla, nuevo.talla_rango)
                if nuevo.talla_revisar
                else f"¡Es una talla {talla_texto(nuevo.talla)}! 💍"
            )
        # Tocó «💍 Quiero separarlo» (o lo dijo) y ya no falta nada: el resumen,
        # sin depender de que la IA lo pida (13/10).
        if (
            quiere_separar(texto)
            and not nuevo.pedido_id
            and not nuevo.falta_para_abono()
            and AccionAsesora.MOSTRAR_RESUMEN not in acciones
            and AccionAsesora.PEDIR_ABONO not in acciones
        ):
            acciones.append(AccionAsesora.MOSTRAR_RESUMEN)
        resumen_antes = AccionAsesora.MOSTRAR_RESUMEN in acciones or (
            AccionAsesora.PEDIR_ABONO in acciones and not nuevo.pedido_id
        )
        # Si el resumen salió DE VERDAD en este turno. La cabecera no basta para
        # saberlo: puede llevar solo «te confirmo tu talla en unos minutos», y
        # debajo le llegaba «¿Así está bien? 🥰» sin nada que confirmar (chats
        # de prueba del 29/09).
        resumen_mostrado = False
        if resumen_antes and not nuevo.falta_para_abono():
            if nuevo.resumen() != nuevo.ultimo_resumen:
                cabecera.decir(nuevo.resumen())
                nuevo.ultimo_resumen = nuevo.resumen()
                resumen_mostrado = True
        elif resumen_antes:
            rechazos.append(ABONO_BLOQUEADO + ", ".join(nuevo.falta_para_abono()))

        # 2. Las acciones se ejecutan ANTES de vigilar el mensaje: si esta misma
        #    jugada recibe el comprobante, «ya tomé tu pedido» ya es verdad.
        fichas = Respuesta()
        # El resumen cambió EN ESTE turno y ella todavía no ha dicho que sí.
        # Se mira antes del bucle: PEDIR_ABONO y MANDAR_CUENTAS son la misma
        # decisión —pedirle plata— y tienen que caer juntas, venga como venga
        # el orden de las acciones (20/09: bloqueó una y la otra mandó el Nequi
        # debajo del «¿está todo bien?»).
        resumen_sin_confirmar = (
            AccionAsesora.PEDIR_ABONO in acciones
            and not nuevo.pedido_id
            and borrador.ultimo_resumen != nuevo.ultimo_resumen
        )
        abono_en_espera = False
        pregunta_en_el_pie = False
        # Preguntó por la cadena y todavía no se le ha mostrado: va DE UNA, sin
        # «¿quieres que te cuente cómo es?» (Erika, 07/10: «Y la cadena con 3
        # huellitas» -> «…¿Quieres que te cuente cómo es?»).
        if (
            pregunta_por_cadenas(texto)
            and AccionAsesora.MOSTRAR_CADENA not in acciones
            and AccionAsesora.MOSTRAR_CADENA.value not in nuevo.mostrado_en
        ):
            acciones.append(AccionAsesora.MOSTRAR_CADENA)
        # Pregunta por el anillo de corazón (o por uno sin huellita, Martha 17/10)
        # y no lo ha visto: su presentación va de una, como la de la cadena.
        if (
            habla_del_corazon(texto)
            and AccionAsesora.MOSTRAR_CORAZON not in acciones
            and AccionAsesora.MOSTRAR_CORAZON.value not in nuevo.mostrado_en
        ):
            acciones.append(AccionAsesora.MOSTRAR_CORAZON)
        # Abrió con «¿Cómo se llama tu peludito?» (13/10): en su segundo mensaje
        # va la presentación (ficha, videos y la foto con «¿Sabes tu talla?»).
        if (
            APERTURA_PELUDITO in borrador.mostrado_en
            and AccionAsesora.MOSTRAR_PRECIOS.value not in nuevo.mostrado_en
            and AccionAsesora.MOSTRAR_PRECIOS not in acciones
            and AccionAsesora.MOSTRAR_CADENA not in acciones
            and AccionAsesora.MOSTRAR_CORAZON not in acciones
            # Preguntó por otra cosa (cobijas, 16/10) y se pasó a Lía: la
            # presentación del anillo ahí no le contesta nada.
            and AccionAsesora.PASAR_A_LIA not in acciones
            and not no_quiere(texto or "")
        ):
            acciones.insert(0, AccionAsesora.MOSTRAR_PRECIOS)
        if (
            AccionAsesora.MOSTRAR_CORAZON in acciones
            and AccionAsesora.MOSTRAR_CORAZON.value not in nuevo.mostrado_en
            and AccionAsesora.MOSTRAR_PRECIOS in acciones
            # Salvo que de entrada pida también uno de huellita («uno de huellita
            # para mí y uno de corazón para mi esposo»): ahí van las dos.
            and (
                APERTURA_PELUDITO in borrador.mostrado_en
                or not _PIDE_UNO_DE_HUELLITA.search(texto or "")
            )
        ):
            # Preguntó por el anillo de corazón: le llega SU presentación. Las
            # dos juntas (dos videos, la foto, la ficha de la huellita y la del
            # corazón) eran demasiado para una pregunta (prueba del 17/10). Los
            # precios de la huellita, si los pide, el modelo los dice en una línea.
            acciones = [a for a in acciones if a is not AccionAsesora.MOSTRAR_PRECIOS]
        if no_quiere(texto or "") and "?" not in (texto or ""):
            # No le interesa (10/10): no se le muestra nada que no pidió (le
            # llegó la cadena —también de plata— a «no me gusta la plata»).
            quitadas = [a for a in acciones if a.value.startswith("MOSTRAR_")]
            acciones = [a for a in acciones if a not in quitadas]
            if quitadas:
                rechazos.append(
                    "no le interesa: no se le muestra nada más ("
                    + ", ".join(a.value for a in quitadas)
                    + ")"
                )
        for accion in acciones:
            if accion in SOLO_UNA_VEZ_EN_LA_CHARLA and accion.value in nuevo.mostrado_en:
                rechazos.append(
                    f"{accion.value} ya se mandó en esta conversación: contéstale "
                    "el precio con una frase, sin reenviar la presentación"
                )
                continue
            if accion in UNA_VEZ and nuevo.mostrado_en.get(accion.value, -9) >= (
                nuevo.turnos - 1
            ):
                rechazos.append(f"{accion.value} ya se mandó en el turno anterior")
                continue
            if accion is AccionAsesora.MOSTRAR_PRECIOS:
                # Lo mismo que manda Lía de primeras: la ficha, los dos videos
                # y la foto del anillo. Es su presentación entera, y es lo que
                # hace que alguien pregunte el precio y no se vaya.
                #
                # LA PREGUNTA VA DE PIE DEL ÚLTIMO MEDIO, no en un mensaje
                # aparte: WhatsApp junta los medios seguidos en un álbum y el
                # pie queda debajo, como en el mensaje de Lía. En un mensaje
                # suelto quedaría despegado del álbum.
                # Si ya sabemos su talla, la presentación no la pregunta y
                # el cierre lo pone el modelo (que sí sabe de qué se habló).
                falta_la_talla = nuevo.talla is None
                # Si es un regalo, la talla no es la suya (17/10: «es para mi
                # hermana» y le llegaba «¿Sabes TU talla?»).
                dicho_por_ella = " ".join(
                    [m.get("texto", "") for m in ctx.charla if m.get("de") == "clienta"]
                    + [texto or ""]
                )
                self._presentacion(
                    fichas,
                    preguntar_talla=falta_la_talla,
                    regalo=es_para_otra_persona(dicho_por_ella),
                )
                pregunta_en_el_pie = falta_la_talla
            elif accion is AccionAsesora.MOSTRAR_CADENA:
                if not pregunta_por_cadenas(texto):
                    # La regla de Camilo (03/10): la cadena NUNCA se ofrece.
                    rechazos.append(
                        "ella no preguntó por cadenas ni por más productos: la cadena "
                        "no se ofrece (no la menciones)"
                    )
                    continue
                h = self._hechos
                if pide_cadena_con_varias(texto):
                    fichas.decir(CADENA_CON_UNA)
                fichas.decir(
                    MENSAJE_DE_LA_CADENA.format(
                        precio=formatear_cop(h.precio_cadena),
                        abono=formatear_cop(h.anticipo_cadena),
                    )
                )
                for foto in FOTOS_DE_LA_CADENA:
                    fichas.mostrar(foto)
            elif accion is AccionAsesora.MOSTRAR_CORAZON:
                # El anillo de corazón (17/10): con la misma estructura que la
                # ficha de la huellita. A diferencia de la cadena, sí se ofrece.
                fichas.decir(self._hechos.ficha_del_corazon())
                for foto in FOTOS_DEL_CORAZON:
                    fichas.mostrar(foto)
            elif accion is AccionAsesora.MOSTRAR_GUIA_TALLA:
                if no_tiene_anillos(texto, ultimo_de_lia):
                    # Sin anillo, la guía (medir un anillo) no le sirve: va la
                    # joyería, más abajo (05/10).
                    rechazos.append(
                        "no tiene anillos: la guía no le sirve (se le dijo lo de la "
                        "joyería)"
                    )
                    continue
                if (
                    nuevo.talla is not None
                    and nuevo.talla_confirmada
                    and not pide_la_guia(texto)
                ):
                    # Ella ya DIJO su talla: no se duda de ella ni se le pide la
                    # regla (prueba de verdad, 05/10: «¿la talla 6 es la
                    # definitiva o te comparto la guía?» + la guía).
                    rechazos.append(
                        f"ella ya dijo su talla ({talla_texto(nuevo.talla)}) y quedó: "
                        "no se le manda la guía ni se le pregunta si es la definitiva"
                    )
                    continue
                fichas.decir(GUIA_TALLA)
                fichas.mostrar("medir_talla_guia")
            elif accion is AccionAsesora.MOSTRAR_MUESTRARIO:
                fichas.mostrar(
                    "muestrario_circones",
                    pie="Estos son los colores de circón que manejamos 🩵🩷",
                )
            elif accion is AccionAsesora.MOSTRAR_EJEMPLOS:
                # La segunda era la foto vieja de los circones SIN nombres (02/10,
                # Camilo: «le falta la parte de la imagen»): va la del muestrario.
                # 13/10: `anillo_ejemplo_3` era un anillo DORADO sobre una regla
                # (no es nuestro). 15/10: va el collage «Inspirado en tu mascota».
                for nombre in (
                    "anillos_inspirado_en_tu_mascota",
                    "anillo_ejemplo_1",
                    "muestrario_circones",
                ):
                    fichas.mostrar(nombre)
            elif (
                accion
                in (
                    AccionAsesora.MOSTRAR_COMO_QUEDA,
                    AccionAsesora.MOSTRAR_SUGERENCIAS,
                )
                and nuevo.es_corazon
            ):
                # El anillo de corazón (17/10): como en la huellita, pero se
                # dibuja SOLO el corazón, al derecho, de su color.
                self._como_queda_el_corazon(
                    nuevo,
                    fichas,
                    jugada,
                    sugerencias=accion is AccionAsesora.MOSTRAR_SUGERENCIAS,
                )
            elif accion is AccionAsesora.MOSTRAR_COMO_QUEDA:
                self._como_queda(nuevo, fichas, jugada)
            elif accion is AccionAsesora.MOSTRAR_SUGERENCIAS:
                self._sugerencias(nuevo, fichas)
            elif accion is AccionAsesora.QUITAR_COLORES:
                # «No ya no me gusto» y todavía no dice cuál quiere. Si en el
                # mismo mensaje sí dijo el color nuevo, ese manda: lo acaba de
                # escoger y borrarlo sería preguntárselo otra vez.
                if not jugada.cambios.huellitas:
                    sin_colores(nuevo)
                    rechazos.append("dijo que ya no le gusta el color: se vuelve a pedir")
            elif accion is AccionAsesora.MANDAR_CUENTAS and not (
                resumen_sin_confirmar and resumen_mostrado
            ):
                self._mandar_cuentas(
                    nuevo, pedido, fichas, rechazos, lo_pidio=pide_las_cuentas(texto)
                )
            elif resumen_sin_confirmar and resumen_mostrado:
                # Primero que lo vea y diga que sí. Pasó: el diseño pasó de 2
                # huellitas a 1 y en el mismo mensaje se creó el pedido y se
                # mandaron las cuentas.
                abono_en_espera = True
                rechazos.append(
                    "no se pidieron las cuentas: el resumen es nuevo y ella no lo ha "
                    "confirmado"
                )
            elif accion is AccionAsesora.PEDIR_ABONO:
                self._pedir_abono(conversation_id, nuevo, fichas, rechazos, notas)
            elif accion is AccionAsesora.RECIBIR_COMPROBANTE and not (
                media or habla_de_pago(texto)
            ):
                # Pasó: «sí, así está perfecto» -> «recibir comprobante» y el pedido
                # quedaba en revisión de pago sin que nadie hubiera pagado.
                rechazos.append(
                    "no llegó comprobante ni dijo que pagó: no se registra ningún pago"
                )
            elif accion is AccionAsesora.RECIBIR_COMPROBANTE:
                self._recibir_comprobante(
                    conversation_id, nuevo, fichas, notas, rechazos, pedido
                )
            if accion in UNA_VEZ or accion in SOLO_UNA_VEZ_EN_LA_CHARLA:
                nuevo.mostrado_en[accion.value] = nuevo.turnos
        # Pide ver UNO de los anillos («muéstrame el de 2», «¿cómo es el de una
        # huellita?»): le llega solo esa pieza de la presentación (Camilo, 13/10).
        cual = pide_ver_el_de(texto)
        if (
            cual
            and AccionAsesora.MOSTRAR_PRECIOS.value in borrador.mostrado_en
            # «¿Me muestras cómo queda una rosada y otra lila?» pide ver SUS
            # colores (sale el dibujo), no el video del de 2 (17/10).
            and AccionAsesora.MOSTRAR_COMO_QUEDA not in acciones
        ):
            nombre_de_la_pieza, es_video = PIEZA_DE_CADA_ANILLO[cual]
            if es_video:
                fichas.reproducir(nombre_de_la_pieza)
            else:
                fichas.mostrar(nombre_de_la_pieza)
        if (
            nuevo.pagado_sin_pedido
            and nuevo.pedido_id is None
            and not nuevo.falta_para_abono()
        ):
            # Ya había pagado; con lo que dijo ahora el pedido quedó completo.
            self._recibir_comprobante(conversation_id, nuevo, fichas, notas, rechazos)
        # Quiere pagar aunque falten datos (Camilo, 05/10; Yesi: «Regálame por fis
        # la cuenta para realizar el abono» y no salió: tuvo que mandarla una
        # persona). El bot no persigue el pago con el pedido a medias, pero si
        # ELLA lo pide —o lo insinúa: «¿cómo te pago?»— se le manda, y abajo se
        # le pide con cariño lo que falta. Lo que falte lo sigue el flujo normal
        # (pagó con el pedido a medias: `pagado_sin_pedido`).
        faltaba_al_pagar: list[str] = []
        if (
            pedido is None
            and not nuevo.pedido_id
            and not (nuevo.abono_reportado or nuevo.pagado_sin_pedido)
            and not abono_en_espera
            and nuevo.mostrado_en.get("MANDAR_CUENTAS") != nuevo.turnos
            and nuevo.mostrado_en.get("PEDIR_ABONO") != nuevo.turnos
            and nuevo.falta_para_abono()
            and (
                quiere_la_cuenta(texto)
                # La IA entendió que quiere pagar y no fue un pago (rara vez
                # inventa esto: la regla 8 del prompt lo pide solo si ella habla
                # de pagar).
                or (
                    AccionAsesora.MANDAR_CUENTAS in acciones
                    and bool(_HABLA_DE_PAGAR.search(texto or ""))
                    and not paga_despues(texto)
                )
            )
        ):
            rechazos[:] = [r for r in rechazos if not r.startswith(ABONO_BLOQUEADO)]
            self._mandar_cuentas(nuevo, pedido, fichas, rechazos, lo_pidio=True)
        if (
            pedido is None
            and not nuevo.pedido_id
            and not (nuevo.abono_reportado or nuevo.pagado_sin_pedido)
            and nuevo.mostrado_en.get("MANDAR_CUENTAS") == nuevo.turnos
        ):
            # Salieron con el pedido a medias (las pidió ella o la IA entendió
            # que quería pagar): debajo, con cariño, lo que falta.
            faltaba_al_pagar = nuevo.falta_para_abono()
        respuesta.escalar = respuesta.escalar or fichas.escalar

        # 3. Vigilar con el estado YA actualizado.
        montos = self._montos(nuevo, pedido)
        promos = self._hechos.promociones_de_hoy()
        mensaje, problemas = vigilar(jugada.mensaje, montos, nuevo, estado, promos)
        final, problemas_final = vigilar(
            jugada.mensaje_final, montos, nuevo, estado, promos
        )
        rechazos += problemas + problemas_final
        # Sin anillos para medir: el dedo con papel o hilo y el video, dicho por
        # el sistema (Camilo, 13/10). Si el modelo también lo explicó, se quita
        # lo suyo (y su «¿cuántos centímetros te da?»): si no, lo lee dos veces.
        propone_el_dedo = bool(_MIDE_EL_DEDO.search(f"{mensaje}\n{final}"))
        ya_la_tiene = SIN_ANILLOS in nuevo.mostrado_en
        if propone_el_dedo and ya_la_tiene and not no_tiene_anillos(texto, ultimo_de_lia):
            # Ya le llegó la guía del dedo con el video: no se le repite (prueba de
            # verdad, 13/10: al dar su nombre le llegó otra vez entera).
            mensaje = _PIDE_LOS_CM.sub("", _MIDE_EL_DEDO.sub("", mensaje)).strip()
            final = _PIDE_LOS_CM.sub("", _MIDE_EL_DEDO.sub("", final)).strip()
        elif (
            nuevo.talla is None
            and not nuevo.es_cadena
            and not nuevo.pedido_id
            and (
                no_tiene_anillos(texto, ultimo_de_lia)
                or (propone_el_dedo and not ya_la_tiene)
            )
            and nuevo.mostrado_en.get(SIN_ANILLOS, -9) < nuevo.turnos - 1
        ):
            mensaje = _PIDE_LOS_CM.sub("", _MIDE_EL_DEDO.sub("", mensaje)).strip()
            final = _PIDE_LOS_CM.sub("", _MIDE_EL_DEDO.sub("", final)).strip()
            cabecera.decir(TALLA_SIN_ANILLOS)
            cabecera.reproducir(VIDEO_DEL_DEDO, pie=PIE_DEL_VIDEO_DEL_DEDO)
            nuevo.mostrado_en[SIN_ANILLOS] = nuevo.turnos
            # Se va a medir: la talla la trae ella después. No se le pide más
            # en la charla (09/10).
            nuevo.lo_manda_despues.setdefault("talla", nuevo.turnos)
        # Pregunta por dorado, oro o baños (05/10): la regla de la plata, dicha
        # por el sistema y siempre igual; lo que el modelo dijo del metal se
        # quita (si no, lo lee dos veces con otras palabras).
        if pregunta_por_otro_metal(texto) and nuevo.mostrado_en.get(PLATA, -9) < (
            nuevo.turnos - 1
        ):
            mensaje = sin_lo_del_metal(mensaje)
            final = sin_lo_del_metal(final)
            cabecera.decir(SOLO_EN_PLATA)
            nuevo.mostrado_en[PLATA] = nuevo.turnos
        # La cadena con varias huellitas (09/10), cuando la información de la
        # cadena ya se le mandó antes: la regla, dicha por el sistema.
        if (
            pide_cadena_con_varias(texto)
            and nuevo.mostrado_en.get(AccionAsesora.MOSTRAR_CADENA.value) != nuevo.turnos
            and CADENA_CON_UNA not in fichas.texto_plano
        ):
            cabecera.decir(CADENA_CON_UNA)
        if CADENA_CON_UNA in f"{fichas.texto_plano}\n{cabecera.texto_plano}":
            # Lo dice el sistema: lo mismo dicho por el modelo sobra (sale dos
            # veces seguidas, prueba de verdad del 09/10).
            mensaje = _UNA_SOLA_HUELLITA.sub("", mensaje).strip()
            final = _UNA_SOLA_HUELLITA.sub("", final).strip()
        # Le mandamos la cuenta con el pedido a medias (porque ella quiso): el
        # mensaje no puede decirle que «faltan datos para poder iniciar» encima
        # de los datos; lo que falta va DESPUÉS, sin presionar.
        if faltaba_al_pagar and (
            debajo := lo_que_falta_al_pagar(faltaba_al_pagar, nuevo)
        ):
            # Su pregunta va debajo de los datos: la del modelo, arriba, sobra.
            mensaje = _PREGUNTA.sub("", _SIN_LO_QUE_FALTA.sub("", mensaje)).strip()
            if len(mensaje) < 20:
                mensaje = f"{mensaje or '¡Claro!'} 💓 Te dejo los datos 👇"
            final = debajo
        if not self._cadena_permitida(nuevo, texto, ctx.charla):
            # La red de seguridad (03/10): la cadena no se ofrece por cuenta propia.
            mensaje, quito = quitar_cadena_no_pedida(mensaje)
            final, quito_final = quitar_cadena_no_pedida(final)
            if quito or quito_final:
                rechazos.append(
                    "nombraba la cadena sin que ella preguntara: se quitó (la cadena "
                    "nunca se ofrece)"
                )
        # Un comprobante no se juzga (Camilo, 04/10): si el valor no es exacto o
        # el nombre no cuadra, lo verifica Lía. A la clienta, que lo recibimos;
        # a Lía, lo que se vio y la charla marcada para una persona. Pasó el
        # 04/10: «La captura muestra $59.700 enviados a otra persona… ¿Querías
        # enviarme otro comprobante?».
        comprobante_ahora = (
            AccionAsesora.RECIBIR_COMPROBANTE in acciones
            and adjunto
            and (
                nuevo.abono_reportado != borrador.abono_reportado
                or nuevo.saldo_reportado != borrador.saldo_reportado
                or nuevo.pagado_sin_pedido
            )
        )
        # Dijo que ya pagó («ya te transferí los 60 mil») sin mandar nada: queda
        # registrado y se le pide el comprobante, que es lo que Lía verifica.
        # Prueba de verdad (04/10): «Apenas Lía verifique… ¿Quieres que el envío
        # vaya a una ciudad distinta a Bucaramanga?», sin pedirlo.
        pago_de_palabra = (
            AccionAsesora.RECIBIR_COMPROBANTE in acciones
            and not adjunto
            and habla_de_pago(texto)
            and (
                nuevo.abono_reportado != borrador.abono_reportado
                or nuevo.saldo_reportado != borrador.saldo_reportado
            )
        )
        if pago_de_palabra and "comprobante" not in f"{mensaje} {final}".lower():
            mensaje, final = PIDE_EL_COMPROBANTE, ""
            rechazos.append("dijo que pagó: se le pide el comprobante para Lía")
        if comprobante_ahora and "recib" not in f"{mensaje} {final}".lower():
            # Mandó el comprobante y el bot contestó «¡Dale! 🙌 ¿Qué color…?»
            # (prueba de verdad, 04/10): primero se le acusa recibo.
            mensaje = "¡Recibido! 🙌 " + re.sub(r"^\s*¡[^!]{1,15}!\s*\W*", "", mensaje)
        if comprobante_ahora and jugada.lectura:
            notas.append(f"🧾 Lo que se leyó del comprobante: {jugada.lectura}")
        if comprobante_ahora and duda_del_comprobante(
            f"{mensaje} {final} {jugada.lectura}"
        ):
            if duda_del_comprobante(f"{mensaje} {final}"):
                mensaje, final = COMPROBANTE_RECIBIDO, ""
                rechazos.append(
                    "dudaba del comprobante: se recibe igual y lo verifica Lía"
                )
            notas.append(
                "⚠️ El comprobante no parece cuadrar (valor o destinatario): "
                "revísalo tú antes de confirmarlo"
            )
            respuesta.escalar = True
        # Los datos de envío se piden al final, con el anillo listo (20/09).
        guia_a_tiempo = pedido is not None and (
            pedido.estado in ("PRODUCCION_LISTA", "ESPERANDO_SALDO", "SALDO_PAGADO")
            or (pedido.estado == "EN_REVISION_PAGO" and nuevo.saldo_reportado)
        )
        if not guia_a_tiempo:
            mensaje, quito = quitar_pedida_de_envio(mensaje)
            final, quito_final = quitar_pedida_de_envio(final)
            if quito or quito_final:
                rechazos.append(
                    "preguntaba datos de envío antes de tiempo: se quitó (van al "
                    "final, con las fotos del anillo listo)"
                )
        if tallas_de_varios and re.search(
            r"regla|medida|talla", f"{mensaje} {final}", re.I
        ):
            # El modelo solo vio una talla y pedía la otra (o la foto de la
            # regla): se le confirman las dos y sigue lo que falta.
            mensaje = "¡Anotadas! 💍 " + " · ".join(
                f"Anillo {i + 1}: talla {talla_texto(t)}" for i, t in tallas_de_varios
            )
            final = ""
        elif (
            not nuevo.varios
            and len(dos := tallas_escritas(texto)) >= 2
            and re.search(r"talla|regla|medida", f"{mensaje} {final}", re.I)
            and "?" in f"{mensaje} {final}"
        ):
            # Dio las tallas de dos anillos antes de que existiera el segundo:
            # quedan anotadas (se le ponen a cada uno al crearse) y no se le
            # vuelve a preguntar la del otro (prueba de verdad, 04/10).
            mensaje = "¡Anotadas! 💍 " + " y ".join(
                f"talla {talla_texto(t)}" for t in dos
            )
            final = ""
        mensaje, final, de_mas = una_sola_pregunta(mensaje, final)
        if de_mas:
            rechazos.append("preguntaba dos cosas a la vez: quedó la primera (ADR 0024)")
        # Pidió la cuenta con todas las letras y no salió: el modelo contestó
        # «las tres están arriba» o las escribió a mano (el vigilante borró los
        # números y quedaba «A nombre de LÍA GÓMEZ» sin un dato). Si la
        # pide, se le manda: es lo que necesita para poder pagar (21/09).
        ya_salieron = (
            nuevo.mostrado_en.get("MANDAR_CUENTAS") == nuevo.turnos
            or nuevo.mostrado_en.get("PEDIR_ABONO") == nuevo.turnos
        )
        if (
            # Solo REENVIAR: si nunca se le mandaron, es porque algo las frena
            # (el resumen sin confirmar, un dato que falta) y eso manda.
            borrador.cuentas_enviadas
            and not abono_en_espera
            and quiere_la_cuenta(texto)
            and not ya_salieron
            and not (nuevo.abono_reportado or nuevo.saldo_reportado)
        ):
            ya_las_tenia = nuevo.cuentas_enviadas
            self._mandar_cuentas(nuevo, pedido, fichas, rechazos, lo_pidio=True)
            if nuevo.mostrado_en.get("MANDAR_CUENTAS") == nuevo.turnos and (
                ya_las_tenia or any(p.startswith(CUENTA_A_MANO) for p in problemas)
            ):
                mensaje, final = "¡Claro! 💓 Te las comparto de nuevo:", ""
        graves = [
            p for p in problemas + problemas_final if p.startswith(PROBLEMAS_GRAVES)
        ]
        dichos = [m.get("texto", "") for m in ctx.charla if m.get("de") == "lia"][-3:]
        vaciado = bool(
            (jugada.mensaje + jugada.mensaje_final).strip()
            and not (mensaje + final).strip()
            and fichas.vacia
            and cabecera.vacia
        )
        abono_bloqueado = next(
            (
                r[len(ABONO_BLOQUEADO) :]
                for r in rechazos
                if r.startswith(ABONO_BLOQUEADO)
            ),
            "",
        )
        repetido = repite_lo_dicho(f"{mensaje}\n{final}", dichos)
        # El cierre hay que mirarlo APARTE. Comparando solo el mensaje entero,
        # la misma pregunta pasaba de contrabando detrás de una frase distinta:
        # el 20/09 pidió la talla cuatro turnos seguidos («¡Perfecto! 3
        # huellitas», «¡Qué combinación tan linda!», «Perfecto, liso»), y como
        # arriba cambiaba, el parecido total nunca llegaba al 75%.
        repetido = repetido or repite_lo_dicho(final, dichos)
        if repetido and not (fichas.vacia and cabecera.vacia):
            # Con fichas en medio solo se atiende la pregunta final repetida.
            repetido = repetido if repite_lo_dicho(final, dichos) else None

        # Un mensaje que no se puede mandar se REESCRIBE con lo que dijo la clienta,
        # no se cambia por una frase fija: la frase fija es la que suena a bot.
        motivo = ""
        if guardia_cantidad and nuevo.veces_preguntando_cantidad >= VECES_ANTES_DE_LIA:
            # La guardia no tenía salida: si ella cree que ya contestó («listo,
            # así»), la conversación daba vueltas hasta que se aburría —en un
            # repaso llegó a decir que ya había pagado y el bot seguía
            # preguntando lo mismo (20/09). Lía lo resuelve en un mensaje.
            mensaje, final = "Dame un momentico y te confirmo 🙌", ""
            respuesta.escalar = True
            notas.append(
                "Lleva "
                f"{nuevo.veces_preguntando_cantidad} veces sin decir de cuántas "
                "huellitas lo quiere (contesta «listo, así»): confírmaselo tú"
            )
            rechazos.append("tercera vez preguntando la cantidad: pasa a Lía")
        elif guardia_cantidad:
            motivo = (
                "la cantidad de huellitas no quedó anotada porque ella no la ha "
                "escrito: contesta a lo que dijo y pregúntale con opciones "
                "(¿de 1 o de 2 huellitas?)"
            )
        elif graves:
            motivo = "decía algo que no es verdad todavía: " + "; ".join(graves)
        elif abono_en_espera:
            motivo = (
                "NO se mandaron las cuentas: el diseño cambió y ella todavía no ha "
                "confirmado el resumen que acaba de recibir; pregúntale si así está bien"
            )
        elif vaciado:
            # Pasó: «Estoy en Bogotá» -> el modelo dio un envío que no era el de
            # la tabla, el vigilante quitó la frase y solo quedó «¡Listo! 🙌».
            motivo = "tenía frases que no se pueden mandar: " + "; ".join(
                problemas + problemas_final
            )
        elif abono_bloqueado:
            # El mensaje ya prometía las cuentas y el abono no salió. Sin esto
            # le llega la promesa sin lo prometido y la venta se para en seco
            # sin que ella sepa que falta algo (20/09).
            motivo = (
                "NO se mandaron las cuentas ni se tomó el pedido porque falta "
                f"{abono_bloqueado}. No prometas datos de pago ni digas que el "
                "pedido quedó tomado: contesta a lo que dijo y pídele ESO que "
                "falta, con cariño y en una frase"
            )
        elif repetido and not repite_lo_dicho(mensaje, dichos):
            # Solo repite la pregunta que va después de las fichas: sobra.
            final = ""
            rechazos.append("pregunta final repetida: se quitó")
        elif repetido:
            motivo = f"repetía casi igual algo que ya le dijiste: «{repetido}»"
        if motivo:
            otro = self._reescribir(
                texto,
                descripciones,
                jugada,
                motivo,
                nuevo,
                montos,
                dichos,
                con_opciones=guardia_cantidad,
                estado=estado,
            )
            if otro:
                # Lo reescrito también lleva UNA pregunta (prueba de verdad,
                # 04/10: «¿Y el de ella qué talla lleva? ¿De cuántas huellitas…?»).
                mensaje, final, _ = una_sola_pregunta(otro, "")
                if repetido and not (graves or guardia_cantidad):
                    rechazos.append("mensaje repetido: se reescribió")
            elif guardia_cantidad:
                mensaje = next(
                    (
                        p
                        for p in PREGUNTAS_DE_CANTIDAD
                        if not repite_lo_dicho(p, dichos) and p not in " ".join(dichos)
                    ),
                    PREGUNTAS_DE_CANTIDAD[-1],
                )
                final = ""
            elif graves and any(g.startswith(TALLER_SIN_ABONO) for g in graves):
                # Dijo que el anillo ya entraba al taller sin abono. «Quedo
                # atenta al comprobante» no le corrige esa idea (21/09, en un
                # repaso): se le dice, con los números de Python, qué va primero.
                mensaje, final = self._el_abono_va_primero(nuevo), ""
            elif graves:
                # Una mentira sobre el estado contamina el mensaje entero: lo que
                # queda alrededor sigue hablando como si fuera verdad.
                seguro = self._mensaje_seguro(nuevo, estado)
                # Con cuentas o fichas en medio, la frase va DESPUÉS: «quedo
                # atenta a tu comprobante» antes de los datos no tiene sentido.
                mensaje, final = ("", seguro) if not fichas.vacia else (seguro, "")
            elif abono_en_espera:
                mensaje, final = "¿Así está bien? 🥰", ""
            elif abono_bloqueado:
                # Sin red o con una reescritura que tampoco pasa: al menos que
                # sepa qué falta, y no una promesa de datos que no van.
                mensaje, final = self._lo_que_falta(nuevo, estado), ""

        # No le falta nada a ELLA (espera a Lía, ya pagó, ya tiene las cuentas y
        # solo falta que pague) o ella POSPONE («mañana le consigno», «ahora no
        # me queda fácil»): no se le pregunta nada y no se insiste; el
        # recordatorio del día siguiente hace lo suyo. Real: Laura (06/10),
        # «Gracias» -> «¿Quieres grabar algo más junto a Bombom?»; Mónica
        # (07/10), cinco «¿te ayudo con algo más?» seguidos mientras iba a pagar.
        # Lo que pregunta el SISTEMA se queda: «¿Me compartes el comprobante?»
        # cuando dijo que pagó sin mandarlo.
        # No le interesa (10/10): se agradece y se cierra, como cuando pospone.
        desinteres = no_quiere(texto or "")
        callar = (
            nada_que_preguntarle(nuevo, estado) or pospone(texto or "") or desinteres
        ) and "?" not in (texto or "")
        if callar and PIDE_EL_COMPROBANTE not in f"{mensaje}\n{final}":
            mensaje, final = sin_preguntas_de_mas(mensaje), sin_preguntas_de_mas(final)
            if not (mensaje or final) and fichas.vacia and cabecera.vacia:
                mensaje = (
                    SI_ALGUN_DIA
                    if desinteres and not pospone(texto or "")
                    else "¡Dale! 🫶 Quedo atenta; cualquier duda, me cuentas"
                    if pospone(texto or "")
                    else "¡Con gusto! 🥰"
                    if _AGRADECE.search(texto or "")
                    else "¡Listo! 🫶"
                )
        # Lo deja para después («el otro mes», «mañana»): se agradece y se
        # cierra, SIN prometer escribirle ni «programar un recordatorio» (Camilo,
        # 09/10), salvo que ella pida que le escriban.
        if (pospone(texto or "") or desinteres) and not pide_que_le_escriban(texto or ""):
            mensaje = sin_promesas_de_escribir(mensaje)
            final = sin_promesas_de_escribir(final)
            if not (mensaje or final) and fichas.vacia and cabecera.vacia:
                mensaje = "¡Dale! 🫶 Quedo atenta; cualquier duda, me cuentas"
        # Confirmar lo que ella ya dijo claro y quedó anotado es preguntar de
        # más: «Adela» -> «¿Así quedan los dos nombres?» (Laura, 06/10). Si ella
        # contestó OTRA cosa o solo una parte, sí se le sigue preguntando lo que
        # falta (Camilo, 07/10: «No así toda» -> quedaba sin pedir el grabado).
        antes_de_quitar = mensaje + final
        mensaje, final = (
            sin_pedir_lo_anotado(mensaje, nuevo),
            sin_pedir_lo_anotado(final, nuevo),
        )
        # No acosar (09/10): lo que dijo que manda después, o lo que ya se le
        # pidió dos veces sin que lo diera, no se le vuelve a pedir —ni con «¿?»
        # ni con «mándame…»—. Lo retoma el recordatorio.
        no_pedir = que_no_se_pide(nuevo)
        # Ya tiene la guía (de un turno anterior) y ahora habla de otra cosa:
        # está midiendo, no se le vuelve a preguntar por la talla (13/10, prueba:
        # tras la guía, «de una huellita, se llama Mimi» -> «¿Ella tiene algún
        # anillo que pueda medir con la guía?»). Se sigue con el diseño.
        guia_en = nuevo.mostrado_en.get(AccionAsesora.MOSTRAR_GUIA_TALLA.value)
        if (
            guia_en is not None
            and guia_en < nuevo.turnos
            and not _HABLA_DE_LA_TALLA.search(texto or "")
        ):
            no_pedir = {*no_pedir, "talla"}
        if no_pedir:
            mensaje, final = sin_pedir(mensaje, no_pedir), sin_pedir(final, no_pedir)
        # Lo que quedó sin una sola letra («🐾» suelto) no dice nada.
        if not any(c.isalnum() for c in mensaje):
            mensaje = ""
        if not any(c.isalnum() for c in final):
            final = ""
        if "?" not in (texto or "") and cambio_anotado(borrador, nuevo):
            mensaje = sin_confirmar_lo_dicho(mensaje)
            final = sin_confirmar_lo_dicho(final)
        if antes_de_quitar.strip() and not (mensaje or final):
            # Solo confirmaba o volvía a pedir lo anotado: queda el «anotado» y
            # el sistema sigue con lo que falte.
            mensaje = (
                "¡Dale! Quedo atenta 🫶"
                if any(n == borrador.turnos for n in nuevo.lo_manda_despues.values())
                else "¡Anotado! 🫶"
            )
        # La información ya va (la cadena se mostró en este turno): ofrecerla
        # sobra.
        if nuevo.turnos in (
            nuevo.mostrado_en.get(AccionAsesora.MOSTRAR_CADENA.value),
            nuevo.mostrado_en.get(AccionAsesora.MOSTRAR_CORAZON.value),
        ):
            mensaje = re.sub(r"[ \t]{2,}", " ", _OFRECE_CONTAR.sub("", mensaje)).strip()
            final = re.sub(r"[ \t]{2,}", " ", _OFRECE_CONTAR.sub("", final)).strip()
        # Lo que va grabado, entre comillas: que sepa exactamente qué lleva el aro
        # (Camilo, 06/10: «que quede en comillas, que ahí va "Bombom"»).
        mensaje = con_comillas(mensaje, nuevo.grabado)
        final = con_comillas(final, nuevo.grabado)
        # La cuenta salió porque ella quiso pagar: primero los datos y DESPUÉS lo
        # que falta (si una reescritura lo dejó arriba, se baja).
        if faltaba_al_pagar and mensaje and not final and "?" in mensaje:
            mensaje, final = "¡Claro! 💓 Te dejo los datos 👇", mensaje

        # La presentación ya termina preguntando por la talla (va de pie del
        # álbum). Si el modelo la repite abajo, la clienta la lee dos veces.
        if pregunta_en_el_pie:
            final = ""

        # Primer mensaje que ya traía su pedido (lo leyó el modelo, ver
        # `trae_datos_del_pedido`): la bienvenida de Lía va igual, arriba.
        if (
            borrador.turnos == 0
            and nuevo.mostrado_en.get(AccionAsesora.MOSTRAR_PRECIOS.value) == nuevo.turnos
            and "lia accesorios" not in mensaje.lower()
        ):
            resto = re.sub(
                r"^(?:\s*¡?\s*(?:hola|buenas(?:\s+(?:noches|tardes|d[ií]as))?"
                r"|buen\s+d[ií]a|buenos\s+d[ií]as)\s*[!,.]*)+\s*",
                "",
                mensaje,
                flags=re.I,
            )
            mensaje = saludo_de_apertura(datetime.now(COLOMBIA).hour) + (
                f"\n{resto[0].upper()}{resto[1:]}"
                if any(c.isalnum() for c in resto)
                else ""
            )

        # Lo deja para después y todavía falta diseñar: UNA vez, con cariño, se le
        # ofrece dejar el anillo listo (Camilo, 13/10). Va en lugar del cierre.
        oferta = ofrecer_dejarlo_listo(nuevo, texto or "")
        if oferta and fichas.vacia and cabecera.vacia:
            mensaje, final = oferta, ""
            nuevo.mostrado_en[OFRECE_DEJARLO_LISTO] = nuevo.turnos
        # Ya está todo menos la talla y no la tiene a mano: UNA vez, separarlo con
        # el abono y mandar la talla después (Camilo, 13/10: «la talla no debe
        # frenar»).
        separar = ofrecer_separar(nuevo, formatear_cop(self._hechos.anticipo))
        if not oferta and separar and fichas.vacia and cabecera.vacia:
            # Sin talla, «apenas Lía confirme la talla te comparto el resumen»
            # no es verdad: el resumen sale si decide separarlo.
            mensaje = _PROMETE_EL_RESUMEN.sub("", sin_preguntas_de_mas(mensaje)).strip()
            final = separar
            nuevo.mostrado_en[OFRECE_SEPARAR] = nuevo.turnos

        # El resumen salió en ESTE turno: prometer mandarlo contradice lo que ella
        # acaba de ver (13/10, charla de prueba: el resumen y debajo «En unos
        # minutos te comparto el resumen de tu anillo…»).
        if resumen_mostrado:
            mensaje = _PROMETE_EL_RESUMEN.sub("", mensaje).strip()
            final = _PROMETE_EL_RESUMEN.sub("", final).strip()

        # Cuándo paga el envío, si cambió en este turno: lo escribe Python.
        acordado = self._envio_acordado(
            borrador, nuevo, pedido, f"{mensaje}\n{final}", notas
        )

        # 4. Armar: resumen, mensaje, fichas/cuentas, cierre.
        respuesta.piezas.extend(cabecera.piezas)
        respuesta.decir(mensaje)
        respuesta.piezas.extend(fichas.piezas)
        respuesta.decir(final)
        respuesta.decir(acordado)

        # Su nombre no se pregunta a ciegas: se le propone el que ya tenemos.
        self._lo_del_nombre(
            nuevo,
            respuesta,
            nombre_de_whatsapp,
            notas,
            rechazos,
            # ¿El pago era de ANTES de este turno? Ver `_lo_del_nombre`.
            pago_previo=(
                borrador.abono_reportado
                or borrador.saldo_reportado
                or borrador.pagado_sin_pedido
            ),
        )

        # Un mensaje sin ninguna pregunta deja la venta parada: ella no sabe si
        # tiene que contestar ni qué (20/09: le llegó el resumen del pedido y
        # debajo «¡Perfecto Camilo! 🫶», y ahí se acabó). Quien vende termina
        # preguntando — salvo cuando de verdad toca esperar a alguien.
        # Las cuentas salieron EN ESTE turno: debajo, una vez, «Quedo atenta…»
        # (sin pregunta). En los turnos siguientes, mientras paga, nada.
        cuentas_ahora = nuevo.turnos in (
            nuevo.mostrado_en.get("MANDAR_CUENTAS"),
            nuevo.mostrado_en.get("PEDIR_ABONO"),
        )
        cierre = self._mensaje_seguro(nuevo, estado)
        if (
            cuentas_ahora
            and not faltaba_al_pagar
            and cierre in (QUEDO_ATENTA, QUEDO_ATENTA_SALDO)
            and "atenta" not in respuesta.texto_plano.lower()
        ):
            respuesta.decir(cierre)
        # Si solo agradece, la pregunta de relleno del sistema tampoco va (13/10,
        # auditoría: «Gracias por la información» -> «¡Con gusto! 🥰» y debajo
        # «¿De cuántas huellitas lo quieres?»). La que haga el modelo, sí.
        if (
            not respuesta.vacia
            and not callar
            and not solo_agradece(texto or "")
            and not se_despide(respuesta.texto_plano)
            and not teme_abonar(texto or "")
            and self._le_falta_la_pregunta(respuesta, nuevo, estado, cabecera)
        ):
            pregunta = (
                CONFIRMA_EL_RESUMEN
                if resumen_mostrado
                # Acaba de ver la cadena: no se le pregunta por el anillo.
                else PREGUNTA_DE_LA_CADENA
                if nuevo.mostrado_en.get(AccionAsesora.MOSTRAR_CADENA.value)
                == nuevo.turnos
                # Ni por las huellitas si acaba de ver el anillo de corazón.
                else PREGUNTA_DEL_CORAZON
                if nuevo.mostrado_en.get(AccionAsesora.MOSTRAR_CORAZON.value)
                == nuevo.turnos
                and not nuevo.es_corazon
                else self._lo_que_falta(nuevo, estado)
            )

            # Pero la pregunta de relleno es una frase FIJA, y ponerla turno
            # tras turno es peor que callarse: en un repaso salió la misma
            # línea en nueve conversaciones seguidas. Si ya se la hicimos, se
            # deja el mensaje como está.
            # `repite_lo_dicho` no mira frases de menos de 20 caracteres,
            # y «¿Así está bien? 🥰» es una de ellas: se compara también tal cual.
            # Tal cual, en TODA la charla (09/10): la pregunta fija de la talla de
            # la apertura volvía a salir igualita diez mensajes después.
            todo_lo_dicho = [
                m.get("texto", "") for m in ctx.charla if m.get("de") == "lia"
            ]

            def _ya_dicha(frase: str) -> bool:
                return bool(repite_lo_dicho(frase, dichos)) or any(
                    frase in (d or "") for d in todo_lo_dicho
                )

            if (
                pregunta is not None
                and _ya_dicha(pregunta)
                and pregunta.startswith("¿")
                and len(pregunta) > 2
            ):
                # Igualita ya se dijo: con otras palabras, no callada (12/10:
                # pagó a medias y no se le volvió a preguntar lo que faltaba).
                resto = f"¿{pregunta[1].lower()}{pregunta[2:]}"
                pagado = nuevo.pagado_sin_pedido or nuevo.abono_reportado
                otra = (
                    f"Para pasar tu pedido al taller, {resto}"
                    if pagado
                    else f"Y cuéntame, {resto}"
                )
                if not _ya_dicha(otra):
                    pregunta = otra
            ya_dicha = pregunta is None or _ya_dicha(pregunta)
            if ya_dicha:
                rechazos.append("no preguntaba nada, pero la pregunta ya se la hicimos")
            else:
                respuesta.decir(pregunta)
                rechazos.append("no preguntaba nada: se le puso la pregunta que faltaba")

        if respuesta.vacia:
            # Un turno mudo deja la conversación parada esperando a que ella
            # adivine el siguiente paso (20/09: mandó «Roberto», que ya estaba
            # anotado, y el bot contestó «¡Listo! 🙌» y nada más). Lía siempre
            # pregunta lo que falta.
            respuesta.decir(self._lo_que_falta(nuevo, estado))
            rechazos.append("el mensaje quedó vacío tras vigilarlo")
        if jugada.nota_para_lia:
            notas.append(jugada.nota_para_lia)
        # Varios anillos: el que iba quedó completo y faltan otros. Se guarda y
        # el turno siguiente ya es del próximo, vacío. Va al FINAL del turno:
        # la foto de cómo queda y el resumen de este turno son del que terminó.
        nuevo.desenfocar()
        if nuevo.pedido_id is None and nuevo.pasar_al_siguiente():
            rechazos.append(
                f"el anillo {nuevo.numero_del_anillo - 1} quedó completo: ahora se "
                f"describe el anillo {nuevo.numero_del_anillo} de {nuevo.anillos_total}"
            )

        # Lo que se le pidió en este mensaje y todavía le falta, cuenta (a la
        # segunda vez sin darlo, se deja al recordatorio).
        if not nuevo.pedido_id:
            contar_lo_pedido(nuevo, respuesta.texto_plano)
        # Sin recordatorios para quien no le interesa (lo dijo ella, o la IA lo
        # entendió así); vuelven si ella retoma el pedido (10/10).
        if desinteres or el_bot_entendio_que_no(respuesta.texto_plano):
            nuevo.sin_recordatorios = True
        elif nuevo.sin_recordatorios and (
            quiere_comprar(texto or "") or cambio_anotado(borrador, nuevo)
        ):
            nuevo.sin_recordatorios = False
        nuevo.avisos = rechazos
        charla = list(ctx.charla)
        charla.append({"de": "clienta", "texto": _para_charla(texto, descripciones)})
        charla.append({"de": "lia", "texto": _para_memoria(respuesta.texto_plano)})
        ctx = ctx.model_copy(
            update={
                "borrador": nuevo.model_dump(mode="json"),
                "charla": charla[-CHARLA_MAXIMA:],
            }
        )
        for nota in notas + [n for n in nuevo.notas if n not in borrador.notas]:
            ctx = ctx.anotar_revision(nota)
        self._mundo.guardar_contexto(ctx)

        respuesta.traza.append(
            f"asesora {capa} {jugada.confianza.value}: {jugada.lectura}"
        )
        for r in rechazos:
            respuesta.traza.append(f"  no pasó: {r}")
            log.info("  no pasó: %s", r)

        turno.jugada, turno.capa = jugada, capa
        turno.contexto, turno.respuesta = ctx, respuesta
        turno.transcripciones = [
            d for d in descripciones if d.startswith("una nota de voz en la que dice")
        ]
        # El registro genérico no sabe de jugadas: sin esto `vb metricas` contaría
        # cada turno de la asesora como «sistema» y las escaladas no se verían.
        turno.registro = replace(
            registro_del_turno(turno, ms=int((time.perf_counter() - inicio) * 1000)),
            routing_layer=capa,
            motivo="asesora",
            escalated=capa == "potente",
            escalation_reason="confianza_baja" if capa == "potente" else "",
            action=",".join(a.value for a in acciones) or "CONVERSAR",
            confidence=jugada.confianza.value,
            human_review=respuesta.escalar,
            corrected=bool(rechazos),
        )
        log.info("  %s", turno.resumen())
        return turno

    def calentar(self) -> None:
        """Una jugada de arranque para que la primera clienta no pague la espera.

        La primera llamada con un esquema nuevo compila la gramática de `Jugada`
        en el proveedor y escribe la caché del prompt. Medido el 20/09 al
        cambiar un campo: 62 s la primera y 2 s todas las demás.

        Por eso esta llamada va SIN el tope de las clientas (`calentando=True`).
        Con el tope de 10 s se rendía antes de que compilara, la gramática no se
        guardaba nunca, y todas las llamadas siguientes fallaban igual: el bot
        entero inservible por haber tocado un campo.

        Nunca falla hacia arriba: sin red, la primera clienta espera como antes.
        """
        if self._llm is None:
            return
        try:
            with consumo.capa("calentar_basico"):
                self._llm.extract(
                    self._system,
                    "# ÚLTIMO MENSAJE DE LA CLIENTA\nhola",
                    Jugada,
                    calentando=True,
                )
        except Exception as exc:
            log.warning("no se pudo calentar la asesora (%s)", type(exc).__name__)
        # Solo el básico. El fuerte (Sonnet) contesta pocas veces y calentarlo era
        # la mayor parte del costo de cada arranque (19/09): esos pocos turnos
        # pagan 8 s una vez, en vez de pagarlo todos los arranques. Mismo
        # criterio que el respaldo, que tampoco se calienta.

    # -- el modelo ---------------------------------------------------------

    def _jugar(self, entrada: str, fotos: list[bytes]) -> tuple[Jugada | None, str]:
        # Cada llamada queda apuntada con su capa (`consumo`): sin esto el
        # registro de decisiones decía «?» y `vb metricas` no distinguía el
        # básico del potente (visto el 29/09 en 73 turnos reales).
        jugada = None
        try:
            with consumo.capa("basico"):
                jugada = self._llm.extract(
                    self._system, entrada, Jugada, images=fotos or None
                )
            capa = "basico"
        except Exception as exc:
            log.warning("la asesora no respondió (%s)", exc)
            capa = "fallo"
        necesita_fuerte = jugada is None or jugada.confianza is Confianza.BAJA
        if necesita_fuerte and self._fuerte is not None:
            try:
                with consumo.capa("fuerte"):
                    jugada = self._fuerte.extract(
                        self._system, entrada, Jugada, images=fotos or None
                    )
                capa = "potente"
            except Exception as exc:
                log.warning("el modelo potente tampoco respondió (%s)", exc)
        return jugada, capa

    def _reescribir(
        self,
        texto,
        descripciones,
        jugada,
        motivo,
        b: Borrador,
        montos,
        dichos,
        *,
        con_opciones: bool,
        estado: str = "",
    ) -> str | None:
        """Otro mensaje para el mismo turno. None si tampoco sirve.

        Solo cambia el TEXTO: el pedido y las acciones de la jugada ya quedaron.
        """
        clienta = texto or ""
        if descripciones:
            clienta += " [" + "; ".join(descripciones) + "]"
        entrada = "\n".join(
            [
                "REESCRIBE SOLO TU MENSAJE de este turno (el pedido y las acciones ya "
                "quedaron hechos; no cambian).",
                f"Por qué no se pudo mandar: {motivo}.",
                "Estado real del pedido: "
                + (b.pedido_codigo or "sin crear")
                + f" ({estado or 'sin pedido'}); abono reportado: "
                + ("sí" if b.abono_reportado else "no")
                + "; cuentas enviadas: "
                + ("sí" if b.cuentas_enviadas else "no")
                + "; falta para el abono: "
                + (", ".join(b.falta_para_abono()) or "nada")
                + "; el envío se paga: "
                + (
                    "JUNTO CON EL SALDO, cuando el anillo esté listo (nunca con el abono)"
                    if b.envio_con_saldo
                    else "al recibir"
                ),
                "Montos que sí puedes escribir: "
                + (", ".join(formatear_cop(m) for m in sorted(montos)) or "ninguno"),
                "Tus últimos mensajes: " + " || ".join(d[:300] for d in dichos),
                f"Último mensaje de la clienta: {clienta}",
                f"Tu mensaje que no se mandó: {jugada.mensaje} {jugada.mensaje_final}",
                "Escribe un mensaje corto y cálido, como Lía, que responda a lo que ella "
                "acaba de decir (reconoce lo concreto: un nombre, un dibujo, su ciudad) "
                "sin repetir frases de tus últimos mensajes y sin afirmar nada falso.",
            ]
        )
        try:
            with consumo.capa("reescribir"):
                r = self._llm.extract(self._system, entrada, MensajeReescrito)
        except Exception as exc:
            log.warning("no se pudo reescribir el mensaje (%s)", exc)
            return None
        limpio, problemas = vigilar(
            getattr(r, "mensaje", ""),
            montos,
            b,
            estado,
            self._hechos.promociones_de_hoy(),
        )
        if not limpio or any(p.startswith(PROBLEMAS_GRAVES) for p in problemas):
            return None
        if (
            habla_de_cadena(limpio)
            and not pregunta_por_cadenas(texto)
            and AccionAsesora.MOSTRAR_CADENA.value not in b.mostrado_en
            and not any(v.es_cadena for v in b.vistas())
        ):
            return None  # la cadena nunca se ofrece (03/10)
        if con_opciones and not pregunto_cantidad_con_opciones(limpio):
            return None
        return limpio

    def _si_falla_la_ia(
        self, conv, texto, media, turno, ctx, pendiente=None, reintento=False
    ) -> Turno:
        """Ninguna IA contestó (caídas, sin saldo, sin red): no se pierde nada.

        29/09: Anthropic devolvió 503, la clienta recibió «dame un momentico» y
        ese momentico nunca llegó: su «Sí» al resumen se perdió. Ahora:

          · lo que escribió queda PENDIENTE en el contexto, y el contenedor lo
            reintenta en segundo plano hasta que alguna IA vuelva; entonces le
            contesta todo y quita la alerta;
          · la frase amable y el aviso a Camilo (celular y Chatwoot) salen UNA
            vez por caída, no en cada mensaje ni en cada reintento;
          · NO pasa a manos de una persona: el bot retoma solo. Solo se calla si
            alguien la toma a mano (escribe o la asigna en Chatwoot).
        """
        if self._respaldo is not None:
            log.warning("turno contestado por el gestor de respaldo")
            return self._respaldo.ejecutar(conv, texto, media)
        from datetime import UTC, timedelta

        ahora = datetime.now(UTC)
        intentos = int((pendiente or {}).get("intentos") or 0) + 1
        espera = min(60 * 2 ** (intentos - 1), 300)
        nuevo_pendiente = {
            "texto": texto or "",
            "media": list(media or []),
            "desde": (pendiente or {}).get("desde")
            or ahora.isoformat(timespec="seconds"),
            "intentos": intentos,
            "proximo": (ahora + timedelta(seconds=espera)).isoformat(timespec="seconds"),
        }
        ctx = ctx.model_copy(update={"pendiente_ia": nuevo_pendiente})
        primera_vez = pendiente is None and not reintento
        if primera_vez:
            ctx = ctx.anotar_revision(
                "La IA no respondió: el bot lo reintenta solo y le contesta cuando "
                "vuelva. Si quieres contestar tú, escríbele (el bot se calla)."
            )
        self._mundo.guardar_contexto(ctx)
        respuesta = Respuesta()
        turno.contexto, turno.respuesta, turno.capa = ctx, respuesta, "sin_modelo"
        if not primera_vez:
            log.warning("la IA sigue sin responder en %s (intento %s)", conv, intentos)
            return turno
        log.error("la IA no respondió en %s: queda pendiente y se reintenta", conv)
        # «Escalar» aquí es la alerta en Chatwoot (necesita-persona); el bot NO
        # se calla: la quita él mismo cuando vuelve la IA y le contesta.
        respuesta.pedir_humano(MOMENTICO)
        if self._avisar is not None:
            try:
                self._avisar(
                    "La IA no respondió",
                    "Una clienta quedó esperando. El bot lo reintenta solo y le "
                    "contesta apenas vuelva la IA; si quieres, escríbele tú.",
                    "ia-no-responde",
                )
            except Exception as exc:  # pragma: no cover - avisar nunca tumba el turno
                log.warning("no se pudo avisar (%s)", exc)
        return turno

    # -- la entrada que lee el modelo --------------------------------------

    def _entrada(
        self, b: Borrador, pedido, charla, texto, descripciones, notas_internas=()
    ) -> str:
        falta = b.falta_para_abono()
        estado = pedido.estado if pedido is not None else ""
        if pedido is not None:
            pendiente = max(0, pedido.saldo_cop - pedido.saldo_pagado_cop)
            en_palabras = ESTADO_EN_PALABRAS.get(estado, estado)
            if estado == "EN_REVISION_PAGO" and pedido.anticipo_pagado_cop:
                en_palabras = "mandó el comprobante del SALDO y Lía lo está verificando"
            linea_pedido = (
                f"Pedido creado: {b.pedido_codigo}. Dónde va: {en_palabras}. "
                f"Total {formatear_cop(pedido.total_cop)} · abono "
                f"{formatear_cop(pedido.anticipo_cop)} · saldo por pagar "
                f"{formatear_cop(pendiente)}"
            )
        else:
            linea_pedido = "Pedido creado: todavía no (nace cuando esté al 100 % y pague)"
        envio = self._mundo.envio_a(b.ciudad or None)
        datos = b.model_dump(
            mode="json",
            exclude={
                "avisos",
                "notas",
                "mostrado_en",
                "pedido_id",
                "cuentas_enviadas",
                "ultimo_resumen",
                "turnos",
                "cantidad_en_duda",
                # Es para Lía («confírmala desde el panel»): al modelo lo confunde.
                "talla_motivo",
                "talla_fotos",
                "talla_exige_lia",
                # Los otros anillos van en palabras (`_linea_de_anillos`).
                "anillos",
                "por_empezar",
                # Van en palabras abajo («NO LE PIDAS…»).
                "lo_manda_despues",
                "recordado_despues",
                "veces_pedido",
            },
        )
        # Solo lo que de verdad le falta (lo ya anotado ni se nombra).
        no_pedir = sorted(que_no_se_pide(b) & lo_que_le_falta(b))
        linea_no_pedir = (
            [
                "NO LE PIDAS AHORA (ni con pregunta ni con «mándame», «cuando puedas»): "
                + ", ".join(
                    f"{q} (dijo que lo manda después)"
                    if q in b.lo_manda_despues
                    else f"{q} (ya se lo pediste dos veces; lo retoma el recordatorio)"
                    for q in no_pedir
                )
                + ". Sigue con lo demás; si ella vuelve a hablar de eso, contéstale."
            ]
            if no_pedir
            else []
        )
        mostrado = ", ".join(
            f"{a} (turno {n})"
            for a, n in sorted(b.mostrado_en.items(), key=lambda x: x[1])
        )
        partes = [
            "# ESTADO DEL PEDIDO",
            *self._linea_de_la_cadena(b, texto, charla),
            *(
                [
                    "LA PIEZA QUE SE DESCRIBE AHORA ES EL ANILLO DE CORAZÓN: no "
                    "preguntes cuántas huellitas ni por deditos; pregunta su talla, "
                    "el color del corazón y el nombre (o los nombres) que van por "
                    "dentro."
                ]
                if b.es_corazon
                else []
            ),
            *self._linea_de_anillos(b),
            "Borrador: " + json.dumps(datos, ensure_ascii=False),
            "Falta para tomar el pedido (antes del abono): "
            + (", ".join(falta) if falta else "NADA (ya se puede resumir y pedir abono)"),
            *linea_no_pedir,
            *(
                [
                    "LO SEPARA SIN TALLA (13/10): el abono NO espera la talla. No se "
                    "la pidas antes de pagar; cuando pague, dile con cariño que su "
                    "anillo entra al taller apenas nos mande la talla."
                ]
                if b.talla_despues and b.talla is None
                else []
            ),
            "Falta para poder entregarlo (se pide AL FINAL, con las fotos del "
            "anillo terminado; NO lo preguntes antes): "
            + (", ".join(b.falta_para_despachar()) or "nada"),
            linea_pedido,
            "Abono reportado por la clienta: "
            + (
                "sí (lo verifica Lía; NO se pide otra vez)" if b.abono_reportado else "no"
            ),
            "Saldo reportado por la clienta: "
            + ("sí (lo verifica Lía)" if b.saldo_reportado else "no"),
            "Cuentas para el abono ya enviadas: "
            + ("sí" if b.cuentas_enviadas else "NO"),
            f"Turno actual: {b.turnos + 1}. Ya se le mostró: " + (mostrado or "nada"),
            f"Envío a {b.ciudad or 'ciudad aún no dicha'}: {formatear_cop(envio)}. "
            + (
                "Lo lleva a recoger: no paga envío."
                if b.recoge
                else "ELLA PIDIÓ PAGARLO ANTES: lo paga JUNTO CON EL SALDO cuando "
                "el anillo esté listo (nunca con el abono)."
                if b.envio_con_saldo
                else "Se paga al recibir (lo normal)."
            ),
            (
                f"Precio de la CADENA: {formatear_cop(self._hechos.precio_cadena)} · "
                f"abono {formatear_cop(self._hechos.anticipo_cadena)} · saldo "
                + formatear_cop(self._hechos.precio_cadena - self._hechos.anticipo_cadena)
                if b.es_cadena
                else f"Precio del ANILLO DE CORAZÓN: "
                f"{formatear_cop(self._hechos.precio_corazon)} · abono "
                f"{formatear_cop(self._hechos.anticipo_corazon)} · saldo "
                + formatear_cop(
                    self._hechos.precio_corazon - self._hechos.anticipo_corazon
                )
                if b.es_corazon
                else f"Precio del anillo de {b.cantidad}: "
                f"{formatear_cop(self._hechos.precios.get(b.cantidad, 0))} · abono "
                f"{formatear_cop(self._hechos.anticipo)} · saldo "
                + formatear_cop(
                    self._hechos.precios.get(b.cantidad, 0) - self._hechos.anticipo
                )
                if b.cantidad in self._hechos.precios
                else "Precio: depende de cuántas huellitas (aún no se sabe)"
            ),
            *self._plata_de_varios(b),
            linea_del_estado(self._hechos.promociones_de_hoy()),
            "",
            "# AVISOS DEL SISTEMA DEL TURNO ANTERIOR",
            "\n".join(f"- {a}" for a in b.avisos) or "- ninguno",
            "",
            # Lo que Lía anotó desde el panel (27/09). Es contexto: NO lo escribió
            # la clienta, ella NO lo ve, y no se le cita ni se le repite. Si dice
            # «talla confirmada», esa es la talla.
            "# NOTAS INTERNAS DE LIA (privadas: la clienta no las ve ni las escribió)",
            "\n".join(
                f"- [{str(n.get('cuando', ''))[:10]} · {n.get('tipo', '')}"
                + (f" · {n['pedido']}" if n.get("pedido") else "")
                + f"] {n.get('texto', '')}"
                for n in list(notas_internas)[-NOTAS_INTERNAS_AL_MODELO:]
            )
            or "- ninguna",
            "",
            "# CONVERSACIÓN RECIENTE",
            "\n".join(
                ("Clienta" if m.get("de") == "clienta" else "Lía")
                + f": {m.get('texto', '')}"
                for m in charla[-CHARLA_MAXIMA:]
            )
            or "(es el primer mensaje)",
            "",
            "# ÚLTIMO MENSAJE DE LA CLIENTA",
            (texto or "").strip() or "(sin texto)",
        ]
        for d in descripciones:
            partes.append(f"[La clienta envió {d}]")
        return "\n".join(partes)

    def _oir(self, adjunto: dict) -> str | None:
        """El texto de una nota de voz. None si no hay oídos o si falla.

        Nunca levanta: perder la transcripción es quedarse como antes; que
        reviente el turno es perder la venta.
        """
        if self._oidos is None or self._descargar is None:
            return None
        try:
            datos = self._descargar(adjunto)
            if not datos:
                return None
            return self._oidos.transcribir(datos, adjunto.get("mime_type") or "")
        except Exception as exc:
            log.warning("no se pudo oír la nota de voz (%s)", exc)
            return None

    def _apertura(self, conversation_id, ctx, borrador, media, texto=None):
        """La presentación del primer mensaje, sin pasar por el modelo.

        ════════════════════════════════════════════════════════════════════
        POR QUÉ NO SE LE PREGUNTA AL MODELO
        ════════════════════════════════════════════════════════════════════
        En las siete conversaciones reales de Lía, el primer mensaje SIEMPRE
        recibe lo mismo: el saludo, la ficha del producto, la foto, los videos
        y «¿Sabes tu talla de anillo o te comparto la guía?». Da igual que la
        clienta escriba «hola», «precios?», «quiero hacer un pedido» o «vi tu
        anuncio en Instagram»: la respuesta no cambia.

        Pagarle a un modelo por elegir entre una sola opción es pagar por una
        decisión que ya está tomada. Y encima cuesta 2-4 segundos justo en el
        primer mensaje, que es donde la clienta decide si esto va en serio.

        Solo se hace cuando la conversación está DE VERDAD en blanco: sin
        historia, sin nada escogido y sin pedido. Si manda una foto de entrada,
        eso sí va al modelo — puede ser la huella de su mascota.
        """
        if ctx.charla or borrador.turnos or borrador.pedido_id or media:
            return None
        if any(h.completa for h in borrador.huellitas) or borrador.cantidad:
            return None
        # Una queja de entrada tampoco: ahí la ficha con precios es lo peor que
        # se le puede mandar. En el repaso del 21/09, a «ustedes son unos
        # estafadores de mierda, devuélvanme la plata» le llegó «¡Hola! Buen día
        # 🌞 Bienvenida…» con el catálogo, y a Lía no le avisó nadie. Suele ser
        # alguien que ya compró escribiendo desde otro número: lo lee el modelo,
        # que puede pasársela a Lía.
        if texto and _QUEJA_DE_ENTRADA.search(texto):
            return None
        # Si de entrada pregunta por la cadena (o escribe desde la cadena del
        # catálogo de WhatsApp), la ficha del anillo no le contesta nada: lo lee
        # el modelo, que le muestra la cadena (R2p). Pasó en el ensayo del 03/10.
        if texto and pregunta_por_cadenas(texto):
            return None
        # Lo mismo si viene por el anillo de corazón (17/10): le contesta el
        # modelo, con la presentación del corazón y no la de la huellita.
        if texto and habla_del_corazon(texto):
            return None
        # Si de entrada ya trae su pedido («quiero uno de una huellita talla 6,
        # todo rosado, que diga Lola»), lo lee el modelo: la presentación va
        # igual, pero lo que dijo queda anotado. Con la apertura fija se perdía y
        # después le preguntaban la talla y las huellitas (prueba del 13/10).
        if texto and trae_datos_del_pedido(texto):
            return None
        # Si cuenta algo suyo (un regalo, un duelo, una pregunta), la lee la IA
        # (17/10): la apertura fija es solo para el saludo y el texto del anuncio.
        if texto and not es_un_arranque_de_cajon(texto):
            return None

        turno = TurnoDeAsesora(conversation_id=conversation_id, texto=texto)
        respuesta = Respuesta()
        respuesta.decir(saludo_de_apertura(datetime.now(COLOMBIA).hour))
        nuevo = borrador.model_copy(deep=True)
        nuevo.turnos = 1
        if self._apertura_peludito and not _PREGUNTA_EL_PRECIO.search(
            _plano_simple(texto or "")
        ):
            # La prueba del 13/10 (marketing: el 67 % deja de escribir apenas
            # recibe los precios): primero su peludito, con la foto de un anillo
            # grabado; la presentación va en su segundo mensaje.
            respuesta.mostrar(FOTO_DEL_PELUDITO, pie=APERTURA_DEL_PELUDITO)
            nuevo.mostrado_en[APERTURA_PELUDITO] = 1
        else:
            nuevo.mostrado_en[AccionAsesora.MOSTRAR_PRECIOS.value] = 1
            self._presentacion(respuesta)

        # Se guarda lo que ESCRIBIÓ, no un relleno. La respuesta no depende de
        # su primer mensaje, pero los turnos siguientes sí: abrió con «quiero
        # el de 3 huellitas» y en el turno siguiente se lo volvían a preguntar,
        # porque en la memoria decía «(su primer mensaje)» (20/09). No
        # contestarle no es lo mismo que no haberla oído.
        charla = [
            {"de": "clienta", "texto": _para_memoria(texto or "(escribió sin texto)")},
            {"de": "lia", "texto": _para_memoria(respuesta.texto_plano)},
        ]
        ctx = ctx.model_copy(
            update={"borrador": nuevo.model_dump(mode="json"), "charla": charla}
        )
        self._mundo.guardar_contexto(ctx)

        turno.respuesta = respuesta
        turno.contexto = ctx
        turno.capa = "apertura"
        respuesta.anotar("apertura fija: sin llamar al modelo")
        log.info("apertura sin modelo (0 tokens)")
        return turno

    def _respuesta_fija(self, conversation_id, ctx, borrador, texto, media):
        """Lo que se contesta igual siempre, sin gastar una llamada.

        Hoy solo una: «no sé mi talla / mándame la guía» justo después de que
        nosotros preguntáramos por la talla. Es el segundo turno de casi toda
        conversación, así que se ahorra una llamada por clienta — y sobre todo
        contesta al instante, que ahí es donde se nota.

        La condición es estrecha a propósito (ver `pide_la_guia_de_la_talla`):
        ante cualquier duda, al modelo.
        """
        if media:
            return None
        ultimo_de_lia = next(
            (m.get("texto", "") for m in reversed(ctx.charla) if m.get("de") == "lia"), ""
        )
        respuesta = Respuesta()
        nuevo = borrador.model_copy(deep=True)
        nuevo.turnos += 1
        dicho = (texto or "").strip()
        if solo_pregunta_por_el_metal(dicho):
            # «Solo en plata? No hay dorado?» (05/10): la regla, y se vuelve a
            # la pregunta que estaba abierta.
            respuesta.decir(SOLO_EN_PLATA)
            falta = [] if borrador.pedido_id else borrador.falta_para_abono()
            abierta = pregunta_abierta(ultimo_de_lia) or (
                COMO_SE_PREGUNTA.get(falta[0], "") if falta else ""
            )
            if abierta.startswith("¿") and len(abierta) > 2:
                # Igualita, palabra por palabra, suena a robot: «Y cuéntame, ¿sabes…».
                abierta = f"Y cuéntame, ¿{abierta[1].lower()}{abierta[2:]}"
            if abierta:
                respuesta.decir(abierta)
            nuevo.mostrado_en[PLATA] = nuevo.turnos
            que = "solo en plata"
        elif len(dicho) <= 120 and pregunta_por_la_ubicacion(dicho):
            # «¿Dónde están ubicados?» (09/10): Floridablanca, sin punto físico,
            # el conjunto para recoger (nunca torre ni apartamento), y se vuelve
            # a la pregunta que estaba abierta.
            respuesta.decir(UBICACION)
            falta = [] if borrador.pedido_id else borrador.falta_para_abono()
            abierta = pregunta_abierta(ultimo_de_lia) or (
                COMO_SE_PREGUNTA.get(falta[0], "") if falta else ""
            )
            if abierta.startswith("¿") and len(abierta) > 2:
                abierta = f"Y cuéntame, ¿{abierta[1].lower()}{abierta[2:]}"
            if abierta:
                respuesta.decir(abierta)
            nuevo.mostrado_en[UBICADOS] = nuevo.turnos
            que = "dónde estamos"
        elif borrador.talla is not None:
            return None
        elif (
            not borrador.es_cadena
            and not borrador.pedido_id
            and len(dicho) <= 120
            and not _TRAE_NUMERO.search(dicho)
            and no_tiene_anillos(dicho, ultimo_de_lia)
        ):
            # «Es que no tengo anillos 🫣»: el dedo con papel o hilo, y el video
            # (Camilo, 13/10; antes, la joyería).
            respuesta.decir(TALLA_SIN_ANILLOS)
            respuesta.reproducir(VIDEO_DEL_DEDO, pie=PIE_DEL_VIDEO_DEL_DEDO)
            siguiente = next(
                (
                    f
                    for f in nuevo.falta_para_abono()
                    if f in COMO_SE_PREGUNTA and f != "talla"
                ),
                None,
            )
            if siguiente in ("cantidad de huellitas", "colores", "grabado"):
                respuesta.decir(f"{MIENTRAS_TANTO} {COMO_SE_PREGUNTA[siguiente]}")
            nuevo.mostrado_en[SIN_ANILLOS] = nuevo.turnos
            # Se va a medir: la talla la trae ella después. No se le pide más
            # en la charla (09/10).
            nuevo.lo_manda_despues.setdefault("talla", nuevo.turnos)
            que = "cómo medirse sin anillo"
        elif pide_la_guia_de_la_talla(texto, ultimo_de_lia):
            dicho_por_ella = " ".join(
                [texto or ""]
                + [m.get("texto", "") for m in ctx.charla if m.get("de") == "clienta"]
            )
            respuesta.decir(
                GUIA_PARA_REGALO
                if es_para_otra_persona(dicho_por_ella)
                else "¡Dale! Te la comparto 📏"
            )
            respuesta.decir(GUIA_TALLA)
            respuesta.mostrar("medir_talla_guia")
            nuevo.mostrado_en[AccionAsesora.MOSTRAR_GUIA_TALLA.value] = nuevo.turnos
            que = "la guía de la talla"
        else:
            return None

        turno = TurnoDeAsesora(conversation_id=conversation_id, texto=texto)

        charla = list(ctx.charla)
        charla.append({"de": "clienta", "texto": texto or ""})
        charla.append({"de": "lia", "texto": _para_memoria(respuesta.texto_plano)})
        ctx = ctx.model_copy(
            update={
                "borrador": nuevo.model_dump(mode="json"),
                "charla": charla[-CHARLA_MAXIMA:],
            }
        )
        self._mundo.guardar_contexto(ctx)
        turno.respuesta = respuesta
        turno.contexto = ctx
        turno.capa = "fija"
        respuesta.anotar(f"respuesta fija: {que}, sin llamar al modelo")
        log.info("%s sin modelo (0 tokens)", que)
        return turno

    def _presentacion(
        self, respuesta: Respuesta, *, preguntar_talla: bool = True, regalo: bool = False
    ) -> None:
        """La ficha, los dos videos y la foto con la pregunta de pie.

        Lo mismo que manda Lía de primeras, y lo que hace que alguien pregunte
        el precio y no se vaya. La pregunta va de PIE del último medio para que
        WhatsApp lo junte todo en un álbum.

        `preguntar_talla=False` cuando ya la sabemos. El 20/09 una clienta
        mandó la foto de la regla como primer mensaje y el bot le contestó «¡Es
        una talla 6.5!» y, tres mensajes después, «¿Sabes tu talla de anillo o
        te comparto la guía?». Lía no le preguntaría eso a quien le acaba de
        mandar la medida.
        """
        respuesta.decir(self._hechos.ficha())
        respuesta.reproducir("presentacion_video_1")
        respuesta.reproducir("presentacion_video_2")
        pregunta = PREGUNTA_DE_LA_TALLA_REGALO if regalo else PREGUNTA_DE_LA_TALLA
        respuesta.mostrar("presentacion_anillo", pie=pregunta if preguntar_talla else "")

    def _talla_para_lia(
        self, conv, antes: Borrador, nuevo: Borrador, jugada, media, descripciones, notas
    ) -> bool:
        """Regla de Lía (29/09): lo que llegó de la talla, para que ELLA decida.

        La IA sí mira la foto —es la misma llamada, no cuesta más, y hace falta
        para saber si es la regla, un comprobante o la mascota—, pero lo que lee
        es solo una SUGERENCIA para el panel. A la clienta no se le dice ninguna
        talla: se le dice que en unos minutos se la confirman, y se sigue.

        Devuelve True si en este turno llegó una foto de la regla o una medida
        escrita (entonces se le manda `TALLA_EN_REVISION`).
        """
        hay_foto = any((m or {}).get("kind") == "image" for m in media or [])
        cambios = jugada.cambios
        es_de_la_talla = (
            hay_foto
            and not llego_un_comprobante(jugada.lectura, descripciones)
            and (
                cambios.medida_cm is not None
                or cambios.talla is not None
                or bool(_HABLA_DE_TALLA.search(jugada.lectura or ""))
            )
        )
        if es_de_la_talla and self._guardar_foto is not None:
            for datos in self._fotos_del_turno:
                try:
                    nombre = self._guardar_foto(datos)
                except Exception as exc:  # una foto sin guardar no tumba el turno
                    log.warning("no se pudo guardar la foto de la talla (%s)", exc)
                    continue
                if nombre and nombre not in nuevo.talla_fotos:
                    nuevo.talla_fotos.append(nombre)
        if es_de_la_talla:
            nuevo.talla_revisar = True
            nuevo.talla_confirmada = False
            if nuevo.talla is None:
                nuevo.talla_motivo = (
                    "Mandó la foto de la regla y la IA no alcanzó a leer la medida: "
                    "mírala tú"
                )
        llego_algo = es_de_la_talla or (
            nuevo.talla_escrita != antes.talla_escrita and bool(nuevo.talla_escrita)
        )
        if llego_algo and nuevo.talla_por_confirmar:
            if nuevo.talla is not None:
                sugerida = f"la IA sugiere {talla_texto(nuevo.talla)}" + (
                    f" ({nuevo.talla_rango})" if nuevo.talla_rango else ""
                )
            else:
                sugerida = "la IA no pudo leerla"
            if es_de_la_talla:
                que = "la foto de la regla"
            else:
                que = f"la medida «{nuevo.talla_escrita}»"
            notas.append(f"📏 Talla por confirmar: mandó {que}; {sugerida}")
            self._avisar_a_lia(
                "📏 Talla por confirmar",
                f"{conv} mandó {que} ({sugerida}). Confírmala en el panel: "
                "Taller → Tallas por confirmar.",
                f"talla:{conv}:{len(nuevo.talla_fotos)}:{nuevo.talla_escrita}",
            )
        if nuevo.falta_para_abono() == [TALLA_DE_LIA] and (
            antes.falta_para_abono() != [TALLA_DE_LIA]
        ):
            self._avisar_a_lia(
                "✅ Lista para el abono: falta la talla",
                f"{conv} ya escogió todo. Solo falta que confirmes la talla en el "
                "panel para mandarle el resumen y el abono.",
                f"talla-lista:{conv}",
            )
        return llego_algo

    def _datos_de_envio_del_mensaje(self, nuevo: Borrador, cambios, texto) -> list[str]:
        """Red de seguridad (29/09): los datos de la guía que mandó en un bloque.

        El 28/09 mandó ciudad, nombre, cédula, celular y dirección, uno por
        renglón, y la dirección no quedó: la IA no la copió. Python lee el
        bloque y llena lo que la IA NO anotó en este turno; lo que sí anotó,
        manda. Solo cuando ya hay pedido (es cuando se le piden).
        """
        from app.domain.envio import leer_datos_de_envio

        ciudades = getattr(self._mundo, "ciudades_conocidas", lambda: ())()
        leidos = leer_datos_de_envio(texto, ciudades)
        if not leidos:
            return []
        anotados = {
            "ciudad": cambios.ciudad,
            "direccion": cambios.direccion,
            "cedula": cambios.cedula,
            "celular": cambios.celular,
        }
        tomados = []
        for campo, valor in leidos.items():
            if anotados.get(campo):
                continue
            # Si el destinatario es ella misma, no hace falta: va a su nombre.
            if campo == "destinatario" and _sin_tildes(valor.lower()) == _sin_tildes(
                nuevo.nombre_clienta.lower()
            ):
                continue
            if getattr(nuevo, campo, None) != valor:
                setattr(nuevo, campo, valor)
                tomados.append(campo)
        if "direccion" in tomados:
            nuevo.recoge = False
        if not tomados:
            return []
        return [
            "datos de envío leídos del mensaje (la IA no los anotó): "
            + ", ".join(tomados)
        ]

    def _avisar_a_lia(self, titulo: str, detalle: str, clave: str) -> None:
        if self._avisar is None:
            return
        try:
            self._avisar(titulo, detalle, clave)
        except Exception as exc:  # un aviso que no sale no tumba el turno
            log.warning("no se pudo avisar a Lía (%s)", exc)

    def tras_confirmar_talla(self, conv: str) -> Respuesta:
        """Lía confirmó la talla en el panel: el flujo sigue donde iba.

        Si con eso el pedido quedó completo, se le manda el resumen para que
        diga que sí y siga el abono de siempre. Si ya había pagado sin pedido,
        el pedido nace aquí. El aviso de la talla lo manda quien llama.
        """
        ctx = self._mundo.contexto(conv)
        b = Borrador.model_validate(ctx.borrador) if ctx.borrador else Borrador()
        b.talla_exige_lia = self._talla_la_confirma_lia
        respuesta = Respuesta()
        notas: list[str] = []
        rechazos: list[str] = []
        if b.pedido_id is None and not b.falta_para_abono():
            if b.pagado_sin_pedido:
                self._recibir_comprobante(conv, b, respuesta, notas, rechazos)
            elif b.resumen() != b.ultimo_resumen:
                respuesta.decir(b.resumen())
                respuesta.decir(CONFIRMA_EL_RESUMEN)
                b.ultimo_resumen = b.resumen()
                b.mostrado_en[AccionAsesora.MOSTRAR_RESUMEN.value] = b.turnos
        charla = list(ctx.charla)
        if respuesta.texto_plano:
            charla.append({"de": "lia", "texto": _para_memoria(respuesta.texto_plano)})
        ctx = ctx.model_copy(
            update={
                "borrador": b.model_dump(mode="json"),
                "charla": charla[-CHARLA_MAXIMA:],
            }
        )
        for nota in notas:
            ctx = ctx.anotar_revision(nota)
        self._mundo.guardar_contexto(ctx)
        for r in rechazos:
            respuesta.anotar(f"no pasó: {r}")
        return respuesta

    def _fotos(self, media: list[dict] | None) -> tuple[list[bytes], list[str]]:
        """Lo que se le pasa al modelo de cada adjunto. Solo las IMÁGENES van como
        imagen: un PDF mandado como foto hace fallar la llamada entera, y una nota
        de voz ignorada deja a la asesora contestándole a un mensaje vacío."""
        fotos, descripciones = [], []
        self._fotos_del_turno = []
        for m in media or []:
            tipo = (m or {}).get("kind")
            if tipo == "audio":
                dicho = self._oir(m)
                descripciones.append(
                    f"una nota de voz en la que dice: «{dicho}» (transcrita: si algo "
                    "suena raro, confírmaselo con cariño)"
                    if dicho
                    else "una nota de voz (no se puede escuchar: "
                    "pídele con cariño que te lo escriba)"
                )
                continue
            if tipo == "video":
                descripciones.append(
                    "un video (no se puede ver: pregúntale qué te quería mostrar)"
                )
                continue
            if tipo == "document":
                descripciones.append(
                    "un documento o PDF (no se puede abrir aquí; si se esperaba el "
                    "comprobante, recíbelo como comprobante: Lía lo verifica)"
                )
                continue
            if tipo in _SIN_ARCHIVO:
                # El 26/09 llegó uno de estos y el modelo se lo inventó: «está
                # mandando la foto de la medida». Se le dice qué fue.
                descripciones.append(_SIN_ARCHIVO[tipo].format(m.get("detalle") or ""))
                continue
            if tipo not in ("image", "sticker"):
                continue
            if m.get("descripcion"):
                descripciones.append(f"una foto: {m['descripcion']}")
                continue
            datos = None
            if self._descargar is not None:
                try:
                    datos = self._descargar(m)
                except Exception as exc:
                    log.warning("no se pudo bajar la foto (%s)", exc)
            if datos:
                fotos.append(datos)
                if tipo == "image":
                    self._fotos_del_turno.append(datos)
                descripciones.append("una foto (va adjunta; mírala)")
            else:
                descripciones.append(
                    "una foto que no se pudo abrir (pídele que la reenvíe si importa)"
                )
        return fotos, descripciones

    # -- acciones ----------------------------------------------------------

    def _abono(self, b: Borrador) -> int:
        """El abono de la compra: uno por pieza (el de la cadena es otro, 03/10),
        y se pagan juntos (Lía, 02/10)."""
        h = self._hechos
        return sum(
            h.anticipo_cadena
            if v.es_cadena
            else h.anticipo_corazon
            if v.es_corazon
            else h.anticipo
            for v in b.vistas()
        )

    def _precio(self, v: Borrador) -> int:
        """El precio de una pieza (0 si todavía no se sabe de cuántas huellitas)."""
        if v.es_cadena:
            return self._hechos.precio_cadena
        if v.es_corazon:
            return self._hechos.precio_corazon
        return self._hechos.precios.get(v.cantidad or 0, 0)

    def _precio_de_todos(self, b: Borrador) -> int:
        """Lo que suman las piezas cuyo precio ya se sabe."""
        return sum(self._precio(v) for v in b.vistas())

    def _cadena_permitida(self, b: Borrador, texto, charla) -> bool:
        """¿Se puede hablar de la cadena? Solo si ella preguntó (03/10, Camilo)."""
        return (
            pregunta_por_cadenas(texto)
            or AccionAsesora.MOSTRAR_CADENA.value in b.mostrado_en
            or any(v.es_cadena for v in b.vistas())
            or any(
                pregunta_por_cadenas(m.get("texto", ""))
                for m in charla
                if m.get("de") == "clienta"
            )
        )

    def _linea_de_la_cadena(self, b: Borrador, texto, charla) -> list[str]:
        """La cadena, SOLO si ella ya preguntó (03/10): si no, el modelo ni la ve."""
        if not self._cadena_permitida(b, texto, charla):
            return []
        h = self._hechos
        lineas = [
            "LA CADENA (ella preguntó por cadenas u otros productos; tú nunca la "
            f"ofreces): cadena con huellita y nombre, {formatear_cop(h.precio_cadena)}"
            f", abono {formatear_cop(h.anticipo_cadena)}, saldo "
            f"{formatear_cop(h.precio_cadena - h.anticipo_cadena)}. UNA huellita "
            "(corazón + 4 deditos) del color que quiera, SIN talla, y el nombre "
            "grabado es OBLIGATORIO: un renglón de grabado por lado, hasta 2 "
            "nombres por lado (2 lados). Si la quiere: acción ES_CADENA."
        ]
        if b.es_cadena:
            lineas.append(
                "LA PIEZA QUE SE DESCRIBE AHORA ES LA CADENA: no preguntes talla ni "
                "cuántas huellitas; pregunta los colores de su huellita y el nombre "
                "(o los nombres) de cada lado."
            )
        return lineas

    @staticmethod
    def _linea_de_anillos(b: Borrador) -> list[str]:
        """Lo que el modelo tiene que saber cuando compra varios anillos."""
        if not b.varios:
            return []
        k, n = b.numero_del_anillo, b.anillos_total
        lineas = [
            f"ANILLOS: compra {n} anillos. Se PREGUNTAN de a uno y en orden: ahora "
            f"va el ANILLO {k} de {n} (es el del Borrador). Hasta que este no tenga "
            "todo, no preguntes por otro. Si ella adelanta algo de OTRO anillo "
            "diciendo cuál («talla 6 el de una», «para el de tres: …», «el "
            "segundo»), anótalo igual en cambios, con los números de huellita de "
            "ESE anillo: el sistema lo guarda en él. Si no se sabe de cuál "
            "habla, pregúntale."
        ]
        otros = []
        for i, v in enumerate(b.vistas()):
            if i == len(b.anillos):
                continue
            estado = "completo" if not v.falta_del_anillo() else "por describir"
            datos = " · ".join(v._lineas_del_anillo("")[2:]) or "nada todavía"
            cantidad = (
                "un corazón"
                if v.es_corazon
                else f"{v.cantidad} huellita(s)"
                if v.cantidad
                else "huellitas ?"
            )
            pieza = (
                "Cadena"
                if v.es_cadena
                else "Anillo de corazón"
                if v.es_corazon
                else "Anillo"
            )
            otros.append(f"{pieza} {i + 1} ({estado}): {cantidad} · {datos}")
        if otros:
            lineas.append(
                "Los otros anillos (si quiere cambiar uno ya completo, anótalo igual "
                "diciendo cuál, o en nota_para_lia): " + "; ".join(otros)
            )
        if b.misma_talla:
            lineas.append(
                "Todos los anillos son de la MISMA talla (ya lo dijo): no la "
                "preguntes otra vez."
            )
        elif (
            k == 1
            and b.talla is None
            and not any(v.talla for v in b.vistas())
            and sum(not v.es_cadena for v in b.vistas()) > 1
        ):
            lineas.append(
                f"TALLA: antes de pedirla, pregúntale si los {n} anillos son de la "
                "misma talla. Si dice que sí: acción MISMA_TALLA (la talla que dé "
                "es la de todos). Si no: se pide la de cada anillo cuando le toque."
            )
        return lineas

    def _plata_de_varios(self, b: Borrador) -> list[str]:
        if not b.varios:
            return []
        return [
            f"Los {b.anillos_total} anillos juntos: total "
            f"{formatear_cop(self._precio_de_todos(b))} (de los que ya se sabe de "
            f"cuántas huellitas) · abono de todos {formatear_cop(self._abono(b))}. "
            "Se paga UN abono por todos y después UN saldo por todos, nunca "
            "anillo por anillo."
        ]

    def _montos(self, b: Borrador, pedido=None) -> set[int]:
        """Las cifras que el mensaje puede decir: precios, abono, saldo, envío
        y sus sumas (a una clienta le sirve «$68.000 con el envío»)."""
        h = self._hechos
        envio = self._mundo.envio_a(b.ciudad or None)
        base = {h.anticipo, *h.precios.values(), envio}
        base |= {p - h.anticipo for p in h.precios.values()}
        # El anillo de corazón se ofrece siempre: sus cifras se pueden decir.
        base |= {
            h.precio_corazon,
            h.anticipo_corazon,
            h.precio_corazon - h.anticipo_corazon,
        }
        if AccionAsesora.MOSTRAR_CADENA.value in b.mostrado_en or any(
            v.es_cadena for v in b.vistas()
        ):
            base |= {
                h.precio_cadena,
                h.anticipo_cadena,
                h.precio_cadena - h.anticipo_cadena,
            }
        if b.varios:
            todos = self._precio_de_todos(b)
            base |= {self._abono(b), todos, max(0, todos - self._abono(b))}
        if pedido is not None:
            base |= {
                pedido.total_cop,
                pedido.anticipo_cop,
                pedido.saldo_cop,
                max(0, pedido.saldo_cop - pedido.saldo_pagado_cop),
            }
            if pedido.envio_contraentrega_cop:
                base.add(pedido.envio_contraentrega_cop)
        return base | {m + envio for m in base if m != envio}

    @staticmethod
    def _lo_del_nombre(
        b: Borrador,
        respuesta,
        en_whatsapp: str,
        notas,
        rechazos,
        *,
        pago_previo: bool = False,
    ) -> None:
        """Su nombre no se pide a ciegas: se le propone el que ya tenemos.

        En una conversación real la clienta pagó los $60.000 y el pedido no
        nació porque nunca escribió su nombre completo: se lo pidieron CUATRO
        veces y ella contestó otras cosas, hasta que las notas del panel
        decían «ha rechazado darlo dos veces». Con Lía esa venta se cerró —
        porque Lía lo tiene delante, en el contacto de WhatsApp, y no se lo
        habría preguntado ni una vez.

        Nadie escribe su nombre en un chat donde el otro ya lo ve. Así que se
        le propone: «¿Lo dejo a nombre de Laura Gómez? 🥰» se contesta con un
        «sí», y el pedido nace.

        Y si ya pagó y sigue faltando, eso lo cierra una persona: dinero
        recibido con el pedido a medias no se queda esperando en un chat.
        """
        if b.nombre_clienta.strip() or b.falta_del_anillo():
            return
        # Pagó y SIGUE sin nombre: lo cierra Lía, una vez, con el de WhatsApp.
        #
        # «Pagó» incluye pagar con el pedido a medias (`pagado_sin_pedido`),
        # que es el caso real: sin nombre el pedido no nace y el abono no llega
        # a contar como reportado. Mirando solo `abono_reportado` esta rama no
        # se encendía nunca, y a Lía no le llegaba el nombre que sí teníamos
        # (repaso del 21/09).
        #
        # «Sigue» quiere decir que el pago es de un turno ANTERIOR
        # (`pago_previo`). En el turno del pago se le pregunta o se le propone
        # como a cualquiera: avisando ahí mismo, Lía recibía `necesita-persona`
        # por algo que se resolvía solo, porque ella daba el nombre en el
        # mensaje siguiente (repasos del 21/09, sint-01 y sint-07).
        if pago_previo and not b.llamada_por_pago_incompleto:
            b.llamada_por_pago_incompleto = True
            respuesta.escalar = True
            notas.append(
                "Pagó y el pedido no está completo: falta su nombre. "
                + (
                    f"En WhatsApp aparece como «{en_whatsapp}»: confírmalo con ella."
                    if en_whatsapp
                    else "No lo ha escrito y ya se le pidió varias veces."
                )
            )
            rechazos.append("pagó y falta su nombre: lo cierra Lía")
            return
        if b.llamada_por_pago_incompleto:
            # Lía ya está avisada y el nombre es suyo.
            return
        # El nombre de WhatsApp es lo que la persona puso en su perfil, y puede
        # ser cualquier cosa: una clienta tenía «.» y le llegó «¿Lo dejo a
        # nombre de .? 🥰» (29/09). Sin al menos dos letras no hay qué proponer.
        nombre = (en_whatsapp or "").strip()
        if sum(c.isalpha() for c in nombre) < 2:
            nombre = ""
        # Se pregunta UNA vez; la segunda ya no se pregunta, se propone. En una
        # prueba en vivo del 21/09 el modelo lo pidió con tres frases distintas
        # («¿A nombre de quién va?», «¿Cuál es tu nombre para el pedido?», «me
        # dejas tu nombre completo») antes de que saliera la propuesta: la
        # pregunta del modelo tapaba la propuesta por la regla de abajo.
        if Asesora._cambiar_por_la_propuesta(b, respuesta, nombre):
            return
        # Una pregunta por mensaje. El 20/09, en una conversación de verdad, a
        # una clienta que acababa de dar el nombre de su perrito le llegó:
        #
        #     ¡Qué nombre tan lindo! 🐾 ¿Cooper es uno solo, o tienes dos…?
        #     ¿Lo dejo a nombre de Jose Pérez? 🥰
        #
        # Dos preguntas seguidas sobre cosas distintas. No volvió a escribir.
        # Lo del nombre del pedido puede esperar al turno siguiente; lo que se
        # está hablando, no.
        if "?" in respuesta.texto_plano:
            return

        # Una vez cada dos turnos como mucho: proponérselo en cada mensaje es
        # el mismo acoso, solo que con otras palabras.
        if not nombre or b.mostrado_en.get("PROPONER_NOMBRE", -9) >= b.turnos - 1:
            return
        b.mostrado_en["PROPONER_NOMBRE"] = b.turnos
        respuesta.decir(f"¿Lo dejo a nombre de {nombre}? 🥰")

    @staticmethod
    def _cambiar_por_la_propuesta(b: Borrador, respuesta, nombre: str) -> bool:
        """¿El modelo le vuelve a pedir su nombre? Entonces se le propone.

        La primera vez que se le pide, se deja y se anota el turno
        (`mostrado_en["PEDIR_NOMBRE"]`). En un turno posterior, la frase del
        modelo se quita y en su lugar va «¿Lo dejo a nombre de X?». Eso pasa
        UNA vez: si ya se le propuso, se deja preguntar al modelo. Sin nombre
        de WhatsApp no hay qué proponer, y se deja como venía.

        Solo si esa es la ÚNICA pregunta del mensaje: si el modelo pregunta
        además otra cosa, se deja todo como está (una pregunta por mensaje, y
        lo que se está hablando va primero).

        Devuelve True si ya quedó resuelto lo del nombre en este turno.
        """
        for i, pieza in enumerate(respuesta.piezas):
            if not pieza.texto or pieza.imagen:
                continue
            frase = _PIDE_SU_NOMBRE.search(pieza.texto)
            if not frase or "grab" in frase.group(0).lower():
                continue
            pedido_antes = b.mostrado_en.get("PEDIR_NOMBRE", b.turnos) < b.turnos
            # Una sola vez. Si ya se le propuso, que el modelo pregunte es lo
            # correcto: puede que haya dicho que no. En el repaso del 21/09 una
            # clienta contestó «No» a «¿Lo dejo a nombre de Daniela Ospina?» y,
            # cambiando cada pregunta del modelo por la propuesta, se le volvió
            # a proponer el mismo nombre dos veces más; el pedido no nació.
            ya_propuesto = "PROPONER_NOMBRE" in b.mostrado_en
            if not pedido_antes or not nombre or ya_propuesto:
                b.mostrado_en.setdefault("PEDIR_NOMBRE", b.turnos)
                return False
            resto = (pieza.texto[: frase.start()] + pieza.texto[frase.end() :]).strip()
            otras = [p.texto for j, p in enumerate(respuesta.piezas) if j != i]
            if "?" in resto or any("?" in t for t in otras if t):
                return False
            # Lo que queda sin letras (un «🥰» suelto) no se manda.
            quedan = list(respuesta.piezas)
            if any(c.isalnum() for c in resto):
                quedan[i] = replace(pieza, texto=resto)
            else:
                del quedan[i]
            respuesta.piezas = quedan
            b.mostrado_en["PROPONER_NOMBRE"] = b.turnos
            respuesta.decir(f"¿Lo dejo a nombre de {nombre}? 🥰")
            return True
        return False

    @staticmethod
    def _le_falta_la_pregunta(respuesta, b: Borrador, estado: str, cabecera) -> bool:
        """¿Se queda mudo pudiendo preguntar algo?"""
        if respuesta.escalar or "?" in respuesta.texto_plano:
            return False
        if estado in SIN_NADA_QUE_PREGUNTAR or b.abono_reportado or b.saldo_reportado:
            return False
        # Con las cuentas recién mandadas se cierra con `QUEDO_ATENTA`: que sepa
        # que falta su comprobante —no que ya lo recibimos— y con una pregunta
        # suave, sin apurarla (Camilo, 21/09). Sale de `_lo_que_falta`.
        if cabecera.vacia is False:
            return True
        # Lo que se agrega tiene que ser una PREGUNTA. Si no falta nada, lo que
        # queda es la frase neutra de `_mensaje_seguro`, y pegarla debajo de una
        # respuesta no pregunta nada: el 21/09 preguntó si podía pagar el envío
        # y le llegó la respuesta y debajo «¡Recibido! 🙌», sin haber mandado
        # ningún pago.
        return "?" in Asesora._lo_que_falta(b, estado)

    @staticmethod
    def _lo_que_falta(b: Borrador, estado: str = "") -> str:
        """Lo siguiente que hay que preguntar, cuando no hay nada que contestar.

        El orden es el mismo de siempre: primero el anillo y su nombre (lo del
        abono), y solo después de las fotos los datos de la guía. Si no falta
        nada, se dice lo neutro de `_mensaje_seguro` — que es de lo que se está
        esperando a una persona.
        """
        falta = b.falta_para_abono() if not b.abono_reportado else b.falta_de_la_guia()
        # Si ya está en lo de la talla (le llegó la guía o lo de la joyería), no
        # se le vuelve a preguntar «¿sabes tu talla o te comparto la guía?»: se
        # sigue con lo siguiente (prueba de verdad, 06/10).
        midiendo = SIN_ANILLOS in b.mostrado_en or (
            AccionAsesora.MOSTRAR_GUIA_TALLA.value in b.mostrado_en
        )
        # Lo que dejó para después o ya se le pidió dos veces, tampoco (09/10).
        no_pedir = que_no_se_pide(b)
        for que in falta:
            if (que == "talla" and midiendo) or que in no_pedir:
                continue
            if que.startswith(ANILLO_SIGUIENTE):
                # Solo si a ese anillo le falta algo que se le pueda pedir, y
                # la frase fija («¿de cuántas huellitas?») solo si está vacío.
                if not queda_algo_del_anillo(b, que):
                    continue
                if otro_anillo_vacio(b, que):
                    return OTRO_ANILLO_POR_EMPEZAR
                continue
            pregunta = pregunta_de(que, b)
            if pregunta:
                return pregunta
        return Asesora._mensaje_seguro(b, estado)

    @staticmethod
    def _mensaje_seguro(b: Borrador, estado: str = "") -> str:
        # «¡Recibido!» SOLO cuando llegó un comprobante o dijo que ya pagó. En
        # cualquier otro momento se lee como «recibí tu pago» (21/09: «Cuál
        # recibido si no he hecho el pago»).
        if (
            b.abono_reportado
            or b.saldo_reportado
            or b.pagado_sin_pedido
            or estado == "EN_REVISION_PAGO"
        ):
            return "¡Recibido! 🙌"
        if b.cuentas_enviadas and estado in ("", "ESPERANDO_ANTICIPO"):
            return QUEDO_ATENTA
        if estado == "ESPERANDO_SALDO":
            return QUEDO_ATENTA_SALDO
        return "¡Listo! 🙌"

    def _sincronizar(
        self, antes: Borrador, nuevo: Borrador, pedido, respuesta, notas, rechazos
    ):
        """Lleva al pedido lo que cambió en la charla, si su estado lo permite."""
        from app.domain.cambios import DATOS_DE_LA_GUIA, Permiso, permiso

        cambiados, ya_tenian = set(), set()
        pares = {
            "talla": ("talla",),
            "colores": ("huellitas",),
            "grabado": ("grabado", "sin_grabado"),
            "nombre": ("nombre_clienta",),
            "destinatario": ("destinatario",),
            "ciudad": ("ciudad",),
            "direccion": ("direccion", "recoge"),
            "barrio": ("barrio",),
            "cedula": ("cedula",),
            "celular": ("celular",),
        }
        for campo, atributos in pares.items():
            if any(getattr(antes, a) != getattr(nuevo, a) for a in atributos):
                cambiados.add(campo)
                if any(getattr(antes, a) for a in atributos):
                    ya_tenian.add(campo)
        if antes.cantidad != nuevo.cantidad:
            # Otra cantidad es otro precio: eso no se re-cotiza desde el chat.
            nuevo.cantidad = antes.cantidad
            rechazos.append(
                "cambiar la cantidad de huellitas de un pedido creado lo hace Lía"
            )
            notas.append(
                f"La clienta quiere cambiar la cantidad de huellitas ({pedido.codigo})"
            )
            respuesta.escalar = True
        if not cambiados:
            return
        veredicto = permiso(pedido.estado, cambiados, sobrescribe=ya_tenian)
        if veredicto in (Permiso.APLICAR, Permiso.APLICAR_Y_REVISAR):
            personalizacion, _ = nuevo.a_personalizacion()
            # Con varios anillos, el que se puede corregir desde el chat es el
            # último (el que se estaba describiendo): solo esa línea.
            self._mundo.actualizar_personalizacion(
                pedido.id,
                personalizacion,
                len(nuevo.anillos) if len(pedido.items) > 1 else None,
            )
            # TODOS los datos de la guía. Antes solo nombre, ciudad y
            # dirección: una cédula o un celular solos no llegaban al pedido.
            if cambiados & DATOS_DE_LA_GUIA:
                envio = (pedido.envio or DatosDeEnvio()).model_copy(
                    update=_envio_desde(nuevo)
                )
                self._mundo.actualizar_envio(pedido.id, envio)
            if veredicto is Permiso.APLICAR_Y_REVISAR:
                notas.append(
                    f"Cambio en {pedido.codigo} ({', '.join(sorted(cambiados))}): revisar"
                )
            return
        # No se aplica: el borrador vuelve a lo que el pedido de verdad tiene.
        for campo in cambiados:
            for atributo in pares[campo]:
                setattr(nuevo, atributo, getattr(antes, atributo))
        rechazos.append(
            f"el pedido {pedido.codigo} está en {pedido.estado}: el cambio de "
            f"{', '.join(sorted(cambiados))} lo decide Lía (no se guardó)"
        )
        if veredicto is Permiso.PEDIR_A_PERSONA:
            que = ", ".join(sorted(cambiados))
            notas.append(f"La clienta pide cambiar {que} en {pedido.codigo}")
            respuesta.escalar = True

    def _como_queda(self, b: Borrador, respuesta: Respuesta, jugada=None) -> None:
        """Le enseña cómo queda: lo que ya escogió, o lo que está mirando.

        «Muéstrame cómo queda en rosado» no es «lo quiero rosado». Si el modelo
        manda `vistas_previas`, se dibujan ESAS y no se guarda nada: está
        comparando. El 20/09 pidió ver colores tres veces y solo le llegó un
        «¡Claro! Te muestro…» sin ninguna foto.
        """
        vistas = list(getattr(jugada, "vistas_previas", None) or [])[:MAXIMO_VISTAS]
        if vistas:
            # Las mismas fotos dos turnos seguidos son ruido: ella ya las vio
            # y normalmente está hablando de otra cosa (20/09).
            firma = [
                f"{h.corazon}-{h.dedos}-{h.dedos_alternos}"
                for d in vistas
                for h in d.huellitas
            ]
            if firma and firma == b.ultimas_vistas:
                return
            b.ultimas_vistas = firma
            mandadas = 0
            for diseno in vistas:
                huellitas = [
                    _a_huellita(h)
                    for h in diseno.huellitas
                    if h.corazon is not None and (h.dedos or h.dedos_alternos)
                ]
                if not huellitas:
                    continue
                huellitas = _el_anillo_entero(huellitas, b)
                if (vista := self._mundo.previsualizar(huellitas)) is not None:
                    # El pie lleva los nombres DEL MUESTRARIO, no el que le puso
                    # el modelo al diseño («verde menta» no existe).
                    pie = "Así se te vería 😍\n" + nombres_de_los_colores(huellitas)
                    respuesta.mostrar(vista, pie=pie)
                    mandadas += 1
            if mandadas:
                return
            # Si no se pudo dibujar ninguna, se sigue al camino de abajo: es
            # preferible enseñarle lo que ya escogió que no enseñarle nada.

        completas = [h for h in b.huellitas if h.completa]
        if not completas:
            return
        personalizacion, _ = b.a_personalizacion()
        vista = self._mundo.previsualizar(personalizacion.huellitas)
        if (
            vista
            and b.ultimas_vistas == [vista]
            and b.mostrado_en.get("VISTA_ESCOGIDA", -9) >= b.turnos - 1
        ):
            # La misma foto del turno anterior, otra vez: ruido (prueba de verdad,
            # 05/10: «sí, así está bien» y le volvió a llegar idéntica).
            return
        if vista:
            b.ultimas_vistas = [vista]
            b.mostrado_en["VISTA_ESCOGIDA"] = b.turnos
            respuesta.mostrar(
                vista,
                pie="Así se te va a ver 😍💍\n"
                + nombres_de_los_colores(personalizacion.huellitas),
            )

    def _como_queda_el_corazon(
        self, b: Borrador, respuesta: Respuesta, jugada=None, *, sugerencias=False
    ) -> None:
        """Cómo queda el anillo de corazón (Camilo, 17/10): el corazón solo, al
        derecho, del color que escogió; o de los que está mirando
        (`vistas_previas`); o, si pide consejo, los cuatro de siempre."""
        if sugerencias:
            colores = list(SUGERENCIAS)
        else:
            colores = [
                h.corazon or h.dedos
                for d in list(getattr(jugada, "vistas_previas", None) or [])[
                    :MAXIMO_VISTAS
                ]
                for h in d.huellitas[:1]
                if h.corazon or h.dedos
            ]
        mirando = bool(colores)
        if not colores and b.huellitas and b.huellitas[0].corazon is not None:
            colores = [b.huellitas[0].corazon]
        firma = [f"corazon-{c}" for c in colores]
        if not colores or (firma == b.ultimas_vistas and not sugerencias):
            return  # nada que mostrar, o lo mismo del turno anterior
        b.ultimas_vistas = firma
        for color in colores:
            vista = self._mundo.previsualizar_corazon(color)
            if vista is None:
                continue
            nombre = f"{EMOJI_COLOR[color]} {NOMBRE_COLOR[color]}"
            pie = (
                pie_de_sugerencia(color)
                if sugerencias
                else f"Así se te vería 😍\nCorazón {nombre}"
                if mirando
                else f"Así se te va a ver 😍💍\nCorazón {nombre}"
            )
            respuesta.mostrar(vista, pie=pie)

    def _sugerencias(self, b: Borrador, respuesta: Respuesta) -> None:
        """Pidió consejo: los 4 diseños de un solo color, con su nombre."""
        n = b.cantidad or 1
        for color in SUGERENCIAS:
            pie = pie_de_sugerencia(color)
            vista = self._mundo.previsualizar(
                [Huellita(corazon=color, dedos=color) for _ in range(n)]
            )
            if vista:
                respuesta.mostrar(vista, pie=pie)

    def _mandar_cuentas(
        self, b: Borrador, pedido, respuesta, rechazos, *, lo_pidio: bool = False
    ) -> None:
        """Preguntó cómo pagar: las cuentas, con el monto que toca AHORA.

        No se repiten en dos turnos seguidos (se lee como spam), SALVO que ella
        las pida con todas las letras: «Cuenta», «¿a qué Nequi?». Negárselas
        ahí la deja sin poder pagar (21/09).
        """
        ultimo = max(
            b.mostrado_en.get("MANDAR_CUENTAS", -9), b.mostrado_en.get("PEDIR_ABONO", -9)
        )
        if ultimo >= b.turnos - 1 and not lo_pidio:
            rechazos.append("las cuentas se mandaron en el turno anterior: no se repiten")
            return
        # Sin pedido y con algo pendiente (la talla que confirma Lía, el
        # resumen…), las cuentas no van si ella no las pidió: el 29/09 le llegó
        # «Lía te confirma la talla en unos minutos y te paso todo» y, justo
        # debajo, los datos para el abono. Si las pide, sí (ADR 0022).
        if pedido is None and (falta := b.falta_para_abono()) and not lo_pidio:
            rechazos.append(ABONO_BLOQUEADO + ", ".join(falta))
            return
        if pedido is not None and pedido.estado in (
            "PRODUCCION_LISTA",
            "ESPERANDO_SALDO",
        ):
            pendiente = max(0, pedido.saldo_cop - pedido.saldo_pagado_cop)
            cabeza = f"*Para el saldo de {formatear_cop(pendiente)} puedes transferir a:*"
        elif b.abono_reportado or (
            pedido is not None and pedido.estado not in ("ESPERANDO_ANTICIPO",)
        ):
            rechazos.append("no hay nada por pagar ahora: no se mandaron cuentas")
            return
        else:
            abono = (pedido.anticipo_cop if pedido is not None else 0) or self._abono(b)
            cabeza = f"*Para el abono de {formatear_cop(abono)} puedes transferir a:*"
        respuesta.decir("\n".join([cabeza, "", datos_para_transferir()]))
        b.cuentas_enviadas = True
        b.mostrado_en["MANDAR_CUENTAS"] = b.turnos

    def _pedir_abono(self, conv, b: Borrador, respuesta, rechazos, notas) -> None:
        falta = b.falta_para_abono()
        if falta:
            rechazos.append(ABONO_BLOQUEADO + ", ".join(falta))
            return
        if b.cuentas_enviadas and b.mostrado_en.get("PEDIR_ABONO", -9) >= b.turnos - 1:
            # Dos veces seguidas el bloque de cuentas se lee como spam, y en el
            # momento de pedir plata eso cuesta confianza.
            rechazos.append("las cuentas se mandaron en el turno anterior: no se repiten")
            return
        if b.pedido_id is None and not self._crear_pedido(
            conv, b, respuesta, rechazos, notas
        ):
            return
        # El monto sale del PEDIDO recién creado: con varios anillos es el abono
        # de todos, en UNA transferencia (Lía, 02/10).
        creado = self._mundo.pedido(b.pedido_id) if b.pedido_id else None
        abono = (creado.anticipo_cop if creado else 0) or self._abono(b)
        de_que = _de_que(b)
        bloque = [
            f"*A esta cuenta puedes transferir los {formatear_cop(abono)} "
            f"del abono {de_que} 💓*",
            "",
            datos_para_transferir(),
            "",
            para_las_piezas(self._linea_del_envio(b), [v.pieza for v in b.vistas()]),
        ]
        if not b.envio_con_saldo and (
            _sin_tildes((b.ciudad or "").strip().lower()) in CIUDADES_CERCA
        ):
            bloque.append(
                "O si prefieres lo recoges en "
                f"{PUNTO_DE_RECOGIDA} y te ahorras el envío 🥰"
            )
        respuesta.decir("\n".join(bloque))
        b.cuentas_enviadas = True
        b.mostrado_en["PEDIR_ABONO"] = b.turnos

    def _envio_al_pedido(self, antes, nuevo, pedido, respuesta, notas, rechazos):
        """Lleva al pedido ya creado CUÁNDO paga el envío.

        Mientras no haya pagado el saldo se puede cambiar: es cuándo se cobra,
        no qué se fabrica. Después ya se cobró como se cobró, y eso lo ve Lía.
        """
        if pedido.estado in (
            "SALDO_PAGADO",
            "DESPACHADO",
            "ENTREGADO",
            "CANCELADO",
            "REEMBOLSO",
        ):
            nuevo.envio_con_saldo = antes.envio_con_saldo
            rechazos.append(
                f"el pedido {pedido.codigo} está en {pedido.estado}: cuándo se paga "
                "el envío ya no se cambia desde el chat (lo ve Lía)"
            )
            notas.append(
                f"La clienta quiere cambiar cuándo paga el envío en {pedido.codigo}"
            )
            respuesta.escalar = True
            return
        # Se relee: `_sincronizar` puede haber guardado recién el nombre o la
        # dirección, y partir del pedido viejo los borraría.
        actual = self._mundo.pedido(pedido.id) or pedido
        envio = (actual.envio or DatosDeEnvio()).model_copy(
            update={"envio_con_saldo": nuevo.envio_con_saldo}
        )
        self._mundo.actualizar_envio(pedido.id, envio)

    def _el_abono_va_primero(self, b: Borrador) -> str:
        """Qué hace entrar el anillo al taller, dicho sin prometer nada."""
        frase = (
            f"Apenas hagas el abono de {formatear_cop(self._abono(b))}, "
            "tu anillo entra al taller 💓"
        )
        if b.envio_con_saldo:
            frase += " El saldo y el envío los pagas cuando esté listo 🚚"
        else:
            frase += " El saldo lo pagas cuando esté listo y lo veas en fotos 🙌"
        return para_las_piezas(frase, [v.pieza for v in b.vistas()])

    def _linea_del_envio(self, b: Borrador) -> str:
        """Cuándo se paga el envío, dicho debajo de las cuentas del abono.

        Lo normal es al recibir. Si ella pidió pagarlo antes, se paga con el
        SALDO —nunca con el abono—, y entonces «lo puedes cancelar al recibir»
        es justo lo contrario de lo que acordó (21/09).
        """
        envio = formatear_cop(self._mundo.envio_a(b.ciudad or None))
        if b.envio_con_saldo:
            return (
                f"El envío nacional ({envio} por COORDINADORA) lo pagas junto con "
                "el saldo cuando tu anillo esté listo, así no tienes que pagar "
                "nada al recibirlo 🚚❣️"
            )
        return (
            f"Envíos nacionales tienen un valor de {envio} por COORDINADORA, "
            "ese valor lo puedes cancelar al recibir tu anillo 🚚❣️"
        )

    def _envio_acordado(
        self, antes: Borrador, nuevo: Borrador, pedido, mensaje: str, notas
    ) -> str:
        """Lo que se dice cuando cambia CUÁNDO paga el envío. Python, no el modelo.

        Es plata: cuánto y cuándo se cobra no puede depender de que el modelo lo
        diga bien. El 21/09 le ofreció pagarlo junto con el abono, y después dio
        el pedido por tomado sin abono. Aquí se deja por escrito lo acordado y,
        si todavía no ha pagado, que el abono es lo que hace entrar el anillo
        al taller.
        """
        if antes.envio_con_saldo == nuevo.envio_con_saldo:
            return ""
        codigo = f" ({pedido.codigo})" if pedido is not None else ""
        if not nuevo.envio_con_saldo:
            notas.append(f"La clienta vuelve a pagar el envío al recibir{codigo}")
            return ""
        notas.append(
            f"La clienta pagará el ENVÍO junto con el SALDO{codigo}: cóbraselo con "
            "el saldo y no al recibir"
        )
        if "saldo" in (mensaje or "").lower():
            # El modelo ya lo dijo bien (el vigilante ya revisó que no lo junte
            # con el abono): repetirlo sería decírselo dos veces.
            return ""
        envio = formatear_cop(self._mundo.envio_a(nuevo.ciudad or None))
        frase = (
            f"El envío ({envio}) lo pagas junto con el saldo cuando tu anillo esté "
            "listo, y así no tienes que pagar nada al recibirlo 🚚"
        )
        if not nuevo.abono_reportado and (
            pedido is None or pedido.estado in ("ESPERANDO_ANTICIPO",)
        ):
            frase += (
                f" Por ahora solo el abono de {formatear_cop(self._abono(nuevo))} "
                "para que tu anillo entre al taller 💓"
            )
        return frase

    def _crear_pedido(self, conv, b: Borrador, respuesta, rechazos, notas) -> bool:
        # Un pedido con una línea por anillo (02/10): un abono y un saldo.
        anillos = b.anillos_del_pedido()
        notas_pedido = list(b.notas) + [n for _, _, ns in anillos for n in ns]
        pedido = self._mundo.crear_pedido_de_anillos(
            conv,
            [(cantidad, personalizacion) for cantidad, personalizacion, _ in anillos],
            envio=DatosDeEnvio(
                **_envio_desde(b),
                telefono=conv.partition(":")[2][:20],
                envio_con_saldo=b.envio_con_saldo,
            ),
        )
        if pedido is None:
            rechazos.append("no se pudo crear el pedido")
            notas.append("No se pudo crear el pedido automáticamente: crearlo a mano")
            respuesta.escalar = True
            return False
        b.pedido_id, b.pedido_codigo = pedido.id, pedido.codigo
        notas.extend(notas_pedido)
        return True

    def _recibir_comprobante(
        self, conv, b: Borrador, respuesta, notas, rechazos, pedido=None
    ) -> None:
        if pedido is not None and pedido.estado in (
            "PRODUCCION_LISTA",
            "ESPERANDO_SALDO",
        ):
            # El anillo ya está listo: este comprobante es el del SALDO. Antes se
            # ignoraba y nadie se enteraba de que la clienta había pagado (19/09).
            if not b.saldo_reportado:
                self._mundo.marcar_pago_por_revisar(pedido.id)
                b.saldo_reportado = True
                pendiente = max(0, pedido.saldo_cop - pedido.saldo_pagado_cop)
                notas.append(
                    f"Verificar SALDO de {formatear_cop(pendiente)} del pedido "
                    f"{pedido.codigo} (ya se puede despachar si llegó)"
                )
            else:
                rechazos.append("el comprobante del saldo ya se había recibido")
            return
        if b.abono_reportado and pedido is not None:
            rechazos.append(
                "el comprobante del saldo ya se había recibido"
                if b.saldo_reportado
                else "el comprobante del abono ya se había recibido"
            )
            return
        if b.pedido_id is None:
            # Pagó antes de que se le mandaran las cuentas (ya las conocía, o
            # compró antes). Si el anillo está completo, el pedido nace aquí:
            # sin él, el pago no queda registrado en ninguna parte.
            falta = b.falta_para_abono()
            if falta:
                b.pagado_sin_pedido = True
                notas.append(
                    "La clienta dice que pagó el abono y el pedido NO está completo "
                    f"(falta {', '.join(falta)}): no entra al taller hasta tenerlo"
                )
                rechazos.append(
                    "pagó antes de completar el pedido: pídele con cariño lo que "
                    "falta (" + ", ".join(falta) + ")"
                )
                return
            if not self._crear_pedido(conv, b, respuesta, rechazos, notas):
                return
        if not b.abono_reportado:
            self._mundo.marcar_pago_por_revisar(b.pedido_id)
            b.abono_reportado = True
            b.pagado_sin_pedido = False
            notas.append(f"Verificar abono del pedido {b.pedido_codigo}")


def _de_que(b: Borrador) -> str:
    """«del anillo», «de la cadena», «de los 2 anillos», «del anillo y la cadena»."""
    vistas = b.vistas()
    cadenas = sum(v.es_cadena for v in vistas)
    anillos = len(vistas) - cadenas
    if len(vistas) == 1:
        return "de la cadena" if cadenas else "del anillo"
    if not cadenas:
        return f"de los {anillos} anillos"
    if not anillos:
        return f"de las {cadenas} cadenas"
    if anillos == 1 and cadenas == 1:
        return "del anillo y la cadena"
    return f"de las {len(vistas)} piezas"


def _envio_desde(b: Borrador) -> dict:
    """Los datos de la guía del borrador, como los guarda el pedido."""
    return {
        "nombre": (b.destinatario or b.nombre_clienta)[:60],
        "ciudad": b.ciudad[:60],
        "direccion": b.direccion[:200],
        "barrio": b.barrio[:80],
        "recoge": b.recoge,
        "cedula": b.cedula[:15],
        "celular": b.celular[:15],
    }


def _sin_tildes(texto: str) -> str:
    import unicodedata

    return "".join(
        c
        for c in unicodedata.normalize("NFKD", texto or "")
        if not unicodedata.combining(c)
    )


#: Pide un anillo de huellita, no solo lo nombra («uno de huellita para mí»).
_PIDE_UNO_DE_HUELLITA = re.compile(
    r"\b(?:uno|un\s+anillo|anillo|otro|el)\s+(?:de|con)\s+(?:la\s+|una\s+)?huellit",
    re.I,
)


def viene_por_el_corazon(b: Borrador, texto: str | None, *, hay_pedido: bool) -> bool:
    """¿La charla es por el anillo de corazón aunque la IA no lo haya marcado?

    Sí cuando vio SU presentación y no la de la huellita, todavía no hay nada
    escogido de otra pieza ni pedido, y lo que dice no habla de huellitas ni es
    un «no». Si vio las dos, decide la IA (puede querer cualquiera).
    """
    return (
        AccionAsesora.MOSTRAR_CORAZON.value in b.mostrado_en
        and AccionAsesora.MOSTRAR_PRECIOS.value not in b.mostrado_en
        and b.pieza == "anillo"
        and not b.varios
        and not b.pedido_id
        and not hay_pedido
        and not re.search(r"huell|patit", texto or "", re.I)
        and not no_quiere(texto or "")
    )


def _colores_completos(b: Borrador) -> bool:
    """¿Ya se sabe el color de todas las huellitas que lleva el anillo?"""
    n = b.cantidad or len(b.huellitas)
    return n > 0 and len(b.huellitas) >= n and all(h.completa for h in b.huellitas[:n])


#: Cuánto se guarda de cada mensaje en la memoria de la charla.
MEMORIA_POR_MENSAJE = 700


def _para_memoria(texto: str) -> str:
    """Lo que se recuerda de un mensaje largo: el FINAL.

    La apertura son ~750 caracteres y termina con «¿Sabes tu talla?». Cortando
    por el principio se guardaba la ficha entera —que es fija, y que el modelo
    ya tiene en sus hechos— y se perdía la pregunta. El turno siguiente leía la
    charla sin saber qué acabábamos de preguntar (20/09).

    Lo último que se dijo es lo que manda la conversación.
    """
    texto = texto or ""
    if len(texto) <= MEMORIA_POR_MENSAJE:
        return texto
    return "…" + texto[-MEMORIA_POR_MENSAJE:]


def _a_huellita(h) -> Huellita:
    """Del borrador (o de lo que propone el modelo) a lo que se fabrica.

    Arrastra los deditos alternos: sin esto, «negro-blanco-negro-blanco» se
    dibujaba con los cuatro deditos iguales (20/09).
    """
    alternos = list(getattr(h, "dedos_alternos", []) or [])
    return Huellita(
        corazon=h.corazon,
        dedos=h.dedos or alternos[0],
        dedos_alternos=alternos if len(alternos) == 4 else [],
    )


def _el_anillo_entero(huellitas: list[Huellita], b) -> list[Huellita]:
    """El anillo completo, no una patita suelta.

    Quien compra el de tres tiene que ver tres. El modelo manda el diseño de la
    que se está hablando; lo que falta se completa con lo que ella ya escogió
    para las otras, y si no hay, repitiendo la última —que es el color que está
    mirando— (Camilo, 20/09).
    """
    cuantas = b.cantidad or 1
    if len(huellitas) >= cuantas:
        return huellitas[:cuantas]
    ya = [_a_huellita(h) for h in b.huellitas[len(huellitas) :] if h.completa]
    completas = (huellitas + ya)[:cuantas]
    return completas + [completas[-1]] * (cuantas - len(completas))


def _para_charla(texto: str | None, descripciones: list[str]) -> str:
    partes = [(texto or "").strip()]
    partes += [f"[foto: {d}]" for d in descripciones]
    return " ".join(p for p in partes if p)[:700] or "(vacío)"
