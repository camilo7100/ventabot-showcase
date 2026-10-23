"""`/panel/finanzas`: las finanzas del negocio, por pestañas (Camilo, 01/10).

«Mete lo que puedas en el panel: finanzas, resumen, materiales, todo por
aparte, bien estructurado». Todo sale de la foto del ERP
(`app.adapters.erp.finanzas`): totales, nunca datos de clientas. Lo que dice
en frases lo calcula `app.domain.finanzas`.
"""

from __future__ import annotations

import html
import logging
from collections.abc import Callable
from datetime import UTC, datetime

from app.api.marketing import ESTILO_MARKETING
from app.domain import finanzas as fin

log = logging.getLogger("ventabot.panel.finanzas")

ESTILO = """
.grafica-mes{width:100%;height:auto;display:block;margin:6px 0}
.grafica-mes text{font-size:11px;fill:#7b6d68}
@media (max-width:600px){.grafica-mes text{font-size:21px}}
.corto{white-space:nowrap}
ol.lista{padding-left:22px;margin:6px 0}
ol.lista li{list-style:decimal;margin:6px 0}
.estado-cuenta{font-variant-numeric:tabular-nums;font-size:14px}
.estado-cuenta div{display:flex;justify-content:space-between;padding:5px 2px;
border-bottom:1px solid var(--borde)}
.estado-cuenta div.total{font-weight:700;border-top:2px solid var(--texto);
border-bottom:0}
.estado-cuenta div.resta span:first-child::before{content:"− ";color:var(--suave)}
.estado-cuenta .malo{color:var(--alerta)}
.chip.ESTIMADO,.chip.SUPUESTO{background:#fff1cf;color:#7a5a12}
.chip.REAL{background:#e3f1e7;color:#2f6b45}
.chip.CALCULADO{background:#e6edfb;color:#294f94}
.numero-grande{font-size:clamp(26px,8vw,34px);font-weight:800;color:var(--acento)}
td.malo{color:var(--alerta)}
.periodo{display:flex;flex-wrap:wrap;gap:8px;align-items:center;font-size:14px}
.periodo select{font:inherit;padding:5px 8px;border-radius:8px;
border:1px solid var(--borde);background:var(--tarjeta)}
.periodo button{padding:5px 12px}
.periodo-caja .ayuda{margin:6px 0 0}
.estado-cuenta div span:first-child{padding-right:10px}
h3{font-size:15px;margin:14px 0 4px}
"""


def _t(x) -> str:
    return html.escape(str(x if x is not None else ""))


def _pesos(x) -> str:
    n = fin.numero(x)
    return _t(f"{'-' if n < 0 else ''}${abs(round(n)):,}".replace(",", "."))


def _pct(x) -> str:
    return f"{fin.numero(x) * 100:.1f} %".replace(".", ",")


def _entero(x) -> str:
    return f"{round(fin.numero(x)):,}".replace(",", ".")


def _chip(calidad) -> str:
    c = _t(calidad)
    return f"<span class='chip {c}'>{c}</span>" if c else ""


def _kpi(etiqueta: str, valor: str, que: str = "", tono: str = "") -> str:
    return (
        f"<div class='kpi {tono}'><div class=etiqueta>{_t(etiqueta)}</div>"
        f"<div class=valor>{valor}</div>"
        + (f"<div class=que>{_t(que)}</div>" if que else "")
        + "</div>"
    )


def _barras(filas: list[tuple[str, float, str]], color: str = "#c96f8b") -> str:
    tope = max((v for _, v, _ in filas), default=0) or 1
    return (
        "<div class=barras>"
        + "".join(
            f"<div class=barra style='grid-template-columns:8.5em 1fr 9.5em'>"
            f"<span>{_t(n)}</span><span class=fondo><span class=lleno "
            f"style='display:block;width:{max(v, 0) / tope * 100:.1f}%;"
            f"background:{color}'></span></span><span class=cuanto>{texto}</span></div>"
            for n, v, texto in filas
        )
        + "</div>"
    )


def _tabla(encabezados: list[str], filas: list[list[str]], numericas: set[int]) -> str:
    cab = "".join(f"<th>{_t(e)}</th>" for e in encabezados)
    cuerpo = "".join(
        "<tr>"
        + "".join(
            f"<td{' class=n' if j in numericas else ''}>{c}</td>" for j, c in enumerate(f)
        )
        + "</tr>"
        for f in filas
    )
    return (
        f"<div class=desliza><table class='tabla datos'><tr>{cab}</tr>{cuerpo}"
        "</table></div>"
    )


def _seccion(titulo: str, cuerpo: str, ancla: str = "", ayuda: str = "") -> str:
    a = f" id={ancla}" if ancla else ""
    return (
        f"<section><h2{a}>{_t(titulo)}</h2><article>"
        + (f"<p class=ayuda>{ayuda}</p>" if ayuda else "")
        + cuerpo
        + "</article></section>"
    )


def _corta(clave) -> str:
    """202601 → «ene 26»: el mes SIEMPRE con su año (Camilo, 01/10)."""
    nombre = fin.nombre_mes(clave)
    partes = nombre.split()
    return f"{partes[0]} {partes[1][-2:]}" if len(partes) == 2 else nombre


_ANCHO, _ALTO, _BASE, _ALTURA = 640, 230, 196, 170


def _ejes(etiquetas: list[str], paso: float) -> str:
    return (
        f"<line x1='0' x2='{_ANCHO}' y1='{_BASE}' y2='{_BASE}' stroke='#d8cfcb'/>"
        + "".join(
            f"<text x='{i * paso + paso / 2:.1f}' y='{_BASE + 15}' text-anchor='middle'>"
            f"{_t(e)}</text>"
            for i, e in enumerate(etiquetas)
        )
    )


