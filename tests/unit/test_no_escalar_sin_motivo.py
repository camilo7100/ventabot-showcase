"""Escalar es la única acción de la que el bot no vuelve solo.

════════════════════════════════════════════════════════════════════════════
DE DÓNDE SALE ESTE ARCHIVO
════════════════════════════════════════════════════════════════════════════
Del cuarto mensaje de una conversación de verdad por WhatsApp:

    «Hola» · «Si» · «Quiero pedir uno» · «Paco»

«Paco» es el nombre del peludito. El modelo lo leyó como HUMANO, y ahí se acabó
la conversación: `LLAMAR_HUMANO` escala, y una conversación escalada se queda
esperando a que una persona la recoja.

Las señales de que alguien quiere una persona son PALABRAS —«asesor», «una
persona», «hablar con»— y las de una queja. Están en `PIDE_HUMANO` y `QUEJA`, se
miran ANTES del modelo, y cortan de una. Si ninguna apareció, el modelo se lo
inventó: en un mensaje de una palabra no cabe una petición de asesor.

Este archivo vigila las dos caras de esa regla, porque las dos cuestan dinero:
  · escalar sin motivo deja la venta congelada
  · NO escalar una queja deja a una clienta enfadada hablando con un bot
"""

from __future__ import annotations

import pytest

from app.adapters.repositories.memory import (
    InMemoryCustomerRepository,
    InMemoryOrderRepository,
    InMemoryProductRepository,
)
from app.conversacion.ejecutor import Ejecutor
from app.conversacion.interprete import Interprete
from app.conversacion.mundo import Mundo
from app.conversacion.pipeline import Pipeline
from app.conversacion.redactor import Redactor
from app.domain.contexto import ContextoConversacional, TipoProceso
from app.domain.interpretacion import Acto, Interpretacion
from app.domain.models import Channel, Customer, Product

CONV = "wa:573001112233"


class ContextoEnMemoria:
    def __init__(self):
        self._d: dict[str, ContextoConversacional] = {}

    def cargar(self, conv_id):
        return self._d.get(conv_id) or ContextoConversacional(conversation_id=conv_id)

    def guardar(self, ctx):
        self._d[ctx.conversation_id] = ctx


class ModeloQueSiempreDiceHumano:
    """El peor modelo posible para esta regla: TODO le parece un asesor.

    Es el doble correcto para probar esto. Si con un modelo que dice HUMANO a
    cada palabra la conversación NO escala, es porque la decisión la toman las
    palabras de la frase y no él — que es justo lo que se quiere garantizar.
    """

    def extract(self, prompt, texto, esquema):
        return Interpretacion(acto=Acto.HUMANO, confianza="ALTA")


