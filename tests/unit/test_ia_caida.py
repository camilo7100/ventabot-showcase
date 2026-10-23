"""Cuando la IA se cae, nada se pierde y el bot retoma solo (29/09).

Lo que pasó: Anthropic devolvió 503 a las 9:16. El bot probó una vez más en
menos de un segundo y se rindió: «dame un momentico» y el momentico nunca
llegó. La clienta había dicho «Sí» al resumen: iba a pagar.

Lo que se pide (Camilo):
  · insistir un rato, y si hay respaldo (GPT), probarlo; en vueltas, en orden;
  · si nada contesta: la frase amable y el aviso, UNA vez;
  · reintentar solo hasta que vuelva, y ahí contestarle lo pendiente;
  · no pasar a manos de una persona, salvo que alguien la tome a mano.
"""

from __future__ import annotations

import pytest

from app.adapters.llm.cadena import CadenaDeModelos, es_pasajero
from app.adapters.llm.openai_client import OpenAILLM
from app.conversacion.asesora import MOMENTICO, Asesora, HechosDelNegocio
from app.domain.asesora import CambiosDelBorrador, Confianza, Jugada
from app.domain.models import Channel, Customer
from tests.unit.test_asesora import CONV, ContextoEnMemoria, abrir_conversacion


class Caido(Exception):
    """Como un 503 de Anthropic."""

    status_code = 503


class MalArmado(Exception):
    """Como un 400: se repetiría igual."""

    status_code = 400


class Modelo:
    """Un modelo de mentira: contesta lo que le digan, en orden."""

    def __init__(self, nombre, *respuestas):
        self.model = nombre
        self._respuestas = list(respuestas)
        self.llamadas = 0

    def extract(self, system_prompt, user_text, schema, **kw):
        self.llamadas += 1
        r = self._respuestas.pop(0) if self._respuestas else self._respuestas_fin
        if isinstance(r, Exception):
            raise r
        return r

    _respuestas_fin = Caido("sigue caído")


def _cadena(*modelos, paciencia=35.0):
    reloj = {"t": 0.0}

    def dormir(s):
        reloj["t"] += s

    return CadenaDeModelos(
        list(modelos), paciencia_s=paciencia, dormir=dormir, reloj=lambda: reloj["t"]
    ), reloj


class TestLaCadena:
    def test_si_anthropic_no_contesta_prueba_el_respaldo(self):
        claude = Modelo("claude", Caido())
        gpt = Modelo("gpt", "ok de gpt")
        cadena, _ = _cadena(claude, gpt)
        assert cadena.extract("s", "t", dict) == "ok de gpt"

    def test_en_langsmith_queda_marcado_cuando_contesta_el_respaldo(self, monkeypatch):
        import app.adapters.llm.cadena as cadena

        etiquetas = []
        monkeypatch.setattr(cadena, "etiquetar", lambda *e: etiquetas.extend(e))
        c, _ = _cadena(Modelo("gpt", Caido()), Modelo("claude", "ok"))
        assert c.extract("p", "hola", Jugada) == "ok"
        assert "respaldo" in etiquetas

    def test_si_contesta_el_principal_no_marca_nada(self, monkeypatch):
        import app.adapters.llm.cadena as cadena

        etiquetas = []
        monkeypatch.setattr(cadena, "etiquetar", lambda *e: etiquetas.extend(e))
        c, _ = _cadena(Modelo("gpt", "ok"), Modelo("claude", "no"))
        c.extract("p", "hola", Jugada)
        assert etiquetas == []

    def test_vuelve_a_empezar_por_el_primero(self):
        """Primera vuelta: los dos caídos. Segunda: Anthropic volvió."""
        claude = Modelo("claude", Caido(), "ok de claude")
        gpt = Modelo("gpt", Caido())
        cadena, reloj = _cadena(claude, gpt)
        assert cadena.extract("s", "t", dict) == "ok de claude"
        assert reloj["t"] == 2.0, "esperó antes de la segunda vuelta"

    def test_insiste_hasta_la_paciencia_y_se_rinde(self):
        claude = Modelo("claude")
        cadena, reloj = _cadena(claude, paciencia=35.0)
        with pytest.raises(Caido):
            cadena.extract("s", "t", dict)
        assert claude.llamadas >= 4 and reloj["t"] <= 35.0

    def test_un_error_que_se_repetiria_no_se_reintenta(self):
        claude = Modelo("claude", MalArmado("400"))
        cadena, reloj = _cadena(claude)
        with pytest.raises(MalArmado):
            cadena.extract("s", "t", dict)
        assert claude.llamadas == 1 and reloj["t"] == 0

    @pytest.mark.parametrize(
        ("codigo", "pasajero"),
        [(503, True), (529, True), (429, True), (400, False), (401, False)],
    )
    def test_que_es_pasajero(self, codigo, pasajero):
        exc = Exception()
        exc.status_code = codigo
        assert es_pasajero(exc) is pasajero

    def test_sin_codigo_es_pasajero(self):
        assert es_pasajero(TimeoutError())