def _leyenda(series: list[tuple[str, str]]) -> str:
    return (
        "<div class=leyenda>"
        + "".join(
            f"<span><i style='background:{c}'></i>{_t(n)}</span>" for n, c in series
        )
        + "</div>"
    )


def _svg(etiqueta: str, cuerpo: str) -> str:
    return (
        f"<svg class=grafica-mes viewBox='0 0 {_ANCHO} {_ALTO}' role=img "
        f"aria-label='{_t(etiqueta)}'>{cuerpo}</svg>"
    )


def _grafica_meses(meses: list[dict]) -> str:
    """Barras de ingresos por mes y, adentro, la utilidad (verde arriba, roja abajo).

    La línea del cero se corre hacia arriba lo que haga falta para que una pérdida
    quepa debajo sin tapar el nombre del mes (pasó el 01/10 con junio y agosto).
    """
    if not meses:
        return ""
    tope = max(max(fin.numero(m.get("Ingresos")) for m in meses), 1)
    hondo = max([-fin.numero(m.get("Utilidad_Op")) for m in meses] + [0])
    escala = _ALTURA / (tope + hondo)
    cero = _BASE - hondo * escala
    paso = _ANCHO / len(meses)
    partes = []
    for i, m in enumerate(meses):
        w = min(paso * 0.7, 72)  # con un solo mes, una columna y no una pared
        x = i * paso + (paso - w) / 2
        ing, util = fin.numero(m.get("Ingresos")), fin.numero(m.get("Utilidad_Op"))
        h = ing * escala
        partes.append(
            f"<rect x='{x:.1f}' y='{cero - h:.1f}' width='{w:.1f}' height='{h:.1f}' "
            f"rx='3' fill='#e7b3c3'><title>{_t(fin.nombre_mes(m.get('MesKey')))}: "
            f"vendido {_pesos(ing)}</title></rect>"
        )
        hu = abs(util) * escala
        y = cero - hu if util >= 0 else cero
        color = "#3f7d5a" if util >= 0 else "#c0392b"
        partes.append(
            f"<rect x='{x + w * 0.25:.1f}' y='{y:.1f}' width='{w * 0.5:.1f}' "
            f"height='{hu:.1f}' rx='2' fill='{color}'><title>Utilidad: "
            f"{_pesos(util)}</title></rect>"
        )
    linea_cero = (
        f"<line x1='0' x2='{_ANCHO}' y1='{cero:.1f}' y2='{cero:.1f}' stroke='#b9a6a0'/>"
        if hondo
        else ""
    )
    return _svg(
        "Ingresos y utilidad por mes",
        _ejes([_corta(m.get("MesKey")) for m in meses], paso)
        + linea_cero
        + "".join(partes),
    ) + _leyenda(
        [
            ("Vendido", "#e7b3c3"),
            ("Utilidad operativa", "#3f7d5a"),
            ("Pérdida", "#c0392b"),
        ]
    )


def _apiladas(
    etiquetas: list[str],
    series: list[tuple[str, str, list[float]]],
    marca: list[float] | None = None,
    nombre_marca: str = "",
) -> str:
    """Columnas apiladas (positivas) y, si hay, una raya negra por columna."""
    if not etiquetas:
        return ""
    sumas = [sum(max(s[2][i], 0) for s in series) for i in range(len(etiquetas))]
    tope = max([*sumas, *(marca or []), 1])
    paso = _ANCHO / len(etiquetas)
    partes = []
    for i in range(len(etiquetas)):
        w = min(paso * 0.64, 72)
        x, y = i * paso + (paso - w) / 2, float(_BASE)
        for nombre, color, valores in series:
            v = max(valores[i], 0)
            h = v / tope * _ALTURA
            if h:
                y -= h
                partes.append(
                    f"<rect x='{x:.1f}' y='{y:.1f}' width='{w:.1f}' height='{h:.1f}' "
                    f"fill='{color}'><title>{_t(etiquetas[i])} · {_t(nombre)}: "
                    f"{_t(_numero_corto(valores[i]))}</title></rect>"
                )
        if marca:
            ym = _BASE - marca[i] / tope * _ALTURA
            partes.append(
                f"<line x1='{x - 3:.1f}' x2='{x + w + 3:.1f}' "
                f"y1='{ym:.1f}' y2='{ym:.1f}' "
                f"stroke='#3a2e2b' stroke-width='2.5'><title>{_t(etiquetas[i])} · "
                f"{_t(nombre_marca)}: {_t(_numero_corto(marca[i]))}</title></line>"
            )
    leyenda = [(n, c) for n, c, _ in series]
    if marca:
        leyenda.append((nombre_marca, "#3a2e2b"))
    return _svg("Gráfica apilada", _ejes(etiquetas, paso) + "".join(partes)) + _leyenda(
        leyenda
    )


def _numero_corto(v: float) -> str:
    return _pesos(v) if abs(v) >= 1000 else _entero(v)


