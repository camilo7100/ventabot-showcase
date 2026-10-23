"""Servicios de dominio: las operaciones que combinan modelos y repositorios.

Siguen dependiendo SOLO de puertos, nunca de adaptadores concretos.
"""

from __future__ import annotations

from datetime import timedelta

from app.domain.models import (
    Order,
    OrderEvent,
    Payment,
    PaymentKind,
    PaymentStatus,
    new_id,
    now_utc,
)
from app.domain.order_state import OrderState, validar_transicion
from app.domain.ports import (
    ConflictoDeEstado,
    OrderRepository,
    PaymentGateway,
    PaymentRepository,
)
from app.domain.pricing import Cotizacion


def transicionar(
    repo: OrderRepository,
    pedido: Order,
    nuevo: OrderState,
    *,
    actor: str,
    motivo: str = "",
    idem_key: str | None = None,
    payload: dict | None = None,
) -> Order:
    """Avanza el pedido validando la transición y dejando rastro de auditoría.

    Es el ÚNICO camino permitido para cambiar el estado de un pedido.
    No escribas `order.estado = ...` en ninguna otra parte del código.

    Orden de operaciones (importa):
      1. Validar la transición contra la tabla.
      2. Escribir con bloqueo optimista (falla si otro proceso llegó primero).
      3. Registrar el evento de auditoría.

    Idealmente 2 y 3 van en la MISMA transacción de base de datos; el adaptador
    SQL lo hace así. El adaptador de Sheets no puede (no hay transacciones), y
    esa es exactamente una de las razones para migrar.
    """
    actual = OrderState(pedido.estado)
    validar_transicion(actual, nuevo)  # lanza TransicionInvalida

    idem_key = idem_key or f"{pedido.id}:{actual.value}->{nuevo.value}:{new_id()}"

    actualizado = repo.update_status(pedido.id, nuevo, expected_current=actual)
    repo.append_event(
        OrderEvent(
            order_id=pedido.id,
            estado_anterior=actual.value,
            estado_nuevo=nuevo.value,
            actor=actor,
            motivo=motivo,
            payload=payload or {},
            idempotency_key=idem_key,
        )
    )
    return actualizado


def aplicar_cotizacion(pedido: Order, cot: Cotizacion) -> Order:
    """Devuelve una copia del pedido con los montos de la cotización aplicados."""
    return pedido.model_copy(
        update={
            "items": list(cot.items),
            "subtotal_cop": cot.subtotal_cop,
            "iva_cop": cot.iva_cop,
            "envio_cop": cot.envio_cop,
            "envio_contraentrega_cop": cot.envio_contraentrega_cop,
            "total_cop": cot.total_cop,
            "anticipo_cop": cot.anticipo_cop,
            "saldo_cop": cot.saldo_cop,
            "fecha_estimada_entrega": now_utc() + timedelta(days=cot.dias_produccion),
            "updated_at": now_utc(),
        }
    )


def generar_cobro(
    payments: PaymentRepository,
    gateway: PaymentGateway,
    pedido: Order,
    tipo: PaymentKind,
) -> Payment:
    """Crea el registro de pago y el link de la pasarela. IDEMPOTENTE por reference.

    La `reference` es determinística: PED-2026-0417-ANTICIPO. Si ya existe un
    payment con esa reference, se devuelve tal cual en vez de crear otro link.

    Esto importa porque LangGraph RE-EJECUTA nodos completos al reanudar tras un
    interrupt. Sin idempotencia aquí, un handoff humano generaría dos links.
    """
    reference = f"{pedido.codigo}-{tipo.value}"

    existente = payments.get_by_reference(reference)
    if existente is not None:
        return existente

    monto = pedido.anticipo_cop if tipo is PaymentKind.ANTICIPO else pedido.saldo_cop
    if monto <= 0:
        raise ValueError(f"monto inválido para {tipo.value}: {monto}")

    link = gateway.create_link(
        reference=reference,
        amount_cop=monto,
        description=f"{tipo.value.title()} pedido {pedido.codigo}",
    )

    return payments.create(
        Payment(
            order_id=pedido.id,
            tipo=tipo,
            metodo="LINK",
            estado=PaymentStatus.PENDIENTE,
            monto_esperado_cop=monto,
            gateway_reference=reference,
            gateway_transaction_id=link.gateway_id,
            payment_link_url=link.url,
        )
    )


def confirmar_pago(
    orders: OrderRepository,
    payments: PaymentRepository,
    payment: Payment,
    *,
    monto_recibido_cop: int,
    transaction_id: str,
    actor: str = "WEBHOOK",
) -> Order:
    """Aplica un pago verificado y avanza el pedido.

    PRECONDICIÓN: el llamador YA verificó la firma del webhook, YA re-consultó
    la API de la pasarela y YA comprobó la idempotencia del evento. Esta función
    solo hace la parte de dominio.

    Verifica el monto aquí también (defensa en profundidad): un pago por menos
    del esperado no aprueba nada.
    """
    if monto_recibido_cop < payment.monto_esperado_cop:
        raise ValueError(
            f"monto insuficiente: recibido {monto_recibido_cop}, "
            f"esperado {payment.monto_esperado_cop}"
        )

    pedido = orders.get(payment.order_id)
    if pedido is None:
        raise ConflictoDeEstado(f"pedido {payment.order_id} no existe")

    payments.update(
        payment.model_copy(
            update={
                "estado": PaymentStatus.APROBADO,
                "monto_recibido_cop": monto_recibido_cop,
                "gateway_transaction_id": transaction_id,
                "verificado_por": actor,
                "verificado_at": now_utc(),
            }
        )
    )

    destino = (
        OrderState.ANTICIPO_PAGADO
        if payment.tipo is PaymentKind.ANTICIPO
        else OrderState.SALDO_PAGADO
    )
    return transicionar(
        orders,
        pedido,
        destino,
        actor=actor,
        motivo=f"pago {payment.tipo.value} confirmado",
        idem_key=f"pay:{payment.id}:{destino.value}",  # idempotente por pago
        payload={"transaction_id": transaction_id, "monto": monto_recibido_cop},
    )


def siguiente_codigo(anio: int, consecutivo: int) -> str:
    """PED-2026-0417. Legible por humanos y usable como `reference` de pasarela."""
    return f"PED-{anio}-{consecutivo:04d}"
