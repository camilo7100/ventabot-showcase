"""Servicio al cliente: acompañar, no solo despachar.

Tres momentos en los que una venta se pierde por cómo contesta el bot, no
por lo que cuesta el anillo:

  1. LA TALLA. Está en la calle, sin regla. Si el flujo se para ahí, vuelve
     a escribir a los tres días — o no vuelve.
  2. LAS OBJECIONES. «Está caro», «me da miedo pagar por adelantado». No son
     dudas técnicas: son miedo, y contestarlas con el catálogo las agranda.
  3. NO SABER QUÉ ESCOGER. Está probado aparte, en `test_previsualizacion`.
"""

from __future__ import annotations

import pytest

from app.adapters.repositories.memory import (
    InMemoryCustomerRepository,
    InMemoryOrderRepository,
)
from app.conversacion.ejecutor import Ejecutor
from app.conversacion.interprete import Interprete
from app.conversacion.mundo import Mundo
from app.conversacion.pipeline import Pipeline
from app.conversacion.redactor import Redactor
from app.domain.contexto import TipoProceso
from app.domain.models import Channel, Customer
from app.domain.order_state import OrderState
from tests.unit.test_inteligencia_conversacional import (
    CONV,
    ContextoEnMemoria,
    ModeloDeMadera,
    _productos,
)


@pytest.fixture
def mundo():
    customers = InMemoryCustomerRepository()
    customers.upsert(
        Customer(id="c1", channel=Channel.WHATSAPP, channel_user_id="573001112233")
    )
    return Mundo(InMemoryOrderRepository(), customers, _productos(), ContextoEnMemoria())


@pytest.fixture
def bot(mundo):
    return Pipeline(
        Interprete(ModeloDeMadera(), "", ""), mundo, Ejecutor(mundo), Redactor()
    )


def hablar(bot, *mensajes):
    return [bot.ejecutar(CONV, m).respuesta.texto_plano for m in mensajes]


def _hasta_la_talla(bot):
    hablar(
        bot,
        "quiero un anillo de 1 huellita",
        "corazón rojo y dedos blancos",
        "se llama Poncho",
    )


def _datos_de_envio(bot):
    """Lo único personal que se pregunta antes del precio: su nombre.

    La ciudad, la cédula, el celular y la dirección se piden AL FINAL, con las
    fotos del anillo terminado (Camilo, 20/09).
    """
    hablar(bot, "Carlos Pérez")


# ═══════════════════════════════════════════════════════════════════════════
# LA TALLA NO PUEDE FRENAR LA VENTA
# ═══════════════════════════════════════════════════════════════════════════


class TestLaTallaNoFrena:
    def test_la_pregunta_ya_ofrece_la_salida(self, bot):
        _hasta_la_talla(bot)
        # El último mensaje es el que pide la talla.
        ultimo = bot.ejecutar(CONV, "mmm").respuesta.texto_plano
        assert "después te la mando" in ultimo.lower() or "regla" in ultimo.lower()

    @pytest.mark.parametrize(
        "excusa",
        [
            "no tengo regla",
            "después te la mando",
            "ahorita no puedo, luego te la mando",
            "estoy en la calle",
            "no sé mi talla",
            "mañana te la mando",
        ],
    )
    def test_si_no_la_tiene_a_mano_se_sigue_igual(self, bot, mundo, excusa):
        _hasta_la_talla(bot)
        hablar(bot, excusa)
        _datos_de_envio(bot)

        pedidos = mundo.pedidos_de(CONV)
        assert len(pedidos) == 1, f"«{excusa}» dejó la venta parada"
        assert pedidos[0].estado == OrderState.ESPERANDO_ANTICIPO.value
        assert pedidos[0].items[0].personalizacion.talla is None

    def test_se_le_dice_que_no_hay_prisa(self, bot):
        _hasta_la_talla(bot)
        hablar(bot, "no tengo regla")
        respuesta = hablar(bot, "Carlos Pérez")[0]
        assert "$60.000" in respuesta, "no llegó al cobro"
        assert "talla" in respuesta.lower()

    def test_el_abono_NO_se_nombra_antes_de_terminar_de_preguntar(self, bot):
        """Pedir plata a los cuatro mensajes, sin saber ni a dónde mandarlo,
        se siente como que están cobrando y no atendiendo."""
        _hasta_la_talla(bot)
        respuesta = hablar(bot, "talla 8")[0]
        assert "60.000" not in respuesta, "pidió el abono antes de tiempo"
        assert "nombre" in respuesta.lower()

    def test_queda_apuntado_para_que_nadie_lo_fabrique_sin_talla(self, bot, mundo):
        _hasta_la_talla(bot)
        hablar(bot, "después te la mando", "Carlos Pérez", "Bucaramanga")
        turno = bot.ejecutar(CONV, "Calle 45 #12-30")
        assert any("NO tiene talla" in nota for nota in turno.contexto.revisar)
        assert any(p.tipo is TipoProceso.DATOS_PEDIDO for p in turno.contexto.abiertos())

    def test_cuando_llega_despues_se_guarda_en_EL_MISMO_pedido(self, bot, mundo):
        _hasta_la_talla(bot)
        hablar(bot, "después te la mando")
        _datos_de_envio(bot)
        hablar(bot, "talla 8")

        pedidos = mundo.pedidos_de(CONV)
        assert len(pedidos) == 1, "creó un pedido nuevo"
        assert pedidos[0].items[0].personalizacion.talla == 8.0

    def test_los_colores_SI_frenan_la_venta(self, bot, mundo):
        """La talla se puede confirmar mientras se fabrica. El color no: sin
        él no hay nada que fundir."""
        hablar(bot, "quiero un anillo de 1 huellita", "se llama Poncho")
        hablar(bot, "no tengo regla")
        _datos_de_envio(bot)
        assert not mundo.pedidos_de(CONV)


