"""Si no le interesa, por pequeño que sea el desinterés, no se le recuerda nada
(Camilo, 10/10).

Real: «Es que no me gusta la plata». Al día siguiente, un recordatorio. «No no los
voy a pedir porque te dije que no me gusta la plata»: le llegó la información de
la CADENA («te dije» se leyó como «un dije») y, al otro día, OTRO recordatorio.
«Que no estoy interesada… Miles de veces».
"""

from __future__ import annotations

import pytest

from app.conversacion.asesora import SI_ALGUN_DIA
from app.domain import recordatorios as r
from app.domain.asesora import AccionAsesora, Borrador, pregunta_por_cadenas
from tests.unit.test_recordatorios import (  # noqa: F401  (la fixture)
    A_LAS_8,
    AHORA,
    _charla,
    _guia,
    entorno,
)
from tests.unit.test_recordatorios import CONV as CONV_REC
from tests.unit.test_talla_la_confirma_lia import (  # noqa: F401  (la fixture)
    CONV,
    _asesora,
    _guardar,
    _jugada,
    mundo,
)


class TestQueNoLeInteresa:
    @pytest.mark.parametrize(
        "texto",
        [
            "Es que no me gusta la plata",
            "No no los voy a pedir porque te dije que no me gusta la plata",
            "Menos pagaría 200 por un anillo en platav",
            "Que no estoy interesada",
            "Miles de veces",
            "no gracias",
            "está muy caro",
            "uy no, demasiado caro",
            "solo estaba mirando",
            "era solo para saber",
            "ya te dije que no",
            "dejen de escribir",
            "no me interesa",
            "no quiero, gracias",
            "ya no lo quiero",
            "no tengo presupuesto",
            "el otro mes",
        ],
    )
    def test_detecta_el_desinteres(self, texto):
        assert r.no_quiere(texto), texto

    @pytest.mark.parametrize(
        "texto",
        [
            "no quiero grabado",
            "no quiero ese color",
            "no sé mi talla",
            "no tengo anillos",
            "no tengo como medir",
            "no voy a poder medir hoy",
            "rosa",
            "talla 7",
            "¿cuánto cuesta?",
        ],
    )
    def test_lo_que_no_es_desinteres(self, texto):
        assert not r.no_quiere(texto), texto

    @pytest.mark.parametrize(
        "texto",
        [
            "Tienes razón, disculpa por insistir. Gracias por decírmelo 💓",
            "Entiendo, no estás interesada. Gracias por aclarármelo 🫶",
            "No te escribiré más sobre el pedido 🫶",
        ],
    )
    def test_la_ia_lo_entendio_asi(self, texto):
        assert r.el_bot_entendio_que_no(texto)


class TestTeDijeNoEsUnDije:
    def test_te_dije_no_es_la_cadena(self):
        assert not pregunta_por_cadenas(
            "No no los voy a pedir porque te dije que no me gusta la plata"
        )

    @pytest.mark.parametrize("texto", ["¿tienen dijes?", "quiero un dije de huellita"])
    def test_el_dije_si(self, texto):
        assert pregunta_por_cadenas(texto)


class TestSinRecordatorios:
    def test_ni_uno(self):
        assert r.etapa(Borrador(turnos=4, cantidad=1, sin_recordatorios=True)) is None

    def test_el_saludo_es_sencillo(self):
        assert r.saludo("Ana", 9) == "¡Buen día, Ana! 🌷 ¿Cómo estás?"
        assert r.saludo("", 17) == "¡Buenas tardes! 🌷 ¿Cómo estás?"


class TestElTurno:
    def test_no_me_gusta_la_plata_cierra_sin_ofrecer_nada(self, mundo):  # noqa: F811
        a = _asesora(
            mundo,
            _jugada(
                "Tienes razón, disculpa por insistir 💓 ¿Te muestro la cadena?",
                AccionAsesora.MOSTRAR_CADENA,
            ),
        )
        _guardar(mundo, Borrador(turnos=4))
        turno = a.ejecutar(
            CONV, "No no los voy a pedir porque te dije que no me gusta la plata"
        )
        texto = turno.respuesta.texto_plano
        assert "cadenita" not in texto and "?" not in texto, texto
        assert not turno.respuesta.imagenes()
        b = Borrador.model_validate(mundo.contexto(CONV).borrador)
        assert b.sin_recordatorios and r.etapa(b) is None

    def test_si_retoma_el_pedido_vuelven(self, mundo):  # noqa: F811
        a = _asesora(mundo, _jugada("¡Qué bien! 🐾", cantidad_huellitas=1))
        _guardar(mundo, Borrador(turnos=4, sin_recordatorios=True))
        a.ejecutar(CONV, "bueno, lo quiero de una huellita")
        b = Borrador.model_validate(mundo.contexto(CONV).borrador)
        assert not b.sin_recordatorios

    def test_el_cierre_es_amable(self):
        assert "?" not in SI_ALGUN_DIA and "aquí estoy" in SI_ALGUN_DIA


class TestElJuez:
    """Antes de cada recordatorio la IA lee la charla (10/10): no depende de cómo
    lo escribió ella."""

    def test_si_el_juez_dice_que_no_no_sale(self, entorno):  # noqa: F811
        c, db = entorno
        _charla(c, db, ella=A_LAS_8, borrador=_guia())
        c.recordador._juez = lambda charla: (False, "dijo que no le gusta la plata")
        assert c.recordador.una_vuelta(AHORA) == 0
        assert not c.outbox.pending(10)
        b = Borrador.model_validate(c.bot._mundo.contexto(CONV_REC).borrador)
        assert b.sin_recordatorios

    def test_si_dice_que_si_sale(self, entorno):  # noqa: F811
        c, db = entorno
        _charla(c, db, ella=A_LAS_8, borrador=_guia())
        c.recordador._juez = lambda charla: (True, "iba a medir")
        assert c.recordador.una_vuelta(AHORA) == 1

    def test_si_la_ia_falla_mandan_las_palabras(self, entorno):  # noqa: F811
        c, db = entorno
        _charla(c, db, ella=A_LAS_8, borrador=_guia())
        c.recordador._juez = lambda charla: None
        assert c.recordador.una_vuelta(AHORA) == 1

    def test_el_juez_con_un_llm(self):
        from app.workers.recordatorios import Veredicto, juez_con

        class _Llm:
            def extract(self, system, texto, schema, **kw):
                assert "no me gusta la plata" in texto
                return Veredicto(escribirle=False, motivo="no le gusta la plata")

        juzgar = juez_con(_Llm())
        charla = [{"de": "clienta", "texto": "Es que no me gusta la plata"}]
        assert juzgar(charla) == (False, "no le gusta la plata")

    def test_el_juez_caido_no_decide(self):
        from app.workers.recordatorios import juez_con

        class _Caido:
            def extract(self, *a, **kw):
                raise RuntimeError("sin red")

        assert juez_con(_Caido())([{"de": "clienta", "texto": "hola"}]) is None