def _linea(
    etiquetas: list[str],
    valores: list[float],
    color: str,
    nombre: str,
    desde_cero: bool = True,
) -> str:
    """Una línea por mes. `desde_cero=False` acerca la escala a los valores (un costo
    que baja de $203.000 a $180.000 se veía plano desde cero, 02/10)."""
    if len(etiquetas) < 2:  # un punto solo no es una línea
        return ""
    if desde_cero:
        bajo, alto = min([*valores, 0]), max([*valores, 1])
    else:
        margen = (max(valores) - min(valores)) * 0.15 or 1
        bajo, alto = min(valores) - margen, max(valores) + margen
    rango = (alto - bajo) or 1
    paso = _ANCHO / len(etiquetas)

    def y(v: float) -> float:
        return _BASE - (v - bajo) / rango * _ALTURA

    puntos = " ".join(
        f"{i * paso + paso / 2:.1f},{y(v):.1f}" for i, v in enumerate(valores)
    )
    marcas = "".join(
        f"<circle cx='{i * paso + paso / 2:.1f}' cy='{y(v):.1f}' r='4' fill='{color}'>"
        f"<title>{_t(etiquetas[i])}: {_pesos(v)}</title></circle>"
        for i, v in enumerate(valores)
    )
    cero = (
        f"<line x1='0' x2='{_ANCHO}' y1='{y(0):.1f}' y2='{y(0):.1f}' stroke='#c0392b' "
        "stroke-dasharray='4 4'/>"
        if bajo < 0
        else ""
    )
    return _svg(
        nombre,
        _ejes(etiquetas, paso)
        + cero
        + f"<polyline points='{puntos}' fill='none' stroke='{color}' stroke-width='3'/>"
        + marcas,
    ) + _leyenda([(nombre, color)])


# ---------------------------------------------------------------------------
# Las pestañas
# ---------------------------------------------------------------------------


def _resumen(f: dict, token: str) -> str:
    r = fin.resumen(f)
    tono = "bueno" if r.utilidad >= 0 else "malo"
    kpis = "".join(
        [
            _kpi("Vendido", _pesos(r.ingresos), f"{r.meses} meses"),
            _kpi("Piezas", _entero(r.piezas), f"ticket promedio {_pesos(r.ticket)}"),
            _kpi(
                "Margen bruto",
                _pesos(r.margen_bruto),
                f"{_pct(r.margen_bruto / r.ingresos if r.ingresos else 0)} de lo vendido "
                "(con el costo de receta)",
            ),
            _kpi(
                "Publicidad",
                _pesos(r.publicidad),
                f"ROAS {r.roas:.1f}x".replace(".", ","),
            ),
            _kpi(
                "Gastos fijos",
                _pesos(r.gastos),
                "salario de Lía, taller, familia, diligencias, colchón (estimados)",
            ),
            _kpi(
                "Utilidad operativa",
                _pesos(r.utilidad),
                f"margen neto {_pct(r.margen_neto)}",
                tono,
            ),
            _kpi(
                "Clientas nuevas",
                _entero(r.clientas_nuevas),
                f"{_entero(r.repetidas)} compras repetidas",
            ),
            _kpi("Caja acumulada", _pesos(r.caja), "cobros − salidas desde el inicio"),
        ]
    )
    iconos = {"urgente": "🚨", "aviso": "⚠️", "bien": "✅"}
    hallazgos = "".join(
        f"<div class='alerta {h.nivel}'><b>{iconos.get(h.nivel, '')} {_t(h.titulo)}</b>"
        f"{_t(h.detalle)}</div>"
        for h in fin.hallazgos(f)
    )
    return (
        _seccion("El negocio en cifras", f"<div class=kpis>{kpis}</div>", "cifras")
        + _seccion("Lo que dicen los números", hallazgos or "<p>Sin datos aún.</p>")
        + _seccion(
            "Mes a mes",
            _grafica_meses(f.get("mensual", [])),
            "meses",
            "Barra rosada: lo vendido. Barra de adentro: lo que quedó después de costo, "
            "publicidad, gastos fijos y depreciación.",
        )
    )


