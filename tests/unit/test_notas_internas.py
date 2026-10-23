"""Al mover un pedido, Lía puede escribirle a la clienta Y anotar algo interno.

Dos textos opcionales por transición (Camilo, 27/09):
  · el MENSAJE le llega a la clienta por WhatsApp y queda en Chatwoot;
  · la NOTA INTERNA no le llega: queda como nota privada en Chatwoot, con su
    tipo y su pedido, y la asesora la lee como contexto, APARTE de la charla,
    sin confundirla con algo que escribió la clienta.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.domain.models import Channel, Customer
from app.domain.notas_internas import nota_de_pedido, nota_de_talla, para_chatwoot
from app.domain.order_state import OrderState

TOKEN = "token-de-prueba-1234"
CONV = "wa:573001112233"
CLIENTA = Customer(
    id="c1", channel=Channel.WHATSAPP, channel_user_id="573001112233", nombre="Ángela"
)


class TestSonClasificables:
    def test_la_nota_dice_de_que_es(self):
        n = nota_de_pedido(
            "  La foto no es\nsuficientemente clara  ",
            codigo="PED-2026-0417",
            destino=OrderState.EN_PRODUCCION,
        )
        assert n["tipo"] == "taller" and n["etapa"] == "En el taller"
        assert n["pedido"] == "PED-2026-0417" and n["autor"] == "panel"
        assert n["texto"] == "La foto no es suficientemente clara"
        assert n["cuando"]

    def test_confirmar_el_abono_es_de_tipo_abono(self):
        n = nota_de_pedido("ok", codigo="P", destino="ANTICIPO_PAGADO")
        assert n["tipo"] == "abono"

    def test_en_chatwoot_lleva_una_cabecera_que_se_puede_buscar(self):
        texto = para_chatwoot(nota_de_talla("Talla 8.", codigo="PED-2026-0417"))
        assert texto.splitlines()[0] == "🗒️ NOTA INTERNA · talla · PED-2026-0417"
        assert texto.splitlines()[1] == "Talla 8."


@pytest.fixture
def entorno(monkeypatch, tmp_path):
    import app.infra.container as contenedor
    from app.infra.settings import get_settings

    monkeypatch.setenv("PANEL_TOKEN", TOKEN)
    monkeypatch.setenv("REPOSITORY_BACKEND", "memory")
    monkeypatch.setenv("CHANNEL_BACKEND", "console")
    monkeypatch.setenv("LLM_BACKEND", "fake")
    monkeypatch.setenv("SQLITE_PATH", str(tmp_path / "t.db"))
    get_settings.cache_clear()
    contenedor._singleton = None

    from app.adapters.crm.chatwoot import CrmDeMentira
    from app.api.main import app

    c = contenedor.get_container()
    c.customers.upsert(CLIENTA)
    espejo = CrmDeMentira()
    monkeypatch.setattr(c, "crm", espejo)
    yield TestClient(app), c, espejo

    get_settings.cache_clear()
    contenedor._singleton = None


def _al_taller(cliente, c, **textos):
    from tests.unit.test_panel import _completo

    pedido = c.orders.create(
        _completo(OrderState.ANTICIPO_PAGADO, anticipo_pagado_cop=60_000), idem_key="k"
    )
    cliente.post(
        f"/panel/mover?token={TOKEN}",
        data={"pedido_id": pedido.id, "destino": "EN_PRODUCCION", **textos},
    )
    return pedido


class TestDesdeElPanel:
    def test_la_tarjeta_trae_los_dos_textos(self, entorno):
        cliente, c, _ = entorno
        from tests.unit.test_panel import _completo

        c.orders.create(_completo(OrderState.ANTICIPO_PAGADO), idem_key="k")
        pagina = cliente.get(f"/panel?token={TOKEN}").text
        assert "name=mensaje" in pagina and "name=nota" in pagina
        assert "Tu mensaje le llega a la clienta" in pagina

    def test_sin_textos_todo_es_como_antes(self, entorno):
        cliente, c, espejo = entorno
        _al_taller(cliente, c)
        assert not c.bot._mundo.contexto(CONV).notas_internas
        assert not any("NOTA INTERNA" in t for _, t, _ in espejo.copias)

    def test_la_nota_NO_le_llega_a_la_clienta(self, entorno):
        cliente, c, espejo = entorno
        _al_taller(cliente, c, nota="Talla 8. Es la que mejor corresponde con la foto.")
        enviados = " ".join(m.text or "" for m in c.outbox.pending(20))
        assert "mejor corresponde" not in enviados
        privadas = [
            t for _, t, _ in espejo.copias if t.startswith("[nota] 🗒️ NOTA INTERNA")
        ]
        assert privadas == [
            "[nota] 🗒️ NOTA INTERNA · taller · PED-2026-0417 · En el taller\n"
            "Talla 8. Es la que mejor corresponde con la foto."
        ]

    def test_la_nota_queda_aparte_de_la_charla(self, entorno):
        cliente, c, _ = entorno
        _al_taller(cliente, c, nota="Ojo con el grabado")
        ctx = c.bot._mundo.contexto(CONV)
        assert [n["texto"] for n in ctx.notas_internas] == ["Ojo con el grabado"]
        assert not any("Ojo con el grabado" in m["texto"] for m in ctx.charla)

    def test_el_mensaje_le_llega_despues_del_aviso(self, entorno):
        cliente, c, espejo = entorno
        _al_taller(cliente, c, mensaje="¡Ya empezamos con tu anillo! 💍")
        textos = [m.text for m in c.outbox.pending(20) if m.text]
        assert textos[-1] == "¡Ya empezamos con tu anillo! 💍"
        assert len(textos) >= 2, "se perdió el aviso automático"
        salientes = [t for _, t, kw in espejo.copias if kw.get("entrante") is False]
        assert "¡Ya empezamos con tu anillo! 💍" in salientes
        charla = c.bot._mundo.contexto(CONV).charla
        assert charla[-1] == {"de": "lia", "texto": "¡Ya empezamos con tu anillo! 💍"}

    def test_dos_clics_un_solo_mensaje(self, entorno):
        """La clave del mensaje es estable: el reenvío del mismo texto en la
        misma transición se descarta en la outbox."""
        from app.infra.container import _huella

        cliente, c, _ = entorno
        pedido = _al_taller(cliente, c, mensaje="Hola")
        clave = f"lia:{pedido.id}:EN_PRODUCCION:{_huella('Hola')}"
        c.escribirle_de_parte_de_lia(CONV, "Hola", clave)
        assert [m.text for m in c.outbox.pending(20)].count("Hola") == 1


class TestLaAsesoraLasLee:
    @pytest.fixture
    def asesora(self):
        from app.adapters.repositories.memory import (
            InMemoryCustomerRepository,
            InMemoryOrderRepository,
            InMemoryProductRepository,
        )
        from app.conversacion.mundo import Mundo
        from tests.unit.test_asesora import ContextoEnMemoria, _asesora

        mundo = Mundo(
            InMemoryOrderRepository(),
            InMemoryCustomerRepository(),
            InMemoryProductRepository([]),
            ContextoEnMemoria(),
        )
        return _asesora(mundo, nueva=True)

    def test_van_en_su_propia_seccion_y_nunca_como_de_la_clienta(self, asesora):
        from app.domain.asesora import Borrador

        nota = nota_de_talla("Talla 8 confirmada", codigo="PED-2026-0417")
        entrada = asesora._entrada(
            Borrador(), None, [{"de": "clienta", "texto": "hola"}], "gracias", [], [nota]
        )
        seccion = entrada.split("# NOTAS INTERNAS DE LIA")[1].split("# CONVERSACIÓN")[0]
        assert "la clienta no las ve ni las escribió" in seccion
        assert "talla · PED-2026-0417] Talla 8 confirmada" in seccion
        conversacion = entrada.split("# CONVERSACIÓN RECIENTE")[1]
        assert "Talla 8 confirmada" not in conversacion

    def test_sin_notas_dice_ninguna(self, asesora):
        from app.domain.asesora import Borrador

        entrada = asesora._entrada(Borrador(), None, [], "hola", [])
        assert "# NOTAS INTERNAS DE LIA" in entrada and "- ninguna" in entrada


class TestLaRafagaQuedaMensajePorMensaje:
    """Una ráfaga se atiende en un turno, pero cada mensaje se guarda y se
    copia a Chatwoot como lo escribió ella."""

    def test_cada_parte_en_el_historial_y_en_chatwoot(self, entorno):
        _, c, espejo = entorno
        from app.domain.models import InboundMessage
        from app.workers.agrupador import fundir

        def msg(texto, id_):
            return InboundMessage(
                channel=Channel.WHATSAPP,
                external_message_id=id_,
                conversation_id=CONV,
                sender_id="573001112233",
                text=texto,
                raw={"id": id_},
            )

        c.procesar_mensaje(
            fundir([msg("Son dos huellitas", "w1"), msg("una negra", "w2")])
        )
        entrantes = [
            m["texto"]
            for m in c.conversaciones.historial(CONV, 20)
            if m["direccion"] == "IN"
        ]
        assert entrantes == ["Son dos huellitas", "una negra"]
        copiados = [t for _, t, kw in espejo.copias if kw.get("entrante") is True]
        assert copiados == ["Son dos huellitas", "una negra"]
