"""El seguimiento: en qué va cada conversación y qué necesita de Lía.

════════════════════════════════════════════════════════════════════════════
POR QUÉ UN MÓDULO APARTE
════════════════════════════════════════════════════════════════════════════
Chatwoot es donde Lía hace el seguimiento de todo (decisión de Camilo, 19/09).
Para que sirva, cada conversación tiene que decir de un vistazo DOS cosas:

  · la ETAPA: dónde va la venta (una sola, se mueve sola);
  · las ALERTAS: lo que necesita a una persona (pueden ser varias o ninguna).

Se calcula aquí, en Python puro, a partir del borrador de la conversación y
del pedido. Así Chatwoot, el panel o lo que venga mañana muestran lo MISMO, y
la regla se prueba sin red. El adaptador solo traduce esto a etiquetas.

Los nombres son las etiquetas tal cual (Chatwoot solo admite letras, números
y guiones). El número delante es para que se ordenen solas en la barra lateral.
"""

from __future__ import annotations

from dataclasses import dataclass, field

#: Las etapas, en el orden de la venta: (etiqueta, descripción, color).
ETAPAS: tuple[tuple[str, str, str], ...] = (
    ("01-consulta", "Preguntó; todavía no ha escogido nada", "#90A4AE"),
    ("02-disenando", "Armando su anillo con el bot", "#42A5F5"),
    ("03-esperando-abono", "Pedido tomado y cuentas enviadas: falta el abono", "#FFA726"),
    ("04-abono-por-verificar", "Mandó el comprobante del abono: VERIFICAR", "#E53935"),
    ("05-en-taller", "Abono verificado: se está fabricando", "#8E24AA"),
    ("06-listo-cobrar-saldo", "Anillo listo, fotos enviadas: falta el saldo", "#FB8C00"),
    ("07-saldo-por-verificar", "Mandó el comprobante del saldo: VERIFICAR", "#E53935"),
    ("08-por-despachar", "Saldo verificado: llevar a Coordinadora", "#00897B"),
    ("09-despachado", "Va en camino", "#43A047"),
    ("10-entregado", "Le llegó", "#2E7D32"),
    ("99-cancelado", "Cancelado o reembolsado", "#616161"),
)
ETIQUETAS_DE_ETAPA = frozenset(e[0] for e in ETAPAS)

#: Lo que necesita a una persona: (etiqueta, descripción, color).
ALERTAS: tuple[tuple[str, str, str], ...] = (
    (
        "necesita-persona",
        "La clienta pidió una persona, hay una queja o un caso raro",
        "#D50000",
    ),
    ("pago-por-verificar", "Hay un comprobante por verificar en la cuenta", "#C51162"),
    (
        "datos-incompletos",
        "Pagó pero al pedido le faltan datos: no entra al taller",
        "#FF6D00",
    ),
    (
        "confirmar-antes-de-fabricar",
        "Algo que mirar antes de fundir (talla dudosa, grabado raro)",
        "#FFAB00",
    ),
    ("tiene-fecha-limite", "Necesita el anillo para una fecha", "#6200EA"),
    (
        "falta-direccion",
        "Pagó el abono y falta la dirección de entrega (o si lo recoge)",
        "#0091EA",
    ),
)
ETIQUETAS_DE_ALERTA = frozenset(a[0] for a in ALERTAS)

#: Lo que Lía hace DESDE Chatwoot poniendo una etiqueta (sirve en la app del
#: celular). El sistema lo ejecuta, quita la etiqueta y deja una nota con el
#: resultado: (etiqueta, qué hace, color, estados a los que lleva, en orden).
ACCIONES: tuple[tuple[str, str, str, tuple[str, ...]], ...] = (
    (
        "hacer-abono-ok",
        "Ya verifiqué el abono: pasa al taller (le avisa a la clienta)",
        "#1B5E20",
        ("ANTICIPO_PAGADO", "EN_PRODUCCION"),
    ),
    (
        "hacer-anillo-listo",
        "El anillo quedó: le manda las fotos del panel y el cobro del saldo",
        "#1B5E20",
        ("PRODUCCION_LISTA", "ESPERANDO_SALDO"),
    ),
    (
        "hacer-saldo-ok",
        "Ya verifiqué el saldo: queda por despachar",
        "#1B5E20",
        ("SALDO_PAGADO",),
    ),
    (
        "hacer-despachado",
        "Ya lo llevé a Coordinadora (le avisa a la clienta)",
        "#1B5E20",
        ("DESPACHADO",),
    ),
    ("hacer-entregado", "Ya le llegó", "#1B5E20", ("ENTREGADO",)),
    # No mueve el pedido: hace que el bot vuelva a pedir lo que falta y le
    # cuente a Lía lo que tiene guardado. Ver `Container._repreguntar`.
    (
        "hacer-preguntar-lo-que-falta",
        "El bot se trabó: que vuelva a pedir lo que falta y me diga qué tiene",
        "#E65100",
        (),
    ),
    # Tampoco mueve el pedido: le devuelve la conversación al bot (09/10). Es la
    # forma de devolverla desde el celular; resolver ya NO la devuelve.
    (
        "hacer-devolver-al-bot",
        "Ya terminé: que la siga atendiendo VentaBot",
        "#4A148C",
        (),
    ),
)
ETIQUETAS_DE_ACCION = frozenset(a[0] for a in ACCIONES)
DESTINOS_DE_ACCION: dict[str, tuple[str, ...]] = {a[0]: a[3] for a in ACCIONES}