def _resultados(f: dict, token: str) -> str:
    r = fin.resumen(f)

    def linea(nombre: str, valor: float, clase: str = "", pct: bool = True) -> str:
        malo = " class=malo" if valor < 0 else ""
        parte = (
            f" <small class=ayuda>{_pct(valor / r.ingresos)}</small>"
            if pct and r.ingresos
            else ""
        )
        return (
            f"<div class='{clase}'><span>{_t(nombre)}</span>"
            f"<span{malo}>{_pesos(valor)}{parte}</span></div>"
        )

    cuenta = (
        "<div class=estado-cuenta>"
        + linea("Ingresos (lo vendido)", r.ingresos, pct=False)
        + linea("Costo de lo vendido (receta)", r.costo_de_lo_vendido, "resta")
        + linea("Margen bruto", r.margen_bruto, "total")
        + linea("Publicidad", r.publicidad, "resta")
        + linea(
            "Gastos fijos (taller, familia, diligencias, merma y colchón)",
            r.gastos,
            "resta",
        )
        + linea("Depreciación de los equipos", r.depreciacion, "resta")
        + linea("Utilidad operativa", r.utilidad, "total")
        + "</div>"
    )
    meses = f.get("mensual", [])
    etiquetas = [_corta(m.get("MesKey")) for m in meses]

    def serie(campo: str) -> list[float]:
        return [fin.numero(m.get(campo)) for m in meses]

    destino = _apiladas(
        etiquetas,
        [
            ("Costo de lo vendido", "#b9a6a0", serie("COGS_Std")),
            ("Publicidad", "#c96f8b", serie("Publicidad")),
            ("Gastos fijos", "#d39b1f", serie("Gastos")),
            ("Depreciación", "#8e7cc3", serie("Deprec")),
            ("Utilidad", "#3f7d5a", serie("Utilidad_Op")),
        ],
        serie("Ingresos"),
        "Vendido",
    )
    filas = []
    for m in meses:
        ing, pub = fin.numero(m.get("Ingresos")), fin.numero(m.get("Publicidad"))
        util = fin.numero(m.get("Utilidad_Op"))
        filas.append(
            [
                _t(fin.nombre_mes(m.get("MesKey"))),
                _pesos(ing),
                _entero(m.get("Unidades")),
                _pesos(m.get("COGS_Std")),
                _pesos(pub),
                _pesos(m.get("Gastos")),
                f"<b>{_pesos(util)}</b>",
                _pct(util / ing if ing else 0),
                (f"{ing / pub:.1f}x" if pub else "").replace(".", ","),
            ]
        )
    por_anio = fin.por_anio(f)
    anual = [
        [
            f"<b>{a}</b>",
            _pesos(x.ingresos),
            _entero(x.piezas),
            _pesos(x.publicidad),
            _pesos(x.gastos),
            f"<b>{_pesos(x.utilidad)}</b>",
            _pct(x.margen_neto),
            f"{x.roas:.1f}x".replace(".", ","),
        ]
        for a, x in por_anio.items()
    ]
    caja = [
        [
            _t(fin.nombre_mes(m.get("MesKey"))),
            _pesos(m.get("Cobros")),
            _pesos(m.get("Salidas_Caja")),
            _pesos(m.get("Flujo")),
            f"<b>{_pesos(m.get('Flujo_Acum'))}</b>",
        ]
        for m in meses
    ]
    return (
        _seccion(
            "Estado de resultados del período",
            cuenta,
            "estado",
            "Lo que quedó de lo vendido, en el orden en que se va la plata (el % es "
            "sobre lo vendido). El costo de lo vendido es el de receta; lo demás que "
            "cuesta una pieza está en gastos fijos (estimados en Costeo).",
        )
        + _seccion(
            "¿A dónde se fue lo vendido cada mes?",
            destino,
            "destino",
            "Cada columna es lo que salió ese mes; la raya negra, lo vendido. Si la "
            "columna pasa la raya, ese mes se perdió plata.",
        )
        + _seccion(
            "Mes a mes",
            _tabla(
                [
                    "Mes",
                    "Ingresos",
                    "Piezas",
                    "Costo",
                    "Publicidad",
                    "Gastos",
                    "Utilidad",
                    "Margen",
                    "ROAS",
                ],
                filas,
                set(range(1, 9)),
            ),
            "mensual",
        )
        + (
            _seccion(
                "Año por año",
                _tabla(
                    [
                        "Año",
                        "Ingresos",
                        "Piezas",
                        "Publicidad",
                        "Gastos",
                        "Utilidad",
                        "Margen",
                        "ROAS",
                    ],
                    anual,
                    set(range(1, 8)),
                ),
                "anual",
            )
            if anual and len(meses) > 1
            else ""
        )
        + _seccion(
            "La caja",
            _linea(etiquetas, serie("Flujo_Acum"), "#294f94", "Caja acumulada")
            + _tabla(
                ["Mes", "Cobrado", "Salió", "Flujo del mes", "Caja acumulada"],
                caja,
                {1, 2, 3, 4},
            ),
            "caja",
            "Cobrado = abonos + saldos (los de la sábana se supusieron cobrados 10 días "
            "después de la venta). Salió = publicidad, gastos y, mientras no se anoten "
            "las Compras, el costo de receta de lo vendido.",
        )
    )


def _balance(f: dict, token: str) -> str:
    filas = f.get("balance", [])
    if not filas:
        return _seccion(
            "Todavía no hay balance",
            "<p>Se arma con <code>vb erp --montar</code> (hoja Balance del ERP).</p>",
        )
    partes = ["<div class=estado-cuenta>"]
    for x in filas:
        tipo = x.get("tipo")
        if tipo == "seccion":
            partes.append(
                f"</div><h3>{_t(str(x.get('concepto')).lstrip('▼ '))}</h3>"
                "<div class=estado-cuenta>"
            )
            continue
        valor = fin.numero(x.get("valor"))
        malo = " class=malo" if valor < 0 else ""
        clase = "total" if tipo == "total" else ""
        nota = (
            f"<br><small class=ayuda>{_t(x.get('nota'))}</small>" if x.get("nota") else ""
        )
        extra = " ✏️" if tipo == "captura" else ""
        partes.append(
            f"<div class='{clase}'><span>{_t(x.get('concepto'))}{extra}{nota}</span>"
            f"<span{malo}>{_pesos(valor)}</span></div>"
        )
    partes.append("</div>")
    hasta = next((i for i, y in enumerate(filas) if y.get("tipo") == "total"), len(filas))
    activos = [
        (str(x.get("concepto")), fin.numero(x.get("valor")))
        for x in filas[:hasta]
        if x.get("tipo") == "dato" and fin.numero(x.get("valor")) > 0
    ]
    return (
        _cierre(f)
        + _seccion(
            "Balance general hoy (estimado)",
            "".join(partes),
            "balance",
            "Lo que tiene el negocio, lo que debe y lo que es suyo, al último mes con "
            "ventas. Es estimado: el ERP no sabe con cuánta caja se arrancó ni las "
            "deudas "
            "(se anotan en la hoja Balance, celdas amarillas ✏️).",
        )
        + (
            _seccion(
                "De qué están hechos los activos",
                _barras([(n, v, _pesos(v)) for n, v in activos], "#294f94"),
                "activos",
            )
            if activos
            else ""
        )
    )


