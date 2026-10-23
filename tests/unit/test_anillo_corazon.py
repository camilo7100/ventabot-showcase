"""El anillo de corazón (Camilo, 17/10).

- Un corazón de circón del color que ella escoja, en vez de huellitas; lo demás
  como el de huellita: talla, hasta 5 nombres por dentro, plata 925, abono
  $60.000, 10 a 15 días, fotos antes del saldo. $200.000.
- A diferencia de la cadena, SÍ se ofrece, desde el primer mensaje.
- «El corazón rosado» de una huellita es otra cosa: la piedra de la patita.
- Martha (17/10) lo describió así: «uno de la huellita y otro que no es de
  huellita, solamente con la piedrita».
"""

from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.adapters.repositories.csv_files import cargar_catalogo_csv
from app.adapters.repositories.memory import (
    InMemoryCustomerRepository,
    InMemoryOrderRepository,
    InMemoryProductRepository,
)
from app.conversacion.asesora import (
    FOTOS_DEL_CORAZON,
    PREGUNTA_DEL_CORAZON,
    Asesora,
    HechosDelNegocio,
)
from app.conversacion.mundo import Mundo
from app.domain import erp
from app.domain.asesora import (
    AccionAsesora,
    Borrador,
    CambiosDelBorrador,
    HuellitaDelBorrador,
    HuellitaPropuesta,
    aplicar,
    contar_anillos,
    habla_del_corazon,
)
from app.domain.models import Channel, Customer, Order, OrderItem, Product
from app.domain.personalizacion import ColorCircon as C
from app.domain.personalizacion import Huellita, Personalizacion
from tests.unit.test_asesora import (
    CONV,
    ContextoEnMemoria,
    Guion,
    _jugada,
    abrir_conversacion,
)

A = AccionAsesora
RAIZ = Path(__file__).resolve().parents[2]


def _productos():
    anillos = [
        Product(
            sku=f"ANI-HUE-{n}",
            nombre=f"Anillo huellita x{n}",
            precio_cop=150_000 + 50_000 * n,
            iva_pct=0,
            dias_produccion=10,
            dias_produccion_max=15,
            anticipo_fijo_cop=60_000,
            huellitas=n,
        )
        for n in (1, 2, 3)
    ]
    corazon = Product(
        sku="ANI-COR-1",
        nombre="Anillo de corazón",
        precio_cop=200_000,
        iva_pct=0,
        dias_produccion=10,
        dias_produccion_max=15,
        anticipo_fijo_cop=60_000,
        huellitas=1,
        categoria="corazones",
    )
    return [*anillos, corazon]


@pytest.fixture
def mundo():
    customers = InMemoryCustomerRepository()
    customers.upsert(
        Customer(id="c1", channel=Channel.WHATSAPP, channel_user_id="573001112233")
    )
    m = Mundo(
        InMemoryOrderRepository(),
        customers,
        InMemoryProductRepository(_productos()),
        ContextoEnMemoria(),
    )
    abrir_conversacion(m)
    return m


def _asesora(mundo, *jugadas):
    hechos = HechosDelNegocio.del_catalogo(_productos())
    return Asesora(mundo, Guion(*jugadas), "{hechos}", hechos)


def _textos(turno) -> str:
    return turno.respuesta.texto_plano


def _fotos(turno) -> list[str]:
    return [p.imagen for p in turno.respuesta.piezas if p.imagen]


class TestElCatalogo:
    def test_esta_en_el_catalogo_y_no_pisa_el_anillo_de_1(self):
        productos = cargar_catalogo_csv(RAIZ / "data" / "catalogo.csv")
        corazon = next(p for p in productos if p.categoria == "corazones")
        assert (corazon.sku, corazon.precio_cop, corazon.anticipo_fijo_cop) == (
            "ANI-COR-1",
            200_000,
            60_000,
        )
        hechos = HechosDelNegocio.del_catalogo(productos)
        assert hechos.precios == {1: 200_000, 2: 250_000, 3: 300_000}
        assert (hechos.precio_corazon, hechos.anticipo_corazon) == (200_000, 60_000)

    def test_las_fotos_existen(self):
        for foto in (*FOTOS_DEL_CORAZON, "anillo_corazon_2"):
            assert (RAIZ / "data" / "imagenes" / f"{foto}.jpg").exists()

    def test_la_ficha_tiene_la_estructura_de_la_huellita(self):
        h = HechosDelNegocio.del_catalogo(_productos())
        ficha = h.ficha_del_corazon()
        assert ficha.startswith("🎀*Anillo de corazón*")
        for pedazo in (
            "Precio: $200.000",
            "Plata Ley 925",
            "Se fabrica en tu medida",
            "color que quieras para el corazón",
            "hasta 5 nombres",
            "anillo de promesa",
            "abonar $60.000",
            "10 a 15 días",
            "te enviamos fotos de cómo quedó",
        ):
            assert pedazo in ficha, pedazo
        assert "huellita" not in ficha.lower()

    def test_el_modelo_lo_conoce_siempre(self):
        texto = HechosDelNegocio.del_catalogo(_productos()).para_el_prompt()
        assert "ANILLO DE CORAZÓN" in texto and "$200.000" in texto
        assert "MOSTRAR_CORAZON" in texto and "ES_CORAZON" in texto


