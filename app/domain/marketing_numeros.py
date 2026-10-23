"""Los números del marketing: KPIs, embudo, recomendaciones e indicadores (01/10).

Camilo, 01/10: «quiero que quede TODO: las recomendaciones, los datos, las
mejoras; todo lo que una compañía profesional podría usar, así no tengas
información». Este módulo saca, de las tablas que lleva el Claude de
marketing (`datos/*.csv` de su carpeta), lo que un departamento de marketing
mira cada mes:

- KPIS: inversión, ventas, ROAS, costo por venta, ganancia, margen, tasa de
  cierre, costo por conversación, CPM, alcance, frecuencia… del último mes
  con datos, contra el mes anterior.
- EL EMBUDO: impresiones → personas alcanzadas → conversaciones → ventas.
- RECOMENDACIONES calculadas con los umbrales de las reglas de marketing.
- EL CATÁLOGO de indicadores de una empresa profesional: los que ya tienen
  dato muestran su valor; los que no, QUÉ falta y CÓMO conseguirlo.

Todo lo de aquí está CALCULADO (el panel lo dice así); el contenido escrito
por el Claude de marketing se muestra aparte, tal cual. Sin red, sin archivos:
recibe el texto de los CSV y devuelve números.
"""

from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass
from datetime import date

#: Umbrales de las «Reglas de cada lunes» de marketing (rev. 3, 30/09): una
#: venta hasta $30.000 es la meta, hasta $45.000 va bien, más de $60.000 es
#: para bajar; nunca más de $1.900.000 al mes de pauta. Una venta que cuesta
#: más de lo que deja un anillo pierde plata.
META_COSTO_POR_VENTA = 30_000
AVISO_COSTO_POR_VENTA = 45_000
MALO_COSTO_POR_VENTA = 60_000
TOPE_MENSUAL_DE_PAUTA = 1_900_000
#: Lo que deja una pieza antes de pauta si no hay foto del ERP ni tablero: ticket
#: $214.620 − costo completo $137.406 (ERP, 02/10: plata de sep, salario de
#: Lía, equipo real de $17,4 M y las 5 piedras de cada huellita). Con foto del
#: ERP el panel lo calcula al día (`_ganancia_por_anillo`).
GANANCIA_POR_ANILLO = 77_214
#: Frecuencia: veces que la misma persona vio el anuncio en el mes. Por encima
#: de esto el público se cansa del video (fatiga creativa).
FRECUENCIA_DE_FATIGA = 2.5
#: Un video propio de más de estos días ya se gastó (dura de 3 a 6 meses).
DIAS_DE_VIDA_DE_UN_VIDEO = 90


def leer_csv(texto: str) -> list[dict[str, str]]:
    """Las filas de un CSV con cabecera. Vacío si no hay nada que leer."""
    if not (texto or "").strip():
        return []
    filas = csv.DictReader(io.StringIO(texto.lstrip("\ufeff")))
    return [{(k or "").strip(): (v or "").strip() for k, v in f.items()} for f in filas]


def numero(valor) -> float | None:
    """«1469» -> 1469.0; «4,70» -> 4.7; vacío o texto -> None."""
    texto = str(valor or "").strip().replace(" ", "")
    if not texto:
        return None
    if "," in texto and "." not in texto:
        texto = texto.replace(",", ".")
    try:
        return float(texto)
    except ValueError:
        return None


def _es_mes(texto: str) -> bool:
    return len(texto) == 7 and texto[4] == "-" and texto[:4].isdigit()


def _por_mes(filas: list[dict[str, str]]) -> dict[str, dict[str, str]]:
    return {f["mes"]: f for f in filas if _es_mes(f.get("mes", ""))}


# ---------------------------------------------------------------------------
# KPIs del mes
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Kpi:
    clave: str
    nombre: str
    valor: float | None
    unidad: str  # "cop" · "pct" · "x" · "numero" · "decimal"
    anterior: float | None = None
    #: Qué dirección es buena: "sube", "baja" o "" (ni una ni otra).
    mejor: str = ""
    que_es: str = ""

    @property
    def cambio_pct(self) -> float | None:
        if self.valor is None or not self.anterior:
            return None
        return (self.valor - self.anterior) / abs(self.anterior) * 100

    @property
    def tono(self) -> str:
        """ "bueno", "malo" o "neutro" según cómo se movió contra el mes anterior."""
        cambio = self.cambio_pct
        if cambio is None or not self.mejor or abs(cambio) < 1:
            return "neutro"
        subio = cambio > 0
        return "bueno" if subio == (self.mejor == "sube") else "malo"


