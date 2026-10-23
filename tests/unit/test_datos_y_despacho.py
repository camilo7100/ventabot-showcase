"""Envíos, guía, datos editables y la tabla de análisis (Camilo, 29/09).

3. Un solo flete ($17.500) para todas las ciudades, editable en el panel.
4. Los datos de envío que manda ella se leen aunque la IA no los anote (el
   28/09 la dirección se perdió); la guía es obligatoria para despachar y le
   llega en el mensaje; un saldo por verificar no sale en «Esperando abono».
5. Todo lo obligatorio se edita a mano, y queda igual en el pedido, el bot y
   Chatwoot (en los dos sentidos).
6. Una fila por pedido, con cada dato en su columna, para analizar.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.domain.asesora import Borrador
from app.domain.edicion import EdicionInvalida, aplicar_edicion, separar_grabado
from app.domain.envio import DatosDeEnvio, leer_datos_de_envio
from app.domain.models import Channel, Customer
from app.domain.operacion import bandejas, falta_para_despachar
from app.domain.order_state import OrderState

TOKEN = "token-de-prueba-1234"
CONV = "wa:573001112233"
CLIENTA = Customer(
    id="c1", channel=Channel.WHATSAPP, channel_user_id="573001112233", nombre="Ángela"
)
#: Textual, el del 28/09 (con otros números).
BLOQUE = (
    "Bogotá\nNatalia Bautista Dussán\n1016000000\n3100000000\n"
    "Cra 90A # 8A - 10 torre 3 apto 110 conjunto residencial Navarra Castilla "
    "reservado - Barrio nueva Castilla"
)


def _pedido(estado: OrderState, **kw):
    from tests.unit.test_panel import _completo

    kw.setdefault(
        "envio",
        DatosDeEnvio(
            nombre="Ángela Pérez",
            ciudad="Bogotá",
            direccion="Cl 45 #12-30",
            cedula="52000000",
            celular="3000000000",
        ),
    )
    return _completo(estado, anticipo_pagado_cop=60_000, **kw)


class TestLeerLosDatosDeEnvio:
    def test_el_bloque_del_28_de_septiembre(self):
        d = leer_datos_de_envio(BLOQUE, ["Bogotá"])
        assert d["ciudad"] == "Bogotá"
        assert d["destinatario"] == "Natalia Bautista Dussán"
        assert d["cedula"] == "1016000000" and d["celular"] == "3100000000"
        assert d["direccion"].startswith("Cra 90A # 8A - 10 torre 3 apto 110")
        assert d["barrio"] == "nueva Castilla"

    def test_con_etiquetas(self):
        d = leer_datos_de_envio(
            "📍 Ciudad: Medellín\n🙋‍♀️ Nombre completo: Ana Pérez\n🪪 Cédula: 43.123.456\n"
            "📱 Celular: 300 123 4567\n🏡 Dirección completa: Calle 10 # 20-30"
        )
        assert d == {
            "ciudad": "Medellín",
            "destinatario": "Ana Pérez",
            "cedula": "43123456",
            "celular": "3001234567",
            "direccion": "Calle 10 # 20-30",
        }

    @pytest.mark.parametrize(
        "charla", ["Bogotá", "sí gracias", "La verde por favor\nPepe"]
    )
    def test_la_charla_normal_no_es_un_bloque_de_datos(self, charla):
        assert leer_datos_de_envio(charla, ["Bogotá"]) == {}


class TestLaGuia:
    def test_sin_guia_no_se_despacha(self):
        p = _pedido(OrderState.SALDO_PAGADO)
        assert falta_para_despachar(p) == ["número de guía"]

    def test_con_guia_si(self):
        p = _pedido(OrderState.SALDO_PAGADO)
        p = p.model_copy(update={"envio": p.envio.model_copy(update={"guia": "700012"})})
        assert falta_para_despachar(p) == []

    def test_si_lo_recoge_no_hace_falta(self):
        p = _pedido(
            OrderState.SALDO_PAGADO, envio=DatosDeEnvio(nombre="Ana", recoge=True)
        )
        assert falta_para_despachar(p) == []

    def test_la_guia_le_llega_en_el_mensaje(self):
        from app.domain.operacion import mensaje_de_aviso

        p = _pedido(OrderState.SALDO_PAGADO)
        p = p.model_copy(
            update={
                "envio": p.envio.model_copy(
                    update={"guia": "700012345678", "transportadora": "Interrapidísimo"}
                )
            }
        )
        m = mensaje_de_aviso(p, CLIENTA, OrderState.DESPACHADO)
        assert "despachado por Interrapidísimo" in m.text
        assert "Número de guía: *700012345678*" in m.text


class TestLasBandejas:
    def test_un_saldo_por_verificar_no_sale_en_esperando_abono(self):
        """28/09: el saldo en revisión salía en «Esperando el abono»."""
        p = _pedido(OrderState.EN_REVISION_PAGO)
        por_clave = {b.clave: b.pedidos for b in bandejas([p])}
        assert p in por_clave["pagos_por_verificar"]
        assert p not in por_clave["esperando_abono"]

    def test_los_pagos_van_primero(self):
        assert bandejas([])[0].clave == "pagos_por_verificar"


class TestEditarAMano:
    def test_separar_el_grabado(self):
        assert separar_grabado("Luna ♡ Rocky") == ["Luna", "Rocky"]
        assert separar_grabado("Luna, Rocky") == ["Luna", "Rocky"]

    def test_un_campo_vacio_no_borra_nada(self):
        p = _pedido(OrderState.SALDO_PAGADO)
        nuevo, _, cambios = aplicar_edicion(
            p, Borrador(), {"direccion": "", "ciudad": ""}
        )
        assert not cambios and nuevo.envio.direccion == p.envio.direccion

    def test_la_direccion_y_la_guia(self):
        p = _pedido(OrderState.SALDO_PAGADO)
        nuevo, b, cambios = aplicar_edicion(
            p,
            Borrador(),
            {"direccion": "Cra 90A # 8A-10", "guia": "700012", "cedula": "1.016.000.000"},
        )
        assert nuevo.envio.direccion == "Cra 90A # 8A-10" == b.direccion
        assert nuevo.envio.guia == "700012"
        assert nuevo.envio.cedula == "1016000000"
        assert len(cambios) == 3

    def test_una_talla_que_no_existe(self):
        with pytest.raises(EdicionInvalida):
            aplicar_edicion(
                _pedido(OrderState.ANTICIPO_PAGADO), Borrador(), {"talla": "7.3"}
            )

    def test_los_colores(self):
        p = _pedido(OrderState.ANTICIPO_PAGADO)
        nuevo, _, cambios = aplicar_edicion(
            p, Borrador(cantidad=1), {"corazon_1": "ROJO", "dedos_1": "BLANCO"}
        )
        h = nuevo.items[0].personalizacion.huellitas[0]
        assert (h.corazon.value, h.dedos.value) == ("ROJO", "BLANCO")
        assert cambios[0].startswith("colores")


class TestLosFletes:
    @pytest.fixture
    def tabla(self, tmp_path):
        from app.adapters.repositories.fletes_sqlite import SqliteFletes
        from app.adapters.repositories.sqlite_store import SqliteDB
        from app.infra.settings import RAIZ

        return SqliteFletes(SqliteDB(tmp_path / "t.db"), RAIZ / "data" / "fletes.csv")

    def test_la_semilla_es_17500_para_todas(self, tabla):
        assert tabla.costo_por_defecto == 17_500
        assert {f.costo_cop for f in tabla.ciudades()} == {17_500}
        assert tabla.buscar("MEDELLÍN").ciudad == "Medellín"

    def test_una_ciudad_que_no_esta_paga_la_general(self, tabla):
        assert tabla.buscar("Pueblo Nuevo").costo_cop == 17_500

    def test_cambiar_todas_y_una(self, tabla):
        tabla.tarifa_unica(19_000)
        assert tabla.costo_por_defecto == 19_000 == tabla.buscar("Cali").costo_cop
        tabla.fijar("Leticia", 35_000)
        assert tabla.buscar("leticia").costo_cop == 35_000
        assert tabla.buscar("Cali").costo_cop == 19_000

    def test_un_precio_absurdo_no_se_guarda(self, tabla):
        with pytest.raises(ValueError):
            tabla.fijar("Cali", 9_000_000)


# ---------------------------------------------------------------------------
# De punta a punta: panel, Chatwoot y análisis
# ---------------------------------------------------------------------------


@pytest.fixture
def entorno(monkeypatch, tmp_path):
    import app.infra.container as contenedor
    from app.adapters.crm.chatwoot import CrmDeMentira
    from app.infra.settings import get_settings

    monkeypatch.setenv("PANEL_TOKEN", TOKEN)
    monkeypatch.setenv("REPOSITORY_BACKEND", "sqlite")
    monkeypatch.setenv("CHANNEL_BACKEND", "console")
    monkeypatch.setenv("LLM_BACKEND", "fake")
    monkeypatch.setenv("SQLITE_PATH", str(tmp_path / "t.db"))
    get_settings.cache_clear()
    contenedor._singleton = None

    from app.api.main import app

    c = contenedor.get_container()
    c.customers.upsert(CLIENTA)
    espejo = CrmDeMentira()
    monkeypatch.setattr(c, "crm", espejo)
    yield TestClient(app), c, espejo

    get_settings.cache_clear()
    contenedor._singleton = None


class TestEnElPanel:
    def test_la_guia_se_escribe_junto_al_boton_y_le_llega(self, entorno):
        cliente, c, _ = entorno
        pedido = c.orders.create(_pedido(OrderState.SALDO_PAGADO), idem_key="k")
        pagina = cliente.get(f"/panel?token={TOKEN}").text
        assert "name=guia" in pagina and "🚚 Para despacharlo" in pagina
        sin = cliente.post(
            f"/panel/mover?token={TOKEN}",
            data={"pedido_id": pedido.id, "destino": "DESPACHADO"},
        )
        assert sin.status_code == 409 and "número de guía" in sin.text
        con = cliente.post(
            f"/panel/mover?token={TOKEN}",
            data={"pedido_id": pedido.id, "destino": "DESPACHADO", "guia": "700099"},
            follow_redirects=False,
        )
        assert con.status_code == 303
        assert c.orders.get(pedido.id).estado == "DESPACHADO"
        assert any(
            "Número de guía: *700099*" in (m.text or "") for m in c.outbox.pending(20)
        )

    def test_editar_los_datos_queda_en_todos_lados(self, entorno):
        cliente, c, espejo = entorno
        pedido = c.orders.create(_pedido(OrderState.SALDO_PAGADO), idem_key="k")
        r = cliente.post(
            f"/panel/datos?token={TOKEN}",
            data={
                "pedido_id": pedido.id,
                "direccion": "Cra 90A # 8A-10 torre 3",
                "barrio": "Nueva Castilla",
                "recoge_presente": "1",
            },
            follow_redirects=False,
        )
        assert r.status_code == 303
        envio = c.orders.get(pedido.id).envio
        assert (
            envio.direccion == "Cra 90A # 8A-10 torre 3"
            and envio.barrio == "Nueva Castilla"
        )
        assert any("✏️ Datos editados desde el panel" in t for _, t, _ in espejo.copias)

    def test_un_dato_invalido_se_explica(self, entorno):
        cliente, c, _ = entorno
        pedido = c.orders.create(_pedido(OrderState.ANTICIPO_PAGADO), idem_key="k")
        r = cliente.post(
            f"/panel/datos?token={TOKEN}", data={"pedido_id": pedido.id, "cedula": "12"}
        )
        assert r.status_code == 400 and "Eso no se pudo guardar" in r.text

    def test_la_pagina_de_envios(self, entorno):
        cliente, _, _ = entorno
        pagina = cliente.get(f"/panel/envios?token={TOKEN}").text
        assert "Envío nacional: $17.500" in pagina and "Medellín" in pagina
        cliente.post(
            f"/panel/envios?token={TOKEN}", data={"accion": "todas", "costo": "18.000"}
        )
        assert (
            "Envío nacional: $18.000" in cliente.get(f"/panel/envios?token={TOKEN}").text
        )

    def test_el_excel_de_datos(self, entorno):
        cliente, c, _ = entorno
        c.orders.create(_pedido(OrderState.SALDO_PAGADO), idem_key="k")
        r = cliente.get(f"/panel/datos.csv?token={TOKEN}")
        assert r.status_code == 200 and "attachment" in r.headers["content-disposition"]
        encabezado, fila = r.text.lstrip("﻿").splitlines()[:2]
        assert encabezado.startswith("codigo;pedido_id;estado")
        assert fila.startswith("PED-2026-0417;")
        assert ";Bogotá;" in fila


class TestDesdeChatwoot:
    def test_lo_que_lia_escribe_en_la_ficha_llega_al_pedido(self, entorno):
        _, c, _ = entorno
        pedido = c.orders.create(_pedido(OrderState.SALDO_PAGADO), idem_key="k")
        ctx = c.bot._mundo.contexto(CONV)
        b = Borrador(pedido_id=pedido.id, pedido_codigo=pedido.codigo)
        c.bot._mundo.guardar_contexto(
            ctx.model_copy(update={"borrador": b.model_dump(mode="json")})
        )
        hechos = c.desde_chatwoot(CONV, {"guia": "700777", "ciudad": "Bogotá"})
        assert hechos == ["número de guía: 700777"], "la ciudad no cambió: no se toca"
        assert c.orders.get(pedido.id).envio.guia == "700777"

    def test_el_eco_de_nuestra_ficha_no_cambia_nada(self, entorno):
        _, c, _ = entorno
        pedido = c.orders.create(_pedido(OrderState.SALDO_PAGADO), idem_key="k")
        ctx = c.bot._mundo.contexto(CONV)
        b = Borrador(pedido_id=pedido.id, pedido_codigo=pedido.codigo)
        c.bot._mundo.guardar_contexto(
            ctx.model_copy(update={"borrador": b.model_dump(mode="json")})
        )
        ficha = c._ficha(b, c.orders.get(pedido.id))
        assert c.desde_chatwoot(CONV, ficha) == []


class TestLosModelos:
    """29/09: Sonnet 5.5 RECHAZA `thinking: disabled` con un 400 (comprobado con
    una llamada de verdad). Cambiar solo el nombre del modelo habría roto la
    capa potente sin avisar."""

    @pytest.mark.parametrize(
        ("modelo", "tipo"),
        [
            ("claude-sonnet-5-5", "between_tools"),
            ("claude-opus-5-5", "adaptive"),
            ("claude-sonnet-5", "disabled"),
            ("claude-opus-5", "disabled"),
            # 12/10: Haiku 5.5 rechaza `between_tools` y acepta `disabled`.
            ("claude-haiku-5-5", "disabled"),
        ],
    )
    def test_como_se_apaga_el_pensar(self, modelo, tipo):
        from app.adapters.llm.anthropic_client import _sin_pensar

        assert _sin_pensar(modelo) == {"type": tipo}

    @pytest.mark.parametrize(
        ("modelo", "le_manda"), [("claude-haiku-5-5", True), ("claude-haiku-4-5", False)]
    )
    def test_a_haiku_5_5_se_le_apaga_el_pensar(self, modelo, le_manda):
        """Haiku 5.5 a veces piensa (12/10: con una foto, 2,0 s contra 1,3 s);
        Haiku 4.5 RECHAZA la opción. A cada uno, lo suyo."""
        from app.adapters.llm.anthropic_client import ClaudeLLM
        from app.domain.asesora import Jugada

        llamadas: list[dict] = []

        class _Mensajes:
            def parse(self, **kw):
                llamadas.append(kw)
                raise RuntimeError("no hace falta contestar")

        class _Cliente:
            messages = _Mensajes()

            def with_options(self, **kw):
                return self

        claude = ClaudeLLM(modelo, "sk-ant-de-prueba")
        claude._get_client = lambda: _Cliente()
        with pytest.raises(RuntimeError):
            claude.extract("sistema", "hola", Jugada)
        assert ("thinking" in llamadas[0]) is le_manda

    def test_los_precios_de_los_modelos_nuevos(self):
        from app.domain.consumo import precio_de

        assert precio_de("claude-sonnet-5-5") == (2.00, 10.00)
        assert precio_de("claude-opus-5-5") == (4.00, 20.00)
        assert precio_de("claude-haiku-4-5") == (1.00, 5.00)
        # 12/10: Haiku 5.5, el respaldo de Claude, 10 veces más barato que 4.5.
        assert precio_de("claude-haiku-5-5") == (0.10, 0.50)
        # GPT-6 (29/09): luna es la principal; sin precio, el costo saldría en 0.
        assert precio_de("gpt-6-luna") == (0.10, 0.50)
        assert precio_de("gpt-6.1-sol") == (2.00, 10.00)