class TestGPT:
    def test_arma_la_llamada_y_devuelve_lo_validado(self):
        from types import SimpleNamespace

        visto = {}

        class Completions:
            def parse(self, **kw):
                visto.update(kw)
                mensaje = SimpleNamespace(parsed="validado", refusal=None)
                return SimpleNamespace(
                    choices=[SimpleNamespace(message=mensaje)],
                    usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5),
                )

        cliente = SimpleNamespace(chat=SimpleNamespace(completions=Completions()))
        gpt = OpenAILLM("gpt-x", "sk-prueba", cliente=cliente)
        assert (
            gpt.extract("el prompt", "hola", Jugada, images=[b"\xff\xd8x"]) == "validado"
        )
        assert visto["model"] == "gpt-x" and visto["response_format"] is Jugada
        assert visto["messages"][0] == {"role": "system", "content": "el prompt"}
        partes = visto["messages"][1]["content"]
        assert partes[0] == {"type": "text", "text": "hola"}
        assert partes[1]["image_url"]["url"].startswith("data:image/jpeg;base64,")
        assert "reasoning_effort" not in visto  # sin esfuerzo: el de fábrica

    def test_el_esfuerzo_llega_a_la_api(self):
        from types import SimpleNamespace

        visto = {}

        class Completions:
            def parse(self, **kw):
                visto.update(kw)
                mensaje = SimpleNamespace(parsed="ok", refusal=None)
                return SimpleNamespace(
                    choices=[SimpleNamespace(message=mensaje)],
                    usage=SimpleNamespace(prompt_tokens=1, completion_tokens=1),
                )

        cliente = SimpleNamespace(chat=SimpleNamespace(completions=Completions()))
        OpenAILLM("gpt-6-luna", "sk-prueba", esfuerzo="low", cliente=cliente).extract(
            "p", "hola", Jugada
        )
        assert visto["reasoning_effort"] == "low"

    def test_la_cache_dura_24_horas_y_se_cobra_como_cache(self, monkeypatch):
        """OpenAI cuenta lo de caché DENTRO de `prompt_tokens`. Apuntarlo todo
        como entrada inflaba el costo 10 veces y escondía si la caché servía."""
        from types import SimpleNamespace

        from app.domain import consumo

        visto = {}

        class Completions:
            def parse(self, **kw):
                visto.update(kw)
                mensaje = SimpleNamespace(parsed="ok", refusal=None)
                uso = SimpleNamespace(
                    prompt_tokens=9214,
                    completion_tokens=160,
                    prompt_tokens_details=SimpleNamespace(cached_tokens=9180),
                )
                return SimpleNamespace(
                    choices=[SimpleNamespace(message=mensaje)], usage=uso
                )

        import app.adapters.llm.openai_client as openai_client

        a_langsmith = {}
        monkeypatch.setattr(
            openai_client,
            "uso_del_modelo",
            lambda modelo, **kw: a_langsmith.update(modelo=modelo, **kw),
        )
        cliente = SimpleNamespace(chat=SimpleNamespace(completions=Completions()))
        turno = consumo.abrir_turno()
        OpenAILLM("gpt-6-luna", "sk-prueba", cliente=cliente).extract("p", "hola", Jugada)
        # LangSmith recibe lo mismo, con su proveedor (antes decía «anthropic»).
        assert a_langsmith == {
            "modelo": "gpt-6-luna",
            "entrada": 34,
            "salida": 160,
            "cache_leida": 9180,
            "proveedor": "openai",
        }
        assert visto["prompt_cache_retention"] == "24h"
        llamada = turno.llamadas[-1]
        assert (llamada.entrada, llamada.cache_leida) == (34, 9180)
        # 34 a 0,10 + 9.180 a 0,01 + 160 a 0,50, por millón.
        assert llamada.usd == pytest.approx((34 * 0.10 + 9180 * 0.01 + 160 * 0.50) / 1e6)


