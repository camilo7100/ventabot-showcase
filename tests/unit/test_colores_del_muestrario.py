"""Los colores son los de las bolsitas del muestrario, y la clienta lo sabe
(30/09/2026).

La IA le confirmaba «verde menta» a quien pedía verde menta y ella nunca se
enteraba de qué piedra le iban a poner. Ahora: los tintes salen medidos de la
foto, el pie de cada vista dice el nombre de la bolsita, y el bot no puede
nombrar como piedra un color que no existe.
"""

from __future__ import annotations

import pytest

from app.adapters.render.huellita import RenderDeHuellitas
from app.domain.asesora import vigilar
from app.domain.personalizacion import (
    HEX_COLOR,
    NOMBRE_COLOR,
    Acabado,
    Huellita,
    nombres_de_los_colores,
)
from app.domain.personalizacion import ColorCircon as C


class TestLaTabla:
    def test_son_los_catorce_de_la_foto(self):
        assert {c.value for c in C} == {
            "BLANCO", "NEGRO", "LILA", "MORADO", "CELESTE", "AZUL_REY", "ROSADO",
            "FUCSIA", "ROJO", "NARANJA", "DURAZNO", "AMARILLO", "VERDE_OLIVA",
            "VERDE_ESMERALDA",
        }  # fmt: skip

    def test_cada_color_tiene_nombre_y_tinte(self):
        for c in C:
            assert NOMBRE_COLOR[c] and HEX_COLOR[c].startswith("#")

    def test_el_script_que_los_mide_cubre_las_catorce_bolsitas(self):
        from scripts.medir_muestrario import CAJAS

        assert {c for c, *_ in CAJAS} == set(C)


class TestElPieDiceElNombre:
    def test_una_huellita(self):
        pie = nombres_de_los_colores([Huellita(corazon=C.VERDE_OLIVA, dedos=C.BLANCO)])
        assert pie == "Corazón 🫒 verde oliva · deditos 🤍 blanco"

    def test_de_un_solo_color(self):
        pie = nombres_de_los_colores([Huellita(corazon=C.ROSADO, dedos=C.ROSADO)])
        assert pie == "Toda en 🩷 rosa"

    def test_varias_y_deditos_alternos(self):
        pie = nombres_de_los_colores(
            [
                Huellita(corazon=C.MORADO, dedos=C.LILA),
                Huellita(
                    corazon=C.ROJO, dedos=C.NEGRO, dedos_alternos=[C.NEGRO, C.BLANCO] * 2
                ),
            ]
        )
        assert pie.splitlines()[0] == "Huellita 1: Corazón 💜 morado · deditos 🪻 lila"
        assert "🖤 negro · 🤍 blanco · 🖤 negro · 🤍 blanco" in pie.splitlines()[1]


class TestElBotNoConfirmaColoresQueNoExisten:
    @pytest.mark.parametrize(
        "frase",
        [
            "¡El verde menta te va a quedar divino!",
            "Perfecto, corazón menta y deditos blancos.",
            "Te lo hago en dorado.",
        ],
    )
    def test_la_frase_se_quita(self, frase):
        limpio, problemas = vigilar(frase + " ¿Y qué grabado quieres?", set())
        assert frase not in limpio and "¿Y qué grabado quieres?" in limpio
        assert any("muestrario" in p for p in problemas)

    @pytest.mark.parametrize(
        "frase",
        [
            "No tenemos verde menta, el más parecido es el verde oliva 💚",
            "Ese turquesa en el muestrario se llama celeste 🩵",
            "Quedaría en verde esmeralda con deditos blancos 😍",
        ],
    )
    def test_la_guia_y_los_nombres_buenos_pasan(self, frase):
        limpio, problemas = vigilar(frase, set())
        assert limpio == frase and not problemas


class TestLasVistasSeRedibujanConLosColoresNuevos:
    def test_cambiar_un_tinte_cambia_el_nombre_del_archivo(self, monkeypatch):
        """Las vistas se guardan y se reusan: con el mismo nombre, el servidor
        seguía mandando las dibujadas con el tinte viejo."""
        h = [Huellita(corazon=C.MORADO, dedos=C.MORADO)]
        antes = RenderDeHuellitas.nombre_de(h)
        monkeypatch.setitem(HEX_COLOR, C.MORADO, "#000001")
        assert RenderDeHuellitas.nombre_de(h) != antes


class TestLoQueSeVeEsLoQueSeEscogio:
    """30/09, Camilo: «al dar Ver sí cambia, pero no al color que coloco». El
    cuerpo de la piedra dibujada da, en promedio, el color del panel; las
    facetas cambian la textura, no el color, y los reflejos solo le
    SUMAN luz blanca encima (como en una piedra de verdad)."""

    @staticmethod
    def _diferencia(tinte: str, acabado: Acabado):
        """Promedio de la piedra menos el color del panel, en 0–255 por canal."""
        from pathlib import Path

        import numpy as np

        img = Path(__file__).resolve().parents[2] / "data" / "imagenes" / "fuentes"
        r = RenderDeHuellitas(
            img / "huellita_base.jpg", img / "huellita_mascaras.png", Path("/tmp")
        )
        _, mascaras = r._cargar()
        dibujo = r._una(
            Huellita(corazon=C.LILA, dedos=C.LILA), {C.LILA: tinte}, {C.LILA: acabado}
        )
        promedio = (np.asarray(dibujo).astype(np.float32) / 255)[mascaras == 1].mean(0)
        objetivo = np.array([int(tinte[i : i + 2], 16) for i in (1, 3, 5)]) / 255
        return (promedio - objetivo) * 255

    @pytest.mark.parametrize(
        "tinte",
        [*(HEX_COLOR[c] for c in C), "#F8C8DC", "#5A0F2E", "#808080", "#1060FF"],
    )
    def test_el_promedio_de_la_piedra_es_el_color_del_panel(self, tinte):
        # Un canal casi a 255 (rosa muy claro, azul eléctrico) no se alcanza
        # del todo sin aplanar las facetas: se prefiere la piedra bonita.
        casi_tope = max(int(tinte[i : i + 2], 16) for i in (1, 3, 5)) >= 0xF0
        sin_luz = Acabado(facetas=50, destellos=0)
        assert abs(self._diferencia(tinte, sin_luz)).max() < (8 if casi_tope else 2)

    @pytest.mark.parametrize("facetas", [0, 25, 75, 100])
    def test_las_facetas_no_cambian_el_color(self, facetas):
        sin_luz = Acabado(facetas=facetas, destellos=0)
        assert abs(self._diferencia("#947FBE", sin_luz)).max() < 2

    @pytest.mark.parametrize(
        "acabado", [Acabado(50, 10), Acabado(50, 60), Acabado(50, 100)]
    )
    def test_los_reflejos_solo_suman_luz(self, acabado):
        diferencia = self._diferencia("#5B47AB", acabado)
        assert diferencia.min() > -2, "no oscurecen ni cambian el tono"
        assert diferencia.max() > 1, "se nota que brilla más"

    def test_el_acabado_si_cambia_la_imagen(self):
        h = [Huellita(corazon=C.LILA, dedos=C.LILA)]
        assert RenderDeHuellitas.nombre_de(h) != RenderDeHuellitas.nombre_de(
            h, acabados={C.LILA: Acabado(facetas=90)}
        )

    @pytest.mark.parametrize(
        "malo", [{"facetas": 101}, {"destellos": -1}, {"fuego": 101}]
    )
    def test_un_acabado_fuera_de_rango(self, malo):
        with pytest.raises(ValueError):
            Acabado(**malo)
