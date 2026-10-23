"""Las notas internas de Lía: lo que anota desde el panel y la clienta no ve.

════════════════════════════════════════════════════════════════════════════
POR QUÉ (Camilo, 27/09)
════════════════════════════════════════════════════════════════════════════
Al mover un pedido —abono confirmado, entra al taller, terminado— o al revisar
la talla, Lía sabe cosas que no le dice a la clienta: «Talla 8, es la que
mejor corresponde con la foto», «la foto no se ve clara, conviene confirmar».
Esas cosas tienen que quedar en tres sitios y sin mezclarse con la charla:

  · en Chatwoot, como NOTA PRIVADA (la clienta no la ve), con una cabecera
    que dice de qué es, para poder buscarla y filtrarla;
  · en la memoria de la conversación, en una lista APARTE (`notas_internas`),
    para que la asesora la lea como contexto y nunca como algo que escribió
    la clienta;
  · con su tipo, su pedido y su etapa: se pueden clasificar.

El mensaje a la clienta, si Lía escribe uno, va por otro lado (WhatsApp, por
la outbox, y copiado a Chatwoot como mensaje normal).
"""

from __future__ import annotations

from datetime import UTC, datetime

from app.domain.order_state import OrderState

S = OrderState

#: De qué es una nota, según a dónde se movió el pedido. Palabras cortas y
#: estables: son las que se filtran.
TIPO_POR_ESTADO: dict[OrderState, str] = {
    S.ESPERANDO_ANTICIPO: "abono",
    S.EN_REVISION_PAGO: "pago",
    S.ANTICIPO_PAGADO: "abono",
    S.EN_PRODUCCION: "taller",
    S.PRODUCCION_LISTA: "terminado",
    S.ESPERANDO_SALDO: "terminado",
    S.SALDO_PAGADO: "saldo",
    S.DESPACHADO: "despacho",
    S.ENTREGADO: "entrega",
    S.CANCELADO: "cancelación",
    S.REEMBOLSO: "reembolso",
}

#: Cómo se lee la etapa en la cabecera de la nota.
ETAPA_LEGIBLE: dict[OrderState, str] = {
    S.ESPERANDO_ANTICIPO: "Esperando abono",
    S.EN_REVISION_PAGO: "Verificando pago",
    S.ANTICIPO_PAGADO: "Abono confirmado",
    S.EN_PRODUCCION: "En el taller",
    S.PRODUCCION_LISTA: "Terminado",
    S.ESPERANDO_SALDO: "Terminado, esperando saldo",
    S.SALDO_PAGADO: "Saldo confirmado",
    S.DESPACHADO: "Despachado",
    S.ENTREGADO: "Entregado",
    S.CANCELADO: "Cancelado",
    S.REEMBOLSO: "Reembolso",
}

#: Tope de una nota. Es una nota, no un informe.
LARGO_MAXIMO = 1000

#: Cuántas se guardan por conversación. Las viejas se caen solas; en Chatwoot
#: quedan todas.
GUARDADAS = 40


def nota_de_pedido(
    texto: str, *, codigo: str, destino: OrderState | str, autor: str = "panel"
) -> dict:
    """La nota que Lía escribió al mover un pedido."""
    estado = OrderState(destino)
    return _nota(
        texto,
        tipo=TIPO_POR_ESTADO.get(estado, "pedido"),
        pedido=codigo,
        etapa=ETAPA_LEGIBLE.get(estado, estado.value),
        autor=autor,
    )


def nota_de_talla(texto: str, *, codigo: str = "", autor: str = "panel") -> dict:
    """La nota de cuando Lía confirma o corrige la talla."""
    return _nota(texto, tipo="talla", pedido=codigo, etapa="", autor=autor)


def _nota(texto: str, *, tipo: str, pedido: str, etapa: str, autor: str) -> dict:
    return {
        "cuando": datetime.now(UTC).isoformat(timespec="seconds"),
        "tipo": tipo,
        "pedido": pedido,
        "etapa": etapa,
        "texto": " ".join((texto or "").split())[:LARGO_MAXIMO],
        "autor": autor,
    }


def para_chatwoot(nota: dict) -> str:
    """«🗒️ NOTA INTERNA · talla · PED-2026-0001» y debajo el texto.

    La cabecera es fija para poder buscar en Chatwoot «NOTA INTERNA · talla».
    """
    cabecera = " · ".join(
        x
        for x in (
            "🗒️ NOTA INTERNA",
            nota.get("tipo"),
            nota.get("pedido"),
            nota.get("etapa"),
        )
        if x
    )
    return f"{cabecera}\n{nota.get('texto', '')}"
