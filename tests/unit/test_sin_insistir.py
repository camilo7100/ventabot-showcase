"""Cuándo NO se pregunta, y lo grabado entre comillas (Camilo, 06/10).

Real: pedido completo, esperando que Lía confirmara la talla. Ella: «Gracias
🥰». El bot: «¡Con gusto! 🥰 ¿Quieres grabar algo más junto a Bombom, como una
fecha o unas alitas?». La regla de «termina con una pregunta» es para que la
conversación avance mientras le falte algo a ELLA; cuando lo que sigue es de Lía
(o ya pagó), no se insiste.
"""

from __future__ import annotations

import pytest

from app.conversacion.asesora import (
    con_comillas,
    nada_que_preguntarle,
    sin_preguntas_de_mas,
)
from app.domain.asesora import Borrador, HuellitaDelBorrador
from app.domain.personalizacion import ColorCircon as C
from tests.unit.test_talla_la_confirma_lia import (  # noqa: F401  (la fixture)
    CONV,
    _asesora,
    _guardar,
    _jugada,
    mundo,
)


def _laura(**kw) -> Borrador:
    """Como estaba Laura: todo escogido; la talla (la foto) la mira Lía."""
    base = dict(
        talla_exige_lia=True,
        turnos=9,
        cantidad=1,
        huellitas=[HuellitaDelBorrador(corazon=C.BLANCO, dedos=C.LILA)],
        grabado=["Bombom"],
        nombre_clienta="Laura Contreras",
        talla_revisar=True,
        talla_fotos=["regla.jpg"],
    )
    return Borrador(**{**base, **kw})


class TestCuandoNoHayNadaQuePreguntarle:
    def test_esperando_la_talla_de_lia(self):
        assert nada_que_preguntarle(_laura())

    def test_ya_pago(self):
        assert nada_que_preguntarle(Borrador(turnos=5, abono_reportado=True))
        assert nada_que_preguntarle(Borrador(turnos=5), "EN_PRODUCCION")

    def test_si_le_falta_algo_a_ella_si_se_pregunta(self):
        assert not nada_que_preguntarle(_laura(grabado=[]))
        assert not nada_que_preguntarle(Borrador(turnos=3, cantidad=1))

    def test_el_resumen_por_confirmar_si_se_pregunta(self):
        """Todo listo y la talla confirmada: falta su «sí» al resumen."""
        b = _laura(talla=7.0, talla_revisar=False, talla_confirmada=True)
        assert b.falta_para_abono() == [] and not nada_que_preguntarle(b)

    @pytest.mark.parametrize(
        "texto, limpio",
        [
            (
                "¡Con gusto! 🥰 ¿Quieres grabar algo más junto a Bombom, como una fecha "
                "o unas alitas?",
                "¡Con gusto! 🥰",
            ),
            (
                "¡Listo, Laura! 🥰 En unos minutos Lía te confirma la talla y te pasa el "
                "resumen, ¿te parece?",
                "¡Listo, Laura! 🥰 En unos minutos Lía te confirma la talla y te pasa el "
                "resumen",
            ),
        ],
    )
    def test_sin_preguntas_de_mas(self, texto, limpio):
        assert sin_preguntas_de_mas(texto) == limpio


