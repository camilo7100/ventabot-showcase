"""Lo que dicen las finanzas del ERP, en frases (`/panel/finanzas`, 01/10).

Trabaja sobre la foto de `app.adapters.erp.finanzas` (un dict con totales):
el resumen del año y los hallazgos que un contador le señalaría a Camilo.
Nada aquí inventa números: todo sale de la foto y, si falta, no se dice.
"""

from __future__ import annotations

from dataclasses import dataclass

#: Un ROAS por debajo de esto, con los gastos fijos de hoy, deja el mes en rojo
#: o casi (ene–sep 2026: los meses de ROAS 3,2 cerraron en pérdida).
ROAS_FLOJO = 4.0
#: Camilo, 02/10: «se ahorran como $800.000 al mes; es especulativo, tómalo con
#: pinzas». Solo para comparar con la caja que calcula el ERP.
AHORRO_DE_REFERENCIA = 800_000
_MESES = (
    "ene",
    "feb",
    "mar",
    "abr",
    "may",
    "jun",
    "jul",
    "ago",
    "sep",
    "oct",
    "nov",
    "dic",
)


def numero(x) -> float:
    if isinstance(x, bool):
        return 0.0
    try:
        return float(x)
    except (TypeError, ValueError):
        return 0.0


def nombre_mes(clave) -> str:
    k = int(numero(clave))
    return f"{_MESES[k % 100 - 1]} {k // 100}" if k and 1 <= k % 100 <= 12 else str(clave)


def _pesos(n: float) -> str:
    signo = "-" if n < 0 else ""
    return f"{signo}${abs(round(n)):,}".replace(",", ".")


@dataclass(frozen=True)
class Resumen:
    meses: int
    ingresos: float
    piezas: float
    ventas: float
    costo_de_lo_vendido: float
    publicidad: float
    gastos: float
    depreciacion: float
    utilidad: float
    clientas_nuevas: float
    cobros: float
    caja: float

    @property
    def ticket(self) -> float:
        return self.ingresos / self.ventas if self.ventas else 0.0

    @property
    def margen_bruto(self) -> float:
        return self.ingresos - self.costo_de_lo_vendido

    @property
    def margen_neto(self) -> float:
        return self.utilidad / self.ingresos if self.ingresos else 0.0

    @property
    def roas(self) -> float:
        return self.ingresos / self.publicidad if self.publicidad else 0.0

    @property
    def repetidas(self) -> float:
        return max(self.ventas - self.clientas_nuevas, 0.0)


def resumen(foto: dict) -> Resumen:
    m = [x for x in foto.get("mensual", []) if isinstance(x, dict)]

    def s(campo: str) -> float:
        return sum(numero(x.get(campo)) for x in m)

    return Resumen(
        meses=len(m),
        ingresos=s("Ingresos"),
        piezas=s("Unidades"),
        ventas=s("N_Ventas"),
        costo_de_lo_vendido=s("COGS_Std"),
        publicidad=s("Publicidad"),
        gastos=s("Gastos"),
        depreciacion=s("Deprec"),
        utilidad=s("Utilidad_Op"),
        clientas_nuevas=s("Clientes_Nuevos"),
        cobros=s("Cobros"),
        caja=numero(m[-1].get("Flujo_Acum")) if m else 0.0,
    )


@dataclass(frozen=True)
class Hallazgo:
    nivel: str  # "urgente" · "aviso" · "bien"
    titulo: str
    detalle: str


def _capa(foto: dict, concepto: str) -> list[float]:
    for c in foto.get("costeo", {}).get("capas", []):
        if str(c.get("concepto", "")).strip().lower() == concepto.lower():
            return [numero(v) for v in c.get("valores", [])]
    return []


