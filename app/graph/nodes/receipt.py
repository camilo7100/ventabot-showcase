"""Nodo de comprobante por imagen.

LEE ESTO ANTES DE TOCAR NADA:

    La imagen NUNCA autoriza un pago. La imagen solo abre un caso.
    Lo que autoriza es una confirmación del lado del dinero.

En Colombia existen aplicaciones falsas que suplantan a Nequi y generan
comprobantes visualmente casi idénticos a los reales. El fraude se concentra
de jueves a domingo, cuando la verificación bancaria es más lenta, y ataca
específicamente ventas por redes sociales.

Por eso este nodo SIEMPRE deja el pago en EN_REVISION y el pedido en
EN_REVISION_PAGO. La aprobación llega después, desde el job de conciliación
que cruza el monto único contra el movimiento bancario real.
"""

from __future__ import annotations

import hashlib

from app.domain.models import (
    DatosComprobante,
    Order,
    Payment,
    PaymentKind,
    PaymentStatus,
)
from app.domain.order_state import OrderState
from app.domain.ports import (
    LLMPort,
    MediaPort,
    OrderRepository,
    PaymentRepository,
)
from app.domain.services import transicionar
from app.graph.state import ConvState

PROMPT_COMPROBANTE = (
    "Eres un extractor de datos de comprobantes de pago colombianos "
    "(Nequi, Bancolombia, Daviplata, PSE, Bre-B).\n"
    "Extrae SOLO lo que ves literalmente en la imagen. "
    "Si un dato no aparece, déjalo en null. NO INVENTES NADA.\n"
    "El monto va en pesos colombianos enteros, sin puntos ni símbolos."
)


def make_comprobante(
    llm: LLMPort,
    media: MediaPort,
    orders: OrderRepository,
    payments: PaymentRepository,
):
    def comprobante(state: ConvState) -> dict:
        refs = state.get("inbound_media") or []
        activo = state.get("active_order")

        if not refs:
            return {
                "reply_kind": "generico",
                "step": "comprobante_sin_media",
                "trace": ["comprobante: sin adjunto"],
            }

        ref = refs[0]
        # Descarga INMEDIATA: en WhatsApp la URL expira a los 5 minutos.
        datos_bin = media.download(ref.get("media_id") or ref.get("url") or "")
        sha = hashlib.sha256(datos_bin).hexdigest()
        url_estable = media.store(datos_bin, filename=f"comprobante-{sha[:12]}.jpg")

        try:
            extraidos = llm.extract(
                PROMPT_COMPROBANTE, "", DatosComprobante, images=[datos_bin]
            )
            assert isinstance(extraidos, DatosComprobante)
            payload = extraidos.model_dump()
        except Exception as exc:
            payload = {"legible": False, "error": str(exc)[:200]}

        if activo is None:
            return {
                "reply_kind": "sin_pedido",
                "step": "comprobante_sin_pedido",
                "trace": ["comprobante: recibido sin pedido activo"],
            }

        pedido = Order(**activo)
        estado = OrderState(pedido.estado)
        tipo = (
            PaymentKind.ANTICIPO
            if estado is OrderState.ESPERANDO_ANTICIPO
            else PaymentKind.SALDO
        )
        esperado = (
            pedido.anticipo_cop if tipo is PaymentKind.ANTICIPO else pedido.saldo_cop
        )

        # Idempotencia: MISMO ARCHIVO = MISMO CASO, no dos.
        # Deliberadamente la `reference` NO incluye el tipo de pago: si el
        # cliente reenvía la misma foto, el estado del pedido ya cambió y el
        # tipo se calcularía distinto, generando un caso duplicado.
        # La clave natural correcta es el hash del archivo.
        reference = f"{pedido.codigo}-IMG-{sha[:12]}"
        existente = payments.get_by_reference(reference)
        if existente is None:
            payments.create(
                Payment(
                    order_id=pedido.id,
                    tipo=tipo,
                    metodo="TRANSFERENCIA",
                    estado=PaymentStatus.EN_REVISION,  # ← NUNCA APROBADO
                    monto_esperado_cop=esperado,
                    gateway_reference=reference,
                    comprobante_media_url=url_estable,
                    comprobante_hash_sha256=sha,
                    comprobante_datos_extraidos=payload,
                )
            )

        if estado is not OrderState.EN_REVISION_PAGO:
            pedido = transicionar(
                orders,
                pedido,
                OrderState.EN_REVISION_PAGO,
                actor="bot",
                motivo="comprobante recibido, pendiente de conciliar",
                idem_key=f"rev:{pedido.id}:{sha[:12]}",
            )

        return {
            "active_order": pedido.model_dump(mode="json"),
            "reply_kind": "comprobante_recibido",
            "reply_slots": {"codigo": pedido.codigo},
            "step": "comprobante_en_revision",
            "trace": [f"comprobante: {sha[:12]} -> EN_REVISION"],
        }

    return comprobante
