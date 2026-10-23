"""El CONTEXTO OPERATIVO: lo que está vivo AHORA, sacado de la base de datos.

════════════════════════════════════════════════════════════════════════════
EL FALLO QUE LO TRAJO (conversación real con el número de prueba de Meta)
════════════════════════════════════════════════════════════════════════════
El pedido PED-2026-4826 se despachó. Cinco minutos después la clienta escribió
«me puedes montar cómo quedaría uno completamente azul?» y el bot le CAMBIÓ LOS
COLORES AL PEDIDO YA DESPACHADO. Luego «comencemos de 0» le volvió a enseñar
ese mismo pedido, y «quiero nombre Roberto y color rosado» lo reescribió otra
vez. Un anillo que ya iba en el camión, modificado tres veces por un chat.

La causa no era el modelo. Era de dónde salía el contexto:

  · El `Proceso` de la compra vive en la memoria CONVERSACIONAL doce días,
    y seguía «abierto» aunque su pedido ya estuviera despachado o entregado.
  · El foco («ese») seguía apuntando a ese pedido.
  · Y al revés: una clienta con un anillo EN PRODUCCIÓN que vuelve a los
    trece días («quiero cambiar la talla») ya no tenía proceso, así que el bot
    no sabía de qué pedido hablaba.

════════════════════════════════════════════════════════════════════════════
LA REGLA
════════════════════════════════════════════════════════════════════════════
La fuente de verdad de QUÉ ESTÁ VIVO es el estado del pedido en la base de
datos, no la memoria de la conversación. Por eso cada turno empieza así:

    1. se leen los pedidos ACTIVOS de la clienta (estados no terminales)
    2. se mira a qué pedidos apunta el contexto guardado
    3. todo lo que apunte a un pedido CERRADO se archiva: sale del contexto
       normal y deja de poder recibir datos, pagos o cambios
    4. los procesos de un pedido ACTIVO no caducan mientras el pedido viva

Los pedidos cerrados siguen en la base de datos intactos. Solo se consultan
cuando la clienta los señala a propósito (ver `app/domain/historial.py`).

Todo aquí es Python puro: entra lo que ya se leyó, sale un objeto. Se prueba
en microsegundos y no puede escribir nada.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from app.domain.contexto import ContextoConversacional, Proceso, TipoProceso
from app.domain.order_state import ANTICIPO_OK, TERMINALES, OrderState

#: Estados en los que lo que falta es el ABONO.
ESPERAN_ABONO = frozenset(
    {
        OrderState.BORRADOR,
        OrderState.COTIZADO,
        OrderState.CONFIRMADO,
        OrderState.ESPERANDO_ANTICIPO,
    }
)
#: Estados en los que lo que falta es el SALDO.
ESPERAN_SALDO = frozenset({OrderState.PRODUCCION_LISTA, OrderState.ESPERANDO_SALDO})
#: Ya no se debe nada: lo confirmó una persona moviendo el pedido.
YA_PAGADOS = frozenset(
    {OrderState.SALDO_PAGADO, OrderState.DESPACHADO, OrderState.ENTREGADO}
)


def pendiente_de_pago(pedido) -> int:
    """Cuánto debe de verdad, en COP. Nunca negativo.

    ════════════════════════════════════════════════════════════════════════
    POR QUÉ NO ES SOLO `total - pagado`
    ════════════════════════════════════════════════════════════════════════
    El panel del taller mueve los pedidos de estado pero NO apunta montos
    (`anticipo_pagado_cop` se queda en 0). Con la resta a secas, un anillo
    DESPACHADO le decía a la clienta «te queda por pagar $200.000» — lo dijo,
    textual, en la conversación de prueba. Decirle a alguien que pagó que
    todavía debe todo es la forma más rápida de perderla.

    El ESTADO lo movió una persona que vio la plata en la cuenta, así que
    manda sobre un campo que nadie rellenó. No se inventa ningún pago: se lee
    lo que la persona ya confirmó.
    """
    estado = OrderState(pedido.estado)
    if estado in YA_PAGADOS:
        return 0
    pagado = pedido.anticipo_pagado_cop + pedido.saldo_pagado_cop
    if estado in ANTICIPO_OK:
        pagado = max(pagado, pedido.anticipo_cop + pedido.saldo_pagado_cop)
    return max(0, int(pedido.total_cop) - int(pagado))


@dataclass(frozen=True)
class PedidoVivo:
    """Un pedido activo, resumido. Lo que el turno necesita saber de él."""

    id: str
    codigo: str
    estado: OrderState
    creado: datetime
    #: Qué pago espera: "abono", "saldo" o "" si no espera ninguno.
    espera_pago: str = ""
    #: El pedido nació sin talla y todavía no la tiene.
    falta_talla: bool = False

    @classmethod
    def de(cls, pedido) -> PedidoVivo:
        estado = OrderState(pedido.estado)
        espera = (
            "abono"
            if estado in ESPERAN_ABONO
            else "saldo"
            if estado in ESPERAN_SALDO
            else ""
        )
        falta_talla = bool(pedido.items) and any(
            i.personalizacion.talla is None for i in pedido.items
        )
        return cls(
            id=pedido.id,
            codigo=pedido.codigo,
            estado=estado,
            creado=pedido.created_at,
            espera_pago=espera,
            falta_talla=falta_talla,
        )


@dataclass(frozen=True)
class Operativo:
    """El contexto operativo del turno. Se construye, no se guarda.

    NO lleva pedidos cerrados, y es a propósito: lo único que sabe de ellos es
    CUÁNTOS hay, para poder decir «tienes pedidos anteriores» sin cargarlos.
    """

    activos: tuple[PedidoVivo, ...] = ()
    cerrados: int = 0
    #: Lo que falta en la compra que se está armando, si hay una.
    compra_pendientes: tuple[str, ...] = ()
    #: Procesos que se sacaron del contexto en este turno, y por qué. Va al
    #: registro de decisiones: es lo que explica un turno que «olvidó» algo.
    archivados: tuple[str, ...] = ()

    @property
    def ids_activos(self) -> frozenset[str]:
        return frozenset(p.id for p in self.activos)

    def espera_comprobante(self) -> bool:
        return any(p.espera_pago for p in self.activos)

    def fuente(self) -> str:
        """De dónde sale el contexto de este turno. Para el registro."""
        if self.compra_pendientes:
            return "compra_en_curso"
        if self.activos:
            return "pedido_activo"
        return "sin_contexto"

    def resumen_para_modelo(self) -> str:
        """Una línea de estado para el modelo. Sin nombres, sin teléfonos.

        El modelo no necesita saber CUÁL pedido ni de quién: necesita saber
        que hay uno esperando el abono para entender que «ya te mandé la foto»
        habla del pago. Mandar más sería pagar tokens por datos personales que
        no cambian la interpretación.
        """
        partes: list[str] = []
        if self.activos:
            estados = ", ".join(
                (p.espera_pago and f"uno esperando el {p.espera_pago}")
                or f"uno {p.estado.value.lower().replace('_', ' ')}"
                for p in self.activos[:3]
            )
            partes.append(f"pedidos activos: {len(self.activos)} ({estados})")
            if any(p.falta_talla for p in self.activos):
                partes.append("a un pedido activo le falta la talla")
        if self.compra_pendientes:
            partes.append(
                "armando un anillo, falta: " + ", ".join(self.compra_pendientes)
            )
        if self.cerrados:
            partes.append(f"tiene {self.cerrados} pedido(s) anteriores ya cerrados")
        return "; ".join(partes)


@dataclass
class Saneamiento:
    """Lo que `sanear` decidió. Para el log, no para la clienta."""

    contexto: ContextoConversacional
    archivados: list[str] = field(default_factory=list)


def _pedido_de(proceso: Proceso) -> str | None:
    return proceso.pedido_id or proceso.datos.get("pedido_id")


def ids_referenciados(ctx: ContextoConversacional) -> set[str]:
    """Todos los pedidos a los que apunta el contexto guardado."""
    ids = {x for x in (_pedido_de(p) for p in ctx.procesos) if x}
    ids.update(x for x in (ctx.foco_id, ctx.foco_previo_id) if x)
    ids.update(m.id for m in ctx.menciones if m.tipo == "PEDIDO")
    return ids


def sanear(
    ctx: ContextoConversacional,
    *,
    cerrados: set[str] | frozenset[str],
    activos: set[str] | frozenset[str] = frozenset(),
    ahora: datetime | None = None,
) -> Saneamiento:
    """Saca del contexto todo lo que apunta a un pedido CERRADO.

    `cerrados` son los ids que EXISTEN en la base de datos y están en un estado
    terminal. Un id que no existe NO es cerrado: es una referencia colgando, y
    de eso ya se encarga el ejecutor volviendo a crear el pedido (ver
    `Ejecutor._cerrar_si_esta_completo`). Mezclar los dos casos tiraría una
    compra que se puede recuperar.

    `activos` hace que los procesos de un pedido vivo no caduquen: una clienta
    con el anillo en el taller puede volver a los veinte días.
    """
    archivados: list[str] = []
    vivos: list[Proceso] = []
    for proceso in ctx.procesos:
        pedido = _pedido_de(proceso)
        if pedido and pedido in cerrados:
            archivados.append(f"{proceso.tipo.value} de un pedido cerrado")
            continue
        if not proceso.vivo(ahora) and not (pedido and pedido in activos):
            continue  # caducó por tiempo, como siempre
        vivos.append(proceso)

    cambios: dict = {"procesos": vivos}
    if ctx.foco_id in cerrados:
        cambios["foco_id"] = None
        cambios["foco_tipo"] = None
        archivados.append("foco en un pedido cerrado")
    if ctx.foco_previo_id in cerrados:
        cambios["foco_previo_id"] = None
    menciones = [
        m
        for m in ctx.menciones_vigentes(ahora)
        if not (m.tipo == "PEDIDO" and m.id in cerrados)
    ]
    cambios["menciones"] = menciones
    if len(menciones) != len(ctx.menciones_vigentes(ahora)):
        archivados.append("lista con pedidos cerrados")

    return Saneamiento(ctx.model_copy(update=cambios), archivados)


def construir(
    ctx: ContextoConversacional,
    pedidos_activos: list,
    *,
    cerrados: int = 0,
    archivados: list[str] | tuple[str, ...] = (),
) -> Operativo:
    """El `Operativo` del turno, a partir de lo ya leído."""
    compra = compra_en_curso(ctx)
    return Operativo(
        activos=tuple(
            PedidoVivo.de(o)
            for o in pedidos_activos
            if OrderState(o.estado) not in TERMINALES
        ),
        cerrados=cerrados,
        compra_pendientes=tuple(compra.pendientes) if compra else (),
        archivados=tuple(archivados),
    )


def compra_en_curso(ctx: ContextoConversacional) -> Proceso | None:
    """La compra a medias más reciente, si hay una."""
    return next((p for p in ctx.abiertos(TipoProceso.COMPRA) if p.pendientes), None)
