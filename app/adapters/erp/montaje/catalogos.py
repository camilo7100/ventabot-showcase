"""Los catálogos con lo que dicen los datos reales (01–02/10).

- Cat_Productos: la cadena a $250.000 (20 de 22 en la sábana), el dije (nuevo)
  y la nota de cada anillo (qué es dato y qué no).
- Cat_Canales: «Clienta antigua» (la sábana anota «vieja» desde agosto).
- Cat_Materiales: el circón (estimado) y la cadena de plata ($30.000, Camilo).
- BOM: los GRAMOS de plata que dijo Camilo el 01/10 (1 huellita 2,7 g · 2
  huellitas 3 g · 3 huellitas 3,5 g · cadena 1,8 g + la cadena de $30.000; el
  dije, 1,8 g como el de la cadena) y lo que le faltaba a la receta de cada
  pieza (el circón de cada huellita, los insumos de la cadena, el dije y la
  manilla). La manilla queda con los 6 g de la receta original del ERP.
"""

from __future__ import annotations

from app.adapters.erp.montaje.comun import (
    CADENA_DE_PLATA,
    CIRCON,
    CIRCON_DEDITO,
    PLATA,
    PLATA_925,
    fila_de,
    filas_libres,
    primera_vacia,
)
from app.adapters.erp.sheets import Hoja

#: Materiales nuevos: (nombre, unidad, costo, stock mínimo, calidad, fuente).
MATERIALES_NUEVOS = (
    (
        CIRCON,
        "unidad",
        1500,
        30,
        "ESTIMADO",
        "Supuesto 01/10: piedra sintética de corazón, ~$1.000–2.000 c/u al por mayor",
    ),
    (
        CIRCON_DEDITO,
        "unidad",
        300,
        100,
        "SUPUESTO",
        "Supuesto 02/10: cada huellita lleva 4 piedritas en los deditos (antes no "
        "se contaban); ~$200–400 c/u al por mayor. El cuestionario de Lía lo pide",
    ),
    (
        CADENA_DE_PLATA,
        "unidad",
        30000,
        3,
        "REAL",
        "Camilo, 01/10: la cadena cuesta $30.000",
    ),
)
#: Gramos de plata por pieza (Camilo, 01/10). Mandan sobre la receta vieja.
GRAMOS = {
    "Anillos 1 huella": 2.7,
    "Anillos 2 huella": 3.0,
    "Anillos 3 huella": 3.5,
    "Cadena": 1.8,
    "Dije": 1.8,
}
#: Lo que se agrega a la receta si falta: (material, cantidad por pieza).
INSUMOS_DE_UNA_PIEZA = (
    ("Cera de modelado", 3),
    ("Yeso refractario", 0.05),
    ("Lija agua #220", 0.15),
    ("Lija agua #400", 0.15),
    ("Lija agua #600", 0.1),
    ("Lija agua #1000", 0.1),
    ("Pulidor liquido", 5),
    ("Gasolina encendedor", 10),
    ("Estuche básico", 1),
    ("Caja de envío", 1),
    ("Tarjeta regalo", 1),
    ("Papel seda", 1),
    ("Silicona moldes", 3),
)


def receta_deseada() -> list[tuple[str, str, float]]:
    """Las líneas que debe tener la BOM (si ya están, no se tocan; los gramos de
    plata se corrigen aparte con `GRAMOS`)."""
    salida: list[tuple[str, str, float]] = []
    for n in (1, 2, 3):
        producto = f"Anillos {n} huella"
        salida += [
            (producto, PLATA_925, GRAMOS[producto]),
            (producto, CIRCON, n),
            (producto, CIRCON_DEDITO, 4 * n),
        ]
    for producto, extra in (
        (
            "Cadena",
            (
                (PLATA_925, GRAMOS["Cadena"]),
                (CIRCON, 1),
                (CIRCON_DEDITO, 4),
                (CADENA_DE_PLATA, 1),
            ),
        ),
        ("Dije", ((PLATA_925, GRAMOS["Dije"]), (CIRCON, 1), (CIRCON_DEDITO, 4))),
        ("Manilla", ((CIRCON, 1),)),
    ):
        salida += [(producto, m, c) for m, c in INSUMOS_DE_UNA_PIEZA]
        salida += [(producto, m, c) for m, c in extra]
    return salida