#: Todas las que maneja el sistema. Las demás etiquetas son de Lía y no se tocan.
ETIQUETAS_DEL_SISTEMA = ETIQUETAS_DE_ETAPA | ETIQUETAS_DE_ALERTA | ETIQUETAS_DE_ACCION

#: Las alertas que dejan la conversación ABIERTA (en la bandeja de Lía).
ALERTAS_QUE_ABREN = frozenset(
    {"necesita-persona", "pago-por-verificar", "datos-incompletos", "falta-direccion"}
)

_ETAPA_DEL_PEDIDO: dict[str, str] = {
    "BORRADOR": "02-disenando",
    "COTIZADO": "02-disenando",
    "CONFIRMADO": "03-esperando-abono",
    "ESPERANDO_ANTICIPO": "03-esperando-abono",
    "ANTICIPO_PAGADO": "05-en-taller",
    "EN_PRODUCCION": "05-en-taller",
    "PRODUCCION_LISTA": "06-listo-cobrar-saldo",
    "ESPERANDO_SALDO": "06-listo-cobrar-saldo",
    "SALDO_PAGADO": "08-por-despachar",
    "DESPACHADO": "09-despachado",
    "ENTREGADO": "10-entregado",
    "CANCELADO": "99-cancelado",
    "REEMBOLSO": "99-cancelado",
}


@dataclass(frozen=True)
class Seguimiento:
    etapa: str
    alertas: frozenset[str] = field(default_factory=frozenset)

    @property
    def etiquetas(self) -> list[str]:
        return [self.etapa, *sorted(self.alertas)]

    @property
    def abierta(self) -> bool:
        """«Abierta» en Chatwoot = necesita a Lía. «Pendiente» = la lleva el bot."""
        return bool(self.alertas & ALERTAS_QUE_ABREN)


def seguimiento(
    *,
    estado_pedido: str = "",
    anticipo_pagado: bool = False,
    diseno_empezado: bool = False,
    escalada: bool = False,
    pagado_sin_pedido: bool = False,
    por_confirmar: bool = False,
    fecha_limite: bool = False,
    falta_direccion: bool = False,
) -> Seguimiento:
    """La etapa y las alertas de una conversación. Función pura.

    `anticipo_pagado` distingue qué pago se revisa en EN_REVISION_PAGO: si el
    abono ya entró, el comprobante es el del saldo.
    """
    if estado_pedido == "EN_REVISION_PAGO":
        etapa = "07-saldo-por-verificar" if anticipo_pagado else "04-abono-por-verificar"
    elif estado_pedido:
        etapa = _ETAPA_DEL_PEDIDO.get(estado_pedido, "02-disenando")
    else:
        etapa = "02-disenando" if diseno_empezado else "01-consulta"

    alertas = set()
    if escalada:
        alertas.add("necesita-persona")
    if estado_pedido == "EN_REVISION_PAGO":
        alertas.add("pago-por-verificar")
    if pagado_sin_pedido:
        alertas.add("datos-incompletos")
        alertas.add("pago-por-verificar")
    if por_confirmar and estado_pedido not in ("DESPACHADO", "ENTREGADO", "CANCELADO"):
        alertas.add("confirmar-antes-de-fabricar")
    if fecha_limite and estado_pedido not in ("DESPACHADO", "ENTREGADO", "CANCELADO"):
        alertas.add("tiene-fecha-limite")
    if falta_direccion and estado_pedido not in (
        "",
        "ESPERANDO_ANTICIPO",
        "DESPACHADO",
        "ENTREGADO",
        "CANCELADO",
        "REEMBOLSO",
    ):
        alertas.add("falta-direccion")
    return Seguimiento(etapa=etapa, alertas=frozenset(alertas))


def nuevas_etiquetas(actuales: list[str], s: Seguimiento) -> list[str]:
    """Las etiquetas que tiene que quedar teniendo la conversación.

    Se reemplazan SOLO las del sistema: las que Lía puso a mano («vip»,
    «regalo») se quedan. Las de acción (`hacer-…`) también se quedan: las quita
    quien las ejecuta, no quien recalcula la etapa.
    """
    de_lia = [
        e
        for e in actuales
        if e not in ETIQUETAS_DE_ETAPA and e not in ETIQUETAS_DE_ALERTA
    ]
    return sorted(set(de_lia) | set(s.etiquetas))
