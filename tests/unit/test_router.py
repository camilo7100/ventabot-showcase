"""Tests del router.

Estos tests cubren TODA tu lógica de flujo conversacional y corren sin LLM,
sin red y sin base de datos. Es el mejor retorno por hora invertida de todo
el proyecto: cada bug de enrutamiento que atrapan aquí es un cliente que no
recibió una respuesta absurda.
"""

from __future__ import annotations

import pytest

from app.domain.models import Intent
from app.graph.router import COMANDOS, INTENT_A_NODO, comando_directo, router


class TestEnrutamiento:
    @pytest.mark.parametrize(
        "intent,destino",
        [
            (Intent.SALUDO.value, "catalogo"),
            (Intent.CATALOGO.value, "catalogo"),
            (Intent.COTIZAR.value, "cotizar"),
            (Intent.CONFIRMAR.value, "crear_pedido"),
            (Intent.ESTADO.value, "estado_pedido"),
            (Intent.COMPROBANTE.value, "comprobante"),
            (Intent.QUEJA.value, "handoff"),
            (Intent.HUMANO.value, "handoff"),
            (Intent.OTRO.value, "redactar"),
        ],
    )
    def test_cada_intencion_va_a_su_nodo(self, intent, destino):
        assert router({"intent": intent}) == destino

    def test_intencion_desconocida_cae_en_redactar(self):
        """Robustez: un valor inesperado NO puede tumbar el grafo."""
        assert router({"intent": "INVENTADA_POR_UN_BUG"}) == "redactar"

    def test_sin_intencion_cae_en_redactar(self):
        assert router({}) == "redactar"
        assert router({"intent": None}) == "redactar"


class TestPrecedencia:
    def test_needs_human_gana_sobre_todo(self):
        estado = {
            "needs_human": True,
            "intent": Intent.COTIZAR.value,
            "inbound_media": [{"kind": "image"}],
        }
        assert router(estado) == "handoff"

    def test_media_gana_sobre_la_intencion(self):
        """Una imagen siempre va a verificación de comprobante."""
        estado = {"intent": Intent.SALUDO.value, "inbound_media": [{"kind": "image"}]}
        assert router(estado) == "comprobante"


class TestComandosDirectos:
    @pytest.mark.parametrize("texto", ["#humano", "#HUMANO", "  #humano  ", "#asesor"])
    def test_comandos_de_escalamiento(self, texto):
        assert comando_directo(texto) == "handoff"

    def test_texto_normal_no_es_comando(self):
        assert comando_directo("hola, quiero comprar") is None
        assert comando_directo(None) is None

    def test_todos_los_comandos_apuntan_a_nodos_reales(self):
        destinos_validos = set(INTENT_A_NODO.values())
        for destino in COMANDOS.values():
            assert destino in destinos_validos


class TestIntegridadDelMapping:
    def test_todas_las_intenciones_del_enum_estan_mapeadas(self):
        """Si agregas una intención al Enum y olvidas mapearla, este test falla."""
        faltantes = {i.value for i in Intent} - set(INTENT_A_NODO)
        assert not faltantes, f"intenciones sin nodo asignado: {faltantes}"

    def test_el_router_es_puro(self):
        """Mismo input -> mismo output, siempre. Sin estado oculto."""
        estado = {"intent": Intent.COTIZAR.value}
        assert len({router(estado) for _ in range(100)}) == 1
