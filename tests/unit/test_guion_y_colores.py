"""El guion de la conversación y la lectura de colores, blindados.

Estos tests protegen dos cosas distintas:

  · GUION: que el orden de las preguntas sea el que el negocio decidió, y que
    ningún dato necesario para fabricar se quede sin pedir. Un hueco aquí es
    un anillo que llega al taller sin saber de qué color va.

  · COLORES: que leer «corazón lila y dedos morados» dé LILA y MORADO, hoy y
    dentro de un año. Es el mensaje más frecuente de toda la operación.
"""

from __future__ import annotations

import pytest

from app.domain.colores_texto import SINONIMOS, leer_colores, normalizar
from app.domain.guion import (
    DESPUES_DEL_ABONO,
    IMAGENES,
    OPCIONES,
    ORDEN,
    TEXTOS,
    Paso,
    huecos_de,
    siguiente_paso,
    texto,
)
from app.domain.personalizacion import (
    MAX_GRABADOS,
    ColorCircon,
    Huellita,
    Personalizacion,
)

LILA_MORADO = Huellita(corazon=ColorCircon.LILA, dedos=ColorCircon.MORADO)


def _personalizacion(**kw) -> Personalizacion:
    return Personalizacion(**kw)


class TestOrdenDelGuion:
    """La decisión de conversión, convertida en test."""

    def test_la_talla_se_pide_DESPUES_del_abono(self):
        """LA regla del guion. Si alguien la invierte, esto se pone rojo.

        Motivo: la talla es el único paso que exige un anillo y una regla
        físicos. Puesta antes del pago, es donde se pierde la venta.
        """
        assert ORDEN.index(Paso.TALLA) > ORDEN.index(Paso.CONFIRMAR_Y_ABONAR)
        assert Paso.TALLA in DESPUES_DEL_ABONO

    def test_el_diseno_se_pide_ANTES_del_abono(self):
        """Diseñar el anillo es lo que la engancha. Cobrar antes de que lo
        haya visto suyo es pedir plata a una desconocida."""
        for paso in (Paso.COLORES, Paso.GRABADO):
            assert ORDEN.index(paso) < ORDEN.index(Paso.CONFIRMAR_Y_ABONAR)
            assert paso not in DESPUES_DEL_ABONO

    def test_nunca_se_pide_la_talla_antes_de_cobrar(self):
        """Cualquier estado, sin abono: el paso jamás puede ser TALLA."""
        estados = [
            _personalizacion(),
            _personalizacion(huellitas=[LILA_MORADO]),
            _personalizacion(huellitas=[LILA_MORADO], grabados=["Rocky"]),
        ]
        for p in estados:
            for n in (1, 2, 3):
                assert (
                    siguiente_paso(p, huellitas_esperadas=n, abono_pagado=False)
                    is not Paso.TALLA
                )


class TestMaquinaDelGuion:
    @pytest.mark.parametrize(
        ("huellitas", "personalizacion", "abono", "esperado"),
        [
            (0, {}, False, Paso.ELEGIR_PRODUCTO),
            (1, {}, False, Paso.COLORES),
            (1, {"huellitas": [LILA_MORADO]}, False, Paso.GRABADO),
            (
                1,
                {"huellitas": [LILA_MORADO], "grabados": ["Rocky"]},
                False,
                Paso.CONFIRMAR_Y_ABONAR,
            ),
            (
                1,
                {"huellitas": [LILA_MORADO], "grabados": ["Rocky"]},
                True,
                Paso.TALLA,
            ),
            (
                1,
                {"huellitas": [LILA_MORADO], "grabados": ["Rocky"], "talla": 7},
                True,
                Paso.LISTO,
            ),
        ],
    )
    def test_camino_completo(self, huellitas, personalizacion, abono, esperado):
        assert (
            siguiente_paso(
                _personalizacion(**personalizacion),
                huellitas_esperadas=huellitas,
                abono_pagado=abono,
            )
            is esperado
        )

    def test_un_anillo_de_tres_huellitas_pide_los_tres_colores(self):
        p = _personalizacion(huellitas=[LILA_MORADO, LILA_MORADO], grabados=["A"])
        assert (
            siguiente_paso(p, huellitas_esperadas=3, abono_pagado=False) is Paso.COLORES
        )

    def test_es_una_funcion_pura(self):
        """Mismo estado, mismo paso. Diez veces seguidas."""
        p = _personalizacion(huellitas=[LILA_MORADO])
        vistos = {
            siguiente_paso(p, huellitas_esperadas=1, abono_pagado=False)
            for _ in range(10)
        }
        assert len(vistos) == 1

    def test_sin_talla_nunca_llega_a_LISTO(self):
        """No se puede fabricar sin talla. Ni con el abono pagado."""
        p = _personalizacion(huellitas=[LILA_MORADO], grabados=["Rocky"])
        assert siguiente_paso(p, huellitas_esperadas=1, abono_pagado=True) is Paso.TALLA


