"""La hoja Costeo: cuánto cuesta de verdad cada pieza, capa por capa (01–02/10).

Las filas NO se escriben a mano: salen de las listas de abajo (supuestos,
calculados, capas, el costo mes a mes y el número para decidir). Una fórmula
nombra lo que usa —`{S:salario}` es «la celda del salario de Lía»,
`{C:plata}` «la plata de esta columna»— y `fila()` lo convierte en la celda.
Así agregar un supuesto no rompe ninguna fórmula (pasó dos veces el 01/10).

Lo que es dato y lo que es supuesto (Camilo, 01–02/10):
- REAL: los gramos de plata de cada pieza y el precio de la plata de cada mes
  (hoja Precio_Plata); la cadena (1,8 g + $30.000); los precios de venta.
- REAL: el equipo del taller ($17,4 M, lista de Camilo del 02/10: va en Activos y entra
  como depreciación). Los «~$23 M de 2025» eran ese equipo, no un gasto de cada año.
- ESTIMADO: el salario de Lía
  (como mínimo el salario mínimo 2026; el negocio es de Lía).
- SUPUESTO: lo que paga a la mamá, al tío y en diligencias, la merma de plata
  y el colchón. El cuestionario para Lía (`vb erp --cuestionario`) los pide.
Camilo es el de TI y no cobra: su tiempo no está costeado (y no debe estarlo).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.adapters.erp.montaje.comun import (
    CADENA_DE_PLATA,
    CIRCON,
    CIRCON_DEDITO,
    COSTEO,
    EMPAQUE,
    INSUMOS_DEL_TALLER,
    PARAMETRO_COSTO,
    PIEZAS,
    PLATA,
    PLATA_925,
    HojaConFormato,
    fila_de,
)
from app.adapters.erp.montaje.formato import (
    AMARILLO_CAPTURA,
    AZUL_CALCULADO,
    FORMATO_NUMERO,
    ancho,
    celdas,
    encabezado,
    limpiar,
    pestana,
    rgb,
    titulo,
)
from app.adapters.erp.sheets import Hoja, _letra


@dataclass(frozen=True)
class Supuesto:
    clave: str
    nombre: str
    valor: float
    unidad: str
    calidad: str
    porque: str


SUPUESTOS = (
    Supuesto(
        "taller",
        "Gastos del taller por año",
        0,
        "$/año",
        "SUPUESTO",
        "Arriendo, servicios y mantenimiento de cada año: FALTA (cuestionario "
        "T1–T4). Los ~$23 M de 2025 eran el equipo (Camilo, 02/10): va en Activos",
    ),
    Supuesto(
        "salario",
        "Salario de Lía (la dueña)",
        2_000_000,
        "$/mes",
        "ESTIMADO",
        "Como mínimo el salario mínimo 2026: $1.750.905 + $249.095 de auxilio de "
        "transporte (decretos 1469 y 1470 de 2025). Si gana menos, no come",
    ),
    Supuesto(
        "mama",
        "Pago a la mamá",
        600_000,
        "$/mes",
        "SUPUESTO",
        "Camilo dice que se le paga; falta la cifra (cuestionario)",
    ),
    Supuesto(
        "tio",
        "Pago al tío",
        400_000,
        "$/mes",
        "SUPUESTO",
        "Camilo dice que se le paga; falta la cifra (cuestionario)",
    ),
    Supuesto(
        "diligencias",
        "Taxis, diligencias y compras",
        200_000,
        "$/mes",
        "SUPUESTO",
        "Taxis a comprar materiales, llevar piezas… nunca se anotan",
    ),
    Supuesto(
        "merma",
        "Merma de plata (fundición)",
        0.08,
        "%",
        "SUPUESTO",
        "A la cera perdida se pierde 5–10 % de la plata; una parte se recupera",
    ),
    Supuesto(
        "colchon",
        "Colchón para lo que no se ve",
        0.10,
        "%",
        "SUPUESTO",
        "Una pieza que se repite, un envío perdido, lo que nadie anota",
    ),
)

#: (clave, nombre, fórmula, unidad, calidad, por qué): se reescriben siempre.
CALCULADOS = (
    (
        "piezas",
        "Piezas al año (ritmo actual)",
        "=ROUND(SUM(Ventas!$J$4:$J$2003)/MAX(Config!$B$13;1)*12;0)",
        "und/año",
        "CALCULADO",
        "Piezas vendidas ÷ meses con ventas × 12 (de Ventas)",
    ),
    (
        "fijos",
        "Gastos fijos por mes",
        "={S:taller}/12+{S:salario}+{S:mama}+{S:tio}+{S:diligencias}",
        "$/mes",
        "CALCULADO",
        "Taller ÷ 12 + salario de Lía + mamá + tío + diligencias (van a Gastos)",
    ),
    (
        "plata",
        "Precio de la plata hoy",
        "=Config!$B$4",
        "$/g",
        "REAL",
        f"El último mes de la hoja {PLATA} (lo que pasó Camilo)",
    ),
    (
        "deprec",
        "Depreciación de los equipos por mes",
        '=SUMIFS(Activos!$E$4:$E$50;Activos!$F$4:$F$50;"SI")',
        "$/mes",
        "CALCULADO",
        "Hoja Activos",
    ),
)


def _sumar(materiales: tuple[str, ...]) -> str:
    return "+".join(
        f'SUMIFS(BOM!$D:$D;BOM!$A:$A;{{c}}{{H}};BOM!$B:$B;"{m}")' for m in materiales
    )


#: Una pieza, de la receta al costo completo: (clave, concepto, fórmula, fuente).
#: `{c}` es la columna de la pieza y `{H}` la fila de los nombres de las piezas.
CAPAS = (
    (
        "gramos",
        "Gramos de plata",
        f'=SUMIFS(BOM!$C:$C;BOM!$A:$A;{{c}}{{H}};BOM!$B:$B;"{PLATA_925}")',
        "Camilo, 01/10: 2,7 g · 3 g · 3,5 g · cadena 1,8 g (BOM)",
    ),
    ("plata", "Plata 925", "={C:gramos}*{S:plata}", "Gramos × precio de la plata hoy"),
    ("merma", "Merma de plata", "={C:plata}*{S:merma}", "Supuesto de arriba"),
    (
        "circones",
        "Circones",
        "=" + _sumar((CIRCON, CIRCON_DEDITO)),
        "BOM: por huellita, 1 piedra de corazón y 4 de los deditos",
    ),
    (
        "cadena",
        "Cadena de plata",
        "=" + _sumar((CADENA_DE_PLATA,)),
        "Camilo, 01/10: $30.000 la cadena",
    ),
    (
        "insumos",
        "Insumos del taller",
        "=" + _sumar(INSUMOS_DEL_TALLER),
        "Cera, yeso, lijas, pulidor, gasolina, silicona",
    ),
    ("empaque", "Empaque", "=" + _sumar(EMPAQUE), "Estuche, caja, tarjeta, papel seda"),
    (
        "otros",
        "Otros materiales",
        "=SUMIFS(BOM!$D:$D;BOM!$A:$A;{c}{H})-{C:plata}-{C:circones}-{C:cadena}"
        "-{C:insumos}-{C:empaque}",
        "Lo demás de la receta (lo que se agregue a la BOM)",
    ),
    (
        "mano",
        "Mano de obra (ayudante)",
        "=IFERROR(INDEX(Cat_Productos!$E$4:$E$53;MATCH({c}{H};Cat_Productos!$A$4:$A$53;0));0)",
        "Config: por pieza",
    ),
    (
        "receta",
        "→ Costo de receta (el del ERP)",
        "=IFERROR(INDEX(Cat_Productos!$F$4:$F$53;MATCH({c}{H};Cat_Productos!$A$4:$A$53;0));0)",
        "Cat_Productos: materiales + mano de obra (lo que usan las fórmulas)",
    ),
    ("taller", "Taller", "=IF({S:piezas}=0;0;{S:taller}/{S:piezas})", "÷ piezas al año"),
    (
        "salario",
        "Salario de Lía",
        "=IF({S:piezas}=0;0;{S:salario}*12/{S:piezas})",
        "× 12 ÷ piezas al año",
    ),
    (
        "familia",
        "Familia (mamá + tío)",
        "=IF({S:piezas}=0;0;({S:mama}+{S:tio})*12/{S:piezas})",
        "× 12 ÷ piezas al año",
    ),
    (
        "diligencias",
        "Taxis y diligencias",
        "=IF({S:piezas}=0;0;{S:diligencias}*12/{S:piezas})",
        "× 12 ÷ piezas al año",
    ),
    (
        "equipos",
        "Equipos del taller (depreciación)",
        "=IF({S:piezas}=0;0;{S:deprec}*12/{S:piezas})",
        "Activos: depreciación del año ÷ piezas",
    ),
    (
        "subtotal",
        "Subtotal",
        "={C:receta}+{C:merma}+{C:taller}+{C:salario}+{C:familia}+{C:diligencias}"
        "+{C:equipos}",
        "",
    ),
    ("colchon", "Colchón", "={C:subtotal}*{S:colchon}", "Supuesto de arriba"),
    (
        "total",
        "COSTO COMPLETO ESTIMADO",
        "={C:subtotal}+{C:colchon}",
        "Lo que de verdad cuesta hoy (estimado)",
    ),
    (
        "precio",
        "Precio de lista",
        "=IFERROR(INDEX(Cat_Productos!$C$4:$C$53;MATCH({c}{H};Cat_Productos!$A$4:$A$53;0));0)",
        "Cat_Productos",
    ),
    ("antes", "Ganancia antes de publicidad", "={C:precio}-{C:total}", ""),
    (
        "publicidad",
        "Publicidad por venta (promedio)",
        "=IFERROR(SUM(Publicidad!$E$4:$E)/COUNT(Ventas!$B$4:$B$2003);0)",
        "Publicidad ÷ ventas (desde el primer mes)",
    ),
    ("neta", "Ganancia neta por pieza", "={C:antes}-{C:publicidad}", ""),
    ("margen", "Margen neto", '=IF({C:precio}=0;"";{C:neta}/{C:precio})', ""),
)
#: Cuántos meses muestra la tabla del costo mes a mes (los de la hoja de la plata).
MESES_DE_PLATA = 24

_MENSUAL = 'SUMIFS(Mensual!${col}$4:${col}$39;Mensual!$A$4:$A$39;"<="&Config!$B$12)'
RESUMEN = (
    (
        "promedio",
        "Costo completo por pieza, HOY (mezcla real)",
        "=IFERROR(SUMPRODUCT({C:total:B}:{C:total:E};COUNTIF(Ventas!$C$4:$C$2003;"
        '{H:B}:{H:E}))/SUMPRODUCT(COUNTIF(Ventas!$C$4:$C$2003;{H:B}:{H:E}));"")',
        "Con la plata de hoy, pesado por lo que se vende. Es el que usa el marketing",
    ),
    (
        "real",
        "Costo completo por pieza en lo vendido (con la plata de cada mes)",
        "=IFERROR(("
        + _MENSUAL.format(col="I")
        + "+"
        + _MENSUAL.format(col="M")
        + "+"
        + _MENSUAL.format(col="N")
        + ")/"
        + _MENSUAL.format(col="F")
        + ';"")',
        "Costo de lo vendido + gastos + depreciación ÷ piezas (Mensual, todo el año)",
    ),
    (
        "receta1",
        "Costo de receta del ERP (1 huellita)",
        "={C:receta:B}",
        "Sin taller ni salario",
    ),
    (
        "config",
        "Costo que usa el ERP y el marketing (Config)",
        "=IFERROR(INDEX(Config!$B:$B;"
        'MATCH("Costo real por anillo ($)";Config!$A:$A;0));"")',
        "Config fila 15: es el «hoy» de arriba",
    ),
)

# --- dónde queda cada cosa -------------------------------------------------
FILA_SUPUESTOS = 6
_FILAS: dict[str, int] = {}
n = FILA_SUPUESTOS
for s in SUPUESTOS:
    _FILAS[f"S:{s.clave}"] = n
    n += 1
for clave, *_ in CALCULADOS:
    _FILAS[f"S:{clave}"] = n
    n += 1
FILA_SECCION_CAPAS = n + 1
FILA_PIEZAS = FILA_SECCION_CAPAS + 1  # «Concepto | Anillos 1 huella | …»
n = FILA_PIEZAS + 1
for clave, *_ in CAPAS:
    _FILAS[f"C:{clave}"] = n
    n += 1
FILA_SECCION_MESES = n + 1
FILA_ENCABEZADO_MESES = FILA_SECCION_MESES + 1
FILA_PRIMER_MES = FILA_ENCABEZADO_MESES + 1
n = FILA_PRIMER_MES + MESES_DE_PLATA
FILA_SECCION_RESUMEN = n + 1
n = FILA_SECCION_RESUMEN + 1
for clave, *_ in RESUMEN:
    _FILAS[f"R:{clave}"] = n
    n += 1
FILA_NOTA = n + 1
ULTIMA_FILA = FILA_NOTA + 1
del n


def fila(clave: str) -> int:
    """La fila de `S:salario`, `C:total` o `R:promedio` en Costeo."""
    return _FILAS[clave]


def celda(clave: str) -> str:
    """`S:merma` → «Costeo!$B$12» (para usar desde otra hoja)."""
    return f"{COSTEO}!$B${fila(clave)}"


def _resolver(formula: str, col: str = "B") -> str:
    def cambio(m: re.Match) -> str:
        tipo, clave, columna = m.group(1), m.group(2), m.group(3)
        if tipo == "H":
            return f"{clave}${FILA_PIEZAS}"
        if tipo == "S":
            return f"$B${fila('S:' + clave)}"
        return f"{columna or col}{fila(tipo + ':' + clave)}"

    texto = re.sub(r"\{([SCRH]):([a-zA-Z0-9]+)(?::([A-Z]))?\}", cambio, formula)
    return texto.replace("{c}", col).replace("{H}", f"${FILA_PIEZAS}")


def montar_costeo(hoja: Hoja) -> list[str]:
    hoja.asegurar_hoja(COSTEO)
    (actual,) = hoja.leer([f"{COSTEO}!A1:F{ULTIMA_FILA + 20}"])
    # Lo que Camilo cambió en un supuesto se guarda por NOMBRE (no por fila).
    anotado = {
        str(f[0]).strip(): f
        for f in actual[FILA_SUPUESTOS - 1 : FILA_SUPUESTOS + 20]
        if len(f) > 1 and str(f[0]).strip() and str(f[1]).strip()
    }
    cols = [_letra(1 + j) for j in range(len(PIEZAS))]
    bloque: list[list] = [[""] * 6 for _ in range(ULTIMA_FILA + 20)]

    def poner(n: int, valores: list) -> None:
        bloque[n - 1] = (list(valores) + [""] * 6)[:6]

    poner(1, ["🧮 COSTEO — Cuánto cuesta de verdad cada pieza (y de dónde sale)"])
    poner(
        2,
        [
            "Amarillo = lo cambias TÚ. Azul = se calcula solo. La receta (BOM) es lo que "
            "usan las fórmulas del ERP; aquí se le suma lo que la receta no ve. La plata "
            f"cambia cada mes: su precio está en la hoja {PLATA}."
        ],
    )
    poner(4, ["▼ SUPUESTOS — cambia SOLO las celdas amarillas"])
    poner(5, ["Supuesto", "Valor", "Unidad", "Calidad", "Por qué / de dónde"])
    for s in SUPUESTOS:
        f = anotado.get(s.nombre, [])
        valor = f[1] if len(f) > 1 else s.valor
        # Lo que dio Lía (cuestionario) queda REAL, con su fuente.
        real = len(f) > 4 and str(f[3]).strip() == "REAL" and s.calidad != "REAL"
        calidad, porque = (f[3], f[4]) if real else (s.calidad, s.porque)
        poner(fila(f"S:{s.clave}"), [s.nombre, valor, s.unidad, calidad, porque])
    for clave, nombre, formula, unidad, calidad, porque in CALCULADOS:
        poner(fila(f"S:{clave}"), [nombre, _resolver(formula), unidad, calidad, porque])
    poner(
        FILA_SECCION_CAPAS, ["▼ COSTO DE UNA PIEZA, CAPA POR CAPA (con la plata de hoy)"]
    )
    poner(FILA_PIEZAS, ["Concepto", *PIEZAS, "De dónde sale"])
    for clave, concepto, formula, fuente in CAPAS:
        poner(
            fila(f"C:{clave}"),
            [concepto, *(_resolver(formula, c) for c in cols), fuente],
        )
    poner(FILA_SECCION_MESES, ["▼ EL COSTO MES A MES (la plata cambia cada mes)"])
    poner(FILA_ENCABEZADO_MESES, ["Mes", "Plata $/g", *PIEZAS[:3], PIEZAS[3]][:6])
    for k in range(MESES_DE_PLATA):
        n = FILA_PRIMER_MES + k
        origen = 4 + k  # fila de la hoja de la plata
        mes = f"{PLATA}!$A${origen}"
        precio = f"{PLATA}!$B${origen}"
        costos = [
            f'=IF(OR({mes}="";{precio}="");"";{c}${fila("C:total")}+{c}${fila("C:gramos")}'
            f"*(1+{_resolver('{S:merma}')})*({precio}-{_resolver('{S:plata}')})"
            f"*(1+{_resolver('{S:colchon}')}))"
            for c in cols
        ]
        poner(
            n,
            [
                f'=IF({mes}="";"";DATE(INT({mes}/100);MOD({mes};100);1))',
                f'=IF({mes}="";"";{precio})',
                *costos,
            ][:6],
        )
    poner(FILA_SECCION_RESUMEN, ["▼ EL NÚMERO PARA DECIDIR"])
    for clave, concepto, formula, fuente in RESUMEN:
        formula = re.sub(
            r"\{C:([a-z0-9]+):([A-Z])\}",
            lambda m: f"{m.group(2)}${fila('C:' + m.group(1))}",
            formula,
        )
        formula = re.sub(
            r"\{H:([A-Z])\}", lambda m: f"{m.group(1)}${FILA_PIEZAS}", formula
        )
        poner(fila(f"R:{clave}"), [concepto, formula, "", "", "", fuente])
    poner(
        FILA_NOTA,
        [
            "Lo que es DATO (gramos, precio de la plata, cadena, precios) y lo que es "
            "supuesto está en la columna Calidad. El cuestionario para Lía pide lo que "
            "falta (vb erp --cuestionario)."
        ],
    )
    hoja.escribir([(f"{COSTEO}!A1", bloque)])
    return ["Costeo"]


def formato_costeo(hoja: HojaConFormato) -> None:
    sid = hoja.pestanas()[COSTEO]["id"]
    pesos = {"numberFormat": FORMATO_NUMERO["pesos"]}
    pct = {"numberFormat": FORMATO_NUMERO["pct"]}
    azul = {"backgroundColor": rgb(AZUL_CALCULADO)}
    p: list[dict] = [limpiar(sid, 0, ULTIMA_FILA + 20, 0, 6)]
    p += titulo(sid, 0, 6, grande=True)
    for n in (4, FILA_SECCION_CAPAS, FILA_SECCION_MESES, FILA_SECCION_RESUMEN):
        p += titulo(sid, n - 1, 6)
    for n in (5, FILA_PIEZAS, FILA_ENCABEZADO_MESES):
        p.append(encabezado(sid, n - 1, 6))
    for s in SUPUESTOS:
        r = fila(f"S:{s.clave}") - 1
        formato = pct if s.unidad == "%" else pesos
        p.append(
            celdas(
                sid,
                r,
                r + 1,
                1,
                2,
                {"backgroundColor": rgb(AMARILLO_CAPTURA), **formato},
                "backgroundColor,numberFormat",
            )
        )
    for clave, *_, unidad, _calidad, _porque in CALCULADOS:
        r = fila(f"S:{clave}") - 1
        formato = (
            {"numberFormat": FORMATO_NUMERO["entero"]}
            if unidad.startswith("und")
            else pesos
        )
        p.append(
            celdas(
                sid, r, r + 1, 1, 2, {**azul, **formato}, "backgroundColor,numberFormat"
            )
        )
    primera, ultima = fila(f"C:{CAPAS[0][0]}") - 1, fila(f"C:{CAPAS[-1][0]}")
    p.append(
        celdas(
            sid, primera, ultima, 1, 5, {**azul, **pesos}, "backgroundColor,numberFormat"
        )
    )
    r = fila("C:gramos") - 1
    p.append(
        celdas(
            sid,
            r,
            r + 1,
            1,
            5,
            {"numberFormat": FORMATO_NUMERO["gramos"]},
            "numberFormat",
        )
    )
    r = fila("C:margen") - 1
    p.append(celdas(sid, r, r + 1, 1, 5, pct, "numberFormat"))
    r = fila("C:receta") - 1
    p.append(celdas(sid, r, r + 1, 0, 6, {"textFormat": {"bold": True}}, "textFormat"))
    r = fila("C:total") - 1
    p.append(
        celdas(
            sid,
            r,
            r + 1,
            0,
            6,
            {
                "backgroundColor": rgb("#FDE68A"),
                "textFormat": {"bold": True, "fontSize": 12},
            },
            "backgroundColor,textFormat",
        )
    )
    r0, r1 = FILA_PRIMER_MES - 1, FILA_PRIMER_MES - 1 + MESES_DE_PLATA
    p.append(
        celdas(sid, r0, r1, 0, 1, {"numberFormat": FORMATO_NUMERO["mes"]}, "numberFormat")
    )
    p.append(celdas(sid, r0, r1, 1, 6, {**azul, **pesos}, "backgroundColor,numberFormat"))
    r0, r1 = fila(f"R:{RESUMEN[0][0]}") - 1, fila(f"R:{RESUMEN[-1][0]}")
    p.append(
        celdas(
            sid,
            r0,
            r1,
            1,
            2,
            {**azul, **pesos, "textFormat": {"bold": True}},
            "backgroundColor,numberFormat,textFormat",
        )
    )
    p += [ancho(sid, 0, 1, 330), ancho(sid, 1, 5, 130), ancho(sid, 5, 6, 440)]
    p.append(pestana(sid, "#F59E0B", 2))
    hoja.lote(p)


CHEQUEO = "El costo de Config no es el de Costeo"


def enlazar(hoja: Hoja, fecha: str) -> list[str]:
    """Config («Costo real por anillo») = el costo de hoy de Costeo; y la
    validación 16 avisa si alguien lo cambia a mano (02/10: «conecta el
    marketing con el costo que calculaste»; antes era un número escrito)."""
    config, validaciones = hoja.leer(["Config!A1:F40", "Validaciones!A1:E30"])
    n = fila_de(config, PARAMETRO_COSTO) or next(
        i
        for i in range(4, 41)
        if i > len(config) or not (config[i - 1] and str(config[i - 1][0]).strip())
    )
    hoy = celda("R:promedio")
    v = next(
        (
            i + 1
            for i, f in enumerate(validaciones)
            if len(f) > 1 and str(f[0]).strip() in ("16", "16.0")
        ),
        19,
    )
    hoja.escribir(
        [
            (
                f"Config!A{n}",
                [
                    [
                        PARAMETRO_COSTO,
                        f"={hoy}",
                        "$/und",
                        "CALCULADO",
                        "Hoja Costeo: costo completo hoy (plata del último mes, "
                        "salario de Lía, taller, familia, diligencias y colchón). "
                        "Lo usa el marketing",
                        fecha,
                    ]
                ],
            ),
            (
                f"Validaciones!A{v}",
                [
                    [
                        16,
                        CHEQUEO,
                        f"=IF(ABS(N(Config!$B${n})-N({hoy}))<1;0;1)",
                        f'=IF($C{v}=0;"✅ OK";"⚠️ REVISAR")',
                        f"Config fila {n} debe ser =Costeo (lo deja así vb erp --montar)",
                    ]
                ],
            ),
        ]
    )
    return [f"Config fila {n} = Costeo (costo de hoy); validación 16"]
