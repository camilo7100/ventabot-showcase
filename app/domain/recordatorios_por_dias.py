"""Los recordatorios POR DÍAS (13/10): a quién, qué, con qué foto y cuándo.

════════════════════════════════════════════════════════════════════════════
POR QUÉ
════════════════════════════════════════════════════════════════════════════
Camilo, 13/10, con los datos de marketing: «reactiva los recordatorios
personalizados a los días que tú decidas, para los clientes que pasan de cierto
punto, con un mensaje personalizado». Los de antes (9 a. m. y 5 p. m., dentro de
las 24 h) eran preguntas de trámite («¿Pudiste medir tu anillo?»): 48 enviados,
5 respuestas. 47 de 70 que llegaron por anuncio mandaron un solo mensaje y no
recibieron ninguno. El freno real es el precio y la talla.

Ahora cada uno lleva una FOTO (su anillo dibujado, o un anillo real con el
nombre grabado), su nombre y el de su peludito si se saben, y tres botones:
«💍 Quiero separarlo» · «Tengo una duda» · «Más adelante». Y la talla no frena:
se puede separar con el abono y mandarla después (Camilo, 13/10).

════════════════════════════════════════════════════════════════════════════
LOS SEGMENTOS Y EL CALENDARIO (días desde su último mensaje)
════════════════════════════════════════════════════════════════════════════
- S1 · vio la presentación y no volvió a escribir (un solo mensaje): día 1 y 4.
- S2 · contestó pero se frenó en la talla, la guía o la cantidad: día 1, 3 y 7.
- S3 · caliente: escogió colores, dio la talla o vio su diseño, sin pedido:
  día 1, 3 y 6.
- S4 · pedido creado, falta el abono: día 1, 3 y 7.

El día 1 va dentro de sus 24 h (texto libre, ~20 h después); los otros, con
plantilla aprobada por Meta. Siempre entre las 10 a. m. y las 7 p. m. (hora
de Colombia). Máximo 3 por cada silencio. Si pidió tiempo o dijo que algo lo
manda después, solo el primero y el último (no se le acosa).

Lo que NO cambia (`app.domain.recordatorios`): solo antes del abono, nunca si
dijo que no o si muestra cualquier desinterés (y antes de cada uno la IA lee la
charla), nunca si la atiende una persona o está escalada, nunca a un número de
prueba. Funciones puras: el worker (`app/workers/recordatorios.py`) las aplica.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta

from app.domain.recordatorios import (
    COLOMBIA,
    GRACIA,
    MINIMO_DESDE_ELLA,
    MINIMO_DESPUES_DEL_BOT,
    QUE_DE_DESPUES,
    VENTANA,
    no_quiere,
    pide_tiempo,
)

#: La franja del día en que se escribe (Colombia).
DESDE = time(10, 0)
HASTA = time(19, 0)
#: El primero, ~20 h después de su último mensaje (dentro de sus 24 h).
DIA_1 = timedelta(hours=20)

#: Qué días le toca a cada segmento (el 1 es el de las 24 h).
CALENDARIO: dict[str, tuple[int, ...]] = {
    "S1": (1, 4),
    "S2": (1, 3, 7),
    "S3": (1, 3, 6),
    "S4": (1, 3, 7),
}
NOMBRES_DE_LOS_SEGMENTOS = {
    "S1": "vio los precios y no volvió",
    "S2": "se frenó en la talla o la cantidad",
    "S3": "caliente: ya escogió algo",
    "S4": "pedido sin abono",
}

#: Los botones de TODOS (los de la plantilla y los de las 24 h). Lo que toque
#: le llega al bot como texto. Máximo 20 caracteres cada uno (WhatsApp).
BOTONES = ("💍 Quiero separarlo", "Tengo una duda", "Más adelante")

#: La foto cuando no hay un dibujo de SU anillo: el collage «Inspirado en tu
#: mascota» (seis anillos reales con nombres; 15/10, Camilo).
FOTO_DE_UN_ANILLO_GRABADO = "anillos_inspirado_en_tu_mascota"

#: La temporada de Navidad (Camilo, 14/10: «no me gusta el de Navidad desde ya,
#: es muy específico; guárdalo, por ahí en noviembre»): SOLO del 1 de noviembre
#: al 8 de diciembre (el último día para pedir y que llegue), el último
#: recordatorio va con `ultimo_navidad`. El resto del año, `ultimo_recordatorio`.
TEMPORADA_DE_NAVIDAD = (date(2026, 11, 1), date(2026, 12, 8))
ULTIMO_DIA_PARA_NAVIDAD = TEMPORADA_DE_NAVIDAD[1]


@dataclass(frozen=True)
class Plantilla:
    """Una plantilla de MARKETING de Meta: cabecera con IMAGEN, el cuerpo con
    {{1}}…, y los tres `BOTONES`. `ejemplo`: lo que Meta pide para revisarla."""

    nombre: str
    cuerpo: str
    ejemplo: tuple[str, ...]


#: Las cuatro (Camilo aprobó consolidar las siete del diseño en cuatro, 13/10),
#: y la del último en Navidad, guardada para su temporada (14/10).
#: {{1}} su nombre (o «de nuevo»); {{2}} su peludito (o «tu peludito»).
PLANTILLAS: dict[str, Plantilla] = {
    p.nombre: p
    for p in (
        Plantilla(
            "anillo_con_abono",
            "Hola {{1}} 💜 Muchas clientas nos escriben que su anillo es su forma de "
            "llevar a su peludito siempre con ellas 🐾 Para empezar el tuyo solo "
            "necesitas el abono de {{2}}, y la talla te ayudo a sacarla después 📏 "
            "¿Te lo diseño?",
            ("Laura", "$60.000"),
        ),
        Plantilla(
            "asi_quedaria",
            "Hola {{1}} 🐾 Así quedaría un anillo con la huellita de {{2}} 💍✨ Se hace "
            "a mano, en tu talla y con los colores que tú elijas. ¿Quieres que te lo "
            "reserve en el taller?",
            ("Laura", "Luna"),
        ),
        Plantilla(
            "cupo_en_el_taller",
            "Hola {{1}} 💜 Tengo cupo en el taller esta semana para el anillo de {{2}} "
            "💍 Con el abono de {{3}} empezamos y te lo entrego en 10 a 15 días ✨ ¿Lo "
            "pasamos al taller?",
            ("Laura", "Luna", "$60.000"),
        ),
        Plantilla(
            "ultimo_recordatorio",
            "Hola {{1}}, te escribo por última vez para no molestarte 🌷 Guardé el "
            "diseño del anillo de {{2}} tal como lo dejamos 💍 Cuando quieras "
            "retomarlo, aquí estoy. ¿Te lo dejo listo?",
            ("Laura", "Luna"),
        ),
        Plantilla(
            "ultimo_navidad",
            "Hola {{1}}, te escribo por última vez para no molestarte 🌷 Si quieres el "
            "anillo de {{2}} para Navidad, el último día para pedirlo es el {{3}} 🎄 "
            "¿Te lo dejo listo?",
            ("Laura", "Luna", "8 de diciembre"),
        ),
    )
}
#: Qué plantilla va en cada día de cada segmento (el día 1 es texto libre).
PLANTILLA_DEL_DIA: dict[tuple[str, int], str] = {
    ("S1", 4): "anillo_con_abono",
    ("S2", 3): "asi_quedaria",
    ("S2", 7): "ultimo_recordatorio",
    ("S3", 3): "cupo_en_el_taller",
    ("S3", 6): "ultimo_recordatorio",
    ("S4", 3): "cupo_en_el_taller",
    ("S4", 7): "ultimo_recordatorio",
}


# ---------------------------------------------------------------------------
# A quién
# ---------------------------------------------------------------------------


def eligio_algo(borrador) -> bool:
    """¿Ya puso algo de ella en su diseño? (colores, talla, o vio su anillo)."""
    if borrador is None:
        return False
    return bool(
        any(h.corazon or h.dedos for h in borrador.huellitas)
        or borrador.talla is not None
        or borrador.ultimas_vistas
    )


def segmento(etapa_de_ella: str | None, borrador, mensajes_de_ella: int) -> str | None:
    """S1…S4 según dónde se quedó (`recordatorios.etapa`), o None."""
    if etapa_de_ella is None:
        return None
    if etapa_de_ella == "abono":
        return "S4"
    if eligio_algo(borrador):
        return "S3"
    if mensajes_de_ella <= 1 or etapa_de_ella == "consulta":
        return "S1"
    return "S2"


# ---------------------------------------------------------------------------
# Cuándo
# ---------------------------------------------------------------------------


def _en_colombia(m: datetime) -> datetime:
    return (m if m.tzinfo else m.replace(tzinfo=UTC)).astimezone(COLOMBIA)


def _a_la_franja(m: datetime) -> datetime:
    """El primer momento ≥ m que cae entre las 10 a. m. y las 7 p. m."""
    m = _en_colombia(m)
    if m.time() < DESDE:
        return datetime.combine(m.date(), DESDE, COLOMBIA)
    if m.time() > HASTA:
        return datetime.combine(m.date() + timedelta(days=1), DESDE, COLOMBIA)
    return m


def dia_1(ultimo_de_ella: datetime, ultimo_del_bot: datetime) -> datetime | None:
    """El de las 24 h: ~20 h después, en la franja y dentro de su ventana. Si no
    cabe (escribió temprano), lo más tarde posible de la franja anterior al
    cierre, con al menos 3 h desde su mensaje. None si no cabe ninguno."""
    piso = max(ultimo_de_ella, ultimo_del_bot + MINIMO_DESPUES_DEL_BOT)
    limite = _en_colombia(ultimo_de_ella + VENTANA)
    deseado = _a_la_franja(max(ultimo_de_ella + DIA_1, piso))
    if deseado <= limite:
        return deseado
    # Lo más tarde de la franja antes del cierre de su ventana.
    if limite.time() > HASTA:
        tope = datetime.combine(limite.date(), HASTA, COLOMBIA)
    elif limite.time() >= DESDE:
        tope = limite
    else:
        tope = datetime.combine(limite.date() - timedelta(days=1), HASTA, COLOMBIA)
    if tope - ultimo_de_ella >= MINIMO_DESDE_ELLA and tope >= piso:
        return tope
    return None


def dia_n(ultimo_de_ella: datetime, n: int) -> datetime:
    """El día `n` después de su mensaje, a la hora en que ella suele escribir
    (dentro de la franja: antes de las 10, a las 10; después de las 7, a las 7)."""
    suyo = _en_colombia(ultimo_de_ella)
    hora = min(max(suyo.time().replace(second=0, microsecond=0), DESDE), HASTA)
    return datetime.combine(suyo.date() + timedelta(days=n), hora, COLOMBIA)


def _mas_adelante(texto: str) -> bool:
    """El botón «Más adelante» (o decirlo): no se le escribe más."""
    t = unicodedata.normalize("NFKD", (texto or "").lower())
    t = "".join(c for c in t if not unicodedata.combining(c))
    return bool(re.search(r"\bmas\s+adelante\b", t))


@dataclass(frozen=True)
class Paso:
    """El recordatorio `numero` (1, 2 o 3) de este silencio: el día `dia`."""

    numero: int
    dia: int
    cuando: datetime
    plantilla: str = ""  # vacío: texto libre (día 1)


def siguiente(
    *,
    segmento_de_ella: str,
    etapa_de_ella: str,
    ultimo_de_ella: datetime,
    ultimo_del_bot: datetime,
    enviados: dict[int, datetime],
    texto_de_ella: str = "",
    ahora: datetime,
    con_plantilla: bool = True,
) -> Paso | None:
    """El próximo de este silencio, o None. `enviados`: {número: cuándo}."""
    if segmento_de_ella not in CALENDARIO:
        return None
    if no_quiere(texto_de_ella) or _mas_adelante(texto_de_ella):
        return None
    dias = CALENDARIO[segmento_de_ella]
    # Pidió tiempo o dijo que algo lo manda después: el primero y el último.
    if pide_tiempo(texto_de_ella) or etapa_de_ella in QUE_DE_DESPUES:
        dias = (dias[0], dias[-1])
    for numero, dia in enumerate(dias, 1):
        if numero in enviados:
            continue
        if dia == 1:
            cuando = dia_1(ultimo_de_ella, ultimo_del_bot)
            plantilla = ""
        else:
            if not con_plantilla:
                return None
            cuando = dia_n(ultimo_de_ella, dia)
            plantilla = plantilla_para(segmento_de_ella, dia, cuando.date())
        if cuando is None:
            continue
        if ahora < cuando + GRACIA:
            return Paso(numero, dia, cuando, plantilla)
    return None


def plantilla_para(seg: str, dia: int, el_dia: date) -> str:
    nombre = PLANTILLA_DEL_DIA.get((seg, dia), "ultimo_recordatorio")
    desde, hasta = TEMPORADA_DE_NAVIDAD
    if nombre == "ultimo_recordatorio" and desde <= el_dia <= hasta:
        return "ultimo_navidad"
    return nombre


# ---------------------------------------------------------------------------
# Qué se le dice
# ---------------------------------------------------------------------------

_MESES = (
    "enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
    "septiembre", "octubre", "noviembre", "diciembre",
)  # fmt: skip


def mascota_de(borrador) -> str:
    """El nombre de su peludito si se sabe (lo que va grabado), o ""."""
    if borrador is None:
        return ""
    for h in borrador.huellitas:
        if (h.mascota or "").strip():
            return str(h.mascota).strip()
    if borrador.grabado:
        # «Toby ♡ Luna», «Toby y Luna», «Toby, Luna» -> «Toby».
        primero = re.split(r"\s*[♡&,]\s*|\s+y\s+", borrador.grabado[0])[0]
        primero = primero.strip(" ♡«»\"'")
        if primero and not any(c.isdigit() for c in primero) and len(primero) <= 20:
            return primero
    return ""


def _hola(nombre: str) -> str:
    return f"Hola {nombre} 🌷" if nombre else "Hola 🌷"


def texto_del_dia_1(
    seg: str,
    etapa_de_ella: str,
    *,
    nombre: str,
    mascota: str,
    abono: str,
    precios: str,
    vio_precios: bool,
    con_su_dibujo: bool,
    cuentas: str = "",
) -> str:
    """El de las 24 h (texto libre, va con foto y los tres botones)."""
    hola = _hola(nombre)
    de = mascota or "tu peludito"
    if seg == "S1":
        if not vio_precios:
            # Abrió con «¿cómo se llama tu peludito?» y no vio la lista de precios.
            return (
                f"{hola} Te cuento por si te sirve: el anillo con la huellita de tu "
                f"peludito cuesta {precios}, en plata Ley 925 y con su nombre grabado "
                "por dentro 💍🐾 ¿Te ayudo a diseñar el tuyo?"
            )
        return (
            f"{hola} Te dejo una foto de cómo quedan nuestros anillos con el nombre "
            "grabado 💍🐾 Cada uno se hace a mano, en tu talla y con los colores que tú "
            "elijas. Si quieres, te ayudo a diseñar el de tu peludito: ¿cómo se llama? "
            "🐶🐱"
        )
    if seg == "S2":
        if etapa_de_ella == "despues_talla":
            return (
                f"{hola} Quedé pendiente de la talla que me ibas a confirmar 📏 Si "
                f"prefieres, lo separas con el abono de {abono} y la talla me la "
                "mandas cuando la tengas 💍"
            )
        if etapa_de_ella in ("talla", "talla_guia"):
            return (
                f"{hola} Para la talla te lo pongo fácil 📏 Mándame una foto de "
                "cualquier anillo tuyo sobre una regla y yo te digo la medida. Y si "
                f"prefieres, lo separas con el abono de {abono} y la talla me la "
                "mandas después 💍"
            )
        return (
            f"{hola} ¿Te ayudo a escoger? 🐾 El de 1 huellita es el clásico, y el de 2 "
            "o 3 es para llevar a varios peluditos juntos. Se hace a mano, en tu "
            "talla y con los colores que tú elijas 💍"
        )
    if seg == "S3":
        if con_su_dibujo:
            return (
                f"{hola} Así quedaría el anillo de {de} con los colores que elegiste "
                "💍🐾 ¿Lo pasamos al taller?"
            )
        return (
            f"{hola} Te dejo una foto de cómo quedan con el nombre grabado 💍🐾 "
            f"¿Seguimos armando el anillo de {de}?"
        )
    # S4: el pedido está hecho, falta el abono.
    texto = (
        f"{hola} El anillo de {de} está listo para empezar 💍 Apenas recibamos el "
        f"abono de {abono}, entra al taller ✨"
    )
    return f"{texto}\n\n{cuentas}" if cuentas else texto


def parametros(
    plantilla: str, *, nombre: str, mascota: str, abono: str, pieza: str = "anillo"
) -> dict[str, str]:
    """Los {{1}}, {{2}}… de cada plantilla, EN ORDEN."""
    uno = nombre or "de nuevo"
    de = mascota or "tu peludito"
    if plantilla == "anillo_con_abono":
        return {"1": uno, "2": abono}
    if plantilla == "asi_quedaria":
        return {"1": uno, "2": de}
    if plantilla == "cupo_en_el_taller":
        return {"1": uno, "2": de, "3": abono}
    if plantilla == "ultimo_recordatorio":
        return {"1": uno, "2": de}
    if plantilla == "ultimo_navidad":
        d = ULTIMO_DIA_PARA_NAVIDAD
        return {"1": uno, "2": de, "3": f"{d.day} de {_MESES[d.month - 1]}"}
    # La vieja (aprobada el 05/10): {{1}} su nombre, {{2}} la pieza.
    return {"1": uno, "2": pieza}


def texto_de_la_plantilla(nombre_de_la_plantilla: str, valores: dict[str, str]) -> str:
    """Cómo se lee (para Chatwoot y la memoria del bot)."""
    from app.domain.recordatorios import CUERPO_DE_LA_PLANTILLA

    cuerpo = (
        PLANTILLAS[nombre_de_la_plantilla].cuerpo
        if nombre_de_la_plantilla in PLANTILLAS
        else CUERPO_DE_LA_PLANTILLA
    )
    for k, v in valores.items():
        cuerpo = cuerpo.replace("{{" + k + "}}", v)
    return cuerpo