class TestElTurno:
    def test_el_caso_de_laura(self, mundo):  # noqa: F811
        a = _asesora(
            mundo,
            _jugada(
                "¡Con gusto! 🥰 ¿Quieres grabar algo más junto a Bombom, como una "
                "fecha o unas alitas?"
            ),
        )
        _guardar(mundo, _laura())
        texto = a.ejecutar(CONV, "Gracias 🥰").respuesta.texto_plano
        assert "?" not in texto, texto
        assert texto.startswith("¡Con gusto! 🥰")

    def test_si_ella_pregunta_se_le_contesta_con_su_pregunta(self, mundo):  # noqa: F811
        """«¿Se puede otro nombre?» sí lleva su «¿cuál agregamos?»."""
        a = _asesora(
            mundo,
            _jugada(
                "Siii, puedes grabar hasta 5 nombres 😊 ¿Cuál otro nombre agregamos?"
            ),
        )
        _guardar(mundo, _laura())
        texto = a.ejecutar(CONV, "Se puede otro nombre?").respuesta.texto_plano
        assert "¿Cuál otro nombre agregamos?" in texto

    def test_si_le_falta_algo_la_pregunta_se_queda(self, mundo):  # noqa: F811
        a = _asesora(
            mundo, _jugada("¡Con gusto! 🥰 ¿Qué nombre quieres grabar en el aro?")
        )
        _guardar(mundo, _laura(grabado=[]))
        texto = a.ejecutar(CONV, "Gracias 🥰").respuesta.texto_plano
        assert "¿Qué nombre quieres grabar en el aro?" in texto


class TestLoGrabadoEntreComillas:
    def test_el_nombre_va_entre_comillas(self):
        assert (
            con_comillas("Bombom 🐾 ¡Qué lindo!", ["Bombom"]) == "«Bombom» 🐾 ¡Qué lindo!"
        )

    def test_varios_y_sin_duplicar(self):
        texto = "Agregamos Adela junto a «Bombom» 🐾"
        assert con_comillas(texto, ["Bombom", "Adela"]) == (
            "Agregamos «Adela» junto a «Bombom» 🐾"
        )

    def test_no_dentro_de_otra_palabra(self):
        assert con_comillas("Lunares y Luna", ["Luna"]) == "Lunares y «Luna»"

    def test_en_el_turno(self, mundo):  # noqa: F811
        a = _asesora(
            mundo, _jugada("Bombom 🐾 ¡Qué lindo! ¿A nombre de quién va el pedido?")
        )
        _guardar(
            mundo, _laura(grabado=["Bombom"], nombre_clienta="", talla_revisar=False)
        )
        texto = a.ejecutar(CONV, "Bombom").respuesta.texto_plano
        assert "«Bombom»" in texto


class TestLasPreguntasDeMasDeLaCharlaDeLaura:
    """La charla entera de Laura (06/10), revisada turno por turno."""

    def test_la_coletilla_cuando_ya_no_falta_nada(self, mundo):  # noqa: F811
        a = _asesora(
            mundo,
            _jugada(
                "¡Listo, Laura! 🥰 En unos minutos Lía te confirma la talla, ¿te parece?"
            ),
        )
        _guardar(mundo, _laura())
        texto = a.ejecutar(CONV, "Si por favor").respuesta.texto_plano
        assert "¿te parece?" not in texto

    def test_no_confirma_lo_que_ella_dijo_claro(self, mundo):  # noqa: F811
        """«Adela» -> «Siii, agregamos Adela junto a Bombom 🐾 ¿Así quedan los dos
        nombres?»: quedó anotado; confirmarlo es preguntar de más."""
        a = _asesora(
            mundo,
            _jugada(
                "Siii, agregamos Adela junto a Bombom 🐾 ¿Así quedan los dos nombres?",
                grabado=["Bombom", "Adela"],
            ),
        )
        _guardar(mundo, _laura(talla_revisar=False, talla_fotos=[], talla=None))
        texto = a.ejecutar(CONV, "Adela").respuesta.texto_plano
        assert "¿Así quedan" not in texto
        assert "«Adela»" in texto and "«Bombom»" in texto

    def test_si_no_quedo_anotado_si_puede_confirmar(self, mundo):  # noqa: F811
        """Si la IA no anotó el grabado porque dudó, su pregunta se queda."""
        a = _asesora(mundo, _jugada("¿Will es el nombre que quieres grabar?"))
        _guardar(mundo, _laura(grabado=[]))
        texto = a.ejecutar(CONV, "Will").respuesta.texto_plano
        assert "es el nombre que quieres grabar?" in texto

    def test_si_contesta_otra_cosa_se_le_sigue_preguntando(self, mundo):  # noqa: F811
        """Camilo (07/10): si contestó otra cosa («Buenos días, qué pena…») o solo
        una parte, se le sigue preguntando lo que falta. Mónica: «No así toda»
        quedó sin que se le volviera a pedir el grabado."""
        anterior = (
            "Para la talla, te la miden en una joyería 😊 ¿Qué color te gustaría "
            "para el corazón y los deditos?"
        )
        a = _asesora(
            mundo,
            _jugada(
                "¡Buenos días! No te preocupes 😊 ¿Qué color te gustaría para el "
                "corazón y los deditos?"
            ),
        )
        ctx = mundo.contexto(CONV)
        mundo.guardar_contexto(
            ctx.model_copy(update={"charla": [{"de": "lia", "texto": anterior}]})
        )
        _guardar(mundo, Borrador(talla_exige_lia=True, turnos=4, cantidad=1))
        texto = a.ejecutar(CONV, "Buenos días, qué pena ayer no alcancé").respuesta
        assert "¿Qué color te gustaría" in texto.texto_plano


