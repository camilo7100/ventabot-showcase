"""El marketing en el ERP: la pauta real en la hoja `Publicidad` (01/10).

El ERP (HUELLAS_ERP_v1) ya sabe qué hacer con la publicidad: su hoja
`Publicidad` (captura) alimenta `Mensual` (la utilidad después de pauta, el
CAC) y el `Dashboard` (ROAS, conversión). Estaba vacía. Ahora, cada vez que se
sube la carpeta de marketing, el bot la llena con `datos/meta_campanas_mensual.csv`:
una fila por campaña y mes, con lo gastado y las conversaciones (reales: salen
de Ads Manager).

Las filas del bot se reconocen por la columna `Origen_Ref` («MKT 2026-09 ·
Nombre de la campaña»): se actualizan y se quitan solas, y una fila que
Camilo escriba a mano (sin esa marca) no se toca nunca.

Puro: sin red. Quien escribe es `app/adapters/erp/marketing.py`.
"""

from __future__ import annotations

import calendar
from datetime import date

from app.domain.marketing_numeros import leer_csv, numero

#: La columna que agrega el bot al final de `Publicidad` para reconocer sus filas.
REFERENCIA = "Origen_Ref"
PREFIJO = "MKT "
#: Las columnas de captura de `Publicidad` (las demás son fórmulas del ERP).
COLUMNAS = (
    "Fecha_Inicio",
    "Fecha_Fin",
    "Canal",
    "Campaña",
    "Inversion",
    "Conversaciones",
    "Leads",
)
#: Todo lo pautado es de Instagram (Meta); así se llama en `Cat_Canales`.
CANAL = "Instagram"


def referencia(mes: str, campana: str) -> str:
    return f"{PREFIJO}{mes} · {campana.strip()}"


def filas_de_publicidad(campanas_csv: str) -> dict[str, dict[str, object]]:
    """{Origen_Ref: fila} de lo que debe haber en `Publicidad`.

    Una fila por (mes, campaña); si la tabla trae la misma campaña dos veces en
    un mes, se suman. Las filas sin gasto no van (no son publicidad).
    """
    sumas: dict[str, tuple[date, str, float, float]] = {}
    for f in leer_csv(campanas_csv):
        mes, campana = f.get("mes", ""), f.get("campana", "").strip()
        gasto = numero(f.get("gasto_cop"))
        if not campana or not gasto:
            continue
        try:
            inicio = date(int(mes[:4]), int(mes[5:7]), 1)
        except ValueError:
            continue
        if len(mes) != 7:
            continue
        ref = referencia(mes, campana)
        conversaciones = numero(f.get("conversaciones_iniciadas")) or 0
        _, _, g, c = sumas.get(ref, (inicio, campana, 0.0, 0.0))
        sumas[ref] = (inicio, campana, g + gasto, c + conversaciones)

    filas: dict[str, dict[str, object]] = {}
    for ref, (inicio, campana, gasto, conversaciones) in sumas.items():
        ultimo = calendar.monthrange(inicio.year, inicio.month)[1]
        filas[ref] = {
            "Fecha_Inicio": inicio.isoformat(),
            "Fecha_Fin": inicio.replace(day=ultimo).isoformat(),
            "Canal": CANAL,
            "Campaña": campana,
            "Inversion": round(gasto),
            "Conversaciones": round(conversaciones),
            "Leads": "",
        }
    return filas


def desde_el_mes(
    filas: dict[str, dict[str, object]], primer_mes: int | None
) -> dict[str, dict[str, object]]:
    """Solo las filas desde `primer_mes` (AAAAMM) en adelante.

    El ERP cuenta la pauta contra SUS ventas: poner meses de pauta sin ventas
    cargadas pinta pérdidas que no existen (el Dashboard de 2026 salía en
    −$16,5 millones con la pauta de nueve meses contra las ventas de prueba de
    uno; 01/10). Así entra desde el primer mes con ventas del ERP (`Config`), y
    el día que se cargue el historial real, los meses anteriores entran solos.
    """
    if not primer_mes:
        return filas
    return {
        ref: f
        for ref, f in filas.items()
        if int(str(f["Fecha_Inicio"])[:4]) * 100 + int(str(f["Fecha_Inicio"])[5:7])
        >= primer_mes
    }