# ═══════════════════════════════════════════════════════════════════════════
# LAS OBJECIONES
# ═══════════════════════════════════════════════════════════════════════════


class TestLasObjeciones:
    @pytest.mark.parametrize(
        "objecion, tiene_que_decir",
        [
            ("está muy caro", "plata ley 925"),
            ("por qué es tan caro", "10 y 15 días"),
            ("hacen descuento?", "abona"),
            ("es confiable?", "fotos"),
            ("me da miedo pagar por adelantado", "floridablanca"),
            ("y si no me queda?", "medida"),
            ("se puede cambiar la talla después?", "medida"),
        ],
    )
    def test_se_contestan_como_lo_que_son(self, bot, objecion, tiene_que_decir):
        respuesta = hablar(bot, objecion)[0].lower()
        assert "no te entendí" not in respuesta
        assert tiene_que_decir in respuesta

    def test_NUNCA_se_ofrece_un_descuento(self, bot):
        """Rebajar delante de una objeción enseña que el precio era mentira,
        y la siguiente clienta también va a pedir rebaja."""
        respuesta = hablar(bot, "hacen descuento?")[0].lower()
        for prohibida in ("descuento", "rebaja", "promoción", "gratis"):
            assert prohibida not in respuesta

    def test_el_miedo_a_pagar_no_se_contesta_con_la_lista_de_cuentas(self, bot):
        """Es tan sordo que cierra la conversación."""
        respuesta = hablar(bot, "me da miedo pagar por adelantado")[0]
        assert "Bancolombia" not in respuesta
        assert "entiendo" in respuesta.lower()


# ═══════════════════════════════════════════════════════════════════════════
# LO QUE MÁS SE PREGUNTA
# ═══════════════════════════════════════════════════════════════════════════


class TestElPrecio:
    @pytest.mark.parametrize(
        "pregunta",
        [
            "cuánto vale",
            "cuanto cuesta el anillo",
            "qué precio tiene",
            "a cómo está",
            "precios porfa",
        ],
    )
    def test_preguntar_el_precio_saca_el_catalogo(self, bot, pregunta):
        respuesta = hablar(bot, pregunta)[0]
        assert "200.000" in respuesta, "no le dijo el precio"


# ═══════════════════════════════════════════════════════════════════════════
# SI EL MODELO SE CAE
# ═══════════════════════════════════════════════════════════════════════════


class TestSinModelo:
    """Un rato de Ollama caído no puede volver tonto al bot.

    Todas las reglas deterministas —el precio, las objeciones, los nombres
    del grabado— son Python y no dependen del modelo. Antes se saltaban en
    el camino degradado, que es justo cuando más falta hacen.
    """

    @pytest.fixture
    def sin_modelo(self, mundo):
        class ModeloCaido:
            def extract(self, *a, **k):
                raise ConnectionError("ollama no responde")

        return Pipeline(
            Interprete(ModeloCaido(), "", ""), mundo, Ejecutor(mundo), Redactor()
        )

    def test_el_precio_se_sigue_contestando(self, sin_modelo):
        assert "200.000" in hablar(sin_modelo, "cuánto vale")[0]

    def test_las_objeciones_tambien(self, sin_modelo):
        assert "no te entendí" not in hablar(sin_modelo, "está muy caro")[0].lower()

    def test_y_una_queja_sigue_yendo_a_una_persona(self, sin_modelo):
        turno = sin_modelo.ejecutar(CONV, "me llegó partido el anillo")
        assert turno.respuesta.escalar


