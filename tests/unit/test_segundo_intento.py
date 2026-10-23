"""Dos memorias que se desincronizan, y el segundo intento con el modelo grande.

Los dos salieron de la misma conversación por WhatsApp, la de «Patroclo».

════════════════════════════════════════════════════════════════════════════
1. LA REFERENCIA COLGANDO
════════════════════════════════════════════════════════════════════════════
El contexto conversacional vive en SQLite y los pedidos viven en el
repositorio, que es OTRA cosa. Con `REPOSITORY_BACKEND=memory` los pedidos se
van al reiniciar y el contexto NO: queda un proceso apuntando con `pedido_id` a
un pedido que ya no existe, y el turno entero se caía con `ConflictoDeEstado`.

════════════════════════════════════════════════════════════════════════════
2. EL SEGUNDO INTENTO
════════════════════════════════════════════════════════════════════════════
Un modelo de 3B no entiende algunos turnos. Antes eso acababa en «no te
entendí». Ahora, SOLO en los turnos donde no se entendió nada —ni el modelo ni
las reglas de Python—, se vuelve a preguntar con un modelo más grande y con los
últimos mensajes en orden. Lo que devuelve pasa por las MISMAS reglas: describe
mejor, no decide más.
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
from app.domain.interpretacion import Acto, Entidad, Interpretacion
from app.domain.models import Channel, Customer, Product

CONV = "wa:573001110001"


class ContextoEnMemoria:
    def __init__(self):
        self._d: dict[str, ContextoConversacional] = {}

    def cargar(self, conv_id):
        return self._d.get(conv_id) or ContextoConversacional(conversation_id=conv_id)

    def guardar(self, ctx):
        self._d[ctx.conversation_id] = ctx


class ModeloMudo:
    """No entiende nada, nunca. Es el 3B en su peor día."""

    def extract(self, prompt, texto, esquema):
        return Interpretacion(acto=Acto.OTRO, confianza="BAJA")


class ModeloGrande:
    """El de rescate. Apunta qué se le mandó, para poder mirarlo."""

    def __init__(self, respuesta: Interpretacion | None = None):
        self.visto: list[str] = []
        self._respuesta = respuesta or Interpretacion(
            acto=Acto.COMPRAR, entidad=Entidad.PRODUCTO, confianza="ALTA"
        )

    def extract(self, prompt, texto, esquema):
        self.visto.append(texto)
        return self._respuesta


class ModeloGrandeRoto:
    def extract(self, prompt, texto, esquema):
        raise TimeoutError("el modelo grande no cargó")


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
            channel_user_id="573001110001",
            nombre="Ángela",
        )
    )
    return Mundo(InMemoryOrderRepository(), customers, _productos(), ContextoEnMemoria())


def _bot(mundo, *, llm=None, grande=None, historial=None):
    interprete = Interprete(
        llm or ModeloMudo(),
        prompt="",
        catalogo_txt="",
        llm_fuerte=grande,
        historial=historial,
    )
    return Pipeline(interprete, mundo, Ejecutor(mundo), Redactor())


def _compra_completa(bot):
    for m in (
        "quiero un anillo de 1 huellita",
        "corazón negro y dedos blancos",
        "que diga Patroclo",
        "talla 7",
        "Carlos Pérez",
        "Bucaramanga",
        "Calle 45 #12-30 apto 301",
    ):
        bot.ejecutar(CONV, m)


# ═══════════════════════════════════════════════════════════════════════════
# 1. UN PEDIDO QUE YA NO EXISTE NO PUEDE TUMBAR EL TURNO
# ═══════════════════════════════════════════════════════════════════════════


class TestLaReferenciaColgando:
    def test_el_turno_no_revienta(self, mundo):
        bot = _bot(mundo)
        _compra_completa(bot)
        pedido = mundo.pedidos_de(CONV)[0]

        # Se pierde el pedido y el contexto NO. Es lo que pasa al reiniciar
        # con REPOSITORY_BACKEND=memory.
        mundo._orders._o.pop(pedido.id, None)

        bot.ejecutar(CONV, "Patroclo")  # antes: ConflictoDeEstado

    def test_la_venta_se_recupera(self, mundo):
        """Lo que ella eligió sigue entero en el proceso, así que el pedido se
        vuelve a crear con los mismos datos. No se pierde la venta."""
        bot = _bot(mundo)
        _compra_completa(bot)
        pedido = mundo.pedidos_de(CONV)[0]
        mundo._orders._o.pop(pedido.id, None)

        bot.ejecutar(CONV, "Patroclo")

        de_nuevo = mundo.pedidos_de(CONV)
        assert de_nuevo, "la venta se perdió"
        descripcion = de_nuevo[0].items[0].personalizacion.describir()
        assert "Patroclo" in descripcion
        assert "negro" in descripcion

    def test_se_olvida_la_referencia_muerta(self, mundo):
        bot = _bot(mundo)
        _compra_completa(bot)
        viejo = mundo.pedidos_de(CONV)[0].id
        mundo._orders._o.pop(viejo, None)

        bot.ejecutar(CONV, "Patroclo")

        procesos = mundo.contexto(CONV).abiertos(TipoProceso.COMPRA)
        apuntan = {p.datos.get("pedido_id") for p in procesos}
        assert viejo not in apuntan

    def test_con_el_pedido_vivo_no_se_duplica(self, mundo):
        """La salvedad no puede crear un pedido nuevo cada vez que hablan."""
        bot = _bot(mundo)
        _compra_completa(bot)
        cuantos = len(mundo.pedidos_de(CONV))
        bot.ejecutar(CONV, "Patroclo")
        assert len(mundo.pedidos_de(CONV)) == cuantos


# ═══════════════════════════════════════════════════════════════════════════
# 2. EL SEGUNDO INTENTO
# ═══════════════════════════════════════════════════════════════════════════


class TestCuandoSeGastaElModeloGrande:
    def test_si_el_pequeno_no_entendio_nada_se_rescata(self, mundo):
        grande = ModeloGrande()
        bot = _bot(mundo, grande=grande)
        turno = bot.ejecutar(CONV, "pues eso que te dije ayer")
        assert grande.visto, "no se intentó el rescate"
        assert turno.interpretacion.acto is Acto.COMPRAR

    def test_si_python_saco_un_dato_NO_se_gasta(self, mundo):
        """Con un dato en la mano la conversación avanza igual, y el modelo
        grande solo añadiría espera."""
        grande = ModeloGrande()
        bot = _bot(mundo, grande=grande)
        bot.ejecutar(CONV, "quiero un anillo de 1 huellita")
        bot.ejecutar(CONV, "corazón negro y dedos blancos")
        assert not grande.visto

    def test_sin_modelo_grande_todo_sigue_igual(self, mundo):
        bot = _bot(mundo, grande=None)
        turno = bot.ejecutar(CONV, "pues eso que te dije ayer")
        assert turno.interpretacion.acto is Acto.OTRO

    def test_si_el_grande_falla_vale_lo_que_ya_teniamos(self, mundo):
        """Un rescate que no rescata no puede costar un turno."""
        bot = _bot(mundo, grande=ModeloGrandeRoto())
        turno = bot.ejecutar(CONV, "pues eso que te dije ayer")
        assert turno.interpretacion.acto is Acto.OTRO
        assert turno.respuesta.piezas, "se quedó sin respuesta"

    def test_si_el_grande_tampoco_entiende_no_cambia_nada(self, mundo):
        grande = ModeloGrande(Interpretacion(acto=Acto.OTRO, confianza="BAJA"))
        bot = _bot(mundo, grande=grande)
        turno = bot.ejecutar(CONV, "pues eso que te dije ayer")
        assert turno.interpretacion.acto is Acto.OTRO


class TestElHistorialQueSeLeManda:
    def test_van_los_mensajes_anteriores_en_orden(self, mundo):
        grande = ModeloGrande()
        historial = lambda _c: [  # noqa: E731
            {"de": "clienta", "texto": "cuanto vale?"},
            {"de": "bot", "texto": "200.000 con una huellita"},
            {"de": "clienta", "texto": "y de dos?"},
        ]
        bot = _bot(mundo, grande=grande, historial=historial)
        bot.ejecutar(CONV, "pues eso")

        mandado = grande.visto[0]
        assert mandado.index("cuanto vale?") < mandado.index("y de dos?")
        assert "CLIENTA" in mandado and "TIENDA" in mandado

    def test_el_mensaje_de_ahora_va_al_final_y_marcado(self, mundo):
        grande = ModeloGrande()
        bot = _bot(
            mundo,
            grande=grande,
            historial=lambda _c: [{"de": "clienta", "texto": "hola"}],
        )
        bot.ejecutar(CONV, "pues eso")
        assert grande.visto[0].rstrip().endswith("pues eso")
        assert "DESCRIBE SOLAMENTE" in grande.visto[0]

    def test_sin_historial_se_manda_el_mensaje_a_secas(self, mundo):
        grande = ModeloGrande()
        bot = _bot(mundo, grande=grande, historial=None)
        bot.ejecutar(CONV, "pues eso")
        assert grande.visto == ["pues eso"]

    def test_un_historial_que_falla_no_tumba_el_rescate(self, mundo):
        def revienta(_c):
            raise RuntimeError("la base de datos se cayó")

        grande = ModeloGrande()
        bot = _bot(mundo, grande=grande, historial=revienta)
        bot.ejecutar(CONV, "pues eso")
        assert grande.visto == ["pues eso"]


class TestElModeloGrandeTampocoDecide:
    def test_no_puede_llamar_a_una_persona_por_su_cuenta(self, mundo):
        """Pasa por `_corregir` igual que el camino normal, así que la regla de
        que a una persona la llaman las PALABRAS también le aplica a él."""
        grande = ModeloGrande(Interpretacion(acto=Acto.HUMANO, confianza="ALTA"))
        bot = _bot(mundo, grande=grande)
        turno = bot.ejecutar(CONV, "Patroclo")
        assert not turno.respuesta.escalar

    def test_los_colores_los_sigue_leyendo_python(self, mundo):
        """Un modelo mejor entiende mejor la intención. Un color es una palabra
        del muestrario: está en la frase o no está."""
        grande = ModeloGrande(
            Interpretacion(acto=Acto.INFORMAR, entidad=Entidad.COLOR, confianza="ALTA")
        )
        bot = _bot(mundo, grande=grande)
        turno = bot.ejecutar(CONV, "pues eso que te dije")
        assert turno.interpretacion.datos.color_corazon is None


# ═══════════════════════════════════════════════════════════════════════════
# 3. EL ADAPTADOR DE CLAUDE
# ═══════════════════════════════════════════════════════════════════════════


class TestElAvisoDeCuentaSinSaldo:
    """El fallo nº1 de una cuenta nueva, y NO es un error de clave.

    La clave es válida, la API contesta 400 y el mensaje dice «credit balance is
    too low». Sin un caso propio, el log soltaba el JSON entero de Anthropic en
    cada mensaje de cada clienta y el aviso útil se perdía dentro.
    """

    def _claude(self):
        from app.adapters.llm.anthropic_client import ClaudeLLM

        return ClaudeLLM("claude-haiku-4-5", "sk-ant-de-prueba")

    def test_el_aviso_de_saldo_sale_una_sola_vez(self, caplog):
        import logging

        claude = self._claude()
        falta_saldo = Exception(
            "Error code: 400 - {'message': 'Your credit balance is too low "
            "to access the Anthropic API.'}"
        )
        with caplog.at_level(logging.ERROR, logger="ventabot.claude"):
            for _ in range(3):
                claude._explicar(falta_saldo)

        assert caplog.text.count("NO TIENE SALDO") == 1

    def test_el_aviso_dice_que_hacer(self, caplog):
        import logging

        claude = self._claude()
        with caplog.at_level(logging.ERROR, logger="ventabot.claude"):
            claude._explicar(Exception("400 credit balance is too low"))

        assert "Plans & Billing" in caplog.text
        assert "LLM_FUERTE_MODEL" in caplog.text

    def test_un_fallo_pasajero_si_se_repite_en_el_log(self, caplog):
        """Un límite de ritmo pasa y vuelve: ese sí interesa cada vez."""
        import logging

        import anthropic

        claude = self._claude()
        with caplog.at_level(logging.WARNING, logger="ventabot.claude"):
            for _ in range(2):
                claude._explicar(
                    anthropic.APIConnectionError(request=None)  # type: ignore[arg-type]
                )

        assert caplog.text.count("sin internet") == 2


class TestElAdaptadorDeClaudeCumpleElPuerto:
    def test_tiene_la_firma_de_LLMPort(self):
        """Si la firma se desvía, el rescate deja de ser intercambiable."""
        import inspect

        from app.adapters.llm.anthropic_client import ClaudeLLM
        from app.adapters.llm.ollama_client import OllamaLLM

        de_claude = inspect.signature(ClaudeLLM.extract).parameters
        de_ollama = inspect.signature(OllamaLLM.extract).parameters
        assert list(de_claude) == list(de_ollama)

    def test_no_se_conecta_al_construirlo(self):
        """El cliente es perezoso: construir el contenedor no puede depender de
        que haya internet ni de que la clave sirva."""
        from app.adapters.llm.anthropic_client import ClaudeLLM

        assert ClaudeLLM("claude-haiku-4-5", "sk-ant-falsa")._client is None


class TestLoQueSeLeMandaAClaude:
    """Lo barato del rescate depende de DOS cosas que no se ven al leer el log.

    Medido contra la API de verdad, con Haiku 4.5:
      · sin caché        4.757 tokens de entrada -> USD 0,0050 por rescate
      · leyendo caché       19 tokens nuevos     -> USD 0,0007 por rescate
    Siete veces menos, y el 95% del coste es el prompt, que es siempre el mismo.
    """

    def _espia(self):
        """Un cliente falso que apunta con qué se llamó a la API."""

        class Respuesta:
            parsed_output = Interpretacion(acto=Acto.CONVERSAR)

        class Mensajes:
            def __init__(self):
                self.kwargs = None

            def parse(self, **kwargs):
                self.kwargs = kwargs
                return Respuesta()

        class Cliente:
            def __init__(self):
                self.messages = Mensajes()

        from app.adapters.llm.anthropic_client import ClaudeLLM

        claude = ClaudeLLM("claude-haiku-4-5", "sk-ant-de-prueba")
        claude._client = Cliente()
        return claude

    def test_el_prompt_va_marcado_para_cachear(self):
        from app.domain.interpretacion import PropuestaDelModelo

        claude = self._espia()
        claude.extract("EL PROMPT LARGO", "hola", PropuestaDelModelo)

        sistema = claude._client.messages.kwargs["system"]
        assert isinstance(sistema, list), "el prompt tiene que ir como bloque"
        assert sistema[0]["cache_control"] == {"type": "ephemeral"}
        assert sistema[0]["text"] == "EL PROMPT LARGO"

    def test_el_mensaje_de_la_clienta_NO_se_cachea(self):
        """Cambia en cada turno: cachearlo no acertaría nunca y ensuciaría el
        prefijo estable, que es lo único que ahorra."""
        from app.domain.interpretacion import PropuestaDelModelo

        claude = self._espia()
        claude.extract("EL PROMPT", "quiero un anillo", PropuestaDelModelo)

        mensajes = claude._client.messages.kwargs["messages"]
        assert "cache_control" not in str(mensajes)

    def test_no_manda_effort_porque_haiku_lo_rechaza(self):
        """Haiku 4.5 devuelve un 400 si se le manda `output_config.effort`."""
        from app.domain.interpretacion import PropuestaDelModelo

        claude = self._espia()
        claude.extract("EL PROMPT", "hola", PropuestaDelModelo)
        assert "output_config" not in claude._client.messages.kwargs

    def test_el_texto_va_despues_de_las_fotos(self):
        """Una foto con su pie: la imagen primero, como pide la API."""
        from app.domain.interpretacion import PropuestaDelModelo

        claude = self._espia()
        claude.extract("P", "mira esto", PropuestaDelModelo, images=[b"jpeg"])

        bloques = claude._client.messages.kwargs["messages"][0]["content"]
        assert [b["type"] for b in bloques] == ["image", "text"]


class TestNoSeEsperaDiezMinutos:
    def test_el_tope_de_espera_es_de_segundos(self):
        """El SDK espera 600 s por defecto. Del otro lado hay una clienta
        mirando WhatsApp: si Claude no contesta rápido, se sigue sin él."""
        from app.adapters.llm.anthropic_client import ESPERA_MAXIMA_S, ClaudeLLM

        assert ESPERA_MAXIMA_S <= 15, "demasiado para alguien esperando un chat"
        cliente = ClaudeLLM("claude-haiku-4-5", "sk-ant-de-prueba")._get_client()
        assert cliente.timeout == ESPERA_MAXIMA_S
        assert cliente.max_retries == 1
