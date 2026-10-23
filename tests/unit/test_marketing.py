"""El marketing en el panel (30/09–01/10): la carpeta de marketing → `/panel/marketing`.

Lo escribe otro Claude y Lía lo sigue al pie de la letra desde el celular, así
que lo que se prueba es que se vea TAL CUAL, que los números calculados den lo
que tienen que dar, y que nada de lo que traiga la carpeta pueda tumbar la
página ni colarse como HTML.
"""

from __future__ import annotations

import io
import json
import tarfile
from datetime import date

import pytest
from fastapi.testclient import TestClient

from app.api import markdown_seguro as md
from app.domain import marketing_numeros as num
from app.domain.marketing import FIN, INICIO, leer_tablero

TOKEN = "token-de-prueba-1234"


def archivo(datos: dict, version: int = 3) -> str:
    """Un `PARA-EL-PANEL.md` como el que escribe el Claude de marketing."""
    return (
        f"---\nformato: lia-marketing-panel\nversion_formato: {version}\n"
        f"revision: {datos['meta']['revision']}\n---\n\n# Marketing\n\n"
        # Como el archivo real: la prosa NOMBRA las marcas (§4) antes del bloque.
        f"Saca el bloque entre `{INICIO}` y `{FIN}`.\n\n"
        f"{INICIO}\n```json\n{json.dumps(datos, ensure_ascii=False, indent=2)}\n```\n"
        f"{FIN}\n\n## 8. Ideas\n"
    )


def tablero(revision: int = 3, actualizado: str = "2026-09-30") -> dict:
    """Una revisión con TODAS las claves del formato v3."""
    return {
        "meta": {
            "revision": revision,
            "actualizado": actualizado,
            "resumen": "Vamos bien.",
        },
        "alertas": [{"nivel": "urgente", "titulo": "Pagar la cuenta", "detalle": "Ya."}],
        "tareas": [
            {"id": "T9", "titulo": "Una ya hecha", "estado": "hecho", "pasos": []},
            {
                "id": "T1",
                "titulo": "Crear la campaña <b>Octubre</b>",
                "cuando": "cada_lunes",
                "quien": "ambos",
                "estado": "pendiente",
                "por_que": "Porque sí.",
                "pasos": [
                    {"texto": "PARTE 1", "subpasos": ["Pagar", "Poner el límite"]},
                    {"texto": "Publicar"},
                ],
                "plantillas": [{"etiqueta": "Bio", "texto": "Línea 1\nLínea 2"}],
                "nota": "Ojo.",
            },
        ],
        "reglas_semanales": {
            "titulo": "Reglas de cada lunes",
            "formula": "Costo por venta = gasto ÷ anillos.",
            "reglas": [{"si": "Menos de $30.000", "hacer": "Subir", "tono": "bueno"}],
        },
        "datos_que_faltan": ["Cuántos anillos por semana"],
        "cifras": [{"etiqueta": "Ganancia", "valor": 22824000, "unidad": "cop"}],
        "rentabilidad": {
            "meses": [{"mes": "2026-01", "anillos": 49, "ganancia_cop": 2991000}],
        },
        "indicadores": [
            {
                "titulo": "Ganancia mes a mes",
                "unidad": "cop",
                "serie": [{"etiqueta": "Ene", "valor": 2991000}],
            }
        ],
        "diagnostico": [{"titulo": "Se gastó de más", "detalle": "…", "principal": True}],
        "costo_por_venta": {
            "columnas": [619, 1469],
            "filas": [{"compra": "1 de cada 21", "valores_cop": [12999, 30849]}],
        },
        "pruebas": [{"id": "P0", "pregunta": "¿Octubre?", "estado": "por_lanzar"}],
        "reels": [
            {
                "nombre": "Caja rosada",
                "estado": "en_pauta",
                "url": "https://www.instagram.com/p/DSat1tnAICP/",
            },
            {"nombre": "Enlace raro", "url": "javascript:alert(1)"},
        ],
        "perfil": [{"parte": "Bio", "hoy": "Vieja", "cambiar": "Nueva"}],
        "formula": {"titulo": "La fórmula", "pasos": ["Una mano"]},
        "angulos": [{"angulo": "Siempre contigo", "para_quien": "Mamás"}],
        "fechas": [
            {"fecha": "2026-10-04", "texto": "Día de los animales", "clave": False},
            {"fecha": "2026-09-01", "texto": "Ya pasó", "clave": False},
            {"fecha": "2026-12-03", "texto": "Último día para Navidad", "clave": True},
        ],
        "aprendizajes": [{"texto": "Más pauta no vende más", "confianza": "alta"}],
        "clave_del_futuro": {"lo_que_sea": 1},
    }


