"""Tabla de tallas de anillo y conversión desde una medida en milímetros.

POR QUÉ ESTO ES PYTHON Y NO EL LLM
==================================
De la foto, el modelo saca UN número: cuántos milímetros mide el anillo.
Eso es leer, y leer se le da bien. Convertir ese número a una talla es
aritmética con una tabla fija, y eso no se le pregunta a un modelo
probabilístico: se calcula. Si el LLM devolviera "talla 7" directamente, un
día devolvería "talla 7.5" y otro "siete", y encima no habría forma de saber
si se equivocó.

Dividido así, el error del modelo se vuelve medible: si dice 17.3 mm cuando
eran 16.5, la talla sale mal en 1, y eso se ve. Si dijera "7" no se vería nada.

EL PROBLEMA REAL DE ESTAS FOTOS
===============================
La clienta apoya el anillo contra una regla, en la calle, con una mano. De
las fotos reales que hemos visto:
  · una mide el borde EXTERIOR (el anillo se ve más grande de lo que es)
  · otra tiene el anillo torcido sobre la regla
  · en ninguna el 0 de la regla coincide con el borde del anillo

Por eso `medir()` no devuelve solo una talla: devuelve también si hay que
REVISARLA. Una talla dudosa no detiene la conversación —la clienta no se
entera de nada— pero sí aparece marcada para que la revisen antes de fundir
plata.

FUENTE DE LA TABLA
==================
La de referencia de Lía (27/09/2026): sistema estadounidense, el que se usa
en Colombia para joyería. Diámetro INTERNO en milímetros:

    talla   5     6     7     8     9     10    11
    mm     15.6  16.4  17.3  18.2  19.0  19.8  20.5

Entre dos tallas enteras hay cuartos (7¼, 7½, 7¾): los dedos no vienen en
números enteros y Lía los fabrica. Se interpolan en línea recta.

UNA MEDIDA ESCRITA ES UNA REFERENCIA, NO UNA TALLA (27/09)
=========================================================
Una clienta escribió «1.8» y el bot le contestó «¡Es una talla 8!». 18 mm cae
entre 7½ y 8: medido con una regla, a ojo, no da para más. Por eso
`estimar()` devuelve la talla MÁS PROBABLE y también las posibles, y lo que
se le dice a ella es una referencia que Lía confirma o corrige desde el panel.
Nunca detiene la conversación: el pedido llega al abono igual.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from itertools import pairwise

#: Las enteras, de la tabla de Lía. 4 y 12-14 no están en su tabla: se dejan
#: las de siempre, que casi no se piden.
_ENTERAS: dict[int, float] = {
    4: 14.9,
    5: 15.6,
    6: 16.4,
    7: 17.3,
    8: 18.2,
    9: 19.0,
    10: 19.8,
    11: 20.5,
    12: 21.4,
    13: 22.2,
    14: 23.0,
}


def _con_cuartos(enteras: dict[int, float]) -> dict[float, float]:
    tabla: dict[float, float] = {}
    tallas = sorted(enteras)
    for a, b in pairwise(tallas):
        for cuarto in (0, 0.25, 0.5, 0.75):
            tabla[float(a) + cuarto] = round(
                enteras[a] + (enteras[b] - enteras[a]) * cuarto, 2
            )
    tabla[float(tallas[-1])] = enteras[tallas[-1]]
    return tabla


#: talla -> diámetro interno en mm, con cuartos de talla.
DIAMETRO_MM: dict[float, float] = _con_cuartos(_ENTERAS)

#: El contorno del DEDO (con una cinta o un hilo), en cm, según Lía. No es π
#: por el diámetro: el dedo se mide más holgado que el anillo, y los rangos se
#: montan (un 5.7 puede ser 7 u 8). Por eso de aquí salen POSIBLES, no una.
#: talla -> (mínimo, máximo, el más típico)
CONTORNO_CM: dict[float, tuple[float, float, float]] = {
    5.0: (5.2, 5.3, 5.25),
    6.0: (5.4, 5.5, 5.45),
    7.0: (5.4, 5.8, 5.7),
    8.0: (5.7, 5.9, 5.9),
    9.0: (6.0, 6.4, 6.2),
    10.0: (6.7, 6.9, 6.8),
    11.0: (7.2, 7.4, 7.3),
}

#: Cuánto se equivoca una regla a ojo: medio milímetro para cada lado. Las
#: tallas cuyo diámetro cae dentro son todas POSIBLES.
MARGEN_REGLA_MM = 0.3

#: Fuera de este rango, la medida no es un anillo de dedo humano: es un error
#: de lectura (la regla mal puesta, el borde exterior, un pulgar en la foto).
MM_MINIMO, MM_MAXIMO = 14.0, 23.5

#: Si la medida cae a más de esto de la talla más cercana, algo no cuadra:
#: las tallas están separadas ~0.4 mm, así que el error máximo esperable es
#: la mitad, 0.2. Un 0.35 significa que la foto no se leyó bien.
TOLERANCIA_MM = 0.35


@dataclass(frozen=True)
class Medicion:
    """El resultado de medir. Siempre hay talla; a veces hay que revisarla."""

    talla: float
    diametro_mm: float
    revisar: bool
    motivo: str = ""

    @property
    def etiqueta(self) -> str:
        """Cómo se escribe la talla: 7 y no 7.0; 7.5 sí lleva decimal."""
        return f"{self.talla:g}"


def tallas_validas() -> list[float]:
    return sorted(DIAMETRO_MM)


def talla_mas_cercana(diametro_mm: float) -> float:
    return min(DIAMETRO_MM, key=lambda t: abs(DIAMETRO_MM[t] - diametro_mm))


def medir(diametro_mm: float, *, foto_clara: bool = True) -> Medicion:
    """Convierte una medida en milímetros a una talla, y dice si es de fiar.

    SIEMPRE devuelve una talla, aunque la medida sea mala. Esa es una decisión
    de negocio deliberada: la clienta nunca se queda esperando ni recibe un
    "no te entendí". Si la medida es dudosa se marca `revisar` y quien fabrica
    lo verifica antes de fundir. Corregir una talla en el taller cuesta un
    minuto; perder a la clienta porque el bot se quedó callado cuesta $200.000.
    """
    if diametro_mm < MM_MINIMO:
        return Medicion(
            talla=min(DIAMETRO_MM),
            diametro_mm=diametro_mm,
            revisar=True,
            motivo=f"{diametro_mm:.1f} mm es más pequeño que cualquier talla "
            f"(mínimo {MM_MINIMO} mm): la regla quedó mal puesta",
        )
    if diametro_mm > MM_MAXIMO:
        return Medicion(
            talla=max(DIAMETRO_MM),
            diametro_mm=diametro_mm,
            revisar=True,
            motivo=f"{diametro_mm:.1f} mm es más grande que cualquier talla "
            f"(máximo {MM_MAXIMO} mm): puede ser el borde exterior del anillo",
        )

    talla = talla_mas_cercana(diametro_mm)
    error = abs(DIAMETRO_MM[talla] - diametro_mm)
    if error > TOLERANCIA_MM:
        return Medicion(
            talla=talla,
            diametro_mm=diametro_mm,
            revisar=True,
            motivo=f"{diametro_mm:.1f} mm cae entre dos tallas "
            f"(se desvía {error:.2f} mm de la talla {talla:g})",
        )
    if not foto_clara:
        return Medicion(
            talla=talla,
            diametro_mm=diametro_mm,
            revisar=True,
            motivo="la foto no se ve bien: anillo torcido, borroso o sin regla",
        )
    return Medicion(talla=talla, diametro_mm=diametro_mm, revisar=False)


# ══════════════════════════════════════════════════════════════════════════
#  UNA MEDIDA ESCRITA: referencia preliminar, con sus posibles (27/09)
# ══════════════════════════════════════════════════════════════════════════

_FRACCION = {0.25: "¼", 0.5: "½", 0.75: "¾"}


def talla_texto(talla: float | None) -> str:
    """7 -> «7», 7.25 -> «7¼», 7.5 -> «7½», 7.75 -> «7¾». Como la escribe Lía."""
    if talla is None:
        return ""
    entera = int(talla)
    resto = round(talla - entera, 2)
    if resto in _FRACCION:
        return f"{entera}{_FRACCION[resto]}"
    return f"{talla:g}"


def leer_talla(texto: str) -> float | None:
    """«7», «7.5», «7,25», «7½», «7 ¾» -> la talla. None si no es una."""
    limpio = (texto or "").strip().replace(",", ".").replace(" ", "")
    for valor, simbolo in _FRACCION.items():
        if limpio.endswith(simbolo):
            base = limpio[: -len(simbolo)]
            return float(base) + valor if base.isdigit() else None
    try:
        return float(limpio)
    except ValueError:
        return None


# ══════════════════════════════════════════════════════════════════════════
#  UNA TALLA DICTADA (05/10)
# ══════════════════════════════════════════════════════════════════════════
# La conversación real del 04/10 venía dictada por voz: «talla seis» llegó
# como «Gamma seis». La IA a veces no la anotaba en ese turno, la anotaba en el
# siguiente y entonces dudaba de ella («¿la talla 6 es la definitiva o te
# comparto la guía?»): le pedía la regla a quien ya había dicho su talla. Aquí
# se lee sin IA: la palabra «talla» (o como la escriba el dictado) con un
# número, o un número suelto justo después de que el bot preguntó la talla.

_NUMEROS = {
    "cuatro": 4, "cinco": 5, "seis": 6, "siete": 7, "ocho": 8, "nueve": 9,
    "diez": 10, "once": 11, "doce": 12, "trece": 13, "catorce": 14,
}  # fmt: skip
_FRACCION_DICHA = {
    "y medio": 0.5, "y media": 0.5, "y cuarto": 0.25, "y tres cuartos": 0.75,
}  # fmt: skip
#: Cómo llega «talla» por el dictado o mal escrita.
_TALLA_LIKE = r"tallas?|tayas?|talias?|talas?|talle|dalla|gamma|gama|tanta"
_NUMERO_DE_TALLA = (
    r"(\d{1,2}(?:[.,](?:25|5|75))?|" + "|".join(_NUMEROS) + r")"
    r"(\s+y\s+(?:tres\s+cuartos|medio|media|cuarto)|\s?[¼½¾])?"
)
_CON_LA_PALABRA = re.compile(
    rf"\b(?:{_TALLA_LIKE})\s+(?:es\s+)?(?:la\s+|de\s+)?{_NUMERO_DE_TALLA}\b"
)
_NUMERO_SUELTO = re.compile(rf"\b{_NUMERO_DE_TALLA}(?!\s*(?:mm|cm|mil|huell))")
#: Las palabras que pueden acompañar a un número que ES la talla.
_RELLENO = {
    "es", "la", "mi", "soy", "uso", "creo", "que", "como", "talla", "tallas",
    "seria", "sería", "numero", "número", "de", "y", "medio", "media",
    "cuarto", "tres", "cuartos", "porfa", "gracias", "si", "sí", "ok", "dale",
    "verdad", "pienso", "mas", "más", "menos", "o", "casi", "seguro", "segura",
    "aprox", "aproximadamente", "yo",
}  # fmt: skip


def _plano(texto: str) -> str:
    # NFD y no NFKD: NFKD vuelve «½» «1⁄2» y «6½» se leería 61.
    t = unicodedata.normalize("NFD", (texto or "").lower())
    return "".join(c for c in t if not unicodedata.combining(c))


def _valor(numero: str, fraccion: str | None) -> float | None:
    numero = numero.replace(",", ".")
    base = float(_NUMEROS[numero]) if numero in _NUMEROS else float(numero)
    extra = 0.0
    if fraccion:
        f = fraccion.strip()
        extra = {"¼": 0.25, "½": 0.5, "¾": 0.75}.get(f, 0.0) or _FRACCION_DICHA.get(
            re.sub(r"\s+", " ", f), 0.0
        )
    talla = base + extra
    return talla if talla in DIAMETRO_MM else None


def talla_dictada(texto: str | None, ultimo_del_bot: str = "") -> float | None:
    """La talla que ella DIJO con palabras o dictada («Gamma seis» -> 6).

    Sin la palabra «talla», solo vale un número suelto en un mensaje corto y
    justo después de que el bot le preguntó la talla. Nunca una medida («18 mm»,
    «1.8 cm»): esa es de la foto de la regla y la mira Lía.
    """
    plano = _plano(texto or "").strip()
    if not plano or re.search(r"\b(mm|cm|milimetro|centimetro|huellit)", plano):
        return None
    if "?" in plano:
        return None  # «¿tienen talla 7?» pregunta, no dice la suya
    if m := _CON_LA_PALABRA.search(plano):
        return _valor(m.group(1), m.group(2))
    pregunto = "talla" in _plano(ultimo_del_bot) and "?" in (ultimo_del_bot or "")
    palabras = re.findall(r"[a-z0-9.,¼½¾]+", plano)
    if not pregunto or not palabras or len(palabras) > 8:
        return None
    numeros = list(_NUMERO_SUELTO.finditer(plano))
    if len(numeros) != 1:
        return None
    sobran = [
        p
        for p in palabras
        if p not in _RELLENO and p not in _NUMEROS and not re.fullmatch(r"[\d.,¼½¾]+", p)
    ]
    if len(sobran) > 1:
        return None  # «tengo cinco perritos»: no es una talla
    return _valor(numeros[0].group(1), numeros[0].group(2))


_PIDE_LA_GUIA = re.compile(
    r"\bguia\b|\bmedir(la|lo)?\b|\bcomo\s+(me\s+)?mid|\bno\s+(se|estoy\s+segura)\b"
    r"|\bno\s+la\s+se\b|\bme\s+la\s+(confirmas|revisas)\b"
)


def pide_la_guia(texto: str | None) -> bool:
    """¿Ella pide la guía o duda de su talla? Solo así se le manda con la talla
    ya dicha."""
    return bool(_PIDE_LA_GUIA.search(_plano(texto or "")))


# ══════════════════════════════════════════════════════════════════════════
#  NO TIENE ANILLOS PARA MEDIR (05/10)
# ══════════════════════════════════════════════════════════════════════════
# Real, 05/10: «Es que no tengo anillos 🫣» y la IA le propuso medirse el dedo
# con una tira de papel. Lía: «si no tienes anillos, sí te tocaría pasar por
# una joyería, porque medir el dedo es muy inexacto y la talla puede quedar
# mal». Medir el DEDO (papel, hilo, cinta) no se propone nunca.

_SIN_ANILLOS = re.compile(
    r"\bno\s+(?:tengo|uso|cargo|utilizo|me\s+pongo)\s+(?:ningun\w*\s+|ni\s+un\s+"
    r"|casi\s+)?anill"
    r"|\bsin\s+anillos?\b|\bnunca\s+(?:he\s+)?(?:usado|tenido|uso)\s+anill"
    r"|\bno\s+tengo\s+(?:con\s+)?(?:que|nada\s+para)\s+medir"
    r"|\bningun\s+anillo\s+me\b|\bno\s+tengo\s+ninguno\b"
)
#: Solo justo después de la guía: «no tengo» = no tengo un anillo para medir.
_NO_TENGO = re.compile(r"^\W*(?:es\s+que\s+)?no\s+(?:tengo|tengo\s+ni\s+uno)\W*$")


def no_tiene_anillos(texto: str | None, ultimo_del_bot: str = "") -> bool:
    """¿Dice que no tiene un anillo con el cual medir su talla?"""
    plano = _plano(texto or "")
    if _SIN_ANILLOS.search(plano):
        return True
    acaba_de_ver_la_guia = "anillo que conserve" in _plano(ultimo_del_bot)
    return acaba_de_ver_la_guia and bool(_NO_TENGO.search(plano))


def referencia_para_la_clienta(talla: float, rango: str = "") -> str:
    """«Con esa medida te da más o menos talla 7¾ (entre 7½ y 8) 💍 …»."""
    entre = f" ({rango})" if rango else ""
    return (
        f"Con esa medida te da más o menos talla {talla_texto(talla)}{entre} 💍 "
        "Es una referencia: antes de fabricar la revisamos para que te quede perfecta"
    )


@dataclass(frozen=True)
class Estimacion:
    """Lo que sale de una medida que ella ESCRIBIÓ. Siempre es preliminar."""

    #: La más probable. Es la que queda guardada mientras Lía no la confirme.
    talla: float
    #: Todas las que caben con esa medida, de menor a mayor.
    posibles: tuple[float, ...]
    #: Cómo se entendió la medida: «diámetro 18 mm», «contorno del dedo 5.7 cm».
    como: str

    @property
    def rango(self) -> str:
        """«entre 7½ y 8», o vacío si solo cabe una."""
        if len(self.posibles) < 2:
            return ""
        return f"entre {talla_texto(self.posibles[0])} y {talla_texto(self.posibles[-1])}"

    def para_la_clienta(self) -> str:
        """Lo que se le dice: una referencia, nunca una confirmación."""
        return referencia_para_la_clienta(self.talla, self.rango)

    def para_lia(self, escrito: float) -> str:
        posibles = ", ".join(talla_texto(t) for t in self.posibles)
        return (
            f"Talla {talla_texto(self.talla)} ESTIMADA (preliminar) de una medida "
            f"ESCRITA «{escrito:g}» = {self.como}. Posibles: {posibles}. "
            "Confírmala o corrígela desde el panel"
        )


def estimar(valor: float) -> Estimacion | None:
    """Una medida escrita -> talla probable y posibles. None si no se entiende.

    El número llega como lo escribió ella, así que se mira el RANGO para saber
    qué midió. No es una conversión a ciegas:
      · 1.2 a 2.6  -> diámetro del anillo en cm («1.8»)
      · 12 a 26    -> diámetro en mm («18»; el modelo a veces lo pone así)
      · 4.8 a 7.8  -> contorno del dedo en cm, con cinta o hilo («5.7»)
      · 48 a 78    -> contorno del dedo en mm
    Entre medio (un 3.5, un 30) no hay forma de saber qué midió: None, y se
    le pregunta cómo la tomó.
    """
    if 1.2 <= valor <= 2.6:
        return _por_diametro(valor * 10)
    if 12 <= valor <= 26:
        return _por_diametro(valor)
    if 4.8 <= valor <= 7.8:
        return _por_contorno(valor)
    if 48 <= valor <= 78:
        return _por_contorno(valor / 10)
    return None


def _por_diametro(mm: float) -> Estimacion | None:
    if not MM_MINIMO <= mm <= MM_MAXIMO:
        return None
    probable = talla_mas_cercana(mm)
    posibles = tuple(
        sorted(t for t, d in DIAMETRO_MM.items() if abs(d - mm) <= MARGEN_REGLA_MM + 1e-9)
    ) or (probable,)
    # Los extremos que tocan el margen de refilón no suman nada: con los
    # cuartos, «entre 7½ y 8» ya dice lo que hay que decir.
    return Estimacion(probable, posibles, f"diámetro {mm:g} mm")


def _por_contorno(cm: float) -> Estimacion | None:
    dentro = [t for t, (lo, hi, _) in CONTORNO_CM.items() if lo - 0.05 <= cm <= hi + 0.05]
    if not dentro:
        # Cae en un hueco de la tabla (un 6.5, entre la 9 y la 10): las dos
        # vecinas son las posibles.
        debajo = [t for t, (_, hi, _) in CONTORNO_CM.items() if hi < cm]
        encima = [t for t, (lo, _, _) in CONTORNO_CM.items() if lo > cm]
        if not debajo or not encima:
            return None
        dentro = [max(debajo), min(encima)]
    probable = min(dentro, key=lambda t: abs(CONTORNO_CM[t][2] - cm))
    return Estimacion(probable, tuple(sorted(dentro)), f"contorno del dedo {cm:g} cm")
