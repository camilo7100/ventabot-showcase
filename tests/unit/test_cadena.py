"""La cadena personalizada con huellita y nombre (Camilo, 03/10).

- $250.000, abono $65.000; el mensaje y las 3 fotos de Camilo.
- NUNCA se ofrece: solo si ella pregunta por cadenas o por más productos.
- Una huellita (corazón + 4 deditos), sin talla, nombre grabado obligatorio:
  hasta 2 nombres por lado, 2 lados.
- Se confirma todo (con la foto de la huellita) antes del abono, como el anillo.
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
    FOTOS_DE_LA_CADENA,
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
    pregunta_por_cadenas,
    quitar_cadena_no_pedida,
)
from app.domain.guion import para_las_piezas
from app.domain.models import Channel, Customer, Order, OrderItem, Product
from app.domain.personalizacion import ColorCircon as C
from app.domain.personalizacion import Huellita, Personalizacion, lados_de_la_cadena
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
    cadena = Product(
        sku="CAD-HUE-1",
        nombre="Cadena huellita con nombre",
        precio_cop=250_000,
        iva_pct=0,
        dias_produccion=10,
        dias_produccion_max=15,
        anticipo_fijo_cop=65_000,
        huellitas=1,
        categoria="cadenas",
    )
    return [*anillos, cadena]


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


# ══════════════════════════════════════════════════════════════════════════
#  EL CATÁLOGO
# ══════════════════════════════════════════════════════════════════════════


class TestElCatalogo:
    def test_la_cadena_esta_en_el_catalogo_y_no_pisa_el_anillo_de_1(self):
        productos = cargar_catalogo_csv(RAIZ / "data" / "catalogo.csv")
        cadena = next(p for p in productos if p.categoria == "cadenas")
        assert (cadena.precio_cop, cadena.anticipo_fijo_cop) == (250_000, 65_000)
        hechos = HechosDelNegocio.del_catalogo(productos)
        assert hechos.precios == {1: 200_000, 2: 250_000, 3: 300_000}
        assert (hechos.precio_cadena, hechos.anticipo_cadena) == (250_000, 65_000)
        assert "cadena" not in hechos.para_el_prompt().lower()

    def test_las_fotos_existen(self):
        for nombre in FOTOS_DE_LA_CADENA:
            assert (RAIZ / "data" / "imagenes" / f"{nombre}.jpg").is_file()


# ══════════════════════════════════════════════════════════════════════════
#  LAS REGLAS (puras)
# ══════════════════════════════════════════════════════════════════════════


class TestElGrabadoDeLaCadena:
    def test_un_renglon_por_lado_hasta_dos_nombres(self):
        lados, avisos = lados_de_la_cadena(["Luna ♡ Mara", "Siempre en mí"])
        assert lados == ["Luna ♡ Mara", "Siempre en mí"] and not avisos

    def test_nombres_sueltos_se_acomodan_de_a_dos_y_se_avisa(self):
        lados, avisos = lados_de_la_cadena(["Luna", "Mara", "Rocky"])
        assert lados == ["Luna ♡ Mara", "Rocky"] and "confírmaselo" in avisos[0]

    def test_tres_en_un_lado_o_cinco_nombres_no_caben(self):
        assert lados_de_la_cadena(["Luna ♡ Mara ♡ Rocky"])[0] == []
        assert lados_de_la_cadena(["A", "B", "C", "D", "E"])[0] == []

    def test_la_personalizacion_de_la_cadena(self):
        p = Personalizacion(
            pieza="cadena",
            huellitas=[Huellita(corazon=C.ROSADO, dedos=C.LILA)],
            sin_grabado=True,
        )
        assert p.falta(1) == ["grabado"], "sin talla; el nombre es obligatorio"
        p = p.model_copy(update={"grabados": ["Luna ♡ Mara", "Rocky"]})
        assert p.falta(1) == []
        assert "Lado 1: Luna ♡ Mara · Lado 2: Rocky" in p.describir()
        assert "Talla" not in p.describir()


class TestElBorradorDeLaCadena:
    def test_falta_y_resumen(self):
        b = Borrador(pieza="cadena", cantidad=1, nombre_clienta="Laura")
        assert b.falta_del_anillo() == ["colores", "grabado"]
        b.huellitas = [HuellitaDelBorrador(corazon=C.ROSADO, dedos=C.LILA)]
        b.grabado = ["Mía"]
        assert b.falta_para_abono() == []
        resumen = b.resumen()
        assert "•Cadena con huellita•" in resumen and "Lado 1: Mía" in resumen
        assert "Talla" not in resumen

    def test_aplicar_cuida_las_reglas(self):
        b = Borrador(pieza="cadena", cantidad=1)
        nuevo, rechazos = aplicar(
            b,
            CambiosDelBorrador(
                cantidad_huellitas=2, talla=7, grabado=["Luna", "Mara", "Rocky"]
            ),
        )
        assert nuevo.cantidad == 1 and nuevo.talla is None
        assert nuevo.grabado == ["Luna ♡ Mara", "Rocky"]
        assert any("UNA sola huellita" in r for r in rechazos)
        assert any("no lleva talla" in r for r in rechazos)
        _, rechazos = aplicar(nuevo, CambiosDelBorrador(sin_grabado=True))
        assert any("SIEMPRE lleva el nombre" in r for r in rechazos)


class TestSoloSiPregunta:
    @pytest.mark.parametrize(
        "texto",
        [
            "¿Tienen cadenas?",
            "Y collares con la huellita?",
            "¿Qué otros productos tienen?",
            "¿Solo venden anillos?",
            "Me muestras el catálogo",
            "Quiero ver más opciones",
        ],
    )
    def test_cuando_pregunta(self, texto):
        assert pregunta_por_cadenas(texto)

    @pytest.mark.parametrize(
        "texto",
        ["Hola, ¿precio?", "Quiero un anillo de 2 huellitas", "talla 7", "Sí"],
    )
    def test_cuando_no(self, texto):
        assert not pregunta_por_cadenas(texto)

    def test_la_red_quita_la_frase_de_la_cadena(self):
        texto, quito = quitar_cadena_no_pedida(
            "¡Qué lindo! También tenemos cadenas con su huellita. "
            "¿De qué color la quieres?"
        )
        assert quito and texto == "¡Qué lindo! ¿De qué color la quieres?"


class TestCualEsLaCadena:
    def _contar(self, b, texto, acciones=(A.ES_CADENA,), mostrada=False):
        return contar_anillos(
            b,
            list(acciones),
            texto,
            CambiosDelBorrador(),
            hay_pedido=False,
            cadena_mostrada=mostrada,
        )

    def test_quiero_la_cadena(self):
        b = Borrador()
        self._contar(b, "Quiero la cadena")
        assert b.es_cadena and b.cantidad == 1 and b.anillos_total == 1

    def test_ya_mostrada_basta_un_la_quiero(self):
        b = Borrador()
        rechazos, *_ = self._contar(b, "Sí, la quiero")
        assert not b.es_cadena and rechazos
        self._contar(b, "Sí, la quiero", mostrada=True)
        assert b.es_cadena

    def test_anillo_y_tambien_una_cadena(self):
        b = Borrador(cantidad=2, talla=7)
        self._contar(b, "y también una cadena")
        assert b.anillos_total == 2 and not b.es_cadena
        assert b.por_empezar[0].pieza == "cadena"

    def test_repetirla_no_suma_otra(self):
        b = Borrador()
        self._contar(b, "Quiero la cadena")
        self._contar(b, "la cadena en rosado")
        assert b.anillos_total == 1


# ══════════════════════════════════════════════════════════════════════════
#  LA CONVERSACIÓN
# ══════════════════════════════════════════════════════════════════════════


class TestNuncaSeOfrece:
    def test_el_modelo_la_ofrece_por_su_cuenta_y_no_llega(self, mundo):
        a = _asesora(
            mundo,
            _jugada(
                "¡Qué lindo! Si quieres también tenemos cadenas con su huellita. "
                "¿De qué color quieres la huellita?",
                A.MOSTRAR_CADENA,
                cantidad_huellitas=1,
            ),
        )
        t = a.ejecutar(CONV, "Quiero un anillo de 1 huellita")
        assert "cadena" not in _textos(t).lower()
        assert not any(f.startswith("cadena") for f in _fotos(t))
        assert "¿De qué color quieres la huellita?" in _textos(t)


class TestCuandoPregunta:
    @pytest.mark.parametrize("texto", ["¿Tienen cadenas?", "¿Qué más productos tienen?"])
    def test_le_llega_el_mensaje_con_las_fotos(self, mundo, texto):
        a = _asesora(mundo, _jugada("¡Claro! 💗", A.MOSTRAR_CADENA))
        t = a.ejecutar(CONV, texto)
        assert "tiene un valor de $250.000" in _textos(t)
        assert "solo necesitas abonar $65.000" in _textos(t)
        assert _fotos(t) == list(FOTOS_DE_LA_CADENA)
        assert "¿Te gustaría hacer la tuya? 💗" in _textos(t)
        assert "huellitas lo quieres" not in _textos(t), "no se le pregunta del anillo"

    def test_una_sola_vez_en_la_charla(self, mundo):
        a = _asesora(
            mundo,
            _jugada("¡Claro! 💗", A.MOSTRAR_CADENA),
            _jugada("Cuesta $250.000 💗", A.MOSTRAR_CADENA),
        )
        a.ejecutar(CONV, "¿Tienen cadenas?")
        t = a.ejecutar(CONV, "¿Y cuánto vale la cadena?")
        assert not _fotos(t) and "$250.000" in _textos(t)


class TestLaCompraDeLaCadena:
    def test_de_principio_a_fin_con_un_abono_de_65_000(self, mundo):
        a = _asesora(
            mundo,
            _jugada("¡Claro! 💗", A.MOSTRAR_CADENA),
            _jugada(
                "¡Qué linda! ¿Qué nombre le grabamos?",
                A.ES_CADENA,
                huellitas=[HuellitaPropuesta(numero=1, corazon=C.ROSADO, dedos=C.LILA)],
            ),
            _jugada(
                "¿Así está bien? 🥰",
                grabado=["Luna", "Mara", "Rocky"],
                nombre_clienta="Laura Gómez",
            ),
            _jugada("¡Listo! 🫶 Te dejo los datos 💓", A.PEDIR_ABONO),
        )
        a.ejecutar(CONV, "¿Tienen cadenas?")
        a.ejecutar(CONV, "Quiero la cadena con la huellita rosa y deditos lila")
        b = mundo.contexto(CONV).borrador
        assert b["pieza"] == "cadena" and b["huellitas"][0]["corazon"] == "ROSADO"

        t = a.ejecutar(CONV, "Luna, Mara y Rocky. A nombre de Laura Gómez")
        resumen = _textos(t)
        assert "•Cadena con huellita•" in resumen
        assert "Lado 1: Luna ♡ Mara · Lado 2: Rocky" in resumen
        assert "Talla" not in resumen

        t = a.ejecutar(CONV, "Sí, así")
        assert "$65.000 del abono de la cadena" in _textos(t)
        assert "al recibir tu cadena" in _textos(t) and "anillo" not in _textos(t)
        pedido = mundo.pedido(mundo.contexto(CONV).borrador["pedido_id"])
        assert [i.sku for i in pedido.items] == ["CAD-HUE-1"]
        assert (pedido.total_cop, pedido.anticipo_cop) == (250_000, 65_000)
        p = pedido.items[0].personalizacion
        assert p.pieza == "cadena" and p.talla is None
        assert p.grabados == ["Luna ♡ Mara", "Rocky"] and p.falta(1) == []

    def test_anillo_y_cadena_un_solo_abono(self, mundo):
        a = _asesora(
            mundo,
            _jugada("¡Claro! 💗", A.MOSTRAR_CADENA),
            _jugada(
                "¡Dale! Primero el anillo",
                A.OTRO_ANILLO,
                A.ES_CADENA,
                cantidad_huellitas=1,
                talla=7,
                huellitas=[HuellitaPropuesta(numero=1, corazon=C.NEGRO, dedos=C.NEGRO)],
                grabado=["Toby"],
                nombre_clienta="Laura Gómez",
            ),
            _jugada(
                "¿Así está bien? 🥰",
                huellitas=[HuellitaPropuesta(numero=1, corazon=C.ROJO, dedos=C.ROJO)],
                grabado=["Toby"],
            ),
            _jugada("¡Listo! 🫶", A.PEDIR_ABONO),
        )
        a.ejecutar(CONV, "¿Tienen cadenas?")
        a.ejecutar(
            CONV,
            "Quiero un anillo de 1 huellita negro, talla 7, Toby, y también una cadena",
        )
        t = a.ejecutar(CONV, "La cadena roja con Toby")
        assert "•Pedido: 1 anillo y 1 cadena•" in _textos(t)
        t = a.ejecutar(CONV, "Sí")
        assert "$125.000 del abono del anillo y la cadena" in _textos(t)
        pedido = mundo.pedido(mundo.contexto(CONV).borrador["pedido_id"])
        assert [i.sku for i in pedido.items] == ["ANI-HUE-1", "CAD-HUE-1"]
        assert pedido.total_cop == 450_000 and pedido.anticipo_cop == 125_000


# ══════════════════════════════════════════════════════════════════════════
#  DESPUÉS DEL ABONO: avisos y ERP
# ══════════════════════════════════════════════════════════════════════════


def _pedido_de_cadena() -> Order:
    return Order(
        codigo="PED-2026-0042",
        customer_id="c1",
        estado="ANTICIPO_PAGADO",
        items=[
            OrderItem(
                sku="CAD-HUE-1",
                nombre="Cadena huellita con nombre",
                cantidad=1,
                precio_unitario_cop=250_000,
                personalizacion=Personalizacion(
                    pieza="cadena",
                    huellitas=[Huellita(corazon=C.ROSADO, dedos=C.ROSADO)],
                    grabados=["Luna ♡ Mara", "Rocky"],
                ),
            )
        ],
        total_cop=250_000,
        anticipo_cop=65_000,
        saldo_cop=185_000,
    )


class TestDespues:
    def test_los_avisos_hablan_de_la_cadena(self):
        assert (
            para_las_piezas("¡Tu anillo ya está listo! ✨", ["cadena"])
            == "¡Tu cadena ya está lista! ✨"
        )
        assert para_las_piezas("Tu anillo va en camino", ["anillo", "cadena"]) == (
            "Tu pedido va en camino"
        )
        assert para_las_piezas("Tu anillo va en camino", ["anillo"]) == (
            "Tu anillo va en camino"
        )

    def test_el_erp_la_anota_como_cadena(self):
        fila = erp.fila_de_venta(
            _pedido_de_cadena(), venta_id="V0500", fecha=datetime(2026, 10, 3, tzinfo=UTC)
        )
        assert fila["Producto"] == "Cadena" and fila["Talla"] == ""
        assert fila["Grabado"] == "Lado 1: Luna♡Mara · Lado 2: Rocky"
