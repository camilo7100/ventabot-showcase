"""Auditoría de las conversaciones reales del 04/10 al 12/10 (Camilo, 13/10).

«El flujo está perfecto, no quiero cambiarlo… pero quiero ser un poco menos
insistente y que no se salga de contexto». Lo que salió, con sus textos reales:

- «Gracias por la información» -> «¡Con gusto! 🥰» y debajo, el sistema, «¿De
  cuántas huellitas lo quieres? 🐾» (seis charlas).
- «Estaba averiguando solamente. Muchas gracias» -> «Si algún día te animas, aquí
  estoy» y debajo «¿De cuántas huellitas lo quieres?».
- «Cuando tenga una talla los contactaré de nuevo, gracias» y «apenas lo haga le
  escribo y elijo el modelo» -> le seguían preguntando.
- Un ❤️ a un mensaje -> «¡Anotado! 🫶» + «¿De cuántas huellitas lo quieres?».
- A las 9:37 p. m. -> «¡Hola! Buen día 🌞».
"""

from __future__ import annotations

import pytest

from app.conversacion.asesora import (
    CONFIRMA_EL_RESUMEN,
    OFRECE_DEJARLO_LISTO,
    PIEZA_DE_CADA_ANILLO,
    PREGUNTA_DE_LA_TALLA,
    SALUDO_DE_APERTURA,
    SALUDO_DE_LA_NOCHE,
    SALUDO_DE_LA_TARDE,
    ofrecer_dejarlo_listo,
    pide_ver_el_de,
    saludo_de_apertura,
    solo_reacciona,
)
from app.domain.asesora import Borrador
from app.domain.recordatorios import no_quiere, pospone, solo_agradece
from tests.unit.test_talla_la_confirma_lia import (  # noqa: F401  (la fixture)
    CONV,
    _asesora,
    _guardar,
    _jugada,
    mundo,
)


class TestSoloAgradece:
    @pytest.mark.parametrize(
        "texto",
        [
            "Gracias",
            "Gracias por la información",
            "Vale gracias",
            "Muchas gracias 🥰",
            "ok, mil gracias!!",
            "Gracias, muy amable",
        ],
    )
    def test_si(self, texto):
        assert solo_agradece(texto), texto

    @pytest.mark.parametrize(
        "texto",
        [
            "Gracias, ¿y cuánto vale el de 2?",
            "gracias, lo quiero de 2 huellitas",
            "Gracias. Voy a pensarlo y les confirmo",
            "si por favor",
            "rosa",
        ],
    )
    def test_no(self, texto):
        assert not solo_agradece(texto), texto


class TestEllaRetomaDespues:
    @pytest.mark.parametrize(
        "texto",
        [
            "Perfecto cuando tenga una talla los contactaré de nuevo gracias",
            "Vale apenas lo haga le escribo y eligo el modelo",
            "Aún no he ido apenas la tenga te aviso",
            "en cuanto la mida te escribo",
        ],
    )
    def test_pospone(self, texto):
        assert pospone(texto), texto

    @pytest.mark.parametrize(
        "texto",
        [
            # Yulieth (09/10): pospone SOLO la medida; sigue con lo demás.
            "No la medida te las confirmo en la tarde pero sería uno más grande",
            "te confirmo que es toda rosa",
            "cuando lo tengas me lo mandas?",
        ],
    )
    def test_no_pospone(self, texto):
        assert not pospone(texto), texto

    def test_averiguando_solamente_es_desinteres(self):
        assert no_quiere("Estaba averiguando solamente \n Muchas gracias")
        assert no_quiere("solamente estaba mirando")
        assert not no_quiere("estaba averiguando la talla")


class TestElSaludoSegunLaHora:
    @pytest.mark.parametrize(
        ("hora", "saludo"),
        [
            (5, SALUDO_DE_APERTURA),
            (11, SALUDO_DE_APERTURA),
            (12, SALUDO_DE_LA_TARDE),
            (18, SALUDO_DE_LA_TARDE),
            (19, SALUDO_DE_LA_NOCHE),
            (23, SALUDO_DE_LA_NOCHE),
            (2, SALUDO_DE_LA_NOCHE),
        ],
    )
    def test_la_hora(self, hora, saludo):
        assert saludo_de_apertura(hora) == saludo

    def test_siempre_con_el_nombre_del_negocio(self):
        for s in (SALUDO_DE_APERTURA, SALUDO_DE_LA_TARDE, SALUDO_DE_LA_NOCHE):
            assert s.startswith("¡Hola!") and "Luna Joyas" in s


