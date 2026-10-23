"""No acosar (Camilo, 09/10, la charla de Yulieth).

Ella: «No la medida te las confirmo en la tarde pero sería uno más grande que el
otro». El bot se la volvió a pedir cuatro veces, a veces sin «¿?» («Me falta la
medida del primer anillo; cuando puedas, mándame la foto con la regla»). Y lo que
dijo para los dos anillos («cada anillo con una sola huella», «Khalifa en los
dos», «una lila y la otra fucsia») se lo volvió a preguntar en el segundo.

Las reglas:
- lo que dice que manda DESPUÉS no se le pide más en la charla; UN recordatorio
  sobre eso y ya;
- lo que no contesta se le pide UNA vez más; después, el recordatorio;
- lo que dijo para todos los anillos queda en cada uno.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.domain import recordatorios as r
from app.domain.asesora import (
    VECES_QUE_SE_PIDE,
    AnilloListo,
    Borrador,
    HuellitaDelBorrador,
    al_dia_lo_que_se_pide,
    cantidad_de_todos,
    colores_por_anillo,
    contar_lo_pedido,
    grabado_para_todos,
    lo_deja_para_despues,
    pide,
    que_no_se_pide,
    sin_pedir,
)
from app.domain.personalizacion import ColorCircon as C
from tests.unit.test_talla_la_confirma_lia import (  # noqa: F401  (la fixture)
    CONV,
    _asesora,
    _guardar,
    _jugada,
    mundo,
)

YULIETH = "No la medida te las confirmo en la tarde pero sería uno más grande que el otro"


def _dos_anillos(**kw) -> Borrador:
    base = dict(
        turnos=6,
        cantidad=1,
        talla_exige_lia=True,
        por_empezar=[AnilloListo(cantidad=1)],
    )
    return Borrador(**{**base, **kw})


# ════════════════════════════════════════════════════════════════════════════
# LO QUE DICE QUE MANDA DESPUÉS
# ════════════════════════════════════════════════════════════════════════════


class TestLoDejaParaDespues:
    @pytest.mark.parametrize(
        "texto",
        [
            YULIETH,
            "la medida te la mando mas tarde",
            "cuando la mida te aviso",
            "despues te digo la talla",
            "todavia no tengo la medida",
            "ahorita no puedo medir, luego te la paso",
            "la talla en la noche te la confirmo",
        ],
    )
    def test_la_talla_despues(self, texto):
        assert lo_deja_para_despues(texto) == ["talla"], texto

    def test_sin_nombrarla_es_lo_que_le_acababan_de_pedir(self):
        ultimo = "¿Me mandas la foto con la regla cuando puedas? 📏"
        assert lo_deja_para_despues("te confirmo en la tarde", ultimo) == ["talla"]
        ultimo = "¿Qué nombre quieres grabar en el aro? 🐾"
        assert lo_deja_para_despues("despues te digo", ultimo) == ["grabado"]

    @pytest.mark.parametrize(
        "texto",
        ["te confirmo que es toda rosa", "talla 7", "lila", "si, asi esta bien"],
    )
    def test_lo_que_no_es_dejarlo_despues(self, texto):
        assert lo_deja_para_despues(texto, "¿Qué talla eres?") == [], texto


class TestQueSePide:
    @pytest.mark.parametrize(
        "texto",
        [
            "¡Listo, Yulieth! 🫶 Me falta la medida del primer anillo; cuando puedas, "
            "mándame la foto con la regla 😊",
            "¿Me mandas la foto con la regla del primer anillo cuando puedas? 💍",
            "¿qué talla usas en el primero?",
            "Cuando tengas la medida de ese anillo, me mandas la foto con la regla",
        ],
    )
    def test_pedir_la_talla_con_o_sin_signos(self, texto):
        assert pide(texto, "talla")

    @pytest.mark.parametrize(
        "texto",
        ["Te comparto la guía para medirla 😊", "📏 Se fabrica en tu medida."],
    )
    def test_nombrarla_no_es_pedirla(self, texto):
        assert not pide(texto, "talla")

    def test_sin_pedir_quita_solo_eso(self):
        texto = (
            "¡Perfecto! «Khalifa» también queda para el segundo 🫶 Cuando tengas la "
            "medida de ese anillo, me mandas la foto con la regla; ¿qué talla usas "
            "en el primero?"
        )
        limpio = sin_pedir(texto, {"talla"})
        assert limpio == "¡Perfecto! «Khalifa» también queda para el segundo 🫶"


class TestLaCuenta:
    def test_lo_que_dejo_para_despues_no_se_pide(self):
        b = _dos_anillos()
        al_dia_lo_que_se_pide(b, YULIETH, "¿Son de la misma talla? 💍")
        assert "talla" in b.lo_manda_despues
        assert "talla" in que_no_se_pide(b)

    def test_si_vuelve_a_hablar_de_la_talla_se_suelta(self):
        b = _dos_anillos(lo_manda_despues={"talla": 3})
        al_dia_lo_que_se_pide(b, "¿cómo mido el anillo?", "")
        assert "talla" not in b.lo_manda_despues

    def test_lo_que_no_contesta_se_pide_una_vez_mas_y_ya(self):
        b = _dos_anillos()
        pedido = "¿Qué color quieres para la huellita? 🎨"
        for _ in range(VECES_QUE_SE_PIDE):
            assert "colores" not in que_no_se_pide(b)
            contar_lo_pedido(b, pedido)
            # Ella contesta otra cosa (no los colores).
            al_dia_lo_que_se_pide(b, "y cuanto se demora?", pedido)
        assert "colores" in que_no_se_pide(b)

    def test_si_lo_da_se_borra_la_cuenta(self):
        b = _dos_anillos(veces_pedido={"colores": 2})
        b.huellitas = [HuellitaDelBorrador(corazon=C.LILA, dedos=C.LILA)]
        b.por_empezar[0].huellitas = [HuellitaDelBorrador(corazon=C.LILA, dedos=C.LILA)]
        al_dia_lo_que_se_pide(b, "lila", "")
        assert "colores" not in b.veces_pedido


class TestElTurnoDeYulieth:
    def test_despues_de_decir_que_la_manda_en_la_tarde_no_se_la_piden(
        self,
        mundo,  # noqa: F811
    ):
        a = _asesora(
            mundo,
            _jugada(
                "¡Dale! Entonces serán de tallas diferentes 😊 Me falta la medida del "
                "primer anillo; cuando puedas, mándame la foto con la regla 😊 ¿Qué "
                "color quieres para la huellita del primero?"
            ),
            _jugada(
                "¡Lila queda lindo! 💜 ¿Me mandas la foto con la regla del primer "
                "anillo cuando puedas? 💍"
            ),
        )
        _guardar(mundo, _dos_anillos())
        primero = a.ejecutar(CONV, YULIETH).respuesta.texto_plano
        assert "regla" not in primero and "medida" not in primero, primero
        assert "color" in primero
        segundo = a.ejecutar(CONV, "lila").respuesta.texto_plano
        assert "regla" not in segundo and "medida" not in segundo, segundo


# ════════════════════════════════════════════════════════════════════════════
# LO QUE DIJO PARA TODOS LOS ANILLOS
# ════════════════════════════════════════════════════════════════════════════


class TestParaTodos:
    @pytest.mark.parametrize(
        "texto",
        [
            "Serían dos anillos cada anillo con una sola huella",
            "los dos de una huellita",
            "ambos con 1 huellita",
            "cada uno de una",
        ],
    )
    def test_la_cantidad_de_todos(self, texto):
        assert cantidad_de_todos(texto) == 1, texto

    @pytest.mark.parametrize(
        "texto",
        ["En los dos anillos\nKhalifa", "para ambos Khalifa", "el mismo nombre"],
    )
    def test_el_grabado_de_todos(self, texto):
        assert grabado_para_todos(texto), texto

    def test_un_color_por_anillo(self):
        b = _dos_anillos()
        assert colores_por_anillo(b, "Una lila y la otra fucsia") == [
            (0, C.LILA),
            (1, C.FUCSIA),
        ]

    def test_si_el_primero_ya_lo_tiene_solo_el_segundo(self):
        b = _dos_anillos(huellitas=[HuellitaDelBorrador(corazon=C.LILA, dedos=C.LILA)])
        assert colores_por_anillo(b, "Una lila y la otra fucsia") == [(1, C.FUCSIA)]

    def test_con_un_solo_anillo_no_aplica(self):
        assert (
            colores_por_anillo(
                Borrador(turnos=3, cantidad=1), "una lila y la otra fucsia"
            )
            == []
        )


# ════════════════════════════════════════════════════════════════════════════
# EL RECORDATORIO: UNO SOBRE ESO, Y YA
# ════════════════════════════════════════════════════════════════════════════

COL = r.COLOMBIA


class TestElRecordatorio:
    def test_la_etapa_es_lo_que_dejo_para_despues(self):
        b = _dos_anillos(lo_manda_despues={"talla": 5})
        assert r.etapa(b) == "despues_talla"

    def test_ya_recordado_no_lleva_otro(self):
        b = _dos_anillos(lo_manda_despues={"talla": 5}, recordado_despues=["talla"])
        assert r.etapa(b) is None

    def test_el_texto_es_sobre_eso(self):
        t = r.texto(
            1,
            "despues_talla",
            nombre="Yulieth",
            pieza="pedido",
            hoy=datetime.now(COL).date(),
        )
        assert "talla que me ibas a confirmar" in t and t.count("?") == 1

    def test_uno_solo_y_sin_plantilla(self):
        ella = datetime.now(COL).replace(hour=14, minute=0, second=0, microsecond=0)
        bot = ella + timedelta(minutes=1)
        primero = r.siguiente(
            etapa_de_ella="despues_talla",
            ultimo_de_ella=ella.astimezone(UTC),
            ultimo_del_bot=bot.astimezone(UTC),
            enviados={},
            ahora=ella.astimezone(UTC),
            con_plantilla=True,
        )
        assert primero is not None and primero.numero == 1
        despues = r.siguiente(
            etapa_de_ella="despues_talla",
            ultimo_de_ella=ella.astimezone(UTC),
            ultimo_del_bot=bot.astimezone(UTC),
            enviados={1: primero.cuando},
            ahora=primero.cuando + timedelta(hours=2),
            con_plantilla=True,
        )
        assert despues is None, "un solo recordatorio, sin el segundo ni la plantilla"

    def test_todas_las_etapas_tienen_su_texto(self):
        for etapa in r.ETAPAS:
            assert etapa in r.PRIMEROS, etapa


class TestDespuesDePagar:
    """12/10 (prueba de verdad): pagó con el pedido a medias. Lo que falta es para
    pasar su pedido al taller: se le pide aunque ya se le haya pedido dos veces."""

    def test_el_tope_de_dos_veces_no_aplica(self):
        b = _dos_anillos(veces_pedido={"colores": 2}, pagado_sin_pedido=True)
        assert "colores" not in que_no_se_pide(b)

    def test_lo_que_dijo_que_manda_despues_se_sigue_respetando(self):
        b = _dos_anillos(lo_manda_despues={"talla": 3}, pagado_sin_pedido=True)
        assert "talla" in que_no_se_pide(b)


class TestLaTallaSoloSiElla:
    """12/10 (prueba de verdad): a «el de ella todo celeste» la IA a veces le
    volvía a anotar al anillo de la hermana la talla del otro. La talla solo cambia
    si ELLA habla de una talla en ese mensaje."""

    @pytest.mark.parametrize(
        "texto",
        ["talla 8", "creo que soy siete", "Gamma seis", "5 y medio", "la medida es 2 cm"],
    )
    def test_habla_de_una_talla(self, texto):
        from app.conversacion.asesora import _HABLA_DE_UNA_TALLA

        assert _HABLA_DE_UNA_TALLA.search(texto)

    @pytest.mark.parametrize(
        "texto", ["el de ella todo celeste", "el de ella dice Kira", "Mónica Herrera"]
    )
    def test_no_habla_de_talla(self, texto):
        from app.conversacion.asesora import _HABLA_DE_UNA_TALLA

        assert not _HABLA_DE_UNA_TALLA.search(texto)

    def test_la_ia_no_le_cambia_la_talla(self, mundo):  # noqa: F811
        a = _asesora(mundo, _jugada("¡Todo celeste! 🩵", talla=6.0))
        _guardar(mundo, _dos_anillos(talla=6.0))
        a.ejecutar(CONV, "el de ella todo celeste")
        b = Borrador.model_validate(mundo.contexto(CONV).borrador)
        assert [v.talla for v in b.vistas()][1] is None


class TestLosAnillosQueDice:
    """12/10 (prueba de verdad): si ella DICE que compra varios, se crean aunque
    la IA tarde en marcar «otro anillo»; si no, lo del segundo quedaba en el
    primero o se perdía."""

    @pytest.mark.parametrize(
        ("texto", "n"),
        [
            ("Hola! quiero dos anillos, uno para mí y otro para mi hermana", 2),
            ("Serían dos anillos cada anillo con una sola huella", 2),
            ("si mando a hacer dos anillos de diferentes medidas que valor tendría?", 2),
            ("necesito 3 anillos", 3),
        ],
    )
    def test_cuantos_compra(self, texto, n):
        from app.domain.asesora import anillos_que_pide

        assert anillos_que_pide(texto) == n

    @pytest.mark.parametrize(
        "texto",
        ["los dos anillos quedan lindos", "cuánto valen dos anillos?", "un anillo"],
    )
    def test_nombrarlos_no_es_comprarlos(self, texto):
        from app.domain.asesora import anillos_que_pide

        assert anillos_que_pide(texto) is None

    def test_el_turno_los_crea_una_sola_vez(self, mundo):  # noqa: F811
        a = _asesora(mundo, _jugada("¡Listo! 🐾"), _jugada("¡Dale! 🫶"))
        _guardar(mundo, Borrador(turnos=3))
        a.ejecutar(CONV, "Serían dos anillos cada anillo con una sola huella")
        b = Borrador.model_validate(mundo.contexto(CONV).borrador)
        assert b.anillos_total == 2
        assert [v.cantidad for v in b.vistas()] == [1, 1]