# ---------------------------------------------------------------------------
# La asesora: lo pendiente
# ---------------------------------------------------------------------------


def _jugada(mensaje="¡Perfecto! 🫶"):
    return Jugada(
        lectura="prueba",
        cambios=CambiosDelBorrador(),
        acciones=[],
        mensaje=mensaje,
        mensaje_final="",
        confianza=Confianza.ALTA,
    )


class Guion:
    """Contesta (o se cae) en el orden en que se le dé; recuerda lo que leyó."""

    def __init__(self, *respuestas):
        self._r = list(respuestas)
        self.model = "guion"
        self.entradas: list[str] = []

    def extract(self, system_prompt, user_text, schema, **kw):
        self.entradas.append(user_text)
        r = self._r.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


@pytest.fixture
def mundo():
    from app.adapters.repositories.memory import (
        InMemoryCustomerRepository,
        InMemoryOrderRepository,
        InMemoryProductRepository,
    )
    from app.conversacion.mundo import Mundo

    customers = InMemoryCustomerRepository()
    customers.upsert(
        Customer(id="c1", channel=Channel.WHATSAPP, channel_user_id="573001112233")
    )
    m = Mundo(
        InMemoryOrderRepository(),
        customers,
        InMemoryProductRepository([]),
        ContextoEnMemoria(),
    )
    abrir_conversacion(m)
    return m


def _asesora(mundo, guion, avisos=None):
    return Asesora(
        mundo,
        guion,
        "{hechos}",
        HechosDelNegocio(precios={1: 200_000}),
        avisar=(lambda t, d, k: avisos.append(t)) if avisos is not None else None,
    )


class TestLasCapasQuedanApuntadas:
    def test_cada_llamada_dice_de_que_capa_es(self, mundo):
        """Antes del 29/09 el registro decía «?» en todas: `vb metricas` no
        distinguía el básico del potente."""
        from app.domain import consumo

        class QueApunta(Guion):
            def extract(self, system_prompt, user_text, schema, **kw):
                consumo.registrar("guion")
                return super().extract(system_prompt, user_text, schema, **kw)

        a = _asesora(mundo, QueApunta(_jugada()))
        a.ejecutar(CONV, "hola")
        capas = [x.capa for x in consumo.actual().llamadas]
        assert capas and capas[0] == "basico" and "?" not in capas


class TestLoPendiente:
    def test_la_primera_caida_avisa_y_guarda_lo_que_dijo(self, mundo):
        avisos = []
        a = _asesora(mundo, Guion(Caido()), avisos)
        t = a.ejecutar(CONV, "Sí")
        assert t.respuesta.texto_plano == MOMENTICO
        assert t.respuesta.escalar, "la alerta de Chatwoot"
        assert avisos == ["La IA no respondió"]
        pendiente = mundo.contexto(CONV).pendiente_ia
        assert pendiente["texto"] == "Sí" and pendiente["intentos"] == 1

    def test_la_segunda_no_repite_el_momentico_y_junta_los_mensajes(self, mundo):
        avisos = []
        a = _asesora(mundo, Guion(Caido(), Caido()), avisos)
        a.ejecutar(CONV, "Sí")
        t = a.ejecutar(CONV, "?")
        assert t.respuesta.vacia, "le repitió el momentico"
        assert avisos == ["La IA no respondió"]
        assert mundo.contexto(CONV).pendiente_ia["texto"] == "Sí\n?"

    def test_cuando_vuelve_le_contesta_todo_y_borra_lo_pendiente(self, mundo):
        guion = Guion(Caido(), _jugada("¡Listo! Te dejo los datos 💓"))
        a = _asesora(mundo, guion)
        a.ejecutar(CONV, "Sí")
        t = a.ejecutar(CONV, None, None, reintento=True)
        assert "Te dejo los datos" in t.respuesta.texto_plano
        assert "Sí" in guion.entradas[-1], "el modelo no leyó lo que ella dijo"
        assert mundo.contexto(CONV).pendiente_ia is None

    def test_un_mensaje_nuevo_tambien_contesta_lo_pendiente(self, mundo):
        guion = Guion(Caido(), _jugada())
        a = _asesora(mundo, guion)
        a.ejecutar(CONV, "Sí")
        a.ejecutar(CONV, "hola?")
        assert "Sí\nhola?" in guion.entradas[-1]
        assert mundo.contexto(CONV).pendiente_ia is None

    def test_un_reintento_sin_nada_pendiente_no_hace_nada(self, mundo):
        guion = Guion()
        t = _asesora(mundo, guion).ejecutar(CONV, None, None, reintento=True)
        assert t.respuesta.vacia and not guion.entradas


