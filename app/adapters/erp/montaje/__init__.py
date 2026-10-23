"""El ERP completo: costos, plata mes a mes, gastos, gráficas y balance.

`vb erp --montar` (y la importación de la sábana) lo deja todo así. Se puede
correr mil veces: lo que Camilo o Lía anotan (supuestos, precios de la plata,
deudas, el año elegido en Gráficas) no se pisa, y nada se duplica.

Cada parte vive en su módulo:

- `catalogos`: productos, canales, materiales y la receta con los gramos reales.
- `plata`: el precio de la plata de cada mes y el costo de cada venta con el
  de su mes.
- `costeo`: el costo completo de cada pieza, capa por capa y mes a mes; Config
  («Costo real por anillo», el que usa el marketing) apunta ahí.
- `gastos`: los gastos fijos estimados (salario de Lía incluido) mes a mes.
- `graficas`: las tablas y gráficas, con año y mes para elegir.
- `balance`: la caja de Mensual y la hoja Balance.
- `leeme`: lo que se cuenta en el LEEME.
"""

from __future__ import annotations

from app.adapters.erp.montaje.balance import FILAS_BALANCE, caja_y_balance
from app.adapters.erp.montaje.catalogos import montar_catalogos, receta_deseada
from app.adapters.erp.montaje.comun import (
    BALANCE,
    CIRCON,
    COSTEO,
    GRAFICAS,
    PARAMETRO_COSTO,
    PIEZAS,
    PLATA,
    PRODUCTOS,
    HojaConFormato,
    ResultadoMontaje,
)
from app.adapters.erp.montaje.costeo import (
    CALCULADOS,
    CAPAS,
    RESUMEN,
    SUPUESTOS,
    enlazar,
    fila,
    formato_costeo,
    montar_costeo,
)
from app.adapters.erp.montaje.gastos import gastos_fijos, montar_gastos
from app.adapters.erp.montaje.graficas import bloques, montar_graficas
from app.adapters.erp.montaje.leeme import montar_leeme
from app.adapters.erp.montaje.plata import PRECIOS_2026, montar_plata

__all__ = [
    "BALANCE",
    "CALCULADOS",
    "CAPAS",
    "CIRCON",
    "COSTEO",
    "FILAS_BALANCE",
    "GRAFICAS",
    "PARAMETRO_COSTO",
    "PIEZAS",
    "PLATA",
    "PRECIOS_2026",
    "PRODUCTOS",
    "RESUMEN",
    "SUPUESTOS",
    "HojaConFormato",
    "ResultadoMontaje",
    "bloques",
    "fila",
    "gastos_fijos",
    "montar",
    "receta_deseada",
]

#: Dónde va cada hoja nueva: (hoja, la que queda antes).
ORDEN = (
    (PLATA, "Config"),
    (COSTEO, "Cat_Productos"),
    (BALANCE, "Mensual"),
    (GRAFICAS, "Dashboard"),
)


def ordenar(hoja: HojaConFormato) -> None:
    """Cada hoja nueva junto a las de su tipo (catálogos, procesamiento, tablero)."""
    for nombre, despues_de in ORDEN:
        info = hoja.pestanas()
        nombres = list(info)
        if nombre not in nombres or despues_de not in nombres:
            continue
        destino = nombres.index(despues_de) + 1
        if nombres.index(nombre) != destino:
            hoja.lote(
                [
                    {
                        "updateSheetProperties": {
                            "properties": {
                                "sheetId": info[nombre]["id"],
                                "index": destino,
                            },
                            "fields": "index",
                        }
                    }
                ]
            )


def montar(
    hoja: HojaConFormato, fecha: str, meses: list[int], resumen_sabana: str
) -> ResultadoMontaje:
    # Primero todas las hojas: una fórmula no puede apuntar a una que no existe.
    for nombre in (PLATA, COSTEO, BALANCE, GRAFICAS):
        hoja.asegurar_hoja(nombre)
    r = ResultadoMontaje()
    r.hechos += montar_catalogos(hoja, fecha)
    r.hechos += montar_costeo(hoja)
    formato_costeo(hoja)
    r.hechos += montar_plata(hoja)
    r.hechos += enlazar(hoja, fecha)
    r.hechos += montar_gastos(hoja, meses)
    r.hechos += montar_graficas(hoja)
    r.hechos += caja_y_balance(hoja)
    r.hechos += montar_leeme(hoja, resumen_sabana)
    ordenar(hoja)
    return r