CORAZON = [{"kind": "reaction", "detalle": "❤️"}]


class TestSoloReacciona:
    def test_un_corazon_no_se_contesta(self):
        assert solo_reacciona(CORAZON, None, PREGUNTA_DE_LA_TALLA)
        assert solo_reacciona(CORAZON, "", "Ya le aviso a Lía 💓")

    def test_un_si_al_resumen_o_al_nombre_si(self):
        assert not solo_reacciona(CORAZON, None, f"…\n{CONFIRMA_EL_RESUMEN}")
        assert not solo_reacciona(CORAZON, None, "¿Lo dejo a nombre de Ana? 🥰")

    def test_con_texto_o_con_foto_si(self):
        assert not solo_reacciona(CORAZON, "sí", PREGUNTA_DE_LA_TALLA)
        foto = [*CORAZON, {"kind": "image"}]
        assert not solo_reacciona(foto, None, PREGUNTA_DE_LA_TALLA)
        assert not solo_reacciona([], None, PREGUNTA_DE_LA_TALLA)


class TestElTurno:
    def test_gracias_sin_la_pregunta_de_relleno(self, mundo):  # noqa: F811
        """Recién presentada, «Gracias por la información»: «¡Con gusto!» y ya."""
        a = _asesora(mundo, _jugada("¡Con gusto! 🥰"))
        _guardar(mundo, Borrador(turnos=1))
        texto = a.ejecutar(CONV, "Gracias por la información").respuesta.texto_plano
        assert texto.strip() == "¡Con gusto! 🥰", texto

    def test_averiguando_solamente_cierra_sin_preguntar(self, mundo):  # noqa: F811
        a = _asesora(
            mundo,
            _jugada("¡Con gusto! 🫶 Si algún día te animas, aquí estoy 💓"),
        )
        _guardar(mundo, Borrador(turnos=1))
        texto = a.ejecutar(
            CONV, "Estaba averiguando solamente\nMuchas gracias"
        ).respuesta.texto_plano
        assert "?" not in texto, texto

    def test_si_la_ia_se_despide_no_va_la_pregunta(self, mundo):  # noqa: F811
        """Charla de prueba del 13/10: «uff está como caro» (sin la palabra que
        busca el filtro). La IA cerró bien; el sistema le pegaba «¿De cuántas…?»."""
        a = _asesora(
            mundo,
            _jugada("¡Gracias por contarme! 🫶 Si algún día te animas, aquí estoy 💓"),
        )
        _guardar(mundo, Borrador(turnos=1))
        texto = a.ejecutar(CONV, "uff está como caro").respuesta.texto_plano
        assert "?" not in texto, texto

    def test_cuando_tenga_la_talla_los_contacto(self, mundo):  # noqa: F811
        """Con cariño y UNA vez: dejar el anillo listo; nada de «¿De cuántas…?»."""
        a = _asesora(
            mundo,
            _jugada("¡Dale! Quedo atenta 😊 ¿De cuántas huellitas lo quieres? 🐾"),
        )
        _guardar(mundo, Borrador(turnos=2))
        texto = a.ejecutar(
            CONV, "Perfecto cuando tenga una talla los contactaré de nuevo gracias"
        ).respuesta.texto_plano
        assert "dejemos tu anillo personalizado listo" in texto, texto
        assert "la talla y el abono" in texto and "foto de la medida" in texto, texto
        assert "huellitas lo quieres" not in texto, texto