# ---------------------------------------------------------------------------
# El contenedor: el reintento en segundo plano
# ---------------------------------------------------------------------------


@pytest.fixture
def entorno(monkeypatch, tmp_path):
    import app.infra.container as contenedor
    from app.adapters.crm.chatwoot import CrmDeMentira
    from app.infra.settings import get_settings

    monkeypatch.setenv("REPOSITORY_BACKEND", "memory")
    monkeypatch.setenv("CHANNEL_BACKEND", "console")
    monkeypatch.setenv("LLM_BACKEND", "fake")
    monkeypatch.setenv("SQLITE_PATH", str(tmp_path / "t.db"))
    get_settings.cache_clear()
    contenedor._singleton = None
    c = contenedor.get_container()
    c.customers.upsert(
        Customer(id="c1", channel=Channel.WHATSAPP, channel_user_id="573001112233")
    )
    espejo = CrmDeMentira()
    monkeypatch.setattr(c, "crm", espejo)
    avisos = []

    class Avisos:
        def avisar(self, titulo, detalle, clave):
            avisos.append(titulo)

    monkeypatch.setattr(c, "avisos", Avisos())
    abrir_conversacion(c.bot._mundo)
    yield c, espejo, avisos
    get_settings.cache_clear()
    contenedor._singleton = None


def _con_guion(c, monkeypatch, *respuestas):
    guion = Guion(*respuestas)
    monkeypatch.setattr(c, "bot", _asesora(c.bot._mundo, guion))
    return guion


def _vencer_el_proximo_intento(c):
    mundo = c.bot._mundo
    ctx = mundo.contexto(CONV)
    pendiente = dict(ctx.pendiente_ia, proximo="2000-01-01T00:00:00+00:00")
    mundo.guardar_contexto(ctx.model_copy(update={"pendiente_ia": pendiente}))


class TestElReintento:
    def test_cuando_vuelve_la_ia_le_contesta_y_quita_la_alerta(
        self, entorno, monkeypatch
    ):
        c, espejo, avisos = entorno
        _con_guion(c, monkeypatch, Caido(), _jugada("¡Listo! Te dejo los datos 💓"))
        c.bot.ejecutar(CONV, "Sí")
        c.actualizar_seguimiento(CONV, escalada=True)
        _vencer_el_proximo_intento(c)
        assert c.reintentar_turnos_pendientes() == 1
        assert any("Te dejo los datos" in (m.text or "") for m in c.outbox.pending(20))
        ctx = c.bot._mundo.contexto(CONV)
        assert ctx.pendiente_ia is None and not ctx.necesita_persona
        assert any("La IA volvió" in t for _, t, _ in espejo.copias)
        assert "✅ La IA volvió" in avisos

    def test_antes_de_su_hora_no_reintenta(self, entorno, monkeypatch):
        c, _, _ = entorno
        guion = _con_guion(c, monkeypatch, Caido(), _jugada())
        c.bot.ejecutar(CONV, "Sí")
        assert c.reintentar_turnos_pendientes() == 0
        assert len(guion.entradas) == 1, "reintentó sin esperar"

    def test_si_sigue_caida_no_le_escribe_nada(self, entorno, monkeypatch):
        c, _, _ = entorno
        _con_guion(c, monkeypatch, Caido(), Caido())
        c.bot.ejecutar(CONV, "Sí")
        antes = len(c.outbox.pending(20))
        _vencer_el_proximo_intento(c)
        assert c.reintentar_turnos_pendientes() == 0
        assert len(c.outbox.pending(20)) == antes
        assert c.bot._mundo.contexto(CONV).pendiente_ia["intentos"] == 2

    def test_si_la_tomo_una_persona_el_bot_no_se_mete(self, entorno, monkeypatch):
        c, _, _ = entorno
        guion = _con_guion(c, monkeypatch, Caido(), _jugada())
        c.bot.ejecutar(CONV, "Sí")
        c.bot._mundo.pausar_por_humano(CONV)
        _vencer_el_proximo_intento(c)
        assert c.reintentar_turnos_pendientes() == 0
        assert len(guion.entradas) == 1
        assert c.bot._mundo.contexto(CONV).pendiente_ia is None