VENTAS = (
    "mes,anillos_vendidos,ingresos_cop,gasto_pauta_cop,conversaciones,"
    "ganancia_despues_de_pauta_cop\n"
    "2026-08,36,7850000,2284000,1145,1246000\n"
    "2026-09,52,11160000,1700000,1107,3220000\n"
    "TOTAL,88,19010000,3984000,2252,4466000\n"
)
META = (
    "mes,gasto_cop,impresiones,alcance,frecuencia,cpm_cop,conversaciones_iniciadas,"
    "costo_por_conversacion_cop\n"
    "2026-08,2412202,661955,483517,1.37,3644,1145,2107\n"
    "2026-09,1701389,266867,176530,1.51,6375,1107,1537\n"
)
CAMPANAS = (
    "mes,campana,objetivo,gasto_cop,alcance,frecuencia,cpm_cop,conversaciones_iniciadas,"
    "costo_por_conversacion_cop\n"
    '2026-09,"VENTAS SEPTIEMBRE",ventas,1489708,116277,1.70,7547,1065,1399\n'
    '2026-09,"Interacción",visitas al perfil,211673,64560,1.08,3047,40,5292\n'
)
ANUNCIOS = (
    "mes,anuncio,video,gasto_cop,alcance,frecuencia,cpm_cop,conversaciones_iniciadas,"
    "costo_por_conversacion_cop\n"
    '2026-09,"REEL lila","caja rosada",1169334,93022,1.61,7790,859,1361\n'
)
CREATIVOS = (
    "creativo_id,nombre,tipo,publicado,costo_mes_1_cop\n"
    "CAJA,Caja rosada,reel,2025-12-18,715\nTERCERA,Tercera,reel,2025-07,376\n"
)


def carpeta_completa() -> dict[str, str]:
    return {
        "PARA-EL-PANEL.md": archivo(tablero()),
        "ESTADO.md": "# Estado\n\nLa cuenta <script>x</script> está **frenada**.",
        "creativos/GANCHOS.md": "# Ganchos\n\n- Uno\n- Dos",
        "bitacora/2026-09-30.md": "# Bitácora 30/09\n\nNada.",
        "datos/meta_cuenta.md": "# Cuenta\n\nact_957048212868257",
        "datos/ventas_mensuales.csv": VENTAS,
        "datos/meta_mensual.csv": META,
        "datos/meta_campanas_mensual.csv": CAMPANAS,
        "datos/meta_anuncios_mensual.csv": ANUNCIOS,
        "datos/creativos.csv": CREATIVOS,
    }


class TestElLector:
    def test_lee_revision_fecha_y_version(self):
        t = leer_tablero(archivo(tablero()))
        assert (t.revision, t.actualizado, t.version_formato) == (3, date(2026, 9, 30), 3)
        assert not t.formato_mas_nuevo

    def test_un_formato_mas_nuevo_se_lee_igual_y_se_marca(self):
        assert leer_tablero(archivo(tablero(), version=9)).formato_mas_nuevo

    @pytest.mark.parametrize(
        ("texto", "motivo"),
        [
            ("sin marcas", "marcas"),
            (f"{INICIO}\n```json\n{{ roto \n```\n{FIN}", "no es JSON"),
            (f"{INICIO}\n[1, 2]\n{FIN}", "objeto"),
            (f'{INICIO}\n{{"meta": {{"actualizado": "2026-09-30"}}}}\n{FIN}', "revision"),
            (
                f'{INICIO}\n{{"meta": {{"revision": 2, "actualizado": "ayer"}}}}\n{FIN}',
                "fecha",
            ),
            ("---\nformato: otra-cosa\n---\n", "otra-cosa"),
        ],
    )
    def test_dice_en_claro_que_arreglar(self, texto, motivo):
        with pytest.raises(ValueError, match=motivo):
            leer_tablero(texto)


