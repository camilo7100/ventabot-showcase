"""Las campañas piloto: fases, embudo y la tarjeta de calificación (03/10).

Camilo, 03/10: «súbeme al panel todo PILOTO VENTABOT, ordenado y escalable,
con desplegables para filtrar, gestionar y mirar lo que se desea». El plan lo
escribió el marketing (`PILOTO-VENTABOT.md`); aquí está lo que se CALCULA:

- **Las fases** salen de `datos/piloto_fases.csv` (una fila por fase y por
  campaña): qué fase va hoy, qué día de la fase y qué viene.
- **El día a día** junta dos fuentes que no se pisan: lo que solo sabe Meta
  (`datos/piloto_dias.csv`: gasto, impresiones, reproducciones de 3 s) y lo
  que pasa DENTRO del chat, que lo cuenta el bot solo
  (`tablero.embudo_por_dia`: conversaciones, enganchadas, listas para pagar,
  ventas). Así el marketing anota tres números al día y no seis.
- **La tarjeta de calificación** (§7 del plan): cinco notas de 0 a 2 —
  atracción, enganche, intención, conversión y rentabilidad— y la decisión
  (escalar, arreglar la nota más baja o replantear). Los umbrales de enganche
  e intención son PROVISIONALES en el plan (se recalibran con las primeras
  150 conversaciones): cambiarlos es cambiar `NOTAS`.

Escalable: todo va por `campana`, así que un segundo piloto es otra fila en
las tablas, no código nuevo. Funciones puras: nada de red ni de base.
"""

from __future__ import annotations

import csv
import io
from collections.abc import Callable
from dataclasses import dataclass, field, fields
from datetime import date, timedelta

#: Una venta del bot que llega tarde se le cuenta al día en que empezó la
#: charla; por eso cada fase se cierra unos días después de apagar la pauta.
DIAS_DE_CIERRE = 5


def _fecha(valor) -> date | None:
    try:
        return date.fromisoformat(str(valor or "").strip())
    except ValueError:
        return None


def _num(valor) -> float | None:
    texto = str(valor or "").strip().replace(",", ".")
    if not texto:
        return None
    try:
        return float(texto)
    except ValueError:
        return None


def _filas(texto: str) -> list[dict[str, str]]:
    if not (texto or "").strip():
        return []
    return [
        {(k or "").strip().lower(): (v or "").strip() for k, v in fila.items()}
        for fila in csv.DictReader(io.StringIO(texto))
    ]


# ---------------------------------------------------------------------------
# Las fases
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Fase:
    campana: str
    numero: int
    nombre: str
    desde: date
    hasta: date | None = None
    diario: float | None = None
    conjuntos: str = ""
    pasa_si: str = ""
    documento: str = ""

    @property
    def dias(self) -> int | None:
        return (self.hasta - self.desde).days + 1 if self.hasta else None

    def incluye(self, dia: date) -> bool:
        return self.desde <= dia and (self.hasta is None or dia <= self.hasta)


def leer_fases(texto: str) -> list[Fase]:
    """Las fases, en orden de campaña y fecha. Una fila sin fecha se salta."""
    fases = []
    for f in _filas(texto):
        desde = _fecha(f.get("desde"))
        numero = _num(f.get("fase"))
        if not f.get("campana") or desde is None or numero is None:
            continue
        fases.append(
            Fase(
                campana=f["campana"],
                numero=int(numero),
                nombre=f.get("nombre", ""),
                desde=desde,
                hasta=_fecha(f.get("hasta")),
                diario=_num(f.get("diario_cop")),
                conjuntos=f.get("conjuntos", ""),
                pasa_si=f.get("pasa_si", ""),
                documento=f.get("documento", ""),
            )
        )
    return sorted(fases, key=lambda x: (x.campana, x.desde))


def campanas(fases: list[Fase]) -> list[str]:
    """Las campañas, la que arranca más tarde primero (la más nueva arriba)."""
    inicio: dict[str, date] = {}
    for x in fases:
        inicio[x.campana] = min(inicio.get(x.campana, x.desde), x.desde)
    return sorted(inicio, key=lambda c: inicio[c], reverse=True)


@dataclass(frozen=True)
class Hoy:
    """Dónde va la campaña hoy."""

    fase: Fase | None  # la que corre hoy (None: antes, entre fases o después)
    dia: int | None  # día N de la fase de hoy
    proxima: Fase | None  # la siguiente que arranca
    dias_para_la_proxima: int | None
    terminada: bool  # ya pasó la última fase (con fecha de fin)


