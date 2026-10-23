"""El marketing y el ERP, en las dos direcciones (01/10).

ERP ← MARKETING · `sincronizar_publicidad`
    Llena la hoja de captura `Publicidad` con la pauta real (una fila por
    campaña y mes; ver `app/domain/erp_marketing.py`). Mismas reglas que con
    las ventas: solo columnas de captura, buscadas por NOMBRE; las filas del
    bot llevan `Origen_Ref` y las de Camilo no se tocan.

ERP → PANEL · `asegurar_rank_ciudades` y `foto`
    `Rank_Ciudades` es una hoja de procesamiento nueva (fórmulas sobre
    `Ventas`): unidades e ingresos por ciudad, y Bogotá·Medellín·Cali contra el
    resto (la prueba «Resto de Colombia» del marketing). `foto` lee lo que el
    panel muestra del ERP —el costo de cada producto, el estado de resultados
    de los últimos meses, las ciudades, las validaciones en «REVISAR»— y lo
    devuelve como un dict que se guarda junto a la carpeta de marketing.

Nada de esto bloquea nada: lo llama el instalador de la carpeta de marketing
(y el botón «Actualizar del ERP» del panel) dentro de un try.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

from app.adapters.erp.montaje.comun import PARAMETRO_COSTO as PARAMETRO
from app.adapters.erp.sheets import FILA_ENCABEZADOS, Hoja, _letra, _Tabla, _valor
from app.domain import erp_marketing as em

HOJA = "Publicidad"
CIUDADES = "Rank_Ciudades"


@dataclass
class ResultadoPublicidad:
    nuevas: int = 0
    actualizadas: int = 0
    quitadas: int = 0
    avisos: list[str] = field(default_factory=list)

    def __str__(self) -> str:
        return (
            f"Publicidad: +{self.nuevas} nuevas, ~{self.actualizadas} actualizadas, "
            f"−{self.quitadas} quitadas"
        )


def sincronizar_publicidad(
    hoja: Hoja, deseadas: dict[str, dict[str, object]]
) -> ResultadoPublicidad:
    """Deja en `Publicidad` exactamente las filas del bot que tocan."""
    r = ResultadoPublicidad()
    (filas,) = hoja.leer([f"{HOJA}!A{FILA_ENCABEZADOS}:Q"])
    tabla = _Tabla(HOJA, filas, "Fecha_Inicio")
    faltan = [c for c in em.COLUMNAS if tabla.col(c) is None]
    if faltan:
        r.avisos.append(f"{HOJA} no tiene las columnas {faltan}: no se escribe")
        return r
    escrituras: list[tuple[str, list[list]]] = []

    c_ref = tabla.col(em.REFERENCIA)
    if c_ref is None:
        c_ref = len(tabla.encabezados)
        escrituras.append(
            (f"{HOJA}!{_letra(c_ref)}{FILA_ENCABEZADOS}", [[em.REFERENCIA]])
        )
        tabla.encabezados += [""] * (c_ref + 1 - len(tabla.encabezados))
        tabla.encabezados[c_ref] = em.REFERENCIA
        r.avisos.append(f"se agregó la columna {em.REFERENCIA} en {HOJA}")

    del_bot: dict[str, int] = {}
    for i, fila in enumerate(tabla.filas):
        ref = str(_valor(fila, c_ref) or "")
        if ref.startswith(em.PREFIJO):
            del_bot[ref] = i

    for ref, valores in deseadas.items():
        if ref in del_bot:
            i = del_bot.pop(ref)
            cambio = False
            for columna in ("Inversion", "Conversaciones", "Campaña"):
                c = tabla.col(columna)
                if c is not None and _igual(_valor(tabla.filas[i], c), valores[columna]):
                    continue
                if c is not None:
                    escrituras.append(
                        (f"{HOJA}!{_letra(c)}{tabla.numero(i)}", [[valores[columna]]])
                    )
                    cambio = True
            r.actualizadas += cambio
            continue
        n = tabla.siguiente_libre()
        for columna, valor in valores.items():
            c = tabla.col(columna)
            if c is not None:
                escrituras.append((f"{HOJA}!{_letra(c)}{n}", [[valor]]))
        escrituras.append((f"{HOJA}!{_letra(c_ref)}{n}", [[ref]]))
        r.nuevas += 1

    # Lo que el bot escribió antes y ya no está en marketing (una campaña que
    # se renombró, un mes corregido): se vacían sus celdas de captura.
    for _ref, i in del_bot.items():
        for columna in (*em.COLUMNAS, em.REFERENCIA):
            c = tabla.col(columna)
            if c is not None:
                escrituras.append((f"{HOJA}!{_letra(c)}{tabla.numero(i)}", [[""]]))
        r.quitadas += 1

    hoja.escribir(escrituras)
    return r


def _igual(actual, nuevo) -> bool:
    try:
        return float(actual) == float(nuevo)
    except (TypeError, ValueError):
        return str(actual or "").strip() == str(nuevo or "").strip()


#: `Rank_Ciudades`: fórmulas con `;` (el ERP está en español) y sin QUERY: con
#: 2.000 filas de fórmulas vacías, QUERY decide mal el tipo de la columna.
_V = "Ventas!$"
_FILAS = "4:$"
_RANGO = "2003"
_CIUDAD = f"{_V}F${_FILAS}F${_RANGO}"
_FECHA = f"{_V}B${_FILAS}B${_RANGO}"
_UNIDADES = f"{_V}J${_FILAS}J${_RANGO}"
_TOTAL = f"{_V}O${_FILAS}O${_RANGO}"
_PRINCIPALES = f'({_FECHA}<>"")*REGEXMATCH(LOWER({_CIUDAD}&"");"bogot|medell|cali")'
_SIN_PRINCIPALES = (
    f'({_FECHA}<>"")*({_CIUDAD}<>"")'
    f'*(1-REGEXMATCH(LOWER({_CIUDAD}&"");"bogot|medell|cali"))'
)
_SIN_CIUDAD = f'({_FECHA}<>"")*({_CIUDAD}="")'
#: Por ciudad va SUMIF (que sí funciona fila por fila dentro de ARRAYFORMULA);
#: SUMIFS ahí repite el primer valor en todas las filas (visto en el ERP, 01/10).
CONTENIDO_CIUDADES = [
    ["🏙️ RANK_CIUDADES — Ventas por ciudad (NO EDITAR · la escribe VentaBot)"],
    [
        "Unidades e ingresos por ciudad, de la hoja Ventas. A la derecha, Bogotá · "
        "Medellín · Cali contra el resto: la prueba «Resto de Colombia» del marketing."
    ],
    ["Ciudad", "Unidades", "Ingresos", "Ventas", "", "Grupo", "Unidades", "Ingresos"],
    [
        f'=IFERROR(SORT(UNIQUE(FILTER({_CIUDAD};{_FECHA}<>"";{_CIUDAD}<>"")));"")',
        f'=ARRAYFORMULA(IF(A4:A="";"";SUMIF({_CIUDAD};A4:A;{_UNIDADES})))',
        f'=ARRAYFORMULA(IF(A4:A="";"";SUMIF({_CIUDAD};A4:A;{_TOTAL})))',
        f'=ARRAYFORMULA(IF(A4:A="";"";COUNTIF({_CIUDAD};A4:A)))',
        "",
        "Bogotá · Medellín · Cali",
        f"=SUMPRODUCT({_PRINCIPALES};IFERROR({_UNIDADES}*1;0))",
        f"=SUMPRODUCT({_PRINCIPALES};IFERROR({_TOTAL}*1;0))",
    ],
    [
        "",
        "",
        "",
        "",
        "",
        "Resto de Colombia",
        f"=SUMPRODUCT({_SIN_PRINCIPALES};IFERROR({_UNIDADES}*1;0))",
        f"=SUMPRODUCT({_SIN_PRINCIPALES};IFERROR({_TOTAL}*1;0))",
    ],
    [
        "",
        "",
        "",
        "",
        "",
        "Sin ciudad (recoge o falta el dato)",
        f"=SUMPRODUCT({_SIN_CIUDAD};IFERROR({_UNIDADES}*1;0))",
        f"=SUMPRODUCT({_SIN_CIUDAD};IFERROR({_TOTAL}*1;0))",
    ],
]


def asegurar_rank_ciudades(hoja: Hoja) -> None:
    """Crea (o rehace) la hoja de ciudades. Es del bot: se reescribe entera."""
    hoja.asegurar_hoja(CIUDADES)
    hoja.escribir([(f"{CIUDADES}!A1", CONTENIDO_CIUDADES)])


def _por_nombre(filas: list[list], encabezado: int = 0) -> list[dict]:
    if len(filas) <= encabezado:
        return []
    cab = [str(x).strip() for x in filas[encabezado]]
    return [
        {c: (f[i] if i < len(f) else "") for i, c in enumerate(cab) if c}
        for f in filas[encabezado + 1 :]
        if any(str(x).strip() for x in f)
    ]


def foto(hoja: Hoja) -> dict:
    """Lo que el panel muestra del ERP. Solo lectura; sin datos de clientas."""
    productos, mensual, ciudades, validaciones, config = hoja.leer(
        [
            "Cat_Productos!A3:K40",
            "Mensual!A3:X40",
            f"{CIUDADES}!A3:H60",
            "Validaciones!A3:E30",
            "Config!A3:F40",
        ]
    )
    # El costo de un anillo HOY: Config, que apunta a la hoja Costeo (02/10).
    costo_real = next(
        (_numero(f[1]) for f in config if len(f) > 1 and str(f[0]).strip() == PARAMETRO),
        0.0,
    )
    por_ciudad = [
        {"ciudad": f[0], "unidades": f[1], "ingresos": f[2], "ventas": f[3]}
        for f in ciudades[1:]
        if f and str(f[0]).strip() and len(f) >= 4
    ]
    grupos = [
        {"grupo": f[5], "unidades": f[6], "ingresos": f[7]}
        for f in ciudades[1:4]
        if len(f) >= 8 and str(f[5]).strip()
    ]
    meses = [
        {
            k: m.get(k, "")
            for k in (
                "MesKey",
                "Ingresos",
                "Unidades",
                "COGS_Std",
                "Margen_Bruto",
                "Publicidad",
                "Gastos",
                "Deprec",
                "Utilidad_Op",
                "Margen_Neto_%",
                "Clientes_Nuevos",
                "CAC",
            )
        }
        for m in _por_nombre(mensual)
        if any(_numero(m.get(k)) for k in ("Ingresos", "Publicidad", "Gastos"))
    ]
    return {
        "leido": datetime.now(UTC).isoformat(timespec="seconds"),
        "productos": [
            {
                k: p.get(k, "")
                for k in (
                    "Producto",
                    "Precio_Lista",
                    "Costo_Total",
                    "Margen_Unit",
                    "Calidad_Dato",
                )
            }
            for p in _por_nombre(productos)
        ],
        "costo_real": costo_real,
        "mensual": meses,
        "ciudades": por_ciudad,
        "grupos": grupos,
        "revisar": [
            {"chequeo": v.get("Chequeo", ""), "resultado": v.get("Resultado", "")}
            for v in _por_nombre(validaciones)
            if "REVISAR" in str(v.get("Estado", ""))
        ],
    }


def _numero(x) -> float:
    try:
        return float(x)
    except (TypeError, ValueError):
        return 0.0


def primer_mes_con_ventas(hoja: Hoja) -> int | None:
    """`Config!B11` del ERP («Primer mes con ventas (clave)», AAAAMM)."""
    (filas,) = hoja.leer(["Config!A11:B11"])
    try:
        return int(filas[0][1])
    except (IndexError, TypeError, ValueError):
        return None


def actualizar(hoja: Hoja, campanas_csv: str, destino_de_la_foto) -> str:
    """Todo junto: pauta → Publicidad, la hoja de ciudades y la foto del ERP.

    Lo llaman el instalador de la carpeta de marketing y el botón «Actualizar
    del ERP» del panel. Devuelve qué pasó, en una línea; si algo falla, lanza
    (quien llama decide: nunca bloquea la subida ni el panel).
    """
    import json

    primer_mes = primer_mes_con_ventas(hoja)
    deseadas = em.desde_el_mes(em.filas_de_publicidad(campanas_csv), primer_mes)
    r = sincronizar_publicidad(hoja, deseadas)
    if primer_mes:
        r.avisos.append(f"pauta desde {primer_mes} (el primer mes con ventas del ERP)")
    asegurar_rank_ciudades(hoja)
    destino_de_la_foto.parent.mkdir(parents=True, exist_ok=True)
    destino_de_la_foto.write_text(
        json.dumps(foto(hoja), ensure_ascii=False, indent=1), encoding="utf-8"
    )
    return f"{r} · Rank_Ciudades al día · foto guardada" + (
        f" · {' · '.join(r.avisos)}" if r.avisos else ""
    )
