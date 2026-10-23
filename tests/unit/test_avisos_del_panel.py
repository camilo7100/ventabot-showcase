"""Cuando Lía mueve el pedido, la clienta se entera sola.

Es la pieza que convierte el panel en una herramienta de venta y no en una
lista de tareas. Hoy ese aviso lo escribe Lía a mano, uno por uno, cuando se
acuerda; cada día de retraso ahí es un día de plata sin cobrar sobre un
anillo que ya se fabricó y ya se pagó en material.

Lo que se prueba:
  · que el texto diga el saldo correcto (es un cobro: si el número está mal,
    es una discusión con alguien que ya pagó un abono)
  · que el aviso vaya a la OUTBOX y no se mande en caliente
  · que tocar el botón dos veces no mande dos mensajes
  · que los estados que NO deben avisar, no avisen
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.domain.guion import AVISOS, aviso_de_cierre
from app.domain.models import Channel, Customer, Order, OrderItem
from app.domain.operacion import avisa_este_estado, mensaje_de_aviso
from app.domain.order_state import TRANSICIONES, OrderState

TOKEN = "token-de-prueba-1234"


def _pedido(estado: OrderState, **kw) -> Order:
    base = {
        "codigo": "PED-2026-0417",
        "customer_id": "c1",
        "estado": estado.value,
        "items": [
            OrderItem(
                sku="ANI-HUE-1",
                nombre="Anillo huellita x1",
                cantidad=1,
                precio_unitario_cop=200_000,
            )
        ],
        "total_cop": 200_000,
        "anticipo_cop": 60_000,
        "saldo_cop": 140_000,
        "anticipo_pagado_cop": 60_000,
    }
    return Order(**{**base, **kw})


def _completo(estado: OrderState, **kw) -> Order:
    from tests.unit.test_panel import _completo as completo

    return completo(estado, anticipo_pagado_cop=60_000, **kw)


CLIENTA = Customer(
    id="c1", channel=Channel.WHATSAPP, channel_user_id="573001112233", nombre="Ángela"
)


def _lo_que_recibe(pedido: Order) -> str:
    """Todo lo que le llega al decirle «tu anillo ya está listo».

    Desde el 20/09 ese aviso son DOS mensajes con las fotos en medio, porque
    así lo manda Lía: primero el saludo y la pedida de datos de envío, luego
    las imágenes del anillo, y al final el cobro. Probar solo el primero sería
    probar media verdad.
    """
    primero = mensaje_de_aviso(pedido, CLIENTA, OrderState.ESPERANDO_SALDO)
    cierre = aviso_de_cierre(
        recoge=bool(pedido.envio and pedido.envio.recoge),
        saldo_cop=max(0, pedido.saldo_cop - pedido.saldo_pagado_cop),
    )
    return f"{primero.text}\n{cierre}"


class TestElTextoDelAviso:
    def test_el_cobro_del_saldo_dice_el_monto_exacto(self):
        texto = _lo_que_recibe(_pedido(OrderState.PRODUCCION_LISTA))
        assert "$140.000" in texto
        assert "$200.000" not in texto, "le está cobrando el total otra vez"

    def test_el_saldo_sale_del_PEDIDO_y_no_de_un_calculo_nuevo(self):
        """Si el precio del catálogo cambia entre que ella confirmó y que se
        le cobra, se le cobra lo que ella aceptó, no lo nuevo."""
        texto = _lo_que_recibe(_pedido(OrderState.PRODUCCION_LISTA, saldo_cop=99_000))
        assert "$99.000" in texto

    def test_descuenta_lo_que_ya_abono_del_saldo(self):
        texto = _lo_que_recibe(
            _pedido(OrderState.PRODUCCION_LISTA, saldo_pagado_cop=40_000)
        )
        assert "$100.000" in texto

    def test_el_cobro_lleva_donde_consignar(self):
        texto = _lo_que_recibe(_pedido(OrderState.PRODUCCION_LISTA))
        for banco in ("Bancolombia", "Nequi", "Daviplata"):
            assert banco in texto

    def test_pide_los_datos_de_envio_AQUI_y_no_antes(self):
        """Regla de Camilo (20/09): la ciudad, la cédula, el celular y la
        dirección se piden con las fotos del anillo terminado, no al empezar.
        Es cuando ella los manda junto con la transferencia."""
        texto = _lo_que_recibe(_pedido(OrderState.PRODUCCION_LISTA))
        for dato in ("Ciudad", "Nombre completo", "Cédula", "Celular", "Dirección"):
            assert dato in texto, f"no le pide {dato}"

    def test_dice_cuanto_con_envio_y_cuanto_sin_envio(self):
        """Las dos cifras, como las manda Lía: para que ella escoja si paga el
        flete ahora o contraentrega."""
        from app.domain.faq import ENVIO_EN_EL_MENSAJE_COP

        texto = _lo_que_recibe(_pedido(OrderState.PRODUCCION_LISTA))
        con_envio = f"${140_000 + ENVIO_EN_EL_MENSAJE_COP:,.0f}".replace(",", ".")
        assert con_envio in texto, "falta el total con envío incluido"
        assert "$140.000" in texto, "falta el valor sin envío"
        assert "contraentrega" in texto.lower()

    def test_a_quien_lo_recoge_no_se_le_habla_de_envio(self):
        from app.domain.envio import DatosDeEnvio

        pedido = _pedido(
            OrderState.PRODUCCION_LISTA,
            envio=DatosDeEnvio(nombre="Ángela", recoge=True),
        )
        texto = _lo_que_recibe(pedido).lower()
        assert "guías de envío" not in texto
        assert "cédula" not in texto, "si lo recoge no hace falta la guía"
        assert "$140.000" in texto

    def test_el_despacho_lleva_el_codigo_del_pedido(self):
        m = mensaje_de_aviso(
            _pedido(OrderState.SALDO_PAGADO), CLIENTA, OrderState.DESPACHADO
        )
        assert "PED-2026-0417" in m.text

    def test_va_al_canal_y_numero_de_la_clienta(self):
        m = mensaje_de_aviso(
            _pedido(OrderState.PRODUCCION_LISTA), CLIENTA, OrderState.ESPERANDO_SALDO
        )
        assert m.channel is Channel.WHATSAPP
        assert m.to == "573001112233"
        assert m.conversation_id == "wa:573001112233"


class TestQueEstadosAvisan:
    def test_cancelar_NO_le_escribe_a_nadie(self):
        """Cancelar es una conversación, no una notificación automática."""
        assert not avisa_este_estado(OrderState.CANCELADO)
        assert (
            mensaje_de_aviso(_pedido(OrderState.COTIZADO), CLIENTA, OrderState.CANCELADO)
            is None
        )

    def test_reembolsar_tampoco(self):
        assert not avisa_este_estado(OrderState.REEMBOLSO)

    def test_produccion_lista_se_mueve_en_silencio(self):
        """Para nosotros «producción lista» y «esperando saldo» son dos
        estados; para la clienta es un solo momento. Avisar dos veces por lo
        mismo es ruido."""
        assert not avisa_este_estado(OrderState.PRODUCCION_LISTA)

    def test_los_tres_que_avisan_son_los_que_la_clienta_espera(self):
        avisan = {e for e in OrderState if avisa_este_estado(e)}
        assert avisan == {
            OrderState.EN_PRODUCCION,
            OrderState.ESPERANDO_SALDO,
            OrderState.DESPACHADO,
        }

    def test_todo_aviso_apunta_a_un_estado_real(self):
        """Un aviso con el nombre mal escrito no se manda nunca, en silencio."""
        validos = {e.value for e in OrderState}
        assert set(AVISOS) <= validos

    def test_ningun_aviso_promete_algo_que_no_se_cumple(self):
        """Se miran los textos YA REDACTADOS, no las plantillas.

        La primera versión de este test leía las plantillas crudas y fallaba
        porque el hueco `{envio_contraentrega}` contiene la palabra
        «contraentrega». Estaba comprobando el andamio en vez del mensaje."""
        redactados = (
            " ".join(
                mensaje_de_aviso(_pedido(OrderState.PRODUCCION_LISTA), CLIENTA, e).text
                for e in OrderState
                if avisa_este_estado(e)
            )
            + " "
            + aviso_de_cierre(recoge=False, saldo_cop=140_000)
            + " "
            + aviso_de_cierre(recoge=True, saldo_cop=140_000)
        ).lower()
        assert "manejamos contraentrega" not in redactados
        assert "envío gratis" not in redactados
        assert "{" not in redactados, "un hueco se quedó sin rellenar"


# ---------------------------------------------------------------------------
# De punta a punta, contra el panel de verdad
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

    from app.api.main import app

    c = contenedor.get_container()
    c.customers.upsert(CLIENTA)
    yield TestClient(app), c

    get_settings.cache_clear()
    contenedor._singleton = None


#: Un pedido listo SIEMPRE tiene fotos: sin ellas el sistema no deja decir
#: «tu anillo ya está listo», porque ese mensaje ES las fotos (Camilo, 20/09).
def _listo(**kw):
    return _pedido(OrderState.PRODUCCION_LISTA, fotos=["anillo-de-angela"], **kw)


class TestDePuntaAPunta:
    def test_lo_que_recibe_la_clienta_tambien_queda_en_chatwoot(
        self, entorno, monkeypatch
    ):
        """26/09: Lía verificó un abono desde el panel, a la clienta le llegó
        «ya entró al taller» y en Chatwoot solo había una nota privada. Chatwoot
        tiene que mostrar la conversación completa: es donde Lía atiende."""
        from app.adapters.crm.chatwoot import CrmDeMentira

        cliente, c = entorno
        espejo = CrmDeMentira()
        monkeypatch.setattr(c, "crm", espejo)
        pedido = c.orders.create(_listo(), idem_key="k")

        cliente.post(
            f"/panel/mover?token={TOKEN}",
            data={"pedido_id": pedido.id, "destino": "ESPERANDO_SALDO"},
        )

        enviados = [m.text for m in c.outbox.pending(10) if m.text]
        copiados = [t for _, t, kw in espejo.copias if kw.get("entrante") is False]
        assert enviados, "no salió nada hacia la clienta"
        assert copiados == enviados, "Chatwoot no muestra lo que le llegó a la clienta"
        assert any(t.startswith("[nota] 📦") for _, t, _ in espejo.copias), (
            "se perdió la nota para Lía"
        )

    def test_cobrar_el_saldo_encola_el_mensaje(self, entorno):
        cliente, c = entorno
        pedido = c.orders.create(_listo(), idem_key="k")

        cliente.post(
            f"/panel/mover?token={TOKEN}",
            data={"pedido_id": pedido.id, "destino": "ESPERANDO_SALDO"},
        )

        pendientes = c.outbox.pending(10)
        # Dos: el saludo con la pedida de datos, y el cobro. Las fotos irían
        # en medio, pero en las pruebas no hay URL pública desde donde servirlas.
        assert len(pendientes) == 2
        junto = " ".join(m.text for m in pendientes)
        assert "$140.000" in junto
        assert "Cédula" in junto, "no le pidió los datos de envío"
        assert all(m.to == "573001112233" for m in pendientes)

    def test_sin_fotos_NO_se_le_dice_que_esta_listo(self, entorno):
        """19/09: salió «Te comparto las fotos de cómo quedó» y no salió
        ninguna foto. Se le pedían $140.000 por algo que no había visto."""
        cliente, c = entorno
        pedido = c.orders.create(_pedido(OrderState.PRODUCCION_LISTA), idem_key="k")
        r = cliente.post(
            f"/panel/mover?token={TOKEN}",
            data={
                "pedido_id": pedido.id,
                "destino": "ESPERANDO_SALDO",
                "mensaje": "Ya quedó tu anillo 💍",
            },
        )
        # 28/09: salía «Internal Server Error». Ahora dice qué hacer, y el
        # mensaje que Lía escribió no se pierde.
        assert r.status_code == 409
        assert "Agregar fotos del anillo" in r.text
        assert "Ya quedó tu anillo 💍" in r.text and "no se mandó" in r.text
        assert not c.outbox.pending(10), "no se le mandó nada"
        assert c.orders.get(pedido.id).estado == OrderState.PRODUCCION_LISTA.value

    def test_va_a_la_outbox_y_NO_se_manda_en_caliente(self, entorno):
        """Si se mandara aquí, un fallo de red dejaría a la clienta sin
        enterarse de que su anillo está listo, y a nadie le constaría."""
        cliente, c = entorno
        pedido = c.orders.create(_listo(), idem_key="k")
        cliente.post(
            f"/panel/mover?token={TOKEN}",
            data={"pedido_id": pedido.id, "destino": "ESPERANDO_SALDO"},
        )
        # Sigue pendiente: nadie lo despachó todavía.
        assert c.outbox.pending(10)

    def test_tocar_el_boton_dos_veces_no_manda_dos_mensajes(self, entorno):
        """El dedo resbala, la página se recarga. La clave de idempotencia
        lleva el estado destino justo para esto."""
        cliente, c = entorno
        pedido = c.orders.create(_listo(), idem_key="k")
        for _ in range(3):
            cliente.post(
                f"/panel/mover?token={TOKEN}",
                data={"pedido_id": pedido.id, "destino": "ESPERANDO_SALDO"},
            )
        assert len(c.outbox.pending(10)) == 2

    def test_un_estado_que_no_avisa_no_encola_nada(self, entorno):
        cliente, c = entorno
        pedido = c.orders.create(_pedido(OrderState.COTIZADO), idem_key="k")
        cliente.post(
            f"/panel/mover?token={TOKEN}",
            data={"pedido_id": pedido.id, "destino": "CANCELADO"},
        )
        assert c.outbox.pending(10) == []

    def test_el_boton_que_escribe_sale_marcado(self, entorno):
        cliente, c = entorno
        c.orders.create(_pedido(OrderState.PRODUCCION_LISTA), idem_key="k")
        texto = cliente.get(f"/panel?token={TOKEN}").text
        assert "✉ Cobrar el saldo" in texto

    def test_avisa_cuando_whatsapp_no_deja_escribir(self, entorno):
        """La fabricación son 10-15 días, así que la ventana de 24 h está
        cerrada en casi todos los pedidos. Callarlo haría que Lía creyera
        que el mensaje salió."""
        cliente, c = entorno
        c.orders.create(_pedido(OrderState.PRODUCCION_LISTA), idem_key="k")
        texto = cliente.get(f"/panel?token={TOKEN}").text
        assert "WhatsApp no deja escribirle ahora" in texto

    def test_el_aviso_queda_en_la_auditoria_del_pedido(self, entorno):
        cliente, c = entorno
        pedido = c.orders.create(_completo(OrderState.ANTICIPO_PAGADO), idem_key="k")
        cliente.post(
            f"/panel/mover?token={TOKEN}",
            data={"pedido_id": pedido.id, "destino": "EN_PRODUCCION"},
        )
        eventos = c.orders.eventos(pedido.id)
        assert any(e.actor == "panel" for e in eventos)


class TestCoherenciaConLaMaquinaDeEstados:
    def test_todo_estado_que_avisa_es_alcanzable(self):
        """Un aviso para un estado al que no se puede llegar no se manda
        nunca, y nadie se entera de que sobra."""
        alcanzables = {d for destinos in TRANSICIONES.values() for d in destinos}
        for estado in OrderState:
            if avisa_este_estado(estado):
                assert estado in alcanzables, f"{estado.value} avisa pero es inalcanzable"


class TestElBotSeEntera:
    def test_el_aviso_del_panel_entra_en_la_memoria_del_bot(self, entorno):
        """19/09: tras «tu anillo ya está listo» el bot decía «está en el taller»,
        porque los avisos del panel no estaban en la charla que lee."""
        cliente, c = entorno
        pedido = c.orders.create(_completo(OrderState.ANTICIPO_PAGADO), idem_key="k")
        cliente.post(
            f"/panel/mover?token={TOKEN}",
            data={"pedido_id": pedido.id, "destino": "EN_PRODUCCION"},
        )
        charla = c.bot._mundo.contexto("wa:573001112233").charla
        assert any("[aviso automático]" in m["texto"] for m in charla)
