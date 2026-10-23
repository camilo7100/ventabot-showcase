"""El Excel para Lía: el cuestionario y lo del mes que el bot no llena (02/10)."""

import io

import openpyxl

from app.adapters.erp import montaje
from app.adapters.erp.cuestionario import (
    RESPUESTAS,
    crear_libro,
    leer_libro,
    pasar_al_erp,
)
from app.adapters.erp.montaje.gastos import montar_gastos
from app.domain.cuestionario import (
    PREGUNTAS,
    SALARIO_MINIMO_2026,
    Respuestas,
    cambios_del_costeo,
    leer_pesos,
    leer_porcentaje,
    no_sabe,
)
from tests.unit.test_erp_real import _erp_para_montar


class TestLeerLoQueEscribe:
    def test_pesos_como_los_escribe_una_persona(self):
        assert leer_pesos("$1.200.000") == 1_200_000
        assert leer_pesos("1,2 millones") == 1_200_000
        assert leer_pesos("600 mil") == 600_000
        assert leer_pesos("600k") == 600_000
        assert leer_pesos("14.000") == 14_000
        assert leer_pesos(250000) == 250_000
        assert leer_pesos("0") == 0
        assert leer_pesos("") is None
        assert leer_pesos("ni idea") is None

    def test_no_se_en_todas_sus_formas(self):
        for texto in ("NO SÉ", "no se", "Nose", "no lo sé", "NS"):
            assert no_sabe(texto), texto
        assert leer_pesos("no sé") is None

    def test_porcentajes(self):
        assert leer_porcentaje("8") == 0.08
        assert leer_porcentaje("8 %") == 0.08
        assert leer_porcentaje("0,05") == 0.05
        assert leer_porcentaje("5 gramos") == 0.05


def _respuestas(**por_id) -> Respuestas:
    return Respuestas(escritas={k: str(v) for k, v in por_id.items()})


class TestQueCambia:
    def test_el_taller_solo_con_las_cuatro_partes(self):
        a_medias = cambios_del_costeo(_respuestas(T1="800 mil", T2="200 mil"), "hoy")
        assert "taller" not in {c.destino for c in a_medias}
        completo = cambios_del_costeo(
            _respuestas(T1="800 mil", T2="200 mil", T3="1 millón", T4="0"), "hoy"
        )
        taller = next(c for c in completo if c.destino == "taller")
        assert taller.valor == 12 * 1_000_000 + 1_000_000

    def test_el_salario_de_paula_nunca_baja_del_minimo(self):
        (c,) = cambios_del_costeo(_respuestas(P1="1.000.000"), "hoy")
        assert c.destino == "salario" and c.valor == SALARIO_MINIMO_2026
        (c,) = cambios_del_costeo(_respuestas(P1="3 millones"), "hoy")
        assert c.valor == 3_000_000

    def test_un_no_se_no_cambia_nada(self):
        assert cambios_del_costeo(_respuestas(P2="NO SÉ", M1="no se"), "hoy") == []

    def test_materiales_y_merma(self):
        cambios = {
            c.destino: c.valor
            for c in cambios_del_costeo(_respuestas(M1="5", M3="250"), "hoy")
        }
        assert cambios == {"merma": 0.05, "material:Circón dedito": 250}

    def test_todas_las_preguntas_tienen_id_unico(self):
        ids = [p.id for p in PREGUNTAS]
        assert len(ids) == len(set(ids))


def _erp() -> object:
    hoja = _erp_para_montar()
    montaje.montar(hoja, "2026-10-02", [202609, 202610], "")
    t = [["título"], ["…"]]
    hoja.hojas.update(
        {
            "Compras": [
                *t,
                [
                    "Fecha",
                    "Proveedor",
                    "Material",
                    "Cantidad",
                    "Unidad (auto)",
                    "Precio_Unit",
                    "Total",
                    "Nota",
                    "MesKey",
                ],
            ],
            "Activos": [
                *t,
                [
                    "Activo",
                    "Fecha_Compra",
                    "Valor",
                    "Vida_Util_Meses",
                    "Deprec",
                    "Activo_SN",
                    "Calidad",
                    "Fuente",
                    "Notas",
                ],
                [
                    "Taller y equipos (consolidado)",
                    "2025-01-01",
                    30000000,
                    120,
                    "",
                    "SI",
                    "ESTIMADO",
                    "",
                    "",
                ],
            ],
            "Ventas": [
                *t,
                [
                    "Venta_ID",
                    "Fecha",
                    "Producto",
                    "Celular_Cliente",
                    "Canal",
                    "Ciudad",
                    "Talla",
                    "Color_Detalle",
                    "Grabado",
                    "Cantidad",
                    "Precio_Unit",
                    "Abono_Inicial",
                    "Medio_Pago",
                    "Estado",
                    "Total",
                    "Pedido_Ref",
                ],
                ["V0007", "2026-09-01", "Anillos 1 huella"],
            ],
            "Inventario": [
                *t,
                ["Material", "Unidad", "Entradas", "Ajustes", "Consumo", "Stock"],
                ["Plata 925 (g)", "g", 0, 0, 30, -30],
            ],
            "Ajustes": [
                *t,
                [
                    "Fecha",
                    "Tipo",
                    "Material",
                    "Cantidad_±",
                    "Valor_Est",
                    "Motivo",
                    "MesKey",
                ],
            ],
        }
    )
    return hoja


