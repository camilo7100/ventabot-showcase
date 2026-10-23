"""Test de integración del grafo completo, SIN red y SIN LLM real.

Esto es la prueba de que la arquitectura hexagonal funciona: el mismo grafo
que en producción corre contra Postgres + Ollama + Bold, aquí corre contra
diccionarios en memoria y termina en milisegundos.

Incluye el test de idempotencia, que es el que más bugs de producción previene.
"""

from __future__ import annotations

import pytest
from langgraph.checkpoint.memory import InMemorySaver

from app.adapters.llm.ollama_client import FakeLLM
from app.adapters.payments.bold import FakeGateway
from app.adapters.repositories.memory import (
    InMemoryCustomerRepository,
    InMemoryIdempotencyStore,
    InMemoryOrderRepository,
    InMemoryPaymentRepository,
    InMemoryProductRepository,
)
from app.domain.models import (
    Channel,
    Customer,
    PaymentKind,
    PaymentStatus,
    Product,
)
from app.domain.order_state import OrderState
from app.domain.services import confirmar_pago
from app.graph.build import Deps, build_graph
from app.graph.state import initial_state


class FakeMedia:
    def download(self, media_id_or_url: str) -> bytes:
        return b"fake-image-bytes"

    def store(self, data: bytes, *, filename: str) -> str:
        return f"https://storage.test/{filename}"


@pytest.fixture
def deps():
    productos = InMemoryProductRepository(
        [
            Product(
                sku="CAM-001",
                nombre="Camiseta premium",
                precio_cop=85_000,
                dias_produccion=5,
            ),
            Product(sku="TAZ-001", nombre="Taza", precio_cop=35_000, dias_produccion=3),
        ]
    )
    customers = InMemoryCustomerRepository()
    customers.upsert(
        Customer(
            channel=Channel.WHATSAPP, channel_user_id="573001112233", nombre="Camilo"
        )
    )
    return Deps(
        products=productos,
        customers=customers,
        orders=InMemoryOrderRepository(),
        payments=InMemoryPaymentRepository(),
        gateway=FakeGateway(),
        llm=FakeLLM(),
        media=FakeMedia(),
    )


@pytest.fixture
def graph(deps):
    return build_graph(deps, checkpointer=InMemorySaver())


def enviar(graph, texto, *, conv="wa:573001112233", media=None):
    estado = initial_state(
        conversation_id=conv,
        channel="whatsapp",
        sender_id="573001112233",
        text=texto,
        media=media,
    )
    return graph.invoke(estado, {"configurable": {"thread_id": conv}})


class TestFlujoDeVenta:
    def test_saludo_muestra_el_catalogo(self, graph):
        r = enviar(graph, "hola buenas")
        assert r["intent"] == "SALUDO"
        assert r["reply_kind"] == "catalogo"
        assert len(r["reply_options"]) == 2
        assert r["reply_text"]

    def test_cotizacion_calcula_montos_reales(self, graph):
        r = enviar(graph, "quiero 2 CAM-001")
        assert r["reply_kind"] == "cotizacion"
        slots = r["reply_slots"]
        assert slots["subtotal"] == 170_000
        assert slots["anticipo"] + slots["saldo"] == slots["total"]
        # El texto solo contiene números que estaban en los slots.
        assert "170.000" in r["reply_text"]

    def test_venta_completa_hasta_el_link_de_pago(self, graph, deps):
        enviar(graph, "quiero 2 CAM-001")
        r = enviar(graph, "listo confirmo")

        assert r["reply_kind"] == "link_anticipo"
        assert r["reply_cta_url"].startswith("https://checkout.test/")

        pedido = deps.orders.get(r["active_order"]["id"])
        assert OrderState(pedido.estado) is OrderState.ESPERANDO_ANTICIPO

        pagos = deps.payments.all()
        assert len(pagos) == 1
        assert pagos[0].tipo is PaymentKind.ANTICIPO
        assert pagos[0].estado is PaymentStatus.PENDIENTE

    def test_consultar_estado_del_pedido(self, graph):
        enviar(graph, "quiero 1 TAZ-001")
        enviar(graph, "confirmo")
        r = enviar(graph, "cómo va mi pedido")
        assert r["reply_kind"] == "estado"
        assert "PED-" in r["reply_text"]

    def test_pedir_humano_calla_al_bot(self, graph):
        r = enviar(graph, "quiero hablar con una persona")
        assert r["needs_human"] is True
        assert r["reply_kind"] == "handoff"


