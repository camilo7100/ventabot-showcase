"""A quién se le recuerda, cuándo, y sobre todo a quién NO (04/10).

La venta más barata de recuperar es la que ya empezó. Pero un recordatorio de
más, o a las 2 a. m., es acoso; el acoso se paga con bloqueos, y los bloqueos
con el número frenado por Meta. Por eso cada regla tiene su prueba.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from app.domain import recordatorios as r
from app.domain.asesora import Borrador

COL = r.COLOMBIA


def _a_las(hora: int, minuto: int = 0, dias: int = 0) -> datetime:
    return datetime(2026, 10, 5, hora, minuto, tzinfo=COL) + timedelta(days=dias)


def _plan(etapa="talla_guia", ella=None, bot=None, enviados=None, texto="", **kw):
    ella = ella or _a_las(14)
    return r.siguiente(
        etapa_de_ella=etapa,
        ultimo_de_ella=ella,
        ultimo_del_bot=bot or ella + timedelta(minutes=1),
        enviados=enviados or {},
        texto_de_ella=texto,
        ahora=kw.pop("ahora", ella),
        **kw,
    )


# ══════════════════════════════════════════════════════════════════════════
#  LOS DOS HORARIOS: 9 a. m. y 5 p. m. (Camilo, 05/10)
# ══════════════════════════════════════════════════════════════════════════


def _todos(etapa: str, ella: datetime) -> list[r.Plan]:
    """Los que le llegarían si nunca contesta, en orden."""
    enviados: dict[int, datetime] = {}
    planes, ahora = [], ella
    for _ in range(4):
        plan = _plan(etapa, ella=ella, enviados=dict(enviados), ahora=ahora)
        if plan is None:
            break
        planes.append(plan)
        enviados[plan.numero] = plan.cuando
        ahora = plan.cuando
    return planes


class TestLosDosHorarios:
    @pytest.mark.parametrize("hora", range(24))
    def test_solo_a_las_9_o_a_las_5(self, hora):
        """Escriba a la hora que escriba, ninguno sale a otra hora."""
        planes = _todos("colores", _a_las(hora, 17))
        assert planes, "a esa hora no le llegaría ninguno"
        assert all(r.es_un_horario(p.cuando) for p in planes), planes

    @pytest.mark.parametrize("hora", range(24))
    def test_siempre_dentro_de_sus_24_horas(self, hora):
        """Los de texto libre, dentro de la ventana (si no, cuestan plantilla)."""
        ella = _a_las(hora, 17)
        for p in _todos("colores", ella):
            if not p.plantilla:
                assert p.cuando - ella < timedelta(hours=24)

    @pytest.mark.parametrize("hora, minuto", [(7, 0), (8, 0), (8, 59)])
    def test_si_escribe_antes_de_las_9_a_las_5_de_la_tarde(self, hora, minuto):
        """Camilo: «los que escriban a las 8… a las 5»."""
        assert _plan("colores", ella=_a_las(hora, minuto)) == r.Plan(1, _a_las(17))

    @pytest.mark.parametrize("hora", [10, 12, 14, 16, 18, 21, 23])
    def test_si_escribe_despues_a_las_9_del_dia_siguiente(self, hora):
        assert _plan("colores", ella=_a_las(hora, 30)) == r.Plan(1, _a_las(9, dias=1))

    def test_entre_las_9_y_las_9_y_media_a_las_5(self):
        """A las 9 a. m. del día siguiente ya se le habría cerrado la ventana."""
        assert _plan("colores", ella=_a_las(9, 10)) == r.Plan(1, _a_las(17))

    def test_de_noche_le_llegan_dos(self):
        """Escribió a las 9 p. m.: a las 9 a. m. y a las 5 p. m. (antes del cierre)."""
        assert r.turnos(_a_las(21), _a_las(21, 1)) == [
            _a_las(9, dias=1),
            _a_las(17, dias=1),
        ]

    def test_de_tarde_uno_solo(self):
        """Escribió a las 4 p. m.: las 5 p. m. siguientes ya quedan fuera."""
        assert r.turnos(_a_las(16), _a_las(16, 1)) == [_a_las(9, dias=1)]

    def test_el_tercero_en_el_horario_mas_cercano_a_cuando_escribe(self):
        assert r.hora_del_tercero(_a_las(7)) == _a_las(9, dias=3)
        assert r.hora_del_tercero(_a_las(12, 59)) == _a_las(9, dias=3)
        assert r.hora_del_tercero(_a_las(15, 10)) == _a_las(17, dias=3)
        assert r.hora_del_tercero(_a_las(23)) == _a_las(17, dias=3)

    def test_el_caso_de_la_noche(self):
        """La de producción (04/10): escribió a las 10:28 p. m. y se quedó en la
        guía de la talla. 9 a. m., 5 p. m. y, a los 3 días, la plantilla a las 5."""
        planes = _todos("talla_guia", _a_las(22, 28, dias=-1))
        assert planes == [
            r.Plan(1, _a_las(9)),
            r.Plan(2, _a_las(17)),
            r.Plan(3, _a_las(17, dias=2)),
        ]

    def test_si_el_servidor_estuvo_caido_no_le_escribe_tarde(self):
        """Se pasó el horario (más de 1 h): ese no sale; sigue el que toque."""
        ella = _a_las(16)
        plan = _plan("colores", ella=ella, ahora=_a_las(10, 30, dias=1))
        assert plan.numero == 3, "el de las 9 ya pasó: queda solo la plantilla"

    def test_el_caso_de_las_9_35_de_la_noche(self):
        """Real (05/10): Lía le escribió a mano en la mañana, el bot se calló
        12 h y, al soltarla a las 9:32 p. m., salió el recordatorio pendiente a
        las 9:35 p. m. Ya no: pasada la hora de su horario, ese no sale."""
        ella = _a_las(9, 24)
        assert _plan("talla_guia", ella=ella) == r.Plan(1, _a_las(17))
        assert (
            _plan("talla_guia", ella=ella, ahora=_a_las(21, 35), con_plantilla=False)
            is None
        )

    def test_si_el_primero_salio_tarde_el_segundo_no_se_pega(self):
        ella = _a_las(21)
        plan = _plan(
            "colores",
            ella=ella,
            enviados={1: _a_las(16, dias=1)},
            ahora=_a_las(16, 5, dias=1),
        )
        assert plan.numero == 3

    def test_nunca_un_cuarto(self):
        ella = _a_las(14)
        todos = {1: ella, 2: ella, 3: ella}
        assert (
            _plan("colores", ella=ella, enviados=todos, ahora=_a_las(15, dias=3)) is None
        )


class TestLaPlantilla:
    def test_solo_para_quien_ya_invirtio_en_su_diseno(self):
        """La que solo vio precios, o nunca dijo su talla, no gasta plantilla."""
        ella = _a_las(14)
        despues = _a_las(15, dias=2)
        for etapa in ("consulta", "talla"):
            assert (
                _plan(etapa, ella=ella, enviados={1: ella, 2: ella}, ahora=despues)
                is None
            )
        for etapa in ("talla_guia", "colores", "grabado", "nombre", "resumen", "abono"):
            plan = _plan(etapa, ella=ella, enviados={1: ella, 2: ella}, ahora=despues)
            assert plan.numero == 3 and plan.plantilla

    def test_sin_plantilla_aprobada_no_hay_tercero(self):
        ella = _a_las(14)
        assert (
            _plan(
                "colores",
                ella=ella,
                enviados={1: ella, 2: ella},
                ahora=_a_las(15, dias=2),
                con_plantilla=False,
            )
            is None
        )

    def test_el_texto_es_el_de_la_plantilla(self):
        t = r.texto(3, "colores", nombre="Laura", pieza="anillo", hoy=_a_las(9).date())
        assert t.startswith("Hola Laura 💜 Soy Lía") and "{{" not in t
        assert r.parametros_de_la_plantilla("", "cadena") == {
            "1": "de nuevo",
            "2": "cadena",
        }

    def test_la_plantilla_cumple_lo_que_pide_meta(self):
        """Meta rechaza un cuerpo que empieza o termina en variable, o de más de
        1.024 caracteres; los botones, de hasta 25."""
        cuerpo = r.CUERPO_DE_LA_PLANTILLA
        assert not cuerpo.startswith("{{") and not cuerpo.rstrip().endswith("}}")
        assert len(cuerpo) < 1024 and "{{1}}" in cuerpo and "{{2}}" in cuerpo
        assert all(len(b) <= 25 for b in r.BOTONES_DE_LA_PLANTILLA)

    def test_el_boton_mas_adelante_cuenta_como_pedir_tiempo(self):
        assert r.pide_tiempo(r.BOTONES_DE_LA_PLANTILLA[1])


# ══════════════════════════════════════════════════════════════════════════
#  A QUIÉN NO
# ══════════════════════════════════════════════════════════════════════════


class TestAQuienNo:
    @pytest.mark.parametrize(
        "texto",
        [
            "No gracias",
            "no me interesa",
            "Ya no 🙏",
            "no me escribas más",
            "Lo voy a dejar pasar quizás para el próximo mes",  # real, 05/10
            "mejor el mes que viene",
            "lo dejo para después",
        ],
    )
    def test_si_dijo_que_no_nunca(self, texto):
        assert _plan("colores", texto=texto) is None
        assert _plan("colores", texto=texto, ahora=_a_las(15, dias=3)) is None

    @pytest.mark.parametrize(
        "texto", ["lo pienso y te aviso", "Más adelante", "cuando me paguen", "mañana"]
    )
    def test_si_pidio_tiempo_uno_en_el_primer_horario_y_luego_el_de_3_dias(self, texto):
        """Camilo (07/10): «mañana le consigno» a las 9 p. m. -> el recordatorio
        de las 9 a. m. y nada más en la ventana."""
        ella = _a_las(21)
        uno = _plan("colores", ella=ella, texto=texto)
        assert uno == r.Plan(1, _a_las(9, dias=1))
        despues = _plan(
            "colores", ella=ella, texto=texto, enviados={1: uno.cuando}, ahora=uno.cuando
        )
        assert despues == r.Plan(3, r.hora_del_tercero(ella)), "no el de las 5 p. m."

    def test_monica_con_sticker_al_final(self):
        """«Mañana le consigno» / «Ahora no me queda fácil» / «Muchas gracias»
        (sus últimos textos, el sticker no cuenta): uno solo, a las 9 a. m."""
        texto = "Ahora no me queda fácil\nMuchas gracias\nNo así está bien mucha gracia"
        assert r.pide_tiempo(texto)
        plan = _plan("abono", ella=_a_las(21, 10), texto=texto, con_plantilla=False)
        assert plan == r.Plan(1, _a_las(9, dias=1))

    def test_un_solo_mensaje_no_se_persigue(self):
        assert not r.vale_la_pena(1, "Hola, precio?")
        assert not r.vale_la_pena(1, "info")
        assert r.vale_la_pena(2, "hola")

    @pytest.mark.parametrize(
        "primero",
        [
            "Quiero hacer un pedido",
            "Hola quisiera encargar un anillo",
            "como hago el pedido",
        ],
    )
    def test_salvo_que_ese_mensaje_ya_sea_una_compra(self, primero):
        assert r.vale_la_pena(1, primero)


class TestLaEtapa:
    def test_sin_borrador_es_consulta(self):
        assert r.etapa(None) == "consulta"
        assert r.etapa(Borrador(turnos=1)) == "consulta"

    def test_la_guia_de_la_talla(self):
        b = Borrador(turnos=3, cantidad=1, mostrado_en={"MOSTRAR_GUIA_TALLA": 2})
        assert r.etapa(b) == "talla_guia"
        assert r.etapa(Borrador(turnos=3, cantidad=1)) == "talla"
        assert r.etapa(Borrador(turnos=3)) == "cantidad"

    def test_con_la_guia_ya_mandada_lo_que_cuesta_es_medir(self):
        """Caso real (04/10): «¿sabes tu talla?» -> «No» -> la guía y «¿de
        cuántas huellitas?» juntos. Se le recuerda medir, no la cantidad."""
        b = Borrador(turnos=2, mostrado_en={"MOSTRAR_GUIA_TALLA": 2})
        assert r.etapa(b) == "talla_guia"
        con_talla = Borrador(turnos=3, talla=7, mostrado_en={"MOSTRAR_GUIA_TALLA": 2})
        assert r.etapa(con_talla) == "cantidad"

    def test_despues_del_abono_nunca(self):
        """Camilo: «solo antes del abono»."""
        assert r.etapa(Borrador(turnos=3, abono_reportado=True)) is None
        assert r.etapa(Borrador(turnos=3, pagado_sin_pedido=True)) is None
        assert r.etapa(Borrador(turnos=5), "ESPERANDO_ANTICIPO") == "abono"
        assert (
            r.etapa(Borrador(turnos=5, abono_reportado=True), "ESPERANDO_ANTICIPO")
            is None
        )
        for estado in ("EN_REVISION_PAGO", "EN_PRODUCCION", "ENTREGADO"):
            assert r.etapa(Borrador(turnos=5), estado) is None


class TestLosTextos:
    @pytest.mark.parametrize("etapa", sorted(r.ETAPAS))
    @pytest.mark.parametrize("numero", [1, 2, 3])
    def test_cortos_sin_plata_y_con_su_nombre(self, etapa, numero):
        t = r.texto(numero, etapa, nombre="Laura", pieza="anillo", hoy=_a_las(9).date())
        assert "Laura" in t and "{" not in t
        assert "$" not in t and "descuento" not in t.lower()
        assert len(t) < 300

    def test_sin_nombre_no_queda_un_hueco(self):
        t = r.texto(1, "colores", nombre="", pieza="anillo", hoy=_a_las(9).date())
        assert t.startswith("¡Buen día! 🌷 ¿Cómo estás?")

    def test_saluda_segun_la_hora(self):
        """Camilo, 09/10: más dulces; saludar y preguntar cómo está según la hora."""
        manana = r.texto(
            1, "abono", nombre="Mónica", pieza="anillo", hoy=_a_las(9).date()
        )
        tarde = r.texto(
            1, "abono", nombre="Mónica", pieza="anillo", hoy=_a_las(9).date(), hora=17
        )
        assert manana.startswith("¡Buen día, Mónica! 🌷 ¿Cómo estás?")
        assert tarde.startswith("¡Buenas tardes, Mónica! 🌷 ¿Cómo estás?")

    def test_una_sola_pregunta_la_del_saludo(self):
        """Lo que sigue al saludo es un recordatorio suave, sin otra pregunta."""
        for etapa in r.PRIMEROS:
            t = r.texto(1, etapa, nombre="Ana", pieza="anillo", hoy=_a_las(9).date())
            assert t.count("?") == 1, (etapa, t)
            assert "🐾" in t or "💍" in t or "🫶" in t or "💗" in t, (etapa, t)
        ultimo = r.texto(2, "abono", nombre="Ana", pieza="anillo", hoy=_a_las(9).date())
        assert ultimo.count("?") == 1

    def test_el_del_abono_no_suena_a_cobro(self):
        """El que le llegó a Mónica («Te escribo por si te quedó alguna duda antes
        del abono») no le gustó a Camilo: ahora es cálido y sin presión."""
        t = r.texto(1, "abono", nombre="Mónica", pieza="anillo", hoy=_a_las(9).date())
        assert "Te escribo por si" not in t and "sigue guardadito" in t

    def test_el_ultimo_le_da_la_fecha(self):
        t = r.texto(2, "abono", nombre="Laura", pieza="anillo", hoy=_a_las(9).date())
        assert "el 20 de octubre" in t

    def test_primer_nombre(self):
        assert r.primer_nombre("MARIA JOSE cardona") == "Maria"
        assert r.primer_nombre("") == "" and r.primer_nombre("🐶") == ""


# ══════════════════════════════════════════════════════════════════════════
#  EL WORKER, CONTRA LA BASE DE VERDAD
# ══════════════════════════════════════════════════════════════════════════

#: El «ahora» del worker: HOY a las 5:10 p. m., justo después de un horario (con
#: la hora real las pruebas dependerían de la hora en que se corren).
AHORA = datetime.now(COL).replace(hour=17, minute=10, second=0, microsecond=0)
#: Escribió a las 8 a. m.: le toca el de las 5 p. m. (ya es hora a las 5:10).
A_LAS_8 = AHORA.replace(hour=8, minute=0)
#: Escribió hace 3 días a las 4 p. m.: la plantilla, hoy a las 5 p. m.
HACE_3_DIAS = (AHORA - timedelta(days=3)).replace(hour=16, minute=0)
NUMERO = "573001112233"
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
        # Estas pruebas son del modo de los dos horarios (9 a. m. y 5 p. m.);
        # el de por días tiene las suyas (test_recordatorios_por_dias).
        recordatorios_modo="horarios",
    )
    c = build_container(s)
    assert c.recordador is not None
    return c, SqliteDB(s.sqlite_path)


def _charla(c, db, *, ella, borrador=None, mensajes=("hola", "lo quiero"), conv=CONV):
    """Una charla en la que ella escribió `mensajes` y el bot contestó de último."""
    numero = conv.rsplit(":", 1)[-1]
    for i, texto in enumerate(mensajes):
        c.conversaciones.registrar_entrante(conv, "whatsapp", numero, f"m{i}", texto, {})
    c.conversaciones.registrar_saliente(conv, "whatsapp", "Te paso la guía 📏", None)
    hasta = ella + timedelta(hours=24)
    db.ejecutar(
        "UPDATE conversations SET ultimo_entrante = ?, ventana_24h_hasta = ? "
        "WHERE conversation_id = ?",
        (ella.isoformat(), hasta.isoformat(), conv),
    )
    for direccion, cuando in (("IN", ella), ("OUT", ella + timedelta(minutes=1))):
        db.ejecutar(
            "UPDATE messages SET created_at = ? "
            "WHERE conversation_id = ? AND direccion = ?",
            (cuando.isoformat(), conv, direccion),
        )
    mundo = c.bot._mundo
    if borrador is not None:
        ctx = mundo.contexto(conv)
        mundo.guardar_contexto(ctx.model_copy(update={"borrador": borrador.model_dump()}))


def _guia() -> Borrador:
    return Borrador(
        turnos=4,
        cantidad=1,
        mostrado_en={"MOSTRAR_GUIA_TALLA": 3},
        nombre_clienta="laura gómez",
    )


def _colores() -> Borrador:
    return Borrador(turnos=6, cantidad=1, talla=7, nombre_clienta="Laura Gómez")


class TestElWorker:
    def test_le_escribe_una_vez_por_la_outbox(self, entorno):
        c, db = entorno
        _charla(c, db, ella=A_LAS_8, borrador=_guia())
        assert c.recordador.una_vuelta(AHORA) == 1
        (mensaje,) = c.outbox.pending(10)
        assert mensaje.to == NUMERO and mensaje.kind == "text"
        # Sale a las 5 p. m.: «Buenas tardes» y lo de la medida, sin presionar.
        assert mensaje.text.startswith("¡Buenas tardes, Laura! 🌷")
        assert "medir tu anillo" in mensaje.text
        # Y nunca dos veces: ni en la vuelta siguiente ni tras un reinicio.
        assert c.recordador.una_vuelta(AHORA) == 0
        assert c.recordador.una_vuelta(AHORA + timedelta(minutes=5)) == 0

    def test_con_la_ventana_cerrada_de_verdad_no_se_encola(self, entorno):
        """17/10: a las que Meta les entregó atrasado, el silencio se contaba
        desde que LLEGÓ su mensaje, no desde que lo escribió. El recordatorio
        quedaba trabado en la outbox con la ventana cerrada hacía días."""
        c, db = entorno
        _charla(c, db, ella=A_LAS_8, borrador=_guia())
        db.ejecutar(
            "UPDATE conversations SET ventana_24h_hasta = ? WHERE conversation_id = ?",
            ((A_LAS_8 - timedelta(days=5)).isoformat(), CONV),
        )
        assert c.recordador.una_vuelta(AHORA) == 0
        assert c.outbox.pending(10) == []

    def test_queda_en_la_memoria_del_bot(self, entorno):
        """Si ella contesta «sí», el bot sabe a qué."""
        c, db = entorno
        _charla(c, db, ella=A_LAS_8, borrador=_guia())
        c.recordador.una_vuelta(AHORA)
        ultimo = c.bot._mundo.contexto(CONV).charla[-1]
        assert ultimo["de"] == "lia" and "medir tu anillo" in ultimo["texto"]

    def test_todavia_no_es_la_hora(self, entorno):
        c, db = entorno
        _charla(c, db, ella=AHORA - timedelta(hours=1), borrador=_guia())
        (plan,) = c.recordador.planes(AHORA)
        assert plan.numero == 1 and plan.cuando > AHORA
        assert c.recordador.una_vuelta(AHORA) == 0

    def test_si_ella_hablo_de_ultimo_le_toca_al_bot(self, entorno):
        c, db = entorno
        _charla(c, db, ella=A_LAS_8, borrador=_guia())
        c.conversaciones.registrar_entrante(CONV, "whatsapp", NUMERO, "m9", "ya voy", {})
        assert c.recordador.planes(AHORA) == []

    def test_un_solo_mensaje_no(self, entorno):
        c, db = entorno
        _charla(c, db, ella=A_LAS_8, mensajes=("Precio?",))
        assert c.recordador.planes(AHORA) == []

    def test_un_solo_mensaje_que_ya_es_compra_si(self, entorno):
        c, db = entorno
        _charla(c, db, ella=A_LAS_8, mensajes=("Quiero hacer un pedido",))
        (plan,) = c.recordador.planes(AHORA)
        assert plan.etapa == "consulta"

    def test_nunca_a_un_numero_de_prueba(self, entorno):
        c, db = entorno
        _charla(
            c,
            db,
            ella=A_LAS_8,
            borrador=_guia(),
            conv="wa:570000000012",
        )
        assert c.recordador.planes(AHORA) == []

    def test_nunca_si_la_atiende_una_persona(self, entorno):
        c, db = entorno
        _charla(c, db, ella=A_LAS_8, borrador=_guia())
        c.bot._mundo.pausar_por_humano(CONV)
        assert c.recordador.una_vuelta(AHORA) == 0

    def test_nunca_si_esta_escalada_a_lia(self, entorno):
        c, db = entorno
        _charla(c, db, ella=A_LAS_8, borrador=_guia())
        mundo = c.bot._mundo
        ctx = mundo.contexto(CONV)
        mundo.guardar_contexto(ctx.model_copy(update={"necesita_persona": True}))
        assert c.recordador.una_vuelta(AHORA) == 0

    def test_nunca_mientras_el_bot_le_contesta(self, entorno):
        c, db = entorno
        _charla(c, db, ella=A_LAS_8, borrador=_guia())
        c.recordador._ocupada = lambda conv: True
        assert c.recordador.una_vuelta(AHORA) == 0

    def test_si_contesta_la_cuenta_vuelve_a_empezar(self, entorno):
        c, db = entorno
        _charla(c, db, ella=A_LAS_8, borrador=_guia())
        assert c.recordador.una_vuelta(AHORA) == 1
        # Ella contesta, el bot le responde y ella se vuelve a quedar callada.
        _charla(c, db, ella=AHORA - timedelta(hours=1), borrador=_guia())
        (plan,) = c.recordador.planes(AHORA)
        assert plan.numero == 1


class TestElWorkerConPlantilla:
    def test_a_los_3_dias_va_la_plantilla(self, entorno):
        c, db = entorno
        _charla(c, db, ella=HACE_3_DIAS, borrador=_colores())
        assert c.recordador.una_vuelta(AHORA) == 1
        (mensaje,) = c.outbox.pending(10)
        assert mensaje.kind == "template" and mensaje.template_name == r.PLANTILLA
        assert mensaje.template_params == {"1": "Laura", "2": "anillo"}
        assert mensaje.text.startswith("Hola Laura 💜 Soy Lía")
        assert c.recordador.una_vuelta(AHORA) == 0

    def test_sin_plantilla_aprobada_no(self, entorno):
        c, db = entorno
        _charla(c, db, ella=HACE_3_DIAS, borrador=_colores())
        c.recordador._con_plantilla = False
        assert c.recordador.una_vuelta(AHORA) == 0

    def test_una_plantilla_por_semana_como_mucho(self, entorno):
        c, db = entorno
        _charla(c, db, ella=HACE_3_DIAS, borrador=_colores())
        db.ejecutar(
            "INSERT INTO recordatorios_24h VALUES (?,?,?,?,?)",
            (
                CONV,
                "otro-silencio",
                3,
                "colores",
                (AHORA - timedelta(days=5)).isoformat(),
            ),
        )
        assert c.recordador.una_vuelta(AHORA) == 0

    def test_la_que_solo_pregunto_precios_no_gasta_plantilla(self, entorno):
        c, db = entorno
        _charla(c, db, ella=HACE_3_DIAS)
        assert c.recordador.planes(AHORA) == []


def test_apagado_de_fabrica(tmp_path):
    """Escribirle a clientas reales lo decide Camilo (`RECORDATORIOS=true`)."""
    from app.infra.container import build_container
    from app.infra.settings import Settings

    s = Settings(
        sqlite_path=tmp_path / "off.db",
        repository_backend="sqlite",
        llm_backend="fake",
        payment_backend="fake",
        channel_backend="console",
        ventas_excel=tmp_path / "v.xlsx",
        ventas_cada_s=0,
        recordatorios=False,
    )
    assert build_container(s).recordador is None
    assert Settings.model_fields["recordatorio_con_plantilla"].default is False


class TestNumerosDeLaCasa:
    """Camilo (19/10): «me enviaste a mi personal recordatorios». A los números
    de la casa, solo la respuesta inmediata: nada programado."""

    def test_cuales_son(self):
        from app.domain.numeros_propios import solo_respuesta_inmediata

        assert solo_respuesta_inmediata("wa:573001110001")  # Camilo
        assert solo_respuesta_inmediata("573001110002")  # el 317
        assert solo_respuesta_inmediata("wa:570000000012")  # una prueba
        assert not solo_respuesta_inmediata("wa:573001112233")  # una clienta

    def test_a_camilo_no_le_llega_ningun_recordatorio(self, entorno):
        c, db = entorno
        _charla(c, db, ella=A_LAS_8, borrador=_guia(), conv="wa:573001110001")
        assert c.recordador.una_vuelta(AHORA) == 0
        assert c.outbox.pending(10) == []