@dataclass(frozen=True)
class Mes:
    """Los números de un mes, de las dos tablas (ventas y Meta)."""

    mes: str
    anillos: float | None = None
    ventas: float | None = None
    pauta: float | None = None
    ganancia: float | None = None
    conversaciones: float | None = None
    impresiones: float | None = None
    alcance: float | None = None
    frecuencia: float | None = None
    cpm: float | None = None
    costo_conversacion: float | None = None

    def kpis(self, antes: Mes | None = None) -> list[Kpi]:
        a = antes or Mes(mes="")

        def div(x, y):
            return x / y if x is not None and y else None

        def k(clave, nombre, este, ese, unidad, mejor, que_es):
            return Kpi(clave, nombre, este, unidad, ese, mejor, que_es)

        return [
            k(
                "ganancia",
                "Ganancia después de pauta",
                self.ganancia,
                a.ganancia,
                "cop",
                "sube",
                "Ventas − costo de los anillos − pauta",
            ),
            k(
                "ventas",
                "Ventas",
                self.ventas,
                a.ventas,
                "cop",
                "sube",
                "Lo que pagaron las clientas",
            ),
            k(
                "anillos",
                "Anillos vendidos",
                self.anillos,
                a.anillos,
                "numero",
                "sube",
                "Ventas cerradas en el mes",
            ),
            k(
                "pauta",
                "Inversión en pauta",
                self.pauta,
                a.pauta,
                "cop",
                "",
                "Lo gastado en Meta Ads",
            ),
            k(
                "roas",
                "ROAS",
                div(self.ventas, self.pauta),
                div(a.ventas, a.pauta),
                "x",
                "sube",
                "Pesos vendidos por cada peso de pauta",
            ),
            k(
                "cpa",
                "Costo por venta",
                div(self.pauta, self.anillos),
                div(a.pauta, a.anillos),
                "cop",
                "baja",
                f"Pauta ÷ anillos. Meta: {_cop(META_COSTO_POR_VENTA)} o menos",
            ),
            k(
                "margen",
                "Margen después de pauta",
                _pct(div(self.ganancia, self.ventas)),
                _pct(div(a.ganancia, a.ventas)),
                "pct",
                "sube",
                "Ganancia ÷ ventas",
            ),
            k(
                "ticket",
                "Ticket promedio",
                div(self.ventas, self.anillos),
                div(a.ventas, a.anillos),
                "cop",
                "sube",
                "Ventas ÷ anillos",
            ),
            k(
                "cierre",
                "Tasa de cierre",
                _pct(div(self.anillos, self.conversaciones)),
                _pct(div(a.anillos, a.conversaciones)),
                "pct",
                "sube",
                "De cada 100 que escriben, cuántas compran",
            ),
            k(
                "peso_pauta",
                "Pauta sobre ventas",
                _pct(div(self.pauta, self.ventas)),
                _pct(div(a.pauta, a.ventas)),
                "pct",
                "baja",
                "Qué parte de cada venta se va en publicidad",
            ),
            k(
                "conversaciones",
                "Conversaciones iniciadas",
                self.conversaciones,
                a.conversaciones,
                "numero",
                "sube",
                "Personas que escribieron desde el anuncio",
            ),
            k(
                "costo_conv",
                "Costo por conversación",
                self.costo_conversacion,
                a.costo_conversacion,
                "cop",
                "baja",
                "Pauta ÷ conversaciones",
            ),
            k(
                "alcance",
                "Personas alcanzadas",
                self.alcance,
                a.alcance,
                "numero",
                "sube",
                "Personas distintas que vieron un anuncio",
            ),
            k(
                "impresiones",
                "Impresiones",
                self.impresiones,
                a.impresiones,
                "numero",
                "sube",
                "Veces que se mostró un anuncio",
            ),
            k(
                "cpm",
                "CPM",
                self.cpm,
                a.cpm,
                "cop",
                "baja",
                "Lo que cuesta mostrar el anuncio 1.000 veces",
            ),
            k(
                "frecuencia",
                "Frecuencia",
                self.frecuencia,
                a.frecuencia,
                "decimal",
                "",
                f"Veces que la misma persona lo vio; más de {FRECUENCIA_DE_FATIGA} cansa",
            ),
        ]


