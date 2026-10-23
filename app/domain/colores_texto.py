"""Leer colores de circón de lo que la clienta escribe. SIN LLM.

POR QUÉ ESTO NO LO HACE EL MODELO
=================================
"quiero corazón lila y dedos morados" no necesita un modelo de lenguaje: es
buscar dos palabras de una lista de catorce. Un `dict` lo hace en microsegundos,
sin GPU, sin red, igual todas las veces, y se puede depurar leyéndolo.

El LLM queda de RESPALDO, para lo que sí es lenguaje de verdad: "ponme el
corazón del color de mis ojos" o "el mismo que le hiciste a mi hermana". Ese
reparto —Python primero, modelo solo si Python no pudo— es el que hace que el
sistema sea rápido y barato en el 90% de los casos y siga siendo capaz en el
10% restante.

CÓMO AGREGAR UN COLOR O UNA FORMA DE DECIRLO
============================================
Todo está en `SINONIMOS`, abajo. Se agrega la palabra nueva apuntando al color
del muestrario y listo: lo aprenden el parser, los tests y el bot. No hay que
tocar ninguna otra cosa. El nombre que Lía le pone a una bolsita en el panel
(Colores) se entiende solo, sin agregarlo aquí (`sinonimos_vigentes`).

LA REGLA DE ORO
===============
Ante la duda, NO adivina. Devolver "no entendí este color" hace que el bot
vuelva a preguntar, que cuesta un mensaje. Adivinar mal hace que se funda un
anillo de plata del color equivocado, que cuesta el anillo, el envío y la
clienta.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from app.domain.personalizacion import NOMBRE_COLOR, ColorCircon

#: Cómo dice la gente cada color. La clave se compara SIN tildes y en
#: minúscula, así que "lila" cubre "Lila" y "LILA".
#:
#: Estas son las formas que aparecen en las conversaciones reales más las
#: variantes obvias. Cuando salga una nueva, se agrega aquí y nada más.
SINONIMOS: dict[str, ColorCircon] = {
    # blanco / transparente
    "blanco": ColorCircon.BLANCO,
    "blanca": ColorCircon.BLANCO,
    "cristal": ColorCircon.BLANCO,
    "transparente": ColorCircon.BLANCO,
    "diamante": ColorCircon.BLANCO,
    "plateado": ColorCircon.BLANCO,
    # negro
    "negro": ColorCircon.NEGRO,
    "negra": ColorCircon.NEGRO,
    # lila / morado — se distinguen a propósito: son dos bolsitas distintas
    "lila": ColorCircon.LILA,
    "lavanda": ColorCircon.LILA,
    "violeta": ColorCircon.MORADO,  # la bolsita morada es azul-violeta (medido 30/09)
    "morado": ColorCircon.MORADO,
    "morada": ColorCircon.MORADO,
    "purpura": ColorCircon.MORADO,
    "uva": ColorCircon.MORADO,
    # azules
    "celeste": ColorCircon.CELESTE,
    "azul claro": ColorCircon.CELESTE,
    "azulclaro": ColorCircon.CELESTE,
    "cielo": ColorCircon.CELESTE,
    "turquesa": ColorCircon.CELESTE,
    "azul rey": ColorCircon.AZUL_REY,
    "azul zafiro": ColorCircon.AZUL_REY,
    "zafiro": ColorCircon.AZUL_REY,
    "azulrey": ColorCircon.AZUL_REY,
    "azul oscuro": ColorCircon.AZUL_REY,
    "azul": ColorCircon.AZUL_REY,
    # rosados
    "rosado": ColorCircon.ROSADO,
    "rosada": ColorCircon.ROSADO,
    "rosa": ColorCircon.ROSADO,
    "rosa palo": ColorCircon.ROSADO,
    "palo de rosa": ColorCircon.ROSADO,
    "fucsia": ColorCircon.FUCSIA,
    "fuccia": ColorCircon.FUCSIA,
    "fuxia": ColorCircon.FUCSIA,
    "rosado fuerte": ColorCircon.FUCSIA,
    "magenta": ColorCircon.FUCSIA,
    # cálidos
    "rojo": ColorCircon.ROJO,
    "roja": ColorCircon.ROJO,
    "vinotinto": ColorCircon.ROJO,
    "naranja": ColorCircon.NARANJA,
    "naranjado": ColorCircon.NARANJA,
    "durazno": ColorCircon.DURAZNO,
    "champagne": ColorCircon.DURAZNO,
    "champana": ColorCircon.DURAZNO,
    "salmon": ColorCircon.DURAZNO,
    "melocoton": ColorCircon.DURAZNO,
    "coral": ColorCircon.DURAZNO,
    "amarillo": ColorCircon.AMARILLO,
    "amarilla": ColorCircon.AMARILLO,
    "dorado": ColorCircon.AMARILLO,  # el circón; el BAÑO dorado no se maneja
    # verdes
    "verde oliva": ColorCircon.VERDE_OLIVA,
    "oliva": ColorCircon.VERDE_OLIVA,
    "verde claro": ColorCircon.VERDE_OLIVA,
    "verde limon": ColorCircon.VERDE_OLIVA,
    "verde esmeralda": ColorCircon.VERDE_ESMERALDA,
    "esmeralda": ColorCircon.VERDE_ESMERALDA,
    "verde oscuro": ColorCircon.VERDE_ESMERALDA,
    "verde": ColorCircon.VERDE_ESMERALDA,
}

#: Cómo llama la gente a la piedra grande del centro.
PALABRAS_CORAZON = (
    "corazon",
    "corazoncito",
    "centro",
    "piedra grande",
    "grande",
    "la del medio",
    "medio",
    "principal",
    "huella",
    "huellita",
)
#: …y a los cuatro circoncitos de alrededor.
PALABRAS_DEDOS = (
    "dedos",
    "deditos",
    "dedito",
    "pequenas",
    "pequenos",
    "chiquitas",
    "chiquitos",
    "chiquiticos",
    "alrededor",
    "patas",
    "paticas",
    "puntos",
)
#: "todo negro", "toda de un color": el mismo color en las dos partes.
PALABRAS_TODO = ("todo", "toda", "completo", "completa", "entero", "entera", "igual")


@dataclass(frozen=True)
class LecturaColores:
    """Lo que se pudo leer del mensaje. Cualquier campo puede venir vacío."""

    corazon: ColorCircon | None = None
    dedos: ColorCircon | None = None
    #: Colores nombrados que no se pudieron asignar a una parte concreta.
    #: Sirven para preguntar mejor: "vi lila y morado, ¿cuál va en el corazón?"
    sueltos: tuple[ColorCircon, ...] = ()

    @property
    def completa(self) -> bool:
        return self.corazon is not None and self.dedos is not None


def normalizar(texto: str) -> str:
    """Minúsculas, sin tildes y sin puntuación. Para comparar, no para mostrar."""
    sin_tildes = "".join(
        c
        for c in unicodedata.normalize("NFD", texto or "")
        if unicodedata.category(c) != "Mn"
    )
    return re.sub(r"[^a-z0-9 ]+", " ", sin_tildes.lower())


#: La tabla vigente, rehecha solo cuando cambian los nombres del panel.
_VIGENTE: tuple[tuple, dict[str, ColorCircon], tuple[str, ...]] | None = None


def _vigente() -> tuple[tuple, dict[str, ColorCircon], tuple[str, ...]]:
    global _VIGENTE
    clave = tuple(NOMBRE_COLOR.items())
    if _VIGENTE is None or _VIGENTE[0] != clave:
        tabla = dict(SINONIMOS)
        for color, nombre in NOMBRE_COLOR.items():
            tabla.setdefault(" ".join(normalizar(nombre).split()), color)
        # Los sinónimos de dos palabras ("azul rey") se buscan ANTES que los de
        # una ("azul"), porque si no "azul rey" no se leería nunca: ganaría
        # "azul" al pasar primero. Ordenar por largo descendente lo resuelve.
        _VIGENTE = (clave, tabla, tuple(sorted(tabla, key=len, reverse=True)))
    return _VIGENTE


def sinonimos_vigentes() -> dict[str, ColorCircon]:
    """`SINONIMOS` más el nombre que tiene HOY cada bolsita en el panel.

    Si Lía rebautiza una bolsita («champaña»), la clienta escribe el nombre
    nuevo —el que le enseñó el bot— y hay que entenderlo sin tocar código.
    """
    return _vigente()[1]


def alternativa_de_colores() -> str:
    """Todas las formas de decir un color, para meterlas en un patrón
    (`a|b|c`), de la más larga a la más corta."""
    return "|".join(re.escape(p) for p in _vigente()[2])


#: Plural pegado al sinónimo: "morados", "blancos", "azules". Sin esto, el
#: mensaje más común de todos —«corazón lila y dedos morados»— perdía el
#: segundo color, porque `\bmorado\b` no casa dentro de "morados". Listar
#: cada plural a mano habría duplicado la tabla y garantizado olvidos.
_PLURAL = r"(?:e?s)?"


def _patron(palabra: str) -> str:
    return rf"\b{re.escape(palabra)}{_PLURAL}\b"


def _hueco(tramo: tuple[int, int], color: tuple[int, int]) -> int:
    """Cuántos caracteres hay ENTRE una palabra de parte y un color."""
    if tramo[1] <= color[0]:
        return color[0] - tramo[1]
    if color[1] <= tramo[0]:
        return tramo[0] - color[1]
    return 0


def _hallazgos(texto: str) -> list[tuple[int, str, ColorCircon]]:
    """Colores encontrados, con su posición, sin solaparse entre sí."""
    encontrados: list[tuple[int, str, ColorCircon]] = []
    ocupado = [False] * len(texto)
    _, tabla, ordenados = _vigente()
    for palabra in ordenados:
        for m in re.finditer(_patron(palabra), texto):
            if any(ocupado[m.start() : m.end()]):
                continue
            for i in range(m.start(), m.end()):
                ocupado[i] = True
            encontrados.append((m.start(), palabra, tabla[palabra]))
    return sorted(encontrados)


def _marcas(texto: str, palabras: tuple[str, ...]) -> list[int]:
    return sorted(m.start() for p in palabras for m in re.finditer(_patron(p), texto))


def _tramos(texto: str, palabras: tuple[str, ...]) -> list[tuple[int, int]]:
    """Dónde empieza y dónde ACABA cada palabra de parte.

    Hace falta el final, no solo el principio: la distancia entre «corazon» y
    «lila» en «corazon lila» es un espacio, y medida de principio a principio
    son ocho caracteres — suficiente para que el color se fuera con la parte
    equivocada. Es el hueco entre las dos palabras lo que dice si van juntas.
    """
    return sorted(
        (m.start(), m.end()) for p in palabras for m in re.finditer(_patron(p), texto)
    )


@dataclass(frozen=True)
class LecturaDeVarias:
    """Todas las huellitas que se nombraron en UN mensaje.

    Una clienta que pide un anillo de tres patitas no escribe tres mensajes:
    escribe «corazón lila dedos rojos y el tercero verde corazón azul dedos».
    Leer solo la primera pareja y tirar el resto obliga a preguntarle dos
    veces algo que ya dijo — y es donde se nota que del otro lado hay una
    máquina.
    """

    parejas: tuple[tuple[ColorCircon, ColorCircon], ...] = ()
    #: La pareja que quedó a medias al final, si la hay: {"corazon": …}.
    media: tuple[tuple[str, ColorCircon], ...] = ()
    #: Colores nombrados sin decir a qué parte van.
    sueltos: tuple[ColorCircon, ...] = ()


#: Hasta dónde se acepta cambiar de parte cuando la más cercana ya está
#: ocupada. Cinco palabras: más allá, el color pertenece a otra cosa.
MARGEN = 30


def _parte_mas_cerca(
    color: tuple[int, int],
    corazon: list[tuple[int, int]],
    dedos: list[tuple[int, int]],
    ocupadas: dict,
) -> str | None:
    """A qué parte pertenece un color: a la palabra que tenga MÁS PEGADA.

    ════════════════════════════════════════════════════════════════════════
    POR QUÉ LA MÁS CERCA Y NO LA ANTERIOR
    ════════════════════════════════════════════════════════════════════════
    En español el color va delante o detrás sin ninguna regla: «corazón lila»
    y «verde esmeralda el corazón» son la misma frase. Mirar solo hacia atrás
    obligaba a un parche —«si sobra un color y falta una parte, se completa»—
    que funcionaba con una pareja y se rompía con dos.

    ════════════════════════════════════════════════════════════════════════
    Y POR QUÉ LA PARTE LIBRE GANA LOS EMPATES
    ════════════════════════════════════════════════════════════════════════
    En «verde corazón azul dedos», el «azul» está a un espacio de las dos
    palabras. Empate perfecto. Pero el corazón de esa huellita ya es verde,
    así que el azul solo puede ser de los deditos. Lo dice el contexto de la
    frase, no la distancia — y por eso hace falta saber qué hay ya puesto.
    """
    cerca_c = min((_hueco(t, color) for t in corazon), default=None)
    cerca_d = min((_hueco(t, color) for t in dedos), default=None)
    if cerca_c is None and cerca_d is None:
        return None
    if cerca_d is None:
        return "corazon"
    if cerca_c is None:
        return "dedos"

    # En un empate manda el corazón: es la piedra grande y la que la gente
    # nombra primero cuando no dice cuál.
    elegida, otra = ("corazon", "dedos") if cerca_c <= cerca_d else ("dedos", "corazon")
    hueco_otra = cerca_d if elegida == "corazon" else cerca_c
    if elegida in ocupadas and otra not in ocupadas and hueco_otra <= MARGEN:
        return otra
    return elegida


def leer_varias(mensaje: str) -> LecturaDeVarias:
    """Todas las parejas de colores de un mensaje, en orden.

    Recorre los colores de izquierda a derecha, le asigna a cada uno la parte
    que tiene más cerca, y cierra una huellita cada vez que se completan las
    dos partes. Es un bucle de quince líneas y no tiene ningún caso especial.
    """
    t = normalizar(mensaje)
    colores = _hallazgos(t)
    if not colores:
        return LecturaDeVarias()

    pos_corazon = _tramos(t, PALABRAS_CORAZON)
    pos_dedos = _tramos(t, PALABRAS_DEDOS)

    # «Todo negro»: un color y una palabra de totalidad. Es una huellita
    # entera del mismo color, y no hay nada que emparejar.
    if len(colores) == 1 and not pos_corazon and not pos_dedos:
        color = colores[0][2]
        if _marcas(t, PALABRAS_TODO):
            return LecturaDeVarias(parejas=((color, color),))
        return LecturaDeVarias(sueltos=(color,))

    parejas: list[tuple[ColorCircon, ColorCircon]] = []
    sueltos: list[ColorCircon] = []
    cur: dict[str, ColorCircon] = {}

    for posicion, palabra, color in colores:
        tramo = (posicion, posicion + len(palabra))
        parte = _parte_mas_cerca(tramo, pos_corazon, pos_dedos, cur)
        if parte is None:
            sueltos.append(color)
            continue
        cur[parte] = color
        if len(cur) == 2:
            parejas.append((cur["corazon"], cur["dedos"]))
            cur = {}

    return LecturaDeVarias(
        parejas=tuple(parejas),
        media=tuple(cur.items()),
        sueltos=tuple(sueltos),
    )


def leer_colores(mensaje: str) -> LecturaColores:
    """La PRIMERA pareja del mensaje. La forma de siempre, sobre `leer_varias`.

    Existe porque casi todo el sistema pregunta por una huellita cada vez.
    Cuando hacen falta todas —«el tercero verde corazón azul dedos»— se usa
    `leer_varias` directamente.
    """
    varias = leer_varias(mensaje)
    if varias.parejas:
        corazon, dedos = varias.parejas[0]
        return LecturaColores(corazon=corazon, dedos=dedos, sueltos=varias.sueltos)
    media = dict(varias.media)
    return LecturaColores(
        corazon=media.get("corazon"),
        dedos=media.get("dedos"),
        sueltos=varias.sueltos,
    )
