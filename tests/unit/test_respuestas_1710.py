"""Las respuestas flojas de la noche del 16/10 (Camilo: «necesito más inteligencia»).

- «¿No se puede contra entrega?», justo después de «¿Sabes tu talla o te
  comparto la guía?», se leía como «no sé (mi talla)» y le llegaba la guía.
- «¿Qué cobijas tienes?» se pasaba a Lía, pero igual le llegaba toda la
  presentación del anillo.
"""

from __future__ import annotations

import pytest

from app.conversacion.asesora import PREGUNTA_DE_LA_TALLA, pide_la_guia_de_la_talla

ULTIMO = "Cuando esté listo te enviamos fotos… " + PREGUNTA_DE_LA_TALLA


class TestLaGuiaDeLaTalla:
    @pytest.mark.parametrize(
        "texto",
        [
            "No se puede contra entrega?",
            "No se puede pagar al recibir?",
            "no se hacen envíos a Pasto?",
            "No se manejan cuotas?",
        ],
    )
    def test_una_pregunta_de_otra_cosa_no_pide_la_guia(self, texto):
        assert not pide_la_guia_de_la_talla(texto, ULTIMO)

    @pytest.mark.parametrize(
        "texto",
        [
            "No sé",
            "no se",
            "No sé mi talla",
            "ni idea",
            "la guía porfa",
            "me la compartes?",
        ],
    )
    def test_el_no_se_de_verdad_sigue_pidiendo_la_guia(self, texto):
        assert pide_la_guia_de_la_talla(texto, ULTIMO)


class TestProbandoComoClientas:
    """Lo que salió al conversar con el bot como clientas distintas (17/10)."""

    @pytest.mark.parametrize(
        "texto",
        [
            "como es lo de 3 huellitas o una no entendi",
            "cual es la diferencia entre 1 y 2 huellitas?",
            "no entendí lo de las huellitas",
            "¿qué significa lo de 2 huellitas?",
            "cuanto vale el de 1?",
        ],
    )
    def test_preguntar_por_las_cantidades_no_es_escoger(self, texto):
        from app.domain.asesora import cantidad_respaldada, pregunta_por_las_cantidades

        assert pregunta_por_las_cantidades(texto)
        assert not cantidad_respaldada(3, texto, "¿Sabes tu talla?")

    @pytest.mark.parametrize(
        "texto", ["quiero el de 3 huellitas", "de una", "son dos huellitas"]
    )
    def test_escoger_una_cantidad_sigue_valiendo(self, texto):
        from app.domain.asesora import pregunta_por_las_cantidades

        assert not pregunta_por_las_cantidades(texto)

    def test_el_que_mas_venden_no_es_pedir_otros_productos(self):
        from app.domain.asesora import pregunta_por_cadenas

        assert not pregunta_por_cadenas("cual es el que mas venden?")
        assert not pregunta_por_cadenas("¿cuál es la que más piden?")
        assert pregunta_por_cadenas("¿qué más venden?")
        assert pregunta_por_cadenas("hola, ¿tienen cadenas?")

    def test_si_cuenta_algo_suyo_no_hay_apertura_fija(self):
        from app.conversacion.asesora import es_un_arranque_de_cajon

        assert es_un_arranque_de_cajon("¡Hola! Quiero más información")
        assert es_un_arranque_de_cajon("Hello! Can I get more info on this?")
        assert not es_un_arranque_de_cajon("es para mi, soy hombre, uso talla 11")


def test_las_fechas_del_grabado_no_borran_la_respuesta():
    """«12/03/2015 - 05/08/2024» parecía un número de cuenta y se borraba todo."""
    from app.domain.asesora import vigilar

    texto, problemas = vigilar(
        "Qué bonito recordarla así 🤍 Le grabamos «Luna (alitas) 12/03/2015 - "
        "05/08/2024» por dentro.",
        set(),
    )
    assert "Luna" in texto and not problemas
    _, malos = vigilar("Transfiere a la cuenta 9124 7189 837.", set())
    assert malos, "un número de cuenta de verdad sí se quita"


def test_el_prompt_explica_las_huellitas_y_la_contraentrega():
    """Lo que marketing pidió (17/10) está en las instrucciones del modelo."""
    from pathlib import Path

    prompt = (
        Path(__file__).resolve().parents[2] / "app" / "prompts" / "asesora_v1.txt"
    ).read_text(encoding="utf-8")
    assert "es el DISEÑO del anillo" in prompt
    assert "EL ANILLO NO, EL ENVÍO SÍ" in prompt
    assert "OTROS PRODUCTOS" in prompt