def hallazgos(foto: dict) -> list[Hallazgo]:
    salida: list[Hallazgo] = []
    meses = [x for x in foto.get("mensual", []) if numero(x.get("Ingresos"))]
    if meses:
        mejor = max(meses, key=lambda x: numero(x.get("Utilidad_Op")))
        peor = min(meses, key=lambda x: numero(x.get("Utilidad_Op")))
        en_rojo = [x for x in meses if numero(x.get("Utilidad_Op")) < 0]
        if en_rojo:
            salida.append(
                Hallazgo(
                    "urgente",
                    f"{len(en_rojo)} mes(es) en pérdida: "
                    + ", ".join(nombre_mes(x.get("MesKey")) for x in en_rojo),
                    "Después de publicidad y gastos fijos no quedó nada. Fueron los "
                    "meses de pauta más cara y menos ventas: la publicidad sin video "
                    "nuevo no se paga sola.",
                )
            )
        salida.append(
            Hallazgo(
                "bien",
                f"El mejor mes: {nombre_mes(mejor.get('MesKey'))} "
                f"({_pesos(numero(mejor.get('Utilidad_Op')))} de utilidad)",
                f"{int(numero(mejor.get('Unidades')))} piezas y "
                f"{_pesos(numero(mejor.get('Ingresos')))} vendidos. El peor: "
                f"{nombre_mes(peor.get('MesKey'))} "
                f"({_pesos(numero(peor.get('Utilidad_Op')))}).",
            )
        )
        flojos = [
            x
            for x in meses
            if numero(x.get("Publicidad"))
            and numero(x.get("Ingresos")) / numero(x.get("Publicidad")) < ROAS_FLOJO
        ]
        if flojos:
            salida.append(
                Hallazgo(
                    "aviso",
                    f"La pauta rindió poco en {len(flojos)} mes(es) (menos de "
                    f"{ROAS_FLOJO:g} pesos vendidos por peso de publicidad)",
                    ", ".join(
                        f"{nombre_mes(x.get('MesKey'))}: "
                        f"{numero(x.get('Ingresos')) / numero(x.get('Publicidad')):.1f}x"
                        for x in flojos
                    ).replace(".", ",")
                    + ". Con los gastos fijos de hoy, por debajo de ~4x el mes "
                    "queda en cero o en rojo.",
                )
            )
    if meses:
        salario = next(
            (
                numero(x.get("valor"))
                for x in foto.get("costeo", {}).get("supuestos", [])
                if str(x.get("nombre", "")).startswith("Salario de Lía")
            ),
            0.0,
        )
        utilidad = sum(numero(x.get("Utilidad_Op")) for x in meses)
        if salario:
            sin = utilidad + salario * len(meses)
            salida.append(
                Hallazgo(
                    "bien" if utilidad >= 0 else "urgente",
                    f"La utilidad ya le paga a Lía: {_pesos(salario)} al mes",
                    f"Con su salario (como mínimo el mínimo 2026) el negocio dejó "
                    f"{_pesos(utilidad)} en {len(meses)} mes(es); sin pagárselo serían "
                    f"{_pesos(sin)} (~{_pesos(sin / len(meses))} al mes"
                    + (
                        f", cerca de los ~{_pesos(AHORRO_DE_REFERENCIA)} que Camilo dice "
                        "que ahorran: lo que se ahorra es, en buena parte, el sueldo de "
                        "Lía"
                        if abs(sin / len(meses) - AHORRO_DE_REFERENCIA)
                        < 0.5 * AHORRO_DE_REFERENCIA
                        else ""
                    )
                    + "). Lía es la dueña: si el negocio no le alcanza a pagarle, la "
                    "pérdida es real aunque haya caja.",
                )
            )
        flujo = sum(numero(x.get("Flujo")) for x in meses) / len(meses)
        salida.append(
            Hallazgo(
                "aviso"
                if abs(flujo - AHORRO_DE_REFERENCIA) > 0.5 * AHORRO_DE_REFERENCIA
                else "bien",
                (
                    f"A la caja le quedan ~{_pesos(flujo)} al mes (ERP)"
                    if flujo >= 0
                    else f"A la caja le faltan ~{_pesos(-flujo)} al mes (ERP)"
                ),
                f"Cobros − salidas, con el salario de Lía y los gastos ya pagados. "
                f"Camilo calcula que ahorran ~{_pesos(AHORRO_DE_REFERENCIA)} al mes "
                "(especulativo). Si se alejan mucho, falta anotar gastos o compras "
                "reales.",
            )
        )
    neto = _capa(foto, "Margen neto")
    piezas = foto.get("costeo", {}).get("piezas", [])
    if neto and piezas:
        textos = [
            f"{p.replace('Anillos ', '').replace(' huella', ' huellita(s)')}: "
            f"{v * 100:.0f} %"
            for p, v in zip(piezas, neto, strict=False)
        ]
        flojo = neto[0] < 0.15
        salida.append(
            Hallazgo(
                "aviso" if flojo else "bien",
                "Lo que deja cada pieza después de TODO (costo completo y publicidad)",
                "; ".join(textos)
                + (
                    ". El anillo de 1 huellita, que es el que más se vende, es el que "
                    "menos deja: subir la mezcla a 2 huellitas o el precio del de 1 "
                    "mueve más la ganancia que vender más del mismo."
                    if flojo
                    else "."
                ),
            )
        )
    canales = contar(foto.get("ventas", []), "canal")
    total = sum(n for _, n, _ in canales)
    sin = next((n for c, n, _ in canales if c == "Por clasificar"), 0)
    if total and sin / total > 0.5:
        salida.append(
            Hallazgo(
                "aviso",
                f"De {int(total)} ventas, {int(sin)} no dicen de dónde vino la clienta",
                "Desde agosto la sábana lo anota («PUBLICIDAD» o «vieja»). Seguir "
                "anotándolo dice cuánto vende de verdad la pauta y cuánto la "
                "recompra.",
            )
        )
    dias = [(d, n) for d, n, _ in por_dia(foto.get("ventas", []))]
    if sum(n for _, n in dias) >= 20:
        flojos = sorted(dias, key=lambda f: f[1])[:2]
        salida.append(
            Hallazgo(
                "bien",
                "Los días que menos se vende: "
                + " y ".join(str(f[0]).lower() for f in flojos),
                "Pauta y contenido rinden más de lunes a jueves; esos días se puede "
                "bajar el presupuesto diario sin perder ventas.",
            )
        )
    supuestos = [
        x
        for x in foto.get("costeo", {}).get("supuestos", [])
        if x.get("calidad") == "SUPUESTO"
    ]
    if supuestos:
        salida.append(
            Hallazgo(
                "aviso",
                f"{len(supuestos)} costos son supuestos míos, no datos",
                ", ".join(str(x.get("nombre")) for x in supuestos)
                + ". Con la cifra real (en la hoja Costeo del ERP, celdas amarillas) el "
                "costo de cada pieza y la utilidad se corrigen solos.",
            )
        )
    revisar = [
        v for v in foto.get("validaciones", []) if "REVISAR" in str(v.get("estado"))
    ]
    if revisar:
        salida.append(
            Hallazgo(
                "aviso",
                f"El ERP marca {len(revisar)} cosa(s) para revisar",
                "; ".join(
                    f"{v.get('chequeo')} ({v.get('resultado')})" for v in revisar[:5]
                )
                + (" …" if len(revisar) > 5 else ""),
            )
        )
    orden = {"urgente": 0, "aviso": 1, "bien": 2}
    return sorted(salida, key=lambda h: orden.get(h.nivel, 3))


