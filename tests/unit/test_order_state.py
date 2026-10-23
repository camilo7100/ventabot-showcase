"""Tests de la máquina de estados del pedido.

ESTOS SON LOS TESTS MÁS VALIOSOS DEL PROYECTO.

No prueban código: prueban tu POLÍTICA DE NEGOCIO. Si alguien (tú dentro de seis
meses, o un LLM que te ayude a refactorizar) cambia la tabla de transiciones por
accidente, CI se pone rojo antes de que despaches un pedido sin cobrarlo.

Corren en milisegundos. Sin red, sin base de datos, sin LLM.
"""

from __future__ import annotations

import itertools

import pytest

from app.domain.order_state import (
    TRANSICIONES,
    TransicionInvalida,
    alcanzables,
    es_terminal,
    puede_transicionar,
    validar_transicion,
)
from app.domain.order_state import (
    OrderState as S,
)


class TestReglasDeNegocioCriticas:
    """Las dos reglas que protegen tu plata."""

    def test_no_se_puede_producir_sin_cobrar_el_anticipo(self):
        assert not puede_transicionar(S.ESPERANDO_ANTICIPO, S.EN_PRODUCCION)
        with pytest.raises(TransicionInvalida):
            validar_transicion(S.ESPERANDO_ANTICIPO, S.EN_PRODUCCION)

    def test_no_se_puede_despachar_sin_cobrar_el_saldo(self):
        assert not puede_transicionar(S.PRODUCCION_LISTA, S.DESPACHADO)
        with pytest.raises(TransicionInvalida):
            validar_transicion(S.PRODUCCION_LISTA, S.DESPACHADO)

    def test_no_se_puede_saltar_de_cotizado_a_despachado(self):
        with pytest.raises(TransicionInvalida):
            validar_transicion(S.COTIZADO, S.DESPACHADO)

    def test_un_comprobante_nunca_produce_directamente(self):
        """EN_REVISION_PAGO debe pasar por ANTICIPO_PAGADO antes de producir."""
        assert not puede_transicionar(S.EN_REVISION_PAGO, S.EN_PRODUCCION)

    def test_el_camino_feliz_completo_es_valido(self):
        camino = [
            S.BORRADOR,
            S.COTIZADO,
            S.CONFIRMADO,
            S.ESPERANDO_ANTICIPO,
            S.ANTICIPO_PAGADO,
            S.EN_PRODUCCION,
            S.PRODUCCION_LISTA,
            S.ESPERANDO_SALDO,
            S.SALDO_PAGADO,
            S.DESPACHADO,
            S.ENTREGADO,
        ]
        for actual, siguiente in itertools.pairwise(camino):
            validar_transicion(actual, siguiente)  # no debe lanzar


class TestIntegridadDeLaTabla:
    def test_todos_los_estados_estan_en_la_tabla(self):
        assert set(TRANSICIONES) == set(S)

    def test_todos_los_destinos_son_estados_validos(self):
        for destinos in TRANSICIONES.values():
            assert destinos <= set(S)

    @pytest.mark.parametrize("estado", [S.ENTREGADO, S.CANCELADO, S.REEMBOLSO])
    def test_los_terminales_no_tienen_salida(self, estado):
        assert es_terminal(estado)
        assert TRANSICIONES[estado] == set()

    def test_todo_estado_no_terminal_puede_avanzar(self):
        for estado, destinos in TRANSICIONES.items():
            if not es_terminal(estado):
                assert destinos, f"{estado.value} no puede avanzar a ninguna parte"

    def test_desde_borrador_se_alcanza_entregado(self):
        assert S.ENTREGADO in alcanzables(S.BORRADOR)

    def test_desde_entregado_no_se_alcanza_nada(self):
        assert alcanzables(S.ENTREGADO) == set()

    def test_no_hay_estados_huerfanos(self):
        """Todo estado (salvo el inicial) debe ser alcanzable desde BORRADOR."""
        desde_inicio = alcanzables(S.BORRADOR) | {S.BORRADOR}
        huerfanos = set(S) - desde_inicio
        assert not huerfanos, f"estados inalcanzables: {huerfanos}"


class TestMensajesDeError:
    def test_el_error_dice_que_transiciones_si_son_validas(self):
        with pytest.raises(TransicionInvalida) as exc:
            validar_transicion(S.COTIZADO, S.DESPACHADO)
        mensaje = str(exc.value)
        assert "COTIZADO" in mensaje and "DESPACHADO" in mensaje
        assert "CONFIRMADO" in mensaje  # sugiere las válidas
