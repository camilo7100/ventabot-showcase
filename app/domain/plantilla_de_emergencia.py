"""La plantilla de emergencia: escribirle a quien se quedó sin respuesta (16/10).

El 14 y 15/10 un cambio de Meta dejó a las clientas de la pauta sin respuesta
dos días. Pasadas 24 h desde su último mensaje, WhatsApp solo deja escribirle
con una plantilla aprobada; esta es para eso, y SOLO para eso: no es un
recordatorio ni publicidad.

Tres maneras de que salga (si ella contesta, la atiende el bot):
- Sola: a cada mensaje ATRASADO que llega (escrito hace más de 24 h), en
  cuanto Meta la tenga aprobada; de noche, a las 8 a. m. (Camilo, 16/10).
- `#retomar` en la conversación de Chatwoot.
- `vb retomar --enviar`: a todas las atrasadas sin respuesta de una vez.
Si Meta la rechaza, ntfy avisa («un mensaje no salió»). Se crea en Meta con
`vb recordatorios --plantillas --crear` (las de `#asesora` también).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

NOMBRE = "retomar_conversacion"

#: Lo que se escribe en Chatwoot para mandarla.
COMANDO = "#retomar"

CUERPO = (
    "Hola 😊 Te escribimos de Luna Joyas. Hace poco nos escribiste por aquí "
    "y, por una falla técnica, tu mensaje no nos llegó a tiempo. ¡Qué pena "
    "contigo! Si aún quieres tu anillo con la huellita de tu peludito 🐾, con "
    "gusto te atendemos ahora mismo."
)

#: La de respaldo (16/10: la primera llevaba 20 h «en revisión» en Meta, y
#: las de los recordatorios se aprobaron en horas). Dice lo mismo con otras
#: palabras; va la que Meta apruebe primero.
RESPALDO = "retomar_conversacion_2"
CUERPO_RESPALDO = (
    "Hola 😊 Te habla Luna Joyas. Vimos que nos escribiste hace unos días y "
    "no alcanzamos a responderte, ¡mil disculpas! ¿Todavía te interesa tu anillo "
    "con la huellita de tu peludito? 🐾 Con gusto te atendemos."
)

#: Todas, en orden de preferencia: nombre -> lo que dice.
PLANTILLAS = {NOMBRE: CUERPO, RESPALDO: CUERPO_RESPALDO}

#: Sin emoji: Meta no los acepta en los botones de respuesta rápida.
BOTONES = ("Sí, sigamos", "Ahora no")


# ---------------------------------------------------------------------------
# `#asesora` (Camilo, 19/10): ella pidió una PERSONA y pasaron las 24 h
# ---------------------------------------------------------------------------
# Laura pidió un asesor el sábado en la noche; el domingo no trabaja nadie y el
# lunes el «Buen día Laura» de Lía se quedó en la outbox: la ventana ya estaba
# cerrada. `#retomar` no sirve ahí (dice «por una falla técnica» y le devuelve
# la charla al bot). Esta dice que ya le escribe una persona, y la conversación
# SIGUE CON LA PERSONA: lo que ella conteste lo atiende Lía, no el bot.

NOMBRE_ASESORA = "asesora_te_atiende"
COMANDO_ASESORA = "#asesora"
#: {{1}} = su primer nombre («de nuevo» si no se sabe).
CUERPO_ASESORA = (
    "Hola {{1}} 🌷 Habla Lía, de Luna Joyas. Ya te escribe una persona de "
    "verdad y con gusto te ayudo con tu anillo 🐾 Gracias por tu paciencia. "
    "¿En qué puedo ayudarte?"
)
EJEMPLO_ASESORA = ("Laura",)
#: La de respaldo, sin variables: va la que Meta apruebe primero.
RESPALDO_ASESORA = "asesora_te_atiende_2"
CUERPO_RESPALDO_ASESORA = (
    "Hola 🌷 Habla Lía, de Luna Joyas. Ya te escribe una persona de verdad y "
    "con gusto te ayudo con tu anillo 🐾 Disculpa la espera. ¿En qué puedo "
    "ayudarte?"
)
#: La tercera (19/10, 7 p. m.: las dos primeras llevaban 5 h «en revisión»):
#: la más corta, sin variables y SIN botones, para que Meta la apruebe pronto.
TERCERA_ASESORA = "asesora_te_atiende_3"
CUERPO_TERCERA_ASESORA = (
    "Hola, habla Lía de Luna Joyas 🌷 Ya te atiende una persona real. "
    "¿En qué puedo ayudarte?"
)
#: En orden de preferencia: sale la primera que Meta haya aprobado.
PLANTILLAS_ASESORA = {
    NOMBRE_ASESORA: CUERPO_ASESORA,
    RESPALDO_ASESORA: CUERPO_RESPALDO_ASESORA,
    TERCERA_ASESORA: CUERPO_TERCERA_ASESORA,
}
BOTONES_ASESORA = ("Quiero asesoría", "Tengo una duda")
#: Las que van sin botones.
SIN_BOTONES = frozenset({TERCERA_ASESORA})
#: Si no se sabe cómo se llama: «Hola de nuevo 🌷…».
SIN_NOMBRE = "de nuevo"


def es_el_comando_asesora(texto: str) -> bool:
    return texto.strip().lower() == COMANDO_ASESORA


def primer_nombre(nombre: str | None) -> str:
    """«laura garcía» -> «Laura». Un teléfono o nada -> «de nuevo»."""
    palabra = (nombre or "").strip().split(" ")[0] if (nombre or "").strip() else ""
    if not palabra.isalpha():
        return SIN_NOMBRE
    return palabra[:1].upper() + palabra[1:].lower()


def la_de_asesora(plantilla: str, nombre: str | None) -> tuple[str, dict]:
    """(lo que ella lee, los parámetros para Meta) de la plantilla escogida."""
    cuerpo = PLANTILLAS_ASESORA[plantilla]
    if "{{1}}" not in cuerpo:
        return cuerpo, {}
    quien = primer_nombre(nombre)
    return cuerpo.replace("{{1}}", quien), {"1": quien}


#: Solo de día, hora de Colombia (UTC-5, sin cambio de horario): nadie recibe
#: una disculpa de madrugada (Camilo, 16/10).
DESDE_LAS, HASTA_LAS = 8, 20
_COLOMBIA = timedelta(hours=-5)


def es_el_comando(texto: str) -> bool:
    return texto.strip().lower() == COMANDO


def cuando_mandarla(ahora: datetime) -> datetime | None:
    """None si se puede mandar ya; si no, las próximas 8 a. m. de Colombia (UTC)."""
    local = ahora.astimezone(UTC) + _COLOMBIA
    if DESDE_LAS <= local.hour < HASTA_LAS:
        return None
    dia = local.date() if local.hour < DESDE_LAS else local.date() + timedelta(days=1)
    return datetime(dia.year, dia.month, dia.day, DESDE_LAS, tzinfo=UTC) - _COLOMBIA


def clave(conv: str, sale: datetime) -> str:
    """La clave en la outbox: una disculpa por clienta y por día de Colombia.

    Antes llevaba el id del mensaje atrasado, y si Meta entregaba tres suyos
    atrasados le llegaban tres disculpas. El bot solo y `vb retomar` usan esta
    misma: entre los dos, una sola.
    """
    dia = (sale.astimezone(UTC) + _COLOMBIA).date().isoformat()
    return f"retomar:{conv}:{dia}"
