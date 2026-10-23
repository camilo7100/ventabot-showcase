"""La hoja Gráficas: tablas con fórmulas y su gráfica al lado, POR PERÍODO (02/10).

Camilo, 02/10: «en todos los apartados del panel y del ERP ponme filtros de
fechas: año o mes». Arriba (fila 3) hay un **Año** y un **Mes** (0 = todo el
año), con lista desplegable:

- Mes a mes, piezas por mes y clientas: los 12 meses del AÑO elegido.
- Qué se vende, canal, tallas, colores y día de la semana: el PERÍODO elegido
  (el año entero o solo ese mes).
- El costo de un anillo por capas: el de hoy (Costeo).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.adapters.erp.montaje import costeo
from app.adapters.erp.montaje.comun import (
    CANALES,
    COLORES,
    DIAS,
    GRAFICAS,
    PRODUCTOS,
    TALLAS,
    HojaConFormato,
)
from app.adapters.erp.montaje.formato import (
    AMARILLO_CAPTURA,
    AZUL_CALCULADO,
    FORMATO_NUMERO,
    ancho,
    celdas,
    encabezado,
    lista,
    pestana,
    rango,
    rgb,
    titulo,
)

#: El período elegido (fila 3): desde y hasta como AAAAMM.
DESDE, HASTA = "$F$3", "$H$3"
EN_PERIODO = f';Ventas!$X$4:$X$2003;">="&{DESDE};Ventas!$X$4:$X$2003;"<="&{HASTA}'
PRIMERA_FILA_DE_BLOQUES = 4  # 0-based: el primer título va en la fila 5


@dataclass
class Bloque:
    titulo: str
    encabezados: list[str]
    filas: list[list]
    #: (tipo, título, columnas de serie [(índice, "COLUMN"/"LINE", eje)], apilada)
    graficas: list[tuple] = field(default_factory=list)
    formatos: dict[int, str] = field(default_factory=dict)  # columna → formato
    inicio: int = 0  # fila (0-based) del título; la pone `bloques()`


def _del_mes(col: str) -> str:
    """El valor de la columna `col` de Mensual para el mes k del año elegido."""
    return (
        f"IFERROR(INDEX(Mensual!${col}$4:${col}$39;"
        "MATCH($B$3*100+{k};Mensual!$A$4:$A$39;0));0)"
    )


def bloques() -> list[Bloque]:
    salida: list[Bloque] = []
    doce = range(12)

    def si(expr: str) -> str:
        return '=IF($A{r}="";"";' + expr + ")"

    mes = '=IF($B$3*100+{k}>Config!$B$12;"";DATE($B$3;{k};1))'
    salida.append(
        Bloque(
            "Mes a mes del año elegido: lo que entra, lo que sale y lo que queda",
            [
                "Mes",
                "Ingresos",
                "Costo de lo vendido",
                "Publicidad",
                "Gastos fijos",
                "Utilidad operativa",
                "Piezas",
                "ROAS",
            ],
            [
                [
                    mes,
                    si(_del_mes("E")),
                    si(_del_mes("I")),
                    si(_del_mes("L")),
                    si(_del_mes("M")),
                    si(_del_mes("O")),
                    si(_del_mes("F")),
                    '=IF($A{r}="";"";IFERROR('
                    + _del_mes("E")
                    + "/"
                    + _del_mes("L")
                    + ';""))',
                ]
                for _ in doce
            ],
            [
                (
                    "COMBO",
                    "Ingresos, publicidad, gastos y utilidad",
                    [
                        (1, "COLUMN", "LEFT_AXIS"),
                        (3, "COLUMN", "LEFT_AXIS"),
                        (4, "COLUMN", "LEFT_AXIS"),
                        (5, "LINE", "LEFT_AXIS"),
                    ],
                    False,
                ),
                (
                    "COMBO",
                    "Publicidad y lo que devuelve (ROAS)",
                    [(3, "COLUMN", "LEFT_AXIS"), (7, "LINE", "RIGHT_AXIS")],
                    False,
                ),
            ],
            {
                0: "mes",
                1: "pesos",
                2: "pesos",
                3: "pesos",
                4: "pesos",
                5: "pesos",
                7: "x",
            },
        )
    )
    salida.append(
        Bloque(
            "Piezas por mes y producto (año elegido)",
            ["Mes", *PRODUCTOS],
            [
                ["=MES_DEL_AÑO"]
                + [
                    si(
                        "COUNTIFS(Ventas!$X$4:$X$2003;$B$3*100+{k};"
                        f'Ventas!$C$4:$C$2003;"{p}")'
                    )
                    for p in PRODUCTOS
                ]
                for _ in doce
            ],
            [
                (
                    "COLUMN",
                    "Piezas por mes (apiladas por producto)",
                    [(j, "COLUMN", "LEFT_AXIS") for j in range(1, len(PRODUCTOS) + 1)],
                    True,
                )
            ],
            {0: "mes"},
        )
    )
    salida.append(
        Bloque(
            "Clientas nuevas, las que vuelven y la caja (año elegido)",
            ["Mes", "Clientas nuevas", "Compras repetidas", "Cobrado", "Caja acumulada"],
            [
                [
                    "=MES_DEL_AÑO",
                    si(_del_mes("Q")),
                    si(_del_mes("G") + "-" + _del_mes("Q")),
                    si(_del_mes("S")),
                    si(_del_mes("V")),
                ]
                for _ in doce
            ],
            [
                (
                    "COLUMN",
                    "Clientas nuevas y compras repetidas",
                    [(1, "COLUMN", "LEFT_AXIS"), (2, "COLUMN", "LEFT_AXIS")],
                    True,
                ),
                (
                    "LINE",
                    "Caja acumulada (cobros − salidas)",
                    [(4, "LINE", "LEFT_AXIS")],
                    False,
                ),
            ],
            {0: "mes", 3: "pesos", 4: "pesos"},
        )
    )
    total = f"SUMIFS(Ventas!$O$4:$O$2003{EN_PERIODO})"
    salida.append(
        Bloque(
            "Qué se vende (período elegido)",
            ["Producto", "Piezas", "Ingresos", "% de los ingresos"],
            [
                [
                    p,
                    f'=COUNTIFS(Ventas!$C$4:$C$2003;"{p}"{EN_PERIODO})',
                    f'=SUMIFS(Ventas!$O$4:$O$2003;Ventas!$C$4:$C$2003;"{p}"{EN_PERIODO})',
                    f'=IF({total}=0;"";C{{r}}/{total})',
                ]
                for p in PRODUCTOS
            ],
            [("PIE", "Mezcla de piezas vendidas", [(1, "", "")], False)],
            {2: "pesos", 3: "pct"},
        )
    )
    salida.append(
        Bloque(
            "De dónde vino la clienta (período elegido)",
            ["Canal", "Ventas", "Ingresos"],
            [
                [
                    c,
                    f'=COUNTIFS(Ventas!$E$4:$E$2003;"{c}"{EN_PERIODO})',
                    f'=SUMIFS(Ventas!$O$4:$O$2003;Ventas!$E$4:$E$2003;"{c}"{EN_PERIODO})',
                ]
                for c in CANALES
            ],
            [("PIE", "Canal de la clienta (ventas)", [(1, "", "")], False)],
            {2: "pesos"},
        )
    )
    salida.append(
        Bloque(
            "Tallas más pedidas (anillos, período elegido)",
            ["Talla", "Anillos"],
            [
                [
                    t.replace("TALLA ", ""),
                    f'=COUNTIFS(Ventas!$G$4:$G$2003;"{t}"{EN_PERIODO})',
                ]
                for t in TALLAS
            ]
            + [
                [
                    "Otras",
                    f'=COUNTIFS(Ventas!$C$4:$C$2003;"Anillos*"{EN_PERIODO})-SUM(B{{a}}:B{{b}})',
                ]
            ],
            [("COLUMN", "Anillos por talla", [(1, "COLUMN", "LEFT_AXIS")], False)],
            {},
        )
    )
    salida.append(
        Bloque(
            "Colores de circón (ventas que lo llevan, período elegido)",
            ["Color", "Ventas"],
            [
                [nombre, f'=COUNTIFS(Ventas!$H$4:$H$2003;"{patron}"{EN_PERIODO})']
                for nombre, patron in COLORES
            ],
            [("BAR", "Colores más pedidos", [(1, "BAR", "BOTTOM_AXIS")], False)],
            {},
        )
    )
    en_periodo = (
        '(Ventas!$B$4:$B$2003<>"")*(Ventas!$X$4:$X$2003>=' + DESDE + ")"
        "*(Ventas!$X$4:$X$2003<=" + HASTA + ")"
    )
    salida.append(
        Bloque(
            "Qué día se vende (período elegido)",
            ["Día", "Ventas", "Ingresos"],
            [
                [
                    d,
                    f"=SUMPRODUCT({en_periodo}*(WEEKDAY(Ventas!$B$4:$B$2003;2)={k}))",
                    f"=SUMPRODUCT({en_periodo}*(WEEKDAY(Ventas!$B$4:$B$2003;2)={k})"
                    "*Ventas!$O$4:$O$2003)",
                ]
                for k, d in enumerate(DIAS, 1)
            ],
            [
                (
                    "COLUMN",
                    "Ventas por día de la semana",
                    [(1, "COLUMN", "LEFT_AXIS")],
                    False,
                )
            ],
            {2: "pesos"},
        )
    )

    def capa(*claves: str) -> str:
        return "=" + "+".join(f"{costeo.COSTEO}!B{costeo.fila('C:' + c)}" for c in claves)

    capas = (
        ("Plata (con merma)", capa("plata", "merma")),
        ("Circón", capa("circones")),
        ("Insumos y otros materiales", capa("insumos", "otros", "cadena")),
        ("Empaque", capa("empaque")),
        ("Mano de obra", capa("mano")),
        ("Salario de Lía", capa("salario")),
        ("Taller", capa("taller")),
        ("Familia", capa("familia")),
        ("Taxis y diligencias", capa("diligencias")),
        ("Equipos (depreciación)", capa("equipos")),
        ("Colchón", capa("colchon")),
    )
    salida.append(
        Bloque(
            "De qué está hecho el costo de un anillo de 1 huellita, hoy (Costeo)",
            ["Capa", "Pesos"],
            [[n, f] for n, f in capas],
            [("PIE", "Costo completo de un anillo, por capa", [(1, "", "")], False)],
            {1: "pesos"},
        )
    )
    # Las filas: cada bloque deja al menos 21 (la gráfica mide ~18).
    fila = PRIMERA_FILA_DE_BLOQUES
    for b in salida:
        b.inicio = fila
        fila += max(len(b.filas) + 4, 21)
    primero = salida[0]
    for b in salida:
        a, z = b.inicio + 3, b.inicio + 2 + len(b.filas) - 1
        for i, f in enumerate(b.filas):
            r = b.inicio + 3 + i  # 1-based
            b.filas[i] = [
                str(c)
                .replace("MES_DEL_AÑO", f"$A{primero.inicio + 3 + i}")
                .format(r=r, k=i + 1, a=a, b=z)
                if isinstance(c, str)
                else c
                for c in f
            ]
    return salida


def _grafica(sid: int, b: Bloque, g: tuple, columna: int) -> dict:
    tipo, nombre, series, apilada = g
    r0, r1 = b.inicio + 1, b.inicio + 2 + len(b.filas)  # encabezado + datos
    posicion = {
        "overlayPosition": {
            "anchorCell": {
                "sheetId": sid,
                "rowIndex": b.inicio + 1,
                "columnIndex": columna,
            },
            "widthPixels": 560,
            "heightPixels": 330,
        }
    }
    if tipo == "PIE":
        spec = {
            "title": nombre,
            "pieChart": {
                "legendPosition": "RIGHT_LEGEND",
                "domain": rango(sid, r0, r1, 0),
                "series": rango(sid, r0, r1, series[0][0]),
                "pieHole": 0.45,
            },
        }
    else:
        basico = {
            "chartType": tipo,
            "legendPosition": "BOTTOM_LEGEND",
            "headerCount": 1,
            "domains": [{"domain": rango(sid, r0, r1, 0)}],
            "series": [
                {"series": rango(sid, r0, r1, c), "targetAxis": eje, "type": t}
                for c, t, eje in series
            ],
        }
        if apilada:
            basico["stackedType"] = "STACKED"
        spec = {"title": nombre, "basicChart": basico}
    return {"addChart": {"chart": {"spec": spec, "position": posicion}}}


def montar_graficas(hoja: HojaConFormato) -> list[str]:
    hoja.asegurar_hoja(GRAFICAS)
    (actual,) = hoja.leer([f"'{GRAFICAS}'!A1:H3"])
    fila3 = actual[2] if len(actual) > 2 else []
    # El período que Camilo dejó elegido se queda (si ya había uno).
    anio = (
        fila3[1] if len(fila3) > 1 and str(fila3[1]).strip() else "=INT(Config!$B$12/100)"
    )
    mes = fila3[3] if len(fila3) > 3 and str(fila3[3]).strip() != "" else 0
    lista_bloques = bloques()
    final = max(b.inicio + 3 + len(b.filas) for b in lista_bloques) + 25
    e: list[tuple[str, list[list]]] = [
        # Primero todo en blanco: una versión anterior tenía los bloques en otras filas.
        (f"'{GRAFICAS}'!A4", [[""] * 9 for _ in range(final)]),
        (
            f"'{GRAFICAS}'!A1",
            [
                [
                    "📈 GRÁFICAS — El negocio en dibujos (NO EDITAR: todo sale de "
                    "Ventas, "
                    "Mensual, Publicidad, Gastos y Costeo)"
                ],
                [
                    "Elige el AÑO y el MES (0 = todo el año) en las celdas amarillas: "
                    "las "
                    "tablas y sus gráficas se recalculan solas."
                ],
                [
                    "Año ▼",
                    anio,
                    "Mes ▼ (0 = todo el año)",
                    mes,
                    "Desde",
                    "=$B$3*100+IF($D$3=0;1;$D$3)",
                    "Hasta",
                    "=$B$3*100+IF($D$3=0;12;$D$3)",
                ],
            ],
        ),
    ]
    for b in lista_bloques:
        e.append((f"'{GRAFICAS}'!A{b.inicio + 1}", [[f"▼ {b.titulo.upper()}"]]))
        e.append((f"'{GRAFICAS}'!A{b.inicio + 2}", [b.encabezados]))
        e.append((f"'{GRAFICAS}'!A{b.inicio + 3}", b.filas))
    hoja.escribir(e)

    info = hoja.pestanas()
    sid = info[GRAFICAS]["id"]
    pedidos: list[dict] = [
        {"deleteEmbeddedObject": {"objectId": g}} for g in info[GRAFICAS]["graficas"]
    ]
    pedidos += titulo(sid, 0, 26, grande=True)
    pedidos += [
        celdas(sid, 2, 3, 0, 8, {"textFormat": {"bold": True}}, "textFormat"),
        celdas(
            sid, 2, 3, 1, 2, {"backgroundColor": rgb(AMARILLO_CAPTURA)}, "backgroundColor"
        ),
        celdas(
            sid, 2, 3, 3, 4, {"backgroundColor": rgb(AMARILLO_CAPTURA)}, "backgroundColor"
        ),
        lista(sid, 2, 1, "=Config!$H$4:$H$14"),
        lista(sid, 2, 3, "=Config!$I$4:$I$16"),
        ancho(sid, 0, 1, 190),
        ancho(sid, 1, 9, 118),
    ]
    for b in lista_bloques:
        columnas = len(b.encabezados)
        pedidos += titulo(sid, b.inicio, columnas)
        pedidos.append(encabezado(sid, b.inicio + 1, columnas))
        pedidos.append(
            celdas(
                sid,
                b.inicio + 2,
                b.inicio + 2 + len(b.filas),
                0,
                columnas,
                {"backgroundColor": rgb(AZUL_CALCULADO)},
                "backgroundColor",
            )
        )
        for col, tipo in b.formatos.items():
            pedidos.append(
                celdas(
                    sid,
                    b.inicio + 2,
                    b.inicio + 2 + len(b.filas),
                    col,
                    col + 1,
                    {"numberFormat": FORMATO_NUMERO[tipo]},
                    "numberFormat",
                )
            )
        for k, g in enumerate(b.graficas):
            pedidos.append(_grafica(sid, b, g, 9 + 7 * k))
    pedidos.append(pestana(sid, "#34A853", 3))
    hoja.lote(pedidos)
    return [
        f"Gráficas: {len(lista_bloques)} tablas, "
        f"{sum(len(b.graficas) for b in lista_bloques)} gráficas, con año y mes"
    ]
