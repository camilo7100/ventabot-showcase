"""La pestaña «Piloto» del panel de marketing (03/10).

Camilo: «súbeme al panel todo PILOTO VENTABOT, ordenado y escalable, con
desplegables para filtrar, gestionar y mirar lo que se desea». Aquí: las fases,
la tarjeta de calificación del plan (§7), los anuncios, el embudo que cuenta el
bot solo y la página con sus filtros y el plan plegado por secciones.
"""

from __future__ import annotations

import json
from datetime import date

import pytest
from fastapi.testclient import TestClient

from app.domain import marketing_piloto as pil

TOKEN = "token-de-prueba-1234"
CAMPANA = "PILOTO VENTABOT"
FASES = (
    "campana,fase,nombre,desde,hasta,diario_cop,conjuntos,pasa_si,documento\n"
    f"{CAMPANA},1,Lanzamiento,2026-10-06,2026-10-12,15000,A,Calificación ≥ 5,"
    "PILOTO-VENTABOT.md\n"
    f"{CAMPANA},2,Validación,2026-10-13,2026-10-26,25000,A y B,Calificación ≥ 8,"
    "PILOTO-VENTABOT.md\n"
    f"{CAMPANA},3,Escala,2026-11-01,,,A y B,Calificación semanal ≥ 8,"
    "PILOTO-VENTABOT.md\n"
)
PLAN = """# Campaña piloto VentaBot · plan de marketing

*Departamento de marketing · 3 oct 2026.*

## 0. Resumen

Probar si la campaña produce ventas rentables.

## 7. Cómo se califica la campaña (tarjeta de 10 puntos)

Cinco notas de 0 a 2.

## 9. Si una nota sale baja: qué se toca

Una cosa a la vez.

## 10. Frenos (apagar de inmediato)

- Un error de plata con una clienta.
- El bot no responde en 10 minutos.
"""


def _hoy(dia: int, mes: int = 10) -> date:
    return date(2026, mes, dia)


class TestLasFases:
    def test_se_leen_en_orden(self):
        fases = pil.leer_fases(FASES)
        assert [f.numero for f in fases] == [1, 2, 3]
        assert fases[0].dias == 7 and fases[2].hasta is None
        assert fases[0].diario == 15000

    def test_antes_de_arrancar(self):
        h = pil.hoy_en(pil.leer_fases(FASES), CAMPANA, _hoy(4))
        assert h.fase is None and h.proxima.numero == 1 and h.dias_para_la_proxima == 2

    def test_en_la_fase_uno(self):
        h = pil.hoy_en(pil.leer_fases(FASES), CAMPANA, _hoy(8))
        assert (h.fase.numero, h.dia, h.proxima.numero) == (1, 3, 2)

    def test_la_fase_tres_no_tiene_fin(self):
        h = pil.hoy_en(pil.leer_fases(FASES), CAMPANA, _hoy(15, 12))
        assert h.fase.numero == 3 and not h.terminada

    def test_los_dias_de_cierre_son_de_la_fase_anterior(self):
        fases = pil.leer_fases(FASES)
        assert pil.fase_del_dia(fases, CAMPANA, _hoy(29)).numero == 2
        assert pil.fase_del_dia(fases, CAMPANA, _hoy(31)).numero == 2  # cierre: 5 días
        sin_escala = [f for f in fases if f.numero < 3]
        assert pil.fase_del_dia(sin_escala, CAMPANA, _hoy(2, 11)) is None

    def test_varias_campanas_la_mas_nueva_primero(self):
        otra = FASES + "NAVIDAD,1,Regalo,2026-11-20,2026-12-03,30000,,,\n"
        assert pil.campanas(pil.leer_fases(otra)) == ["NAVIDAD", CAMPANA]


def _totales(**k) -> pil.Totales:
    return pil.Totales(**k)