def hoy_en(fases: list[Fase], campana: str, hoy: date) -> Hoy:
    propias = [x for x in fases if x.campana == campana]
    actual = next((x for x in propias if x.incluye(hoy)), None)
    proxima = next((x for x in propias if x.desde > hoy), None)
    ultima = propias[-1] if propias else None
    return Hoy(
        fase=actual,
        dia=(hoy - actual.desde).days + 1 if actual else None,
        proxima=proxima,
        dias_para_la_proxima=(proxima.desde - hoy).days if proxima else None,
        terminada=bool(ultima and ultima.hasta and hoy > ultima.hasta and actual is None),
    )


def fase_del_dia(fases: list[Fase], campana: str, dia: date) -> Fase | None:
    """La fase a la que pertenece un día. Los días de cierre (tras apagar la
    pauta) siguen siendo de la fase anterior."""
    propias = [x for x in fases if x.campana == campana]
    for x in propias:
        if x.incluye(dia):
            return x
    anteriores = [x for x in propias if x.hasta and x.hasta < dia]
    ultima = anteriores[-1] if anteriores else None
    if ultima and ultima.hasta and dia <= ultima.hasta + timedelta(days=DIAS_DE_CIERRE):
        return ultima
    return None


# ---------------------------------------------------------------------------
# El día a día: Meta + el bot
# ---------------------------------------------------------------------------


@dataclass
class Totales:
    """Lo de un día, una semana, una fase o todo: siempre se suma igual."""

    gasto: float = 0
    impresiones: float = 0
    reproducciones_3s: float = 0
    conversaciones_meta: float = 0
    conversaciones: float = 0  # las cuenta el bot: personas que escribieron
    enganchadas: float = 0
    listas: float = 0
    ventas: float = 0
    ventas_cop: float = 0
    dias_con_gasto: int = 0
    notas: list[str] = field(default_factory=list)

    def __add__(self, otro: Totales) -> Totales:
        suma = Totales()
        for f in fields(Totales):
            a, b = getattr(self, f.name), getattr(otro, f.name)
            setattr(suma, f.name, a + b)
        return suma

    @property
    def conversaciones_para_costo(self) -> float:
        """Para el costo por conversación vale la cuenta de Meta (es lo que
        cobra); si no se anotó, la del bot."""
        return self.conversaciones_meta or self.conversaciones

    def _div(self, a: float, b: float, por: float = 1) -> float | None:
        return a / b * por if b else None

    @property
    def costo_por_conversacion(self) -> float | None:
        return self._div(self.gasto, self.conversaciones_para_costo)

    @property
    def enganche_pct(self) -> float | None:
        return self._div(self.enganchadas, self.conversaciones, 100)

    @property
    def intencion_pct(self) -> float | None:
        return self._div(self.listas, self.conversaciones, 100)

    @property
    def conversion_pct(self) -> float | None:
        return self._div(self.ventas, self.conversaciones, 100)

    @property
    def costo_por_venta(self) -> float | None:
        return self._div(self.gasto, self.ventas)

    @property
    def retencion_pct(self) -> float | None:
        return self._div(self.reproducciones_3s, self.impresiones, 100)


@dataclass
class Dia:
    fecha: date
    fase: Fase | None
    totales: Totales


def dias_de(
    fases: list[Fase],
    campana: str,
    texto_dias: str,
    embudo_bot: list[dict] | None,
    hoy: date,
) -> list[Dia]:
    """Los días de una campaña, del primero hasta hoy (o el cierre de la última
    fase). Lo de Meta sale de `piloto_dias.csv`; lo del chat, del bot."""
    propias = [x for x in fases if x.campana == campana]
    if not propias:
        return []
    inicio = propias[0].desde
    ultima = propias[-1]
    fin = hoy
    if ultima.hasta:
        fin = min(hoy, ultima.hasta + timedelta(days=DIAS_DE_CIERRE))
    por_fecha: dict[date, Totales] = {}
    for f in _filas(texto_dias):
        dia = _fecha(f.get("fecha"))
        if dia is None or f.get("campana", "") != campana:
            continue
        t = por_fecha.setdefault(dia, Totales())
        gasto = _num(f.get("gasto_cop")) or 0
        t.gasto += gasto
        t.dias_con_gasto += 1 if gasto else 0
        t.impresiones += _num(f.get("impresiones")) or 0
        t.reproducciones_3s += _num(f.get("reproducciones_3s")) or 0
        t.conversaciones_meta += _num(f.get("conversaciones_meta")) or 0
        if f.get("notas"):
            t.notas.append(f["notas"])
    for f in embudo_bot or []:
        dia = _fecha(f.get("fecha"))
        if dia is None:
            continue
        t = por_fecha.setdefault(dia, Totales())
        t.conversaciones += _num(f.get("conversaciones")) or 0
        t.enganchadas += _num(f.get("enganchadas")) or 0
        t.listas += _num(f.get("listas")) or 0
        t.ventas += _num(f.get("ventas")) or 0
        t.ventas_cop += _num(f.get("ventas_cop")) or 0
    return [
        Dia(d, fase_del_dia(fases, campana, d), por_fecha[d])
        for d in sorted(por_fecha)
        if inicio <= d <= fin
    ]


