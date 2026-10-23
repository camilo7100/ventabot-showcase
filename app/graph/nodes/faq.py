"""Nodo FAQ: responde las preguntas de siempre. SIN LLM redactando.

Este nodo no llama al modelo. El modelo ya hizo su parte en `nlu`: eligió
cuál de las preguntas conocidas era. Aquí solo se busca el texto en una tabla
y se devuelve palabra por palabra.

Eso importa más de lo que parece. Son respuestas sobre garantía, material y
dinero: si el modelo las redactara, algún día diría "un año de garantía" o
"sí manejamos contraentrega". Eso no es un bug, es una promesa comercial que
alguien tendría que cumplir o romper delante de una clienta.

Es además el nodo más barato del sistema: cero tokens, cero latencia, y
resuelve una porción enorme de las conversaciones reales.
"""

from __future__ import annotations

from app.domain.faq import Pregunta, responder
from app.graph.state import ConvState


def faq(state: ConvState) -> dict:
    crudo = (state.get("entities") or {}).get("pregunta")
    try:
        pregunta = Pregunta(crudo)
    except ValueError:
        # El modelo devolvió algo fuera del Enum. No debería poder —el schema
        # lo impide— pero si algún día se cambia el backend de LLM por uno sin
        # decodificación restringida, esto evita un KeyError en producción.
        pregunta = Pregunta.NINGUNA

    texto = responder(pregunta)
    if texto is None:
        # No era una pregunta conocida. No se inventa nada: se ofrece humano.
        return {
            "reply_kind": "handoff",
            "needs_human": True,
            "trace": [f"faq: '{crudo}' no tiene respuesta escrita -> humano"],
        }

    return {
        "reply_kind": "faq",
        "reply_text": texto,
        "reply_slots": {},
        "trace": [f"faq: {pregunta.value}"],
    }