class TestLaCalificacion:
    def test_todo_verde_es_escalar(self):
        t = _totales(
            gasto=105_000,
            conversaciones=100,
            conversaciones_meta=80,
            enganchadas=40,
            listas=10,
            ventas=3,
        )
        cal = pil.calificar(t, 77_214)
        assert cal.completa and cal.puntos == 10
        assert cal.lectura[1] == "La campaña funciona"

    def test_a_medias_dice_la_nota_mas_baja(self):
        t = _totales(
            gasto=105_000,
            conversaciones=60,
            conversaciones_meta=60,
            enganchadas=10,
            listas=4,
            ventas=2,
        )
        cal = pil.calificar(t, 77_214)
        # 1 750 por conversación (1) · 16,7 % (0) · 6,7 % (1) · 3,3 % (2) · 52 500 (1)
        assert [n.puntos for n in cal.notas] == [1, 0, 1, 2, 1]
        assert cal.puntos == 5 and cal.lectura[1] == "Funciona a medias"
        assert cal.mas_baja.nota.nombre == "Enganche"

    def test_gastar_sin_vender_es_rojo_en_rentabilidad(self):
        cal = pil.calificar(_totales(gasto=50_000, conversaciones=30), 77_214)
        assert cal.notas[4].puntos == 0 and cal.notas[3].puntos == 0

    def test_sin_gasto_no_se_puede_decidir(self):
        cal = pil.calificar(_totales(conversaciones=20, enganchadas=8), 77_214)
        assert not cal.completa
        assert cal.lectura[1] == "Todavía no se puede calificar"

    def test_la_rentabilidad_usa_lo_que_deja_una_pieza(self):
        t = _totales(gasto=120_000, conversaciones=100, ventas=2)  # 60 000 c/u
        assert pil.calificar(t, 77_214).notas[4].puntos == 1
        assert pil.calificar(t, 50_000).notas[4].puntos == 0


class TestElDiaADia:
    def test_junta_meta_y_el_bot(self):
        dias = pil.dias_de(
            pil.leer_fases(FASES),
            CAMPANA,
            "fecha,campana,gasto_cop,conversaciones_meta,notas\n"
            f"2026-10-06,{CAMPANA},15000,12,arrancó\n"
            "2026-10-06,OTRA,99999,1,\n",
            [
                {
                    "fecha": "2026-10-06",
                    "conversaciones": 10,
                    "enganchadas": 4,
                    "listas": 1,
                    "ventas": 1,
                    "ventas_cop": 200000,
                },
                {"fecha": "2026-10-01", "conversaciones": 3},
            ],  # antes del piloto
            _hoy(7),
        )
        assert [d.fecha for d in dias] == [_hoy(6)]
        t = dias[0].totales
        assert (t.gasto, t.conversaciones_meta, t.conversaciones, t.ventas) == (
            15000,
            12,
            10,
            1,
        )
        assert t.notas == ["arrancó"] and dias[0].fase.numero == 1

    def test_por_semana_y_por_fase(self):
        bot = [
            {"fecha": f"2026-10-{d:02d}", "conversaciones": 1} for d in (6, 7, 12, 13, 14)
        ]
        dias = pil.dias_de(pil.leer_fases(FASES), CAMPANA, "", bot, _hoy(20))
        semanas = dict(pil.agrupar(dias, "semana", _hoy(6)))
        assert semanas["Semana 1 · 2026-10-06 a 2026-10-12"].conversaciones == 3
        assert semanas["Semana 2 · 2026-10-13 a 2026-10-19"].conversaciones == 2
        fases = dict(pil.agrupar(dias, "fase"))
        assert fases["Fase 1 · Lanzamiento"].conversaciones == 3