class TestIdempotencia:
    """Los tests que más bugs de producción previenen."""

    def test_confirmar_dos_veces_no_genera_dos_links(self, graph, deps):
        enviar(graph, "quiero 2 CAM-001")
        r1 = enviar(graph, "confirmo")
        r2 = enviar(graph, "confirmo")  # el cliente le da doble tap al botón

        assert len(deps.payments.all()) == 1, "se generaron dos cobros"
        assert r1["reply_cta_url"] == r2["reply_cta_url"]

    def test_el_store_de_idempotencia_detecta_repetidos(self):
        store = InMemoryIdempotencyStore()
        assert store.mark_processed("whatsapp", "wamid.ABC") is True
        assert store.mark_processed("whatsapp", "wamid.ABC") is False
        # Distinta fuente, mismo id: son eventos distintos.
        assert store.mark_processed("bold", "wamid.ABC") is True

    def test_webhook_de_pago_repetido_no_avanza_dos_veces(self, graph, deps):
        enviar(graph, "quiero 2 CAM-001")
        enviar(graph, "confirmo")
        pago = deps.payments.all()[0]

        pedido = confirmar_pago(
            deps.orders,
            deps.payments,
            pago,
            monto_recibido_cop=pago.monto_esperado_cop,
            transaction_id="TX-1",
        )
        assert OrderState(pedido.estado) is OrderState.ANTICIPO_PAGADO

        # El mismo webhook llega otra vez (Bold reintenta 5 veces).
        # El bloqueo optimista lo bloquea: el pedido ya no está en
        # ESPERANDO_ANTICIPO, así que la segunda aplicación falla en vez de
        # avanzar de más.
        from app.domain.ports import ConflictoDeEstado

        with pytest.raises((ConflictoDeEstado, Exception)):
            confirmar_pago(
                deps.orders,
                deps.payments,
                pago,
                monto_recibido_cop=pago.monto_esperado_cop,
                transaction_id="TX-1",
            )

        # Y solo hay UN evento de auditoría para esa transición.
        eventos = [
            e
            for e in deps.orders.eventos(pedido.id)
            if e.estado_nuevo == OrderState.ANTICIPO_PAGADO.value
        ]
        assert len(eventos) == 1


class TestSeguridadDePagos:
    def test_un_pago_por_menos_del_esperado_se_rechaza(self, graph, deps):
        enviar(graph, "quiero 2 CAM-001")
        enviar(graph, "confirmo")
        pago = deps.payments.all()[0]

        with pytest.raises(ValueError, match="insuficiente"):
            confirmar_pago(
                deps.orders,
                deps.payments,
                pago,
                monto_recibido_cop=pago.monto_esperado_cop - 1,
                transaction_id="TX-FRAUDE",
            )

    def test_un_comprobante_por_imagen_nunca_aprueba_el_pago(self, graph, deps):
        enviar(graph, "quiero 2 CAM-001")
        enviar(graph, "confirmo")

        r = enviar(graph, None, media=[{"kind": "image", "media_id": "MID-1"}])

        pedido = deps.orders.get(r["active_order"]["id"])
        assert OrderState(pedido.estado) is OrderState.EN_REVISION_PAGO

        por_imagen = [p for p in deps.payments.all() if p.metodo == "TRANSFERENCIA"]
        assert len(por_imagen) == 1
        assert por_imagen[0].estado is PaymentStatus.EN_REVISION
        assert por_imagen[0].comprobante_hash_sha256  # evidencia guardada

    def test_dos_veces_el_mismo_comprobante_no_crea_dos_casos(self, graph, deps):
        enviar(graph, "quiero 2 CAM-001")
        enviar(graph, "confirmo")
        media = [{"kind": "image", "media_id": "MID-1"}]
        enviar(graph, None, media=media)
        enviar(graph, None, media=media)

        por_imagen = [p for p in deps.payments.all() if p.metodo == "TRANSFERENCIA"]
        assert len(por_imagen) == 1


class TestArquitectura:
    def test_el_dominio_no_importa_adaptadores(self):
        """La regla que hace posible migrar a SQL y a SAP sin reescribir.

        Puedes hacerla obligatoria en CI con `import-linter`.
        """
        import pathlib
        import re

        # Solo sentencias de import reales, no menciones en comentarios.
        PROHIBIDO = re.compile(
            r"^\s*(from|import)\s+app\.(adapters|graph|api|infra|workers)\b",
            re.MULTILINE,
        )
        raiz = pathlib.Path(__file__).resolve().parents[2] / "app" / "domain"
        for archivo in raiz.glob("*.py"):
            malos = PROHIBIDO.findall(archivo.read_text(encoding="utf-8"))
            assert not malos, (
                f"app/domain/{archivo.name} importa una capa externa: la "
                f"arquitectura hexagonal se rompió y la migración a SQL/SAP "
                f"se acaba de volver cara."
            )