class TestLaConfiguracion:
    def test_sin_respaldo_la_cadena_es_solo_anthropic(self, monkeypatch):
        from app.infra.container import _modelos_con_respaldo
        from app.infra.settings import Settings

        s = Settings(llm_fuerte_model="claude-sonnet-5-5", anthropic_api_key="x")
        basico, fuerte = _modelos_con_respaldo(s)
        assert basico.model == "claude-haiku-5-5"
        assert fuerte.model == "claude-sonnet-5-5"

    def test_con_gpt_va_despues_de_anthropic(self):
        from app.infra.container import _modelos_con_respaldo
        from app.infra.settings import Settings

        s = Settings(
            llm_fuerte_model="claude-sonnet-5-5",
            anthropic_api_key="x",
            ia_principal="anthropic",
            llm_respaldo_backend="openai",
            openai_api_key="sk-x",
            openai_modelo="gpt-basico",
            openai_modelo_fuerte="gpt-fuerte",
        )
        basico, fuerte = _modelos_con_respaldo(s)
        assert basico.model == "claude-haiku-5-5 → gpt-basico"
        assert fuerte.model == "claude-sonnet-5-5 → gpt-fuerte"

    def test_produccion_gpt_primero_y_claude_de_respaldo(self):
        """Lo de docker-compose.yml desde el 29/09: luna sin razonar para casi
        todo, la misma luna razonando un poco cuando duda, y Claude detrás."""
        from app.infra.container import _modelos_con_respaldo
        from app.infra.settings import Settings

        s = Settings(
            llm_basico_model="claude-haiku-5-5",
            llm_fuerte_model="claude-sonnet-5-5",
            anthropic_api_key="x",
            ia_principal="openai",
            llm_respaldo_backend="openai",
            openai_api_key="sk-x",
            openai_modelo="gpt-6-luna",
            openai_esfuerzo="none",
            openai_modelo_fuerte="gpt-6-luna",
            openai_esfuerzo_fuerte="low",
        )
        basico, fuerte = _modelos_con_respaldo(s)
        assert basico.model == "gpt-6-luna → claude-haiku-5-5"
        assert fuerte.model == "gpt-6-luna → claude-sonnet-5-5"
        assert basico._modelos[0]._esfuerzo == "none"
        assert fuerte._modelos[0]._esfuerzo == "low"

    def test_los_ojos_usan_la_misma_cadena_con_su_modelo(self):
        """29/09: Haiku leyó un comprobante de $60.000 como $60.000.000; luna,
        bien. Las fotos también van GPT primero, con Claude detrás."""
        from app.infra.container import _modelos_con_respaldo
        from app.infra.settings import Settings

        s = Settings(
            llm_fuerte_model="claude-sonnet-5-5",
            anthropic_api_key="x",
            ia_principal="openai",
            llm_respaldo_backend="openai",
            openai_api_key="sk-x",
            openai_modelo="gpt-6-luna",
        )
        vista, _ = _modelos_con_respaldo(s, claude_basico_modelo="claude-ojos")
        assert vista.model == "gpt-6-luna → claude-ojos"

    def test_gpt_primero_sin_su_clave_se_queda_con_claude(self):
        """Pedir GPT primero sin clave no deja al bot sin IA."""
        from app.infra.container import _modelos_con_respaldo
        from app.infra.settings import Settings

        s = Settings(
            llm_fuerte_model="claude-sonnet-5-5",
            anthropic_api_key="x",
            ia_principal="openai",
            llm_respaldo_backend="openai",
            openai_api_key="",
            openai_modelo="gpt-6-luna",
        )
        basico, fuerte = _modelos_con_respaldo(s)
        assert basico.model == "claude-haiku-5-5"
        assert fuerte.model == "claude-sonnet-5-5"