class TestLosNumeros:
    def test_une_ventas_y_meta_por_mes_y_deja_fuera_el_total(self):
        meses = num.meses(VENTAS, META)
        assert [m.mes for m in meses] == ["2026-08", "2026-09"]
        assert meses[-1].anillos == 52 and meses[-1].cpm == 6375

    def test_los_kpis_de_septiembre_contra_agosto(self):
        ultimo, antes = num.ultimo_con_ventas(num.meses(VENTAS, META))
        k = {x.clave: x for x in ultimo.kpis(antes)}
        assert round(k["roas"].valor, 2) == 6.56
        assert round(k["cpa"].valor) == 32692
        assert round(k["cierre"].valor, 2) == 4.70
        assert k["cpa"].tono == "bueno", "bajó el costo por venta: es bueno"
        assert k["cpm"].tono == "malo", "subió el CPM: es malo"
        assert k["pauta"].tono == "neutro"

    def test_el_embudo_va_de_impresiones_a_ventas(self):
        ultimo, _ = num.ultimo_con_ventas(num.meses(VENTAS, META))
        escalones = num.embudo(ultimo)
        assert [e.cuantos for e in escalones] == [266867, 176530, 1107, 52]
        assert escalones[2].paso == "4,70 % pasa al siguiente"

    def test_recomendaciones_de_un_analista(self):
        # Con lo que deja una pieza bien por encima del costo de la venta, mandan
        # las demás reglas (el umbral de «se perdió plata» tiene su propia prueba).
        recs = num.recomendaciones(
            num.meses(VENTAS, META), CAMPANAS, CREATIVOS, date(2026, 10, 1), 95_000
        )
        titulos = " | ".join(r.titulo for r in recs)
        assert recs[0].nivel == "urgente" and "Visitas al perfil" in recs[0].titulo
        assert "El video propio más nuevo tiene 287 días" in titulos
        assert "Venta a $32.692 en septiembre 2026: va bien" in titulos

    def test_sobre_el_tope_de_pauta_y_numeros_viejos(self):
        recs = num.recomendaciones(num.meses(VENTAS, META), "", "", date(2027, 1, 15))
        titulos = " | ".join(r.titulo for r in recs)
        assert "Los números llegan hasta septiembre 2026" in titulos
        recs = num.recomendaciones(
            [num.Mes("2026-07", anillos=56, pauta=3171000, ventas=12250000)],
            "",
            "",
            date(2026, 8, 1),
        )
        assert any("sobre el tope" in r.titulo for r in recs)

    def test_el_catalogo_cubre_las_areas_de_un_departamento(self):
        areas = {i.categoria for i in num.CATALOGO}
        assert areas >= {
            "Rentabilidad",
            "Adquisición",
            "Embudo",
            "Creativos",
            "Clientas",
            "Orgánico",
            "Mercado",
        }
        sin_dato = [i for i in num.CATALOGO if not i.kpi]
        assert all(i.como_conseguirlo for i in sin_dato), "cada falta dice cómo tenerlo"


class TestMarkdown:
    def test_el_html_sale_como_texto(self):
        salida = md.a_html("Hola <script>alert(1)</script> **ya**")
        assert "<script>" not in salida and "&lt;script&gt;" in salida
        assert "<b>ya</b>" in salida

    def test_solo_enlaces_http_y_abren_fuera(self):
        salida = md.a_html("[bien](https://x.co/a_b_c) [mal](javascript:alert(1))")
        assert "href='https://x.co/a_b_c' target=_blank" in salida
        assert "href='javascript" not in salida
        assert "<i>" not in salida, "un «_» de una dirección no es cursiva"

    def test_tablas_listas_y_casillas(self):
        salida = md.a_html(
            "| A | B |\n|---|---|\n| 1 | 2 |\n\n- uno\n  - adentro\n- [x] hecho"
        )
        assert "<table class=md><tr><th>A</th>" in salida
        assert salida.count("<ul>") == 2 and "☑ hecho" in salida

    def test_el_numero_de_la_cuenta_va_enmascarado(self):
        assert "act_…8257" in md.a_html("Cuenta act_957048212868257")


