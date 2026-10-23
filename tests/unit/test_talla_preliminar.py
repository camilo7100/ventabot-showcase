"""La talla de una medida es una REFERENCIA; la de Lía es la que vale (27/09).

El 26/09 una clienta escribió «1.8» y el bot le contestó «¡Es una talla 8!».
18 mm cae entre 7½ y 8. Lo que se pide:
  · la estimación es preliminar y así se le dice;
  · nunca se detiene la conversación esperando a Lía (llega al abono igual);
  · se conservan las tallas intermedias (7¼, 7½, 7¾) y la duda cuando la hay;
  · Lía confirma o corrige desde el panel, y desde ahí esa es la talla.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.domain.asesora import Borrador, CambiosDelBorrador, aplicar
from app.domain.models import Channel, Customer
from app.domain.order_state import OrderState
from app.domain.tallas import (
    CONTORNO_CM,
    DIAMETRO_MM,
    estimar,
    leer_talla,
    referencia_para_la_clienta,
    talla_texto,
)

TOKEN = "token-de-prueba-1234"
CLIENTA = Customer(
    id="c1", channel=Channel.WHATSAPP, channel_user_id="573001112233", nombre="Ángela"
)


class TestLaTablaDeLia:
    @pytest.mark.parametrize(
        ("talla", "mm"),
        [(5, 15.6), (6, 16.4), (7, 17.3), (8, 18.2), (9, 19.0), (10, 19.8), (11, 20.5)],
    )
    def test_los_diametros_son_los_suyos(self, talla, mm):
        assert DIAMETRO_MM[float(talla)] == mm

    def test_hay_cuartos_de_talla(self):
        for t in (7.25, 7.5, 7.75):
            assert t in DIAMETRO_MM
        assert DIAMETRO_MM[7.25] < DIAMETRO_MM[7.5] < DIAMETRO_MM[7.75] < DIAMETRO_MM[8.0]

    def test_el_contorno_del_dedo_es_el_suyo(self):
        assert CONTORNO_CM[7.0][:2] == (5.4, 5.8)
        assert CONTORNO_CM[8.0][:2] == (5.7, 5.9)
        assert CONTORNO_CM[11.0][:2] == (7.2, 7.4)

    @pytest.mark.parametrize(
        ("talla", "texto"), [(7.0, "7"), (7.25, "7¼"), (7.5, "7½"), (7.75, "7¾")]
    )
    def test_se_escribe_como_la_escribe_lia(self, talla, texto):
        assert talla_texto(talla) == texto
        assert leer_talla(texto) == talla


class TestUnaMedidaEscrita:
    def test_1_8_no_es_talla_8(self):
        """El caso del 26/09."""
        e = estimar(1.8)
        assert e.talla == 7.75
        assert e.posibles == (7.5, 7.75, 8.0)
        assert e.rango == "entre 7½ y 8"

    def test_lo_que_se_le_dice_es_una_referencia(self):
        texto = estimar(1.8).para_la_clienta()
        assert "más o menos talla 7¾" in texto and "(entre 7½ y 8)" in texto
        assert "referencia" in texto
        assert "¡Es una talla" not in texto

    def test_en_milimetros_tambien(self):
        """El 26/09 el modelo leyó «19» en la foto y se rechazó por «19 cm»."""
        assert estimar(19).talla == 9.0
        assert estimar(19).como == "diámetro 19 mm"

    def test_el_contorno_del_dedo_deja_la_duda(self):
        """5.7 cm cabe en la 7 y en la 8: se guardan las dos posibles."""
        e = estimar(5.7)
        assert e.posibles == (7.0, 8.0) and e.talla == 7.0
        assert e.como.startswith("contorno del dedo")

    def test_un_hueco_de_la_tabla_da_las_dos_vecinas(self):
        assert estimar(6.55).posibles == (9.0, 10.0)

    @pytest.mark.parametrize("raro", [3.5, 30, 0.5, 90])
    def test_lo_que_no_se_entiende_no_se_inventa(self, raro):
        assert estimar(raro) is None


class TestNuncaDetieneLaConversacion:
    def test_la_medida_deja_talla_para_seguir_y_marcada_para_lia(self):
        b, rechazos = aplicar(Borrador(cantidad=1), CambiosDelBorrador(medida_cm=1.8))
        assert not rechazos
        assert b.talla == 7.75, "sin talla, el pedido no llegaría al abono"
        assert b.talla_revisar and not b.talla_confirmada
        assert b.talla_rango == "entre 7½ y 8"
        assert "ESTIMADA (preliminar)" in b.talla_motivo

    def test_la_talla_no_le_falta_para_el_abono(self):
        b, _ = aplicar(Borrador(cantidad=1), CambiosDelBorrador(medida_cm=1.8))
        assert "talla" not in " ".join(b.falta_para_abono()).lower()

    def test_la_talla_que_dice_ella_no_es_preliminar(self):
        b, _ = aplicar(Borrador(cantidad=1), CambiosDelBorrador(talla=7.5))
        assert b.talla == 7.5 and not b.talla_revisar and not b.talla_rango

    def test_un_cuarto_de_talla_se_acepta(self):
        b, rechazos = aplicar(Borrador(cantidad=1), CambiosDelBorrador(talla=7.25))
        assert b.talla == 7.25 and not rechazos

    def test_una_medida_nueva_no_pisa_la_talla_de_lia(self):
        confirmada = Borrador(cantidad=1, talla=8.0, talla_confirmada=True)
        b, rechazos = aplicar(confirmada, CambiosDelBorrador(medida_cm=1.7))
        assert b.talla == 8.0
        assert any("ya está fija" in r for r in rechazos)
        assert any("revisar" in n for n in b.notas)

    def test_el_resumen_la_escribe_con_fraccion(self):
        b, _ = aplicar(Borrador(cantidad=1), CambiosDelBorrador(medida_cm=1.8))
        assert "Talla: 7¾" in b.resumen()

    def test_la_frase_de_referencia(self):
        assert referencia_para_la_clienta(7.75, "entre 7½ y 8").startswith(
            "Con esa medida te da más o menos talla 7¾ (entre 7½ y 8)"
        )


# ---------------------------------------------------------------------------
# Lía confirma o corrige desde el panel
# ---------------------------------------------------------------------------


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


def _pedido_con_talla_estimada(c):
    from tests.unit.test_panel import _completo

    pedido = _completo(OrderState.ANTICIPO_PAGADO, anticipo_pagado_cop=60_000)
    item = pedido.items[0]
    p = item.personalizacion.model_copy(
        update={"talla": 7.75, "talla_revisar": True, "talla_motivo": "estimada de 1.8"}
    )
    pedido = pedido.model_copy(
        update={"items": [item.model_copy(update={"personalizacion": p})]}
    )
    creado = c.orders.create(pedido, idem_key="k")
    b = Borrador(cantidad=1, talla=7.75, talla_revisar=True, talla_rango="entre 7½ y 8")
    ctx = c.bot._mundo.contexto("wa:573001112233")
    c.bot._mundo.guardar_contexto(
        ctx.model_copy(update={"borrador": b.model_dump(mode="json")})
    )
    return creado


class TestPaoLaConfirma:
    def test_el_panel_muestra_la_talla_por_confirmar(self, entorno):
        cliente, c, _ = entorno
        _pedido_con_talla_estimada(c)
        pagina = cliente.get(f"/panel?token={TOKEN}").text
        assert "📏 Talla 7¾ · por confirmar" in pagina
        assert "<option value='7.75' selected>7¾</option>" in pagina

    def test_corregirla_la_deja_firme_en_el_pedido_y_en_la_conversacion(self, entorno):
        cliente, c, espejo = entorno
        pedido = _pedido_con_talla_estimada(c)
        r = cliente.post(
            f"/panel/talla?token={TOKEN}",
            data={
                "pedido_id": pedido.id,
                "talla": "8",
                "nota": "Es la que mejor corresponde con la foto enviada.",
            },
            follow_redirects=False,
        )
        assert r.status_code == 303
        p = c.orders.get(pedido.id).items[0].personalizacion
        assert p.talla == 8.0 and not p.talla_revisar
        assert p.talla_motivo.startswith("Corregida por Lía (antes 7¾)")
        b = Borrador.model_validate(c.bot._mundo.contexto("wa:573001112233").borrador)
        assert b.talla == 8.0 and b.talla_confirmada and not b.talla_revisar
        notas = [t for _, t, _ in espejo.copias if t.startswith("[nota] 🗒️ NOTA INTERNA")]
        assert notas and "talla" in notas[0] and "mejor corresponde" in notas[0]

    def test_confirmarla_sin_mensaje_no_le_escribe_a_nadie(self, entorno):
        cliente, c, _ = entorno
        pedido = _pedido_con_talla_estimada(c)
        cliente.post(
            f"/panel/talla?token={TOKEN}", data={"pedido_id": pedido.id, "talla": "7.75"}
        )
        assert c.orders.get(pedido.id).items[0].personalizacion.talla_motivo == (
            "Confirmada por Lía"
        )
        assert not [m for m in c.outbox.pending(10) if m.text]

    def test_con_mensaje_le_llega_a_ella(self, entorno):
        cliente, c, espejo = entorno
        pedido = _pedido_con_talla_estimada(c)
        cliente.post(
            f"/panel/talla?token={TOKEN}",
            data={"pedido_id": pedido.id, "talla": "8", "mensaje": "Te queda talla 8 💍"},
        )
        assert [m.text for m in c.outbox.pending(10)] == ["Te queda talla 8 💍"]
        salientes = [t for _, t, kw in espejo.copias if kw.get("entrante") is False]
        assert "Te queda talla 8 💍" in salientes

    def test_una_talla_que_no_existe_se_rechaza(self, entorno):
        cliente, c, _ = entorno
        pedido = _pedido_con_talla_estimada(c)
        r = cliente.post(
            f"/panel/talla?token={TOKEN}", data={"pedido_id": pedido.id, "talla": "7.3"}
        )
        assert r.status_code == 400
