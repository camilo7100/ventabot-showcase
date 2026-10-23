"""EL ROUTER: aquí vive el determinismo del flujo.

Todo lo que hace es un `dict.get` con default. Sin LLM, sin red, sin estado
oculto. Se testea en microsegundos y cubre TODA tu lógica de flujo.

El LLM devuelve una ETIQUETA (un Enum de 10 valores). Python decide el NODO.
Esa separación es lo que convierte un sistema probabilístico en uno predecible.

Si un día te descubres escribiendo `if "quiere comprar" in respuesta_del_llm`,
volviste al caos. La etiqueta cerrada es innegociable.
"""

from __future__ import annotations

from app.domain.models import Intent
from app.graph.state import ConvState

#: Mapping CERRADO intención -> nodo. Cualquier valor fuera de aquí cae en OTRO.
INTENT_A_NODO: dict[str, str] = {
    Intent.SALUDO.value: "catalogo",
    Intent.CATALOGO.value: "catalogo",
    Intent.COTIZAR.value: "cotizar",
    Intent.CONFIRMAR.value: "crear_pedido",
    Intent.ESTADO.value: "estado_pedido",
    Intent.PAGO.value: "estado_pedido",
    Intent.COMPROBANTE.value: "comprobante",
    Intent.QUEJA.value: "handoff",
    Intent.HUMANO.value: "handoff",
    Intent.PREGUNTA.value: "faq",
    # TALLA y PERSONALIZAR van a `personalizar`, que hoy sabe responder la
    # guía de medición y para todo lo demás llama a un humano. Es deliberado:
    # el llenado de ranuras (colores, grabado, talla) es el paso siguiente de
    # la Fase 2, y hasta que exista es preferible que conteste Lía a que el
    # bot adivine de qué color va un anillo de $200.000.
    Intent.TALLA.value: "personalizar",
    Intent.PERSONALIZAR.value: "personalizar",
    Intent.OTRO.value: "redactar",
}

#: Comandos literales que cortocircuitan el LLM por completo.
#: Son gratis, instantáneos y 100% confiables. Úsalos para lo crítico.
COMANDOS: dict[str, str] = {
    "#humano": "handoff",
    "#agente": "handoff",
    "#asesor": "handoff",
    "#catalogo": "catalogo",
    "#estado": "estado_pedido",
}

#: Intenciones que SIEMPRE ganan, incluso a mitad de un diseño.
ESCAPES: frozenset[str] = frozenset(
    {
        Intent.HUMANO.value,
        Intent.QUEJA.value,
        Intent.PREGUNTA.value,
        Intent.ESTADO.value,
    }
)

#: Pasos del guion en los que se está esperando una respuesta de la clienta.
#: LISTO y ELEGIR_PRODUCTO no están: ahí no hay nada pendiente que leer.
PASOS_EN_CURSO: frozenset[str] = frozenset(
    {
        "COLORES",
        "GRABADO",
        "TALLA",
    }
)

DESTINOS_VALIDOS = {
    "catalogo",
    "cotizar",
    "crear_pedido",
    "estado_pedido",
    "comprobante",
    "faq",
    "personalizar",
    "handoff",
    "redactar",
}


def router(state: ConvState) -> str:
    """Decide el siguiente nodo. Orden de precedencia deliberado.

    1. Escalamiento humano (bandera ya puesta por otro nodo).
    2. Media adjunta -> siempre va a verificación de comprobante.
    3. La intención clasificada.
    4. Default: redactar una respuesta genérica con oferta de humano.
    """
    if state.get("needs_human"):
        return "handoff"

    intent = state.get("intent")

    # SALIDAS DE EMERGENCIA. Se atienden aunque haya un diseño a medias: una
    # clienta que pregunta "¿es plata de verdad?" mientras elige colores no
    # puede recibir "¿de qué color el corazón?" otra vez. Encerrarla en el
    # formulario es la forma más rápida de perderla.
    if intent in ESCAPES:
        return INTENT_A_NODO[intent]

    if state.get("inbound_media"):
        # Una foto cuando se está esperando la talla es la foto del anillo
        # con la regla, no un comprobante de pago. Mandarla al verificador de
        # pagos abriría un caso de revisión falso por cada clienta que mide
        # su dedo.
        if state.get("paso") == "TALLA":
            return "personalizar"
        return "comprobante"

    # CONVERSACIÓN EN CURSO. Si el guion está esperando un dato concreto, el
    # mensaje se interpreta como esa respuesta. Sin esta regla, «morados» se
    # clasificaría como OTRO y el diseño no avanzaría nunca.
    if state.get("paso") in PASOS_EN_CURSO:
        return "personalizar"

    destino = INTENT_A_NODO.get(intent or "", "redactar")

    # Cinturón y tirantes: si alguien edita el mapping mal, no rompemos el grafo.
    return destino if destino in DESTINOS_VALIDOS else "redactar"


def comando_directo(texto: str | None) -> str | None:
    """Atajo sin LLM. Devuelve el nodo destino o None."""
    if not texto:
        return None
    return COMANDOS.get(texto.strip().lower())