@pytest.fixture
def panel(monkeypatch, tmp_path):
    import app.infra.container as contenedor
    from app.infra.settings import get_settings

    monkeypatch.setenv("PANEL_TOKEN", TOKEN)
    monkeypatch.setenv("REPOSITORY_BACKEND", "sqlite")
    monkeypatch.setenv("CHANNEL_BACKEND", "console")
    monkeypatch.setenv("LLM_BACKEND", "fake")
    monkeypatch.setenv("SQLITE_PATH", str(tmp_path / "t.db"))
    get_settings.cache_clear()
    contenedor._singleton = None
    import app.api.marketing as m
    from app.api.main import app

    # Un «hoy» fijo: el calendario y los avisos no cambian con la fecha real.
    monkeypatch.setattr(m, "_hoy", lambda: date(2026, 10, 1))
    carpeta = get_settings().marketing_dir

    def ver(archivos: dict[str, str] | None = None, vista: str = "hoy") -> str:
        for nombre, texto in (archivos or {}).items():
            destino = carpeta / nombre
            destino.parent.mkdir(parents=True, exist_ok=True)
            destino.write_text(texto, encoding="utf-8")
        r = TestClient(app).get(f"/panel/marketing?token={TOKEN}&vista={vista}")
        assert r.status_code == 200
        return r.text

    yield ver
    get_settings.cache_clear()
    contenedor._singleton = None


class TestLaPagina:
    def test_hoy_en_el_orden_del_formato_y_las_ocho_pestanas(self, panel):
        pagina = panel(carpeta_completa())
        orden = [
            "id=alertas",
            "id=recomendaciones",
            "id=tareas",
            "id=reglas",
            "id=fechas",
            "id=faltan",
        ]
        posiciones = [pagina.index(x) for x in orden]
        assert posiciones == sorted(posiciones)
        assert "Revisión 3 · 30 sep 2026" in pagina and "Vamos bien." in pagina
        assert pagina.count("&vista=") == 9  # 8 pestañas (con «Piloto») + «Siguiente»

    def test_el_texto_va_tal_cual_y_escapado(self, panel):
        pagina = panel(carpeta_completa())
        assert "Crear la campaña &lt;b&gt;Octubre&lt;/b&gt;" in pagina
        assert "<b>Octubre</b>" not in pagina

    def test_tareas_plegables_con_casillas_y_lo_hecho_al_final(self, panel):
        pagina = panel(carpeta_completa())
        assert pagina.index("id='T1'") < pagina.index("id='T9'"), "lo hecho, al final"
        assert "<details class='tarea pendiente' id='T1' open>" in pagina
        assert pagina.count("type=checkbox data-paso=") == 4
        assert pagina.count("class=copiar>") == 1 and "Línea 1\nLínea 2" in pagina

    def test_numeros_kpis_embudo_e_historia(self, panel):
        pagina = panel(carpeta_completa(), "numeros")
        assert "Indicadores de septiembre 2026" in pagina
        assert "6,56×" in pagina and "$32.692" in pagina and "▼" in pagina
        assert "id=embudo" in pagina and "id=historia" in pagina
        assert "🧮 Calculado por el panel" in pagina

    def test_campanas_por_objetivo_con_el_perfil_en_rojo(self, panel):
        pagina = panel(carpeta_completa(), "campanas")
        assert "<span class='chip malo'>visitas al perfil</span>" in pagina
        assert "REEL lila" in pagina and "act_…8257" in pagina
        assert "123456789012345" not in pagina

    def test_creativos_con_videos_y_documentos(self, panel):
        pagina = panel(carpeta_completa(), "creativos")
        assert "href='https://www.instagram.com/p/DSat1tnAICP/' target=_blank" in pagina
        assert "javascript:" not in pagina
        assert "Ganchos" in pagina and "id=producciones" in pagina

    def test_estrategia_con_el_calendario_completo(self, panel, monkeypatch):
        import app.api.marketing as m

        monkeypatch.setattr(m, "_hoy", lambda: date(2026, 10, 1))
        pagina = panel(carpeta_completa(), "estrategia")
        assert pagina.index("Ya pasó") < pagina.index("Día de los animales")
        assert "Día de los animales · <b>en 3 días</b>" in pagina
        assert "id=recomendaciones" in pagina and "id=diagnostico" in pagina

    def test_indicadores_dice_cuantos_tienen_dato_y_como_tener_los_demas(self, panel):
        pagina = panel(carpeta_completa(), "indicadores")
        assert f"de {len(num.CATALOGO)}</b> ya tienen dato" in pagina
        assert "Cómo tenerlo:" in pagina and "✅" in pagina

    def test_biblioteca_con_todo_y_sin_html_colado(self, panel):
        pagina = panel(carpeta_completa(), "biblioteca")
        assert "Estado" in pagina and "Bitácora 30/09" in pagina
        assert "&lt;script&gt;" in pagina and "<script>x" not in pagina
        assert "ventas_mensuales.csv" in pagina

    def test_una_seccion_rota_no_tumba_la_pagina(self, panel, monkeypatch):
        import app.api.marketing as m

        def rota(c):
            raise TypeError("algo raro")

        vistas = tuple(
            (clave, nombre, tuple((n, rota if n == "Qué hacer" else f) for n, f in secs))
            for clave, nombre, secs in m.VISTAS
        )
        monkeypatch.setattr(m, "VISTAS", vistas)
        pagina = panel(carpeta_completa())
        assert "La parte «Qué hacer» no se pudo mostrar" in pagina
        assert "id=reglas" in pagina

    def test_una_vista_que_no_existe_lleva_a_hoy(self, panel):
        assert "id=tareas" in panel(carpeta_completa(), "inventada")

    def test_sin_carpeta_explica_como_subirla(self, panel):
        assert "SUBIR-MARKETING.cmd" in panel()

    def test_un_tablero_roto_se_explica_y_lo_demas_se_ve(self, panel):
        archivos = carpeta_completa() | {"PARA-EL-PANEL.md": "sin marcas"}
        pagina = panel(archivos, "biblioteca")
        assert "llegó con un error" in pagina and "Bitácora 30/09" in pagina

    def test_avisa_si_la_revision_es_vieja(self, panel):
        viejo = carpeta_completa() | {
            "PARA-EL-PANEL.md": archivo(tablero(actualizado="2026-01-01"))
        }
        assert "Esta revisión tiene" in panel(viejo)

    def test_el_taller_y_el_centro_de_mando_llevan_al_marketing(self, panel):
        from app.api.main import app

        cliente = TestClient(app)
        assert "📣 marketing" in cliente.get(f"/panel?token={TOKEN}").text
        todo = cliente.get(f"/panel/todo?token={TOKEN}").text
        assert f"/panel/marketing?token={TOKEN}" in todo and "El marketing 📣" in todo