def _pct(x: float | None) -> float | None:
    return None if x is None else x * 100


def _cop(n: float) -> str:
    return "$" + f"{round(n):,}".replace(",", ".")


def meses(ventas_csv: str, meta_csv: str) -> list[Mes]:
    """Todos los meses con algún dato, en orden. Une ventas y Meta por mes."""
    ventas = _por_mes(leer_csv(ventas_csv))
    meta = _por_mes(leer_csv(meta_csv))
    todos = []
    for clave in sorted(set(ventas) | set(meta)):
        v, m = ventas.get(clave, {}), meta.get(clave, {})
        anillos = numero(v.get("anillos_vendidos"))
        ingresos = numero(v.get("ingresos_cop"))
        pauta = numero(v.get("gasto_pauta_cop")) or numero(m.get("gasto_cop"))
        todos.append(
            Mes(
                mes=clave,
                anillos=anillos,
                ventas=ingresos,
                pauta=pauta,
                ganancia=numero(v.get("ganancia_despues_de_pauta_cop")),
                conversaciones=numero(m.get("conversaciones_iniciadas"))
                or numero(v.get("conversaciones")),
                impresiones=numero(m.get("impresiones")),
                alcance=numero(m.get("alcance")),
                frecuencia=numero(m.get("frecuencia")),
                cpm=numero(m.get("cpm_cop")),
                costo_conversacion=numero(m.get("costo_por_conversacion_cop")),
            )
        )
    return todos


def ultimo_con_ventas(todos: list[Mes]) -> tuple[Mes | None, Mes | None]:
    """(el último mes con ventas, el anterior a él). Las ventas mandan."""
    con_ventas = [m for m in todos if m.anillos is not None]
    if not con_ventas:
        return (todos[-1] if todos else None), (todos[-2] if len(todos) > 1 else None)
    ultimo = con_ventas[-1]
    antes = con_ventas[-2] if len(con_ventas) > 1 else None
    return ultimo, antes


# ---------------------------------------------------------------------------
# El embudo
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Escalon:
    nombre: str
    cuantos: float
    paso: str  # cómo se pasa de este escalón al siguiente


def embudo(m: Mes) -> list[Escalon]:
    """Impresiones → alcance → conversaciones → ventas, lo que haya."""
    escalones = [
        ("Veces que se mostró el anuncio", m.impresiones, ""),
        ("Personas que lo vieron", m.alcance, ""),
        ("Personas que escribieron", m.conversaciones, ""),
        ("Anillos vendidos", m.anillos, ""),
    ]
    con_dato = [(n, c) for n, c, _ in escalones if c]
    salida = []
    for i, (nombre, cuantos) in enumerate(con_dato):
        paso = ""
        if i + 1 < len(con_dato):
            siguiente = con_dato[i + 1][1]
            paso = f"{siguiente / cuantos * 100:.2f} % pasa al siguiente".replace(
                ".", ","
            )
        salida.append(Escalon(nombre, cuantos, paso))
    return salida


# ---------------------------------------------------------------------------
# Recomendaciones calculadas
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Recomendacion:
    nivel: str  # "urgente" · "aviso" · "bien"
    titulo: str
    detalle: str


