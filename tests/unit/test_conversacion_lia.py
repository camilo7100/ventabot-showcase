"""La conversación de Lía, completa, mensaje por mensaje.

Es el test que más vale del proyecto: reproduce una venta real —la de Ángela
y su perro Rocky, de las conversaciones de septiembre— y comprueba que el bot
la lleva de principio a fin sin adivinar nada y sin pedirle la talla antes de
cobrarle.

Corre en milisegundos, sin red, sin Ollama y sin WhatsApp.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.adapters.repositories.csv_files import cargar_catalogo_csv
from app.adapters.repositories.memory import InMemoryOrderRepository
from app.domain.guion import Paso
from app.domain.models import Order, OrderItem
from app.domain.order_state import OrderState
from app.domain.personalizacion import ColorCircon, Personalizacion
from app.graph.nodes.personalizar import make_personalizar

RAIZ = Path(__file__).resolve().parents[2]


class CatalogoFalso:
    def __init__(self, productos):
        self._p = productos

    def list_active(self):
        return self._p

    def get(self, sku):
        return next((p for p in self._p if p.sku == sku), None)


@pytest.fixture(scope="module")
def productos():
    return cargar_catalogo_csv(RAIZ / "data" / "catalogo.csv")


@pytest.fixture
def orders():
    return InMemoryOrderRepository()


@pytest.fixture
def nodo(productos, orders):
    return make_personalizar(CatalogoFalso(productos), orders)


def _pedido(orders, sku: str, *, anticipo_pagado: int = 0) -> dict:
    o = Order(
        codigo="PED-2026-0417",
        customer_id="c1",
        estado=OrderState.COTIZADO.value,
        items=[
            OrderItem(sku=sku, nombre="Anillo", cantidad=1, precio_unitario_cop=200_000)
        ],
        total_cop=200_000,
        anticipo_cop=60_000,
        saldo_cop=140_000,
        anticipo_pagado_cop=anticipo_pagado,
    )
    orders.create(o, idem_key="t")
    return o.model_dump(mode="json")


def _turno(nodo, estado: dict, texto: str | None = None, **extra) -> dict:
    """Un mensaje de la clienta. Devuelve el estado siguiente, ya fusionado."""
    entrada = {**estado, "inbound_text": texto, **extra}
    salida = nodo(entrada)
    return {**entrada, **salida}


class TestVentaCompleta:
    def test_de_hola_a_pedido_listo(self, nodo, orders, productos):
        """La venta de Ángela: 1 huellita, corazón lila, dedos morados,
        grabado Rocky, talla 7. Exactamente la del chat real."""
        estado: dict = {
            "conversation_id": "wa:573001112233",
            "active_order": _pedido(orders, "ANI-HUE-1"),
            "customer": {"nombre": "Ángela"},
            "entities": {},
        }

        # --- 1. Ya eligió 1 huellita: el bot pide los colores ---
        estado = _turno(nodo, estado, "")
        assert estado["paso"] == Paso.COLORES.value
        assert "corazón" in estado["reply_text"]
        assert estado["reply_imagen"] == "muestrario_circones"

        # --- 2. «quiero corazón lila y dedos morados» ---
        estado = _turno(nodo, estado, "quiero corazón lila y dedos morados")
        diseno = Personalizacion(**estado["diseno"])
        assert diseno.huellitas[0].corazon is ColorCircon.LILA
        assert diseno.huellitas[0].dedos is ColorCircon.MORADO
        assert estado["paso"] == Paso.GRABADO.value

        # --- 3. «Nombre rocky» ---
        estado = _turno(nodo, estado, "Nombre rocky")
        assert Personalizacion(**estado["diseno"]).grabados == ["Rocky"]

        # --- 4. Diseño listo: se pide el ABONO, no la talla ---
        assert estado["paso"] == Paso.CONFIRMAR_Y_ABONAR.value
        confirmacion = estado["reply_text"]
        assert "$60.000" in confirmacion
        assert "$140.000" in confirmacion
        assert "corazón lila / dedos morado" in confirmacion
        assert "Rocky" in confirmacion
        assert "talla" not in confirmacion.lower(), (
            "se le está pidiendo la talla antes de cobrarle"
        )

        # --- 5. Paga el abono. AHORA sí, la talla ---
        estado["active_order"] = _pedido(orders, "ANI-HUE-1", anticipo_pagado=60_000)
        estado = _turno(nodo, estado, "")
        assert estado["paso"] == Paso.TALLA.value
        assert "talla" in estado["reply_text"].lower()
        assert "afán" in estado["reply_text"].lower()

        # --- 6. «soy talla 7» ---
        estado = _turno(nodo, estado, "soy talla 7")
        assert Personalizacion(**estado["diseno"]).talla == 7.0
        assert estado["paso"] == Paso.LISTO.value
        assert "PED-2026-0417" in estado["reply_text"]
        assert "Ángela" in estado["reply_text"]

        # --- 7. Y quedó GUARDADA en el pedido, no solo en la conversación ---
        pedido = orders.get(estado["active_order"]["id"])
        assert pedido.items[0].personalizacion.talla == 7.0
        assert pedido.items[0].personalizacion.grabados == ["Rocky"]

    def test_el_anillo_de_tres_huellitas_pide_los_tres_colores(self, nodo, orders):
        estado: dict = {
            "active_order": _pedido(orders, "ANI-HUE-3"),
            "entities": {},
            "customer": {},
        }
        estado = _turno(nodo, estado, "")
        assert "huellita 1" in estado["reply_text"].lower()

        estado = _turno(nodo, estado, "corazón rojo dedos blancos")
        assert "huellita 2" in estado["reply_text"].lower()

        estado = _turno(nodo, estado, "todo verde esmeralda")
        assert "huellita 3" in estado["reply_text"].lower()

        estado = _turno(nodo, estado, "corazon negro dedos amarillos")
        assert estado["paso"] == Paso.GRABADO.value
        assert len(Personalizacion(**estado["diseno"]).huellitas) == 3


class TestNoAdivinaNunca:
    def test_un_color_ambiguo_se_repregunta_mostrando_lo_que_leyo(self, nodo, orders):
        estado = _turno(
            nodo,
            {
                "active_order": _pedido(orders, "ANI-HUE-1"),
                "entities": {},
                "customer": {},
            },
            "lila y morado",
        )
        assert estado["paso"] == Paso.COLORES.value, "avanzó sin entender"
        assert "lila" in estado["reply_text"] and "morado" in estado["reply_text"]
        assert Personalizacion(**estado["diseno"]).huellitas == []

    def test_un_mensaje_sin_colores_no_inventa_ninguno(self, nodo, orders):
        estado = _turno(
            nodo,
            {
                "active_order": _pedido(orders, "ANI-HUE-1"),
                "entities": {},
                "customer": {},
            },
            "ay que lindo",
        )
        assert Personalizacion(**estado["diseno"]).huellitas == []
        assert estado["paso"] == Paso.COLORES.value

    def test_una_talla_imposible_no_se_guarda(self, nodo, orders):
        """«la 25» no es una talla. Fabricarla es perder el anillo."""
        base = {
            "active_order": _pedido(orders, "ANI-HUE-1", anticipo_pagado=60_000),
            "entities": {},
            "customer": {},
            "diseno": Personalizacion(
                huellitas=[{"corazon": "LILA", "dedos": "LILA"}], grabados=["Rocky"]
            ).model_dump(mode="json"),
            "huellitas_esperadas": 1,
        }
        estado = _turno(nodo, base, "la 25")
        assert Personalizacion(**estado["diseno"]).talla is None
        assert estado["paso"] == Paso.TALLA.value

    def test_un_grabado_con_emoji_se_explica_en_vez_de_fabricarse(self, nodo, orders):
        base = {
            "active_order": _pedido(orders, "ANI-HUE-1"),
            "entities": {},
            "customer": {},
            "diseno": Personalizacion(
                huellitas=[{"corazon": "LILA", "dedos": "LILA"}]
            ).model_dump(mode="json"),
            "huellitas_esperadas": 1,
        }
        estado = _turno(nodo, base, "Rocky 🐶")
        assert Personalizacion(**estado["diseno"]).grabados == []
        assert "Ups" in estado["reply_text"]


class TestTallaPorFoto:
    def _base(self, orders):
        return {
            "active_order": _pedido(orders, "ANI-HUE-1", anticipo_pagado=60_000),
            "customer": {},
            "huellitas_esperadas": 1,
            "diseno": Personalizacion(
                huellitas=[{"corazon": "LILA", "dedos": "LILA"}], grabados=["Rocky"]
            ).model_dump(mode="json"),
        }

    def test_una_foto_buena_da_la_talla_sin_marcarla(self, nodo, orders):
        estado = _turno(
            nodo,
            self._base(orders),
            None,
            entities={"diametro_mm": 17.3, "foto_clara": True},
        )
        p = Personalizacion(**estado["diseno"])
        assert (p.talla, p.talla_revisar) == (7.0, False)
        assert estado["paso"] == Paso.LISTO.value

    def test_una_foto_mala_igual_avanza_pero_queda_marcada(self, nodo, orders):
        """Lo que pidió el negocio: el bot decide, la clienta no se entera, y
        queda marcado para que lo revisen antes de fundir plata."""
        estado = _turno(
            nodo,
            self._base(orders),
            None,
            entities={"diametro_mm": 25.0, "foto_clara": True},
        )
        p = Personalizacion(**estado["diseno"])
        assert p.talla is not None
        assert p.talla_revisar is True
        assert "exterior" in p.talla_motivo
        # A la clienta no se le dice NADA de la duda.
        assert "revisar" not in estado["reply_text"].lower()
        assert "no pude" not in estado["reply_text"].lower()

    def test_la_marca_de_revision_llega_al_pedido(self, nodo, orders):
        estado = _turno(
            nodo,
            self._base(orders),
            None,
            entities={"diametro_mm": 25.0, "foto_clara": False},
        )
        pedido = orders.get(estado["active_order"]["id"])
        assert pedido.items[0].personalizacion.talla_revisar is True
        assert pedido.items[0].personalizacion.talla_motivo


class TestNombresGrabados:
    """Se graba en plata y no se puede deshacer."""

    def test_rocky_llega_con_mayuscula(self, nodo, orders):
        base = {
            "active_order": _pedido(orders, "ANI-HUE-1"),
            "entities": {},
            "customer": {},
            "diseno": Personalizacion(
                huellitas=[{"corazon": "LILA", "dedos": "LILA"}]
            ).model_dump(mode="json"),
            "huellitas_esperadas": 1,
        }
        estado = _turno(nodo, base, "nombre rocky")
        assert Personalizacion(**estado["diseno"]).grabados == ["Rocky"]

    def test_pero_MAX_se_respeta_tal_cual(self, nodo, orders):
        """Si ella lo escribió en mayúsculas, sabe cómo se escribe."""
        base = {
            "active_order": _pedido(orders, "ANI-HUE-1"),
            "entities": {},
            "customer": {},
            "diseno": Personalizacion(
                huellitas=[{"corazon": "LILA", "dedos": "LILA"}]
            ).model_dump(mode="json"),
            "huellitas_esperadas": 1,
        }
        estado = _turno(nodo, base, "MAX")
        assert Personalizacion(**estado["diseno"]).grabados == ["MAX"]

    def test_varios_nombres_separados_por_y_o_coma(self, nodo, orders):
        base = {
            "active_order": _pedido(orders, "ANI-HUE-1"),
            "entities": {},
            "customer": {},
            "diseno": Personalizacion(
                huellitas=[{"corazon": "LILA", "dedos": "LILA"}]
            ).model_dump(mode="json"),
            "huellitas_esperadas": 1,
        }
        estado = _turno(nodo, base, "que diga Luna y Simba")
        assert Personalizacion(**estado["diseno"]).grabados == ["Luna", "Simba"]


class TestSinGrabado:
    def test_quien_no_quiere_grabado_no_queda_en_bucle(self, nodo, orders):
        base = {
            "active_order": _pedido(orders, "ANI-HUE-1"),
            "entities": {},
            "customer": {},
            "diseno": Personalizacion(
                huellitas=[{"corazon": "LILA", "dedos": "LILA"}]
            ).model_dump(mode="json"),
            "huellitas_esperadas": 1,
        }
        estado = _turno(nodo, base, "sin grabado gracias")
        assert Personalizacion(**estado["diseno"]).sin_grabado is True
        assert estado["paso"] == Paso.CONFIRMAR_Y_ABONAR.value


class TestDeterminismo:
    def test_el_mismo_mensaje_da_siempre_el_mismo_resultado(self, nodo, orders):
        base = {
            "active_order": _pedido(orders, "ANI-HUE-1"),
            "entities": {},
            "customer": {},
        }
        salidas = {
            _turno(nodo, dict(base), "corazón lila y dedos morados")["reply_text"]
            for _ in range(20)
        }
        assert len(salidas) == 1