class TestDeQueHabla:
    @pytest.mark.parametrize(
        "texto",
        [
            "Hola, info del anillo de corazón",
            "me gusta el de corazón",
            "y el anillo con el corazoncito?",
            "uno de la huellita y otro que no es de huellita, solamente con la piedrita",
            "tienen anillos de promesa?",
            "quiero uno sin huella",
        ],
    )
    def test_el_anillo_de_corazon(self, texto):
        assert habla_del_corazon(texto)

    @pytest.mark.parametrize(
        "texto",
        [
            "el corazón rosado y los deditos blancos",
            "corazón negro",
            "que el corazón sea fucsia",
            "quiero 2 huellitas",
        ],
    )
    def test_el_corazon_de_una_huellita_no(self, texto):
        assert not habla_del_corazon(texto)


class TestElBorrador:
    def _corazon(self) -> Borrador:
        b = Borrador()
        contar_anillos(
            b,
            [A.ES_CORAZON],
            "quiero el anillo de corazón",
            CambiosDelBorrador(),
            hay_pedido=False,
        )
        return b

    def test_es_un_anillo_con_un_corazon(self):
        b = self._corazon()
        assert b.es_corazon and b.cantidad == 1
        assert b.falta_del_anillo() == ["talla", "colores", "grabado"]

    def test_un_color_basta_venga_como_venga(self):
        b, _ = aplicar(
            self._corazon(),
            CambiosDelBorrador(huellitas=[HuellitaPropuesta(numero=1, dedos=C.FUCSIA)]),
        )
        assert b.huellitas[0].corazon == b.huellitas[0].dedos == C.FUCSIA
        assert "colores" not in b.falta_del_anillo()

    def test_no_se_le_anota_una_cantidad_de_huellitas(self):
        b, rechazos = aplicar(self._corazon(), CambiosDelBorrador(cantidad_huellitas=3))
        assert b.cantidad == 1 and any("UN solo corazón" in r for r in rechazos)

    def test_el_resumen(self):
        b, _ = aplicar(
            self._corazon(),
            CambiosDelBorrador(
                talla=7,
                huellitas=[HuellitaPropuesta(numero=1, corazon=C.FUCSIA)],
                grabado=["Ana", "Luis"],
            ),
        )
        resumen = b.resumen()
        assert resumen.startswith("•Anillo de corazón•")
        assert "Talla: 7" in resumen and "Color del corazón:" in resumen
        assert "Fucsia" in resumen and "Grabado: Ana ♡ Luis" in resumen
        assert "Huellita" not in resumen and "Dedos" not in resumen

    def test_sin_que_ella_hable_del_corazon_no_se_anota(self):
        b = Borrador()
        rechazos, *_ = contar_anillos(
            b,
            [A.ES_CORAZON],
            "el corazón rosado y los dedos blancos",
            CambiosDelBorrador(),
            hay_pedido=False,
        )
        assert not b.es_corazon and rechazos

    def test_mejor_el_de_huellitas_vuelve_al_anillo_de_siempre(self):
        b = self._corazon()
        contar_anillos(
            b, [], "mejor el de 2 huellitas", CambiosDelBorrador(), hay_pedido=False
        )
        assert not b.es_corazon and b.cantidad is None

    def test_la_huellita_que_ya_tenia_color_conserva_el_color(self):
        b = Borrador(huellitas=[HuellitaDelBorrador(corazon=C.ROJO, dedos=C.BLANCO)])
        contar_anillos(
            b,
            [A.ES_CORAZON],
            "mejor el anillo de corazón",
            CambiosDelBorrador(),
            hay_pedido=False,
        )
        assert b.huellitas[0].corazon == b.huellitas[0].dedos == C.ROJO


