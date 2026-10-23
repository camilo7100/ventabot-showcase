"""La sábana real al ERP, el filtro de las pruebas del bot y el montaje (01/10).

Datos inventados con la FORMA de la sábana de Camilo (nunca datos de clientas).
"""

from __future__ import annotations

from datetime import UTC, date, datetime

from app.adapters.erp import historial, montaje
from app.adapters.erp.sheets import HojaEnMemoria
from app.domain import erp, sabana


def _f(a: int, m: int, d: int) -> datetime:
    """Una fecha como la da Excel: sin zona horaria."""
    return datetime(a, m, d)  # noqa: DTZ001


ENCABEZADOS = [
    "DIA",
    "CELULAR",
    "TALLA",
    "COLOR",
    "GRABADO",
    "ABONO",
    "MEDIO DE PAGO",
    "RESTANTE",
    "pendiente",
    "TOTAL",
]


def _mes(filas: list[list], con_origen: bool = False) -> list[list]:
    """Una hoja de mes: el resumen de arriba y la tabla en la fila 13."""
    arriba = [[None] * 5 for _ in range(12)]
    arriba[1][0] = "Resumen del mes"
    cab = ([""] if con_origen else []) + ENCABEZADOS
    return [*arriba, cab, *filas]


ENERO = _mes(
    [
        [
            _f(2026, 1, 5),
            3001112233,
            "TALLA 7",
            "♡ Blanco",
            "Luna",
            60000,
            None,
            None,
            None,
            200000,
        ],
        # Un anillo de 3 huellitas: tres filas, una venta.
        [
            _f(1900, 1, 6),
            "300 111 4455",
            "TALLA 6 1/2",
            "HUELLA 1: Rosa",
            "Kira",
            100000,
            None,
            None,
            None,
            300000,
        ],
        [None, None, None, "HUELLA 2: Lila", "Toby"],
        [None, None, None, "HUELLA 3: Champagne"],
        [
            _f(1900, 1, 7),
            "Ana (sin número)",
            "MANILLA",
            "♡ Rojo",
            "Max",
            60000,
            None,
            None,
            None,
            160000,
        ],
        # La fila de la suma del mes: no es una venta.
        [None, None, None, None, None, None, None, None, None, 660000 + 9_000_000],
    ]
)
SEPTIEMBRE = _mes(
    [
        [
            "PUBLICIDAD",
            _f(2026, 9, 2),
            3009998877,
            "CADENA",
            "♡ Azul",
            "Coco",
            100000,
            None,
            None,
            None,
            250000,
        ],
        [
            "vieja",
            _f(2026, 9, 3),
            3009998877,
            "TALLA 8",
            "HUELLA 1: Verde",
            "Sol",
            60000,
            None,
            None,
            None,
            250000,
        ],
        ["", None, None, None, "HUELLA 2: Blanco"],
    ],
    con_origen=True,
)
RESUMEN = [
    [None, "HUELLAS 2026 — RESUMEN"],
    [None, "Mes", "Unidades", "Ventas", "Publicidad"],
    [None, "Enero", 3, 660000, 100000],
    [None, "Septiembre", 3, 750000, 200000],
]


def _sabana() -> sabana.Sabana:
    return sabana.leer(
        {"Resumen": RESUMEN, "Enero": ENERO, "Septiembre": SEPTIEMBRE}, 2026
    )