class TestDejarloListo:
    """Camilo, 13/10, la charla real del 11/10: «Vale apenas lo haga le escribo y
    eligo el modelo» -> «¡Dale! Quedo atenta 🙌 ¿De cuántas huellitas te gustaría
    el anillo?». Lo que quería: aceptarlo bonito y ofrecerle dejar el anillo listo
    para que solo queden la talla y el abono; y si no, quedar atenta."""

    REAL = "Vale apenas lo haga le escribo y eligo el modelo"

    def test_se_ofrece_cuando_falta_disenar(self):
        oferta = ofrecer_dejarlo_listo(Borrador(turnos=2), self.REAL)
        assert oferta.startswith("¡Claro, sin afán! 🫶")
        assert "quedarían pendientes la talla y el abono" in oferta
        assert oferta.count("?") == 1

    def test_si_habla_de_la_talla_queda_atenta_a_la_medida(self):
        oferta = ofrecer_dejarlo_listo(Borrador(turnos=2), "apenas me mida te escribo")
        assert "foto de la medida" in oferta

    def test_con_la_guia_recien_mandada_tambien(self):
        """El caso real: le llegó la guía y «Vale apenas lo haga le escribo»."""
        b = Borrador(turnos=2, mostrado_en={"MOSTRAR_GUIA_TALLA": 2})
        assert "foto de la medida" in ofrecer_dejarlo_listo(b, self.REAL)
        assert "para cuando quieras" in ofrecer_dejarlo_listo(
            Borrador(turnos=2), self.REAL
        )

    def test_con_la_talla_ya_dada_solo_queda_el_abono(self):
        oferta = ofrecer_dejarlo_listo(Borrador(turnos=2, talla=7.0), "lo pienso")
        assert "solo quedaría pendiente el abono" in oferta, oferta

    def test_a_mitad_del_diseno_se_sigue_sin_pedir_permiso(self):
        """Ya escogió 1 huellita y el color; «luego te paso la foto del anillo con
        la regla»: se acepta y se sigue con el grabado (prueba del 13/10)."""
        from app.domain.asesora import HuellitaDelBorrador
        from app.domain.personalizacion import ColorCircon as C

        b = Borrador(
            turnos=4,
            cantidad=1,
            huellitas=[
                HuellitaDelBorrador(corazon=C.VERDE_ESMERALDA, dedos=C.VERDE_ESMERALDA)
            ],
        )
        oferta = ofrecer_dejarlo_listo(b, "luego te paso la foto del anillo con la regla")
        assert oferta.startswith(
            "¡Claro, sin afán! 🫶 Mientras tanto vamos dejando listo"
        )
        assert "grab" in oferta and "te gustaría que" not in oferta, oferta

    def test_una_sola_vez(self):
        b = Borrador(turnos=3, mostrado_en={OFRECE_DEJARLO_LISTO: 2})
        assert ofrecer_dejarlo_listo(b, self.REAL) == ""

    @pytest.mark.parametrize(
        "texto",
        [
            "no me gusta la plata, después miro",
            "¿y luego cómo pago?",
            "escríbeme el otro mes",
            "rosa",
        ],
    )
    def test_cuando_no_toca(self, texto):
        assert ofrecer_dejarlo_listo(Borrador(turnos=2), texto) == ""

    def test_con_el_diseno_completo_no(self):
        assert ofrecer_dejarlo_listo(_disenado(), "mañana le consigno") == ""

    def test_el_otro_mes_si(self):
        assert ofrecer_dejarlo_listo(
            Borrador(turnos=2), "Lo voy a dejar pasar quizás para el próximo mes"
        )

    def test_en_el_turno_y_la_segunda_vez_ya_no(self, mundo):  # noqa: F811
        a = _asesora(
            mundo,
            _jugada(
                "¡Dale! Quedo atenta 🙌 ¿De cuántas huellitas te gustaría el anillo?"
            ),
            _jugada("¡Dale! 🫶 Quedo atenta"),
        )
        _guardar(mundo, Borrador(turnos=2))
        primera = a.ejecutar(CONV, self.REAL).respuesta.texto_plano
        assert "dejemos tu anillo personalizado listo" in primera, primera
        segunda = a.ejecutar(CONV, "no, después lo hago").respuesta.texto_plano
        assert "dejemos tu anillo" not in segunda and "?" not in segunda, segunda


def _disenado() -> Borrador:
    from app.domain.asesora import HuellitaDelBorrador
    from app.domain.personalizacion import ColorCircon as C

    return Borrador(
        turnos=6,
        cantidad=1,
        talla=7.0,
        huellitas=[HuellitaDelBorrador(corazon=C.ROSADO, dedos=C.ROSADO)],
        grabado=["Luna"],
        nombre_clienta="Ana Gómez",
    )


class TestVerUnoSolo:
    @pytest.mark.parametrize(
        ("texto", "cual"),
        [
            ("me muestras como es el de 2 huellitas?", 2),
            ("¿Cómo es el de una huellita?", 1),
            ("quiero ver el de tres", 3),
            ("mándame foto del de 1 huellita porfa", 1),
        ],
    )
    def test_cual(self, texto, cual):
        assert pide_ver_el_de(texto) == cual

    @pytest.mark.parametrize(
        "texto",
        [
            "lo quiero de 2 huellitas",
            "Me los puede mostrar por separado",
            "muéstrame el de 1 y el de 2",
            "¿qué precio tiene?",
        ],
    )
    def test_no(self, texto):
        assert pide_ver_el_de(texto) is None

    def test_cada_pieza_es_la_de_verdad(self):
        """Revisado a ojo (13/10): video 1 = 2 huellitas, video 2 = 1, foto = 3."""
        assert PIEZA_DE_CADA_ANILLO[2] == ("presentacion_video_1", True)
        assert PIEZA_DE_CADA_ANILLO[1] == ("presentacion_video_2", True)
        assert PIEZA_DE_CADA_ANILLO[3] == ("presentacion_anillo", False)

    def test_en_el_turno_va_solo_esa(self, mundo):  # noqa: F811
        from app.domain.asesora import AccionAsesora

        a = _asesora(mundo, _jugada("¡Claro! Este es el de 2 huellitas 🐾"))
        _guardar(
            mundo,
            Borrador(turnos=1, mostrado_en={AccionAsesora.MOSTRAR_PRECIOS.value: 1}),
        )
        piezas = a.ejecutar(CONV, "me muestras el de 2 huellitas?").respuesta.piezas
        medios = [p.imagen for p in piezas if p.imagen]
        assert medios == ["presentacion_video_1"], medios