def formula_bom(n: int) -> list[str]:
    return [
        f'=IF(OR($A{n}="";$B{n}="");"";$C{n}*IFERROR(INDEX(Cat_Materiales!$C$4:$C$56;'
        f"MATCH($B{n};Cat_Materiales!$A$4:$A$56;0));0))",
        f'=IF($A{n}="";"";SUMIFS(Produccion!$D:$D;Produccion!$C:$C;$A{n}))',
        f'=IF($A{n}="";"";$C{n}*$E{n})',
    ]


def _gramos(producto: str) -> str:
    g = GRAMOS.get(producto)
    return f"{g:g}".replace(".", ",") + " g" if g else ""


def montar_catalogos(hoja: Hoja, fecha: str) -> list[str]:
    productos, canales, materiales, bom = hoja.leer(
        [
            "Cat_Productos!A1:K60",
            "Cat_Canales!A1:C30",
            "Cat_Materiales!A1:H60",
            "BOM!A1:F300",
        ]
    )
    e: list[tuple[str, list[list]]] = []
    hechos: list[str] = []

    # Productos: precios de la sábana y qué es dato en el costo de cada uno.
    if n := fila_de(productos, "Cadena"):
        e.append((f"Cat_Productos!C{n}", [[250000]]))
    if fila_de(productos, "Dije") is None:
        n = primera_vacia(productos)
        e.append((f"Cat_Productos!A{n}", [["Dije", "Joyería", 180000]]))
        e.append((f"Cat_Productos!E{n}", [["=Config!$B$5"]]))
        productos = productos + [[]] * (n - len(productos))
        productos[n - 1] = ["Dije"]
        hechos.append("producto Dije")
    for producto in (*GRAMOS, "Manilla"):
        n = fila_de(productos, producto)
        if n is None:
            continue
        plata = (
            f"Plata: {_gramos(producto)} (Camilo) al precio de {PLATA}"
            if producto in GRAMOS
            else "Plata: 6 g de la receta original del ERP"
        )
        e.append(
            (
                f"Cat_Productos!I{n}",
                [
                    [
                        "ESTIMADO",
                        f"{plata}; insumos y empaque del sistema anterior. "
                        "Costo completo: hoja Costeo",
                        fecha,
                    ]
                ],
            )
        )

    if fila_de(canales, "Clienta antigua") is None:
        n = primera_vacia(canales)
        e.append(
            (
                f"Cat_Canales!A{n}",
                [
                    [
                        "Clienta antigua",
                        "Orgánico",
                        "Ya era clienta o conocía la marca (sábana: «vieja»)",
                    ]
                ],
            )
        )
        hechos.append("canal Clienta antigua")

    libres_m = filas_libres(materiales)
    for nombre, unidad, costo, minimo, calidad, fuente in MATERIALES_NUEVOS:
        if (m := fila_de(materiales, nombre)) is not None:
            actual = materiales[m - 1]
            # Lo que Lía ya dio como REAL (cuestionario) no se vuelve supuesto.
            if not (len(actual) > 5 and str(actual[5]).strip() == "REAL"):
                e.append((f"Cat_Materiales!F{m}", [[calidad, fuente]]))
            continue
        n = next(libres_m)
        e.append(
            (
                f"Cat_Materiales!A{n}",
                [[nombre, unidad, costo, minimo, "", calidad, fuente, fecha]],
            )
        )
        hechos.append(f"material {nombre}")

    # BOM: los gramos reales y lo que falta.
    hay: dict[tuple[str, str], int] = {}
    for i, f in enumerate(bom[3:], start=4):
        if len(f) > 1 and str(f[0]).strip():
            hay[(str(f[0]).strip(), str(f[1]).strip())] = i
    corregidos = 0
    for producto, g in GRAMOS.items():
        if (producto, PLATA_925) in hay:
            i = hay[(producto, PLATA_925)]
            if str(bom[i - 1][2] if len(bom[i - 1]) > 2 else "") != str(g):
                e.append((f"BOM!C{i}", [[g]]))
                corregidos += 1
    libres = filas_libres(bom)
    nuevas = 0
    for producto, material, cantidad in receta_deseada():
        if (producto, material) not in hay:
            n = next(libres)
            e.append((f"BOM!A{n}", [[producto, material, cantidad, *formula_bom(n)]]))
            hay[(producto, material)] = n
            nuevas += 1
    if corregidos:
        hechos.append(f"gramos de plata reales en {corregidos} piezas")
    if nuevas:
        hechos.append(f"{nuevas} líneas de receta")
    hoja.escribir(e)
    return hechos
