"""Clientas de todos los estilos, porque ninguna escribe como el manual.

════════════════════════════════════════════════════════════════════════════
QUÉ SE PRUEBA AQUÍ Y POR QUÉ NO EN OTRO SITIO
════════════════════════════════════════════════════════════════════════════
`test_conversaciones_reales.py` recorre el esqueleto de una venta. Esto es lo
contrario: **lo que se sale del esqueleto**. La que escribe en mayúsculas, la
que manda todo en un párrafo, la que desaparece tres días, la que dice «está
caro», la que manda una nota de voz, la que quiere tres anillos, la que pide
una persona.

Cada uno de estos casos existe en las conversaciones reales de Lía. Y cada uno
es un sitio donde una venta se puede caer en silencio: el bot no se rompe, solo
contesta algo que no encaja y la clienta deja de escribir.

Todos usan el modelo simulado: cuestan cero y corren en milisegundos.
"""

from __future__ import annotations

import pytest

from app.domain.asesora import (
    AccionAsesora,
    Borrador,
    HuellitaPropuesta,
)
from app.domain.personalizacion import ColorCircon as C
from tests.unit.test_asesora import CONV, _asesora, _jugada, mundo

__all__ = ["mundo"]


def _texto(respuesta) -> str:
    return " ".join(p.texto or "" for p in respuesta.piezas)


def _fotos(respuesta) -> list[str]:
    return [p.imagen for p in respuesta.piezas if p.imagen]


def _borrador(turno) -> Borrador:
    return Borrador.model_validate(turno.contexto.borrador)


# ══════════════════════════════════════════════════════════════════════════
#  1. Cómo escribe la gente
# ══════════════════════════════════════════════════════════════════════════


class TestComoEscribeLaGente:
    @pytest.mark.parametrize(
        "mensaje",
        [
            "QUIERO UNO DE DOS HUELLITAS",
            "quiero uno d 2 huellitas",
            "kiero 2 huellitas porfa",
            "Quiero    uno   de dos   huellitas",
            "quiero uno de dos huellitas 🐾🐾",
        ],
    )
    def test_mayusculas_faltas_y_emojis_no_cambian_nada(self, mundo, mensaje):
        """Lo que entiende el modelo es cosa suya; lo que NO puede pasar es
        que Python tire lo que ya entendió por cómo venía escrito."""
        a = _asesora(mundo, _jugada("¡Dos huellitas! 💜", cantidad_huellitas=2))
        t = a.ejecutar(CONV, mensaje)
        assert _borrador(t).cantidad == 2

    def test_todo_en_un_parrafo_de_una_vez(self, mundo):
        """«Quiero uno de 1 huellita, negra, que diga Rocky, talla 7, soy
        Laura» — pasa, y es la mejor clienta del mundo."""
        a = _asesora(
            mundo,
            _jugada(
                "¿Así está bien? 🥰",
                cantidad_huellitas=1,
                huellitas=[HuellitaPropuesta(numero=1, corazon=C.NEGRO, dedos=C.NEGRO)],
                grabado=["Rocky"],
                talla=7,
                nombre_clienta="Laura Gómez",
            ),
        )
        t = a.ejecutar(CONV, "uno de 1 huellita negra que diga Rocky talla 7, soy Laura")
        assert _borrador(t).falta_para_abono() == []

    def test_manda_cinco_mensajes_seguidos(self, mundo):
        """Cada uno es un turno para la asesora; ninguno se pierde."""
        a = _asesora(
            mundo,
            _jugada("¡Hola! 🥰"),
            _jugada("¡Una huellita! 💜", cantidad_huellitas=1),
            _jugada(
                "¡Negro, qué elegante! 🖤",
                huellitas=[HuellitaPropuesta(numero=1, corazon=C.NEGRO, dedos=C.NEGRO)],
            ),
            _jugada("¡Listo, Rocky! 🐾", grabado=["Rocky"]),
            _jugada("¡Talla 7! 💍", talla=7),
        )
        for mensaje in ("hola", "una", "negra", "rocky", "talla 7"):
            assert a.ejecutar(CONV, mensaje).respuesta.piezas
        t = a.ejecutar(CONV, "ya")
        b = _borrador(t)
        assert b.cantidad == 1 and b.talla == 7 and b.grabado == ["Rocky"]

    def test_una_nota_de_voz_se_entiende_y_queda_anotada(self, mundo):
        a = _asesora(
            mundo,
            _jugada(
                "¡Perfecto, morado! 💜",
                huellitas=[HuellitaPropuesta(numero=1, corazon=C.MORADO, dedos=C.MORADO)],
            ),
        )
        t = a.ejecutar(CONV, "", media=[{"kind": "audio", "media_id": "a1"}])
        assert t.respuesta.piezas, "una nota de voz no puede dejar al bot mudo"