def _excel_lleno() -> bytes:
    archivo = io.BytesIO()
    crear_libro(archivo, ["Plata 925 (g)", "Circón corazón"], "02/10/2026")
    libro = openpyxl.load_workbook(io.BytesIO(archivo.getvalue()))
    preguntas = libro["Preguntas"]
    for fila in preguntas.iter_rows(min_row=2):
        respuesta = {"P2": "500 mil", "M2": "1.200", "P4": "14000", "G1": "NO SÉ"}
        fila[5].value = respuesta.get(fila[0].value, "")
    libro["Compras"].append(["2026-10-03", "Plata Ltda", "Plata 925 (g)", 100, "650.000"])
    libro["Gastos"].append(["2026-10-05", "Pago a la mamá", "500000", ""])
    libro["Plata"].append(["2026-10", "6.800", ""])
    libro["Equipos"].append(["Pulidora", 2021, "2.500.000", 8, ""])
    libro["Ventas fuera del bot"].append(
        ["2026-10-08", "Anillos 2 huella", 1, "250000", "Feria", "Bucaramanga", ""]
    )
    libro["Inventario hoy"].append(["Plata 925 (g)", 80, "2026-10-09", ""])
    salida = io.BytesIO()
    libro.save(salida)
    return salida.getvalue()


class TestElExcel:
    def test_ida_y_vuelta_al_erp(self):
        hoja = _erp()
        libro = leer_libro(_excel_lleno())
        assert libro.respuestas.escritas["P2"] == "500 mil"
        r = pasar_al_erp(hoja, libro, "2026-10-10")
        assert any("en blanco" in a for a in r.avisos), "avisa lo que dejó vacío"

        costeo = hoja.hojas["Costeo"]
        mama = costeo[montaje.fila("S:mama") - 1]
        assert mama[1] == 500_000 and mama[3] == "REAL" and "Lía" in mama[4]
        assert hoja.hojas[RESPUESTAS][0][0] == "#"

        compra = next(f for f in hoja.hojas["Compras"][3:] if f and f[0])
        assert compra[:4] == ["2026-10-03", "Plata Ltda", "Plata 925 (g)", 100]
        assert compra[5] == 6500 and compra[7].startswith("LIA compra")

        gasto = next(f for f in hoja.hojas["Gastos"][3:] if f and f[4] == "REAL")
        assert gasto[1] == "Pago a la mamá" and gasto[3] == 500_000

        plata = [f for f in hoja.hojas["Precio_Plata"][3:] if f and f[0] == 202610]
        assert plata and plata[0][1] == 6800

        activos = hoja.hojas["Activos"]
        assert activos[3][5] == "NO", "el bloque estimado deja de contar"
        assert activos[4][0] == "Pulidora" and activos[4][3] == 96

        venta = hoja.hojas["Ventas"][4]
        assert venta[0] == "V0008" and venta[11] == 250_000
        assert venta[15].startswith("LIA venta")

        ajuste = next(f for f in hoja.hojas["Ajustes"][3:] if f and f[0])
        assert ajuste[3] == 110, "contó 80 y el ERP decía −30"

    def test_importar_dos_veces_no_duplica(self):
        hoja = _erp()
        libro = leer_libro(_excel_lleno())
        pasar_al_erp(hoja, libro, "2026-10-10")
        compras = len([f for f in hoja.hojas["Compras"] if f and f[0]])
        r = pasar_al_erp(hoja, libro, "2026-10-11")
        assert len([f for f in hoja.hojas["Compras"] if f and f[0]]) == compras
        assert not any(h.startswith(("Compras", "Gastos", "Ventas")) for h in r.hechos)


class TestElEstimadoSeQuitaConElReal:
    def test_un_gasto_real_del_mes_reemplaza_su_estimado(self):
        hoja = _erp()
        gastos = hoja.hojas["Gastos"]
        gastos.append(
            [
                "2026-10-05",
                "Pago a la mamá",
                "Personal",
                500000,
                "REAL",
                "LIA gasto x",
                202610,
            ]
        )
        montar_gastos(hoja, [202609, 202610])
        estimados = [
            f[5]
            for f in hoja.hojas["Gastos"]
            if len(f) > 5 and str(f[5]).startswith("COSTEO")
        ]
        assert any("2026-09 mama" in n for n in estimados), "septiembre sigue estimado"
        assert not any("2026-10 mama" in n for n in estimados), "octubre ya es real"
