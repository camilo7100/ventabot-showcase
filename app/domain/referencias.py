"""«El segundo», «ese», «el otro» → un identificador real. En Python.

════════════════════════════════════════════════════════════════════════════
LA REGLA
════════════════════════════════════════════════════════════════════════════
El modelo dice QUÉ TIPO de referencia oyó. Este módulo dice A QUÉ apunta.

Esa división no es purismo. «El segundo» es un hecho verificable: había una
lista, tenía un orden, y en la posición 2 estaba el PED-2026-0456. Preguntarle
eso a un modelo de lenguaje es convertir un dato exacto en una probabilidad, y
el día que se equivoque le va a cobrar el saldo de un pedido a la clienta de
otro.

════════════════════════════════════════════════════════════════════════════
NUNCA ADIVINA
════════════════════════════════════════════════════════════════════════════
Todas las funciones devuelven `Resolucion`, que puede ser:

    RESUELTA    -> un id, con la certeza de dónde salió
    AMBIGUA     -> varios candidatos; hay que preguntar, con los candidatos
                   a mano para poder preguntar bien
    SIN_DATOS   -> no hay contexto suficiente
    NO_APLICA   -> el mensaje no traía ninguna referencia

Un `None` habría mezclado «no dijo nada» con «dijo algo que no pude resolver»,
que son dos situaciones opuestas: la primera se sigue de largo, la segunda
obliga a parar.
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass, field
from enum import Enum

from app.domain.contexto import ContextoConversacional, Mencion
from app.domain.interpretacion import Referencia, TipoReferencia


class Estado(str, Enum):
    RESUELTA = "RESUELTA"
    AMBIGUA = "AMBIGUA"
    SIN_DATOS = "SIN_DATOS"
    NO_APLICA = "NO_APLICA"


@dataclass(frozen=True)
class Resolucion:
    estado: Estado
    id: str | None = None
    #: De dónde salió. Va al log y, cuando hay que depurar, es lo único que
    #: explica por qué el bot creyó que «el segundo» era ese.
    origen: str = ""
    #: Cuando es AMBIGUA: entre cuáles hay que elegir. Sirve para preguntar
    #: nombrándolos, en vez de un «¿cuál?» a secas.
    candidatos: tuple[Mencion, ...] = ()

    @property
    def ok(self) -> bool:
        return self.estado is Estado.RESUELTA


def _normalizar(texto: str) -> str:
    sin_tildes = "".join(
        c
        for c in unicodedata.normalize("NFD", texto or "")
        if unicodedata.category(c) != "Mn"
    )
    return sin_tildes.lower().strip()


@dataclass
class Catalogo:
    """Lo que hay disponible para resolver. Lo arma quien llama.

    Se pasa explícito en vez de que este módulo consulte la base de datos: así
    la resolución es una función pura, se prueba en microsegundos, y no puede
    tener efectos secundarios sobre los datos.
    """

    menciones: list[Mencion] = field(default_factory=list)
    foco_id: str | None = None
    foco_previo_id: str | None = None
    #: Todos los candidatos posibles aunque no se hayan mostrado. Es lo que
    #: permite resolver «el anillo rosado» sin que hubiera una lista antes.
    todos: list[Mencion] = field(default_factory=list)


def desde_contexto(
    ctx: ContextoConversacional, todos: list[Mencion] | None = None
) -> Catalogo:
    return Catalogo(
        menciones=ctx.menciones_vigentes(),
        foco_id=ctx.foco_id,
        foco_previo_id=ctx.foco_previo_id,
        todos=todos or [],
    )


def resolver(ref: Referencia, cat: Catalogo) -> Resolucion:
    """El único punto de entrada. Devuelve siempre una `Resolucion`."""
    if ref.tipo is TipoReferencia.NINGUNA:
        return Resolucion(Estado.NO_APLICA)

    if ref.tipo is TipoReferencia.ORDINAL:
        return _ordinal(ref, cat)
    if ref.tipo is TipoReferencia.ULTIMO:
        return _ultimo(cat)
    if ref.tipo is TipoReferencia.ESE:
        return _ese(cat)
    if ref.tipo in (TipoReferencia.OTRO, TipoReferencia.ANTERIOR):
        return _otro(cat)
    if ref.tipo is TipoReferencia.CODIGO:
        return _codigo(ref, cat)
    if ref.tipo is TipoReferencia.DESCRIPCION:
        return _descripcion(ref, cat)
    return Resolucion(Estado.SIN_DATOS, origen=f"tipo no soportado: {ref.tipo}")


def _ordinal(ref: Referencia, cat: Catalogo) -> Resolucion:
    if not cat.menciones:
        return Resolucion(
            Estado.SIN_DATOS,
            origen="dijo un ordinal pero no se le ha mostrado ninguna lista",
        )
    if ref.posicion is None:
        return Resolucion(
            Estado.AMBIGUA, candidatos=tuple(cat.menciones), origen="ordinal sin número"
        )
    encontrada = next((m for m in cat.menciones if m.posicion == ref.posicion), None)
    if encontrada is None:
        # Pidió «el quinto» de una lista de tres. Preguntar es mejor que
        # devolver el último por aproximación.
        return Resolucion(
            Estado.AMBIGUA,
            candidatos=tuple(cat.menciones),
            origen=f"pidió la posición {ref.posicion} de una lista de "
            f"{len(cat.menciones)}",
        )
    return Resolucion(
        Estado.RESUELTA,
        id=encontrada.id,
        origen=f"posición {ref.posicion} de la última lista",
    )


def _ultimo(cat: Catalogo) -> Resolucion:
    if cat.menciones:
        m = max(cat.menciones, key=lambda x: x.posicion)
        return Resolucion(Estado.RESUELTA, id=m.id, origen="el último de la lista")
    if cat.foco_id:
        return Resolucion(Estado.RESUELTA, id=cat.foco_id, origen="el foco actual")
    return Resolucion(Estado.SIN_DATOS, origen="no hay lista ni foco")


def _ese(cat: Catalogo) -> Resolucion:
    """«ese» es de lo que se está hablando ahora mismo."""
    if cat.foco_id:
        return Resolucion(Estado.RESUELTA, id=cat.foco_id, origen="el foco actual")
    if len(cat.menciones) == 1:
        return Resolucion(
            Estado.RESUELTA,
            id=cat.menciones[0].id,
            origen="solo se le mostró uno, no hay ambigüedad",
        )
    if cat.menciones:
        return Resolucion(
            Estado.AMBIGUA,
            candidatos=tuple(cat.menciones),
            origen="dijo «ese» pero se le mostraron varios y ninguno está en foco",
        )
    return Resolucion(Estado.SIN_DATOS, origen="dijo «ese» sin contexto previo")


def _otro(cat: Catalogo) -> Resolucion:
    """«el otro» / «el anterior»: el que NO es el que está en foco."""
    if cat.foco_previo_id:
        return Resolucion(
            Estado.RESUELTA,
            id=cat.foco_previo_id,
            origen="el que estaba en foco antes de este",
        )
    restantes = [m for m in cat.menciones if m.id != cat.foco_id]
    if len(restantes) == 1:
        return Resolucion(
            Estado.RESUELTA,
            id=restantes[0].id,
            origen="el único de la lista que no está en foco",
        )
    if restantes:
        return Resolucion(
            Estado.AMBIGUA,
            candidatos=tuple(restantes),
            origen="dijo «el otro» y hay más de uno que podría serlo",
        )
    return Resolucion(Estado.SIN_DATOS, origen="no hay ningún «otro» del que hablar")


def _codigo(ref: Referencia, cat: Catalogo) -> Resolucion:
    """Dijo un código. Se comprueba contra datos reales, nunca se usa tal cual.

    Un código que la clienta escribe mal —o que el modelo transcribe mal— no
    puede convertirse en un id que se consulta a ciegas.
    """
    buscado = _normalizar(ref.texto or "")
    if not buscado:
        return Resolucion(Estado.SIN_DATOS, origen="código vacío")
    universo = cat.todos or cat.menciones
    for m in universo:
        if (
            buscado == _normalizar(m.codigo)
            or buscado in _normalizar(m.etiqueta)
            or buscado == _normalizar(m.id)
        ):
            return Resolucion(Estado.RESUELTA, id=m.id, origen=f"código «{ref.texto}»")
    return Resolucion(
        Estado.SIN_DATOS, origen=f"el código «{ref.texto}» no es de ningún pedido suyo"
    )


def _descripcion(ref: Referencia, cat: Catalogo) -> Resolucion:
    """«el anillo rosado», «el que ya enviaron».

    Se buscan TODAS las palabras del texto dentro de la etiqueta. Si encaja
    exactamente una, se resuelve; si encajan varias, se pregunta nombrándolas.
    Aproximar aquí es cómo se termina cancelando el pedido equivocado.
    """
    palabras = [p for p in _normalizar(ref.texto or "").split() if len(p) > 2]
    if not palabras:
        return Resolucion(Estado.SIN_DATOS, origen="descripción vacía")

    universo = cat.menciones or cat.todos
    if not universo:
        return Resolucion(Estado.SIN_DATOS, origen="no hay nada contra qué buscar")

    encajan = [m for m in universo if all(p in _normalizar(m.etiqueta) for p in palabras)]
    if len(encajan) == 1:
        return Resolucion(
            Estado.RESUELTA, id=encajan[0].id, origen=f"describió «{ref.texto}»"
        )
    if len(encajan) > 1:
        return Resolucion(
            Estado.AMBIGUA,
            candidatos=tuple(encajan),
            origen=f"«{ref.texto}» encaja con {len(encajan)} de sus pedidos",
        )
    # Segundo intento, más flojo: alguna palabra en vez de todas.
    parciales = [
        m for m in universo if any(p in _normalizar(m.etiqueta) for p in palabras)
    ]
    if len(parciales) == 1:
        return Resolucion(
            Estado.RESUELTA,
            id=parciales[0].id,
            origen=f"describió «{ref.texto}» (coincidencia parcial)",
        )
    if parciales:
        return Resolucion(
            Estado.AMBIGUA,
            candidatos=tuple(parciales),
            origen=f"«{ref.texto}» podría ser varios",
        )
    return Resolucion(Estado.SIN_DATOS, origen=f"«{ref.texto}» no coincide con nada suyo")
