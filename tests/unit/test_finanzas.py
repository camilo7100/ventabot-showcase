"""Las finanzas del ERP en el panel: la foto, los hallazgos y las pestañas (01/10)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.adapters.erp import finanzas as foto_erp
from app.adapters.erp.sheets import HojaEnMemoria
from app.api import finanzas as pagina_fin
from app.domain import finanzas as fin


def _venta(mes: int, dia: int, producto: str, canal: str, total: int) -> dict:
    return {
        "fecha": f"{dia:02d}/{mes % 100:02d}/{mes // 100}",
        "mes": mes,
        "producto": producto,
        "canal": canal,
        "talla": "TALLA 7",
        "colores": "♡ Rosa / Dedos: Blanco",
        "total": total,
        "nueva": 1,
    }


#: 30 ventas sin datos de la clienta: casi todas sin canal.
VENTAS = [
    _venta(
        202607 + (i % 3),
        1 + i % 27,
        "Anillos 1 huella" if i % 4 else "Cadena",
        "Instagram" if i < 5 else "Por clasificar",
        200_000,
    )
    for i in range(30)
]


def _mes(clave, ingresos, util, pub, unidades=40):
    return {
        "MesKey": clave,
        "Ingresos": ingresos,
        "Unidades": unidades,
        "N_Ventas": unidades,
        "COGS_Std": ingresos * 0.3,
        "Publicidad": pub,
        "Gastos": 3_116_667,
        "Deprec": 250_000,
        "Utilidad_Op": util,
        "Clientes_Nuevos": unidades - 5,
        "Cobros": ingresos,
        "Salidas_Caja": ingresos - util,
        "Flujo": util,
        "Flujo_Acum": util * 2,
    }


FOTO = {
    "leido": "2026-10-01T20:00:00+00:00",
    "parametros": {"Precio plata ($/g)": 9000, "Primer mes con ventas (clave)": 202601},
    "mensual": [
        _mes(202607, 12_210_000, 1_859_383, 3_171_590),
        _mes(202608, 7_730_000, -365_249, 2_412_202),
        _mes(202609, 10_405_000, 2_155_052, 1_701_381),
    ],
    "costeo": {
        "supuestos": [
            {
                "nombre": "Gastos del taller por año",
                "valor": 23_000_000,
                "unidad": "$/año",
                "calidad": "ESTIMADO",
                "porque": "Camilo",
            },
            {
                "nombre": "Salario de Lía (la dueña)",
                "valor": 2_000_000,
                "unidad": "$/mes",
                "calidad": "ESTIMADO",
                "porque": "mínimo 2026",
            },
            {
                "nombre": "Pago a la mamá",
                "valor": 600_000,
                "unidad": "$/mes",
                "calidad": "SUPUESTO",
                "porque": "supuesto",
            },
            {
                "nombre": "Merma de plata (fundición)",
                "valor": 0.08,
                "unidad": "%",
                "calidad": "SUPUESTO",
                "porque": "cera perdida",
            },
        ],
        "piezas": ["Anillos 1 huella", "Anillos 2 huella", "Anillos 3 huella", "Cadena"],
        "capas": [
            {"concepto": "Plata 925", "valores": [29250, 29250, 29250, 72000]},
            {"concepto": "Taller", "valores": [40998, 40998, 40998, 40998]},
            {
                "concepto": "COSTO COMPLETO ESTIMADO",
                "valores": [141786, 143436, 145086, 192485],
            },
            {"concepto": "Margen neto", "valores": [0.08, 0.257, 0.376, 0.061]},
        ],
        "resumen": [
            {
                "concepto": "Costo promedio por pieza vendida (mezcla real)",
                "valor": 144896,
            },
            {"concepto": "Costo que usa el ERP y el marketing (Config)", "valor": 144896},
        ],
        "por_mes": [
            {"mes": 202607, "plata": 8000, "costos": [152000, 153600, 155800, 198000]},
            {"mes": 202608, "plata": 7000, "costos": [148900, 150400, 152300, 196100]},
            {"mes": 202609, "plata": 6500, "costos": [147669, 149319, 150969, 198368]},
        ],
    },
    "plata": [
        {"mes": 202607, "precio": 8000, "fuente": "Camilo"},
        {"mes": 202608, "precio": 7000, "fuente": "Camilo"},
        {"mes": 202609, "precio": 6500, "fuente": "Camilo"},
    ],
    "ventas": VENTAS,
    "tablas": {},
    "productos": [
        {
            "Producto": "Anillos 1 huella",
            "Precio_Lista": 200000,
            "Costo_Total": 59890,
            "Calidad_Dato": "ESTIMADO",
        }
    ],
    "materiales": [
        {
            "material": "Circón corazón",
            "unidad": "unidad",
            "costo": 1500,
            "calidad": "ESTIMADO",
            "stock": 0,
            "estado": "⚠️ RESTOCK",
        }
    ],
    "gastos": [
        {
            "concepto": "Taller (gastos del año ÷ 12)",
            "categoria": "Operativo",
            "calidad": "ESTIMADO",
            "total": 17_250_000,
            "meses": 9,
        }
    ],
    "clientas": {"Clientes únicos": 353, "Tasa de recompra": 0.12},
    "balance": [
        {"concepto": "▼ ACTIVOS — lo que tiene el negocio", "tipo": "seccion"},
        {
            "concepto": "Caja estimada",
            "valor": 9_000_000,
            "tipo": "dato",
            "nota": "cobros",
        },
        {"concepto": "Deudas con proveedores", "valor": 0, "tipo": "captura"},
        {"concepto": "TOTAL ACTIVOS", "valor": 9_000_000, "tipo": "total"},
    ],
    "validaciones": [
        {
            "numero": 6,
            "chequeo": "Saldos negativos",
            "resultado": 1,
            "estado": "⚠️ REVISAR",
        },
        {
            "numero": 2,
            "chequeo": "Ventas sin producto",
            "resultado": 0,
            "estado": "✅ OK",
        },
    ],
}


class TestLoQueDicenLosNumeros:
    def test_el_resumen_suma_los_meses(self):
        r = fin.resumen(FOTO)
        assert r.meses == 3 and r.ingresos == 30_345_000
        assert r.utilidad == 1_859_383 - 365_249 + 2_155_052
        assert round(r.roas, 1) == round(
            30_345_000 / (3_171_590 + 2_412_202 + 1_701_381), 1
        )

    def test_los_hallazgos_lo_urgente_primero(self):
        h = fin.hallazgos(FOTO)
        assert h[0].nivel == "urgente" and "ago 2026" in h[0].titulo
        titulos = " ".join(x.titulo for x in h)
        assert "rindió poco" in titulos and "no dicen de dónde vino" in titulos
        assert "supuestos míos" in titulos and "1 cosa(s) para revisar" in titulos
        assert (
            "La utilidad ya le paga a Lía" in titulos
            and "A la caja le quedan" in titulos
        )
        assert any("1 huellita" in x.detalle for x in h), "el anillo que menos deja"

    def test_sin_foto_no_inventa(self):
        assert fin.hallazgos({}) == [] and fin.resumen({}).ingresos == 0


def _cabecera(titulo: str) -> str:
    return f"<html><head><title>{titulo}</title><style></style></head><body>"


class TestLaPagina:
    @pytest.mark.parametrize(
        "vista,espera",
        [
            ("resumen", "Utilidad operativa"),
            ("resultados", "Estado de resultados"),
            ("balance", "Balance general"),
            ("costos", "$144.896"),
            ("materiales", "Circón corazón"),
            ("ventas", "jul 2026"),
            ("calidad", "Saldos negativos"),
        ],
    )
    def test_cada_pestana(self, vista, espera):
        html = pagina_fin.pagina(FOTO, "tok", _cabecera, vista)
        assert espera in html and "Actualizar del ERP" in html
        assert "no se pudo mostrar" not in html

    def test_sin_foto_dice_como_tomarla(self):
        assert "vb erp --montar" in pagina_fin.pagina(None, "tok", _cabecera)

    def test_la_ruta_pide_la_llave(self, monkeypatch, tmp_path):
        import app.infra.container as contenedor
        from app.infra.settings import get_settings

        for k, v in {
            "PANEL_TOKEN": "llave",
            "REPOSITORY_BACKEND": "sqlite",
            "CHANNEL_BACKEND": "console",
            "LLM_BACKEND": "fake",
            "SQLITE_PATH": str(tmp_path / "t.db"),
        }.items():
            monkeypatch.setenv(k, v)
        get_settings.cache_clear()
        contenedor._singleton = None
        from app.api.main import app

        cliente = TestClient(app)
        assert cliente.get("/panel/finanzas").status_code == 404
        r = cliente.get("/panel/finanzas?token=llave")
        assert r.status_code == 200 and "Todavía no hay foto" in r.text
        import json

        destino = get_settings().finanzas_foto_del_erp
        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_text(json.dumps(FOTO), encoding="utf-8")
        r = cliente.get("/panel/finanzas?token=llave&vista=costos")
        assert "Capa por capa" in r.text
        assert "💰 finanzas" in cliente.get("/panel?token=llave").text
        assert "Las finanzas 💰" in cliente.get("/panel/todo?token=llave").text
        get_settings.cache_clear()
        contenedor._singleton = None


class TestLaFoto:
    def test_solo_totales_y_hasta_el_ultimo_mes(self):
        t = [["título"], ["…"]]
        config = [*t, ["Parámetro", "Valor"]] + [[f"P{n}", n] for n in range(4, 11)]
        config += [
            ["Primer mes con ventas (clave)", 202601],
            ["Último mes con ventas (clave)", 202602],
        ]
        hoja = HojaEnMemoria(
            {
                "Mensual": [
                    *t,
                    ["MesKey", "Ingresos", "Utilidad_Op"],
                    [202601, 100, 10],
                    [202602, 200, 20],
                    [202603, 0, 0],
                ],
                "Config": config,
                "Costeo": [],
                "Gráficas": [],
                "Balance": [],
                "Precio_Plata": [*t, ["Mes", "Precio"], [202601, 13500, "Camilo"]],
                "Ventas": [
                    *t,
                    [
                        "Venta_ID",
                        "Fecha",
                        "Producto",
                        "Celular_Cliente",
                        "Canal",
                        "Grabado",
                        "Total",
                        "MesKey",
                        "Cliente_Nuevo",
                    ],
                    [
                        "V0001",
                        "05/01/2026",
                        "Anillos 1 huella",
                        "'3009998877",
                        "Instagram",
                        "Luna ♡ Sol",
                        200000,
                        202601,
                        1,
                    ],
                ],
                "Cat_Productos": [*t, ["Producto", "Precio_Lista"], ["Dije", 180000]],
                "Cat_Materiales": [*t, ["Material", "Unidad"], ["Plata 925 (g)", "g"]],
                "Inventario": [
                    *t,
                    ["Material", "Stock", "Estado"],
                    ["Plata 925 (g)", 0, "OK"],
                ],
                "Gastos": [
                    *t,
                    ["Fecha", "Concepto", "Categoria", "Monto"],
                    ["2026-01-01", "Taller", "Operativo", 100],
                    ["2026-02-01", "Taller", "Operativo", 100],
                ],
                "Validaciones": [*t, ["#", "Chequeo", "Resultado", "Estado"]],
                "Rank_Clientes": [
                    *t,
                    ["KPI", "Valor", "", "#", "Celular"],
                    ["Clientes únicos", 353, "", 1, "3001112233"],
                ],
            }
        )
        f = foto_erp.foto(hoja)
        assert [m["MesKey"] for m in f["mensual"]] == [202601, 202602]
        assert f["gastos"][0]["total"] == 200 and f["gastos"][0]["meses"] == 2
        assert f["clientas"] == {"Clientes únicos": 353}
        assert "3001112233" not in str(f), "ningún celular sale del ERP"
        assert "3009998877" not in str(f) and "Luna" not in str(f), "ni grabados"
        assert f["ventas"][0]["producto"] == "Anillos 1 huella"
        assert f["ventas"][0]["mes"] == 202601 and f["ventas"][0]["total"] == 200000
        assert f["plata"] == [{"mes": 202601, "precio": 13500, "fuente": "Camilo"}]


class TestElPeriodo:
    def test_todas_las_pestanas_tienen_periodo(self):
        for vista in (
            "resumen",
            "resultados",
            "balance",
            "costos",
            "materiales",
            "ventas",
        ):
            html = pagina_fin.pagina(FOTO, "tok", _cabecera, vista, "2026", "9")
            assert "Mostrando: <b>septiembre 2026</b>" in html, vista

    def test_ventas_del_periodo(self):
        html = pagina_fin.pagina(FOTO, "tok", _cabecera, "ventas", "2026", "9")
        assert "sep 2026" in html and "jul 2026" not in html
        assert "Ventas del período:</b> 10" in html

    def test_el_costo_y_la_plata_del_periodo(self):
        costos = pagina_fin.pagina(FOTO, "tok", _cabecera, "costos", "2026", "8")
        assert "El costo mes a mes" in costos and "$148.900" in costos
        assert "$152.000" not in costos, "julio no es agosto"
        materiales = pagina_fin.pagina(FOTO, "tok", _cabecera, "materiales")
        assert "La plata, mes a mes" in materiales and "$6.500" in materiales

    def test_el_balance_al_cierre_del_periodo(self):
        html = pagina_fin.pagina(FOTO, "tok", _cabecera, "balance", "2026", "8")
        assert "Al cierre de ago 2026" in html
        # utilidades jul + ago; la caja de agosto (Flujo_Acum del mes)
        assert fin.cierre(FOTO, 202608)["utilidades"] == 1_859_383 - 365_249

    def test_un_mes_de_un_anio(self):
        html = pagina_fin.pagina(FOTO, "tok", _cabecera, "resumen", "2026", "8")
        assert "Mostrando: <b>agosto 2026</b>" in html and "$7.730.000" in html
        assert "$12.210.000" not in html, "julio no entra en agosto"
        assert "&anio=2026&mes=8" in html, "las pestañas conservan el período"

    def test_los_meses_llevan_su_anio_y_lo_raro_se_ignora(self):
        html = pagina_fin.pagina(FOTO, "tok", _cabecera, "resultados", "abc", "99")
        assert "todo el historial" in html and "jul 26" in html
        assert "Año por año" in html and "<b>2026</b>" in html

    def test_el_dominio_filtra_y_suma_por_anio(self):
        assert fin.anios(FOTO) == [2026]
        assert len(fin.del_periodo(FOTO, 2026, 9)["mensual"]) == 1
        assert fin.por_anio(FOTO)[2026].ingresos == 30_345_000


def test_el_css_de_finanzas_no_pisa_clases_del_panel():
    """Pasó el 01/10: `.cuenta` del panel (una píldora rosada) tapó el estado de
    resultados. Solo se pueden extender a propósito las de esta lista."""
    import re

    from app.api import panel

    def clases(css: str) -> set[str]:
        return set(re.findall(r"\.([a-zA-Z][\w-]*)", css))

    a_proposito = {"ayuda", "chip"}
    assert clases(pagina_fin.ESTILO) & clases(panel.ESTILO) <= a_proposito
