"""Lo que pidió Camilo el 13/10 con el diseño de marketing, aparte de los
recordatorios: separar sin talla, la venta a Meta y la apertura del peludito."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from app.domain.asesora import (
    Borrador,
    HuellitaDelBorrador,
    acepta_separar,
    al_dia_lo_que_se_pide,
    quiere_separar,
)
from app.domain.personalizacion import ColorCircon as C
from tests.unit.test_talla_la_confirma_lia import (  # noqa: F401  (la fixture)
    CONV,
    _asesora,
    _guardar,
    _jugada,
    mundo,
)


def _sin_talla(**kw) -> Borrador:
    """Todo el diseño listo; solo falta la talla."""
    base = dict(
        turnos=6,
        cantidad=1,
        huellitas=[HuellitaDelBorrador(corazon=C.LILA, dedos=C.LILA)],
        grabado=["Coco"],
        nombre_clienta="Ana Gómez",
    )
    return Borrador(**{**base, **kw})


# ══════════════════════════════════════════════════════════════════════════
#  SEPARAR SIN TALLA («la talla no debe frenar»)
# ══════════════════════════════════════════════════════════════════════════


class TestQuiereSeparar:
    @pytest.mark.parametrize(
        "texto",
        ["💍 Quiero separarlo", "lo separo de una", "resérvamelo porfa", "apártamelo"],
    )
    def test_si(self, texto):
        assert quiere_separar(texto), texto

    @pytest.mark.parametrize("texto", ["no lo quiero separar todavía", "rosado", "hola"])
    def test_no(self, texto):
        assert not quiere_separar(texto), texto

    def test_un_si_a_la_oferta(self):
        oferta = "Si quieres, ya lo puedes separar con el abono de $60.000 y la talla…"
        assert acepta_separar("Sí, dale", oferta)
        assert not acepta_separar("Sí, dale", "¿De qué color quieres la huellita?")


class TestElAbonoNoEsperaLaTalla:
    def test_sin_marcar_la_talla_falta(self):
        assert _sin_talla().falta_para_abono() == ["talla"]

    def test_al_separar_ya_no(self):
        b = _sin_talla()
        al_dia_lo_que_se_pide(b, "💍 Quiero separarlo", "")
        assert b.talla_despues and b.falta_para_abono() == []
        assert "Talla: me la mandas después 📏" in b.resumen()

    def test_la_cadena_no_lleva_talla(self):
        b = Borrador(turnos=3, pieza="cadena")
        al_dia_lo_que_se_pide(b, "quiero separarlo", "")
        assert not b.talla_despues

    def test_si_ya_tiene_talla_no_se_marca(self):
        b = _sin_talla(talla=7.0)
        al_dia_lo_que_se_pide(b, "lo separo", "")
        assert not b.talla_despues


class TestLaOferta:
    def test_solo_falta_la_talla_y_no_la_tiene_a_mano(self):
        from app.conversacion.asesora import ofrecer_separar

        b = _sin_talla(lo_manda_despues={"talla": 4})
        oferta = ofrecer_separar(b, "$60.000")
        assert "separar con el abono de $60.000" in oferta and oferta.count("?") == 1

    def test_no_si_falta_otra_cosa_o_ya_se_ofrecio(self):
        from app.conversacion.asesora import OFRECE_SEPARAR, ofrecer_separar

        assert not ofrecer_separar(_sin_talla(grabado=[]), "$60.000")
        b = _sin_talla(lo_manda_despues={"talla": 4}, mostrado_en={OFRECE_SEPARAR: 5})
        assert not ofrecer_separar(b, "$60.000")
        assert not ofrecer_separar(_sin_talla(), "$60.000")  # no dijo que no la tiene

    def test_en_el_turno(self, mundo):  # noqa: F811
        a = _asesora(
            mundo, _jugada("¡Listo, Ana! 🫶 Apenas tengas la talla, seguimos 😊")
        )
        _guardar(mundo, _sin_talla(lo_manda_despues={"talla": 4}))
        texto = a.ejecutar(CONV, "Ana Gómez").respuesta.texto_plano
        assert "separar con el abono" in texto, texto

    def test_la_pregunta_de_la_ia_sobre_la_talla_se_va(self, mundo):  # noqa: F811
        """Charla de prueba: «¡Gracias, Carolina! 🫶 ¿La tienes o prefieres que te
        comparta la guía?» a quien va a la joyería. Va el ofrecimiento."""
        a = _asesora(
            mundo,
            _jugada(
                "¡Gracias, Carolina! 🫶 ¿La tienes o prefieres que te comparta la guía?"
            ),
        )
        _guardar(mundo, _sin_talla(lo_manda_despues={"talla": 4}))
        texto = a.ejecutar(CONV, "Carolina Díaz").respuesta.texto_plano
        assert "guía" not in texto and "separar con el abono" in texto, texto
        assert texto.count("?") == 1, texto

    def test_sin_promesas_del_resumen(self, mundo):  # noqa: F811
        a = _asesora(
            mundo,
            _jugada(
                "¡Listo, Carolina Díaz! 🫶 Apenas Lía confirme la talla, te compartimos "
                "el resumen del pedido."
            ),
        )
        _guardar(mundo, _sin_talla(lo_manda_despues={"talla": 4}))
        texto = a.ejecutar(CONV, "Carolina Díaz").respuesta.texto_plano
        assert "resumen" not in texto and texto.startswith("¡Listo, Carolina Díaz!"), (
            texto
        )

    def test_el_boton_lleva_al_resumen(self, mundo):  # noqa: F811
        """Todo listo menos la talla y toca «💍 Quiero separarlo»: el resumen."""
        a = _asesora(mundo, _jugada("¡Qué alegría! 🥰"))
        _guardar(mundo, _sin_talla())
        r = a.ejecutar(CONV, "💍 Quiero separarlo").respuesta
        assert "Talla: me la mandas después" in r.texto_plano, (r.texto_plano, r.traza)


# ══════════════════════════════════════════════════════════════════════════
#  LA VENTA A META
# ══════════════════════════════════════════════════════════════════════════


class TestLaVentaAMeta:
    def test_el_evento_como_lo_mando_marketing(self):
        from app.adapters.conversiones_meta import evento_de_compra

        e = evento_de_compra(
            codigo="PED-2026-0001",
            valor_cop=200_000,
            ctwa_clid="AfiJclid",
            waba_id="123",
            cuando=datetime(2026, 10, 13, 15, tzinfo=UTC),
        )["data"][0]
        assert e["event_name"] == "Purchase" and e["event_id"] == "PED-2026-0001"
        assert e["action_source"] == "business_messaging"
        assert e["messaging_channel"] == "whatsapp"
        assert e["user_data"] == {
            "whatsapp_business_account_id": "123",
            "ctwa_clid": "AfiJclid",
        }
        assert e["custom_data"] == {
            "currency": "COP",
            "value": 200_000,
            "order_id": "PED-2026-0001",
        }

    def test_sin_clic_de_anuncio_no_se_manda(self):
        from app.adapters.conversiones_meta import ConversionesDeMeta

        assert not ConversionesDeMeta("d", "t", "w").compra(
            codigo="X", valor_cop=1, ctwa_clid="", cuando=datetime.now(UTC)
        )

    def test_al_confirmar_el_abono(self, tmp_path):
        """El contenedor busca el `ctwa_clid` del primer mensaje y la manda."""
        from app.infra.container import build_container
        from app.infra.settings import Settings

        c = build_container(
            Settings(
                sqlite_path=tmp_path / "m.db",
                repository_backend="sqlite",
                llm_backend="fake",
                payment_backend="fake",
                channel_backend="console",
                ventas_excel=tmp_path / "v.xlsx",
                ventas_cada_s=0,
            )
        )
        mandadas = []

        class Falsa:
            def compra(self, **kw):
                mandadas.append(kw)
                return True

        c.conversiones = Falsa()
        conv = "wa:573001112244"
        crudo = {
            "type": "text",
            "referral": {"ctwa_clid": "AfiJclid", "source_type": "ad"},
        }
        c.conversaciones.registrar_entrante(
            conv, "whatsapp", "573001112244", "m1", "hola", crudo
        )

        class Pedido:
            codigo = "PED-2026-0002"
            total_cop = 250_000

        assert c.avisar_venta_a_meta(Pedido(), conv)
        assert (
            mandadas[0]["ctwa_clid"] == "AfiJclid" and mandadas[0]["valor_cop"] == 250_000
        )
        # Un número de prueba, nunca.
        assert not c.avisar_venta_a_meta(Pedido(), "wa:570000000011")
        # Sin clic de anuncio, tampoco.
        otro = "wa:573001112255"
        c.conversaciones.registrar_entrante(
            otro, "whatsapp", "573001112255", "m2", "hola", {}
        )
        assert not c.avisar_venta_a_meta(Pedido(), otro)
        assert json.dumps(mandadas[0], default=str)  # solo datos simples


# ══════════════════════════════════════════════════════════════════════════
#  LA APERTURA DEL PELUDITO (prueba)
# ══════════════════════════════════════════════════════════════════════════


def _con_peludito(mundo, *jugadas):  # noqa: F811
    """La asesora con la prueba encendida y la conversación EN BLANCO."""
    a = _asesora(mundo, *jugadas)
    a._apertura_peludito = True
    ctx = mundo.contexto(CONV)
    mundo.guardar_contexto(ctx.model_copy(update={"charla": []}))
    return a


class TestLaAperturaDelPeludito:
    def test_quiere_mas_informacion(self, mundo):  # noqa: F811
        from app.conversacion.asesora import APERTURA_PELUDITO, FOTO_DEL_PELUDITO

        a = _con_peludito(mundo)
        t = a.ejecutar(CONV, "¡Hola! Quiero más información")
        medios = [p.imagen for p in t.respuesta.piezas if p.imagen]
        assert medios == [FOTO_DEL_PELUDITO], medios
        assert "¿Cómo se llama tu peludito?" in t.respuesta.texto_plano
        assert "$200.000" not in t.respuesta.texto_plano
        b = Borrador.model_validate(t.contexto.borrador)
        assert (
            APERTURA_PELUDITO in b.mostrado_en and "MOSTRAR_PRECIOS" not in b.mostrado_en
        )

    def test_si_pregunta_el_precio_la_de_siempre(self, mundo):  # noqa: F811
        a = _con_peludito(mundo)
        t = a.ejecutar(CONV, "¿Qué precio tiene el anillo? 💍🐾")
        medios = [p.imagen for p in t.respuesta.piezas if p.imagen]
        assert "presentacion_anillo" in medios

    def test_en_su_segundo_mensaje_va_la_presentacion(self, mundo):  # noqa: F811
        a = _con_peludito(
            mundo, _jugada("¡Qué lindo nombre! 🐾 Se lo grabamos por dentro")
        )
        a.ejecutar(CONV, "¡Hola! Quiero más información")
        t = a.ejecutar(CONV, "Se llama Luna")
        medios = [p.imagen for p in t.respuesta.piezas if p.imagen]
        assert "presentacion_anillo" in medios and "presentacion_video_1" in medios
        assert "¿Sabes tu talla" in t.respuesta.texto_plano


class TestSuNombreDeWhatsApp:
    """Los recordatorios la saludan por su nombre: se guarda el de su perfil."""

    def test_se_guarda_la_primera_vez_y_no_se_pisa(self, tmp_path):
        from app.domain.models import Channel, InboundMessage
        from app.infra.container import build_container
        from app.infra.settings import Settings

        c = build_container(
            Settings(
                sqlite_path=tmp_path / "n.db",
                repository_backend="sqlite",
                llm_backend="fake",
                payment_backend="fake",
                channel_backend="console",
                ventas_excel=tmp_path / "v.xlsx",
                ventas_cada_s=0,
            )
        )

        def llega(nombre: str, n: int) -> None:
            c.procesar_mensaje(
                InboundMessage(
                    channel=Channel.WHATSAPP,
                    external_message_id=f"w{n}",
                    conversation_id="wa:573001112266",
                    sender_id="573001112266",
                    sender_name=nombre,
                    text="hola",
                )
            )

        llega("Laura Gómez", 1)
        llega("Otro Nombre", 2)
        cliente = c.customers.get_by_channel_user("whatsapp", "573001112266")
        assert cliente.nombre == "Laura Gómez"