class TestElPrimerMensajeConSuPedido:
    @pytest.mark.parametrize(
        "texto",
        [
            "Hola, quiero un anillo de una huellita talla 6, todo rosado, que diga Lola",
            "quiero el de 2 huellitas",
            "lo quiero todo negro",
        ],
    )
    def test_lo_lee_el_modelo(self, texto):
        from app.conversacion.asesora import trae_datos_del_pedido

        assert trae_datos_del_pedido(texto)

    @pytest.mark.parametrize(
        "texto",
        [
            "¡Hola! Quiero más información",
            "precio?",
            "Hola quiero uno",
            "Buenas noches",
            "¡Hola! Cuánto vale un anillo con dos huellitas",
        ],
    )
    def test_la_apertura_de_siempre(self, texto):
        from app.conversacion.asesora import trae_datos_del_pedido

        assert not trae_datos_del_pedido(texto)


class TestElRegalo:
    @pytest.mark.parametrize(
        "texto",
        [
            "Hola buenas, es para regalarle a mi hija pero ella no vive conmigo",
            "es un regalo sorpresa",
            "Es para mi novia",
        ],
    )
    def test_si(self, texto):
        from app.conversacion.asesora import es_para_otra_persona

        assert es_para_otra_persona(texto)

    @pytest.mark.parametrize(
        "texto", ["Me regalas la guía", "regálame la cuenta", "es para mí"]
    )
    def test_no(self, texto):
        from app.conversacion.asesora import es_para_otra_persona

        assert not es_para_otra_persona(texto)


class TestLaFotoQueMandaDespues:
    def test_es_la_de_la_medida(self):
        from app.domain.asesora import lo_deja_para_despues

        ultimo = "¿Qué nombre completo pongo para el pedido?"
        assert lo_deja_para_despues(
            "le pido la foto a ella y ya te la mando", ultimo
        ) == ["talla"]

    def test_la_del_pago_no(self):
        from app.domain.asesora import lo_deja_para_despues

        assert "talla" not in lo_deja_para_despues(
            "ahorita te mando la foto del comprobante", "¿Me compartes el comprobante?"
        )


class TestLaReaccionEnElContenedor:
    def test_no_se_contesta_y_queda_en_chatwoot(self, monkeypatch, tmp_path):
        import app.infra.container as contenedor
        from app.adapters.channels.whatsapp import WhatsAppAdapter
        from app.infra.settings import get_settings
        from tests.unit.test_adjuntos_visibles import _msg, _uno

        monkeypatch.setenv("REPOSITORY_BACKEND", "memory")
        monkeypatch.setenv("CHANNEL_BACKEND", "console")
        monkeypatch.setenv("LLM_BACKEND", "fake")
        monkeypatch.setenv("SQLITE_PATH", str(tmp_path / "t.db"))
        get_settings.cache_clear()
        contenedor._singleton = None
        try:
            c = contenedor.get_container()
            canal = WhatsAppAdapter(
                phone_number_id="p", access_token="t", app_secret="s", verify_token="v"
            )
            m = _uno(canal, _msg("reaction", {"message_id": "wamid.x", "emoji": "❤️"}))
            # Primer mensaje de la charla: va la apertura, como siempre.
            assert not c._solo_reacciona(m)
            c.bot._mundo.anotar_mensaje_de_humano(m.conversation_id, PREGUNTA_DE_LA_TALLA)
            assert c._solo_reacciona(m)
            assert c.procesar_mensaje(m) == []
            c.bot._mundo.anotar_mensaje_de_humano(m.conversation_id, CONFIRMA_EL_RESUMEN)
            assert not c._solo_reacciona(m)
        finally:
            get_settings.cache_clear()
            contenedor._singleton = None
