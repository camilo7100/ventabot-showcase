"""La foto de las finanzas del ERP para el panel (`/panel/finanzas`, 01/10).

Solo lectura: estado de resultados por mes, el costeo (y su costo mes a mes),
el precio de la plata, los materiales, los gastos por concepto, el balance, lo
que Validaciones marca y las ventas UNA POR UNA pero sin la clienta (fecha,
pieza, canal, talla, colores y total; para filtrar por año y mes en el panel).
Ningún celular, nombre ni grabado sale de aquí (de Rank_Clientes se leen solo
los indicadores de la columna B).

La foto se guarda en `estado/finanzas/erp.json`: la toman `vb erp --montar`,
la importación de la sábana, el botón «Actualizar del ERP» del panel y el
hilo del ERP del bot cada hora.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import app.adapters.erp.montaje.costeo as costeo_hoja
from app.adapters.erp.marketing import _numero, _por_nombre
from app.adapters.erp.montaje import (
    BALANCE,
    COSTEO,
    FILAS_BALANCE,
    GRAFICAS,
    PLATA,
    bloques,
)
from app.adapters.erp.sheets import Hoja

CAMPOS_MENSUAL = (
    "MesKey",
    "Ingresos",
    "Unidades",
    "N_Ventas",
    "Descuentos",
    "COGS_Std",
    "Margen_Bruto",
    "Publicidad",
    "Gastos",
    "Deprec",
    "Utilidad_Op",
    "Clientes_Nuevos",
    "CAC",
    "Cobros",
    "Salidas_Caja",
    "Flujo",
    "Flujo_Acum",
)


def _fila(filas: list[list], n: int) -> list:
    """La fila n (1-based) de un rango leído desde la fila 1."""
    return filas[n - 1] if 0 < n <= len(filas) else []


def _celda(fila: list, j: int):
    return fila[j] if j < len(fila) else ""


def foto(hoja: Hoja) -> dict:
    (
        mensual,
        config,
        costeo,
        graficas,
        productos,
        materiales,
        inventario,
        gastos,
        validaciones,
        clientes,
        balance,
        plata,
        ventas,
    ) = hoja.leer(
        [
            "Mensual!A3:W40",
            "Config!A1:F30",
            f"{COSTEO}!A1:F{costeo_hoja.ULTIMA_FILA}",
            f"'{GRAFICAS}'!A1:H260",
            "Cat_Productos!A3:K40",
            "Cat_Materiales!A3:H60",
            "Inventario!A3:L60",
            "Gastos!A3:G2000",
            "Validaciones!A3:E30",
            "Rank_Clientes!A3:B10",
            f"{BALANCE}!A1:C30",
            f"{PLATA}!A1:C200",
            "Ventas!A3:AH2003",
        ]
    )
    parametros = {
        str(f[0]).strip(): f[1] for f in config[3:] if len(f) > 1 and str(f[0]).strip()
    }
    ultimo = int(_numero(parametros.get("Último mes con ventas (clave)")))
    meses = [
        {k: m.get(k, "") for k in CAMPOS_MENSUAL}
        for m in _por_nombre(mensual)
        if _numero(m.get("MesKey")) and (not ultimo or _numero(m.get("MesKey")) <= ultimo)
    ]

    supuestos = [
        {
            "nombre": _celda(f, 0),
            "valor": _celda(f, 1),
            "unidad": _celda(f, 2),
            "calidad": _celda(f, 3),
            "porque": _celda(f, 4),
        }
        for f in (
            _fila(costeo, n)
            for n in range(costeo_hoja.FILA_SUPUESTOS, costeo_hoja.FILA_SECCION_CAPAS)
        )
        if _celda(f, 0)
    ]
    cab = _fila(costeo, costeo_hoja.FILA_PIEZAS)
    piezas = [str(x) for x in cab[1:5]]
    capas = [
        {
            "clave": clave,
            "concepto": _celda(f, 0),
            "valores": [_celda(f, j) for j in range(1, 1 + len(piezas))],
            "fuente": _celda(f, 1 + len(piezas)),
        }
        for clave, f in (
            (c[0], _fila(costeo, costeo_hoja.fila("C:" + c[0])))
            for c in costeo_hoja.CAPAS
        )
        if _celda(f, 0)
    ]
    resumen = [
        {
            "clave": clave,
            "concepto": _celda(f, 0),
            "valor": _celda(f, 1),
            "fuente": _celda(f, 5),
        }
        for clave, f in (
            (r[0], _fila(costeo, costeo_hoja.fila("R:" + r[0])))
            for r in costeo_hoja.RESUMEN
        )
        if _celda(f, 0)
    ]
    # La fila k del costo mes a mes es la fila 4 + k de la hoja de la plata.
    por_mes = [
        {
            "mes": int(_numero(_celda(_fila(plata, 4 + k), 0))),
            "plata": _celda(f, 1),
            "costos": [_celda(f, j) for j in range(2, 2 + len(piezas))],
        }
        for k, f in (
            (k, _fila(costeo, costeo_hoja.FILA_PRIMER_MES + k))
            for k in range(costeo_hoja.MESES_DE_PLATA)
        )
        if str(_celda(f, 0)).strip() and _numero(_celda(_fila(plata, 4 + k), 0))
    ]
    precios_plata = [
        {"mes": int(_numero(f[0])), "precio": _numero(f[1]), "fuente": _celda(f, 2)}
        for f in plata[3:]
        if len(f) > 1 and _numero(f[0]) and _numero(f[1])
    ]
    c = {str(x).strip(): j for j, x in enumerate(ventas[0])} if ventas else {}

    def de_venta(fila: list, columna: str):
        j = c.get(columna)
        return fila[j] if j is not None and j < len(fila) else ""

    lista_ventas = [
        {
            "fecha": str(de_venta(f, "Fecha")),
            "mes": int(_numero(de_venta(f, "MesKey"))),
            "producto": de_venta(f, "Producto"),
            "canal": de_venta(f, "Canal"),
            "talla": de_venta(f, "Talla"),
            "colores": de_venta(f, "Color_Detalle"),
            "total": _numero(de_venta(f, "Total")),
            "nueva": int(_numero(de_venta(f, "Cliente_Nuevo"))),
        }
        for f in ventas[1:]
        if str(de_venta(f, "Fecha")).strip() and _numero(de_venta(f, "MesKey"))
    ]

    tablas = {}
    for b in bloques():
        filas = [_fila(graficas, b.inicio + 3 + i) for i in range(len(b.filas))]
        tablas[b.titulo] = {
            "encabezados": b.encabezados,
            "filas": [
                [_celda(f, j) for j in range(len(b.encabezados))]
                for f in filas
                if str(_celda(f, 0)).strip()
            ],
        }

    stock = {str(f.get("Material", "")).strip(): f for f in _por_nombre(inventario)}
    lista_materiales = []
    for m in _por_nombre(materiales):
        nombre = str(m.get("Material", "")).strip()
        if not nombre:
            continue
        inv = stock.get(nombre, {})
        lista_materiales.append(
            {
                "material": nombre,
                "unidad": m.get("Unidad", ""),
                "costo": m.get("Costo_Unitario", ""),
                "calidad": m.get("Calidad_Dato", ""),
                "fuente": m.get("Fuente", ""),
                "stock": inv.get("Stock", ""),
                "estado": inv.get("Estado", ""),
            }
        )

    por_concepto: dict[str, dict] = {}
    for g in _por_nombre(gastos):
        concepto = str(g.get("Concepto", "")).strip()
        if not concepto or not _numero(g.get("Monto")):
            continue
        x = por_concepto.setdefault(
            concepto,
            {
                "concepto": concepto,
                "categoria": g.get("Categoria", ""),
                "calidad": g.get("Calidad_Dato", ""),
                "total": 0.0,
                "meses": 0,
            },
        )
        x["total"] += _numero(g.get("Monto"))
        x["meses"] += 1

    return {
        "leido": datetime.now(UTC).isoformat(timespec="seconds"),
        "parametros": {
            k: v
            for k, v in parametros.items()
            if k
            in (
                "Precio plata ($/g)",
                "Mano de obra por pieza ($)",
                "Capacidad mensual (unidades)",
                "Costo real por anillo ($)",
                "Primer mes con ventas (clave)",
                "Último mes con ventas (clave)",
            )
        },
        "mensual": meses,
        "costeo": {
            "supuestos": supuestos,
            "piezas": piezas,
            "capas": capas,
            "resumen": resumen,
            "por_mes": por_mes,
        },
        "plata": precios_plata,
        "ventas": lista_ventas,
        "tablas": tablas,
        "productos": [
            {
                k: p.get(k, "")
                for k in (
                    "Producto",
                    "Categoria",
                    "Precio_Lista",
                    "Costo_Materiales",
                    "Costo_MO",
                    "Costo_Total",
                    "Margen_Unit",
                    "Calidad_Dato",
                )
            }
            for p in _por_nombre(productos)
            if str(p.get("Producto", "")).strip()
        ],
        "materiales": lista_materiales,
        "gastos": sorted(por_concepto.values(), key=lambda x: -x["total"]),
        "clientas": {
            str(f[0]).strip(): f[1]
            for f in clientes[1:]
            if len(f) > 1 and str(f[0]).strip()
        },
        "balance": [
            {
                "concepto": c,
                "valor": _celda(_fila(balance, n), 1) if t != "seccion" else "",
                "tipo": t,
                "nota": nota,
            }
            for n, c, _, t, nota in FILAS_BALANCE
        ],
        "validaciones": [
            {
                "numero": v.get("#", ""),
                "chequeo": v.get("Chequeo", ""),
                "resultado": v.get("Resultado", ""),
                "estado": v.get("Estado", ""),
                "donde": v.get("Dónde corregir", ""),
            }
            for v in _por_nombre(validaciones)
            if str(v.get("Chequeo", "")).strip()
        ],
    }


def guardar(hoja: Hoja, destino: Path) -> dict:
    datos = foto(hoja)
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text(json.dumps(datos, ensure_ascii=False, indent=1), encoding="utf-8")
    return datos