class TestYaPagoPeroFaltaElComprobante:
    def test_la_pregunta_del_comprobante_se_queda_y_no_deja_frases_cortadas(self):
        """Prueba de verdad (06/10): «ya te transferí» -> «¡Recibido! 🙌 Para pasar
        tu pedido al taller, ¿me compartes el comprobante?» quedaba en «Para
        pasar tu pedido al taller,»."""
        texto = (
            "¡Recibido! 🙌 Para pasar tu pedido al taller, ¿me compartes el "
            "comprobante, porfa?"
        )
        assert sin_preguntas_de_mas(texto) == texto
        otra = "¡Listo! 🙌 Para que quede perfecto, ¿quieres agregar una fecha?"
        assert sin_preguntas_de_mas(otra) == "¡Listo! 🙌"


class TestSiSoloConfirmaba:
    def test_queda_el_anotado_y_no_vuelve_a_la_guia(self, mundo):  # noqa: F811
        """Prueba de verdad (06/10): «Will» -> la IA solo preguntaba «¿Will es el
        nombre que quieres grabar?»; al quitarlo, el relleno era «¿Sabes tu talla
        o te comparto la guía?» a quien ya fue a la joyería."""
        from app.conversacion.asesora import PREGUNTA_DE_LA_TALLA, SIN_ANILLOS

        a = _asesora(
            mundo, _jugada("¿Will es el nombre que quieres grabar?", grabado=["Will"])
        )
        _guardar(
            mundo,
            Borrador(
                talla_exige_lia=True,
                turnos=6,
                cantidad=1,
                huellitas=[HuellitaDelBorrador(corazon=C.NEGRO, dedos=C.NEGRO)],
                mostrado_en={SIN_ANILLOS: 3},
            ),
        )
        texto = a.ejecutar(CONV, "Will").respuesta.texto_plano
        assert texto.startswith("¡Anotado! 🫶")
        assert PREGUNTA_DE_LA_TALLA not in texto and "guía" not in texto
        assert "nombre completo" in texto, "sigue con lo que falta: su nombre"


