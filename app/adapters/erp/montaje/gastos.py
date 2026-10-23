"""Los gastos fijos estimados en la hoja Gastos, mes a mes (01–02/10).

Una fila por mes con ventas para cada gasto de Costeo, con la FÓRMULA que
apunta a su supuesto: cambiar el supuesto en Costeo cambia todos los meses. Así
el estado de resultados (Mensual, Dashboard, el panel) los descuenta.

- El salario de Lía (la dueña), el taller, la mamá, el tío y las
  diligencias: el valor mensual de Costeo.
- El colchón: su % sobre lo que de verdad costó ESE mes (costo de lo vendido con
  la plata del mes + gastos fijos + depreciación). La merma ya va en el costo de
  cada venta (`Ventas!T`, ver `plata.py`), no aquí.

Cuando Lía anote un gasto real del mes, la fila estimada de ese concepto se
borra (lo dice la nota). Las filas viejas que ya no son de Costeo (la «merma y
colchón» del 01/10) se quitan solas.
"""

from __future__ import annotations

from app.adapters.erp.montaje.costeo import celda
from app.adapters.erp.sheets import Hoja

MARCA_GASTO = "COSTEO"

#: Los gastos que anota Lía cada mes (plantilla de `vb erp --cuestionario`):
#: (concepto, categoría, el estimado de Costeo que ese mes deja de contarse, o
#: None). Si anota el arriendo de octubre, octubre ya no usa «taller ÷ 12»: hay
#: que anotar TODO lo del taller ese mes (lo dice la plantilla).
GASTOS_DE_LIA: tuple[tuple[str, str, str | None], ...] = (
    ("Arriendo del taller", "Operativo", "taller"),
    ("Servicios del taller (luz, agua, gas, internet)", "Operativo", "taller"),
    ("Mantenimiento, reparaciones y herramientas", "Operativo", "taller"),
    ("Otros gastos del taller", "Operativo", "taller"),
    ("Salario de Lía", "Personal", "salario"),
    ("Pago a la mamá", "Personal", "mama"),
    ("Pago al tío", "Personal", "tio"),
    ("Pago extra al ayudante", "Personal", None),
    ("Taxis y diligencias", "Logística", "diligencias"),
    ("Envíos pagados por el negocio", "Logística", None),
    ("Comisiones de banco o Nequi", "Financiero", None),
    ("Contador, impuestos y Cámara de Comercio", "Administrativo", None),
    ("Página web, dominio y apps", "Administrativo", None),
    ("Celular y plan de datos", "Administrativo", None),
    ("Publicidad fuera de Meta", "Comercial", None),
    ("Muestras, regalos y reposiciones", "Comercial", None),
    ("Otro", "Otro", None),
)
_REEMPLAZA = {concepto: clave for concepto, _, clave in GASTOS_DE_LIA if clave}


def gastos_fijos() -> tuple[tuple[str, str, str, str], ...]:
    """(clave, concepto, categoría, fórmula con {mes} = AAAAMM)."""
    return (
        ("salario", "Salario de Lía (la dueña)", "Personal", f"={celda('S:salario')}"),
        (
            "taller",
            "Taller (gastos del año ÷ 12)",
            "Operativo",
            f"={celda('S:taller')}/12",
        ),
        ("mama", "Pago a la mamá", "Personal", f"={celda('S:mama')}"),
        ("tio", "Pago al tío", "Personal", f"={celda('S:tio')}"),
        (
            "diligencias",
            "Taxis, diligencias y compras",
            "Logística",
            f"={celda('S:diligencias')}",
        ),
        (
            "colchon",
            "Colchón (lo que no se ve)",
            "Otro",
            f"={celda('S:colchon')}*(SUMIFS(Ventas!$T$4:$T$2003;Ventas!$X$4:$X$2003;{{mes}})"
            f"+{celda('S:fijos')}+{celda('S:deprec')})",
        ),
    )


def montar_gastos(hoja: Hoja, meses: list[int]) -> list[str]:
    """Las filas de gasto estimado de cada mes (`meses` = AAAAMM con ventas)."""
    (filas,) = hoja.leer(["Gastos!A3:G2000"])
    hay: dict[str, int] = {}
    libres: list[int] = []
    #: (mes, estimado) que Lía ya anotó de verdad: ese mes no se estima.
    reales: set[tuple[int, str]] = set()
    for i, f in enumerate(filas[1:]):
        n = 4 + i
        nota = str(f[5]).strip() if len(f) > 5 else ""
        if nota.startswith(MARCA_GASTO):
            hay[nota.split(" · ")[0]] = n
        elif not (f and str(f[0]).strip()):
            libres.append(n)
        elif (clave := _REEMPLAZA.get(str(f[1]).strip() if len(f) > 1 else "")) and (
            mes := _mes(f[6] if len(f) > 6 else "")
        ):
            reales.add((mes, clave))
    siguiente = 4 + len(filas[1:])
    e: list[tuple[str, list[list]]] = []
    vigentes: set[str] = set()
    nuevas = 0
    for mes in meses:
        clave_mes = f"{mes // 100}-{mes % 100:02d}"
        for clave, concepto, categoria, formula in gastos_fijos():
            if (mes, clave) in reales:
                continue
            marca = f"{MARCA_GASTO} {clave_mes} {clave}"
            vigentes.add(marca)
            fila = [
                f"{clave_mes}-01",
                concepto,
                categoria,
                formula.format(mes=mes),
                "ESTIMADO",
                f"{marca} · estimado: se cambia en la hoja Costeo (si anotas el real, "
                "borra esta fila)",
            ]
            if marca in hay:
                n = hay[marca]
            else:
                n = libres.pop(0) if libres else siguiente
                if n == siguiente:
                    siguiente += 1
                nuevas += 1
            e.append((f"Gastos!A{n}", [fila]))
    viejas = [n for marca, n in hay.items() if marca not in vigentes]
    for n in viejas:
        e.append((f"Gastos!A{n}", [[""] * 6]))
    hoja.escribir(e)
    return [
        f"Gastos: {len(meses)} meses × {len(gastos_fijos())} estimados (+{nuevas}"
        + (f", −{len(viejas)} viejas" if viejas else "")
        + ")"
    ]


def _mes(valor) -> int | None:
    """La MesKey (AAAAMM) de una fila de Gastos, como la calcula la hoja."""
    try:
        mes = int(float(str(valor).strip()))
    except ValueError:
        return None
    return mes if 200001 <= mes <= 209912 else None
