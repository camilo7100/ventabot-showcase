"""Nodo de redacción + la compuerta de validación de salida.

PRINCIPIO: para el ~90% de las respuestas NO necesitas LLM.
Una plantilla con slots es más rápida, más barata, y 100% determinista.

Cuando sí uses el LLM (respuestas realmente abiertas), la salida pasa por
`validar_numeros()`: ningún número del texto puede ser un número que no le
dimos en los slots. Un precio inventado cuesta plata real.
"""

from __future__ import annotations

import re

from app.domain.pricing import formatear_cop
from app.graph.state import ConvState

#: `reply_kind` cuyo texto ya viene listo del nodo y no se toca.
KINDS_TEXTO_LITERAL = {"faq", "guion"}

#: Plantillas por `reply_kind`. Datos, no lógica. Fáciles de editar sin tocar código.
PLANTILLAS: dict[str, str] = {
    "catalogo": (
        "¡Hola! 👋 Este es nuestro portafolio. "
        "Escogé el que te guste y me decís cuántos querés."
    ),
    "falta_sku": (
        "Perfecto. ¿Cuál de los productos te interesa? "
        "Te muestro el portafolio para que escojás."
    ),
    "cotizacion": (
        "Listo. {cantidad} x {sku}\n\n"
        "Subtotal: {subtotal}\n"
        "IVA: {iva}\n"
        "Envío: {envio}\n"
        "*Total: {total}*\n\n"
        "Para arrancar producción necesito un anticipo de *{anticipo}* "
        "y el saldo de {saldo} antes del envío.\n"
        "Tiempo de producción: {dias} días hábiles."
    ),
    "link_anticipo": (
        "¡Gracias! Tu pedido es *{codigo}*.\n\n"
        "Anticipo a pagar: *{anticipo}*\n"
        "Saldo antes del envío: {saldo}\n\n"
        "Pagá con el botón de abajo 👇 Apenas confirme el pago, "
        "arrancamos producción y te aviso."
    ),
    "estado": (
        "Tu pedido *{codigo}* está: {estado}.\n\n"
        "Total: {total} · Anticipo: {anticipo} · Saldo: {saldo}"
    ),
    "comprobante_recibido": (
        "Recibí tu comprobante del pedido *{codigo}* 🧾\n\n"
        "Lo estoy verificando contra el movimiento del banco. "
        "Apenas confirme, te aviso y arrancamos. "
        "Normalmente toma unos minutos en horario hábil."
    ),
    "sin_pedido": (
        "No encuentro un pedido activo tuyo. ¿Querés que te muestre el portafolio?"
    ),
    "error_cotizacion": (
        "Se me enredó algo con esa cotización. "
        "Ya le paso tu mensaje a una persona del equipo. 🙏"
    ),
    "handoff": ("Listo, ya le avisé a alguien del equipo. Te escriben en un momento. 🙌"),
    "generico": (
        "No estoy seguro de haber entendido. "
        "¿Querés ver el portafolio, consultar tu pedido, o hablar con alguien?"
    ),
}

#: Slots cuyo valor se formatea como dinero colombiano antes de sustituir.
SLOTS_DINERO = {
    "subtotal",
    "iva",
    "envio",
    "total",
    "anticipo",
    "saldo",
    "anticipo_pagado",
    "saldo_pagado",
}

_NUMERO = re.compile(r"\d[\d.,]*")


def formatear_slots(slots: dict) -> dict:
    out: dict = {}
    for k, v in slots.items():
        if k in SLOTS_DINERO and isinstance(v, int):
            out[k] = formatear_cop(v)
        else:
            out[k] = v
    return out


def validar_numeros(texto: str, slots_formateados: dict) -> bool:
    """Ningún número del texto puede estar fuera de los slots.

    Es la compuerta que impide que el LLM invente un precio. Si falla, el
    grafo cae a la plantilla pura — degradación segura, nunca un número falso.
    """
    permitidos: set[str] = set()
    for v in slots_formateados.values():
        for m in _NUMERO.findall(str(v)):
            permitidos.add(m.strip(".,"))
    encontrados = {m.strip(".,") for m in _NUMERO.findall(texto)}
    return encontrados.issubset(permitidos)


def redactar(state: ConvState) -> dict:
    """Redacción determinista por plantilla.

    Para usar un LLM aquí (tono más natural, respuestas abiertas), genera el
    texto con el modelo y luego:

        if not validar_numeros(texto_llm, slots):
            texto = plantilla_pura

    Nunca al revés.
    """
    kind = state.get("reply_kind") or "generico"

    # Algunos nodos ya traen el texto DEFINITIVO, copiado palabra por palabra
    # de una fuente escrita a mano (las respuestas de FAQ). Ese texto no pasa
    # por plantilla ni por `validar_numeros`, y no debe:
    #
    #   · no hay nada que rellenar
    #   · sus números ($16.500, 925, 6 meses) son parte de la frase, no slots,
    #     así que el validador los rechazaría y borraría una respuesta correcta
    #
    # El validador existe para vigilar al LLM. Aquí no hubo LLM redactando.
    if kind in KINDS_TEXTO_LITERAL and state.get("reply_text"):
        return {
            "reply_text": state["reply_text"],
            "step": "redactado",
            "trace": [f"redactar: {kind} (texto literal, sin plantilla)"],
        }

    plantilla = PLANTILLAS.get(kind, PLANTILLAS["generico"])
    slots = formatear_slots(state.get("reply_slots") or {})

    try:
        texto = plantilla.format(**slots)
    except KeyError as exc:
        # Falta un slot: mejor un mensaje genérico que un crash o un {placeholder}.
        texto = PLANTILLAS["generico"]
        return {
            "reply_text": texto,
            "error": f"slot faltante: {exc}",
            "step": "redactado_fallback",
            "trace": [f"redactar: slot faltante {exc}"],
        }

    assert validar_numeros(texto, slots), "plantilla con números fuera de los slots"

    return {
        "reply_text": texto,
        "step": "redactado",
        "trace": [f"redactar: {kind}"],
    }
