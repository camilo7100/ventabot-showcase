"""Cuando le da miedo abonar (Camilo, 13/10).

Real, Nora: «Si pero no me gusta que tiene que dar vueltas lata adelantada». El
bot: «Te entiendo 😊 Para iniciar solo abonas $60.000…» y de una «¿Lo quieres de
1, 2 o 3 huellitas?». Camilo: «es lógico que a la gente le dé miedo abonar dinero
a personas que no conoce»; tranquilizarla desde el sentir, no desde los números:
que entienda que el abono es lo que permite hacer SU anillo y que el resto lo
paga cuando lo vea terminado; la página y el Instagram, que dan confianza.
"""

from __future__ import annotations

import pytest

from app.conversacion.asesora import HechosDelNegocio, teme_abonar
from app.domain.asesora import Borrador, inventa_datos_del_negocio
from app.domain.recordatorios import no_quiere
from tests.unit.test_talla_la_confirma_lia import (  # noqa: F401  (la fixture)
    CONV,
    _asesora,
    _guardar,
    _jugada,
    mundo,
)

NORA = "Si pero no me gusta que tiene que dar vueltas lata adelantada"


class TestTemeAbonar:
    @pytest.mark.parametrize(
        "texto",
        [
            NORA,
            "no me gusta dar la plata adelantada",
            "me da miedo consignar a alguien que no conozco",
            "cómo sé que no es una estafa?",
            "y si no me llega?",
            "uy pagar antes no sé",
            "es que no los conozco",
        ],
    )
    def test_si(self, texto):
        assert teme_abonar(texto), texto

    @pytest.mark.parametrize(
        "texto",
        ["ya te transferí", "¿cuánto es el abono?", "me encanta", "talla 7", "rosa"],
    )
    def test_no(self, texto):
        assert not teme_abonar(texto), texto


class TestLaPlataAdelantadaEsDinero:
    def test_no_es_desinteres(self):
        """«No me gusta la plata ADELANTADA» es miedo a abonar, no al metal."""
        assert not no_quiere("no me gusta la plata adelantada")
        assert not no_quiere(NORA)

    def test_el_metal_si(self):
        assert no_quiere("Es que no me gusta la plata")


class TestLoQueEsVerdad:
    @pytest.mark.parametrize(
        "frase",
        [
            "Estamos creando piezas especiales desde 2019: lunajoyas.example",
            "Nos encuentras en Instagram @lunajoyas ✨",
            "https://lunajoyas.example y https://instagram.com/lunajoyas",
        ],
    )
    def test_las_de_verdad_pasan(self, frase):
        assert not inventa_datos_del_negocio(frase), frase

    @pytest.mark.parametrize(
        "frase",
        [
            "Tenemos Instagram @lia_accesorios con cientos de clientes",
            "Llevamos más de 8 años haciendo anillos",
            "mira www.anillosbonitos.com",
            "lunajoyas.example y @otra_cuenta",
        ],
    )
    def test_lo_inventado_no(self, frase):
        assert inventa_datos_del_negocio(frase), frase

    def test_el_modelo_lo_sabe(self):
        texto = HechosDelNegocio(precios={1: 200_000}).para_el_prompt()
        assert "https://lunajoyas.example" in texto
        assert "@lunajoyas" in texto and "desde 2019" in texto


class TestExplicarElAbonoNoEsMentir:
    """El vigilante borraba «el abono es lo que nos permite empezarlo en el taller»
    (lo leía como «ya está en el taller»). Explicar sí; afirmar que YA está, no."""

    @pytest.mark.parametrize(
        "frase",
        [
            "Como tu anillo se hace solo para ti, el abono es lo que nos permite "
            "empezarlo en el taller.",
            "Con el abono pasa al taller y el resto lo pagas cuando lo veas terminado.",
            "Tu anillo entra al taller cuando haces el abono 💍",
        ],
    )
    def test_explica(self, frase):
        from app.domain.asesora import explica_el_abono

        assert explica_el_abono(frase), frase

    @pytest.mark.parametrize(
        "frase",
        [
            "Tu anillo ya está en el taller 💍",
            "Con el abono tu anillo ya entró al taller",
            "Estamos fabricando tu anillo",
        ],
    )
    def test_afirmar_que_ya_esta_no(self, frase):
        from app.domain.asesora import explica_el_abono

        assert not explica_el_abono(frase), frase

    def test_el_vigilante_la_deja(self):
        from app.domain.asesora import vigilar
        from tests.unit.test_asesora import PERMITIDOS

        frase = "El abono es lo que nos permite empezarlo en el taller 💍"
        limpio, _ = vigilar(frase, PERMITIDOS, Borrador())
        assert "taller" in limpio
        limpio, _ = vigilar("Tu anillo ya está en el taller 💍", PERMITIDOS, Borrador())
        assert "taller" not in limpio


class TestElResumenYaSalio:
    def test_no_promete_mandarlo(self):
        from app.conversacion.asesora import _PROMETE_EL_RESUMEN

        texto = (
            "¡Listo, Andrea! 🫶 En unos minutos te comparto el resumen de tu anillo "
            "para confirmar que todo esté bien."
        )
        # Se va solo la promesa; el «¡Listo, Andrea!» se queda.
        assert _PROMETE_EL_RESUMEN.sub("", texto).strip() == "¡Listo, Andrea!"
        assert (
            _PROMETE_EL_RESUMEN.sub("", "¡Gracias, Andrea! 🫶") == "¡Gracias, Andrea! 🫶"
        )


class TestElTurno:
    def test_sin_la_pregunta_de_relleno(self, mundo):  # noqa: F811
        """Se la tranquiliza; debajo no va «¿De cuántas huellitas lo quieres?»."""
        tranquila = (
            "Te entiendo muchísimo 🫶 es normal sentir eso cuando todavía no nos "
            "conoces.\nComo tu anillo se hace solo para ti, el abono es lo que nos "
            "permite empezarlo en el taller. El resto lo pagas solo cuando veas las "
            "fotos de tu anillo terminado y te encante 💍\nEstamos creando piezas "
            "especiales desde 2019: lunajoyas.example y en Instagram @lunajoyas ✨"
        )
        a = _asesora(mundo, _jugada(tranquila))
        _guardar(mundo, Borrador(turnos=2))
        texto = a.ejecutar(CONV, NORA).respuesta.texto_plano
        assert "huellitas lo quieres" not in texto, texto
        assert "lunajoyas.example" in texto and "@lunajoyas" in texto, texto