def recomendaciones(
    todos: list[Mes],
    campanas_csv: str,
    creativos_csv: str,
    hoy: date,
    ganancia_por_anillo: float = GANANCIA_POR_ANILLO,
) -> list[Recomendacion]:
    """Lo que un analista señalaría al mirar las tablas. Lo urgente, primero."""
    salida: list[Recomendacion] = []
    ultimo, antes = ultimo_con_ventas(todos)

    if ultimo is not None:
        nombre = _nombre_mes(ultimo.mes)
        cpa = ultimo.pauta / ultimo.anillos if ultimo.pauta and ultimo.anillos else None
        if cpa is not None:
            if cpa > ganancia_por_anillo:
                salida.append(
                    Recomendacion(
                        "urgente",
                        f"En {nombre} cada venta costó {_cop(cpa)}: se perdió plata",
                        f"Es más de lo que deja un anillo (~{_cop(ganancia_por_anillo)})."
                        " Bajar el presupuesto y revisar los anuncios antes de seguir.",
                    )
                )
            elif cpa > MALO_COSTO_POR_VENTA:
                salida.append(
                    Recomendacion(
                        "aviso",
                        f"Venta cara en {nombre}: {_cop(cpa)}",
                        f"Más de {_cop(MALO_COSTO_POR_VENTA)}. La regla: si se repite "
                        "dos "
                        "semanas, bajar el presupuesto 30 %.",
                    )
                )
            elif cpa > AVISO_COSTO_POR_VENTA:
                salida.append(
                    Recomendacion(
                        "aviso",
                        f"Venta a {_cop(cpa)} en {nombre}",
                        f"Entre {_cop(AVISO_COSTO_POR_VENTA)} y "
                        f"{_cop(MALO_COSTO_POR_VENTA)}: "
                        "no tocar, pero avisar a Camilo.",
                    )
                )
            elif cpa <= META_COSTO_POR_VENTA:
                salida.append(
                    Recomendacion(
                        "bien",
                        f"Venta a {_cop(cpa)} en {nombre}: en la meta",
                        "Si se sostiene dos semanas, la regla permite subir el "
                        "presupuesto 20 %.",
                    )
                )
            else:
                salida.append(
                    Recomendacion(
                        "bien",
                        f"Venta a {_cop(cpa)} en {nombre}: va bien",
                        f"Entre {_cop(META_COSTO_POR_VENTA)} y "
                        f"{_cop(AVISO_COSTO_POR_VENTA)}. "
                        "No tocar nada.",
                    )
                )
        if ultimo.pauta and ultimo.pauta > TOPE_MENSUAL_DE_PAUTA:
            salida.append(
                Recomendacion(
                    "aviso",
                    f"{nombre}: {_cop(ultimo.pauta)} de pauta, sobre el tope",
                    f"El tope es {_cop(TOPE_MENSUAL_DE_PAUTA)} al mes: por encima no se "
                    "venden más anillos (may–ago 2026).",
                )
            )
        if (
            antes is not None
            and ultimo.anillos
            and antes.anillos
            and ultimo.conversaciones
            and antes.conversaciones
        ):
            cierre, cierre_antes = (
                ultimo.anillos / ultimo.conversaciones,
                antes.anillos / antes.conversaciones,
            )
            if cierre < cierre_antes * 0.8:
                salida.append(
                    Recomendacion(
                        "aviso",
                        "Compran menos de las que escriben",
                        f"La tasa de cierre bajó de {cierre_antes * 100:.1f} % a "
                        f"{cierre * 100:.1f} %. Revisar qué se les responde y el "
                        "precio en "
                        "el anuncio.".replace(".", ",", 2),
                    )
                )
        if ultimo.frecuencia and ultimo.frecuencia > FRECUENCIA_DE_FATIGA:
            salida.append(
                Recomendacion(
                    "aviso",
                    f"El público se está cansando: frecuencia {ultimo.frecuencia:.1f}",
                    "La misma persona ve el anuncio demasiadas veces: toca video nuevo o "
                    "público más amplio.",
                )
            )
        if antes is not None and ultimo.costo_conversacion and antes.costo_conversacion:
            subio = ultimo.costo_conversacion / antes.costo_conversacion - 1
            if subio > 0.2:
                salida.append(
                    Recomendacion(
                        "aviso",
                        f"La conversación subió {subio * 100:.0f} % en {nombre}",
                        f"De {_cop(antes.costo_conversacion)} a "
                        f"{_cop(ultimo.costo_conversacion)}. Suele ser el video gastado.",
                    )
                )

    perfil = [
        f
        for f in leer_csv(campanas_csv)
        if "visitas al perfil" in f.get("objetivo", "").lower()
    ]
    if perfil and ultimo is not None:
        del_mes = sum(
            numero(f.get("gasto_cop")) or 0 for f in perfil if f.get("mes") == ultimo.mes
        )
        if del_mes:
            salida.append(
                Recomendacion(
                    "urgente",
                    f"{_cop(del_mes)} en «Visitas al perfil» en "
                    f"{_nombre_mes(ultimo.mes)}",
                    "Ese objetivo no trae ventas: cada conversación salió a más de "
                    "$5.000. "
                    "Apagar esas campañas; el objetivo es Ventas o Mensajes.",
                )
            )

    propios = [
        f
        for f in leer_csv(creativos_csv)
        if f.get("tipo", "").lower() in ("reel", "carrusel", "historia")
    ]
    fechas = [d for f in propios if (d := _fecha_de(f.get("publicado", "")))]
    if fechas:
        dias = (hoy - max(fechas)).days
        if dias > DIAS_DE_VIDA_DE_UN_VIDEO:
            salida.append(
                Recomendacion(
                    "aviso",
                    f"El video propio más nuevo tiene {dias} días",
                    "Un video dura de 3 a 6 meses en pauta; pasados "
                    f"{DIAS_DE_VIDA_DE_UN_VIDEO} "
                    "días toca grabar la siguiente producción.",
                )
            )

    if todos:
        ultimo_dato = _fecha_de(todos[-1].mes)
        if (
            ultimo_dato
            and (hoy.year - ultimo_dato.year) * 12 + hoy.month - ultimo_dato.month > 1
        ):
            salida.append(
                Recomendacion(
                    "aviso",
                    f"Los números llegan hasta {_nombre_mes(todos[-1].mes)}",
                    "Faltan los meses siguientes: pasarle a Camilo los datos de Ads "
                    "Manager y "
                    "de ventas para que el tablero esté al día.",
                )
            )

    orden = {"urgente": 0, "aviso": 1, "bien": 2}
    return sorted(salida, key=lambda r: orden.get(r.nivel, 3))


