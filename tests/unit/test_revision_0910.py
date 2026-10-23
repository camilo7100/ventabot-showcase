"""La revisión del 09/10, con buena y mala ortografía, como escribe la gente.

1. Dónde estamos: Floridablanca, sin punto físico, solo el CONJUNTO para recoger
   (nunca la dirección, la torre ni el apartamento: es la casa de Lía).
2. La cadena lleva UNA huellita, siempre, y el sistema lo dice.
3. «El otro mes»: se acepta y se cierra, sin insistir ni prometer escribirle,
   salvo que ella lo pida.
4. Las cuatro situaciones: no responde, responde a medias, rechaza una
   pregunta, pospone.
5. Una pregunta útil a la vez.
"""

from __future__ import annotations

import pytest

from app.conversacion.asesora import CADENA_CON_UNA, lo_que_falta_al_pagar
from app.domain.asesora import (
    AccionAsesora,
    Borrador,
    HuellitaDelBorrador,
    aplicar,
    pide_cadena_con_varias,
    sin_promesas_de_escribir,
    vigilar,
)
from app.domain.faq import (
    PUNTO_DE_RECOGIDA,
    RESPUESTAS,
    UBICACION,
    Pregunta,
    pregunta_por_la_ubicacion,
)
from app.domain.personalizacion import CADENA, HUELLITAS_DE_LA_CADENA
from app.domain.personalizacion import ColorCircon as C
from app.domain.recordatorios import no_quiere, pide_que_le_escriban, pospone
from tests.unit.test_talla_la_confirma_lia import (  # noqa: F401  (la fixture)
    CONV,
    _asesora,
    _guardar,
    _jugada,
    mundo,
)

# ════════════════════════════════════════════════════════════════════════════
# 1. DÓNDE ESTAMOS
# ════════════════════════════════════════════════════════════════════════════


class TestDondeEstamos:
    @pytest.mark.parametrize(
        "texto",
        [
            "Dónde están ubicados?",
            "donde estan ubicadas",
            "dnd qdan?",
            "Donde quedan",
            "tienen tienda fisica?",
            "Tienen local?",
            "hay punto fisico?",
            "de donde son?",
            "ubicacion porfa",
            "ubicasion?",
            "En que parte estan?",
            "donde queda la tienda",
            "se puede visitar el taller?",
            "cual es la direccion de ustedes",
        ],
    )
    def test_pregunta_donde_estamos(self, texto):
        assert pregunta_por_la_ubicacion(texto), texto

    @pytest.mark.parametrize(
        "texto",
        [
            "donde esta mi anillo?",
            "mi direccion es calle 45 #12-30",
            "vivo en floridablanca",
            "puedo pasar la foto?",
            "donde tienen las cuentas?",
            "envialo a bucaramanga",
            "el anillo de 2 huellitas",
        ],
    )
    def test_lo_que_no_es_preguntar_donde_estamos(self, texto):
        assert not pregunta_por_la_ubicacion(texto), texto

    def test_la_respuesta_cuida_la_casa_de_lia(self):
        assert "Floridablanca" in UBICACION and "punto físico" in UBICACION
        assert "Conjunto Ejemplo" in UBICACION
        for prohibido in ("Torre", "torre", "apto", "301", "21-462", "Anillo Vial"):
            assert prohibido not in UBICACION, prohibido
            assert prohibido not in PUNTO_DE_RECOGIDA, prohibido
        assert RESPUESTAS[Pregunta.UBICACION] == UBICACION

    def test_el_domicilio_en_bucaramanga_sin_valor_exacto(self):
        assert "Bucaramanga" in UBICACION and "$" not in UBICACION
        assert "depende del domicilio" in UBICACION

    @pytest.mark.parametrize(
        "frase",
        [
            "Estamos en Anillo Vial #21-462 Km 1, Floridablanca.",
            "Lo recoges en Conjunto Ejemplo, Torre 1 apto 301.",
            "Es en la torre 1 apto 301 🥰",
        ],
    )
    def test_vigilar_borra_la_direccion_de_la_casa(self, frase):
        limpio, problemas = vigilar(f"¡Claro! 💓 {frase}", set())
        assert "301" not in limpio and "21-462" not in limpio
        assert problemas and limpio.startswith("¡Claro!")

    def test_la_direccion_de_una_clienta_si_se_repite(self):
        limpio, problemas = vigilar(
            "Te lo envío a Calle 45 #12-30 apto 301, sobre el Anillo Vial 🚚", set()
        )
        assert "apto 301" in limpio and not problemas

    def test_el_turno_contesta_sin_gastar_el_modelo(self, mundo):  # noqa: F811
        a = _asesora(mundo)  # sin jugadas: si llamara al modelo, fallaría
        turno = a.ejecutar(CONV, "hola donde estan ubicados?")
        texto = turno.respuesta.texto_plano
        assert "Floridablanca" in texto and "301" not in texto
        assert turno.capa == "fija"


# ════════════════════════════════════════════════════════════════════════════
# 2. LA CADENA: UNA HUELLITA
# ════════════════════════════════════════════════════════════════════════════


