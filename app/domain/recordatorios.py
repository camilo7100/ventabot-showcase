"""El seguimiento: a quién escribirle, qué y CUÁNDO (04/10).

════════════════════════════════════════════════════════════════════════════
POR QUÉ
════════════════════════════════════════════════════════════════════════════
Camilo, 04/10: «la persona que me escribió y quedó en la talla: es normal,
medir un anillo es un esfuerzo grande y se le olvida. Pero si me escribe a las
2 de la tarde no le voy a escribir a las 2 a. m. Hay que ser muy inteligente…
me da miedo que a la gente no le guste ser acosada… haz lo que más me venda».

La venta más barata de recuperar es la que ya empezó. Y dentro de la ventana
de 24 h de WhatsApp (desde el último mensaje de ELLA) se le puede escribir
texto libre: sin plantilla, sin aprobación de Meta y casi gratis (los primeros
1.000 mensajes de servicio al mes son gratis; después ~US$0,0008 cada uno).
Los textos son FIJOS: ni un peso de IA.

════════════════════════════════════════════════════════════════════════════
LAS REGLAS (las de vender sin acosar)
════════════════════════════════════════════════════════════════════════════
1. **Solo si la pelota está en SU cancha**: lo último lo dijo el bot (o Lía)
   y falta algo de ella — la talla, la cantidad, los colores, el grabado, su
   nombre, el «sí» al resumen o el abono. Si lo que falta es de Lía (confirmar
   la talla, verificar un pago), no se le escribe a ella.
2. **Máximo TRES por cada vez que se queda callada**: el de su etapa, otro
   si cabe un segundo horario en sus 24 h y —solo si ya invirtió en su diseño
   (`CON_PLANTILLA`)— uno con plantilla a los 3 días. La plantilla, como mucho
   una vez por semana a la misma persona (lo controla el worker). Si contesta,
   la cuenta vuelve a empezar con su próximo silencio.
3. **Solo en DOS horarios: 9 a. m. y 5 p. m., hora de Colombia** (Camilo,
   05/10: el de las 9:35 «no está mal, lo que no me gusta es el horario»).
   El primero va en el primer horario que quede al menos 8 h después de su
   último mensaje: si escribió antes de las 9 a. m., a las 5 p. m. de ese día;
   si escribió después, a las 9 a. m. del día siguiente. Siempre dentro de sus
   24 h (texto libre, sin plantilla): quien escribió entre 9:00 y 9:30 recibe
   el de las 5 p. m. (las 9 a. m. siguientes ya quedarían por fuera).
4. **El segundo, solo si cabe otro horario en la ventana** (al menos 5 h
   después del primero; en la práctica, quien escribió de noche recibe uno a
   las 9 a. m. y otro a las 5 p. m.), con una razón para hacerlo hoy: la fecha
   en que tendría su anillo. Sin descuentos (no se dan).
5. **El de los 3 días, también en un horario**: el más cercano a la hora en
   que ella suele escribir (antes de la 1 p. m., las 9; si no, las 5).
6. **Si dijo que NO** («no gracias», «no me interesa») o lo deja para otro
   mes («lo dejo pasar, quizás el próximo mes»), nunca. **Si pidió
   tiempo** («lo pienso», «mañana le consigno», «ahora no me queda fácil»),
   UNO solo en la ventana: el PRIMER horario (escribió a las 9 p. m. -> a las
   9 a. m.; Camilo, 07/10); después, si aplica, el de los 3 días. Un sticker o
   una reacción solos no cuentan como «lo último lo dijo ella».
7. Nunca si la atiende una persona, si la charla está escalada a Lía o si es
   un número de prueba.
8. **Solo ANTES del abono** (Camilo, 04/10): el «falta el abono» es lo último
   que se le recuerda; después de pagar, nunca.
9. **Solo a quien escribió al menos DOS mensajes** (Camilo, 04/10): la que
   escribe uno y desaparece no se persigue, salvo que ese único mensaje ya sea
   una compra («quiero hacer un pedido»: `vale_la_pena`).

Esto es SOLO de los recordatorios: no cambia nada del flujo de la charla.

Funciones puras: nada de red ni de base. El worker
(`app/workers/recordatorios.py`) las aplica cada pocos minutos.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta, timezone

#: La hora de Camilo (sin `ZoneInfo`: Windows no trae la base de zonas).
COLOMBIA = timezone(timedelta(hours=-5), "America/Bogota")

#: Los ÚNICOS dos momentos del día en que salen (Camilo, 05/10: «dejar solo 2
#: horas al día… uno tipo 9 a. m. y el otro tipo 5 p. m.»). Hora de Colombia.
HORARIOS = (time(9, 0), time(17, 0))
#: La ventana de WhatsApp es de 24 h desde su último mensaje; se deja media hora
#: de margen para que el mensaje alcance a salir (la vuelta de 5 min, la outbox).
VENTANA = timedelta(hours=23, minutes=30)
#: El primero va en el primer horario que quede al menos esto después de su
#: último mensaje: la que escribe a las 8 a. m. recibe el de las 5 p. m. (no el
#: de las 9, una hora después); la de las 4 p. m., el de las 9 a. m. siguientes.
PRIMERO_DESPUES_DE = timedelta(hours=8)
#: Si con eso no cabe ninguno en la ventana (escribió entre 9:00 y 9:30: las
#: 9 a. m. siguientes ya quedan por fuera), el último que quepa con esto.
MINIMO_DESDE_ELLA = timedelta(hours=3)
#: Entre el primero y el segundo, por lo menos esto.
ENTRE_LOS_DOS = timedelta(hours=5)
#: Lo mínimo después de lo último que dijo el bot.
MINIMO_DESPUES_DEL_BOT = timedelta(hours=1)
#: Si el servidor estuvo caído y se pasó un horario, hasta cuándo vale todavía.
GRACIA = timedelta(hours=1)

#: Las etapas en las que se le recuerda (cada una con su texto, `PRIMEROS`).
ETAPAS = frozenset(
    {
        "consulta",
        "talla",
        "talla_guia",
        "cantidad",
        "colores",
        "grabado",
        "nombre",
        "otro_anillo",
        "resumen",
        "abono",
    }
) | frozenset(
    # Lo que dijo que manda DESPUÉS («la medida te la confirmo en la tarde»,
    # 09/10): UN recordatorio sobre eso, y ya.
    {
        "despues_talla",
        "despues_cantidad",
        "despues_colores",
        "despues_grabado",
        "despues_nombre",
    }
)
#: Qué cosa del pedido es cada etapa «despues_…» (y al revés).
DESPUES: dict[str, str] = {
    "talla": "despues_talla",
    "cantidad de huellitas": "despues_cantidad",
    "colores": "despues_colores",
    "grabado": "despues_grabado",
    "nombre completo": "despues_nombre",
}
QUE_DE_DESPUES = {v: k for k, v in DESPUES.items()}

#: Los días que tarda el taller (el más largo): para «lo tendrías el …».
DIAS_DE_TALLER = 15


# ---------------------------------------------------------------------------
# Dónde se quedó
# ---------------------------------------------------------------------------


def etapa(borrador, estado_pedido: str = "") -> str | None:
    """Qué le falta a ELLA (una de `ETAPAS`), o None si no le toca a ella.

    `borrador` es el `Borrador` de la charla (o None si solo hubo apertura).
    """
    from app.domain.asesora import ANILLO_SIGUIENTE, TALLA_DE_LIA

    if estado_pedido:
        # Con pedido: solo el abono es de ella. Lo demás (pago por verificar,
        # taller, envío) es de Lía, o ya pagó.
        if estado_pedido == "ESPERANDO_ANTICIPO" and not borrador.abono_reportado:
            return "abono"
        return None
    if borrador is not None and borrador.sin_recordatorios:
        return None  # no le interesa: ni uno más (10/10)
    if borrador is None or borrador.turnos <= 1:
        return "consulta"
    if borrador.abono_reportado or borrador.pagado_sin_pedido:
        return None  # pagó: lo que falta lo pregunta el bot cuando ella vuelva
    # Lo que dijo que manda después: UN recordatorio sobre eso y ya; si ya lo
    # tuvo, ninguno más hasta que ella vuelva a escribir (Camilo, 09/10).
    from app.domain.asesora import lo_que_le_falta

    le_falta = lo_que_le_falta(borrador)
    for que, cual in DESPUES.items():
        if que in borrador.lo_manda_despues and que in le_falta:
            return None if que in borrador.recordado_despues else cual
    falta = borrador.falta_para_abono()
    if not falta:
        return "resumen"
    primero = falta[0]
    if primero == TALLA_DE_LIA:
        return None  # la que tiene que hacer algo es Lía
    if primero.startswith(ANILLO_SIGUIENTE):
        return "otro_anillo"
    guia = "MOSTRAR_GUIA_TALLA" in borrador.mostrado_en
    # Si ya le llegó la guía, lo que le cuesta es MEDIR (aunque la cantidad
    # vaya antes en el orden: el bot la pregunta cuando ella vuelva). Caso
    # real del 04/10: «¿sabes tu talla?» -> «No» -> guía + «¿cuántas huellitas?».
    if primero == "talla" or (guia and "talla" in falta):
        return "talla_guia" if guia else "talla"
    return {
        "cantidad de huellitas": "cantidad",
        "colores": "colores",
        "grabado": "grabado",
        "nombre completo": "nombre",
    }.get(primero, "consulta")


def _plano(texto: str) -> str:
    t = unicodedata.normalize("NFKD", texto or "").lower()
    return "".join(c for c in t if not unicodedata.combining(c))


#: Que NO quiere, por pequeño que sea el desinterés (Camilo, 10/10). Real: «Es
#: que no me gusta la plata», «No no LOS voy a pedir porque te dije que no me
#: gusta la plata», «Menos pagaría 200 por un anillo en plata», «Que no estoy
#: interesada», «Miles de veces»: le llegaron DOS recordatorios. Ni uno más.
#: «No quiero grabado» es rechazar UNA pregunta, no la compra: no entra.
_NO_QUIERE = re.compile(
    r"|".join(
        (
            r"\bno\s+(?:gracias|me\s+interesa|por\s+ahora|estoy\s+interesad|estamos\s+interesad)",
            r"\bno\s+quiero\s*(?:$|[.!,]|nada|el\s+anillo|comprar|pedir|gracias|mas)",
            r"\bya\s+no\s+(?:l[oa]s?\s+)?(?:quiero|voy|me\s+interesa|necesito|lo\s+pido)"
            r"|\bya\s+no\s*(?:$|[^\w\s]|gracias)"
            r"|\bdeja\s+as[ií]\b|\bno\s+me\s+escrib|\bno\s+me\s+(?:molest|insist)",
            # «No no LOS voy a pedir»; «no voy a poder hoy» es posponer, no entra.
            r"\bno\s+(?:l[oa]s?\s+|me\s+l[oa]s?\s+)?(?:voy|vamos)\s+a\s+"
            r"(?:pedir|comprar|hacer|llevar|encargar|mandar)",
            # «La plata ADELANTADA» es dinero, no el metal (Nora, 13/10): eso es
            # miedo a abonar, no desinterés.
            r"\bno\s+me\s+gusta(?:n)?\s+(?:la\s+plata(?!\s+(?:adelantad|antes|por\s+adelant"
            r"|primero))|el\s+material|los\s+anillos|el\s+anillo|eso|nada|mucho)",
            r"\bsin\s+interes|\bdesinteres|\bno\s+me\s+llama",
            r"\b(?:muy|esta|es|demasiado|super|re)\s+car[oa]s?\b|\bno\s+me\s+alcanza\b"
            r"|\bno\s+tengo\s+(?:plata|dinero|presupuesto)\b",
            r"\bmenos\s+(?:pagaria|compraria|lo\s+compro|lo\s+pido)",
            r"\bsolo\s+(?:estaba|estoy|era)\s+(?:mirando|preguntando|averiguando|cotizando)"
            r"|\bpor\s+curiosidad\b|\bera\s+solo\s+para\s+saber",
            # «Estaba averiguando solamente» (12/10, real): el «solo» va al final.
            r"\b(?:estaba|estoy|era)\s+(?:mirando|preguntando|averiguando|cotizando)\s+"
            r"(?:solamente|nada\s+mas|no\s+mas|nomas)\b"
            r"|\bsolamente\s+(?:estaba\s+|estoy\s+)?(?:mirando|preguntando|averiguando"
            r"|cotizando)",
            r"\bdej(?:a|en|e)\s+de\s+(?:escribir|insistir|mandar)|\bno\s+insistas?\b"
            r"|\bmiles\s+de\s+veces\b|\bya\s+te\s+dije\b|\bte\s+dije\s+que\s+no\b",
            r"\bnunca\s+(?:lo\s+)?(?:voy|pedi|quise)",
            # «Lo voy a dejar pasar quizás para el próximo mes» (05/10) está en
            # `_PARA_OTRO_MES`: también cuenta para `no_quiere`, pero no es un
            # rechazo (`rechaza`), es un «después».
        )
    )
)
#: Lo que contesta la IA cuando ENTENDIÓ que no le interesa («disculpa por
#: insistir», «gracias por decírmelo», «no te escribiré más»): aunque ella lo
#: haya dicho con otras palabras, el bot ya lo leyó así (10/10).
_EL_BOT_ENTENDIO_QUE_NO = re.compile(
    r"disculpa\s+por\s+insistir|perdon\s+por\s+insistir|no\s+te\s+(?:escribire|escribo|molesto"
    r"|vuelvo\s+a\s+escribir)\s+mas|gracias\s+por\s+(?:decirmelo|aclararmelo|avisarme"
    r"|contarme)|no\s+estas\s+interesad|no\s+te\s+convence|si\s+no\s+te\s+gusta\s+ese\s+material",
    re.I,
)


def el_bot_entendio_que_no(texto_del_bot: str) -> bool:
    return bool(_EL_BOT_ENTENDIO_QUE_NO.search(_plano(texto_del_bot)))


#: Lo deja para otro mes: «el otro mes» y cómo se escribe de verdad (09/10):
#: «pal otro mez», «el mes q viene», «a fin de mes», «el mes entrante», «para
#: diciembre». Cuenta como NO QUIERE (ningún recordatorio) y como POSPONE (el
#: bot agradece y cierra, sin preguntas ni promesas).
_PARA_OTRO_MES = re.compile(
    r"|".join(
        (
            r"\b(proximo|siguiente|otro|otra|proxima)\s+(mes|mez|ano|año|quincena)\b",
            r"\bmes\s+(que|q|k|ke)\s+viene\b",
            r"\bmes\s+entrante\b",
            r"\bfin(al)?(es)?\s+de(l)?\s+mes\b",
            r"\bpara\s+(enero|febrero|marzo|abril|mayo|junio|julio|agosto"
            r"|septiembre|setiembre|octubre|noviembre|diciembre)\b",
            r"\bdejar(lo)?\s+pasar\b|\blo\s+dejo\s+pasar\b|\bpara\s+despues\b",
        )
    )
)
_PIDE_TIEMPO = re.compile(
    r"\blo\s+pienso\b|\bte\s+aviso\b|\bte\s+escribo\b|\bmas\s+tarde\b|\bluego\b"
    r"|\bdespues\b|\bvoy\s+a\s+pensar|\blo\s+hablo\b|\bte\s+confirmo\b|\botro\s+dia\b"
    r"|\bmanana\b|\bcuando\s+(me\s+)?paguen\b|\bquincena\b|\bmas\s+adelante\b"
    r"|\bno\s+me\s+queda\s+facil\b|\bahor(a|ita)\s+no\b|\ben\s+un\s+rat(o|ico|ito)\b",
)
#: Lo deja para después, dicho sin dudas (para que el bot no insista en la
#: charla). Más estricto que `_PIDE_TIEMPO`: «te confirmo que es toda rosa» no
#: pospone nada.
_POSPONE = re.compile(
    r"\bmanana\b|\bluego\b|\bdespues\b|\bmas\s+tarde\b|\botro\s+dia\b|\bmas\s+adelante\b"
    r"|\bcuando\s+(me\s+)?paguen\b|\bquincena\b|\blo\s+pienso\b|\bvoy\s+a\s+pensar"
    r"|\bno\s+me\s+queda\s+facil\b|\bahor(a|ita)\s+no\b|\ben\s+un\s+rat(o|ico|ito)\b"
    # Ella retoma cuando tenga algo (13/10, auditoría): «cuando tenga una talla los
    # contactaré de nuevo», «apenas lo haga le escribo y elijo el modelo».
    r"|\b(?:cuando|apenas|en\s+cuanto)\b[^.?!]{0,40}?\b(?:te|le|les|los|las)\s+"
    r"(?:escrib\w*|contact\w*|aviso|avisare|hablo)\b",
)

#: Solo agradece o da el visto bueno, sin pedir nada (13/10, auditoría): «Gracias
#: por la información», «Vale gracias», «Gracias». Se le contesta «¡Con gusto!» y
#: ya: pegarle «¿De cuántas huellitas lo quieres?» es insistir.
_SOLO_AGRADECE = re.compile(
    r"^(?:(?:ok|okey|okay|vale|listo|dale|bueno|perfecto|si|super|genial|ah|ay)\W*)*"
    r"(?:muchas|mil|muchisimas)?\s*gracias\b"
    r"(?:\W*(?:por\s+(?:la\s+info\w*|todo|tu\s+ayuda|su\s+ayuda|responder|la\s+atencion)"
    r"|a\s+ti|a\s+usted|muy\s+amable|de\s+verdad|que\s+amable)\b)*\W*$"
)


#: Un primer mensaje que ya es una compra («quiero hacer un pedido», «quiero el
#: de 2 huellitas», «me lo encargas»): con UN solo mensaje, solo estos valen
#: un recordatorio (Camilo, 04/10: «los de un solo mensaje que desaparecen no
#: son relevantes, a menos de que genuinamente estés casi seguro»).
_QUIERE_COMPRAR = re.compile(
    r"\b(quiero|quisiera|necesito|me\s+gustaria)\s+(hacer\s+(un|el)\s+pedido|pedir"
    r"|encargar|comprar|mandar\s+a\s+hacer|uno|una|el\s+de\s+\w+\s+huellita|un\s+anillo"
    r"|el\s+anillo|la\s+cadena|una\s+cadena)\b"
    r"|\b(como|donde)\s+(hago|hacer)\s+(el|un|mi)\s+pedido\b|\bme\s+lo\s+(hacen|encargo)\b",
)


def vale_la_pena(mensajes_de_ella: int, primer_mensaje: str) -> bool:
    """¿Escribió al menos DOS mensajes, o el único ya es una compra?"""
    return mensajes_de_ella >= 2 or bool(_QUIERE_COMPRAR.search(_plano(primer_mensaje)))


def quiere_comprar(texto_de_ella: str) -> bool:
    """«Quiero hacer un pedido», «me lo encargas»: vuelve el interés."""
    return bool(_QUIERE_COMPRAR.search(_plano(texto_de_ella)))


def no_quiere(texto_de_ella: str) -> bool:
    plano = _plano(texto_de_ella)
    return bool(_NO_QUIERE.search(plano) or _PARA_OTRO_MES.search(plano))


def rechaza(texto_de_ella: str) -> bool:
    """No lo quiere («no me gusta la plata», «muy caro», «solo miraba»). Dejarlo
    para otro mes NO es esto: es un «después» (13/10)."""
    return bool(_NO_QUIERE.search(_plano(texto_de_ella)))


def pide_tiempo(texto_de_ella: str) -> bool:
    return bool(_PIDE_TIEMPO.search(_plano(texto_de_ella)))


def pospone(texto_de_ella: str) -> bool:
    """«Mañana le consigno», «ahora no me queda fácil», «el otro mes»: lo deja
    para después. El bot agradece y cierra, sin preguntas (09/10)."""
    plano = _plano(texto_de_ella)
    return bool(_POSPONE.search(plano) or _PARA_OTRO_MES.search(plano))


def solo_agradece(texto_de_ella: str) -> bool:
    """«Gracias», «Vale gracias», «Gracias por la información»: nada más."""
    return bool(_SOLO_AGRADECE.search(_plano(texto_de_ella).strip()))


#: Ella PIDE que le escriban después («escríbeme el otro mes», «me recuerdas en
#: la quincena»). Solo entonces se le puede decir «te escribo»; si no lo pide,
#: el bot no promete nada (Camilo, 09/10).
_PIDE_QUE_LE_ESCRIBAN = re.compile(
    r"\b(escribe|escribame|escribeme|escribime|me\s+escrib(es|e|en|is)"
    r"|recuerdame|recuerdeme|me\s+recuerd(as|a|an)|me\s+(avisas|avisa|avisan)"
    r"|me\s+contact(as|a|an)|contactame|me\s+buscas|me\s+hablas)\b"
)


def pide_que_le_escriban(texto_de_ella: str) -> bool:
    return bool(_PIDE_QUE_LE_ESCRIBAN.search(_plano(texto_de_ella)))


# ---------------------------------------------------------------------------
# Cuándo
# ---------------------------------------------------------------------------


def _en_colombia(momento: datetime) -> datetime:
    if momento.tzinfo is None:
        momento = momento.replace(tzinfo=UTC)
    return momento.astimezone(COLOMBIA)


def es_un_horario(momento: datetime) -> bool:
    """¿Es las 9 a. m. o las 5 p. m. en punto (hora de Colombia)?"""
    m = _en_colombia(momento)
    return m.time().replace(second=0, microsecond=0) in HORARIOS


def horarios_entre(desde: datetime, hasta: datetime) -> list[datetime]:
    """Las 9 a. m. y 5 p. m. que caen después de `desde` y hasta `hasta`."""
    d, h = _en_colombia(desde), _en_colombia(hasta)
    salida = []
    dia = d.date()
    while dia <= h.date():
        for hora in HORARIOS:
            momento = datetime.combine(dia, hora, COLOMBIA)
            if d < momento <= h:
                salida.append(momento)
        dia += timedelta(days=1)
    return salida


def turnos(ultimo_de_ella: datetime, ultimo_del_bot: datetime) -> list[datetime]:
    """Los horarios en que se le escribe por este silencio, dentro de sus 24 h:
    el primero y, si cabe otro, el segundo. Lista vacía: ninguno cabe."""
    piso = max(ultimo_de_ella, ultimo_del_bot + MINIMO_DESPUES_DEL_BOT)
    todos = horarios_entre(piso, ultimo_de_ella + VENTANA)
    lejos = [m for m in todos if m - ultimo_de_ella >= PRIMERO_DESPUES_DE]
    if lejos:
        primero = lejos[0]
    else:
        cerca = [m for m in todos if m - ultimo_de_ella >= MINIMO_DESDE_ELLA]
        if not cerca:
            return []
        primero = cerca[-1]
    segundo = next((m for m in todos if m - primero >= ENTRE_LOS_DOS), None)
    return [primero, segundo] if segundo else [primero]


@dataclass(frozen=True)
class Plan:
    """Lo que toca: el recordatorio `numero` a partir de `cuando`. El 3 va con
    plantilla (la ventana ya se cerró)."""

    numero: int
    cuando: datetime

    @property
    def plantilla(self) -> bool:
        return self.numero == 3


#: El tercero, ya fuera de la ventana: con plantilla de marketing aprobada
#: (~US$0,0125 en Colombia), a los 3 días, solo para quien ya invirtió en su
#: diseño. Para un anillo de $200.000–$300.000, con que 1 de cada ~400 cierre,
#: se paga solo (Camilo, 04/10: «haz lo que mayor costo-beneficio tenga»).
DIAS_PARA_EL_TERCERO = 3
#: Las etapas en las que ya invirtió algo de ella (no la que solo vio precios
#: ni la que nunca contestó lo de la talla).
CON_PLANTILLA = ETAPAS - {"consulta", "talla"} - set(QUE_DE_DESPUES)


def hora_del_tercero(ultimo_de_ella: datetime) -> datetime:
    """A los 3 días, en el horario más cercano a la hora en que ella escribió
    (cuando suele tener tiempo): antes de la 1 p. m., las 9 a. m.; si no, las
    5 p. m."""
    suyo = _en_colombia(ultimo_de_ella)
    hora = HORARIOS[0] if suyo.time() < time(13, 0) else HORARIOS[1]
    return datetime.combine(
        suyo.date() + timedelta(days=DIAS_PARA_EL_TERCERO), hora, COLOMBIA
    )


def siguiente(
    *,
    etapa_de_ella: str,
    ultimo_de_ella: datetime,
    ultimo_del_bot: datetime,
    enviados: dict[int, datetime],
    texto_de_ella: str = "",
    ahora: datetime,
    con_plantilla: bool = True,
) -> Plan | None:
    """El próximo recordatorio de este silencio, o None si ya no toca ninguno.

    `enviados`: {número: cuándo} de los que ya salieron por este silencio.
    """
    if etapa_de_ella not in ETAPAS or no_quiere(texto_de_ella):
        return None
    # Si pidió tiempo, o dijo que lo manda después: UNO solo.
    tiempo = pide_tiempo(texto_de_ella) or etapa_de_ella in QUE_DE_DESPUES
    horarios = turnos(ultimo_de_ella, ultimo_del_bot)
    # (número, cuándo): el primero y el segundo. Si pidió tiempo («mañana le
    # consigno», «lo pienso»), UNO solo en la ventana: el primer horario
    # (Camilo, 07/10: escribió a las 9 p. m. -> a las 9 a. m.), y después, si
    # aplica, el de los 3 días.
    candidatos = list(enumerate(horarios[:1] if tiempo else horarios, 1))
    for numero, cuando in candidatos:
        if numero in enviados or (2 in enviados and numero == 1):
            continue
        if 1 in enviados and cuando - enviados[1] < ENTRE_LOS_DOS:
            continue  # el primero salió tarde (servidor caído): no se pegan
        if ahora < cuando + GRACIA:
            return Plan(numero, cuando)
    if con_plantilla and etapa_de_ella in CON_PLANTILLA and 3 not in enviados:
        tercero = hora_del_tercero(ultimo_de_ella)
        if ahora < tercero + GRACIA:
            return Plan(3, tercero)
    return None


# ---------------------------------------------------------------------------
# Qué se le dice
# ---------------------------------------------------------------------------


def primer_nombre(nombre: str) -> str:
    """«MARIA JOSE cardona» -> «Maria»; vacío si no parece un nombre."""
    partes = [p for p in re.split(r"\s+", (nombre or "").strip()) if p.isalpha()]
    return partes[0].capitalize() if partes else ""


_MESES = (
    "enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
    "septiembre", "octubre", "noviembre", "diciembre",
)  # fmt: skip


def listo_el(hoy: date) -> str:
    """«el 20 de octubre»: cuándo lo tendría si lo deja listo hoy."""
    d = hoy + timedelta(days=DIAS_DE_TALLER)
    return f"el {d.day} de {_MESES[d.month - 1]}"


#: El saludo va según la hora del envío (Camilo, 09/10: «más dulces, saludar»;
#: 10/10: sencillo, «buen día, ¿cómo estás?»). Es la ÚNICA
#: pregunta del mensaje: lo que sigue es un recordatorio suave, sin otra
#: pregunta encima (una pregunta a la vez).
#: Camilo, 10/10: «buenos días, ¿cómo amaneciste?» no; mejor sencillo: «buen
#: día, ¿cómo estás?».
SALUDO_MANANA = "¡Buen día{nombre}! 🌷 ¿Cómo estás?"
SALUDO_TARDE = "¡Buenas tardes{nombre}! 🌷 ¿Cómo estás?"
SALUDO_NOCHE = "¡Buenas noches{nombre}! 🌙 ¿Cómo estás?"


def saludo(nombre: str, hora: int) -> str:
    """El saludo según la hora de Colombia en que sale (9 a. m. o 5 p. m.)."""
    con_nombre = f", {nombre}" if nombre else ""
    if hora < 12:
        plantilla = SALUDO_MANANA
    elif hora < 19:
        plantilla = SALUDO_TARDE
    else:
        plantilla = SALUDO_NOCHE
    return plantilla.format(nombre=con_nombre)


#: El primero: útil, corto, cálido y sin presionar. Sin pregunta: la pregunta
#: es la del saludo. Lo que le falta, dicho como invitación («cuando puedas»).
PRIMEROS: dict[str, str] = {
    "consulta": "Quedé pendiente por si te quedó alguna duda de tu {pieza} 🐾 Con "
    "gusto te ayudo a diseñarlo cuando quieras 💍",
    "talla": "Cuando tengas un ratico, me cuentas tu talla 💍 Y si no la sabes, te "
    "paso una guía facilita para medirla en casa con un anillo y una regla 📏",
    "talla_guia": "Cuando puedas medir tu anillo, me mandas la foto sobre la regla "
    "y yo te digo la talla 📏💍",
    "cantidad": "Cuando quieras, me cuentas de cuántas huellitas lo quieres: puede "
    "ser de 1, 2 o 3 🐾",
    "colores": "Cuando tengas un momentico, me cuentas los colores de la huellita y "
    "te muestro cómo queda 🎨🐾",
    "grabado": "Cuando quieras, me cuentas qué nombre te gustaría grabar en el aro: "
    "el de tu peludito, una fecha especial o lo que tú quieras 🫶",
    "nombre": "Ya casi lo tenemos listo 🙌 Solo me falta tu nombre completo para el "
    "pedido 💗",
    "otro_anillo": "Tengo guardado todo lo que escogiste, y cuando quieras seguimos "
    "con el otro anillo 💍🐾",
    "resumen": "Quedo pendiente de que revises el resumen de tu {pieza} 🐾 Si todo "
    "está bien, me dices y te paso los datos para el abono 🫶",
    # Lo que dijo que manda después: le recuerda ESO, una vez (09/10).
    "despues_talla": "Quedé pendiente de la talla que me ibas a confirmar 📏 Cuando la "
    "tengas, me la escribes por aquí y seguimos con tu {pieza} 💍🐾",
    "despues_cantidad": "Quedé pendiente de cuántas huellitas ibas a querer 🐾 Cuando "
    "lo tengas claro, me cuentas y seguimos 💍",
    "despues_colores": "Quedé pendiente de los colores que ibas a escoger 🎨 Cuando "
    "te decidas, me cuentas y te muestro cómo queda 🐾",
    "despues_grabado": "Quedé pendiente del nombre que ibas a grabar en el aro 🫶 "
    "Cuando lo tengas, me cuentas y seguimos 🐾",
    "despues_nombre": "Quedé pendiente de tu nombre completo para el pedido 💗 Cuando "
    "puedas, me lo compartes y seguimos 🐾",
    "abono": "Tu {pieza} con la huellita de tu peludito sigue guardadito tal como lo "
    "dejamos 🐾 Cuando hagas el abono, me mandas el comprobante y entra de una al "
    "taller 💍 Cualquier cosita, aquí estoy 💗",
}
#: El último: le da una razón para hacerlo hoy (la fecha) y la deja tranquila.
ULTIMO = (
    "Te cuento que si lo dejamos listo hoy, tendrías tu {pieza} más o menos "
    "{fecha} ✨ Sin afán: cuando quieras seguimos, aquí estoy 💗🐾"
)


#: El tercero (plantilla de MARKETING en Meta, aprobada aparte: la crea
#: `vb recordatorios --plantilla`). {{1}} su nombre (o «de nuevo»), {{2}} la pieza.
PLANTILLA = "retomar_diseno"
CUERPO_DE_LA_PLANTILLA = (
    "Hola {{1}} 💜 Soy Lía, de Luna Joyas. Lo que escogiste para tu {{2}} con "
    "la huellita de tu peludito quedó guardado tal como lo dejaste 🐾 ¿Quieres que "
    "lo terminemos? Te ayudo en un momento 🫶"
)
#: Los botones de respuesta rápida: lo que ella toque le llega al bot como texto
#: («Más adelante» cuenta como pedir tiempo: no se le insiste).
BOTONES_DE_LA_PLANTILLA = ("Sí, sigamos", "Más adelante")


def parametros_de_la_plantilla(nombre: str, pieza: str) -> dict[str, str]:
    return {"1": nombre or "de nuevo", "2": pieza}


def texto(
    numero: int,
    etapa_de_ella: str,
    *,
    nombre: str,
    pieza: str,
    hoy: date,
    hora: int = 9,
) -> str:
    """El mensaje, con su nombre si se sabe. `pieza`: «anillo», «cadena»…
    `hora`: la de Colombia a la que sale (el saludo cambia con ella)."""
    if numero == 3:
        valores = parametros_de_la_plantilla(nombre, pieza)
        return CUERPO_DE_LA_PLANTILLA.replace("{{1}}", valores["1"]).replace(
            "{{2}}", valores["2"]
        )
    if numero == 1:
        cuerpo = PRIMEROS[etapa_de_ella].format(pieza=pieza)
    else:
        cuerpo = ULTIMO.format(pieza=pieza, fecha=listo_el(hoy))
    return f"{saludo(nombre, hora)}\n\n{cuerpo}"


def pieza_de(borrador) -> str:
    """«anillo», «cadena», «pedido» (varias piezas)."""
    if borrador is None:
        return "anillo"
    vistas = borrador.vistas()
    if len(vistas) > 1:
        return "pedido"
    return "cadena" if vistas[0].es_cadena else "anillo"