def _costos(f: dict, token: str) -> str:
    c = f.get("costeo", {})
    resumen = c.get("resumen", [])
    decidir = "".join(
        f"<div class=dato-par><b>{_t(x.get('concepto'))}:</b> {_pesos(x.get('valor'))}"
        f" <small class=ayuda>{_t(x.get('fuente'))}</small></div>"
        for x in resumen[1:]
    )
    promedio = resumen[0].get("valor") if resumen else ""
    piezas = c.get("piezas", [])
    filas = []
    for capa in c.get("capas", []):
        concepto = str(capa.get("concepto", ""))
        es_pct = concepto.lower().startswith("margen")
        if capa.get("clave") == "gramos" or concepto.startswith("Gramos"):
            valores = [
                f"{fin.numero(v):g} g".replace(".", ",") for v in capa.get("valores", [])
            ]
        else:
            valores = [
                (_pct(v) if es_pct else _pesos(v)) for v in capa.get("valores", [])
            ]
        if concepto.upper() == concepto or concepto.startswith("→"):
            valores = [f"<b>{v}</b>" for v in valores]
            concepto_html = f"<b>{_t(concepto)}</b>"
        else:
            concepto_html = _t(concepto)
        filas.append([concepto_html, *valores])
    uno = {
        str(x.get("concepto")): fin.numero((x.get("valores") or [0])[0])
        for x in c.get("capas", [])
    }
    capas_1 = [
        ("Plata + merma", uno.get("Plata 925", 0) + uno.get("Merma de plata", 0)),
        ("Circón", uno.get("Circones", 0)),
        (
            "Insumos y otros",
            uno.get("Insumos del taller", 0) + uno.get("Otros materiales", 0),
        ),
        ("Empaque", uno.get("Empaque", 0)),
        ("Mano de obra", uno.get("Mano de obra (ayudante)", 0)),
        ("Salario de Lía", uno.get("Salario de Lía", 0)),
        ("Taller", uno.get("Taller", 0)),
        ("Familia", uno.get("Familia (mamá + tío)", 0)),
        ("Taxis y diligencias", uno.get("Taxis y diligencias", 0)),
        ("Equipos (depreciación)", uno.get("Equipos del taller (depreciación)", 0)),
        ("Colchón", uno.get("Colchón", 0)),
    ]
    supuestos = [
        [
            _t(s.get("nombre")),
            (
                _pct(s.get("valor"))
                if s.get("unidad") == "%"
                else _pesos(s.get("valor"))
                if str(s.get("unidad", "")).startswith("$")
                else _entero(s.get("valor"))
            ),
            _t(s.get("unidad")),
            _chip(s.get("calidad")),
            _t(s.get("porque")),
        ]
        for s in c.get("supuestos", [])
    ]
    gastos = [
        [
            _t(g.get("concepto")),
            _t(g.get("categoria")),
            _pesos(g.get("total")),
            _entero(g.get("meses")),
            _chip(g.get("calidad")),
        ]
        for g in f.get("gastos", [])
    ]
    return (
        _seccion(
            "El número para decidir",
            f"<div class=numero-grande>{_pesos(promedio)}</div>"
            "<p class=ayuda>Costo completo HOY de una pieza vendida (anillos y "
            "cadenas, pesado por lo que se vende), con la plata de este mes, el "
            "salario de Lía, taller, familia, diligencias y colchón.</p>"
            + decidir
            + "<p class=nota>Este es el costo que usa el marketing (Config apunta a "
            "Costeo). Para cambiarlo se cambia lo que lo forma: el precio de la plata "
            "del mes, los gramos o los supuestos amarillos de Costeo.</p>",
            "numero",
        )
        + _seccion(
            "Capa por capa",
            _tabla(["Concepto", *piezas], filas, set(range(1, len(piezas) + 1))),
            "capas",
            "Arriba la receta (lo que usan las fórmulas del ERP); debajo lo que la "
            "receta no ve. Cambiar un supuesto en la hoja Costeo del ERP mueve todo.",
        )
        + _costo_mes_a_mes(c)
        + _seccion(
            "De qué está hecho un anillo de 1 huellita",
            _barras([(n, v, _pesos(v)) for n, v in capas_1 if v]),
            "uno",
        )
        + _seccion(
            "Los supuestos (hoja Costeo, celdas amarillas)",
            _tabla(["Supuesto", "Valor", "Unidad", "Calidad", "Por qué"], supuestos, {1}),
            "supuestos",
        )
        + _seccion(
            "Gastos fijos por concepto",
            _tabla(["Concepto", "Categoría", "Total", "Meses", "Calidad"], gastos, {2, 3})
            if gastos
            else "<p>Sin gastos registrados.</p>",
            "gastos",
            "De la hoja Gastos del ERP. Los ESTIMADOS salen de Costeo; cuando haya "
            "cifras reales, se anotan ahí y estas filas se borran.",
        )
    )


