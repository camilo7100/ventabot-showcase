"""Cuándo calla el bot porque está contestando una persona.

════════════════════════════════════════════════════════════════════════════
POR QUÉ HACE FALTA
════════════════════════════════════════════════════════════════════════════
El día que Camilo o Lía entren a escribirle a una clienta —desde el panel,
desde Chatwoot o desde donde sea—, lo peor que puede pasar es que el bot siga
contestando encima. La clienta ve dos voces distintas en el mismo chat, con
dos versiones del pedido, y se acabó la confianza.

Quien ya montó esto coincide en lo mismo: el traspaso a una persona es la
parte difícil, no la conversación. Así que la regla es de una sola línea:

    **si una persona escribió en esta conversación, el bot se calla.**

No se calla para siempre, porque entonces cada intervención mataría el bot en
esa clienta y nadie se acordaría de reactivarlo: se calla un rato (por
defecto 12 horas), y vuelve solo. Quien atiende puede devolvérsela antes con
un botón, o alargarla escribiendo otra vez.

La pausa vive en el contexto de la conversación (`humano_hasta`), que ya se
guarda entero en cada turno: no hace falta una tabla nueva.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from app.domain.models import now_utc

#: Cuánto calla el bot después de que una persona escribe. Doce horas cubre
#: «le contesté anoche y seguimos por la mañana» sin dejar la conversación
#: muerta para siempre.
HORAS_DE_PAUSA = 12


def pausar(horas: float = HORAS_DE_PAUSA, *, desde: datetime | None = None) -> datetime:
    """Hasta cuándo calla el bot."""
    return (desde or now_utc()) + timedelta(hours=horas)


def en_pausa(humano_hasta: datetime | None, *, ahora: datetime | None = None) -> bool:
    """¿La está atendiendo una persona ahora mismo?"""
    if humano_hasta is None:
        return False
    momento = ahora or now_utc()
    if humano_hasta.tzinfo is None:  # guardado sin zona: se asume UTC
        humano_hasta = humano_hasta.replace(tzinfo=momento.tzinfo)
    return humano_hasta > momento


def minutos_restantes(
    humano_hasta: datetime | None, *, ahora: datetime | None = None
) -> int:
    """Para decirle a quien atiende cuánto falta para que el bot vuelva."""
    if humano_hasta is None or not en_pausa(humano_hasta, ahora=ahora):
        return 0
    momento = ahora or now_utc()
    if humano_hasta.tzinfo is None:
        humano_hasta = humano_hasta.replace(tzinfo=momento.tzinfo)
    return max(0, int((humano_hasta - momento).total_seconds() // 60))