def semana_del_piloto(dia: date, inicio: date) -> tuple[int, date, date]:
    """(número, primer día, último día) de la semana del piloto de `dia`.

    Las semanas se cuentan desde el día en que arranca la campaña, no de lunes
    a domingo: el plan arranca el 6 de octubre de 2026, que es martes (03/10:
    el plan decía «lun 6 oct», el calendario de 2025). Así la semana 1 es la
    fase 1 entera y cada calificación semanal cae el mismo día de la semana.
    """
    n = (dia - inicio).days // 7
    desde = inicio + timedelta(days=7 * n)
    return n + 1, desde, desde + timedelta(days=6)


def agrupar(
    dias: list[Dia], por: str, inicio: date | None = None
) -> list[tuple[str, Totales]]:
    """(etiqueta, totales) por «dia», «semana» (del piloto: ver
    `semana_del_piloto`) o «fase». `inicio`: el primer día de la campaña."""
    grupos: dict[str, Totales] = {}
    primero = inicio or (dias[0].fecha if dias else date.min)
    for d in dias:
        if por == "semana":
            n, desde, hasta = semana_del_piloto(d.fecha, primero)
            clave = f"Semana {n} · {desde.isoformat()} a {hasta.isoformat()}"
        elif por == "fase":
            clave = (
                f"Fase {d.fase.numero} · {d.fase.nombre}" if d.fase else "Fuera de fase"
            )
        else:
            clave = d.fecha.isoformat()
        grupos[clave] = grupos.get(clave, Totales()) + d.totales
    return list(grupos.items())


def total(dias: list[Dia]) -> Totales:
    suma = Totales()
    for d in dias:
        suma = suma + d.totales
    return suma


# ---------------------------------------------------------------------------
# La tarjeta de calificación (§7 del plan)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Nota:
    numero: int
    nombre: str
    mide: str
    #: Saca el valor de los totales (None = no hay con qué medirla).
    valor: Callable[[Totales, float], float | None]
    #: Los puntos: 2 verde, 1 amarillo, 0 rojo.
    puntos: Callable[[float, float], int]
    formato: str  # «pesos» o «pct»
    umbrales: str  # cómo se lee, para la tarjeta
    provisional: bool = False


def _menor_es_mejor(verde: float, amarillo: float) -> Callable[[float, float], int]:
    return lambda v, _g: 2 if v <= verde else 1 if v <= amarillo else 0


def _mayor_es_mejor(verde: float, amarillo: float) -> Callable[[float, float], int]:
    return lambda v, _g: 2 if v >= verde else 1 if v >= amarillo else 0


def _rentabilidad(v: float, ganancia: float) -> int:
    # Rojo: cada venta cuesta más de lo que deja una pieza (se pierde plata).
    return 2 if v <= 45_000 else 1 if v <= ganancia else 0


def _costo_por_venta(t: Totales, _g: float) -> float | None:
    if not t.gasto:
        return None
    # Con gasto y sin ventas, la venta «costó» todo lo gastado y más: rojo.
    return t.costo_por_venta if t.ventas else float("inf")


NOTAS: tuple[Nota, ...] = (
    Nota(
        1,
        "Atracción",
        "Costo por conversación",
        lambda t, _g: t.costo_por_conversacion if t.gasto else None,
        _menor_es_mejor(1_400, 2_000),
        "pesos",
        "🟢 ≤ $1.400 · 🟡 hasta $2.000 · 🔴 más",
    ),
    Nota(
        2,
        "Enganche",
        "Enganchadas ÷ conversaciones",
        lambda t, _g: t.enganche_pct,
        _mayor_es_mejor(35, 20),
        "pct",
        "🟢 ≥ 35 % · 🟡 desde 20 % · 🔴 menos",
        provisional=True,
    ),
    Nota(
        3,
        "Intención",
        "Listas para pagar ÷ conversaciones",
        lambda t, _g: t.intencion_pct,
        _mayor_es_mejor(9, 5),
        "pct",
        "🟢 ≥ 9 % · 🟡 desde 5 % · 🔴 menos",
        provisional=True,
    ),
    Nota(
        4,
        "Conversión",
        "Ventas ÷ conversaciones",
        lambda t, _g: t.conversion_pct,
        _mayor_es_mejor(2.8, 1.8),
        "pct",
        "🟢 ≥ 2,8 % · 🟡 desde 1,8 % · 🔴 menos (no paga la pauta)",
    ),
    Nota(
        5,
        "Rentabilidad",
        "Gasto ÷ ventas",
        _costo_por_venta,
        _rentabilidad,
        "pesos",
        "🟢 ≤ $45.000 · 🟡 hasta lo que deja una pieza · 🔴 más (pierde plata)",
    ),
)


