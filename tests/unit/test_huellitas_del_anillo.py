"""Cómo se ve el anillo: la forma no se escoge, los colores sí.

De la tanda de Camilo del 20/09, con las fotos del anillo de verdad delante:

  · «puede pedir cada dedo con un color diferente, hay que interpretar eso»
  · «en los anillos de 2 o 3 la idea es que en la misma imagen salgan las 2 o
     3 huellas; solo en la que es individual debe salir 1»
  · «una huella es mirando para arriba, que es corazón abajo y dedos arriba;
     2 huellitas es la de la izquierda mirando para arriba y la de la derecha
     mirando abajo; y la de 3, las de los extremos mirando para arriba y la
     del centro mirando para abajo»
  · «no existen variaciones en las direcciones de las huellitas»
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.adapters.render.huellita import VUELTAS, RenderDeHuellitas
from app.conversacion.asesora import _a_huellita, _el_anillo_entero
from app.domain.asesora import Borrador, HuellitaDelBorrador
from app.domain.personalizacion import ColorCircon as C
from app.domain.personalizacion import Huellita

RAIZ = Path(__file__).resolve().parents[2]
BASE = RAIZ / "data" / "imagenes" / "fuentes" / "huellita_base.jpg"
MASCARAS = RAIZ / "data" / "imagenes" / "fuentes" / "huellita_mascaras.png"


class TestCadaDeditoDeSuColor:
    """Antes, «negro-blanco-negro-blanco» se guardaba como `dedos_alternos[0]`
    y los otros tres colores se iban a una nota suelta: el dibujo enseñaba los
    cuatro deditos iguales y al taller le llegaba un anillo unicolor.
    """

    def test_los_cuatro_colores_llegan_al_pedido(self):
        b = Borrador(
            cantidad=1,
            huellitas=[
                HuellitaDelBorrador(
                    corazon=C.ROJO,
                    dedos_alternos=[C.NEGRO, C.BLANCO, C.NEGRO, C.BLANCO],
                )
            ],
        )
        p, _ = b.a_personalizacion()
        assert p.huellitas[0].dedos_alternos == [C.NEGRO, C.BLANCO, C.NEGRO, C.BLANCO]

    def test_sin_alternos_los_cuatro_son_el_mismo(self):
        h = Huellita(corazon=C.ROJO, dedos=C.BLANCO)
        assert h.colores_de_los_dedos == [C.BLANCO] * 4

    def test_o_son_los_cuatro_o_ninguno(self):
        """Tres colores para cuatro deditos es un pedido imposible."""
        with pytest.raises(ValueError):
            Huellita(corazon=C.ROJO, dedos=C.BLANCO, dedos_alternos=[C.NEGRO, C.BLANCO])

    def test_se_los_describe_uno_por_uno(self):
        h = Huellita(
            corazon=C.ROJO, dedos=C.NEGRO, dedos_alternos=[C.NEGRO, C.BLANCO] * 2
        )
        assert h.describir() == "corazón rojo / dedos negro-blanco-negro-blanco"

    def test_dos_combinaciones_distintas_no_comparten_dibujo(self):
        """El nombre del archivo sale de los colores: si los alternos no
        entraran en la firma, la segunda clienta recibiría el dibujo de la
        primera."""
        iguales = [Huellita(corazon=C.ROJO, dedos=C.NEGRO)]
        alternos = [
            Huellita(
                corazon=C.ROJO, dedos=C.NEGRO, dedos_alternos=[C.NEGRO, C.BLANCO] * 2
            )
        ]
        assert RenderDeHuellitas.nombre_de(iguales) != RenderDeHuellitas.nombre_de(
            alternos
        )


class TestLaFormaDelAnillo:
    """La segunda huellita va siempre volteada: en el de dos, una mira arriba
    y la otra abajo; en el de tres, la del centro es la del revés."""

    def test_solo_la_segunda_va_al_reves(self):
        assert list(VUELTAS) == [1]

    @pytest.mark.skipif(not BASE.is_file(), reason="sin la foto base")
    def test_el_de_una_no_se_voltea(self, tmp_path):
        import numpy as np

        r = RenderDeHuellitas(BASE, MASCARAS, tmp_path)
        una = r.dibujar([Huellita(corazon=C.ROJO, dedos=C.BLANCO)])
        sola = r._una(Huellita(corazon=C.ROJO, dedos=C.BLANCO), {}, {})
        from app.adapters.render.huellita import _recortar

        assert np.array_equal(np.asarray(una), np.asarray(_recortar(sola)))

    @pytest.mark.skipif(not BASE.is_file(), reason="sin la foto base")
    def test_en_el_de_tres_la_del_centro_mira_al_otro_lado(self, tmp_path):
        """El corazón es la piedra grande. En las de los extremos queda abajo;
        en la del centro, arriba."""
        import numpy as np

        r = RenderDeHuellitas(BASE, MASCARAS, tmp_path)
        tres = [Huellita(corazon=C.NEGRO, dedos=C.BLANCO)] * 3
        imagen = np.asarray(r.dibujar(tres).convert("L")).astype(float)
        ancho = imagen.shape[1] // 3
        for i, corazon_abajo in enumerate((True, False, True)):
            trozo = imagen[:, i * ancho : (i + 1) * ancho]
            oscuro = trozo < 90  # el corazón negro es lo más oscuro del trozo
            ys = np.where(oscuro.any(axis=1))[0]
            centro = ys.mean() / imagen.shape[0]
            if corazon_abajo:
                assert centro > 0.5, f"la huellita {i + 1} no mira hacia arriba"
            else:
                assert centro < 0.5, "la del centro tiene que mirar hacia abajo"


class TestSeEnseñaElAnilloEntero:
    """Quien compra el de tres tiene que ver tres, aunque esté comparando el
    color de una sola."""

    def _rosada(self):
        return Huellita(corazon=C.ROSADO, dedos=C.ROSADO)

    def test_una_opcion_suelta_se_completa_hasta_la_cantidad(self):
        b = Borrador(cantidad=3)
        assert len(_el_anillo_entero([self._rosada()], b)) == 3

    def test_el_de_una_sigue_siendo_una(self):
        b = Borrador(cantidad=1)
        assert len(_el_anillo_entero([self._rosada()], b)) == 1

    def test_se_completa_con_lo_que_ella_ya_escogio(self):
        b = Borrador(
            cantidad=2,
            huellitas=[
                HuellitaDelBorrador(corazon=C.NEGRO, dedos=C.BLANCO),
                HuellitaDelBorrador(corazon=C.ROJO, dedos=C.AMARILLO),
            ],
        )
        anillo = _el_anillo_entero([self._rosada()], b)
        assert [h.corazon for h in anillo] == [C.ROSADO, C.ROJO], (
            "la segunda patita ya estaba escogida: no se repite la que mira"
        )

    def test_nunca_se_enseñan_mas_de_las_que_compra(self):
        b = Borrador(cantidad=1)
        muchas = [self._rosada(), self._rosada(), self._rosada()]
        assert len(_el_anillo_entero(muchas, b)) == 1

    def test_los_alternos_sobreviven_al_dibujo(self):
        h = HuellitaDelBorrador(
            corazon=C.ROJO, dedos_alternos=[C.NEGRO, C.BLANCO, C.NEGRO, C.BLANCO]
        )
        assert _a_huellita(h).dedos_alternos == [C.NEGRO, C.BLANCO, C.NEGRO, C.BLANCO]


class TestElResumenComoLoEscribeLia:
    """Camilo lo escribió tal cual lo quiere (20/09):

        •Anillo 1 huellita•

        Talla: 7
        Color: 🖤 Negro / Dedos: Negro-Blanco-Negro-Blanco
        Grabado: Akira ♡ 08/02/2021

    Faltaban dos cosas: el renglón en blanco debajo del título y el punto de
    color delante del corazón. El emoji no es adorno: el resumen se lee de un
    vistazo en WhatsApp, y con el color se ve la joya en vez de una factura.
    """

    def _borrador(self):
        return Borrador(
            cantidad=1,
            talla=7,
            huellitas=[
                HuellitaDelBorrador(
                    corazon=C.NEGRO,
                    dedos_alternos=[C.NEGRO, C.BLANCO, C.NEGRO, C.BLANCO],
                )
            ],
            grabado=["Akira ♡ 08/02/2021"],
        )

    def test_sale_igual_que_el_que_escribio_camilo(self):
        assert self._borrador().resumen() == (
            "•Anillo 1 huellita•\n"
            "\n"
            "Talla: 7\n"
            "Color: 🖤 Negro / Dedos: Negro-Blanco-Negro-Blanco\n"
            "Grabado: Akira ♡ 08/02/2021"
        )

    def test_el_nombre_va_debajo_en_la_entrega(self):
        """La talla y el nombre van ANTES del abono: los dos tienen que
        verse en lo que ella confirma."""
        b = self._borrador()
        b.nombre_clienta = "Camilo"
        assert b.resumen().endswith("•Entrega•\nA nombre de: Camilo")

    def test_cada_color_tiene_el_suyo(self):
        from app.domain.personalizacion import EMOJI_COLOR

        assert set(EMOJI_COLOR) == set(C), "algún circón se quedó sin su punto"

    def test_una_huellita_de_un_solo_color_tambien_lo_lleva(self):
        b = Borrador(
            cantidad=1,
            talla=7,
            huellitas=[HuellitaDelBorrador(corazon=C.ROJO, dedos=C.ROJO)],
        )
        assert "Color: ❤️ Rojo (toda la huellita)" in b.resumen()