class TestLaSabana:
    def test_una_venta_es_una_fila_con_total(self):
        s = _sabana()
        assert [v.producto for v in s.ventas] == [
            "Anillos 1 huella",
            "Anillos 3 huella",
            "Manilla",
            "Cadena",
            "Anillos 2 huella",
        ]
        tres = s.ventas[1]
        assert tres.colores == ["HUELLA 1: Rosa", "HUELLA 2: Lila", "HUELLA 3: Champagne"]
        assert tres.grabados == ["Kira", "Toby"] and tres.huellitas == 3

    def test_arregla_fechas_tallas_y_celulares(self):
        s = _sabana()
        assert s.ventas[1].fecha == date(2026, 1, 6), "1900 = solo el día"
        assert s.ventas[1].talla == "TALLA 6.5" and s.ventas[0].talla == "TALLA 7"
        assert s.ventas[1].celular == "3001114455" and s.ventas[2].celular == ""
        assert s.ventas[2].talla == "", "una manilla no tiene talla"
        assert any("solo el día" in a for a in s.avisos)

    def test_el_canal_y_el_saldo(self):
        s = _sabana()
        assert [v.canal for v in s.ventas] == [
            "Por clasificar",
            "Por clasificar",
            "Por clasificar",
            "Instagram",
            "Clienta antigua",
        ]
        assert s.ventas[0].saldo == 140000 and s.ventas[0].ref == "SABANA 2026-01 F14"

    def test_cuadra_contra_el_resumen(self):
        s = _sabana()
        assert s.cuadre() == [
            (202601, 3, 3, 660000, 660000),
            (202609, 2, 3, 500000, 750000),
        ]

    def test_tallas_raras_se_dejan_como_las_anoto_lia(self):
        assert sabana.talla("un poquitin + de 6 1/2") == "un poquitin + de 6 1/2"
        assert sabana.talla("9.5") == "TALLA 9.5" and sabana.talla("16.71mm") == "16.71mm"


def _pedido(codigo: str, creado: datetime):
    class P:
        pass

    p = P()
    p.codigo, p.created_at = codigo, creado
    return p


class TestSoloLasVentasReales:
    def test_antes_del_dia_real_es_prueba(self):
        viejo = _pedido("PED-1", datetime(2026, 9, 30, 20, tzinfo=UTC))  # 15:00 Colombia
        nuevo = _pedido("PED-2", datetime(2026, 10, 1, 4, tzinfo=UTC))  # 23:00 del 30/09
        nuevo2 = _pedido("PED-3", datetime(2026, 10, 1, 6, tzinfo=UTC))  # 01:00 del 01/10
        reales = erp.solo_reales([viejo, nuevo, nuevo2], "2026-10-01")  # type: ignore[list-item]
        assert [p.codigo for p in reales] == ["PED-3"]
        assert erp.solo_reales([viejo], "") == [viejo], "sin día, nada es de prueba"


VENTAS_CAB = [*erp.COLUMNAS_VENTA, "Total", erp.REFERENCIA]


def _erp_con_pruebas() -> HojaEnMemoria:
    titulo = [["título"], ["…"]]
    cab = [*erp.COLUMNAS_VENTA] + [""] * 17 + [erp.REFERENCIA]
    prueba = ["V0001", "2026-09-29", "Anillos 1 huella", "'3000000000", "WhatsApp"]
    prueba += [""] * (len(cab) - len(prueba))
    prueba[-1] = "PED-2026-0001"
    return HojaEnMemoria(
        {
            "Ventas": [*titulo, cab, prueba],
            "Pagos": [
                *titulo,
                list(erp.COLUMNAS_PAGO),
                ["2026-09-30", "V0001", 140000, "Nequi", "PED-2026-0001 saldo"],
            ],
            "Produccion": [
                *titulo,
                list(erp.COLUMNAS_PRODUCCION),
                ["2026-09-30", "PED-2026-0001", "Anillos 1 huella", 1, 80],
            ],
        }
    )