_MESES = (
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


def _nombre_mes(clave: str) -> str:
    if not _es_mes(clave):
        return clave
    return f"{_MESES[int(clave[5:]) - 1]} {clave[:4]}"


def _fecha_de(texto: str) -> date | None:
    texto = (texto or "").strip()
    try:
        if len(texto) == 7:
            return date.fromisoformat(texto + "-01")
        return date.fromisoformat(texto[:10])
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# El catálogo de indicadores de un departamento de marketing profesional
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Indicador:
    categoria: str
    nombre: str
    que_es: str
    #: La clave del KPI que lo llena, si ya se calcula ("" = aún no hay dato).
    kpi: str = ""
    #: Si no hay dato: qué falta y cómo conseguirlo.
    como_conseguirlo: str = ""


#: Lo que mira un departamento de marketing de verdad, por área. Los que
#: tienen `kpi` se llenan con los números del mes; los demás dicen cómo
#: conseguirlos. Es la lista de mejoras de medición, en orden de importancia
#: dentro de cada área.
CATALOGO: tuple[Indicador, ...] = (
    # Rentabilidad
    Indicador(
        "Rentabilidad", "Ganancia después de pauta", "Lo que queda de verdad", "ganancia"
    ),
    Indicador("Rentabilidad", "Margen después de pauta", "Ganancia ÷ ventas", "margen"),
    Indicador("Rentabilidad", "ROAS", "Pesos vendidos por peso de pauta", "roas"),
    Indicador(
        "Rentabilidad",
        "Pauta sobre ventas",
        "Qué parte de la venta es publicidad",
        "peso_pauta",
    ),
    Indicador("Rentabilidad", "Ticket promedio", "Ventas ÷ anillos", "ticket"),
    Indicador(
        "Rentabilidad",
        "Mezcla 1 · 2 · 3 huellitas",
        "Qué anillos se venden: el de 3 deja más",
        como_conseguirlo="VentaBot lo sabe de cada pedido: se muestra aquí cuando los "
        "pedidos del bot sean reales (instructivo §10).",
    ),
    Indicador(
        "Rentabilidad",
        "Costo real por anillo",
        "Plata, circones, taller y empaque, medido",
        como_conseguirlo="Lo calcula el ERP capa por capa (hoja Costeo; panel: "
        "Finanzas → Costos) con los gramos reales, la plata de cada mes, el salario "
        "de Lía, taller, familia, diligencias y colchón. Lo que falta para que "
        "sea exacto lo pide el cuestionario para Lía (vb erp --cuestionario).",
    ),
    # Adquisición (pauta)
    Indicador("Adquisición", "Costo por venta (CPA)", "Pauta ÷ anillos", "cpa"),
    Indicador(
        "Adquisición",
        "Costo por conversación",
        "Pauta ÷ personas que escriben",
        "costo_conv",
    ),
    Indicador("Adquisición", "CPM", "Costo de 1.000 impresiones", "cpm"),
    Indicador(
        "Adquisición",
        "Frecuencia",
        "Veces que la misma persona ve el anuncio",
        "frecuencia",
    ),
    Indicador(
        "Adquisición",
        "CTR (clics ÷ impresiones)",
        "Qué tanto invita a tocar el anuncio",
        como_conseguirlo="Ads Manager → columna «CTR (todos)»: anotarla por anuncio "
        "cada lunes.",
    ),
    Indicador(
        "Adquisición",
        "Costo por venta de cada anuncio",
        "Qué anuncio vende y cuál solo gasta",
        como_conseguirlo="Cuando entre la atribución de anuncios (ADR 0028) VentaBot "
        "sabrá de qué anuncio vino cada clienta: gasto del anuncio ÷ sus ventas.",
    ),
    Indicador(
        "Adquisición",
        "Ventas por ciudad",
        "Si el «Resto de Colombia» vende",
        como_conseguirlo="VentaBot guarda la ciudad de envío de cada pedido: se cuenta "
        "aquí cuando los pedidos sean reales. Mientras, Lía la anota cada lunes.",
    ),
    # Embudo
    Indicador("Embudo", "Impresiones", "Veces que se mostró un anuncio", "impresiones"),
    Indicador("Embudo", "Personas alcanzadas", "Personas distintas", "alcance"),
    Indicador(
        "Embudo", "Conversaciones iniciadas", "Personas que escribieron", "conversaciones"
    ),
    Indicador(
        "Embudo", "Tasa de cierre", "De cada 100 que escriben, cuántas compran", "cierre"
    ),
    Indicador(
        "Embudo",
        "Conversación → abono → pago completo",
        "En qué paso se quedan las que no compran",
        como_conseguirlo="VentaBot registra cada paso (cotiza, talla, colores, abono, "
        "pago): se mide cuando los pedidos sean reales.",
    ),
    Indicador(
        "Embudo",
        "Tiempo de primera respuesta",
        "Cuánto espera la clienta",
        como_conseguirlo="VentaBot lo mide (panel → métricas); hoy son charlas de "
        "prueba.",
    ),
    # Creativos
    Indicador(
        "Creativos",
        "Días del video más nuevo",
        "Un video dura de 3 a 6 meses",
        como_conseguirlo="Se calcula de `datos/creativos.csv` (pestaña Creativos).",
    ),
    Indicador(
        "Creativos",
        "Retención de 3 segundos (hook rate)",
        "De cada 100 que lo ven, cuántos se quedan 3 s",
        como_conseguirlo="Ads Manager → «Reproducciones de 3 segundos» ÷ impresiones, "
        "por anuncio. Meta: 18 % o más.",
    ),
    Indicador(
        "Creativos",
        "Reproducciones completas (ThruPlay)",
        "Cuántos lo ven hasta el final",
        como_conseguirlo="Ads Manager → columna «ThruPlays», por anuncio.",
    ),
    Indicador(
        "Creativos",
        "Costo de arranque de cada producción",
        "Lo que costó la conversación el primer mes",
        kpi="",
        como_conseguirlo="Está en `datos/creativos.csv` (costo_mes_1_cop): pestaña "
        "Creativos.",
    ),
    # Clientas
    Indicador(
        "Clientas",
        "Recompra",
        "Clientas que vuelven a comprar",
        como_conseguirlo="Cruzar los teléfonos de los pedidos (VentaBot) cuando sean "
        "reales: quién compró dos veces.",
    ),
    Indicador(
        "Clientas",
        "Valor de una clienta en el tiempo (LTV)",
        "Lo que compra una clienta en total",
        como_conseguirlo="Sale de la recompra y el ticket, con un año de pedidos reales.",
    ),
    Indicador(
        "Clientas",
        "Satisfacción (NPS) y reseñas",
        "Qué tan probable es que recomiende",
        como_conseguirlo="Una pregunta al entregar: «del 0 al 10, ¿nos recomendarías?». "
        "Puede mandarla el bot con el aviso de entrega.",
    ),
    Indicador(
        "Clientas",
        "Fotos y videos de clientas conseguidos",
        "Material para anuncios nuevos",
        como_conseguirlo="Contar los «sí» de la tarea de pedir foto en cada entrega.",
    ),
    # Orgánico
    Indicador(
        "Orgánico",
        "Seguidores y crecimiento",
        "36,8 mil (30 sep 2026)",
        como_conseguirlo="Instagram → Panel profesional: anotarlo el día 1 de cada mes.",
    ),
    Indicador(
        "Orgánico",
        "Alcance e interacción de los reels",
        "Vistas, guardados y compartidos",
        como_conseguirlo="Instagram → Estadísticas de cada reel; los que pasan de 20 mil "
        "vistas en 48 h son candidatos a anuncio.",
    ),
    Indicador(
        "Orgánico",
        "Publicaciones por semana",
        "Meta: 2 o 3 reels",
        como_conseguirlo="Calendario orgánico de la carpeta de marketing.",
    ),
    # Competencia y mercado
    Indicador(
        "Mercado",
        "Anuncios de la competencia",
        "Quién pauta anillos de huellita y a qué precio",
        como_conseguirlo="Biblioteca de anuncios de Meta, una vez al mes (ver "
        "Creativos → Competencia).",
    ),
    Indicador(
        "Mercado",
        "Estacionalidad",
        "Meses que venden más",
        como_conseguirlo="Con 12 meses de ventas reales se ve solo en «Mes a mes».",
    ),
)


# ---------------------------------------------------------------------------
# Lo que sabe el bot: sus pedidos (tabla de análisis), por ciudad y por mes
# ---------------------------------------------------------------------------

#: Las tres ciudades de la campaña principal; el resto es la prueba «Resto de
#: Colombia» del marketing (P1).
_PRINCIPALES = re.compile(r"bogot|medell|\bcali\b", re.IGNORECASE)


@dataclass(frozen=True)
class VentasDelBot:
    """Las ventas que pasaron por el bot (abono confirmado)."""

    de_prueba: bool
    pedidos: int  # se le pidió el abono
    ventas: int  # abono confirmado
    entregados: int
    ingresos: float
    por_ciudad: tuple[tuple[str, int, float], ...]
    principales: tuple[int, float]
    resto: tuple[int, float]
    mezcla: tuple[tuple[int, int], ...]  # (huellitas, anillos)
    por_mes: tuple[tuple[str, int, float], ...]
    dias_hasta_abono: float | None


def _ciudad(texto: str) -> str:
    limpio = " ".join((texto or "").split()).strip(" .,")
    return limpio.title() if limpio else "Sin ciudad"


def ventas_del_bot(filas: list[dict], reales_desde: str = "") -> VentasDelBot:
    """Resume la tabla de análisis de pedidos (`SqliteAnalitica.filas()`).

    Sin `reales_desde`, todo es de prueba (se dice así); con la fecha, solo
    cuentan los pedidos de ese día en adelante.
    """
    desde = reales_desde.strip()

    def vale(f: dict) -> bool:
        return not desde or str(f.get("creado") or "")[:10] >= desde

    pedidos = [f for f in filas if vale(f)]
    ventas = [f for f in pedidos if f.get("fecha_abono_confirmado")]
    ciudades: dict[str, list[float]] = {}
    meses: dict[str, list[float]] = {}
    mezcla: dict[int, int] = {}
    for f in ventas:
        precio = float(f.get("precio_total_cop") or 0)
        c = ciudades.setdefault(_ciudad(str(f.get("ciudad") or "")), [0, 0.0])
        c[0] += 1
        c[1] += precio
        mes = str(f.get("fecha_abono_confirmado"))[:7]
        m = meses.setdefault(mes, [0, 0.0])
        m[0] += 1
        m[1] += precio
        try:
            n = int(f.get("cantidad_huellitas") or 0)
        except (TypeError, ValueError):
            n = 0
        if n:
            mezcla[n] = mezcla.get(n, 0) + 1
    principales = [0, 0.0]
    resto = [0, 0.0]
    for nombre, (cuantos, plata) in ciudades.items():
        grupo = principales if _PRINCIPALES.search(nombre) else resto
        grupo[0] += int(cuantos)
        grupo[1] += plata
    dias = [
        float(f["dias_hasta_abono"])
        for f in ventas
        if f.get("dias_hasta_abono") not in (None, "")
    ]
    return VentasDelBot(
        de_prueba=not desde,
        pedidos=len(pedidos),
        ventas=len(ventas),
        entregados=sum(1 for f in ventas if f.get("fecha_entregado")),
        ingresos=sum(float(f.get("precio_total_cop") or 0) for f in ventas),
        por_ciudad=tuple(
            sorted(
                ((n, int(c), p) for n, (c, p) in ciudades.items()), key=lambda x: -x[1]
            )
        ),
        principales=(int(principales[0]), principales[1]),
        resto=(int(resto[0]), resto[1]),
        mezcla=tuple(sorted(mezcla.items())),
        por_mes=tuple((m, int(c), p) for m, (c, p) in sorted(meses.items())),
        dias_hasta_abono=sum(dias) / len(dias) if dias else None,
    )
