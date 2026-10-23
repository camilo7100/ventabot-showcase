"""Tests del motor de precios.

El test estrella es `test_anticipo_mas_saldo_siempre_es_igual_al_total`:
es el bug clásico que produce un descuadre contable que nadie encuentra
después. Si alguna vez cambias el cálculo, este test te avisa.
"""

from __future__ import annotations

import dataclasses
from decimal import Decimal

import pytest

from app.domain.models import Product
from app.domain.pricing import (
    Cotizacion,
    calcular_iva,
    cotizar,
    formatear_cop,
    monto_con_digitos_unicos,
)

CATALOGO = {
    "CAM-001": Product(
        sku="CAM-001", nombre="Camiseta", precio_cop=85_000, dias_produccion=5
    ),
    "TAZ-001": Product(
        sku="TAZ-001",
        nombre="Taza",
        precio_cop=35_000,
        dias_produccion=3,
        anticipo_pct=Decimal("0.70"),
    ),
    "OFF-001": Product(
        sku="OFF-001", nombre="Descontinuado", precio_cop=10_000, activo=False
    ),
}


class TestCotizacion:
    def test_calcula_subtotal_iva_y_total(self):
        c = cotizar(CATALOGO, [("CAM-001", 2)], envio_cop=15_000)
        assert c.subtotal_cop == 170_000
        assert c.iva_cop == calcular_iva(170_000, Decimal("0.19"))
        assert c.total_cop == c.subtotal_cop + c.iva_cop + 15_000

    def test_multiples_productos(self):
        c = cotizar(CATALOGO, [("CAM-001", 1), ("TAZ-001", 3)])
        assert c.subtotal_cop == 85_000 + 105_000
        assert len(c.items) == 2

    def test_toma_los_dias_de_produccion_mas_largos(self):
        c = cotizar(CATALOGO, [("TAZ-001", 1), ("CAM-001", 1)])
        assert c.dias_produccion == 5  # el máximo, no el primero

    def test_toma_el_anticipo_mas_exigente(self):
        """Si un producto pide 70%, todo el pedido pide 70%."""
        c = cotizar(CATALOGO, [("CAM-001", 1), ("TAZ-001", 1)])
        assert c.anticipo_cop >= int(c.total_cop * Decimal("0.69"))

    def test_rechaza_sku_inexistente(self):
        with pytest.raises(KeyError):
            cotizar(CATALOGO, [("NO-EXISTE", 1)])

    def test_rechaza_producto_inactivo(self):
        with pytest.raises(ValueError, match="inactivo"):
            cotizar(CATALOGO, [("OFF-001", 1)])

    def test_rechaza_pedido_vacio(self):
        with pytest.raises(ValueError):
            cotizar(CATALOGO, [])

    def test_rechaza_cantidad_cero(self):
        with pytest.raises(ValueError):
            cotizar(CATALOGO, [("CAM-001", 0)])


class TestAnticipoYSaldo:
    @pytest.mark.parametrize("cantidad", range(1, 40))
    def test_anticipo_mas_saldo_siempre_es_igual_al_total(self, cantidad):
        """EL test que evita el descuadre contable.

        El saldo se calcula por DIFERENCIA (total - anticipo), nunca como
        total * 0.5. Si redondeas los dos por separado, no suman.
        """
        c = cotizar(CATALOGO, [("CAM-001", cantidad)], envio_cop=15_000)
        assert c.anticipo_cop + c.saldo_cop == c.total_cop

    def test_el_anticipo_se_redondea_a_miles(self):
        c = cotizar(CATALOGO, [("CAM-001", 3)], envio_cop=15_000)
        assert c.anticipo_cop % 1000 == 0

    def test_el_anticipo_nunca_supera_el_total(self):
        c = cotizar(CATALOGO, [("TAZ-001", 1)], anticipo_pct_override=Decimal("1.5"))
        assert c.anticipo_cop <= c.total_cop
        assert c.saldo_cop >= 0

    def test_todos_los_montos_son_enteros(self):
        """Nunca float para dinero: 0.1 + 0.2 != 0.3."""
        c = cotizar(CATALOGO, [("CAM-001", 7)], envio_cop=12_345)
        for valor in (
            c.subtotal_cop,
            c.iva_cop,
            c.total_cop,
            c.anticipo_cop,
            c.saldo_cop,
        ):
            assert isinstance(valor, int)


class TestMontoUnico:
    def test_nunca_cobra_menos_de_lo_debido(self):
        for monto in (150_000, 99_999, 1_000, 87_654):
            assert monto_con_digitos_unicos(monto, "PED-2026-0001") >= monto

    def test_es_determinista(self):
        a = monto_con_digitos_unicos(150_000, "PED-2026-0417")
        b = monto_con_digitos_unicos(150_000, "PED-2026-0417")
        assert a == b

    def test_el_sobreprecio_es_cosmetico(self):
        """Menos de 2000 pesos de diferencia: aceptable para el cliente."""
        for monto in (150_000, 85_000, 1_200_000):
            delta = monto_con_digitos_unicos(monto, "PED-X") - monto
            assert 0 <= delta < 2000


class TestFormato:
    @pytest.mark.parametrize(
        "monto,esperado",
        [
            (1_234_567, "$1.234.567"),
            (85_000, "$85.000"),
            (0, "$0"),
        ],
    )
    def test_formato_colombiano(self, monto, esperado):
        assert formatear_cop(monto) == esperado


class TestSlots:
    def test_los_slots_contienen_todo_lo_que_usa_la_plantilla(self):
        c = cotizar(CATALOGO, [("CAM-001", 2)], envio_cop=15_000)
        slots = c.slots()
        for clave in ("subtotal", "iva", "envio", "total", "anticipo", "saldo", "dias"):
            assert clave in slots

    def test_cotizacion_es_inmutable(self):
        c = cotizar(CATALOGO, [("CAM-001", 1)])
        # `Cotizacion` es un dataclass frozen: asignar lanza FrozenInstanceError.
        with pytest.raises(dataclasses.FrozenInstanceError):
            c.total_cop = 999  # type: ignore[misc]
        assert isinstance(c, Cotizacion)