class TestLaCadenaLlevaUna:
    def test_es_una_y_esta_en_el_codigo(self):
        assert HUELLITAS_DE_LA_CADENA == 1

    @pytest.mark.parametrize(
        "texto",
        [
            "La cadena puede ser con 2 huellitas?",
            "kiero la cadenita d dos huellitas",
            "cadena con varias patitas se puede?",
            "y el collar con mas de una huella?",
            "la cadena con 3 huellas de mis perritos",
        ],
    )
    def test_detecta_que_la_pide_con_varias(self, texto):
        assert pide_cadena_con_varias(texto), texto

    @pytest.mark.parametrize(
        "texto", ["la cadena cuanto vale?", "anillo de 2 huellitas", "quiero la cadena"]
    )
    def test_lo_que_no_es_pedirla_con_varias(self, texto):
        assert not pide_cadena_con_varias(texto), texto

    def test_el_sistema_no_anota_dos_en_la_cadena(self):
        from app.domain.asesora import CambiosDelBorrador

        b = Borrador(turnos=3, pieza=CADENA)
        nuevo, rechazos = aplicar(b, CambiosDelBorrador(cantidad_huellitas=2))
        assert nuevo.cantidad == 1
        assert any("UNA sola huellita" in r for r in rechazos)

    def test_el_mensaje_de_la_cadena_lo_dice(self):
        from app.conversacion.asesora import MENSAJE_DE_LA_CADENA

        assert "Lleva una huellita" in MENSAJE_DE_LA_CADENA
        assert "una sola huellita" in CADENA_CON_UNA

    def test_si_la_pide_con_dos_se_lo_dice_el_sistema(self, mundo):  # noqa: F811
        a = _asesora(mundo, _jugada("¡Claro! 💗", AccionAsesora.MOSTRAR_CADENA))
        _guardar(mundo, Borrador(turnos=2))
        texto = a.ejecutar(CONV, "tienen cadena con dos huellitas?").respuesta.texto_plano
        assert CADENA_CON_UNA in texto
        assert texto.index(CADENA_CON_UNA) < texto.index("cadenita personalizada")


# ════════════════════════════════════════════════════════════════════════════
# 3 y 4. LO DEJA PARA DESPUÉS / LAS CUATRO SITUACIONES
# ════════════════════════════════════════════════════════════════════════════


class TestLoDejaParaDespues:
    @pytest.mark.parametrize(
        "texto",
        [
            "el otro mes",
            "Mejor el otro mes 😊",
            "pal otro mez",
            "el mes q viene lo hago",
            "a fin de mes te consigno",
            "para diciembre",
            "el mes entrante",
            "lo voy a dejar pasar",
            "mañana le consigno",
            "manana te escribo",
            "cuando me paguen",
            "ahorita no me queda facil",
        ],
    )
    def test_pospone(self, texto):
        assert pospone(texto), texto

    @pytest.mark.parametrize(
        "texto",
        [
            "no quiero grabado",
            "sin grabado",
            "te confirmo que es toda rosa",
            "rosa",
            "Laura Gómez",
        ],
    )
    def test_no_es_posponer(self, texto):
        """Rechazar UNA pregunta (el grabado) o contestar no es posponer."""
        assert not pospone(texto), texto

    @pytest.mark.parametrize("texto", ["el otro mes", "pal otro mez", "a fin de mes"])
    def test_el_otro_mes_no_lleva_recordatorios(self, texto):
        assert no_quiere(texto)

    @pytest.mark.parametrize(
        "texto",
        [
            "escribeme el otro mes",
            "me recuerdas a fin de mes porfa",
            "recuérdame la otra quincena",
            "me avisas el mes q viene",
        ],
    )
    def test_ella_pide_que_le_escriban(self, texto):
        assert pide_que_le_escriban(texto), texto

    def test_si_no_lo_pide_no_se_le_promete(self):
        assert not pide_que_le_escriban("el otro mes")

    @pytest.mark.parametrize(
        "texto",
        [
            "¡Dale! 🫶 Te escribo el próximo mes para recordarte 💗",
            "Listo, te programo un recordatorio para fin de mes",
            "Perfecto, te aviso más adelante 🐾",
        ],
    )
    def test_quita_las_promesas_de_escribirle(self, texto):
        limpio = sin_promesas_de_escribir(texto)
        for palabra in ("escribo", "recordatorio", "aviso"):
            assert palabra not in limpio, limpio

    def test_lo_que_no_es_promesa_se_queda(self):
        assert (
            sin_promesas_de_escribir("¡Dale! Quedo atenta 🫶") == "¡Dale! Quedo atenta 🫶"
        )

    def test_el_otro_mes_cierra_sin_preguntas_ni_promesas(self, mundo):  # noqa: F811
        a = _asesora(
            mundo,
            _jugada(
                "¡Dale! Te escribo el próximo mes para recordarte 💗 ¿Te ayudo con algo "
                "más mientras tanto?"
            ),
        )
        _guardar(
            mundo,
            Borrador(
                turnos=4,
                cantidad=1,
                huellitas=[HuellitaDelBorrador(corazon=C.ROSADO, dedos=C.ROSADO)],
            ),
        )
        texto = a.ejecutar(CONV, "mejor el otro mes 😊").respuesta.texto_plano
        # Desde el 13/10 (Camilo): con cariño y UNA vez, se le ofrece dejar el
        # anillo listo; nada más (ni «¿te ayudo con algo más?»).
        assert "dejemos tu anillo personalizado listo" in texto, texto
        assert texto.count("?") == 1, texto
        assert "escribo" not in texto and "recordar" not in texto, texto


# ════════════════════════════════════════════════════════════════════════════
# 5. UNA PREGUNTA ÚTIL A LA VEZ
# ════════════════════════════════════════════════════════════════════════════


class TestUnaALaVez:
    def test_debajo_de_las_cuentas_una_sola_cosa(self):
        texto = lo_que_falta_al_pagar(
            ["talla", "grabado", "nombre completo"], Borrador(turnos=3)
        )
        assert texto.count("?") == 1
        assert "tu talla" in texto and "grabar" not in texto and "nombre" not in texto