class TestTextosDelGuion:
    def test_todos_los_pasos_tienen_texto(self):
        faltan = [p.value for p in Paso if p not in TEXTOS]
        assert not faltan, f"pasos mudos: {faltan}"

    def test_todos_los_pasos_del_orden_existen_en_el_enum(self):
        assert set(ORDEN) <= set(Paso)

    def test_las_plantillas_se_rellenan_sin_reventar(self):
        """Un `{hueco}` mal escrito llegaría literal a la clienta."""
        datos = {
            "numero": 1,
            "resumen": "Colores: corazón lila / dedos morado",
            "total": "$200.000",
            "anticipo": "$60.000",
            "saldo": "$140.000",
            "dias": 10,
            "dias_max": 15,
            "envio_contraentrega": "$16.500",
            "codigo": "PED-2026-0001",
            "nombre": "Ángela",
        }
        for paso in Paso:
            necesita = huecos_de(paso) - {"max_grabados"}
            salida = texto(paso, **{k: datos[k] for k in necesita})
            assert "{" not in salida, f"{paso.value} dejó un hueco sin rellenar"
            assert salida.strip()

    def test_el_momento_del_abono_responde_las_tres_objeciones(self):
        """El mensaje donde se pide la plata es el de máxima desconfianza.
        Tiene que contestar solo lo que la clienta iba a preguntar."""
        t = TEXTOS[Paso.CONFIRMAR_Y_ABONAR].lower()
        assert "fotos" in t, "no explica que verá fotos antes de pagar el saldo"
        assert "925" in t, "no dice que es plata de verdad"
        assert "garantía" in t, "no menciona la garantía"
        assert "días" in t, "no dice cuándo lo recibe"

    def test_el_paso_de_la_talla_dice_que_no_hay_afan(self):
        """Ya pagó. Si se siente presionada aquí, se arrepiente."""
        assert "afán" in TEXTOS[Paso.TALLA].lower()

    def test_los_botones_del_catalogo_son_los_tres_anillos(self):
        ids = {o.id for o in OPCIONES[Paso.ELEGIR_PRODUCTO]}
        assert ids == {"ANI-HUE-1", "ANI-HUE-2", "ANI-HUE-3"}

    def test_el_paso_de_colores_manda_el_muestrario(self):
        """Sin la foto de las bolsitas, «lila» y «morado» son lo mismo."""
        assert IMAGENES[Paso.COLORES] == "muestrario_circones"

    def test_el_maximo_de_grabados_sale_del_dominio_y_no_a_mano(self):
        """Si mañana caben 6 nombres, el texto tiene que cambiar solo."""
        assert str(MAX_GRABADOS) in texto(Paso.GRABADO)


