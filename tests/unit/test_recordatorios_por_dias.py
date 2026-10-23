"""Los recordatorios POR DÍAS (Camilo, 13/10, con el diseño de marketing).

S1 vio los precios y no volvió · S2 se frenó en talla o cantidad · S3 ya
escogió algo · S4 pedido sin abono. El día 1 dentro de sus 24 h (texto libre,
con foto y botones); los otros con plantilla. Entre 10 a. m. y 7 p. m.
"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta

import pytest

from app.domain import recordatorios_por_dias as d
from app.domain.asesora import Borrador, HuellitaDelBorrador
from app.domain.personalizacion import ColorCircon as C
from app.domain.recordatorios import COLOMBIA as COL


def _a_las(hora: int, minuto: int = 0, dias: int = 0) -> datetime:
    return datetime(2026, 10, 14, hora, minuto, tzinfo=COL) + timedelta(days=dias)


def _paso(seg="S2", etapa="talla_guia", ella=None, enviados=None, texto="", **kw):
    ella = ella or _a_las(15)
    return d.siguiente(
        segmento_de_ella=seg,
        etapa_de_ella=etapa,
        ultimo_de_ella=ella,
        ultimo_del_bot=ella + timedelta(minutes=1),
        enviados=enviados or {},
        texto_de_ella=texto,
        ahora=kw.pop("ahora", ella),
        **kw,
    )


def _todos(seg="S2", etapa="talla_guia", ella=None, texto="", **kw):
    """Los que le llegarían si nunca contesta, en orden."""
    ella = ella or _a_las(15)
    enviados: dict[int, datetime] = {}
    pasos, ahora = [], ella
    for _ in range(5):
        p = _paso(seg, etapa, ella, dict(enviados), texto, ahora=ahora, **kw)
        if p is None:
            break
        pasos.append(p)
        enviados[p.numero] = p.cuando
        ahora = p.cuando
    return pasos


class TestLosSegmentos:
    def test_s4_pedido_sin_abono(self):
        assert d.segmento("abono", Borrador(turnos=8), 6) == "S4"

    def test_s3_ya_escogio_algo(self):
        colores = Borrador(
            turnos=5, cantidad=1, huellitas=[HuellitaDelBorrador(corazon=C.ROSADO)]
        )
        assert d.segmento("grabado", colores, 4) == "S3"
        assert d.segmento("colores", Borrador(turnos=4, talla=7.0), 3) == "S3"

    def test_s2_se_freno_en_la_talla_o_la_cantidad(self):
        assert d.segmento("talla_guia", Borrador(turnos=3, cantidad=1), 3) == "S2"
        assert d.segmento("cantidad", Borrador(turnos=2), 2) == "S2"

    def test_s1_un_solo_mensaje(self):
        assert d.segmento("consulta", Borrador(turnos=1), 1) == "S1"
        assert d.segmento("consulta", None, 1) == "S1"

    def test_si_no_le_toca_ninguno(self):
        assert d.segmento(None, Borrador(), 3) is None


class TestCuando:
    @pytest.mark.parametrize(
        ("ella", "esperado"),
        [
            (_a_las(21), _a_las(17, dias=1)),  # 20 h después
            (_a_las(15), _a_las(11, dias=1)),
            (_a_las(13), _a_las(10, dias=1)),  # 9 a. m. -> a las 10
            (_a_las(10, 15), _a_las(19)),  # a las 10 del otro día ya no cabe
            (_a_las(8), _a_las(19)),
        ],
    )
    def test_el_dia_1_entre_10_y_7_y_dentro_de_sus_24_horas(self, ella, esperado):
        cuando = d.dia_1(ella, ella + timedelta(minutes=1))
        assert cuando == esperado
        assert d.DESDE <= cuando.time() <= d.HASTA
        assert cuando - ella <= timedelta(hours=23, minutes=30)

    def test_los_otros_a_la_hora_en_que_ella_escribe(self):
        assert d.dia_n(_a_las(15, 30), 3) == _a_las(15, 30, dias=3)
        assert d.dia_n(_a_las(22), 3) == _a_las(19, dias=3)
        assert d.dia_n(_a_las(7), 4) == _a_las(10, dias=4)


class TestElCalendario:
    @pytest.mark.parametrize(
        ("seg", "dias"),
        [("S1", [1, 4]), ("S2", [1, 3, 7]), ("S3", [1, 3, 6]), ("S4", [1, 3, 7])],
    )
    def test_cada_segmento_sus_dias(self, seg, dias):
        etapa = {"S1": "consulta", "S4": "abono"}.get(seg, "talla_guia")
        assert [p.dia for p in _todos(seg, etapa)] == dias

    def test_maximo_tres(self):
        assert len(_todos("S3", "grabado")) <= 3

    def test_el_dia_1_es_texto_y_los_otros_plantilla(self):
        pasos = _todos("S2", "talla_guia")
        assert pasos[0].plantilla == ""
        assert [p.plantilla for p in pasos[1:]] == ["asi_quedaria", "ultimo_recordatorio"]

    def test_sin_plantillas_aprobadas_solo_el_dia_1(self):
        assert [p.dia for p in _todos("S3", "grabado", con_plantilla=False)] == [1]

    @pytest.mark.parametrize("texto", ["no gracias", "Más adelante", "muy caro"])
    def test_si_dijo_que_no_o_mas_adelante_ninguno(self, texto):
        assert _paso(texto=texto) is None

    def test_si_pidio_tiempo_el_primero_y_el_ultimo(self):
        assert [p.dia for p in _todos("S3", "grabado", texto="lo pienso")] == [1, 6]

    def test_lo_que_manda_despues_tambien(self):
        assert [p.dia for p in _todos("S2", "despues_talla")] == [1, 7]

    def test_si_el_servidor_estuvo_caido_no_le_escribe_tarde(self):
        ella = _a_las(15)
        tarde = d.dia_1(ella, ella) + timedelta(hours=3)
        p = _paso(ella=ella, ahora=tarde)
        assert p is not None and p.dia == 3  # el 1 se perdió; sigue el 3

    def test_navidad_solo_en_su_temporada(self):
        """Camilo, 14/10: la de Navidad solo en su temporada (1/11 al 8/12)."""
        assert d.plantilla_para("S2", 7, date(2026, 10, 20)) == "ultimo_recordatorio"
        assert d.plantilla_para("S2", 7, date(2026, 11, 1)) == "ultimo_navidad"
        assert d.plantilla_para("S2", 7, date(2026, 12, 8)) == "ultimo_navidad"
        assert d.plantilla_para("S2", 7, date(2026, 12, 9)) == "ultimo_recordatorio"


KW = dict(
    nombre="Laura",
    mascota="Luna",
    abono="$60.000",
    precios="$200.000 (1 huellita), $250.000 (2) o $300.000 (3)",
    vio_precios=True,
    con_su_dibujo=True,
)


class TestLosTextos:
    def test_s1_le_pregunta_por_su_peludito(self):
        t = d.texto_del_dia_1("S1", "consulta", **KW)
        assert t.startswith("Hola Laura 🌷") and "¿cómo se llama?" in t

    def test_s1_si_no_vio_los_precios_se_los_da(self):
        t = d.texto_del_dia_1("S1", "consulta", **{**KW, "vio_precios": False})
        assert "$200.000" in t and "¿cómo se llama" not in t

    def test_s2_la_talla_no_frena(self):
        t = d.texto_del_dia_1("S2", "talla_guia", **KW)
        assert "regla" in t and "separas con el abono de $60.000" in t

    def test_s3_su_anillo_con_su_peludito(self):
        t = d.texto_del_dia_1("S3", "grabado", **KW)
        assert "anillo de Luna" in t and "colores que elegiste" in t

    def test_s4_con_las_cuentas(self):
        t = d.texto_del_dia_1("S4", "abono", **KW, cuentas="✨ Nequi: 300")
        assert "entra al taller" in t and t.endswith("✨ Nequi: 300")

    def test_sin_nombre_ni_mascota_no_quedan_huecos(self):
        t = d.texto_del_dia_1("S3", "grabado", **{**KW, "nombre": "", "mascota": ""})
        assert t.startswith("Hola 🌷") and "tu peludito" in t and "  " not in t

    def test_la_mascota_sale_del_grabado(self):
        assert d.mascota_de(Borrador(grabado=["Toby ♡ Luna"])) == "Toby"
        assert d.mascota_de(Borrador(grabado=["Toby y Luna"])) == "Toby"
        assert d.mascota_de(Borrador(grabado=["14/02/2020"])) == ""
        con = Borrador(huellitas=[HuellitaDelBorrador(mascota="Kira")])
        assert d.mascota_de(con) == "Kira"


class TestLasPlantillasCumplenConMeta:
    @pytest.mark.parametrize("p", list(d.PLANTILLAS.values()), ids=lambda p: p.nombre)
    def test_cada_una(self, p):
        variables = re.findall(r"\{\{(\d+)\}\}", p.cuerpo)
        assert variables == [str(i) for i in range(1, len(variables) + 1)]
        assert len(p.ejemplo) == len(variables)
        assert not p.cuerpo.startswith("{{") and not p.cuerpo.rstrip().endswith("}}")
        assert len(p.cuerpo) < 1024

    def test_los_botones(self):
        assert len(d.BOTONES) == 3
        assert all(len(b) <= 20 for b in d.BOTONES)

    def test_los_parametros_en_orden(self):
        assert d.parametros(
            "cupo_en_el_taller", nombre="", mascota="", abono="$60.000"
        ) == {"1": "de nuevo", "2": "tu peludito", "3": "$60.000"}
        assert d.parametros(
            "ultimo_recordatorio", nombre="Ana", mascota="Coco", abono=""
        ) == {"1": "Ana", "2": "Coco"}
        navidad = d.parametros("ultimo_navidad", nombre="Ana", mascota="Coco", abono="")
        assert navidad["3"] == "8 de diciembre"

    def test_como_se_lee(self):
        t = d.texto_de_la_plantilla("asi_quedaria", {"1": "Ana", "2": "Coco"})
        assert "Hola Ana 🐾" in t and "huellita de Coco" in t and "{{" not in t


# ══════════════════════════════════════════════════════════════════════════
#  EL WORKER Y WHATSAPP
# ══════════════════════════════════════════════════════════════════════════


class TestLoQueSale:
    def test_el_dia_1_con_foto_y_botones(self):
        from app.workers.recordatorios import Envio, mensaje_de

        e = Envio(
            "wa:573001112233", 1, "S2:talla_guia", "a", _a_las(11), "Hola 🌷 …",
            segmento="S2", media_url="https://x/media/anillos_inspirado_en_tu_mascota",
            botones=d.BOTONES,
        )  # fmt: skip
        m = mensaje_de(e)
        assert m.kind == "options"
        assert m.media_url.endswith("anillos_inspirado_en_tu_mascota")
        assert [o.title for o in m.options] == list(d.BOTONES)
        assert [o.id for o in m.options] == list(d.BOTONES)  # le llega como texto

    def test_la_plantilla_con_su_foto(self):
        from app.workers.recordatorios import Envio, mensaje_de

        e = Envio(
            "wa:573001112233", 2, "S3:grabado", "a", _a_las(11), "…",
            segmento="S3", plantilla_nombre="cupo_en_el_taller",
            parametros={"1": "Ana", "2": "Coco", "3": "$60.000"},
            media_url="https://x/media/vista_1",
        )  # fmt: skip
        m = mensaje_de(e)
        assert m.kind == "template" and m.template_name == "cupo_en_el_taller"
        assert m.template_params["imagen"] == "https://x/media/vista_1"

    def test_la_vieja_sin_cabecera(self):
        from app.workers.recordatorios import Envio, mensaje_de

        e = Envio(
            "wa:573001112233", 3, "S2:talla", "a", _a_las(11), "…", segmento="S2",
            plantilla_nombre="retomar_diseno",
            parametros={"1": "Ana", "2": "anillo"},
            media_url="https://x/media/anillos_inspirado_en_tu_mascota",
        )  # fmt: skip
        assert "imagen" not in mensaje_de(e).template_params

    def test_whatsapp_botones_con_imagen_arriba(self):
        from app.adapters.channels.whatsapp import WhatsAppAdapter
        from app.domain.models import Channel, Option, OutboundMessage

        canal = WhatsAppAdapter(
            phone_number_id="p", access_token="t", app_secret="s", verify_token="v"
        )
        m = OutboundMessage(
            channel=Channel.WHATSAPP, to="57300", kind="options", text="Hola",
            options=[Option(id=b, title=b) for b in d.BOTONES],
            media_url="https://x/media/a.jpg",
        )  # fmt: skip
        cuerpo = canal.render(m)["interactive"]
        assert cuerpo["type"] == "button"
        assert cuerpo["header"] == {
            "type": "image",
            "image": {"link": "https://x/media/a.jpg"},
        }

    def test_whatsapp_plantilla_con_cabecera(self):
        from app.adapters.channels.whatsapp import _componentes_plantilla

        partes = _componentes_plantilla(
            {"2": "Coco", "1": "Ana", "imagen": "https://x/a"}
        )
        assert partes[0] == {
            "type": "header",
            "parameters": [{"type": "image", "image": {"link": "https://x/a"}}],
        }
        assert [p["text"] for p in partes[1]["parameters"]] == ["Ana", "Coco"]


#: Escribió ayer a las 3 p. m.; el día 1 le toca hoy a las 11 a. m. (las pruebas
#: no dependen de la hora en que se corren).
ELLA = datetime.now(COL).replace(hour=15, minute=0, second=0, microsecond=0) - timedelta(
    days=1
)
AHORA = ELLA + timedelta(hours=1)
NUMERO = "573001112299"
CONV = f"wa:{NUMERO}"


@pytest.fixture
def entorno(tmp_path):
    from app.adapters.repositories.sqlite_store import SqliteDB
    from app.infra.container import build_container
    from app.infra.settings import Settings

    s = Settings(
        sqlite_path=tmp_path / "rec.db",
        repository_backend="sqlite",
        llm_backend="fake",
        payment_backend="fake",
        channel_backend="console",
        ventas_excel=tmp_path / "v.xlsx",
        ventas_cada_s=0,
        recordatorios=True,
        recordatorio_con_plantilla=True,
        recordatorios_modo="dias",
        public_url="https://bot.ejemplo.co",
    )
    c = build_container(s)
    assert c.recordador is not None and c.recordador._por_dias is not None
    return c, SqliteDB(s.sqlite_path)


def _charla(c, db, *, ella, borrador=None, mensajes=("hola",)):
    from tests.unit.test_recordatorios import _charla as charla

    charla(c, db, ella=ella, borrador=borrador, mensajes=mensajes, conv=CONV)


class TestElWorkerPorDias:
    def test_s1_un_solo_mensaje_si_recibe_el_dia_1(self, entorno):
        c, db = entorno
        _charla(
            c,
            db,
            ella=ELLA,
            borrador=Borrador(turnos=1, mostrado_en={"MOSTRAR_PRECIOS": 1}),
        )
        planes = c.recordador.planes(AHORA)
        assert planes and planes[0].segmento == "S1" and planes[0].numero == 1
        assert planes[0].media_url.endswith("/media/anillos_inspirado_en_tu_mascota")
        assert planes[0].etapa == "S1:consulta"

    def test_s3_con_el_dibujo_de_su_anillo(self, entorno):
        c, db = entorno
        b = Borrador(
            turnos=5,
            cantidad=1,
            talla=7.0,
            huellitas=[HuellitaDelBorrador(corazon=C.ROSADO, dedos=C.ROSADO)],
            grabado=["Coco"],
            nombre_clienta="Ana Gómez",
        )
        _charla(c, db, ella=ELLA, borrador=b, mensajes=("hola", "rosado", "Coco"))
        planes = c.recordador.planes(AHORA)
        assert planes and planes[0].segmento == "S3"
        assert "anillo de Coco" in planes[0].texto and planes[0].texto.startswith(
            "Hola Ana"
        )

    def test_nunca_a_un_numero_de_prueba(self, entorno):
        c, db = entorno
        from tests.unit.test_recordatorios import _charla as charla

        charla(c, db, ella=ELLA, borrador=Borrador(turnos=1), conv="wa:570000000099")
        assert not c.recordador.planes(AHORA)