def _materiales(f: dict, token: str) -> str:
    productos = [
        [
            _t(p.get("Producto")),
            _pesos(p.get("Precio_Lista")),
            _pesos(p.get("Costo_Materiales")),
            _pesos(p.get("Costo_MO")),
            f"<b>{_pesos(p.get('Costo_Total'))}</b>",
            (
                _pesos(p.get("Margen_Unit"))
                if fin.numero(p.get("Precio_Lista"))
                else "<small class=ayuda>sin precio</small>"
            ),
            _chip(p.get("Calidad_Dato")),
        ]
        for p in f.get("productos", [])
    ]
    materiales = [
        [
            _t(m.get("material")),
            _t(m.get("unidad")),
            _pesos(m.get("costo")),
            _chip(m.get("calidad")),
            _t(m.get("stock")),
            f"<span class=corto>{_t(m.get('estado'))}</span>",
            f"<small>{_t(m.get('fuente'))}</small>",
        ]
        for m in f.get("materiales", [])
    ]
    p = f.get("parametros", {})
    parametros = "".join(
        f"<div class=dato-par><b>{_t(k)}:</b> "
        + (
            _t(fin.nombre_mes(v))
            if "clave" in k
            else _entero(v)
            if "Capacidad" in k
            else _pesos(v)
        )
        + "</div>"
        for k, v in p.items()
    )
    return (
        _seccion(
            "Los productos y su costo de receta",
            _tabla(
                [
                    "Producto",
                    "Precio",
                    "Materiales",
                    "Mano de obra",
                    "Costo receta",
                    "Margen",
                    "Calidad",
                ],
                productos,
                {1, 2, 3, 4, 5},
            ),
            "productos",
            "Costo de receta = materiales de la BOM + mano de obra. El costo completo "
            "(con taller, familia y colchón) está en la pestaña Costos.",
        )
        + _seccion(
            "Materiales",
            _tabla(
                ["Material", "Unidad", "Costo", "Calidad", "Stock", "Estado", "Fuente"],
                materiales,
                {2, 4},
            ),
            "materiales",
            "El stock sale de Compras − consumo de Producción: mientras no se anoten las "
            "compras, el ERP no sabe cuánto material hay (por eso marca RESTOCK).",
        )
        + _plata_mes_a_mes(f)
        + _seccion("Parámetros del ERP (Config)", parametros, "parametros")
    )


def _ventas(f: dict, token: str) -> str:
    ventas = [v for v in f.get("ventas", []) if isinstance(v, dict)]
    if not ventas:
        return _seccion("Sin ventas en este período", "<p>Elige otro período.</p>")
    total = sum(fin.numero(v.get("total")) for v in ventas)
    productos = fin.contar(ventas, "producto")
    meses, nombres, tabla = fin.por_mes_y_producto(ventas)
    filas_piezas = [
        [_t(fin.nombre_mes(m)), *(_entero(tabla.get((m, p), 0)) for p in nombres)]
        for m in meses
    ]
    apiladas = _apiladas(
        [_corta(m) for m in meses],
        [
            (
                p,
                COLORES_PRODUCTO[i % len(COLORES_PRODUCTO)],
                [tabla.get((m, p), 0) for m in meses],
            )
            for i, p in enumerate(nombres)
        ],
    )
    clientas = f.get("clientas", {})
    nuevas = sum(1 for v in ventas if fin.numero(v.get("nueva")))
    datos_clientas = (
        f"<div class=dato-par><b>Ventas del período:</b> {_entero(len(ventas))} · "
        f"{_pesos(total)} · ticket {_pesos(total / len(ventas))}</div>"
        f"<div class=dato-par><b>Clientas nuevas en el período:</b> {_entero(nuevas)} · "
        f"<b>compras repetidas:</b> {_entero(len(ventas) - nuevas)}</div>"
        + "".join(
            f"<div class=dato-par><b>{_t(k)} (todo el historial):</b> "
            + (
                _pct(v)
                if "Tasa" in k
                else _pesos(v)
                if "$" in k or "LTV" in k or "Ticket" in k
                else _entero(v)
            )
            + "</div>"
            for k, v in clientas.items()
        )
    )
    return (
        _seccion(
            "Qué se vende",
            _barras([(p, s, f"{_pesos(s)} · {n}") for p, n, s in productos]),
            "mezcla",
            "Ingresos por producto y piezas vendidas en el período.",
        )
        + _seccion(
            "Piezas por mes",
            (apiladas if len(meses) > 1 else "")
            + _tabla(["Mes", *nombres], filas_piezas, set(range(1, len(nombres) + 1))),
            "piezas",
        )
        + _seccion(
            "De dónde vino la clienta",
            _barras([(c, n, _entero(n)) for c, n, _ in fin.contar(ventas, "canal")]),
            "canal",
            "«Por clasificar» = la sábana no lo anotaba (antes de agosto).",
        )
        + _seccion(
            "Clientas",
            datos_clientas,
            "clientas",
            "Una clienta = un celular. Las ventas sin celular no cuentan aquí.",
        )
        + _seccion(
            "Tallas más pedidas",
            _barras([(t, n, _entero(n)) for t, n in fin.por_talla(ventas)], "#8e7cc3"),
            "tallas",
        )
        + _seccion(
            "Colores de circón",
            _barras([(c, n, _entero(n)) for c, n in fin.por_color(ventas)], "#d39b1f"),
            "colores",
            "Ventas que llevan ese color (corazón o dedos); una venta de 2 colores "
            "cuenta en los dos.",
        )
        + _seccion(
            "Qué día se vende",
            _barras(
                [
                    (d, n, f"{_entero(n)} · {_pesos(s)}")
                    for d, n, s in fin.por_dia(ventas)
                ],
                "#3f7d5a",
            ),
            "dias",
        )
    )