def _productos() -> InMemoryProductRepository:
    return InMemoryProductRepository(
        [
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
    )


@pytest.fixture
def mundo():
    customers = InMemoryCustomerRepository()
    customers.upsert(
        Customer(
            id="c1",
            channel=Channel.WHATSAPP,
            channel_user_id="573001112233",
            nombre="Ángela",
        )
    )
    return Mundo(InMemoryOrderRepository(), customers, _productos(), ContextoEnMemoria())


@pytest.fixture
def bot(mundo):
    """El bot con el modelo que siempre dice HUMANO."""
    interprete = Interprete(ModeloQueSiempreDiceHumano(), prompt="", catalogo_txt="")
    return Pipeline(interprete, mundo, Ejecutor(mundo), Redactor())


def escala(bot, texto: str) -> bool:
    return bot.ejecutar(CONV, texto).respuesta.escalar


# ═══════════════════════════════════════════════════════════════════════════
# 1. LO QUE NO PUEDE ESCALAR NUNCA
# ═══════════════════════════════════════════════════════════════════════════

#: Nombres de mascota. Es lo que contesta una clienta que ya decidió comprar,
#: y son los de las conversaciones reales de Lía.
NOMBRES = [
    "Paco",
    "Luna",
    "Simba",
    "Rocky",
    "Nina",
    "Coco",
    "Michi",
    "Toby",
    "Kira",
    "Zeus",
    "Mia",
    "Lola",
    "Bruno",
    "Canela",
    "Gordo",
    "Pan",
    "Sakura",
    "Muñeco",
    "Lilú",
    "Roberta",
    "Lulu",
    "Mara",
    "Pancho",
]

#: Datos del anillo, sueltos, como llegan de verdad.
DATOS = [
    "1",
    "2",
    "3",
    "una",
    "dos",
    "tres",
    "talla 7",
    "8.5",
    "1,80 cm",
    "negro",
    "morado",
    "rosado",
    "azul rey",
    "verde",
    "lila",
    "blanco",
    "todo negro",
    "corazón lila y dedos morados",
    "dedos blancos",
]

#: Cortesía y charla. Media conversación real es esto.
CHARLA = [
    "ok",
    "listo",
    "dale",
    "gracias",
    "perfecto",
    "bueno",
    "si",
    "claro",
    "buenas",
    "hola",
    "que lindos",
    "me encanta",
    "bendiciones",
    "siii",
]

#: Preguntas del negocio. Tienen respuesta escrita: no van a una persona.
DUDAS = [
    "cuanto vale",
    "info",
    "me compartes la guia?",
    "es de plata?",
    "cuanto demora?",
    "hacen envios?",
    "hacen envios a Giron?",
    "nequi",
    "bancolombia",
    "a qué número te envío los 60?",
    "son días hábiles?",
    "tienen garantía?",
    "y si no me queda?",
    "está muy caro",
]


class TestNiUnaPalabraSueltaEscala:
    @pytest.mark.parametrize("texto", NOMBRES)
    def test_un_nombre_de_mascota_no_pide_un_asesor(self, bot, texto):
        assert not escala(bot, texto)

    @pytest.mark.parametrize("texto", DATOS)
    def test_un_dato_del_anillo_no_pide_un_asesor(self, bot, texto):
        assert not escala(bot, texto)

    @pytest.mark.parametrize("texto", CHARLA)
    def test_la_charla_no_pide_un_asesor(self, bot, texto):
        assert not escala(bot, texto)

    @pytest.mark.parametrize("texto", DUDAS)
    def test_una_duda_del_negocio_no_pide_un_asesor(self, bot, texto):
        assert not escala(bot, texto)


class TestLaConversacionRealQueSeMurio:
    """«Hola» · «Si» · «Quiero pedir uno» · «Paco». Textual, por WhatsApp."""

    def test_ninguno_de_los_cuatro_mensajes_escala(self, bot):
        for texto in ("Hola", "Si", "Quiero pedir uno", "Paco"):
            assert not escala(bot, texto), f"escaló en {texto!r}"

    def test_y_el_dato_no_se_tira_por_el_camino(self, bot, mundo):
        """Degradar a OTRO deja que las reglas de Python sigan mirando la
        frase: si trae un color, se anota igual."""
        bot.ejecutar(CONV, "quiero un anillo de 1 huellita")
        bot.ejecutar(CONV, "corazón negro y dedos blancos")
        abiertos = mundo.contexto(CONV).abiertos(TipoProceso.COMPRA)
        assert abiertos and abiertos[0].datos.get("colores")


# ═══════════════════════════════════════════════════════════════════════════
# 2. LO QUE SÍ TIENE QUE IR A UNA PERSONA
# ═══════════════════════════════════════════════════════════════════════════

PIDEN_PERSONA = [
    "quiero hablar con una persona",
    "me pasas con un asesor",
    "hay algun asesor?",
    "necesito hablar con alguien",
    "me pueden llamar?",
    "#humano",
    "#asesor",
]

QUEJAS = [
    "me llegó partido",
    "el anillo está roto",
    "quiero una devolución",
    "esto es una estafa",
    "no me ha llegado nada",
    "se le cayó una piedra",
    "está mal hecho",
    "me llegó el equivocado",
]


class TestLaReglaDeSeguridadSigueEnPie:
    @pytest.mark.parametrize("texto", PIDEN_PERSONA)
    def test_pedir_una_persona_escala(self, bot, texto):
        assert escala(bot, texto)

    @pytest.mark.parametrize("texto", QUEJAS)
    def test_una_queja_escala_siempre(self, bot, texto):
        """Una clienta enfadada no discute con un bot. No se delega en nadie:
        es una regla del negocio, y por eso la decide una lista de palabras."""
        assert escala(bot, texto)


class TestElModeloNoDecideSolo:
    def test_con_un_modelo_que_grita_HUMANO_la_venta_llega_igual(self, bot, mundo):
        """La prueba de fuego: el peor modelo posible y la venta se cierra."""
        for m in (
            "quiero un anillo de 1 huellita",
            "corazón negro y dedos blancos",
            "que diga Paco",
            "talla 7",
            "Carlos Pérez",
            "Bucaramanga",
            "Calle 45 #12-30 apto 301",
        ):
            bot.ejecutar(CONV, m)
        assert mundo.pedidos_de(CONV), "ni con todos los datos se creó el pedido"


# ═══════════════════════════════════════════════════════════════════════════
# 3. TRES PREGUNTAS DISTINTAS NO SON «LA MISMA PREGUNTA» TRES VECES
# ═══════════════════════════════════════════════════════════════════════════


class TestCadaDudaCuentaPorSeparado:
    """Todas las FAQ salían por `RESPONDER_DUDA` y compartían clave, así que la
    cuenta de insistencias subía como si el bot se repitiera. En la conversación
    real: «¿es de plata?», «¿cuánto demora?», «¿hacen envíos a Girón?» — y a la
    tercera contestó «mejor te paso con una personita»."""

    def test_tres_dudas_seguidas_no_escalan(self, bot):
        respuestas = [
            bot.ejecutar(CONV, m).respuesta
            for m in ("es de plata de verdad?", "cuanto demora?", "hacen envios a Giron?")
        ]
        assert not any(r.escalar for r in respuestas)

    def test_cada_duda_tiene_su_propia_clave(self, bot):
        claves = {
            bot.ejecutar(CONV, m).respuesta.clave
            for m in ("es de plata de verdad?", "cuanto demora?", "hacen envios?")
        }
        assert len(claves) == 3, f"dos dudas distintas comparten clave: {claves}"

    def test_la_misma_duda_repetida_si_cambia_de_forma(self, bot):
        """La escalera de insistencias sigue funcionando para la MISMA duda."""
        textos = [
            bot.ejecutar(CONV, "cuanto demora?").respuesta.texto_plano for _ in range(2)
        ]
        assert textos[0] != textos[1]


class TestPreguntarPorElEnvioNoEsPreguntarElTiempo:
    """«¿Hacen envíos a Girón?» se contestaba con los 10 a 15 días de
    fabricación. Ella no preguntó cuánto tarda: preguntó si le llega."""

    def test_hacen_envios_contesta_del_envio(self, bot):
        respuesta = bot.ejecutar(CONV, "hacen envios a Giron?").respuesta.texto_plano
        assert "COORDINADORA" in respuesta

    def test_nombrar_el_envio_manda_siempre(self, bot):
        """Aunque la frase traiga «demora», si nombra el envío contesta del
        envío. Es UNA sola regla a propósito: la versión con excepción dejaba
        dos caminos contestando distinto a la misma frase.

        [POSTERIOR] Lo que de verdad pide «¿cuánto demora el envío?» son los
        días de transporte, que están en data/fletes.csv y no en la respuesta.
        """
        respuesta = bot.ejecutar(CONV, "cuanto demora el envio?").respuesta.texto_plano
        assert "COORDINADORA" in respuesta

    def test_sin_nombrar_el_envio_contesta_el_tiempo(self, bot):
        respuesta = bot.ejecutar(CONV, "cuanto demora?").respuesta.texto_plano
        assert "10 a 15" in respuesta