def _clave(m: dict) -> int:
    return int(numero(m.get("MesKey")))


def anios(foto: dict) -> list[int]:
    """Los años con meses en la foto (para elegir el período)."""
    return sorted({_clave(m) // 100 for m in foto.get("mensual", []) if _clave(m)})


def _en(clave: int, anio: int | None, mes: int | None) -> bool:
    return (
        bool(clave)
        and (anio is None or clave // 100 == anio)
        and (mes is None or clave % 100 == mes)
    )


def del_periodo(foto: dict, anio: int | None, mes: int | None = None) -> dict:
    """La foto con solo el período (sin año = todo; sin mes = el año): los meses,
    las ventas una por una y el costo de cada mes."""
    costeo = foto.get("costeo", {})
    return {
        **foto,
        "mensual": [m for m in foto.get("mensual", []) if _en(_clave(m), anio, mes)],
        "ventas": [
            v
            for v in foto.get("ventas", [])
            if isinstance(v, dict) and _en(int(numero(v.get("mes"))), anio, mes)
        ],
        "costeo": {
            **costeo,
            "por_mes": [
                x
                for x in costeo.get("por_mes", [])
                if _en(int(numero(x.get("mes"))), anio, mes)
            ],
        },
    }


# --- las ventas del período, contadas (de la lista sin datos de la clienta) ---

#: (cómo se muestra, lo que se busca en los colores, en minúsculas).
COLORES = (
    ("Blanco", "blanco"),
    ("Rosa / rosa claro", "rosa"),
    ("Fucsia", "fucsia"),
    ("Lila", "lila"),
    ("Morado", "morad"),
    ("Celeste / turquesa", "celeste"),
    ("Azul", "azul"),
    ("Verde oliva", "oliva"),
    ("Verde (todos)", "verde"),
    ("Amarillo", "amarillo"),
    ("Champagne", "champa"),
    ("Naranja", "naranja"),
    ("Rojo", "rojo"),
    ("Negro", "negro"),
)
DIAS = ("Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo")


def contar(ventas: list[dict], campo: str) -> list[tuple[str, int, float]]:
    """[(valor, ventas, pesos)] de mayor a menor."""
    cuenta: dict[str, list[float]] = {}
    for v in ventas:
        clave = str(v.get(campo) or "Sin dato").strip() or "Sin dato"
        x = cuenta.setdefault(clave, [0, 0.0])
        x[0] += 1
        x[1] += numero(v.get("total"))
    return sorted(
        ((k, int(n), s) for k, (n, s) in cuenta.items()), key=lambda t: (-t[1], t[0])
    )


def por_talla(ventas: list[dict]) -> list[tuple[str, int]]:
    """Anillos por talla, de la más chica a la más grande; lo raro al final."""
    cuenta: dict[str, int] = {}
    for v in ventas:
        if str(v.get("producto", "")).startswith("Anillos"):
            t = str(v.get("talla") or "").replace("TALLA ", "").strip() or "Sin talla"
            cuenta[t] = cuenta.get(t, 0) + 1

    def orden(t: str) -> tuple[int, float, str]:
        try:
            return (0, float(t), "")
        except ValueError:
            return (1, 0.0, t)

    return sorted(cuenta.items(), key=lambda kv: orden(kv[0]))


def por_color(ventas: list[dict]) -> list[tuple[str, int]]:
    """Ventas que llevan cada color (en el corazón o los dedos)."""
    salida = []
    for nombre, busca in COLORES:
        n = sum(1 for v in ventas if busca in str(v.get("colores", "")).lower())
        if n:
            salida.append((nombre, n))
    return sorted(salida, key=lambda t: -t[1])


def _dia(fecha: str) -> int | None:
    """0 = lunes, de «19/09/2026» o «2026-09-19»."""
    from datetime import date

    t = str(fecha).strip()
    try:
        if len(t) >= 10 and t[2] == "/":
            return date(int(t[6:10]), int(t[3:5]), int(t[0:2])).weekday()
        return date.fromisoformat(t[:10]).weekday()
    except ValueError:
        return None


def por_dia(ventas: list[dict]) -> list[tuple[str, int, float]]:
    cuenta = [[0, 0.0] for _ in DIAS]
    for v in ventas:
        if (d := _dia(v.get("fecha", ""))) is not None:
            cuenta[d][0] += 1
            cuenta[d][1] += numero(v.get("total"))
    return [(DIAS[i], int(n), s) for i, (n, s) in enumerate(cuenta)]


def por_mes_y_producto(ventas: list[dict]) -> tuple[list[int], list[str], dict]:
    """(meses, productos, {(mes, producto): piezas}) para la gráfica apilada."""
    meses = sorted({int(numero(v.get("mes"))) for v in ventas if numero(v.get("mes"))})
    productos = [p for p, _, _ in contar(ventas, "producto")]
    tabla: dict[tuple[int, str], int] = {}
    for v in ventas:
        k = (int(numero(v.get("mes"))), str(v.get("producto")))
        tabla[k] = tabla.get(k, 0) + 1
    return meses, productos, tabla


def por_anio(foto: dict) -> dict[int, Resumen]:
    return {a: resumen(del_periodo(foto, a)) for a in anios(foto)}


def cierre(foto: dict, hasta: int) -> dict | None:
    """El balance al cierre de un mes (AAAAMM), con la foto COMPLETA: la caja de
    ese mes, la depreciación acumulada a esa fecha y las utilidades hasta ahí.
    Lo demás (saldos por cobrar, deudas) solo se conoce hoy."""
    meses = [m for m in foto.get("mensual", []) if _clave(m) and _clave(m) <= hasta]
    if not meses:
        return None
    ultimo = meses[-1]
    despues = sum(1 for m in foto.get("mensual", []) if _clave(m) > hasta)
    balance = {
        str(x.get("concepto")): numero(x.get("valor")) for x in foto.get("balance", [])
    }
    deprec_hoy = next((v for k, v in balance.items() if "Depreciación" in k), 0.0)
    equipos = next((v for k, v in balance.items() if k.startswith("Equipos")), 0.0)
    deprec = deprec_hoy + numero(ultimo.get("Deprec")) * despues
    return {
        "mes": _clave(ultimo),
        "caja": numero(ultimo.get("Flujo_Acum")),
        "equipos": equipos,
        "depreciacion": deprec,
        "utilidades": sum(numero(m.get("Utilidad_Op")) for m in meses),
    }
