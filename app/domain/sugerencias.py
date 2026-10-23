"""Ayudarla a escoger. Es servicio, no venta.

════════════════════════════════════════════════════════════════════════════
POR QUÉ EL BOT PROPONE
════════════════════════════════════════════════════════════════════════════
Catorce colores para el corazón por catorce para los deditos son ciento
noventa y seis anillos posibles. Delante de eso mucha gente no elige: dice
«déjame pensarlo» y no vuelve. No es que no quiera el anillo; es que no
quiere equivocarse.

Proponer tres combinaciones concretas —con su foto— quita esa parálisis. La
clienta ya no tiene que imaginar nada: mira, señala y sigue.

════════════════════════════════════════════════════════════════════════════
Y POR QUÉ LA ÚLTIMA PALABRA ES SIEMPRE SUYA
════════════════════════════════════════════════════════════════════════════
Una sugerencia que suena a decisión tomada es peor que no sugerir nada: se
lleva puesto lo que la clienta quería y encima la deja sin ganas de
corregir. Por eso cada propuesta se ofrece con nombre y se cierra con una
pregunta, y por eso las tres van juntas y no de una en una.

    Proponer sí. Decidir por ella, nunca.

Si se equivoca la propuesta no pasa nada —cuesta un mensaje—; si se le
impone, cuesta la clienta.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.domain.personalizacion import NOMBRE_COLOR, ColorCircon, Huellita


@dataclass(frozen=True)
class Sugerencia:
    """Una combinación con nombre. El nombre es lo que la hace elegible.

    «La elegante» se puede señalar en un mensaje; «la opción 2» hay que
    contarla, y «verde esmeralda con blancos» hay que escribirla entera.
    """

    clave: str
    nombre: str
    corazon: ColorCircon
    dedos: ColorCircon
    #: Por qué se la enseñamos. Una línea, en voz de Lía.
    gancho: str

    @property
    def huellita(self) -> Huellita:
        return Huellita(corazon=self.corazon, dedos=self.dedos)

    def describir(self) -> str:
        return (
            f"*{self.nombre}* — corazón {NOMBRE_COLOR[self.corazon]}, "
            f"deditos en {NOMBRE_COLOR[self.dedos]}. {self.gancho}"
        )


#: Las que se proponen. Tres, y no cinco.
#:
#: Tres caben en una pantalla de WhatsApp con sus tres fotos, y son pocas
#: para compararlas de un vistazo. Con cinco vuelve el problema que esto
#: viene a resolver.
#:
#: Están escogidas para que NO se parezcan entre ellas: una clásica, una de
#: color y una con carácter. Si las tres fueran variaciones de rosa, no
#: serían una elección.
COMBINACIONES: tuple[Sugerencia, ...] = (
    Sugerencia(
        clave="elegante",
        nombre="La elegante",
        corazon=ColorCircon.VERDE_ESMERALDA,
        dedos=ColorCircon.BLANCO,
        gancho="Es la que más se vende: se ve fina y combina con todo 💚",
    ),
    Sugerencia(
        clave="clasica",
        nombre="La clásica",
        corazon=ColorCircon.ROJO,
        dedos=ColorCircon.BLANCO,
        gancho="Nunca falla, y el rojo resalta muchísimo en la plata ❤️",
    ),
    Sugerencia(
        clave="dulce",
        nombre="La dulce",
        corazon=ColorCircon.LILA,
        dedos=ColorCircon.ROSADO,
        gancho="Suavecita y muy bonita para el día a día 💜",
    ),
)

#: Cómo se señala una de las tres. Se compara ya normalizado.
COMO_SE_LLAMAN: dict[str, str] = {
    "elegante": "elegante",
    "la elegante": "elegante",
    "verde": "elegante",
    "esmeralda": "elegante",
    "clasica": "clasica",
    "la clasica": "clasica",
    "roja": "clasica",
    "la roja": "clasica",
    "dulce": "dulce",
    "la dulce": "dulce",
    "lila": "dulce",
    "la lila": "dulce",
}


def por_clave(clave: str) -> Sugerencia | None:
    return next((s for s in COMBINACIONES if s.clave == clave), None)


def por_posicion(posicion: int) -> Sugerencia | None:
    """«La segunda». La posición 1 es la primera que ve, no el índice 0."""
    if 1 <= posicion <= len(COMBINACIONES):
        return COMBINACIONES[posicion - 1]
    return None


def por_nombre(texto: str) -> Sugerencia | None:
    """«La elegante», «la roja». Devuelve None si no nombró ninguna."""
    return por_clave(COMO_SE_LLAMAN.get((texto or "").strip(), ""))