# ══════════════════════════════════════════════════════════════════════════
#  2. Las preguntas de siempre
# ══════════════════════════════════════════════════════════════════════════


class TestLasPreguntasDeSiempre:
    @pytest.mark.parametrize(
        ("pregunta", "respuesta_del_modelo"),
        [
            ("¿de qué material es?", "Plata Ley 925 con circones ✨ No se pela"),
            ("¿tiene garantía?", "6 meses por defectos de fabricación 💍"),
            ("¿cuánto se demora?", "10 a 15 días calendario ⏳"),
            ("¿hacen envíos a Cali?", "¡Sí! A todo el país por Coordinadora 🚚"),
            ("¿puedo pagar con tarjeta?", "Con tarjeta te generamos el link 💳"),
        ],
    )
    def test_se_contestan_en_una_linea_sin_reenviar_la_ficha(
        self, mundo, pregunta, respuesta_del_modelo
    ):
        """Lía contesta estas con una frase. Reenviar la presentación entera
        es lo que hacía el bot el 20/09 y es lo que cansa."""
        a = _asesora(mundo, _jugada(respuesta_del_modelo))
        r = a.ejecutar(CONV, pregunta).respuesta
        assert _texto(r).strip()
        assert "$250.000" not in _texto(r), "reenvió la ficha de precios"
        assert not _fotos(r), "mandó fotos para contestar una pregunta"

    def test_pregunta_el_precio_a_mitad_de_la_charla(self, mundo):
        """La ficha ya se mandó en la apertura: aquí va una frase."""
        a = _asesora(mundo, _jugada("El de 2 huellitas son $250.000 💍"))
        r = a.ejecutar(CONV, "¿y el de dos cuánto vale?").respuesta
        assert "250.000" in _texto(r)
        assert not _fotos(r)


# ══════════════════════════════════════════════════════════════════════════
#  3. Las que cuestan plata si se contestan mal
# ══════════════════════════════════════════════════════════════════════════


class TestLasQueCuestanPlata:
    def test_dice_que_esta_caro_y_el_bot_NO_inventa_un_descuento(self, mundo):
        """Si el modelo se inventa un precio, el vigilante lo borra: un
        descuento que nadie autorizó lo paga Lía."""
        a = _asesora(mundo, _jugada("¡Te lo dejo en $150.000! 😍"))
        r = a.ejecutar(CONV, "uy está caro").respuesta
        assert "150.000" not in _texto(r), "se inventó un precio"

    def test_pide_una_persona_y_el_bot_escala(self, mundo):
        a = _asesora(
            mundo, _jugada("¡Claro! Ya te paso con Lía 🥰", AccionAsesora.PASAR_A_LIA)
        )
        t = a.ejecutar(CONV, "quiero hablar con una persona de verdad")
        assert t.respuesta.escalar

    def test_una_queja_llega_a_una_persona(self, mundo):
        a = _asesora(mundo, _jugada("Lo siento muchísimo 🥺", AccionAsesora.PASAR_A_LIA))
        assert a.ejecutar(CONV, "el anillo me llegó partido").respuesta.escalar

    def test_paga_y_el_bot_NUNCA_dice_que_esta_confirmado(self, mundo):
        a = _asesora(
            mundo,
            _jugada(
                "¡Pago confirmado! Ya lo verifiqué 🙌", AccionAsesora.RECIBIR_COMPROBANTE
            ),
        )
        texto = _texto(a.ejecutar(CONV, "ya te transferí").respuesta).lower()
        assert "confirmad" not in texto and "verifiqué" not in texto

    def test_pregunta_por_su_pedido_y_no_se_le_inventa_un_estado(self, mundo):
        """Sin pedido no se puede decir «va en camino»."""
        a = _asesora(mundo, _jugada("¡Tu anillo ya va en camino! 🚚"))
        texto = _texto(a.ejecutar(CONV, "¿cómo va mi anillo?").respuesta).lower()
        assert "en camino" not in texto


# ══════════════════════════════════════════════════════════════════════════
#  4. Las que se salen del guion
# ══════════════════════════════════════════════════════════════════════════