class TestCuandoPregunta:
    def test_le_llega_la_presentacion_con_la_foto(self, mundo):
        a = _asesora(mundo, _jugada("¡Claro! 💗 Te cuento del anillo de corazón"))
        t = a.ejecutar(CONV, "Hola, ¿cómo es el anillo de corazón?")
        assert "🎀*Anillo de corazón*" in _textos(t)
        assert _fotos(t) == list(FOTOS_DEL_CORAZON)
        assert PREGUNTA_DEL_CORAZON in _textos(t)
        assert "huellitas lo quieres" not in _textos(t)
        assert "Anillo personalizado huellita" not in _textos(t), (
            "no le llega la presentación de la huellita"
        )

    def test_una_sola_vez_en_la_charla(self, mundo):
        a = _asesora(
            mundo,
            _jugada("¡Claro! 💗", A.MOSTRAR_CORAZON),
            _jugada("Cuesta $200.000 💗", A.MOSTRAR_CORAZON),
        )
        a.ejecutar(CONV, "¿tienen anillos de promesa?")
        t = a.ejecutar(CONV, "¿y cuánto vale el de corazón?")
        assert not _fotos(t) and "$200.000" in _textos(t)

    def test_el_modelo_lo_puede_ofrecer_por_su_cuenta(self, mundo):
        """A diferencia de la cadena: una pareja, una promesa…"""
        a = _asesora(
            mundo,
            _jugada(
                "Para tu novio también tenemos el anillo de corazón 💗",
                A.MOSTRAR_CORAZON,
            ),
        )
        t = a.ejecutar(CONV, "es para regalarle a mi novio")
        assert "anillo de corazón" in _textos(t)
        assert _fotos(t) == list(FOTOS_DEL_CORAZON)


class TestLaCompra:
    def test_de_principio_a_fin_con_un_abono_de_60_000(self, mundo):
        a = _asesora(
            mundo,
            _jugada("¡Claro! 💗", A.MOSTRAR_CORAZON),
            _jugada(
                "¡Qué lindo! 💗 ¿De qué color quieres el corazón?",
                A.ES_CORAZON,
                talla=7,
            ),
            _jugada(
                "¿Así está bien? 🥰",
                huellitas=[HuellitaPropuesta(numero=1, corazon=C.FUCSIA)],
                grabado=["Ana", "Luis"],
                nombre_clienta="Martha Godoy",
            ),
            _jugada("¡Listo! 🫶 Te dejo los datos 💓", A.PEDIR_ABONO),
        )
        a.ejecutar(CONV, "Me interesa el anillo de corazón")
        a.ejecutar(CONV, "Lo quiero, el de corazón, talla 7")
        b = mundo.contexto(CONV).borrador
        assert b["pieza"] == "corazon" and b["talla"] == 7

        t = a.ejecutar(CONV, "fucsia, con Ana y Luis. A nombre de Martha Godoy")
        resumen = _textos(t)
        assert "•Anillo de corazón•" in resumen and "Fucsia" in resumen

        t = a.ejecutar(CONV, "Sí, así")
        assert "$60.000" in _textos(t)
        pedido = mundo.pedido(mundo.contexto(CONV).borrador["pedido_id"])
        assert [i.sku for i in pedido.items] == ["ANI-COR-1"]
        assert (pedido.total_cop, pedido.anticipo_cop) == (200_000, 60_000)
        p = pedido.items[0].personalizacion
        assert p.pieza == "corazon" and p.talla == 7 and p.falta(1) == []
        assert p.huellitas[0].corazon == C.FUCSIA

    def test_si_la_ia_no_lo_marca_igual_es_el_corazon(self, mundo):
        """Prueba con la IA real (17/10): «me encanta, es para mi novio. Talla 9»
        sin ES_CORAZON -> «¿De qué color quieres la huellita?» y después le
        llegó el dibujo de una huellita roja."""
        a = _asesora(
            mundo,
            _jugada("¡Claro! 💗", A.MOSTRAR_CORAZON),
            _jugada("¡Qué lindo regalo! 🫶", talla=9),
            _jugada(
                "¡Rojo y «Andrés»! ❤️",
                huellitas=[HuellitaPropuesta(numero=1, corazon=C.ROJO, dedos=C.ROJO)],
                grabado=["Andrés"],
            ),
        )
        a.ejecutar(CONV, "Hola, quiero info del anillo de corazón")
        a.ejecutar(CONV, "me encanta, es para mi novio. Talla 9")
        b = mundo.contexto(CONV).borrador
        assert b["pieza"] == "corazon" and b["talla"] == 9
        t = a.ejecutar(CONV, "rojo, y que diga Andrés por dentro")
        assert not any(f.startswith("vista_") for f in _fotos(t)), "ni un dibujo"
        assert "huellita" not in _textos(t).lower()


