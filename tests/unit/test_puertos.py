"""Todos los adaptadores cumplen el contrato de su puerto. Comprobado, no supuesto.

POR QUÉ EXISTE
==============
Escribí `SqliteCustomerRepository` con un método `get_by_channel(channel:
Channel, ...)` cuando el puerto pide `get_by_channel_user(channel: str, ...)`.
Se veía correcto, pasaba todos sus tests, y el sistema arrancaba en verde.
Habría reventado con un `AttributeError` el primer día que alguien lo usara
en producción — es decir, el día que Lía tocara «Cobrar el saldo».

Ese es el precio de una arquitectura hexagonal sin verificación: los
`Protocol` de Python son structural typing, así que nadie comprueba nada
hasta que se llama al método que falta.

Este archivo cierra ese hueco: por cada puerto, se comprueba que TODOS sus
adaptadores tengan los métodos, con los mismos nombres y los mismos
parámetros. Es aburrido y es exactamente lo que hay que tener.

CÓMO CRECE
==========
Cuando escribas un adaptador nuevo (el de Sheets, el de Postgres, el de SAP),
agrégalo a la lista de su puerto. Si le falta un método, te enteras aquí.
"""

from __future__ import annotations

import inspect
from typing import get_type_hints

import pytest

from app.adapters.repositories.memory import (
    InMemoryCustomerRepository,
    InMemoryIdempotencyStore,
    InMemoryOrderRepository,
    InMemoryPaymentRepository,
    InMemoryProductRepository,
)
from app.adapters.repositories.sqlite_store import (
    SqliteCustomerRepository,
    SqliteIdempotencyStore,
    SqliteOrderRepository,
    SqliteOutbox,
)
from app.domain import ports

#: puerto -> adaptadores que dicen implementarlo.
IMPLEMENTACIONES: dict[type, list[type]] = {
    ports.CustomerRepository: [InMemoryCustomerRepository, SqliteCustomerRepository],
    ports.OrderRepository: [InMemoryOrderRepository, SqliteOrderRepository],
    ports.ProductRepository: [InMemoryProductRepository],
    ports.PaymentRepository: [InMemoryPaymentRepository],
    ports.IdempotencyStore: [InMemoryIdempotencyStore, SqliteIdempotencyStore],
    ports.Outbox: [SqliteOutbox],
}


def _metodos_del_puerto(puerto: type) -> list[str]:
    return [
        nombre
        for nombre, _ in inspect.getmembers(puerto, inspect.isfunction)
        if not nombre.startswith("_")
    ]


CASOS = [
    (puerto, adaptador)
    for puerto, adaptadores in IMPLEMENTACIONES.items()
    for adaptador in adaptadores
]
IDS = [f"{p.__name__}-{a.__name__}" for p, a in CASOS]


@pytest.mark.parametrize(("puerto", "adaptador"), CASOS, ids=IDS)
class TestContratos:
    def test_tiene_todos_los_metodos(self, puerto, adaptador):
        faltan = [m for m in _metodos_del_puerto(puerto) if not hasattr(adaptador, m)]
        assert not faltan, (
            f"{adaptador.__name__} no implementa {faltan} de "
            f"{puerto.__name__}. El sistema arranca en verde y revienta el día "
            f"que alguien llame a ese método."
        )

    def test_los_parametros_se_llaman_igual(self, puerto, adaptador):
        """Un método con el nombre correcto y los parámetros distintos falla
        igual: `get_by_channel(channel=...)` frente a
        `get_by_channel_user(channel=...)` fue exactamente ese bug."""
        for nombre in _metodos_del_puerto(puerto):
            if not hasattr(adaptador, nombre):
                continue  # ya lo reportó el test anterior
            esperados = [
                p
                for p in inspect.signature(getattr(puerto, nombre)).parameters
                if p != "self"
            ]
            reales = [
                p
                for p in inspect.signature(getattr(adaptador, nombre)).parameters
                if p != "self"
            ]
            assert reales == esperados, (
                f"{adaptador.__name__}.{nombre} recibe {reales} pero el puerto "
                f"pide {esperados}"
            )


class TestElPuertoNoSeAmplioSinQuerer:
    """Cada método del puerto es superficie que TODO adaptador futuro tendrá
    que implementar: el de Sheets, el de Postgres, el de SAP. Crecer aquí es
    barato hoy y caro tres migraciones después, así que se cuenta a propósito."""

    @pytest.mark.parametrize(
        ("puerto", "cuantos"),
        [
            (ports.OrderRepository, 8),
            (ports.CustomerRepository, 3),
            (ports.LLMPort, 1),
        ],
    )
    def test_cuantos_metodos_tiene(self, puerto, cuantos):
        reales = _metodos_del_puerto(puerto)
        assert len(reales) == cuantos, (
            f"{puerto.__name__} pasó de {cuantos} a {len(reales)} métodos: "
            f"{reales}. Si el método nuevo hace falta, sube el número aquí y "
            f"acuérdate de implementarlo en TODOS los adaptadores."
        )

    def test_el_LLM_sigue_sin_poder_escribir_texto_libre(self):
        """`LLMPort` tiene un solo método, `extract`, y devuelve un objeto
        validado. El día que alguien le agregue un `chat()` que devuelva
        `str`, el LLM podrá inventar precios."""
        assert _metodos_del_puerto(ports.LLMPort) == ["extract"]
        firma = get_type_hints(ports.LLMPort.extract)
        assert firma["return"] is not str


class TestElDominioNoConoceAdaptadores:
    def test_ports_no_importa_nada_de_afuera(self):
        """La regla que hace posible cambiar de SQLite a Postgres a SAP."""
        import pathlib
        import re

        fuente = pathlib.Path(ports.__file__).read_text(encoding="utf-8")
        prohibido = re.compile(
            r"^\s*(from|import)\s+app\.(adapters|graph|api|infra|workers)\b",
            re.MULTILINE,
        )
        assert not prohibido.findall(fuente)