def _calidad(f: dict, token: str) -> str:
    filas = [
        [
            _t(v.get("numero")),
            _t(v.get("chequeo")),
            _t(v.get("resultado")),
            (
                "<b class='malo corto'>⚠️ revisar</b>"
                if "REVISAR" in str(v.get("estado"))
                else "✅"
                if v.get("numero") not in ("", None)
                else "ℹ️"
            ),
            f"<small>{_t(v.get('donde'))}</small>",
        ]
        for v in f.get("validaciones", [])
    ]
    falta = [
        "Lo que pagan de verdad a la mamá, al tío y en diligencias, y el arriendo y los "
        "servicios del taller (hoy son supuestos o faltan; el cuestionario para Lía los "
        "pide).",
        "Anotar las Compras (plata, circones, empaque): sin ellas el inventario y el "
        "costo de la plata son estimados.",
        "Los gastos reales del mes en Gastos (hoy son los supuestos de Costeo).",
        "En la sábana: el canal de cada venta (PUBLICIDAD / vieja) y la ciudad.",
        "Septiembre: el resumen a mano dice 52 ventas y el detalle 48 (faltan 4 por "
        "$755.000); enero: falta una cadena de $200.000 en el detalle.",
    ]
    return _seccion(
        "Lo que el ERP revisa solo (Validaciones)",
        _tabla(["#", "Chequeo", "Resultado", "Estado", "Dónde corregir"], filas, {2}),
        "validaciones",
    ) + _seccion(
        "Lo que falta para que todo sea real",
        "<ol class=lista>" + "".join(f"<li>{_t(x)}</li>" for x in falta) + "</ol>",
        "falta",
    )


VISTAS: tuple[tuple[str, str, Callable[[dict, str], str]], ...] = (
    ("resumen", "Resumen", _resumen),
    ("resultados", "Resultados", _resultados),
    ("balance", "Balance", _balance),
    ("costos", "Costos", _costos),
    ("materiales", "Materiales", _materiales),
    ("ventas", "Ventas", _ventas),
    ("calidad", "Calidad", _calidad),
)


#: Pestañas a las que aplica el período (las demás muestran todo el historial).
CON_PERIODO = (
    "resumen",
    "resultados",
    "balance",
    "costos",
    "materiales",
    "ventas",
)
_NOMBRES_MES = (
    "enero",
    "febrero",
    "marzo",
    "abril",
    "mayo",
    "junio",
    "julio",
    "agosto",
    "septiembre",
    "octubre",
    "noviembre",
    "diciembre",
)


def _entero_o_nada(texto: str, desde: int, hasta: int) -> int | None:
    return int(texto) if texto.isdigit() and desde <= int(texto) <= hasta else None


def _selector(foto: dict, tok: str, vista: str, anio: int | None, mes: int | None) -> str:
    """El período: un año (o todos) y un mes (o todos), sin JavaScript obligatorio."""
    anios = fin.anios(foto)
    opciones_anio = "<option value=''>Todos los años</option>" + "".join(
        f"<option value={a}{' selected' if a == anio else ''}>{a}</option>" for a in anios
    )
    con_datos = sorted(
        {
            int(fin.numero(m.get("MesKey"))) % 100
            for m in fin.del_periodo(foto, anio).get("mensual", [])
        }
    )
    opciones_mes = "<option value=''>Todo el año</option>" + "".join(
        f"<option value={m}{' selected' if m == mes else ''}>"
        f"{_NOMBRES_MES[m - 1]}</option>"
        for m in con_datos
    )
    return (
        "<form method=get action='/panel/finanzas' class=periodo>"
        f"<input type=hidden name=token value='{tok}'>"
        f"<input type=hidden name=vista value='{vista}'>"
        f"<label>Período <select name=anio onchange='this.form.submit()'>{opciones_anio}"
        f"</select></label> <select name=mes onchange='this.form.submit()'>{opciones_mes}"
        "</select> <button>Ver</button></form>"
    )


def _texto_periodo(anio: int | None, mes: int | None) -> str:
    if anio is None:
        return "todo el historial"
    return f"{_NOMBRES_MES[mes - 1]} {anio}" if mes else f"todo {anio}"


