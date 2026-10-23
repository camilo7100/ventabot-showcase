"""Pedidos HISTÓRICOS: se buscan cuando la clienta los señala, y solo entonces.

════════════════════════════════════════════════════════════════════════════
LA REGLA
════════════════════════════════════════════════════════════════════════════
Un pedido cerrado (entregado, cancelado, reembolsado) sigue en la base de datos
para siempre, pero NO entra en el contexto normal de la conversación (ver
`app/domain/operativo.py`). Así «ya te mandé la foto» se interpreta contra el
pedido de ESTE mes y no contra el de agosto.

Cuando la clienta SÍ habla del pasado —«¿qué pasó con mi pedido de agosto?»,
«el de la huella que compré antes», «¿qué talla había pedido la vez pasada?»—
se hace una recuperación SELECTIVA: se leen sus pedidos de la base de datos y
se filtran con datos estructurados (fecha, código, colores, nombres grabados,
estado). Nada se le pega al prompt de ningún modelo.

════════════════════════════════════════════════════════════════════════════
POR QUÉ NO HAY EMBEDDINGS AQUÍ
════════════════════════════════════════════════════════════════════════════
Una clienta de este negocio tiene uno, dos, cinco pedidos en su vida. Buscar
entre cinco filas por mes, color o nombre grabado es un `for`, y acierta
siempre que el dato exista. Un índice vectorial acertaría MENOS («agosto» no
se parece semánticamente a una fecha) y añadiría un servicio, una dependencia y
una forma nueva de equivocarse. Si algún día la búsqueda estructurada no basta,
el síntoma será medible: consultas históricas que acaban preguntando «¿cuál?»
teniendo la clienta un único pedido que encaja. Hoy no pasa.

Todo es Python puro y determinista.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from pydantic import BaseModel, Field

from app.domain.tallas import talla_texto

MESES: dict[str, int] = {
    "enero": 1,
    "febrero": 2,
    "marzo": 3,
    "abril": 4,
    "mayo": 5,
    "junio": 6,
    "julio": 7,
    "agosto": 8,
    "septiembre": 9,
    "setiembre": 9,
    "octubre": 10,
    "noviembre": 11,
    "diciembre": 12,
}
NOMBRE_MES = {v: k for k, v in MESES.items() if k != "setiembre"}

_UNIDAD_DIAS = {"dia": 1, "dias": 1, "semana": 7, "semanas": 7, "mes": 30, "meses": 30}
_CANTIDAD = {"un": 1, "una": 1, "dos": 2, "tres": 3, "cuatro": 4, "unos": 2, "unas": 2}


def normalizar(texto: str) -> str:
    sin_tildes = "".join(
        c
        for c in unicodedata.normalize("NFD", texto or "")
        if unicodedata.category(c) != "Mn"
    )
    return re.sub(r"[^a-z0-9\- ]+", " ", sin_tildes.lower()).strip()


#: Frases que hablan del PASADO de la clienta con la tienda. Se leen sobre el
#: texto normalizado (sin tildes, en minúscula).
SENALES_DEL_PASADO = re.compile(
    r"\b("
    r"pedidos?\s+(anterior|anteriores|pasados?|viejos?|antiguos?)|"
    r"(anterior|ultimo|primer)\s+pedido|"
    r"(mi|el|la|mis)\s+(pedido|anillo|compra)s?\s+(anterior|pasad[oa]|de\s+antes)|"
    r"la\s+(vez|ultima\s+vez|otra\s+vez)\s+(pasada|que)|la\s+vez\s+pasada|"
    r"(el|la)\s+(mes|semana|ano)\s+pasad[oa]|"
    r"hace\s+(\d+|un|una|dos|tres|cuatro|unos|unas)\s+(dias?|semanas?|mes|meses)|"
    r"(que|lo\s+que|el\s+que|la\s+que)\s+(te\s+)?(compre|pedi|encargue)|"
    r"(compre|pedi|encargue)\s+(antes|anteriormente|hace|la\s+vez|el\s+mes)|"
    r"hab[ia]+\s+(pedido|comprado|encargado)|"
    r"ya\s+me\s+hab[ia]+[ns]?\s+(despachado|enviado|mandado|entregado)|"
    r"cuantos\s+pedidos|historial|todos\s+mis\s+pedidos|mis\s+pedidos\s+anteriores|"
    r"resumen\s+de\s+(mis\s+)?pedidos|pedidos\s+(he|que\s+he)\s+hecho|"
    r"(el|la|mi)\s+otr[oa]\s+(pedido|anillo|compra)"
    r")\b"
)

#: «el pedido de agosto», «lo que compré en julio». Un mes SOLO cuenta si va
#: con algo que hable de un pedido: «que me llegue en diciembre» no es pasado.
MES_CON_PEDIDO = re.compile(
    r"\b(pedido|anillo|compra|compre|pedi|enviaron|mandaron|despacharon|llego|hice)"
    r"\b[^.?!]{0,25}\b(de|en|del)\s+(" + "|".join(MESES) + r")\b"
    r"|\b(de|en)\s+(" + "|".join(MESES) + r")\b[^.?!]{0,25}"
    r"\b(pedido|anillo|compre|pedi|compra)\b"
)

PIDE_RESUMEN = re.compile(
    r"\b(cuantos\s+pedidos|todos\s+mis\s+pedidos|historial|resumen|"
    r"pedidos\s+(he|que\s+he)\s+hecho|mis\s+pedidos\s+anteriores)\b"
)
DICE_OTRO = re.compile(r"\b(el|la|mi)\s+otr[oa]\s+(pedido|anillo|compra)\b")
DICE_ANTERIOR = re.compile(
    r"\b(anterior|pasad[oa]|antes|la\s+vez|ultimo\s+pedido|primer\s+pedido|hab[ia]+)\b"
)
CODIGO = re.compile(r"\bped-?\s?(\d{4})-?(\d{3,5})\b")

#: Palabras que no discriminan entre pedidos: están en todas las frases.
NO_DISCRIMINAN = frozenset(
    {
        "pedido",
        "pedidos",
        "anillo",
        "anillos",
        "compra",
        "compre",
        "pedi",
        "que",
        "paso",
        "con",
        "mi",
        "mis",
        "el",
        "la",
        "los",
        "las",
        "de",
        "del",
        "en",
        "un",
        "una",
        "cuando",
        "enviaron",
        "mandaron",
        "despacharon",
        "llego",
        "anterior",
        "anteriores",
        "pasado",
        "pasada",
        "vez",
        "antes",
        "hace",
        "mes",
        "meses",
        "semana",
        "semanas",
        "dias",
        "ano",
        "otro",
        "otra",
        "me",
        "puedes",
        "decir",
        "habia",
        "hice",
        "hecho",
        "cual",
        "como",
        "va",
        "estado",
        "ese",
        "esa",
        "ya",
        "tu",
        "te",
        "lo",
        "le",
        "por",
        "para",
        "y",
        "o",
        "si",
        "no",
        "cuantos",
        "todos",
        "resumen",
        "historial",
        "dame",
        "vamos",
        "mas",
        "talla",
        "fecha",
        "huella",
        "huellas",
        "huellita",
        "huellitas",
        "perro",
        "perrito",
        "gato",
        "gatito",
        "mascota",
        "plata",
        "comprado",
        "habias",
        "habian",
        "despachado",
        "enviado",
        "mandado",
        "entregado",
        "ultimo",
        "ultima",
        "primer",
        "tenia",
        "era",
    }
)


class FiltroHistorico(BaseModel):
    """Lo que la frase dice del pedido que busca. Todo opcional."""

    meses: list[int] = Field(default_factory=list, max_length=3)
    anio: int | None = None
    desde: datetime | None = None
    hasta: datetime | None = None
    codigo: str | None = None
    #: Palabras que pueden estar en el pedido: un color, un nombre grabado.
    palabras: list[str] = Field(default_factory=list, max_length=8)
    #: «el otro pedido»: cualquiera menos el que está en foco.
    otro: bool = False
    #: «mi pedido anterior», «la vez pasada»: prefiere los ya cerrados.
    anterior: bool = False
    #: «cuántos pedidos he hecho»: los quiere ver todos.
    resumen: bool = False

    def vacio(self) -> bool:
        return not (self.meses or self.anio or self.desde or self.codigo or self.palabras)

    def describir(self) -> str:
        """Para el log: qué criterio se usó. Sin datos personales."""
        partes = []
        if self.codigo:
            partes.append("codigo")
        if self.meses:
            partes.append("mes=" + ",".join(NOMBRE_MES[m] for m in self.meses))
        if self.anio:
            partes.append(f"anio={self.anio}")
        if self.desde:
            partes.append("rango_fechas")
        if self.palabras:
            partes.append(f"palabras={len(self.palabras)}")
        if self.otro:
            partes.append("otro")
        if self.anterior:
            partes.append("anterior")
        if self.resumen:
            partes.append("resumen")
        return " ".join(partes) or "sin_filtro"


def es_referencia_historica(texto: str) -> bool:
    t = normalizar(texto)
    return bool(
        SENALES_DEL_PASADO.search(t) or MES_CON_PEDIDO.search(t) or CODIGO.search(t)
    )


def leer_filtro(texto: str, hoy: datetime | None = None) -> FiltroHistorico:
    """Los filtros que se pueden sacar de la frase. Nunca falla."""
    hoy = hoy or datetime.now(UTC)
    t = normalizar(texto)
    f = FiltroHistorico()

    if m := CODIGO.search(t):
        f.codigo = f"PED-{m.group(1)}-{m.group(2)}"

    for nombre, numero in MESES.items():
        if re.search(rf"\b{nombre}\b", t) and numero not in f.meses:
            f.meses.append(numero)
    if re.search(r"\bel\s+mes\s+pasado\b", t):
        f.meses.append(12 if hoy.month == 1 else hoy.month - 1)
    if re.search(r"\bel\s+ano\s+pasado\b", t):
        f.anio = hoy.year - 1

    if m := re.search(
        r"\bhace\s+(\d+|un|una|dos|tres|cuatro|unos|unas)\s+(dias?|semanas?|mes|meses)\b",
        t,
    ):
        n = int(m.group(1)) if m.group(1).isdigit() else _CANTIDAD[m.group(1)]
        dias = n * _UNIDAD_DIAS[m.group(2)]
        f.desde = hoy - timedelta(days=dias * 1.6 + 3)
        f.hasta = hoy - timedelta(days=max(0.0, dias * 0.5 - 3))
    if re.search(r"\bla\s+semana\s+pasada\b", t):
        f.desde, f.hasta = hoy - timedelta(days=15), hoy - timedelta(days=4)

    f.otro = bool(DICE_OTRO.search(t))
    f.anterior = bool(DICE_ANTERIOR.search(t)) and not f.otro
    f.resumen = bool(PIDE_RESUMEN.search(t))

    meses_txt = set(MESES)
    for palabra in t.split():
        if (
            len(palabra) >= 4
            and palabra not in NO_DISCRIMINAN
            and palabra not in meses_txt
            and not palabra.isdigit()
            and not palabra.startswith("ped-")
            and palabra not in f.palabras
        ):
            f.palabras.append(palabra)
    f.palabras = f.palabras[:8]
    return f


def _aware(d: datetime) -> datetime:
    return d if d.tzinfo else d.replace(tzinfo=UTC)


def texto_de_busqueda(pedido) -> str:
    """Todo lo buscable de un pedido, normalizado. Colores, nombres, código."""
    from app.domain.personalizacion import NOMBRE_COLOR

    partes = [pedido.codigo]
    for item in pedido.items:
        partes.append(item.nombre)
        p = item.personalizacion
        for h in p.huellitas:
            partes += [NOMBRE_COLOR[h.corazon], NOMBRE_COLOR[h.dedos]]
        partes += list(p.grabados)
        if p.talla is not None:
            partes.append(f"talla {talla_texto(p.talla)}")
    if getattr(pedido, "envio", None) is not None and pedido.envio.ciudad:
        partes.append(pedido.envio.ciudad)
    return normalizar(" ".join(partes))


@dataclass
class ResultadoHistorico:
    """Lo que encontró la búsqueda. Nunca adivina entre varios."""

    candidatos: list = field(default_factory=list)
    #: Por qué se eligieron estos. Va al registro de decisiones.
    criterio: str = ""
    #: True cuando hay VARIOS y los datos no alcanzan para elegir uno.
    ambiguo: bool = False
    #: Palabras de la frase que no coincidieron con ningún pedido. Si hay y
    #: la búsqueda salió ambigua, es el caso en el que un modelo más capaz
    #: puede aportar (una descripción que no está en los campos).
    palabras_sin_coincidencia: list[str] = field(default_factory=list)

    @property
    def unico(self):
        return self.candidatos[0] if len(self.candidatos) == 1 else None


def buscar(
    pedidos: list,
    filtro: FiltroHistorico,
    *,
    activos: frozenset[str] | set[str] = frozenset(),
    en_foco: str | None = None,
    hoy: datetime | None = None,
) -> ResultadoHistorico:
    """Filtra los pedidos de UNA clienta con lo que dijo. Determinista.

    `pedidos` son TODOS los suyos (activos y cerrados), del más reciente al más
    viejo. `activos` y `en_foco` sirven para «el anterior» y «el otro», que se
    definen respecto de lo que está vivo ahora.
    """
    hoy = hoy or datetime.now(UTC)
    universo = sorted(pedidos, key=lambda o: _aware(o.created_at), reverse=True)
    criterio: list[str] = []

    if filtro.codigo:
        exacto = [o for o in universo if o.codigo.upper() == filtro.codigo.upper()]
        return ResultadoHistorico(exacto, "codigo")

    if filtro.resumen:
        return ResultadoHistorico(universo[:10], "resumen")

    if filtro.otro:
        universo = [o for o in universo if o.id != en_foco]
        criterio.append("sin_el_del_foco")

    if filtro.meses:

        def _del_mes(o) -> bool:
            creado = _aware(o.created_at)
            anio_esperado = filtro.anio or (
                hoy.year if max(filtro.meses) <= hoy.month else hoy.year - 1
            )
            return creado.month in filtro.meses and creado.year == anio_esperado

        universo = [o for o in universo if _del_mes(o)]
        criterio.append("mes")
    elif filtro.anio:
        universo = [o for o in universo if _aware(o.created_at).year == filtro.anio]
        criterio.append("anio")
    if filtro.desde and filtro.hasta:
        universo = [
            o for o in universo if filtro.desde <= _aware(o.created_at) <= filtro.hasta
        ]
        criterio.append("rango")

    sin_coincidencia: list[str] = []
    if filtro.palabras and universo:
        textos = {o.id: texto_de_busqueda(o) for o in universo}
        puntos = {
            o.id: sum(1 for p in filtro.palabras if p[:5] in textos[o.id])
            for o in universo
        }
        sin_coincidencia = [
            p for p in filtro.palabras if not any(p[:5] in t for t in textos.values())
        ]
        mejor = max(puntos.values())
        if mejor > 0:
            universo = [o for o in universo if puntos[o.id] == mejor]
            criterio.append("palabras")

    # «Mi pedido anterior»: los que ya NO están vivos van primero. Si con eso
    # queda uno solo, es ese; «anterior» en singular es el último cerrado.
    if filtro.anterior and len(universo) > 1:
        cerrados = [o for o in universo if o.id not in activos]
        if cerrados:
            universo = cerrados
            criterio.append("cerrados_primero")
        if len(universo) > 1 and filtro.vacio():
            universo = universo[:1]
            criterio.append("el_mas_reciente")

    return ResultadoHistorico(
        candidatos=universo,
        criterio=" ".join(criterio) or "todos",
        ambiguo=len(universo) > 1,
        palabras_sin_coincidencia=sin_coincidencia,
    )


def fecha_corta(d: datetime) -> str:
    """«14 de agosto de 2026». Sin locale: el servidor puede estar en inglés."""
    d = _aware(d)
    return f"{d.day} de {NOMBRE_MES[d.month]} de {d.year}"
