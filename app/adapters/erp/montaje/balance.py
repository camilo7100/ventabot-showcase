"""La hoja Balance y la caja de Mensual (01/10).

- Mensual: mientras un mes no tenga Compras ni Producción anotadas, la plata
  de los materiales y la mano de obra sale igual: el costo de lo vendido. Sin
  esto la caja acumulada salía inflada (los materiales nunca «salían»).
- Balance: activos, pasivos y patrimonio con fórmulas, al último mes con
  ventas; las deudas se anotan en amarillo.
"""

from __future__ import annotations

from app.adapters.erp.montaje.comun import BALANCE, HojaConFormato
from app.adapters.erp.montaje.formato import (
    AMARILLO_CAPTURA,
    AZUL_CALCULADO,
    FORMATO_NUMERO,
    ancho,
    celdas,
    encabezado,
    rgb,
    titulo,
)

_FIN = "DATE(INT(Config!$B$12/100);MOD(Config!$B$12;100);1)"
_HASTA = "MATCH(Config!$B$12;Mensual!$A$4:$A$39;0)"
#: (fila, concepto, fórmula o valor, tipo, nota). tipo: seccion · dato · captura
#: (amarillo, lo anota Camilo) · total.
FILAS_BALANCE = (
    (4, "▼ ACTIVOS — lo que tiene el negocio", "", "seccion", ""),
    (
        5,
        "Caja estimada",
        f"=INDEX(Mensual!$V$4:$V$39;{_HASTA})",
        "dato",
        "Cobros − salidas desde el primer mes (sin el saldo con que se arrancó)",
    ),
    (
        6,
        "Saldos por cobrar a clientas",
        "=SUM(Ventas!$S$4:$S$2003)",
        "dato",
        "Ventas: total − abono − pagos",
    ),
    (
        7,
        "Inventario de materiales",
        "=Inventario!$H$57",
        "dato",
        "Compras − consumo: en 0 mientras no se anoten las Compras",
    ),
    (
        8,
        "Equipos del taller (costo)",
        '=SUMIFS(Activos!$C$4:$C$50;Activos!$F$4:$F$50;"SI")',
        "dato",
        "Hoja Activos",
    ),
    (
        9,
        "(−) Depreciación acumulada",
        '=-SUMPRODUCT((Activos!$F$4:$F$13="SI")*IFERROR(Activos!$E$4:$E$13*((YEAR('
        f"{_FIN})-YEAR(Activos!$B$4:$B$13))*12+MONTH({_FIN})-MONTH(Activos!$B$4:$B$13)+1);0))",
        "dato",
        "Depreciación mensual × meses desde la compra",
    ),
    (10, "TOTAL ACTIVOS", "=SUM(B5:B9)", "total", ""),
    (12, "▼ PASIVOS — lo que el negocio debe", "", "seccion", ""),
    (
        13,
        "Abonos de pedidos sin entregar",
        '=SUMIFS(Ventas!$L$4:$L$2003;Ventas!$B$4:$B$2003;"<>";Ventas!$N$4:$N$2003;'
        '"<>Entregado";Ventas!$N$4:$N$2003;"<>Cancelado")',
        "dato",
        "Plata de clientas por un anillo que aún no se entrega",
    ),
    (
        14,
        "Deudas con proveedores",
        0,
        "captura",
        "Anótalas aquí (el ERP no las registra)",
    ),
    (15, "Préstamos y otras deudas", 0, "captura", "Anótalas aquí"),
    (16, "TOTAL PASIVOS", "=SUM(B13:B15)", "total", ""),
    (18, "▼ PATRIMONIO — lo que es del negocio", "", "seccion", ""),
    (
        19,
        "Utilidades desde el primer mes",
        f"=SUM(OFFSET(Mensual!$O$4;0;0;{_HASTA};1))",
        "dato",
        "Suma de la utilidad operativa de Mensual",
    ),
    (
        20,
        "Capital y lo que el ERP no explica",
        "=B10-B16-B19",
        "dato",
        "Lo que se puso al empezar (taller, caja inicial) y lo no registrado",
    ),
    (21, "TOTAL PATRIMONIO", "=B19+B20", "total", "Activos − Pasivos"),
)