def pagina(
    foto: dict | None,
    token: str,
    cabecera,
    vista: str = "resumen",
    anio: str = "",
    mes: str = "",
) -> str:
    tok = html.escape(token)
    claves = [v[0] for v in VISTAS]
    vista = vista if vista in claves else "resumen"
    a = _entero_o_nada(str(anio), 2000, 2100)
    m = _entero_o_nada(str(mes), 1, 12) if a else None
    filtro = (f"&anio={a}" if a else "") + (f"&mes={m}" if m else "")
    pestanas = "".join(
        f"<a href='/panel/finanzas?token={tok}&vista={c}{filtro}'"
        f"{' class=activa' if c == vista else ''}>{n}</a>"
        for c, n, _ in VISTAS
    )
    boton = (
        f"<form method=post action='/panel/finanzas/erp?token={tok}&vista={vista}'>"
        "<button class=principal>🔄 Actualizar del ERP</button></form>"
    )
    leido = ""
    if foto and foto.get("leido"):
        try:
            hace = datetime.now(UTC) - datetime.fromisoformat(str(foto["leido"]))
            minutos = int(hace.total_seconds() // 60)
            leido = (
                f"leído del ERP hace {minutos} min"
                if minutos < 120
                else f"leído del ERP hace {minutos // 60} h"
            )
        except ValueError:
            leido = ""
    cuerpo = [
        cabecera("Finanzas · Luna Joyas").replace(
            "</style>", ESTILO_MARKETING + ESTILO + "</style>"
        ),
        "<header><h1>💰 Finanzas</h1><div class=sub>"
        f"<a href='/panel?token={tok}'>← taller</a> · "
        f"<a href='/panel/marketing?token={tok}'>marketing</a> · "
        f"<a href='/panel/todo?token={tok}'>todo</a></div>"
        + (f"<div class=revision>{_t(leido)}</div>" if leido else "")
        + f"<nav class=pestanas>{pestanas}</nav></header><main>",
    ]
    if not foto:
        cuerpo.append(
            _seccion(
                "Todavía no hay foto del ERP",
                "<p>Se toma con <code>vb erp --montar</code>, cada hora desde el bot o "
                "con este botón.</p>" + boton,
            )
        )
    else:
        datos = foto
        if vista in CON_PERIODO:
            datos = {**fin.del_periodo(foto, a, m), "_todo": foto, "_periodo": (a, m)}
            cuerpo.append(
                f"<section class=periodo-caja>{_selector(foto, tok, vista, a, m)}"
                "<p class=ayuda>Mostrando: "
                f"<b>{_t(_texto_periodo(a, m))}</b></p></section>"
            )
        hacer = next(v[2] for v in VISTAS if v[0] == vista)
        try:
            cuerpo.append(hacer(datos, token))
        except Exception as exc:  # una pestaña rota no tumba la página
            log.warning("finanzas: la pestaña %s no se pudo mostrar (%s)", vista, exc)
            cuerpo.append(
                "<section><div class='alerta aviso'><b>⚠️ Esta parte no se pudo "
                "mostrar</b>La foto del ERP llegó con un formato inesperado: "
                "actualízala o avísale a Camilo.</div></section>"
            )
        cuerpo.append(f"<section>{boton}</section>")
    siguiente = claves[(claves.index(vista) + 1) % len(claves)]
    nombre = next(n for c, n, _ in VISTAS if c == siguiente)
    cuerpo.append(
        f"<p class=siguiente><a href='/panel/finanzas?token={tok}&vista={siguiente}"
        f"{filtro}'>Siguiente: {nombre} →</a></p></main></body></html>"
    )
    return "".join(cuerpo)


COLORES_PRODUCTO = ("#e7b3c3", "#c96f8b", "#8e3b5a", "#d39b1f", "#8e7cc3", "#3f7d5a")


def _costo_mes_a_mes(c: dict) -> str:
    """El costo de cada pieza con la plata de cada mes (hoja Costeo)."""
    por_mes = [x for x in c.get("por_mes", []) if isinstance(x, dict)]
    if not por_mes:
        return ""
    piezas = c.get("piezas", [])
    etiquetas = [_corta(x.get("mes")) for x in por_mes]
    filas = [
        [
            _t(fin.nombre_mes(x.get("mes"))),
            _pesos(x.get("plata")),
            *(_pesos(v) for v in x.get("costos", [])),
        ]
        for x in por_mes
    ]
    return _seccion(
        "El costo mes a mes (la plata cambia)",
        _linea(
            etiquetas,
            [fin.numero((x.get("costos") or [0])[0]) for x in por_mes],
            "#c96f8b",
            "Anillo de 1 huellita",
            desde_cero=False,
        )
        + _tabla(["Mes", "Plata $/g", *piezas], filas, set(range(1, len(piezas) + 2))),
        "mes-a-mes",
        "Costo completo de cada pieza con el precio de la plata de ese mes (lo que "
        "anotó Camilo en la hoja Precio_Plata).",
    )


def _plata_mes_a_mes(f: dict) -> str:
    anio, mes = f.get("_periodo") or (None, None)
    precios = [
        x
        for x in f.get("plata", [])
        if isinstance(x, dict)
        and (anio is None or int(fin.numero(x.get("mes"))) // 100 == anio)
        and (mes is None or int(fin.numero(x.get("mes"))) % 100 == mes)
    ]
    if not precios:
        return ""
    return _seccion(
        "La plata, mes a mes",
        _linea(
            [_corta(x.get("mes")) for x in precios],
            [fin.numero(x.get("precio")) for x in precios],
            "#8e7cc3",
            "Plata 925 ($/g)",
            desde_cero=False,
        )
        + _tabla(
            ["Mes", "Precio por gramo", "Fuente"],
            [
                [
                    _t(fin.nombre_mes(x.get("mes"))),
                    _pesos(x.get("precio")),
                    f"<small>{_t(x.get('fuente'))}</small>",
                ]
                for x in precios
            ],
            {1},
        ),
        "plata",
        "Lo que costó el gramo de plata 925 cada mes (hoja Precio_Plata del ERP). El "
        "último es el precio de hoy, con el que se calcula la receta.",
    )


def _cierre(f: dict) -> str:
    anio, _mes = f.get("_periodo") or (None, None)
    meses = f.get("mensual", [])
    if anio is None or not meses:
        return ""
    hasta = int(fin.numero(meses[-1].get("MesKey")))
    c = fin.cierre(f.get("_todo", f), hasta)
    if not c:
        return ""
    filas = [
        ("Caja estimada", c["caja"]),
        ("Equipos del taller (costo)", c["equipos"]),
        ("(−) Depreciación acumulada", c["depreciacion"]),
        ("Utilidades desde el primer mes", c["utilidades"]),
    ]
    return _seccion(
        f"Al cierre de {fin.nombre_mes(c['mes'])}",
        "<div class=estado-cuenta>"
        + "".join(
            f"<div><span>{_t(n)}</span><span{' class=malo' if v < 0 else ''}>"
            f"{_pesos(v)}</span></div>"
            for n, v in filas
        )
        + "</div>",
        "cierre",
        "Lo que se puede saber de esa fecha con lo que hay en el ERP. Los saldos por "
        "cobrar y las deudas solo se conocen hoy (abajo).",
    )
