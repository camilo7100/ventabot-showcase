"""Quién atiende cada conversación: VentaBot o una persona (09/10).

UN SOLO CRITERIO, igual en Chatwoot del PC, en el celular y en el panel:
quien está ASIGNADO en Chatwoot es quien atiende.

- **VentaBot** (por defecto): contesta el bot. Chatwoot la muestra en
  «Pendiente», que es como Chatwoot trata las conversaciones de un bot.
- **Una persona** (Lía, Camilo): contesta ella y el bot se calla. Pasa
  cuando escribe desde Chatwoot o el panel, cuando está escribiendo o cuando
  se la asigna. Queda en «Abierta».
- **Devolver al bot** es una acción propia y explícita: la macro «🤖 Devolver
  al bot», la etiqueta `hacer-devolver-al-bot`, asignarla a VentaBot o el botón
  «Que siga el bot» del panel.
- **Resolver** solo cierra la conversación: no cambia quién la lleva.
- **Sin asignar** no se deja: vuelve a VentaBot.

La pausa del bot dura 12 h desde lo último que escribió la persona
(`app/domain/atencion.py`); si pasan sin que nadie la devuelva y la clienta
escribe, el bot la retoma y Chatwoot vuelve a mostrar VentaBot.
"""

from __future__ import annotations

import logging

log = logging.getLogger("ventabot.atencion")


def _asignar(c, conv_id: str, quien) -> None:
    """En Chatwoot, sin esperar: "bot" o el id de una persona."""
    crm = getattr(c, "crm", None)
    if crm is not None and hasattr(crm, "asignar") and quien:
        crm.asignar(conv_id, quien)


def la_toma_una_persona(c, conv_id: str, persona) -> None:
    """Una persona tomó la conversación: el bot se calla y en Chatwoot queda
    asignada a ELLA. Sin `persona` (no se sabe quién), solo se calla el bot."""
    c.bot._mundo.pausar_por_humano(conv_id)
    _asignar(c, conv_id, persona)


def devolver_al_bot(c, conv_id: str) -> None:
    """«Que siga el bot»: la acción explícita. NO es resolver."""
    c.bot._mundo.devolver_al_bot(conv_id)
    _asignar(c, conv_id, "bot")
    c.actualizar_seguimiento(conv_id)
    log.info("devuelta al bot: %s", conv_id)