# ═══════════════════════════════════════════════════════════════════════════
# EL PEDIDO SE TERMINA DE ARMAR ANTES DE HABLAR DE PLATA
# ═══════════════════════════════════════════════════════════════════════════


class TestPrimeroElPedidoDespuesElAbono:
    """Pedir plata a los cuatro mensajes se siente como que están cobrando.

    Es el mismo pedido con los mismos pasos en otro orden, y el orden es la
    venta: cada dato que da es una inversión suya en la compra, y para cuando
    llega el precio ya está dentro.

    Lo que SÍ cambió el 20/09: los datos de envío ya no van aquí. Antes se le
    pedían ciudad y dirección antes de cobrar, y eso es un formulario a alguien
    que todavía no ha comprado. Van al final, con las fotos del anillo
    terminado, que es cuando ella los manda junto con la transferencia.
    """

    def test_despues_de_la_talla_pregunta_a_nombre_de_quien(self, bot):
        _hasta_la_talla(bot)
        respuesta = hablar(bot, "talla 8")[0]
        assert "nombre" in respuesta.lower()
        assert "60.000" not in respuesta

    def test_NO_le_pide_la_direccion_antes_de_cobrar(self, bot):
        """La regla del 20/09, dicha al revés: lo que NO puede pasar."""
        _hasta_la_talla(bot)
        todo = " ".join(hablar(bot, "talla 8", "Carlos Pérez")).lower()
        for dato in ("dirección", "cédula", "ciudad"):
            assert dato not in todo, f"le pidió {dato} antes de cobrar"

    def test_con_el_nombre_ya_aparece_el_precio(self, bot, mundo):
        _hasta_la_talla(bot)
        hablar(bot, "talla 8")
        respuesta = hablar(bot, "Carlos Pérez")[0]
        assert "$60.000" in respuesta
        assert mundo.pedidos_de(CONV)

    def test_el_pedido_nace_a_nombre_de_ella_y_con_su_telefono(self, bot, mundo):
        _hasta_la_talla(bot)
        hablar(bot, "talla 8", "Carlos Pérez")
        envio = mundo.pedidos_de(CONV)[0].envio
        assert envio.nombre == "Carlos Pérez"
        assert envio.telefono == "573001112233", "el teléfono se pone solo"
        assert not envio.direccion, "la dirección se pide al final"

    def test_si_ella_da_la_direccion_por_su_cuenta_se_guarda(self, bot, mundo):
        """No se le pide, pero si la da no se tira: mucha gente contesta
        «Carlos Pérez, Bucaramanga, Calle 45» de una."""
        _hasta_la_talla(bot)
        hablar(bot, "talla 8")
        respuesta = hablar(bot, "Carlos Pérez, Bucaramanga, Calle 45 #12-30")[0]
        assert "$60.000" in respuesta, "volvió a preguntar lo que ya le dieron"
        envio = mundo.pedidos_de(CONV)[0].envio
        assert envio.nombre and envio.ciudad
        assert "Calle 45" in envio.direccion

    def test_el_cierre_no_mete_prisa(self, bot):
        _hasta_la_talla(bot)
        hablar(bot, "talla 8")
        respuesta = hablar(bot, "Carlos Pérez")[0].lower()
        assert "sin prisa" in respuesta
        assert "cualquier cosa que quieras cambiar" in respuesta

    def test_el_flete_es_el_de_la_tabla_y_hoy_es_uno_solo(self, mundo):
        """Lía cobra UNA tarifa nacional (Camilo, 20/09). Lo que se prueba es
        que la cifra salga del CSV y no de un número escrito a mano: el bot
        llegó a cotizar $8.000 a Bogotá con las filas viejas."""
        from app.adapters.repositories.csv_files import CsvFletes
        from app.domain.faq import ENVIO_NACIONAL_COP
        from app.infra.settings import get_settings

        mundo._fletes = CsvFletes(get_settings().fletes_csv)
        for ciudad in ("Bogotá", "medellin", "Un pueblo que no existe", None):
            assert mundo.envio_a(ciudad) == ENVIO_NACIONAL_COP