def test_el_erp_lo_anota_como_el_de_1_huella_con_su_detalle():
    pedido = Order(
        codigo="PED-2026-0099",
        customer_id="c1",
        estado="ANTICIPO_PAGADO",
        items=[
            OrderItem(
                sku="ANI-COR-1",
                nombre="Anillo de corazón",
                cantidad=1,
                precio_unitario_cop=200_000,
                personalizacion=Personalizacion(
                    pieza="corazon",
                    talla=7,
                    huellitas=[Huellita(corazon=C.FUCSIA, dedos=C.FUCSIA)],
                    grabados=["Ana", "Luis"],
                ),
            )
        ],
        total_cop=200_000,
        anticipo_cop=60_000,
        saldo_cop=140_000,
    )
    fila = erp.fila_de_venta(
        pedido, venta_id="V0600", fecha=datetime(2026, 10, 17, tzinfo=UTC)
    )
    assert fila["Producto"] == "Anillos 1 huella"
    assert "Anillo de corazón" in erp.color_detalle(pedido)
    assert pedido.items[0].personalizacion.describir().startswith("Anillo de corazón")


class TestComoQueda:
    """Camilo (17/10): como en las huellitas, pero solo el corazón, al derecho."""

    def test_el_dibujo_es_solo_el_corazon_derecho_y_de_su_color(self, tmp_path):
        import numpy as np
        from PIL import Image

        from app.adapters.render.huellita import RenderDeHuellitas

        fuentes = RAIZ / "data" / "imagenes" / "fuentes"
        render = RenderDeHuellitas(
            fuentes / "huellita_base.jpg", fuentes / "huellita_mascaras.png", tmp_path
        )
        nombre = render.previsualizar_corazon(C.ROJO)
        assert nombre and nombre.startswith("corazon_")
        assert render.previsualizar_corazon(C.ROJO) == nombre, "la misma, reusada"
        a = np.asarray(Image.open(tmp_path / f"{nombre}.jpg").convert("RGB")).astype(int)
        piedra = a[(a.min(axis=2) < 230)]
        r, g, b = piedra.mean(axis=0)
        assert r > g + 40 and r > b + 40, "rojo"
        # Al derecho: los dos lóbulos arriba (más piedra) y la punta abajo.
        mitad = a.shape[0] // 2
        arriba = (a[:mitad].min(axis=2) < 230).sum()
        abajo = (a[mitad:].min(axis=2) < 230).sum()
        assert arriba > abajo

    def test_en_la_charla_llega_con_su_pie(self):
        class Dibujante:
            def previsualizar_corazon(self, color):
                return f"corazon_{color.value.lower()}"

        customers = InMemoryCustomerRepository()
        customers.upsert(
            Customer(id="c1", channel=Channel.WHATSAPP, channel_user_id="573001112233")
        )
        m = Mundo(
            InMemoryOrderRepository(),
            customers,
            InMemoryProductRepository(_productos()),
            ContextoEnMemoria(),
            render=Dibujante(),
        )
        abrir_conversacion(m)
        a = _asesora(
            m,
            _jugada("¡Claro! 💗", A.MOSTRAR_CORAZON),
            _jugada("¡Qué lindo! 💗", A.ES_CORAZON, talla=8),
            _jugada(
                "¡Rojo! ❤️",
                huellitas=[HuellitaPropuesta(numero=1, corazon=C.ROJO)],
            ),
        )
        a.ejecutar(CONV, "info del anillo de corazón")
        a.ejecutar(CONV, "lo quiero, el de corazón, talla 8")
        t = a.ejecutar(CONV, "rojo")
        assert "corazon_rojo" in _fotos(t)
        pies = [p.texto for p in t.respuesta.piezas if p.imagen == "corazon_rojo"]
        assert pies and "Corazón" in pies[0] and "rojo" in pies[0].lower()
        assert not any(f.startswith("vista_") for f in _fotos(t)), "nada de huellita"