class TestLosAnuncios:
    TABLA = (
        "semana,campana,anuncio,gasto_cop,dias_en_pauta,retencion_3s_pct,"
        "conversaciones\n"
        f"2026-10-13,{CAMPANA},A,40000,7,30,30\n"  # 1 333 → 2
        f"2026-10-13,{CAMPANA},B,35000,7,22,15\n"  # 2 333 → 0: apagar
        f"2026-10-13,{CAMPANA},C,10000,3,40,4\n"  # poco tiempo: no se juzga
    )

    def test_se_apaga_el_peor_con_tiempo_y_gasto(self):
        a = {x.nombre: x for x in pil.anuncios_de(self.TABLA, CAMPANA, 77_214)}
        assert (a["A"].puntos, a["B"].puntos) == (2, 0)
        assert a["B"].apagar and not a["A"].apagar and not a["C"].apagar
        assert a["A"].totales.retencion_pct == 30

    def test_sin_atribucion_solo_la_nota_uno(self):
        a = pil.anuncios_de(self.TABLA, CAMPANA, 77_214)[0]
        assert len(a.calificacion.notas) == 1

    def test_uno_solo_no_se_apaga(self):
        solo = self.TABLA.splitlines()[0] + "\n" + self.TABLA.splitlines()[2] + "\n"
        assert not pil.anuncios_de(solo, CAMPANA, 77_214)[0].apagar


# ---------------------------------------------------------------------------
# El embudo del chat, desde la base del bot
# ---------------------------------------------------------------------------


def _charla(
    db,
    numero: str,
    cuando: str,
    borrador: dict | None = None,
    pedido: tuple[str, str, int] | None = None,
) -> None:
    conv = f"whatsapp:{numero}"
    db.ejecutar(
        "INSERT INTO messages (conversation_id, direccion, channel, created_at) "
        "VALUES (?, 'IN', 'whatsapp', ?)",
        (conv, cuando),
    )
    b = dict(borrador or {})
    if pedido:
        pid, estado, total = pedido
        b["pedido_id"] = pid
        db.ejecutar(
            "INSERT INTO orders (id, codigo, customer_id, estado, payload, created_at, "
            "updated_at) VALUES (?, ?, 'c', ?, ?, ?, ?)",
            (pid, pid, estado, json.dumps({"total_cop": total}), cuando, cuando),
        )
    db.ejecutar(
        "INSERT INTO conv_contexto (conversation_id, payload, actualizado) "
        "VALUES (?, ?, ?)",
        (conv, json.dumps({"borrador": b}), cuando),
    )


class TestElEmbudoDelChat:
    def test_cuenta_por_el_dia_en_que_empezo(self, tmp_path):
        from app.adapters.repositories.sqlite_store import SqliteDB
        from app.adapters.repositories.tablero import embudo_por_dia

        db = SqliteDB(tmp_path / "e.db")
        # 7 p. m. del 5 en Colombia = medianoche del 6 en UTC: es del día 5.
        _charla(db, "573001", "2026-10-06T00:30:00+00:00")
        _charla(db, "573002", "2026-10-06T15:00:00+00:00", {"cantidad": 2})
        _charla(
            db,
            "573003",
            "2026-10-06T16:00:00+00:00",
            {},
            ("P1", "ESPERANDO_ANTICIPO", 250000),
        )
        _charla(
            db,
            "573004",
            "2026-10-06T17:00:00+00:00",
            {},
            ("P2", "ANTICIPO_PAGADO", 200000),
        )
        _charla(db, "570000000077", "2026-10-06T18:00:00+00:00", {"cantidad": 1})
        _charla(db, "573005", "2026-09-30T18:00:00+00:00")  # antes de «desde»
        filas = {f["fecha"]: f for f in embudo_por_dia(db, "2026-10-01")}
        assert filas["2026-10-05"]["conversaciones"] == 1
        seis = filas["2026-10-06"]
        assert (seis["conversaciones"], seis["enganchadas"], seis["listas"]) == (3, 3, 2)
        assert (seis["ventas"], seis["ventas_cop"]) == (1, 200000)
        assert "2026-09-30" not in filas


# ---------------------------------------------------------------------------
# La página
# ---------------------------------------------------------------------------


