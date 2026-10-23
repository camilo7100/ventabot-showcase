"""Máquina de estados del PEDIDO.

Esta es la pieza más importante del sistema: es donde vive el dinero.

Las reglas de negocio están codificadas en la tabla TRANSICIONES. Lo que no
está en la tabla es IMPOSIBLE — no por disciplina del equipo, sino por diseño
del sistema. Ni un bug, ni un webhook duplicado, ni el LLM pueden saltárselo.

Las dos reglas críticas, escritas como huecos deliberados en la tabla:
  * NO existe ESPERANDO_ANTICIPO -> EN_PRODUCCION  (no se produce sin cobrar)
  * NO existe PRODUCCION_LISTA   -> DESPACHADO     (no se despacha sin cobrar)

No confundas esta máquina con la de la CONVERSACIÓN (el checkpoint de LangGraph):
  - Conversación: dónde va el diálogo. Vive horas. Se puede perder sin drama.
  - Pedido:       dónde va el negocio. Vive semanas. NO se puede perder jamás.
"""

from __future__ import annotations

from enum import Enum


class OrderState(str, Enum):
    BORRADOR = "BORRADOR"
    COTIZADO = "COTIZADO"
    CONFIRMADO = "CONFIRMADO"
    ESPERANDO_ANTICIPO = "ESPERANDO_ANTICIPO"
    EN_REVISION_PAGO = "EN_REVISION_PAGO"
    ANTICIPO_PAGADO = "ANTICIPO_PAGADO"
    EN_PRODUCCION = "EN_PRODUCCION"
    PRODUCCION_LISTA = "PRODUCCION_LISTA"
    ESPERANDO_SALDO = "ESPERANDO_SALDO"
    SALDO_PAGADO = "SALDO_PAGADO"
    DESPACHADO = "DESPACHADO"
    ENTREGADO = "ENTREGADO"
    CANCELADO = "CANCELADO"
    REEMBOLSO = "REEMBOLSO"


S = OrderState

TRANSICIONES: dict[OrderState, set[OrderState]] = {
    S.BORRADOR: {S.COTIZADO, S.CANCELADO},
    S.COTIZADO: {S.COTIZADO, S.CONFIRMADO, S.CANCELADO},  # re-cotizar permitido
    S.CONFIRMADO: {S.ESPERANDO_ANTICIPO, S.CANCELADO},
    S.ESPERANDO_ANTICIPO: {S.ANTICIPO_PAGADO, S.EN_REVISION_PAGO, S.CANCELADO},
    S.EN_REVISION_PAGO: {
        S.ANTICIPO_PAGADO,
        S.SALDO_PAGADO,
        S.ESPERANDO_ANTICIPO,
        S.ESPERANDO_SALDO,
        S.CANCELADO,
    },
    S.ANTICIPO_PAGADO: {S.EN_PRODUCCION, S.REEMBOLSO},
    S.EN_PRODUCCION: {S.PRODUCCION_LISTA, S.REEMBOLSO},
    S.PRODUCCION_LISTA: {S.ESPERANDO_SALDO},
    S.ESPERANDO_SALDO: {S.SALDO_PAGADO, S.EN_REVISION_PAGO},
    S.SALDO_PAGADO: {S.DESPACHADO, S.REEMBOLSO},
    S.DESPACHADO: {S.ENTREGADO},
    # terminales
    S.ENTREGADO: set(),
    S.CANCELADO: set(),
    S.REEMBOLSO: set(),
}

TERMINALES = {s for s, destinos in TRANSICIONES.items() if not destinos}

#: Estados en los que el pedido ya cobró el anticipo (puede producirse).
ANTICIPO_OK = {
    S.ANTICIPO_PAGADO,
    S.EN_PRODUCCION,
    S.PRODUCCION_LISTA,
    S.ESPERANDO_SALDO,
    S.SALDO_PAGADO,
    S.DESPACHADO,
    S.ENTREGADO,
}

#: Mensaje que se le muestra al cliente por estado. Datos, no lógica.
ETIQUETA_CLIENTE: dict[OrderState, str] = {
    S.BORRADOR: "estamos armando tu pedido",
    S.COTIZADO: "te pasamos la cotización, esperamos tu confirmación",
    S.CONFIRMADO: "pedido confirmado, generando el link de pago",
    S.ESPERANDO_ANTICIPO: "esperando el pago del anticipo",
    S.EN_REVISION_PAGO: "estamos verificando tu pago",
    S.ANTICIPO_PAGADO: "anticipo confirmado, entra a producción",
    S.EN_PRODUCCION: "en producción",
    S.PRODUCCION_LISTA: "producción terminada",
    S.ESPERANDO_SALDO: "esperando el pago del saldo para despachar",
    S.SALDO_PAGADO: "saldo confirmado, alistando el envío",
    S.DESPACHADO: "despachado",
    S.ENTREGADO: "entregado",
    S.CANCELADO: "cancelado",
    S.REEMBOLSO: "en proceso de reembolso",
}


class TransicionInvalida(Exception):
    """Se intentó una transición que no está en la tabla."""

    def __init__(self, actual: OrderState, destino: OrderState) -> None:
        self.actual = actual
        self.destino = destino
        super().__init__(
            f"Transición no permitida: {actual.value} -> {destino.value}. "
            f"Permitidas desde {actual.value}: "
            f"{sorted(s.value for s in TRANSICIONES[actual]) or '(estado terminal)'}"
        )


def puede_transicionar(actual: OrderState, destino: OrderState) -> bool:
    return destino in TRANSICIONES[actual]


def validar_transicion(actual: OrderState, destino: OrderState) -> None:
    """Lanza TransicionInvalida si el salto no está permitido.

    Llamar SIEMPRE antes de escribir el nuevo estado en el repositorio.
    """
    if not puede_transicionar(actual, destino):
        raise TransicionInvalida(actual, destino)


def es_terminal(estado: OrderState) -> bool:
    return estado in TERMINALES


def alcanzables(desde: OrderState) -> set[OrderState]:
    """Cierre transitivo: todos los estados alcanzables desde `desde`.

    Útil para tests de invariantes ("desde COTIZADO no se debe poder llegar a
    DESPACHADO sin pasar por SALDO_PAGADO") y para dibujar el grafo.
    """
    vistos: set[OrderState] = set()
    pila = [desde]
    while pila:
        actual = pila.pop()
        for siguiente in TRANSICIONES[actual]:
            if siguiente not in vistos:
                vistos.add(siguiente)
                pila.append(siguiente)
    return vistos