def paquete(archivos: dict[str, str | bytes]) -> bytes:
    salida = io.BytesIO()
    with tarfile.open(fileobj=salida, mode="w:gz") as tar:
        for nombre, contenido in archivos.items():
            datos = contenido.encode("utf-8") if isinstance(contenido, str) else contenido
            info = tarfile.TarInfo(f"./{nombre}")
            info.size = len(datos)
            tar.addfile(info, io.BytesIO(datos))
    return salida.getvalue()


class TestSubirLaCarpeta:
    @pytest.fixture
    def subir(self, tmp_path):
        import importlib.util
        from pathlib import Path

        ruta = Path(__file__).resolve().parents[2] / "scripts" / "marketing.py"
        spec = importlib.util.spec_from_file_location("script_marketing", ruta)
        modulo = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(modulo)
        carpeta = tmp_path / "marketing" / "carpeta"
        return lambda datos: modulo.instalar(datos, carpeta), carpeta

    def test_pone_la_carpeta_y_deja_fuera_lo_que_no_va(self, subir):
        poner, carpeta = subir
        archivos = carpeta_completa() | {
            "CLAUDE.md": "instrucciones",
            "datos/entrada/export.csv": "crudo",
            "programa.exe": b"MZ",
        }
        tablero_puesto, puestos, _ = poner(paquete(archivos))
        assert tablero_puesto.revision == 3
        assert (carpeta / "creativos" / "GANCHOS.md").is_file()
        assert (carpeta / "datos" / "ventas_mensuales.csv").is_file()
        for fuera in ("CLAUDE.md", "datos/entrada/export.csv", "programa.exe"):
            assert not (carpeta / fuera).exists() and fuera not in puestos

    def test_guarda_la_anterior_y_no_vuelve_atras(self, subir):
        poner, carpeta = subir
        poner(paquete(carpeta_completa() | {"PARA-EL-PANEL.md": archivo(tablero(2))}))
        poner(paquete(carpeta_completa()))
        anterior = carpeta.with_name("carpeta.anterior") / "PARA-EL-PANEL.md"
        assert '"revision": 2' in anterior.read_text(encoding="utf-8")
        with pytest.raises(ValueError, match="no se vuelve atrás"):
            poner(paquete(carpeta_completa() | {"PARA-EL-PANEL.md": archivo(tablero(1))}))
        assert '"revision": 3' in (carpeta / "PARA-EL-PANEL.md").read_text(
            encoding="utf-8"
        )

    def test_un_md_suelto_cambia_solo_el_tablero(self, subir):
        poner, carpeta = subir
        poner(paquete(carpeta_completa()))
        poner(archivo(tablero(4)).encode("utf-8"))
        assert '"revision": 4' in (carpeta / "PARA-EL-PANEL.md").read_text(
            encoding="utf-8"
        )
        assert (carpeta / "creativos" / "GANCHOS.md").is_file(), "lo demás se queda"

    @pytest.mark.parametrize(
        ("archivos", "motivo"),
        [
            ({"ESTADO.md": "sin tablero"}, "no trae PARA-EL-PANEL.md"),
            ({"PARA-EL-PANEL.md": "sin marcas"}, "marcas"),
            (
                {"PARA-EL-PANEL.md": archivo(tablero()), "malo.md": b"\xff\xfe\x00"},
                "UTF-8",
            ),
        ],
    )
    def test_un_paquete_malo_no_reemplaza_al_bueno(self, subir, archivos, motivo):
        poner, carpeta = subir
        poner(paquete(carpeta_completa()))
        with pytest.raises(ValueError, match=motivo):
            poner(paquete(archivos))
        assert (carpeta / "creativos" / "GANCHOS.md").is_file()