class TestLaCharlaDeMonica:
    """La charla entera de Mónica (07/10), revisada turno por turno."""

    def test_de_una_es_una_huellita(self):
        from app.domain.asesora import cantidad_contestada

        pregunta = "¡Súper! ¿De cuántas huellitas lo quieres? 🐾"
        assert cantidad_contestada("De una", pregunta) == 1
        assert cantidad_contestada("dos", pregunta) == 2
        assert cantidad_contestada("De una", "¿Qué nombre quieres grabar?") is None

    def test_la_verdad_creo_que_soy_7(self):
        from app.conversacion.asesora import PREGUNTA_DE_LA_TALLA
        from app.domain.tallas import talla_dictada

        assert talla_dictada("La verdad creo que soy 7", PREGUNTA_DE_LA_TALLA) == 7

    def test_las_comillas_no_se_anidan(self):
        nombres = ["Campanita", "Dulce", "Eva", "Adán", "miruso"]
        ya = "Quedarían así: «Campanita ♡ Dulce ♡ Eva ♡ Adán ♡ miruso» 🐾"
        assert con_comillas(ya, nombres) == ya
        suelto = "Quedarían así: Campanita ♡ Dulce ♡ Eva ♡ Adán ♡ miruso 🐾"
        assert con_comillas(suelto, nombres) == ya

    def test_pospone_es_pospone_y_te_confirmo_no(self):
        from app.domain.recordatorios import pospone

        assert pospone("Yo el día de mañana le estaré consignando")
        assert pospone("Ahora no me queda fácil")
        assert not pospone("Sí, te confirmo que es toda rosa")


class TestLaCadenaDeUna:
    def test_pregunta_por_la_cadena_y_va_la_informacion(self, mundo):  # noqa: F811
        """Erika (07/10): «Y la cadena con 3 huellitas» -> «La cadena lleva una
        sola huellita… ¿Quieres que te cuente cómo es?». Va DE UNA."""
        from app.conversacion.asesora import PREGUNTA_DE_LA_CADENA

        a = _asesora(
            mundo,
            _jugada(
                "La cadena lleva una sola huellita, no se puede hacer con 3 😊 "
                "¿Quieres que te cuente cómo es?"
            ),
        )
        _guardar(mundo, Borrador(turnos=1))
        t = a.ejecutar(CONV, "Y la cadena con 3 huellitas")
        texto = t.respuesta.texto_plano
        assert "una sola huellita" in texto
        assert "Nuestra cadenita personalizada" in texto
        assert "te cuente" not in texto
        assert texto.rstrip().endswith(PREGUNTA_DE_LA_CADENA)


class TestLoQueEncontroLaPruebaDeVerdad0710:
    def test_de_una_no_vuelve_a_preguntar_la_cantidad(self, mundo):  # noqa: F811
        """Mónica: «De una» -> «¡Súper! 🐾 ¿Lo quieres de 1, 2 o 3 huellitas?»."""
        a = _asesora(mundo, _jugada("¡Súper! 🐾 ¿Lo quieres de 1, 2 o 3 huellitas?"))
        ctx = mundo.contexto(CONV)
        mundo.guardar_contexto(
            ctx.model_copy(
                update={
                    "charla": [
                        {"de": "lia", "texto": "¿De cuántas huellitas lo quieres? 🐾"}
                    ]
                }
            )
        )
        _guardar(mundo, Borrador(talla_exige_lia=True, turnos=3, talla=7.0))
        texto = a.ejecutar(CONV, "De una").respuesta.texto_plano
        assert "1, 2 o 3" not in texto
        # Con una huellita, en singular (13/10): «¿De qué color quieres la huellita?»
        assert "color" in texto, "sigue con lo que falta"

    def test_pago_a_medias_se_le_sigue_pidiendo_lo_que_falta(self):
        b = Borrador(turnos=4, cantidad=1, talla=9.0, pagado_sin_pedido=True)
        assert not nada_que_preguntarle(b)

    def test_no_promete_confirmar_una_talla_que_no_ha_dado(self):
        from app.domain.asesora import vigilar

        b = Borrador(turnos=5, cantidad=1, grabado=["Luna"])
        limpio, problemas = vigilar(
            "¡Listo, Laura! 🫶 Ya casi; en unos minutos te confirmo la talla.", set(), b
        )
        assert problemas and "confirmo" not in limpio
        _, ok = vigilar("Cuando me mandes la foto, te confirmo tu talla 💍", set(), b)
        assert not ok