def caja_y_balance(hoja: HojaConFormato) -> list[str]:
    # Mensual: mientras un mes no tenga Compras ni Producción anotadas, la plata
    # de los materiales y la mano de obra sale igual: el costo de receta (01/10).
    salidas = [
        [
            f"=SUMIFS(Compras!$G:$G;Compras!$I:$I;$A{n})+$L{n}+$M{n}"
            f"+SUMIFS(Produccion!$I:$I;Produccion!$J:$J;$A{n})"
            f"+IF(SUMIFS(Compras!$G:$G;Compras!$I:$I;$A{n})"
            f"+SUMIFS(Produccion!$I:$I;Produccion!$J:$J;$A{n})=0;$I{n};0)"
        ]
        for n in range(4, 40)
    ]
    hoja.asegurar_hoja(BALANCE)
    (actual,) = hoja.leer([f"{BALANCE}!A1:C30"])
    e: list[tuple[str, list[list]]] = [
        ("Mensual!T4", salidas),
        (
            f"{BALANCE}!A1",
            [
                [
                    "⚖️ BALANCE — Lo que tiene, lo que debe y lo que es del negocio "
                    "(NO EDITAR salvo lo amarillo)"
                ]
            ],
        ),
        (
            f"{BALANCE}!A2",
            [
                [
                    "Estimado: el ERP no sabe con cuánta caja se arrancó ni las "
                    "deudas; anótalas en amarillo. Al último mes con ventas."
                ]
            ],
        ),
        (f"{BALANCE}!A3", [["Concepto", "Valor", "De dónde sale"]]),
    ]
    for fila, concepto, valor, tipo, nota in FILAS_BALANCE:
        f = actual[fila - 1] if fila - 1 < len(actual) else []
        if tipo == "captura" and len(f) > 1 and str(f[1]).strip() not in ("", "0"):
            valor = f[1]  # lo que Camilo anotó se queda
        e.append((f"{BALANCE}!A{fila}", [[concepto, valor, nota]]))
    hoja.escribir(e)

    sid = hoja.pestanas()[BALANCE]["id"]
    pesos = {"numberFormat": FORMATO_NUMERO["pesos"]}
    p: list[dict] = [*titulo(sid, 0, 3, grande=True), encabezado(sid, 2, 3)]
    for fila, _, _, tipo, _ in FILAS_BALANCE:
        r = fila - 1
        if tipo == "seccion":
            p += titulo(sid, r, 3)
        elif tipo == "total":
            p.append(
                celdas(
                    sid,
                    r,
                    r + 1,
                    0,
                    3,
                    {
                        "backgroundColor": rgb("#FDE68A"),
                        "textFormat": {"bold": True},
                        **pesos,
                    },
                    "backgroundColor,textFormat,numberFormat",
                )
            )
        else:
            color = AMARILLO_CAPTURA if tipo == "captura" else AZUL_CALCULADO
            p.append(
                celdas(
                    sid,
                    r,
                    r + 1,
                    1,
                    2,
                    {"backgroundColor": rgb(color), **pesos},
                    "backgroundColor,numberFormat",
                )
            )
    p += [ancho(sid, 0, 1, 320), ancho(sid, 1, 2, 150), ancho(sid, 2, 3, 460)]
    p.append(
        {
            "updateSheetProperties": {
                "properties": {
                    "sheetId": sid,
                    "gridProperties": {"frozenRowCount": 3},
                    "tabColorStyle": {"rgbColor": rgb("#3B82F6")},
                },
                "fields": "gridProperties.frozenRowCount,tabColorStyle",
            }
        }
    )
    hoja.lote(p)
    return ["Balance y caja (materiales = costo de receta sin Compras)"]
