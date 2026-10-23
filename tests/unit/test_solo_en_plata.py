"""Solo en plata: la regla del metal (Camilo, 05/10).

Real: «Solo en plata? No hay dorado?». La regla: no se hacen baños de oro ni de
otros colores porque con el tiempo se pelan; para que la joya dure toda la vida
se trabaja solo en plata. Lo dice el sistema, siempre igual. Y «el corazón
dorado» es otra cosa: es el circón amarillo.
"""

from __future__ import annotations

import pytest

from app.conversacion.asesora import (
    PREGUNTA_DE_LA_TALLA,
    pregunta_abierta,
    solo_pregunta_por_el_metal,
)
from app.domain.asesora import Borrador
from app.domain.faq import RESPUESTAS, SOLO_EN_PLATA, Pregunta, pregunta_por_otro_metal
from tests.unit.test_talla_la_confirma_lia import (  # noqa: F401  (la fixture)
    CONV,
    _asesora,
    _guardar,
    _jugada,
    mundo,
)


class TestLaPregunta:
    @pytest.mark.parametrize(
        "texto",
        [
            "Solo en plata? No hay dorado?",  # real, 05/10
            "lo hay en color dorado?",  # reales de antes (golden)
            "lo tienen en oro",
            "manejan enchapado dorado?",
            "¿le hacen baño de oro?",
            "¿lo tienen en rose gold?",
            "¿la cadena es dorada?",
            "¿hay en otro material?",
        ],
    )
    def test_la_reconoce(self, texto):
        assert pregunta_por_otro_metal(texto)

    @pytest.mark.parametrize(
        "texto",
        [
            "el corazón dorado y los deditos blancos",  # una piedra
            "deditos en dorado porfa",
            "ya pagué por Bancolombia",  # «ban…» no es «baño»
            "quiero 2 huellitas",
            "plata ley 925, qué bien",
        ],
    )
    def test_lo_que_no_es(self, texto):
        assert not pregunta_por_otro_metal(texto)

    def test_es_la_misma_respuesta_de_la_pregunta_frecuente(self):
        assert RESPUESTAS[Pregunta.COLOR_DORADO] == SOLO_EN_PLATA
        assert "se pelan" in SOLO_EN_PLATA and "toda la vida" in SOLO_EN_PLATA

    def test_sola_o_con_otra_cosa(self):
        assert solo_pregunta_por_el_metal("Solo en plata? No hay dorado?")
        assert not solo_pregunta_por_el_metal("¿lo hay en oro? ¿y cuánto demora?")

    def test_la_pregunta_abierta(self):
        assert pregunta_abierta(f"Hola\n{PREGUNTA_DE_LA_TALLA}") == PREGUNTA_DE_LA_TALLA
        assert pregunta_abierta("Listo, anotado 🫶") == ""


class TestElTurno:
    def test_sola_es_fija_y_vuelve_a_la_pregunta(self, mundo):  # noqa: F811
        a = _asesora(mundo)  # sin jugadas: si llamara a la IA, fallaría
        ctx = mundo.contexto(CONV)
        mundo.guardar_contexto(
            ctx.model_copy(
                update={"charla": [{"de": "lia", "texto": PREGUNTA_DE_LA_TALLA}]}
            )
        )
        _guardar(mundo, Borrador(talla_exige_lia=True, turnos=1))
        t = a.ejecutar(CONV, "Solo en plata? No hay dorado?")
        texto = t.respuesta.texto_plano
        assert SOLO_EN_PLATA in texto
        assert "Y cuéntame, ¿sabes tu talla de anillo o te comparto la guía?" in texto
        assert PREGUNTA_DE_LA_TALLA not in texto, "la repetía igualita"
        assert t.capa == "fija"

    def test_con_otra_pregunta_el_modelo_contesta_lo_demas(self, mundo):  # noqa: F811
        a = _asesora(
            mundo,
            _jugada(
                "Siii, lo hacemos en plata Ley 925 😊 Se demora de 10 a 15 días. "
                "¿Sabes tu talla?"
            ),
        )
        _guardar(mundo, Borrador(talla_exige_lia=True, turnos=2))
        texto = a.ejecutar(
            CONV, "lo tienen en oro? y cuánto demora?"
        ).respuesta.texto_plano
        assert texto.count(SOLO_EN_PLATA) == 1
        assert "lo hacemos en plata" not in texto, "lo diría dos veces"
        assert "10 a 15 días" in texto and "¿Sabes tu talla?" in texto

    def test_el_corazon_dorado_es_una_piedra(self, mundo):  # noqa: F811
        a = _asesora(mundo, _jugada("¡Corazón amarillo! 💛 ¿Y los deditos?"))
        _guardar(mundo, Borrador(talla_exige_lia=True, turnos=3, cantidad=1))
        texto = a.ejecutar(CONV, "el corazón dorado").respuesta.texto_plano
        assert SOLO_EN_PLATA not in texto
