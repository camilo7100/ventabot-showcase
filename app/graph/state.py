"""Estado conversacional del grafo.

NO confundir con el estado del PEDIDO (app.domain.order_state):
  - Este estado vive en el checkpoint de LangGraph, por thread_id.
  - Se puede perder sin drama (se reinicia el diálogo).
  - El estado del pedido vive en la base de datos y NO se puede perder jamás.
"""

from __future__ import annotations

from operator import add
from typing import Annotated, TypedDict


class ConvState(TypedDict, total=False):
    # --- identidad ---
    conversation_id: str
    channel: str
    sender_id: str
    customer_id: str | None

    # --- entrada del turno ---
    inbound_text: str | None
    inbound_media: list[dict]

    # --- resultado del NLU (ya validado con Pydantic) ---
    intent: str | None
    entities: dict

    # --- contexto cargado desde los repositorios ---
    customer: dict | None
    active_order: dict | None

    # --- el diseño que se está armando en esta conversación ---
    #
    # Es una `Personalizacion` serializada. Vive aquí, en el checkpoint, y NO
    # en la base de datos, mientras se está preguntando: si la conversación se
    # pierde, se vuelve a preguntar y no pasa nada. En el momento en que la
    # clienta confirma, se copia al pedido, que sí es la fuente de verdad.
    #
    # `huellitas_esperadas` viene del producto elegido (1, 2 o 3) y es lo que
    # le dice al guion cuántos pares de colores faltan.
    diseno: dict
    huellitas_esperadas: int
    paso: str

    # --- salida ---
    reply_kind: str | None
    reply_text: str | None
    # `reply_slots` es lo que garantiza el determinismo de datos: los números
    # calculados por Python entran aquí, y el validador de salida comprueba que
    # ningún número del texto final esté fuera de este diccionario.
    reply_slots: dict
    reply_options: list[dict]
    reply_cta_url: str | None
    #: Nombre LÓGICO de la imagen que acompaña la respuesta ("muestrario_circones").
    #: A qué archivo o `media_id` de WhatsApp corresponde lo resuelve el
    #: adaptador del canal: el grafo no sabe de archivos.
    reply_imagen: str | None

    # --- control ---
    step: str
    error: str | None
    needs_human: bool
    nlu_retries: int

    # Reducer: los logs se concatenan entre nodos en vez de sobrescribirse.
    trace: Annotated[list[str], add]


def initial_state(
    *,
    conversation_id: str,
    channel: str,
    sender_id: str,
    text: str | None,
    media: list[dict] | None = None,
) -> ConvState:
    return ConvState(
        conversation_id=conversation_id,
        channel=channel,
        sender_id=sender_id,
        inbound_text=text,
        inbound_media=media or [],
        entities={},
        reply_slots={},
        reply_options=[],
        needs_human=False,
        nlu_retries=0,
        step="START",
        trace=[],
    )
