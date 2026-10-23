"""La sábana de ventas de Camilo («HUELLAS 2026.xlsx») leída como ventas del ERP.

La sábana es como Lía la lleva a mano, no una tabla. Lo que hay que saber
(revisado el 01/10 con la de ene–sep 2026):

- Una hoja por mes («Enero» … «Septiembre») y una «Resumen» con los totales
  que Camilo escribe a mano (unidades, ventas, publicidad por mes).
- En cada mes, arriba, un «Resumen del mes» y, debajo, la tabla: una fila con
  encabezados DIA · CELULAR · TALLA · COLOR · GRABADO · ABONO · MEDIO DE PAGO ·
  RESTANTE · pendiente · TOTAL. Desde agosto hay una columna más a la izquierda
  (de dónde vino la clienta: «PUBLICIDAD» o «vieja»).
- **Una venta = una fila con TOTAL.** Un anillo de 2 o 3 huellitas ocupa 2 o 3
  filas: la de la venta y debajo «HUELLA 2: …», «HUELLA 3: …» (color y, a
  veces, grabado), sin fecha ni total. Esas filas son de la misma venta.
- Al final de algunos meses hay una fila con la SUMA (un TOTAL de millones sin
  fecha ni talla): no es una venta.
- Fechas escritas solo con el día («5»): Excel las guarda como 05/01/1900. Se
  arreglan con el mes de la hoja.

Todo lo que se arregla o no cuadra queda en `avisos` para mostrárselo a
Camilo; nada se inventa en silencio.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime

MESES = (
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
#: Precio de lista de un anillo según sus huellitas (catálogo del bot y del ERP).
PRECIO_ANILLO = {1: 200_000, 2: 250_000, 3: 300_000}
#: Un TOTAL por encima de esto en una fila sin fecha ni talla es la suma del mes.
TOPE_DE_UNA_VENTA = 1_000_000
#: De dónde vino la clienta (columna de la izquierda, desde agosto) → Cat_Canales.
CANALES = {"publicidad": "Instagram", "vieja": "Clienta antigua"}
SIN_CANAL = "Por clasificar"
PREFIJO = "SABANA"


@dataclass
class VentaDeSabana:
    ref: str  # «SABANA 2026-01 F14»: la hoja y la fila; así se reimporta sin duplicar
    fecha: date
    producto: str
    huellitas: int
    celular: str
    talla: str
    colores: list[str] = field(default_factory=list)
    grabados: list[str] = field(default_factory=list)
    abono: int = 0
    total: int = 0
    canal: str = SIN_CANAL

    @property
    def saldo(self) -> int:
        return max(self.total - self.abono, 0)

    @property
    def mes(self) -> int:
        return self.fecha.year * 100 + self.fecha.month


@dataclass
class Sabana:
    ventas: list[VentaDeSabana]
    #: {AAAAMM: (unidades, ventas_cop, publicidad_cop)} de la hoja «Resumen».
    resumen: dict[int, tuple[int, int, int]]
    avisos: list[str]

    def por_mes(self) -> dict[int, tuple[int, int]]:
        """{AAAAMM: (ventas, pesos)} contando el detalle."""
        salida: dict[int, tuple[int, int]] = {}
        for v in self.ventas:
            n, s = salida.get(v.mes, (0, 0))
            salida[v.mes] = (n + 1, s + v.total)
        return salida

    def cuadre(self) -> list[tuple[int, int, int, int, int]]:
        """(mes, ventas del detalle, del resumen, pesos del detalle, del resumen)."""
        detalle = self.por_mes()
        meses = sorted(set(detalle) | set(self.resumen))
        return [
            (
                m,
                detalle.get(m, (0, 0))[0],
                self.resumen.get(m, (0, 0, 0))[0],
                detalle.get(m, (0, 0))[1],
                self.resumen.get(m, (0, 0, 0))[1],
            )
            for m in meses
        ]


def _texto(x) -> str:
    if x is None:
        return ""
    if isinstance(x, float) and x.is_integer():
        x = int(x)
    return str(x).strip()


def _entero(x) -> int | None:
    if isinstance(x, bool) or x in (None, ""):
        return None
    if isinstance(x, (int, float)):
        return round(x)
    solo = re.sub(r"[^\d]", "", str(x))
    return int(solo) if solo else None


def celular(x) -> str:
    """Los 10 dígitos colombianos, o vacío si lo anotado no es un número."""
    if isinstance(x, float) and x.is_integer():
        x = int(x)
    solo = re.sub(r"\D", "", str(x or ""))
    return solo[-10:] if len(solo) >= 10 else ""


def talla(x) -> str:
    """«TALLA 7 1/2» → «TALLA 7.5», como la escribe el bot (un decimal se ordena y
    se filtra; una fracción no). Lo que no es una talla limpia («un poquitín más
    de 7», «16.71mm», «Ajustable») se deja tal cual lo anotó Lía."""
    t = re.sub(r"\s+", " ", _texto(x))
    numero = re.sub(r"(?i)^talla\s*", "", t).strip()
    m = re.fullmatch(r"(\d{1,2})(?:\s+(\d)\s*/\s*(\d))?", numero)
    if m:
        valor = int(m[1]) + (int(m[2]) / int(m[3]) if m[2] else 0)
    elif re.fullmatch(r"\d{1,2}[.,]\d{1,2}", numero):
        valor = float(numero.replace(",", "."))
    else:
        return t
    return f"TALLA {valor:g}" if 2 <= valor <= 14 else t


def producto_de(tipo: str, huellitas: int) -> str:
    t = tipo.lower()
    if "manilla" in t:
        return "Manilla"
    if "dije" in t:
        return "Dije"
    if "cadena" in t:
        return "Cadena"
    return f"Anillos {min(max(huellitas, 1), 3)} huella"


def _fecha(x, año: int, mes: int) -> tuple[date | None, str]:
    """(fecha, aviso). Una fecha de 1900 es «solo el día»: se le pone el mes."""
    if isinstance(x, datetime):
        x = x.date()
    if isinstance(x, date):
        if x.year == 1900:
            return date(año, mes, x.day), "día sin mes ni año"
        return x, ""
    if isinstance(x, (int, float)) and 1 <= int(x) <= 31:
        return date(año, mes, int(x)), "día sin mes ni año"
    return None, ""


def _encabezados(filas: list[list]) -> tuple[int, dict[str, int]] | None:
    for i, f in enumerate(filas):
        nombres = [_texto(c).upper() for c in f]
        if "DIA" in nombres and "TOTAL" in nombres:
            cols = {n: j for j, n in enumerate(nombres) if n}
            return i, cols
    return None


def leer_mes(
    nombre: str, filas: list[list], año: int
) -> tuple[list[VentaDeSabana], list[str]]:
    mes = MESES.index(nombre.strip().lower()) + 1
    clave = f"{año}-{mes:02d}"
    hallado = _encabezados(filas)
    if hallado is None:
        return [], [f"{nombre}: no encontré la fila de encabezados (DIA … TOTAL)"]
    h, cols = hallado

    def col(fila: list, nombre_col: str):
        j = cols.get(nombre_col)
        return fila[j] if j is not None and j < len(fila) else None

    origen_j = cols["DIA"] - 1 if cols["DIA"] > 0 else None
    ventas: list[VentaDeSabana] = []
    avisos: list[str] = []
    sin_mes = sin_celular = 0
    for i, fila in enumerate(filas[h + 1 :], start=h + 2):
        total = _entero(col(fila, "TOTAL"))
        tipo = _texto(col(fila, "TALLA"))
        color = _texto(col(fila, "COLOR"))
        grabado = _texto(col(fila, "GRABADO"))
        dia = col(fila, "DIA")
        if total:
            if total > TOPE_DE_UNA_VENTA and not tipo and dia in (None, ""):
                continue  # la fila de la suma del mes
            fecha, aviso = _fecha(dia, año, mes)
            if aviso:
                sin_mes += 1
            if fecha is None:
                fecha = ventas[-1].fecha if ventas else date(año, mes, 1)
                avisos.append(f"{nombre} fila {i}: sin fecha; se usó {fecha:%d/%m}")
            elif (fecha.year, fecha.month) != (año, mes):
                avisos.append(
                    f"{nombre} fila {i}: la fecha {fecha:%d/%m/%Y} no es del mes "
                    "de la hoja"
                )
            tel = celular(col(fila, "CELULAR"))
            if not tel:
                sin_celular += 1
            origen = _texto(fila[origen_j]).lower() if origen_j is not None else ""
            ventas.append(
                VentaDeSabana(
                    ref=f"{PREFIJO} {clave} F{i}",
                    fecha=fecha,
                    producto="",
                    huellitas=1,
                    celular=tel,
                    talla=talla(tipo),
                    colores=[color] if color else [],
                    grabados=[grabado] if grabado else [],
                    abono=_entero(col(fila, "ABONO")) or 0,
                    total=total,
                    canal=CANALES.get(origen, SIN_CANAL),
                )
            )
            ventas[-1].producto = tipo  # provisional: se resuelve al cerrar la venta
        elif ventas and (color or grabado) and dia in (None, ""):
            # Otra huellita del mismo anillo.
            if color:
                ventas[-1].colores.append(color)
            if grabado:
                ventas[-1].grabados.append(grabado)
    for v in ventas:
        tipo = v.producto
        es_anillo = not re.search(r"(?i)manilla|dije|cadena", tipo)
        v.huellitas = max(len(v.colores), 1) if es_anillo else 1
        v.producto = producto_de(tipo, v.huellitas)
        if es_anillo:
            v.talla = v.talla or ""
            lista = PRECIO_ANILLO.get(v.huellitas)
            if v.huellitas > 3:
                avisos.append(
                    f"{v.ref}: {v.huellitas} filas de huellitas; se cuenta como 3"
                )
            elif lista and v.total not in (lista,) and v.total in PRECIO_ANILLO.values():
                avisos.append(
                    f"{v.ref}: {v.huellitas} huellita(s) pero TOTAL ${v.total:,}"
                    " (precio de otro anillo)".replace(",", ".")
                )
        else:
            v.talla = ""
    if sin_mes:
        avisos.append(
            f"{nombre}: {sin_mes} fecha(s) tenían solo el día; se les puso {clave}"
        )
    if sin_celular:
        avisos.append(
            f"{nombre}: {sin_celular} venta(s) sin celular (anotado un nombre o vacío)"
        )
    return ventas, avisos


def leer_resumen(filas: list[list], año: int) -> dict[int, tuple[int, int, int]]:
    salida: dict[int, tuple[int, int, int]] = {}
    for f in filas:
        textos = [_texto(c).lower() for c in f]
        for j, t in enumerate(textos):
            if t in MESES:
                nums = [_entero(c) for c in f[j + 1 : j + 4]]
                if all(n is not None for n in nums):
                    u, v, p = nums
                    salida[año * 100 + MESES.index(t) + 1] = (u, v, p)  # type: ignore[assignment]
                break
    return salida


def leer(hojas: dict[str, list[list]], año: int) -> Sabana:
    """Todas las hojas de mes (en orden) y el resumen."""
    ventas: list[VentaDeSabana] = []
    avisos: list[str] = []
    for nombre, filas in hojas.items():
        if nombre.strip().lower() in MESES:
            v, a = leer_mes(nombre, filas, año)
            ventas += v
            avisos += a
    resumen = next(
        (
            leer_resumen(f, año)
            for n, f in hojas.items()
            if n.strip().lower() == "resumen"
        ),
        {},
    )
    ventas.sort(key=lambda v: (v.fecha, v.ref.split()[1], int(v.ref.rsplit("F", 1)[1])))
    return Sabana(ventas, resumen, avisos)
