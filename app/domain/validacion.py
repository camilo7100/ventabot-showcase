"""La puerta entre entender y actuar. Aquí se corta, o se pasa.

════════════════════════════════════════════════════════════════════════════
LA REGLA DE AMBIGÜEDAD, ESCRITA UNA SOLA VEZ
════════════════════════════════════════════════════════════════════════════
    Si hay varias interpretaciones posibles y equivocarse cuesta dinero:
    NO se asume. Se pregunta.

    Si equivocarse solo cuesta un mensaje: se elige lo más reciente y se
    sigue, porque un bot que pregunta de más cansa tanto como uno que asume
    de más — pero solo uno de los dos le cobra el saldo a la clienta
    equivocada.

Qué cuesta dinero no lo decide esta función: está declarado en
`acciones.CRITICAS`. Aquí solo se aplica. Esa separación es lo que permite
cambiar la política comercial (¿cancelar es crítico? ¿y modificar un color?)
tocando una línea de una lista, sin releer esta lógica.

════════════════════════════════════════════════════════════════════════════
EL VEREDICTO NO ES UN BOOLEANO
════════════════════════════════════════════════════════════════════════════
«No se puede ejecutar» tiene tres formas distintas y cada una se contesta
distinto:

    EJECUTAR   -> adelante
    PREGUNTAR  -> falta un dato o hay ambigüedad; la conversación sigue
    ESCALAR    -> hace falta una persona

Un booleano habría obligado a inventar la diferencia después, en el sitio
equivocado y probablemente dos veces.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from app.domain.acciones import CRITICAS, NECESITA, Accion, Requisito
from app.domain.contexto import Mencion
from app.domain.interpretacion import Interpretacion
from app.domain.referencias import Estado, Resolucion


class Veredicto(str, Enum):
    EJECUTAR = "EJECUTAR"
    PREGUNTAR = "PREGUNTAR"
    ESCALAR = "ESCALAR"


@dataclass(frozen=True)
class Decision:
    veredicto: Veredicto
    accion: Accion
    #: El pedido/proceso sobre el que se actúa, si se pudo determinar.
    objetivo_id: str | None = None
    #: Por qué. Va al log Y alimenta la pregunta que se le hace a la clienta,
    #: así que se escribe pensando en que alguien lo va a leer.
    motivo: str = ""
    #: Cuando hay que preguntar entre varios: cuáles. Permite preguntar
    #: nombrándolos («¿el del taller o el que espera saldo?») en vez de un
    #: «¿cuál?» que obliga a la clienta a repetir todo.
    candidatos: tuple[Mencion, ...] = ()
    #: Qué requisito falló. Lo usa el redactor para elegir qué preguntar.
    falta: Requisito | None = None

    @property
    def ejecutable(self) -> bool:
        return self.veredicto is Veredicto.EJECUTAR


@dataclass
class Disponible:
    """Lo que el sistema tiene a mano en este turno.

    Se pasa explícito en lugar de que `validar()` vaya a buscarlo: así la
    validación es pura y se puede probar cada rama en una línea.
    """

    pedidos: list[Mencion] = field(default_factory=list)
    procesos: list[str] = field(default_factory=list)
    resolucion: Resolucion | None = None
    #: Con abono pagado o en producción: son los que importan para cobrar.
    pedidos_con_saldo: list[Mencion] = field(default_factory=list)


def validar(accion: Accion, interp: Interpretacion, disp: Disponible) -> Decision:
    """¿Se puede ejecutar esta acción, ahora, con lo que hay?"""
    if accion is Accion.LLAMAR_HUMANO:
        return Decision(Veredicto.ESCALAR, accion, motivo="lo pidió explícitamente")

    critica = accion in CRITICAS
    requisitos = NECESITA.get(accion, ())
    objetivo = _id_de(disp)

    # -- ¿hace falta saber de QUÉ pedido habla? ----------------------------
    if Requisito.PEDIDO in requisitos:
        decision, elegido = _elegir_pedido(accion, disp, critica)
        if decision is not None:
            return decision
        objetivo = elegido or objetivo

    # -- ¿hace falta una compra abierta? -----------------------------------
    if Requisito.PROCESO in requisitos and not disp.procesos:
        return Decision(
            Veredicto.PREGUNTAR,
            accion,
            falta=Requisito.PROCESO,
            motivo="no hay ninguna compra a medias a la que aplicar esto",
        )

    # -- ¿el mensaje traía algo aprovechable? ------------------------------
    if Requisito.DATOS in requisitos and not interp.datos.hay_algo():
        return Decision(
            Veredicto.PREGUNTAR,
            accion,
            falta=Requisito.DATOS,
            motivo="dijo que informaba algo pero no se entendió qué",
        )

    # -- confianza baja en algo que cuesta dinero --------------------------
    #
    # No es lo mismo entender mal «¿cuánto cuesta?» que entender mal «cancela
    # ese pedido». Cuando el modelo mismo duda y la acción es de las caras,
    # se confirma antes.
    if critica and interp.confianza == "BAJA":
        return Decision(
            Veredicto.PREGUNTAR,
            accion,
            objetivo_id=objetivo,
            motivo="no se entendió con seguridad y esto no se puede deshacer",
        )

    return Decision(
        Veredicto.EJECUTAR,
        accion,
        objetivo_id=objetivo,
        motivo="hay todo lo necesario",
    )


def _id_de(disp: Disponible) -> str | None:
    if disp.resolucion is not None and disp.resolucion.ok:
        return disp.resolucion.id
    if len(disp.pedidos) == 1:
        return disp.pedidos[0].id
    return None


def _elegir_pedido(
    accion: Accion, disp: Disponible, critica: bool
) -> tuple[Decision | None, str | None]:
    """(corta aquí, o sigue con este pedido).

    Devuelve la pareja y no solo la Decision porque «se puede seguir» no basta:
    hay que decir CON CUÁL. La primera versión devolvía None al acertar y el
    pedido elegido se perdía, así que la acción se ejecutaba sin objetivo —
    una consulta de saldo sin saber de qué pedido.
    """
    res = disp.resolucion

    # La clienta señaló uno y se pudo resolver.
    if res is not None and res.ok:
        return None, res.id

    # Señaló uno y NO se pudo. Aquí no se salva ni el caso fácil: dijo «el
    # segundo» y no cuadró, así que asumir cualquier otro es traicionar lo
    # que pidió.
    if res is not None and res.estado is Estado.AMBIGUA:
        return Decision(
            Veredicto.PREGUNTAR,
            accion,
            falta=Requisito.PEDIDO,
            candidatos=res.candidatos,
            motivo=res.origen,
        ), None
    if res is not None and res.estado is Estado.SIN_DATOS:
        return Decision(
            Veredicto.PREGUNTAR,
            accion,
            falta=Requisito.PEDIDO,
            candidatos=tuple(disp.pedidos),
            motivo=res.origen,
        ), None

    # No señaló ninguno. Hay que deducirlo de lo que tiene abierto.
    #
    # Para cobrar o cancelar se mira solo entre los que tienen saldo: si
    # tiene tres pedidos pero solo uno debe plata, «ya pagué» no es ambiguo
    # por más que existan los otros dos. Restringir el universo a lo que la
    # frase puede significar quita casi todas las preguntas innecesarias.
    universo = (
        disp.pedidos_con_saldo if critica and disp.pedidos_con_saldo else disp.pedidos
    )

    if not universo:
        return Decision(
            Veredicto.PREGUNTAR,
            accion,
            falta=Requisito.PEDIDO,
            motivo="no tiene ningún pedido al que se pueda referir",
        ), None
    if len(universo) == 1:
        return None, universo[0].id  # no hay ambigüedad posible

    if critica:
        return Decision(
            Veredicto.PREGUNTAR,
            accion,
            falta=Requisito.PEDIDO,
            candidatos=tuple(universo),
            motivo=f"tiene {len(universo)} pedidos a los que podría referirse y "
            f"esto no se puede deshacer",
        ), None

    # No es crítica y hay varios. NO se elige uno a escondidas: se sigue sin
    # objetivo, y la herramienta los muestra todos.
    #
    # Elegir el más reciente en silencio parecía más ágil y era peor por dos
    # razones: la clienta que pregunta «¿cómo van mis pedidos?» quiere ver los
    # suyos, y mostrarlos es lo único que deja registrada la lista que hace
    # resoluble el «¿y el segundo?» del mensaje siguiente.
    return None, None