class TestLaSabanaEnElErp:
    def test_entra_limpia_y_sin_las_pruebas_del_bot(self):
        hoja = _erp_con_pruebas()
        r = historial.importar(
            hoja, _sabana(), quitar_del_bot=frozenset({"PED-2026-0001"})
        )
        assert (r.nuevas, r.del_bot_quitadas) == (5, 1)
        ventas = hoja.hojas["Ventas"]
        ref = len([*erp.COLUMNAS_VENTA] + [""] * 17)
        assert ventas[3][0] == "V0001" and ventas[3][ref] == "SABANA 2026-01 F14", (
            "la primera venta real queda arriba y es la V0001"
        )
        assert [f[0] for f in ventas[3:8]] == [
            "V0001",
            "V0002",
            "V0003",
            "V0004",
            "V0005",
        ]
        assert ventas[4][2] == "Anillos 3 huella" and "HUELLA 3" in ventas[4][7]
        assert ventas[3][3] == "'3001112233", "el celular va como texto"
        pagos = [f for f in hoja.hojas["Pagos"][3:] if any(str(x) for x in f)]
        assert len(pagos) == 5 and all(f[4].startswith("SABANA") for f in pagos)
        assert pagos[0][2] == 140000 and pagos[0][0] == "2026-01-15"
        assert not any(
            "PED-2026-0001" in str(x) for f in hoja.hojas["Produccion"] for x in f
        )

    def test_reimportar_no_duplica_y_quita_lo_que_ya_no_esta(self):
        hoja = _erp_con_pruebas()
        historial.importar(hoja, _sabana(), quitar_del_bot=frozenset({"PED-2026-0001"}))
        filas = len(hoja.hojas["Ventas"])
        r = historial.importar(hoja, _sabana())
        assert (r.nuevas, r.actualizadas, r.quitadas, r.pagos_nuevos) == (0, 0, 0, 0)
        assert len(hoja.hojas["Ventas"]) == filas
        menos = _sabana()
        menos.ventas = menos.ventas[:-1]
        r = historial.importar(hoja, menos)
        assert (r.quitadas, r.pagos_quitados) == (1, 1)


def _erp_para_montar() -> HojaEnMemoria:
    t = [["título"], ["…"]]
    config = [*t, ["Parámetro", "Valor"]] + [[f"P{n}", n] for n in range(4, 15)]
    return HojaEnMemoria(
        {
            "LEEME": [
                ["", "HUELLAS"],
                ["", "DATOS MIGRADOS Y BANDERAS"],
                ["", "142 ventas"],
            ],
            "Config": config,
            "Cat_Productos": [
                *t,
                ["Producto"],
                ["Anillos 1 huella"],
                ["Cadena", "Joyería", 200000],
            ],
            "Cat_Canales": [*t, ["Canal"], ["Instagram"]],
            "Cat_Materiales": [*t, ["Material"], ["Plata 925 (g)"]],
            "BOM": [
                *t,
                ["Producto"],
                ["Anillos 1 huella", "Plata 925 (g)", 3.25],
                [],  # un hueco en la receta: lo nuevo no puede pisar lo de abajo
                ["Cadena", "Plata 925 (g)", 8],
            ],
            "Gastos": [
                *t,
                ["Fecha", "Concepto", "Categoria", "Monto", "Calidad", "Nota"],
                [
                    "2026-01-01",
                    "Merma de plata y colchón",
                    "Otro",
                    1,
                    "ESTIMADO",
                    "COSTEO 2026-01 merma · supuesto",
                ],
            ],
            "Ventas": [],
            "Mensual": [],
            "Validaciones": [
                *t,
                ["#", "Chequeo"],
                [16, "Anillos con costo de receta por debajo del costo real (Config)"],
                ["", "Recordatorio estructural: el tiempo del dueño y de la madre NO"],
            ],
        }
    )


