"""Las promociones activas (Camilo, 17/10).

Martha vio «dos anillos por el precio de uno» en una publicación y preguntó por
esa promoción. No existía. El bot no tenía dónde mirarlo: le contestó «no tengo
confirmada esa publicación» y la pasó a Lía.

Ahora hay una lista: `data/promociones.csv`, una fila por promoción, con sus
fechas. Cada turno el bot ve las vigentes HOY en el estado del pedido. Si no
hay ninguna, lo dice con transparencia; nunca inventa una. Y por si el modelo
la inventa igual, `vigilar` quita la frase que promete una promoción que no
está en la lista.

Una promoción se deja cargada con anticipación: empieza y se acaba sola con
`desde` y `hasta` (inclusive, hora de Colombia).
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class Promocion:
    #: Cómo se llama («2x1 en anillos de 1 huellita»). Es lo que el bot nombra.
    nombre: str
    #: Las condiciones, tal cual se le explican a la clienta.
    detalle: str
    desde: date | None = None
    hasta: date | None = None
    activa: bool = True

    def vigente(self, hoy: date) -> bool:
        if not self.activa or not self.nombre.strip():
            return False
        if self.desde is not None and hoy < self.desde:
            return False
        return not (self.hasta is not None and hoy > self.hasta)


def vigentes(promociones, hoy: date) -> list[Promocion]:
    return [p for p in promociones if p.vigente(hoy)]


def linea_del_estado(activas: list[Promocion]) -> str:
    """Lo que el modelo lee cada turno. Sin promociones, lo dice claro."""
    if not activas:
        return (
            "PROMOCIONES ACTIVAS HOY: NINGUNA. Si pregunta por promociones, "
            "descuentos, 2x1 u ofertas, o dice que vio una: dile con transparencia "
            "que en este momento no hay ninguna promoción activa. No inventes ni "
            "prometas ninguna."
        )
    return "PROMOCIONES ACTIVAS HOY (solo estas, tal cual): " + " · ".join(
        f"{p.nombre}: {p.detalle}"
        + (f" (hasta el {p.hasta:%d/%m})" if p.hasta is not None else "")
        for p in activas
    )


def _plano(texto: str) -> str:
    sin = unicodedata.normalize("NFKD", (texto or "").lower())
    return "".join(c for c in sin if not unicodedata.combining(c))


#: Que PROMETE una promoción («tenemos 2x1», «hoy con 20 % de descuento», «te
#: damos el segundo gratis»). Nombrarla para decir que no hay no es prometerla.
_PROMETE = re.compile(
    r"\b2\s*x\s*1\b|\bdos\s+por\s+(?:el\s+precio\s+de\s+)?uno\b"
    r"|\b\d{1,2}\s*%\s*(?:de\s+)?(?:descuento|dcto|off)\b"
    r"|\b(?:el\s+)?segundo\s+(?:anillo\s+)?(?:gratis|a\s+mitad)\b"
    r"|\b(?:promocion|promo|oferta|descuento)\w*\s+(?:de|del|en|por|para)\b"
    r"|\b(?:tenemos|hay|aplica|aplicamos|te\s+(?:doy|damos|hago|hacemos|dejo))\s+"
    r"(?:una\s+|un\s+|la\s+|el\s+)?(?:promocion|promo|oferta|descuento)\w*"
)
#: Lo dice para NEGARLA: «no hay», «ninguna», «en este momento no».
_NIEGA = re.compile(
    r"\bno\b|\bningun\w*|\bsin\b|\btampoco\b|\bnunca\b|\bni\b|\bya\s+no\b"
)
#: Pregunta por promociones (para la prueba de verdad y las respuestas fijas).
_PREGUNTA = re.compile(
    r"\bpromo\w*|\bofertas?\b|\bdescuentos?\b|\b2\s*x\s*1\b"
    r"|\bdos\s+por\s+(?:el\s+precio\s+de\s+)?uno\b|\bprecio\s+de\s+uno\b"
)


def pregunta_por_promociones(texto: str | None) -> bool:
    return bool(_PREGUNTA.search(_plano(texto or "")))


def promete_una_promocion(frase: str, activas: Sequence[Promocion] = ()) -> bool:
    """¿La frase ofrece una promoción que no está vigente?

    Si nombra una vigente, puede: es la lista que Camilo cargó."""
    plano = _plano(frase)
    if not _PROMETE.search(plano) or _NIEGA.search(plano):
        return False
    return not any(_plano(p.nombre) and _plano(p.nombre) in plano for p in activas)