def test_la_perdida_se_mide_contra_lo_que_deja_una_pieza():
    """La venta de septiembre costó $32.692 en pauta. Con el costo del ERP (02/10:
    deja ~$77.214) no se perdió plata; si dejara $25.000, sí, y va primero."""
    meses = num.meses(VENTAS, META)
    recs = num.recomendaciones(meses, CAMPANAS, CREATIVOS, date(2026, 10, 1))
    assert not any("se perdió plata" in r.titulo for r in recs)
    recs = num.recomendaciones(
        meses, CAMPANAS, CREATIVOS, date(2026, 10, 1), ganancia_por_anillo=25_000
    )
    assert recs[0].nivel == "urgente" and "se perdió plata" in recs[0].titulo


class TestElPeriodo:
    """02/10, Camilo: «en todos los apartados del panel, filtros de fechas»."""

    VENTAS = (
        "mes,anillos_vendidos,ingresos_cop,gasto_pauta_cop\n"
        "2025-12,30,6000000,900000\n"
        "2026-08,36,7730000,2284000\n"
        "2026-09,48,10405000,1700000\n"
        "TOTAL,114,24135000,4884000\n"
    )

    def test_las_tablas_se_quedan_con_su_periodo(self):
        from app.api.marketing import _del_periodo

        solo_2026 = _del_periodo(self.VENTAS, "2026")
        assert "2026-08" in solo_2026 and "2026-09" in solo_2026
        assert "2025-12" not in solo_2026 and "TOTAL" not in solo_2026
        assert _del_periodo(self.VENTAS, "2026-09").count("\n") == 2
        assert (
            _del_periodo("creativo_id,nombre\nA,b\n", "2026")
            == "creativo_id,nombre\nA,b\n"
        )
        assert _del_periodo(self.VENTAS, "") == self.VENTAS

    def test_la_pagina_lleva_el_selector_y_lo_conserva_en_las_pestanas(self, tmp_path):
        from app.api.marketing import pagina

        (tmp_path / "datos").mkdir()
        (tmp_path / "datos" / "ventas_mensuales.csv").write_text(self.VENTAS, "utf-8")
        html = pagina(
            tmp_path,
            "tok",
            lambda _: "<html><head><style></style></head><body>",
            "numeros",
            date(2026, 10, 1),
            anio="2026",
            mes="9",
        )
        assert "Viendo: <b>septiembre 2026</b>" in html
        assert "<option value=2025>2025</option>" in html
        assert "vista=campanas&anio=2026&mes=9" in html