class TestElMontaje:
    def test_monta_todo_y_se_puede_repetir(self):
        hoja = _erp_para_montar()
        montaje.montar(hoja, "2026-10-02", [202601, 202602], "La sábana: 2 meses")
        for nombre in ("Costeo", "Gráficas", "Precio_Plata", "Balance"):
            assert nombre in hoja.hojas
        graficas = len(hoja.graficas["Gráficas"])
        assert graficas >= 10
        costeo = hoja.hojas["Costeo"]
        fila = montaje.fila
        assert costeo[fila("S:taller") - 1][1] == 0, "los $23 M eran el equipo"
        assert costeo[fila("S:salario") - 1][1] == 2_000_000, "Lía, como mínimo"
        assert costeo[fila("C:total") - 1][0] == "COSTO COMPLETO ESTIMADO"
        assert 'BOM!$B:$B;"Circón corazón"' in costeo[fila("C:circones") - 1][1]
        assert costeo[fila("C:salario") - 1][1].startswith("=IF($B$")
        gastos = [f for f in hoja.hojas["Gastos"][3:] if f and f[0]]
        assert len(gastos) == 12, "6 gastos × 2 meses; la «merma» vieja se quita"
        assert gastos[0][1].startswith("Salario de Lía")
        colchon = [f for f in gastos if f[1].startswith("Colchón")]
        assert "SUMIFS(Ventas!$T$4:$T$2003;Ventas!$X$4:$X$2003;202601)" in colchon[0][3]
        # Camilo cambia un supuesto y se vuelve a montar: no se pisa, nada se duplica.
        hoja.hojas["Costeo"][fila("S:mama") - 1][1] = 900_000
        hoja.hojas["Precio_Plata"][3][1] = 14_000  # corrige enero
        montaje.montar(hoja, "2026-10-02", [202601, 202602], "La sábana: 2 meses")
        assert hoja.hojas["Costeo"][fila("S:mama") - 1][1] == 900_000
        assert hoja.hojas["Precio_Plata"][3][1] == 14_000
        assert len(hoja.graficas["Gráficas"]) == graficas
        assert len([f for f in hoja.hojas["Gastos"][3:] if f and f[0]]) == 12
        balance = hoja.hojas["Balance"]
        assert balance[9][0] == "TOTAL ACTIVOS" and balance[20][1] == "=B19+B20"
        assert "IF(SUMIFS(Compras" in hoja.hojas["Mensual"][3][19], "sin Compras: receta"
        bom = [tuple(f[:2]) for f in hoja.hojas["BOM"][3:] if f]
        assert len(bom) == len(set(bom)), "la receta no se duplica"

    def test_la_plata_de_cada_mes_y_el_costo_que_usa_el_marketing(self):
        hoja = _erp_para_montar()
        montaje.montar(hoja, "2026-10-02", [202601], "")
        plata = {f[0]: f[1] for f in hoja.hojas["Precio_Plata"][3:] if f}
        assert plata[202601] == 13_500 and plata[202609] == 6_500
        config = hoja.hojas["Config"]
        assert config[3][1].startswith("=IFERROR(INDEX(Precio_Plata!$B$4:$B$200;COUNTA(")
        costo = next(f for f in config if f and f[0] == montaje.PARAMETRO_COSTO)
        assert costo[1] == f"=Costeo!$B${montaje.fila('R:promedio')}", "Config = Costeo"
        venta = hoja.hojas["Ventas"][3][19]
        assert "MATCH($X4;Precio_Plata!$A$4:$A$200;0)" in venta, "la plata de su mes"
        assert f"(1+Costeo!$B${montaje.fila('S:merma')})" in venta, "con la merma"
        chequeo = hoja.hojas["Validaciones"][3]
        assert chequeo[1] == "El costo de Config no es el de Costeo"

    def test_los_gramos_reales_de_camilo(self):
        hoja = _erp_para_montar()
        montaje.montar(hoja, "2026-10-02", [202601], "")
        bom = {(f[0], f[1]): f[2] for f in hoja.hojas["BOM"][3:] if len(f) > 2}
        assert bom[("Anillos 1 huella", "Plata 925 (g)")] == 2.7
        assert bom[("Anillos 3 huella", "Plata 925 (g)")] == 3.5
        assert bom[("Cadena", "Plata 925 (g)")] == 1.8
        assert bom[("Cadena", "Cadena plata 925 (45 cm)")] == 1
        assert hoja.hojas["BOM"][4][0] != "", "el hueco se usó y no se pisó la cadena"

    def test_catalogos_y_leeme(self):
        hoja = _erp_para_montar()
        montaje.montar(hoja, "2026-10-01", [202601], "Se importó la sábana")
        productos = {f[0]: f for f in hoja.hojas["Cat_Productos"][3:] if f}
        assert productos["Cadena"][2] == 250000 and productos["Dije"][2] == 180000
        assert "2,7 g" in productos["Anillos 1 huella"][9]
        assert any(f and f[0] == "Clienta antigua" for f in hoja.hojas["Cat_Canales"])
        materiales = [f[0] for f in hoja.hojas["Cat_Materiales"][3:] if f]
        assert montaje.CIRCON in materiales
        leeme = [f[1] for f in hoja.hojas["LEEME"] if len(f) > 1]
        assert leeme[1].startswith("DATOS REALES") and leeme[2] == "Se importó la sábana"
        assert any(t.startswith("Precio_Plata — ") for t in leeme)
        recordatorio = hoja.hojas["Validaciones"][4][1]
        assert (
            "salario de Lía" in recordatorio and "Camilo (TI) no cobra" in recordatorio
        )

    def test_las_graficas_tienen_ano_y_mes(self):
        bloques = montaje.bloques()
        mes_a_mes, piezas, mezcla = bloques[0], bloques[1], bloques[3]
        primera = mes_a_mes.inicio + 3
        assert "MATCH($B$3*100+1;Mensual!$A$4:$A$39;0)" in mes_a_mes.filas[0][1]
        assert "MATCH($B$3*100+12;" in mes_a_mes.filas[11][1]
        assert piezas.filas[2][0] == f"=$A{primera + 2}"
        assert '">="&$F$3' in mezcla.filas[0][1]
        assert '"<="&$H$3' in mezcla.filas[0][1]
        assert "{" not in str([b.filas for b in bloques])

    def test_quita_pruebas_viejas_que_ya_no_estan_en_la_base_del_bot(self):
        hoja = _erp_con_pruebas()
        ventas = hoja.hojas["Ventas"]
        vieja = list(ventas[3])
        vieja[0], vieja[1], vieja[-1] = "V0002", "19/09/2026", "PED-2026-6737"
        real = list(ventas[3])
        real[0], real[1], real[-1] = "V0003", "02/10/2026", "PED-2026-7777"
        ventas += [vieja, real]
        r = historial.importar(
            hoja,
            _sabana(),
            quitar_del_bot=frozenset({"PED-2026-0001"}),
            reales_desde="2026-10-01",
        )
        assert r.del_bot_quitadas == 2
        refs = [f[-1] for f in hoja.hojas["Ventas"][3:] if f and len(f) > 30]
        assert "PED-2026-6737" not in refs and "PED-2026-7777" in refs, (
            "lo de antes del día real sale; un pedido real del bot se queda"
        )


def test_ningun_texto_del_erp_empieza_con_igual():
    """Sheets lee «=…» como fórmula: una etiqueta o nota así sale #ERROR! (01/10)."""
    textos = [s.nombre for s in montaje.SUPUESTOS] + [s.porque for s in montaje.SUPUESTOS]
    textos += [c[1] for c in montaje.CALCULADOS] + [c[-1] for c in montaje.CALCULADOS]
    textos += [c for _, c, _, _ in montaje.CAPAS] + [f for *_, f in montaje.CAPAS]
    textos += [c for _, c, _, _ in montaje.RESUMEN] + [f for *_, f in montaje.RESUMEN]
    textos += [c for _, c, *_ in montaje.FILAS_BALANCE]
    textos += [nota for *_, nota in montaje.FILAS_BALANCE]
    assert not [t for t in textos if str(t).startswith("=")]