class TestLeerColores:
    """Los mensajes reales de las clientas de Lía."""

    @pytest.mark.parametrize(
        ("mensaje", "corazon", "dedos"),
        [
            ("quiero corazon lila y dedos morados", ColorCircon.LILA, ColorCircon.MORADO),
            (
                "-quiero corazón lila y dedos morados",
                ColorCircon.LILA,
                ColorCircon.MORADO,
            ),
            ("corazon rojo dedos blancos", ColorCircon.ROJO, ColorCircon.BLANCO),
            ("la quiero toda negra", ColorCircon.NEGRO, ColorCircon.NEGRO),
            ("todo azul rey", ColorCircon.AZUL_REY, ColorCircon.AZUL_REY),
            (
                "el corazon rosado y alrededor fucsia",
                ColorCircon.ROSADO,
                ColorCircon.FUCSIA,
            ),
            (
                "quiero la huellita blanca con deditos negros",
                ColorCircon.BLANCO,
                ColorCircon.NEGRO,
            ),
            (
                "corazón lila, morado los deditos",
                ColorCircon.LILA,
                ColorCircon.MORADO,
            ),
            (
                "verde esmeralda el corazon y los deditos blancos",
                ColorCircon.VERDE_ESMERALDA,
                ColorCircon.BLANCO,
            ),
        ],
    )
    def test_mensajes_reales(self, mensaje, corazon, dedos):
        r = leer_colores(mensaje)
        assert (r.corazon, r.dedos) == (corazon, dedos)
        assert r.completa

    def test_los_plurales_no_se_pierden(self):
        """«dedos morados» en plural es como escribe TODO el mundo. Sin esto,
        el mensaje más común de la operación perdía el segundo color."""
        assert leer_colores("corazon lila dedos morados").dedos is ColorCircon.MORADO
        assert leer_colores("corazon azules").corazon is ColorCircon.AZUL_REY

    def test_azul_rey_le_gana_a_azul(self):
        """Si «azul» se buscara primero, «azul rey» no existiría nunca."""
        assert leer_colores("todo azul rey").corazon is ColorCircon.AZUL_REY

    def test_ante_la_duda_NO_adivina(self):
        """Un color mal leído es un anillo de plata del color equivocado.
        Preguntar otra vez cuesta un mensaje."""
        r = leer_colores("lila y morado")
        assert not r.completa
        assert set(r.sueltos) == {ColorCircon.LILA, ColorCircon.MORADO}

    def test_un_color_solo_es_ambiguo(self):
        r = leer_colores("celeste")
        assert not r.completa
        assert r.sueltos == (ColorCircon.CELESTE,)

    def test_un_mensaje_sin_colores_no_inventa_ninguno(self):
        for m in ("hola", "cuanto vale", "", "gracias!!"):
            r = leer_colores(m)
            assert (r.corazon, r.dedos, r.sueltos) == (None, None, ())

    def test_todos_los_colores_del_muestrario_se_pueden_nombrar(self):
        """Si un color no tiene ni un sinónimo, la clienta no puede pedirlo."""
        cubiertos = set(SINONIMOS.values())
        faltan = [c.value for c in ColorCircon if c not in cubiertos]
        assert not faltan, f"colores que nadie puede pedir: {faltan}"

    def test_es_determinista(self):
        m = "quiero corazon lila y dedos morados"
        assert len({leer_colores(m) for _ in range(50)}) == 1

    def test_normalizar_quita_tildes_y_signos(self):
        assert normalizar("¡Corazón LILA!") == " corazon lila "


class TestVariasHuellitasEnUnMensaje:
    """«Corazón lila dedos rojos y el tercero verde corazón azul dedos».

    Es una frase real de una conversación real. Antes se leía la primera
    pareja y las otras se perdían sin que nadie lo notara.
    """

    def test_dos_parejas_seguidas(self):
        from app.domain.colores_texto import leer_varias

        v = leer_varias("corazon lila dedos rojos y el tercero verde corazon azul dedos")
        assert v.parejas == (
            (ColorCircon.LILA, ColorCircon.ROJO),
            (ColorCircon.VERDE_ESMERALDA, ColorCircon.AZUL_REY),
        )

    @pytest.mark.parametrize(
        "mensaje, esperado",
        [
            ("corazon lila y dedos morados", (ColorCircon.LILA, ColorCircon.MORADO)),
            ("corazón lila, morado los deditos", (ColorCircon.LILA, ColorCircon.MORADO)),
            (
                "verde esmeralda el corazon y los deditos blancos",
                (ColorCircon.VERDE_ESMERALDA, ColorCircon.BLANCO),
            ),
            ("la quiero toda negra", (ColorCircon.NEGRO, ColorCircon.NEGRO)),
            ("corazon rojo dedos blancos", (ColorCircon.ROJO, ColorCircon.BLANCO)),
        ],
    )
    def test_una_sola_sigue_leyendose_igual(self, mensaje, esperado):
        from app.domain.colores_texto import leer_varias

        assert leer_varias(mensaje).parejas == (esperado,)

    def test_una_correccion_no_es_una_huellita_mas(self):
        """«Corazón lila y corazón rojo» es una sola patita, la roja."""
        from app.domain.colores_texto import leer_varias

        v = leer_varias("corazon lila y corazon rojo")
        assert v.parejas == ()
        assert dict(v.media) == {"corazon": ColorCircon.ROJO}

    def test_sin_partes_nombradas_no_se_empareja_nada(self):
        from app.domain.colores_texto import leer_varias

        v = leer_varias("lila y morado")
        assert v.parejas == ()
        assert set(v.sueltos) == {ColorCircon.LILA, ColorCircon.MORADO}
