"""Cálculo de precios, anticipo y saldo.

DOS REGLAS QUE NO SE NEGOCIAN
=============================

1. El dinero se representa como ENTERO de pesos (int), nunca como float.
   0.1 + 0.2 != 0.3 en punto flotante, y en dinero eso es un descuadre
   contable permanente. En COP no hay centavos, así que es directo.
   Para porcentajes se usa Decimal, y se convierte a int al final.

2. El saldo se calcula como `total - anticipo`, NUNCA como `total * 0.5`.
   Si redondeas ambos por separado, los dos pagos no suman el total.
   Es un bug clásico y produce un descuadre que nadie encuentra después.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_CEILING, ROUND_HALF_UP, Decimal

from app.domain.models import OrderItem, Product

#: Redondeo del anticipo hacia arriba al múltiplo más cercano, para que el
#: número que ve el cliente quede "limpio" ($75.000 en vez de $74.732).
REDONDEO_ANTICIPO_COP = 1000


@dataclass(frozen=True)
class Cotizacion:
    """Resultado inmutable de cotizar. Sin efectos secundarios."""

    items: tuple[OrderItem, ...]
    subtotal_cop: int
    iva_cop: int
    envio_cop: int
    anticipo_cop: int
    dias_produccion: int
    dias_produccion_max: int = 0
    #: El flete que la clienta paga AL TRANSPORTADOR cuando recibe, no a
    #: nosotros. Se le informa, pero NO entra en el total ni en el saldo.
    #:
    #: Meterlo en el total sería cobrarlo dos veces: una en el link de pago y
    #: otra en la puerta de su casa. Es el tipo de error que no revienta
    #: ningún test y sí revienta la reputación.
    envio_contraentrega_cop: int = 0

    @property
    def total_cop(self) -> int:
        return self.subtotal_cop + self.iva_cop + self.envio_cop

    @property
    def saldo_cop(self) -> int:
        # SIEMPRE por diferencia. Ver regla 2 arriba.
        return self.total_cop - self.anticipo_cop

    def slots(self) -> dict:
        """Los valores que se le pasan a la plantilla de redacción.

        El LLM SOLO puede usar estos números. El validador de salida verifica
        que ningún otro número aparezca en el texto final.
        """
        return {
            "subtotal": self.subtotal_cop,
            "iva": self.iva_cop,
            "envio": self.envio_cop,
            "total": self.total_cop,
            "anticipo": self.anticipo_cop,
            "saldo": self.saldo_cop,
            "dias": self.dias_produccion,
            "dias_max": self.dias_produccion_max or self.dias_produccion,
            "envio_contraentrega": self.envio_contraentrega_cop,
        }


def _redondear_arriba(valor: Decimal, multiplo: int) -> int:
    return int((valor / multiplo).to_integral_value(ROUND_CEILING)) * multiplo


def calcular_iva(base_cop: int, iva_pct: Decimal) -> int:
    return int((Decimal(base_cop) * iva_pct).to_integral_value(ROUND_HALF_UP))


def cotizar(
    productos: dict[str, Product],
    pedido: list[tuple[str, int]],
    *,
    envio_cop: int = 0,
    envio_contraentrega_cop: int = 0,
    anticipo_pct_override: Decimal | None = None,
) -> Cotizacion:
    """Cotiza una lista de (sku, cantidad).

    Args:
        productos: catálogo indexado por SKU (viene del ProductRepository).
        pedido: lista de (sku, cantidad).
        envio_cop: costo de envío que SÍ se cobra en el link de pago.
        envio_contraentrega_cop: flete que la clienta le paga al transportador
            al recibir. Se informa, no se cobra: no entra en el total.
        anticipo_pct_override: fuerza un porcentaje distinto al del producto.

    Raises:
        KeyError: si un SKU no existe. Nunca cotices un SKU que el LLM
            "inventó" — por eso el validador de `Intencion.sku` verifica
            existencia contra el catálogo real.
        ValueError: si el producto está inactivo o la cantidad es inválida.
    """
    if not pedido:
        raise ValueError("no se puede cotizar un pedido vacío")

    items: list[OrderItem] = []
    subtotal = 0
    iva_total = 0
    dias = 0
    dias_max = 0
    anticipo_pct_max = Decimal("0")
    anticipo_fijo_total = 0
    hay_anticipo_fijo = False

    for sku, cantidad in pedido:
        if cantidad < 1:
            raise ValueError(f"cantidad inválida para {sku}: {cantidad}")
        producto = productos[sku]  # KeyError intencional si no existe
        if not producto.activo:
            raise ValueError(f"producto inactivo: {sku}")

        linea_subtotal = producto.precio_cop * cantidad
        subtotal += linea_subtotal
        iva_total += calcular_iva(linea_subtotal, producto.iva_pct)
        dias = max(dias, producto.dias_produccion)
        dias_max = max(dias_max, producto.dias_produccion_max or producto.dias_produccion)
        anticipo_pct_max = max(anticipo_pct_max, producto.anticipo_pct)
        # El abono fijo es POR UNIDAD: dos anillos son dos fundiciones, y cada
        # una cuesta su plata. Sumarlo (en vez de tomar el máximo) es lo que
        # hace que el pedido de dos anillos no arranque medio financiado.
        if producto.anticipo_fijo_cop is not None:
            hay_anticipo_fijo = True
            anticipo_fijo_total += producto.anticipo_fijo_cop * cantidad

        items.append(
            OrderItem(
                sku=sku,
                nombre=producto.nombre,
                cantidad=cantidad,
                precio_unitario_cop=producto.precio_cop,
            )
        )

    total = subtotal + iva_total + envio_cop

    # ORDEN DE PRECEDENCIA, de más específico a más general:
    #   1. el override explícito de quien llama
    #   2. el abono fijo en pesos del producto
    #   3. el porcentaje del producto
    if anticipo_pct_override is not None:
        anticipo = _redondear_arriba(
            Decimal(total) * anticipo_pct_override, REDONDEO_ANTICIPO_COP
        )
    elif hay_anticipo_fijo:
        # Sin redondeo: $60.000 son $60.000. Redondear un número que ya es
        # redondo solo puede empeorarlo.
        anticipo = anticipo_fijo_total
    else:
        anticipo = _redondear_arriba(
            Decimal(total) * anticipo_pct_max, REDONDEO_ANTICIPO_COP
        )

    anticipo = min(anticipo, total)  # nunca cobrar más que el total

    return Cotizacion(
        items=tuple(items),
        subtotal_cop=subtotal,
        iva_cop=iva_total,
        envio_cop=envio_cop,
        anticipo_cop=anticipo,
        dias_produccion=dias,
        dias_produccion_max=dias_max,
        envio_contraentrega_cop=envio_contraentrega_cop,
    )


# ---------------------------------------------------------------------------
# Monto único: la técnica que hace determinística la conciliación manual
# ---------------------------------------------------------------------------

DIGITOS_UNICOS = 1000  # 3 dígitos -> 1000 slots


def monto_con_digitos_unicos(monto_cop: int, order_codigo: str) -> int:
    """Añade 3 dígitos derivados del pedido para poder conciliar transferencias.

    En COP no hay centavos, así que el discriminante son los últimos dígitos:

        $150.000  ->  $150.037     (037 derivado de PED-2026-0417)

    Con 1000 slots y una ventana temporal, el match contra el extracto bancario
    o la notificación de abono es DETERMINÍSTICO. El "descuadre" es de centenas
    de pesos y se le presenta al cliente como "código de verificación".

    Úsalo SOLO en el camino alterno (cliente que insiste en transferir directo).
    En el camino feliz (link de pago + webhook) no hace falta: la `reference`
    de la pasarela ya identifica el pedido.

    NOTA: si tienes muchos pedidos abiertos simultáneamente, verifica colisiones
    contra los `monto_esperado_cop` de los payments PENDIENTE/EN_REVISION antes
    de usarlo, y desplaza +1 hasta encontrar uno libre.
    """
    base = (monto_cop // DIGITOS_UNICOS) * DIGITOS_UNICOS
    sufijo = abs(hash(order_codigo)) % DIGITOS_UNICOS
    candidato = base + sufijo
    # Nunca cobrar menos de lo debido.
    if candidato < monto_cop:
        candidato += DIGITOS_UNICOS
    return candidato


def formatear_cop(monto: int) -> str:
    """$1.234.567 — formato colombiano (punto como separador de miles)."""
    return "$" + f"{monto:,}".replace(",", ".")