@pytest.fixture
def ver(monkeypatch, tmp_path):
    import app.api.marketing as m
    import app.infra.container as contenedor
    from app.infra.settings import get_settings

    for k, v in {
        "PANEL_TOKEN": TOKEN,
        "REPOSITORY_BACKEND": "sqlite",
        "CHANNEL_BACKEND": "console",
        "LLM_BACKEND": "fake",
        "SQLITE_PATH": str(tmp_path / "t.db"),
        "VENTAS_REALES_DESDE": "2026-10-01",
    }.items():
        monkeypatch.setenv(k, v)
    get_settings.cache_clear()
    contenedor._singleton = None
    monkeypatch.setattr(m, "_hoy", lambda: date(2026, 10, 8))
    from app.api.main import app

    s = get_settings()
    archivos = {
        "PILOTO-VENTABOT.md": PLAN,
        "PLAN-CAMPANA.md": "# El plan de siempre\n\n## 1. Uno\n\nTexto.\n",
        "datos/piloto_fases.csv": FASES,
        "datos/piloto_dias.csv": (
            "fecha,campana,gasto_cop,conversaciones_meta\n"
            f"2026-10-06,{CAMPANA},15000,12\n2026-10-07,{CAMPANA},15000,9\n"
        ),
    }
    for nombre, texto in archivos.items():
        destino = s.marketing_dir / nombre
        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_text(texto, encoding="utf-8")

    def ver(consulta: str = "") -> str:
        r = TestClient(app).get(f"/panel/marketing?token={TOKEN}&vista=piloto{consulta}")
        assert r.status_code == 200
        return r.text

    ver.db = contenedor.get_container().db
    yield ver
    get_settings.cache_clear()
    contenedor._singleton = None


class TestLaPestana:
    def test_esta_despues_de_hoy(self, ver):
        pagina = ver()
        assert pagina.index("vista=hoy") < pagina.index("vista=piloto")
        assert "🚀 Piloto" in pagina

    def test_la_fase_de_hoy_y_los_frenos(self, ver):
        pagina = ver()
        assert "Hoy: fase 1 · Lanzamiento — día 3 de 7" in pagina
        assert "Frenos: apagar de inmediato" in pagina
        assert "El bot no responde en 10 minutos" in pagina

    def test_los_desplegables(self, ver):
        pagina = ver()
        for nombre in ("name=campana", "name=fase", "name=por", "name=plan"):
            assert nombre in pagina
        assert "Fase 2" in pagina and "Semana" in pagina

    def test_la_calificacion_con_el_chat_del_bot(self, ver):
        _charla(
            ver.db,
            "573001",
            "2026-10-06T15:00:00+00:00",
            {"cantidad": 1},
            ("P1", "ANTICIPO_PAGADO", 200000),
        )
        pagina = ver()
        assert "La calificación" in pagina and "de 10" in pagina
        assert "Atracción" in pagina and "Rentabilidad" in pagina
        assert "Enganchadas" in pagina  # el embudo

    def test_ver_por_semana(self, ver):
        assert "Semana 1 · 2026-10-06 a 2026-10-12" in ver("&por=semana")

    def test_el_plan_en_secciones_con_buscador(self, ver):
        pagina = ver()
        assert "id='plan-7'" in pagina and "id='plan-10'" in pagina
        assert "id=plan-buscar" in pagina and "Abrir todo" in pagina
        assert "Ir a…" in pagina

    def test_otro_plan_del_desplegable(self, ver):
        pagina = ver("&plan=PLAN-CAMPANA.md")
        assert "El plan de siempre" in pagina

    def test_sin_fases_lo_explica(self, ver, monkeypatch):
        from app.infra.settings import get_settings

        (get_settings().marketing_dir / "datos" / "piloto_fases.csv").unlink()
        assert "Aún no hay campañas piloto" in ver()

    def test_un_plan_que_no_existe_no_rompe(self, ver):
        assert "Campaña piloto VentaBot" in ver("&plan=../../.env")
