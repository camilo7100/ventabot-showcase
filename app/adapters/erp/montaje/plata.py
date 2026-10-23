"""El precio de la plata mes a mes, y el costo de cada venta con la de su mes (02/10).

Camilo, 01/10 (nota con los precios por gramo, en pesos): «el anillo cambia mes
a mes ya que la plata cambia también; no guardé cuánto compré en cada época».

- Hoja `Precio_Plata`: una fila por mes (AAAAMM, $/g, fuente). Lo que Camilo
  anote ahí manda: el montaje solo llena los meses vacíos.
- `Config!B4` (el precio que usan Cat_Materiales y la receta) es el del ÚLTIMO
  mes de esa hoja: la receta y el Costeo son «con la plata de hoy».
- `Ventas!T` (Costo_Std de cada venta) suma a la receta la diferencia de la
  plata de SU mes, con la merma: gramos × ((1 + merma) × precio del mes −
  precio de hoy). Un anillo de enero (plata a $13.500) cuesta más que uno de
  septiembre ($6.500), y el estado de resultados de cada mes lo refleja.
"""

from __future__ import annotations

from app.adapters.erp.montaje import costeo
from app.adapters.erp.montaje.comun import PLATA, PLATA_925, HojaConFormato
from app.adapters.erp.montaje.formato import (
    AMARILLO_CAPTURA,
    FORMATO_NUMERO,
    ancho,
    celdas,
    encabezado,
    pestana,
    rgb,
    titulo,
)

#: La nota de Camilo (01/10/2026): plata 925, pesos por gramo.
PRECIOS_2026 = {
    202601: 13_500,
    202602: 11_500,
    202603: 11_000,
    202604: 9_000,
    202605: 9_000,
    202606: 8_000,
    202607: 8_000,
    202608: 7_000,
    202609: 6_500,
}
FUENTE = "Camilo, nota del 01/10/2026 (precio por gramo de cada mes)"
FILAS_DE_VENTAS = range(4, 2004)


def costo_de_venta(n: int) -> str:
    """La fórmula de `Ventas!T{n}`: la receta con la plata del mes de la venta."""
    receta = (
        "IFERROR(INDEX(Cat_Productos!$F$4:$F$53;"
        f"MATCH($C{n};Cat_Productos!$A$4:$A$53;0));0)"
    )
    gramos = f'SUMIFS(BOM!$C:$C;BOM!$A:$A;$C{n};BOM!$B:$B;"{PLATA_925}")'
    del_mes = (
        f"IFERROR(INDEX({PLATA}!$B$4:$B$200;MATCH($X{n};{PLATA}!$A$4:$A$200;0));"
        "Config!$B$4)"
    )
    merma = costeo.celda("S:merma")
    return (
        f'=IF($B{n}="";"";$J{n}*({receta}+{gramos}*((1+{merma})*{del_mes}-Config!$B$4)))'
    )


def montar_plata(hoja: HojaConFormato) -> list[str]:
    hoja.asegurar_hoja(PLATA)
    (actual,) = hoja.leer([f"{PLATA}!A1:D200"])
    hay = {
        int(float(f[0])): i + 1
        for i, f in enumerate(actual[3:], start=3)
        if f and str(f[0]).strip().replace(".0", "").isdigit()
    }
    e: list[tuple[str, list[list]]] = [
        (f"{PLATA}!A1", [["🪙 PRECIO DE LA PLATA — un renglón por mes (lo anotas TÚ)"]]),
        (
            f"{PLATA}!A2",
            [
                [
                    "Plata 925, pesos por gramo, como se compró ese mes. El último mes "
                    "es el «precio de hoy» (Config): con él se calcula la receta; cada "
                    "venta "
                    "usa el de su mes."
                ]
            ],
        ),
        (
            f"{PLATA}!A3",
            [["Mes (AAAAMM)", "Precio plata 925 ($/g)", "Fuente", "Anotado"]],
        ),
    ]
    siguiente = max([3, *hay.values()]) + 1
    nuevos = 0
    for mes, precio in sorted(PRECIOS_2026.items()):
        if mes in hay:
            continue  # lo que ya está (o Camilo corrigió) no se pisa
        e.append((f"{PLATA}!A{siguiente}", [[mes, precio, FUENTE, "2026-10-01"]]))
        siguiente += 1
        nuevos += 1
    # Config: el precio de hoy es el último mes anotado (en orden de fila).
    e.append(
        (
            "Config!B4",
            [
                [
                    f"=IFERROR(INDEX({PLATA}!$B$4:$B$200;COUNTA({PLATA}!$B$4:$B$200));9000)",
                    "$/g",
                    "REAL",
                    f"El último mes de la hoja {PLATA} (Camilo)",
                ]
            ],
        )
    )
    e.append(("Ventas!T4", [[costo_de_venta(n)] for n in FILAS_DE_VENTAS]))
    hoja.escribir(e)

    sid = hoja.pestanas()[PLATA]["id"]
    p = [
        *titulo(sid, 0, 4, grande=True),
        encabezado(sid, 2, 4),
        celdas(
            sid,
            3,
            200,
            0,
            2,
            {"backgroundColor": rgb(AMARILLO_CAPTURA)},
            "backgroundColor",
        ),
        celdas(
            sid, 3, 200, 1, 2, {"numberFormat": FORMATO_NUMERO["pesos"]}, "numberFormat"
        ),
        ancho(sid, 0, 1, 130),
        ancho(sid, 1, 2, 170),
        ancho(sid, 2, 3, 420),
        pestana(sid, "#F59E0B", 3),
    ]
    hoja.lote(p)
    return [f"Precio de la plata ({len(hay) + nuevos} meses; +{nuevos})"]