@dataclass(frozen=True)
class NotaPuesta:
    nota: Nota
    valor: float | None
    puntos: int | None  # None: no hay datos para ponerla


@dataclass(frozen=True)
class Calificacion:
    notas: tuple[NotaPuesta, ...]

    @property
    def completa(self) -> bool:
        return all(n.puntos is not None for n in self.notas)

    @property
    def puntos(self) -> int:
        return sum(n.puntos or 0 for n in self.notas)

    @property
    def posibles(self) -> int:
        return 2 * sum(1 for n in self.notas if n.puntos is not None)

    @property
    def mas_baja(self) -> NotaPuesta | None:
        puestas = [n for n in self.notas if n.puntos is not None and n.puntos < 2]
        return min(puestas, key=lambda n: (n.puntos, n.nota.numero)) if puestas else None

    @property
    def lectura(self) -> tuple[str, str, str]:
        """(tono, lectura, qué se hace), la tabla de decisión del plan."""
        if not self.completa:
            return (
                "neutro",
                "Todavía no se puede calificar",
                "Faltan datos para alguna nota (el gasto lo anota el marketing en "
                "datos/piloto_dias.csv; lo del chat lo cuenta el bot).",
            )
        if self.puntos >= 8:
            return "bueno", "La campaña funciona", "Pasar de fase / subir 20 %."
        if self.puntos >= 5:
            return (
                "neutro",
                "Funciona a medias",
                "Quedarse en la fase y arreglar la nota más baja (§9 del plan).",
            )
        return (
            "malo",
            "No funciona así",
            "Parar, entender cuál nota falla y replantear antes de gastar más.",
        )


def calificar(t: Totales, ganancia_por_pieza: float) -> Calificacion:
    puestas = []
    for n in NOTAS:
        valor = n.valor(t, ganancia_por_pieza)
        puntos = n.puntos(valor, ganancia_por_pieza) if valor is not None else None
        puestas.append(NotaPuesta(n, valor, puntos))
    return Calificacion(tuple(puestas))


# ---------------------------------------------------------------------------
# Los anuncios (calificación semanal por anuncio)
# ---------------------------------------------------------------------------

#: El plan: se apaga el de menor puntaje con 7 días y más de $30.000 gastados,
#: si queda al menos otro con nota igual o mejor.
DIAS_PARA_APAGAR = 7
GASTO_PARA_APAGAR = 30_000


@dataclass
class Anuncio:
    semana: date
    nombre: str
    totales: Totales
    dias_en_pauta: int | None
    notas: str = ""
    calificacion: Calificacion | None = None
    apagar: bool = False

    @property
    def puntos(self) -> int:
        return self.calificacion.puntos if self.calificacion else 0


def anuncios_de(texto: str, campana: str, ganancia_por_pieza: float) -> list[Anuncio]:
    """Los anuncios de la campaña, semana por semana. Por anuncio solo se ponen
    las notas que hay con qué medir: sin atribución por anuncio, la 1."""
    lista = []
    for f in _filas(texto):
        semana = _fecha(f.get("semana"))
        if semana is None or f.get("campana", "") != campana or not f.get("anuncio"):
            continue
        t = Totales(
            gasto=_num(f.get("gasto_cop")) or 0,
            conversaciones_meta=_num(f.get("conversaciones")) or 0,
            conversaciones=_num(f.get("conversaciones")) or 0,
            enganchadas=_num(f.get("enganchadas")) or 0,
            ventas=_num(f.get("ventas")) or 0,
        )
        retencion = _num(f.get("retencion_3s_pct"))
        if retencion is not None:
            t.impresiones, t.reproducciones_3s = 100, retencion
        cal = calificar(t, ganancia_por_pieza)
        sin_atribucion = not f.get("enganchadas") and not f.get("ventas")
        if sin_atribucion:
            cal = Calificacion((cal.notas[0],))
        dias = _num(f.get("dias_en_pauta"))
        lista.append(
            Anuncio(
                semana,
                f["anuncio"],
                t,
                int(dias) if dias is not None else None,
                f.get("notas", ""),
                cal,
            )
        )
    for semana in {a.semana for a in lista}:
        de_la_semana = [a for a in lista if a.semana == semana]
        candidatos = [
            a
            for a in de_la_semana
            if (a.dias_en_pauta or 0) >= DIAS_PARA_APAGAR
            and a.totales.gasto > GASTO_PARA_APAGAR
        ]
        if not candidatos:
            continue
        peor = min(candidatos, key=lambda a: a.puntos)
        if any(a is not peor and a.puntos >= peor.puntos for a in de_la_semana):
            peor.apagar = True
    return sorted(lista, key=lambda a: (a.semana, a.nombre), reverse=True)