class TestSeSalenDelGuion:
    def test_quiere_tres_anillos_distintos(self, mundo):
        """Se toma el primero y se le dice que el otro va después."""
        a = _asesora(
            mundo, _jugada("¡Empecemos por el primero! 💍", cantidad_huellitas=1)
        )
        assert a.ejecutar(
            CONV, "quiero tres anillos, uno para cada hermana"
        ).respuesta.piezas

    def test_cambia_la_cantidad_a_mitad(self, mundo):
        a = _asesora(
            mundo,
            _jugada("¡Una huellita! 💜", cantidad_huellitas=1),
            _jugada("¡Cambiado a dos! 🐾", cantidad_huellitas=2),
        )
        a.ejecutar(CONV, "una huellita")
        t = a.ejecutar(CONV, "mejor que sean dos")
        assert _borrador(t).cantidad == 2

    def test_desaparece_y_vuelve_tres_dias_despues(self, mundo):
        """El borrador tiene que seguir ahí: volver a preguntarle todo es
        perderla otra vez."""
        a = _asesora(
            mundo,
            _jugada(
                "¡Negro, qué elegante! 🖤",
                cantidad_huellitas=1,
                huellitas=[HuellitaPropuesta(numero=1, corazon=C.NEGRO, dedos=C.NEGRO)],
            ),
            _jugada("¡Aquí seguimos! 🥰"),
        )
        a.ejecutar(CONV, "una negra")
        t = a.ejecutar(CONV, "hola, perdón la demora")
        b = _borrador(t)
        assert b.cantidad == 1 and b.huellitas[0].corazon is C.NEGRO

    def test_pregunta_algo_que_no_tiene_nada_que_ver(self, mundo):
        a = _asesora(mundo, _jugada("Jajaja, de anillos sí sé 🥰"))
        assert a.ejecutar(CONV, "¿sabes qué hora es en Japón?").respuesta.piezas

    def test_manda_una_foto_de_su_mascota(self, mundo):
        a = _asesora(mundo, _jugada("¡Qué belleza tu peludito! 🐾"))
        t = a.ejecutar(CONV, "mira mi gato", media=[{"kind": "image", "media_id": "m1"}])
        assert t.respuesta.piezas

    def test_dice_que_lo_recoge(self, mundo):
        """Si lo recoge no hacen falta ni ciudad, ni cédula, ni dirección.
        El nombre sí: hay que saber a quién se le entrega."""
        a = _asesora(
            mundo,
            _jugada(
                "¡Perfecto, lo recoges! 🥰",
                recoge_en_tienda=True,
                nombre_clienta="Laura Gómez",
            ),
        )
        t = a.ejecutar(CONV, "yo paso a recogerlo, vivo en Floridablanca")
        b = _borrador(t)
        assert b.recoge and b.falta_para_despachar() == []

    def test_un_grabado_con_emojis_y_fecha(self, mundo):
        """«🐱 Gordo & Pan 🍞» y «Paz ♡ 05/01/2025» son grabados reales."""
        a = _asesora(mundo, _jugada("¡Qué lindo! 🫶", grabado=["Paz ♡ 05/01/2025"]))
        t = a.ejecutar(CONV, "que diga Paz ♡ 05/01/2025")
        assert _borrador(t).grabado == ["Paz ♡ 05/01/2025"]

    def test_no_quiere_grabado(self, mundo):
        a = _asesora(mundo, _jugada("¡Listo, sin grabado! ✨", sin_grabado=True))
        t = a.ejecutar(CONV, "sin grabado por favor")
        assert "grabado" not in _borrador(t).falta_para_abono()


class TestElRegistroSePuedeLeerDespues:
    """Leer el registro de una noche entera sin fecha es adivinar.

    Y cuando dos procesos escriben a la vez —el que se está cerrando y el que
    arranca— las líneas quedan desordenadas sin que se pueda notar. Pasó el
    20/09 y costó un rato entender que no había un servidor duplicado."""

    def test_el_archivo_lleva_la_fecha(self):
        import logging

        from app.infra.logging import Formato

        registro = logging.LogRecord(
            "ventabot.api", logging.INFO, "x", 1, "hola", None, None
        )
        linea = Formato(color=False, fecha=True).format(registro)
        assert linea[:4].isdigit() and linea[4] == "-", linea

    def test_la_ventana_NO_lleva_la_fecha(self):
        """Camilo está mirando lo que pasa ahora: la fecha es ruido."""
        import logging

        from app.infra.logging import Formato

        registro = logging.LogRecord(
            "ventabot.api", logging.INFO, "x", 1, "hola", None, None
        )
        linea = Formato(color=False).format(registro)
        assert linea[2] == ":" and linea[5] == ":", linea
