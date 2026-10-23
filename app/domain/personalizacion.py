"""Lo que hace único a cada anillo: talla, colores y grabados.

POR QUÉ ESTO VIVE EN EL DOMINIO
===============================
Un anillo de huellitas no es un producto de catálogo: es un producto de
catálogo MÁS un conjunto de decisiones de la clienta. Sin esas decisiones no
se puede fabricar. Y como no se puede fabricar, tampoco se puede pasar el
pedido a producción: el estado del pedido y la personalización están atados.

Modelarlo aquí, y no como texto libre en las notas del pedido, es lo que
permite que el sistema PREGUNTE lo que falta en vez de que alguien descubra
en el taller que nadie sabe de qué color van los dedos.

TODO ES ENUM CERRADO, A PROPÓSITO
=================================
Los colores son los del muestrario físico: si el modelo pudiera devolver
"lila pastel" o "morado clarito", habría que fabricar un circón que no
existe. Con un `Enum`, `format=<json_schema>` de Ollama hace IMPOSIBLE que
salga otra cosa: la restricción actúa sobre los logits, no sobre un reproche
en el prompt.

Lo único libre son los nombres grabados, y no puede ser de otra forma: el
perro se puede llamar como sea. Por eso son el único campo con validación de
longitud y de caracteres.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum

from pydantic import BaseModel, Field, field_validator

from app.domain.tallas import DIAMETRO_MM, talla_texto


class ColorCircon(str, Enum):
    """Los 14 colores del muestrario. Ni uno más.

    Salen de la foto de las bolsitas que Lía le manda a cada clienta. Si algún
    día compra otro color, se agrega aquí y el sistema entero lo aprende: el
    schema del LLM, los botones de WhatsApp y las validaciones.
    """

    BLANCO = "BLANCO"
    NEGRO = "NEGRO"
    LILA = "LILA"
    MORADO = "MORADO"
    CELESTE = "CELESTE"
    AZUL_REY = "AZUL_REY"
    ROSADO = "ROSADO"
    FUCSIA = "FUCSIA"
    ROJO = "ROJO"
    NARANJA = "NARANJA"
    DURAZNO = "DURAZNO"
    AMARILLO = "AMARILLO"
    VERDE_OLIVA = "VERDE_OLIVA"
    VERDE_ESMERALDA = "VERDE_ESMERALDA"


#: Cómo se le escribe a la clienta. El Enum es para el código; esto es para
#: el ser humano. Nunca se le muestra "AZUL_REY" a nadie.
#:
#: Son los nombres de la foto del muestrario que recibe la clienta (Camilo,
#: 30/09) y los valores DE FÁBRICA: Lía los cambia en el panel (Colores), la
#: tabla `colores_circon` manda y se aplican aquí al arrancar y al guardar
#: (`aplicar_paleta`). La CLAVE (AZUL_REY…) no cambia nunca: es la que guardan
#: los pedidos y la que escoge la IA.
NOMBRE_COLOR: dict[ColorCircon, str] = {
    ColorCircon.BLANCO: "blanco",
    ColorCircon.NEGRO: "negro",
    ColorCircon.LILA: "lila",
    ColorCircon.MORADO: "morado",
    ColorCircon.CELESTE: "celeste turquesa",
    ColorCircon.AZUL_REY: "azul zafiro",
    ColorCircon.ROSADO: "rosa",
    ColorCircon.FUCSIA: "fucsia",
    ColorCircon.ROJO: "rojo",
    ColorCircon.NARANJA: "naranja",
    ColorCircon.DURAZNO: "champagne",
    ColorCircon.AMARILLO: "amarillo",
    ColorCircon.VERDE_OLIVA: "verde oliva",
    ColorCircon.VERDE_ESMERALDA: "verde esmeralda",
}

#: Los nombres que van ESCRITOS en la foto del muestrario que recibe la clienta
#: (`data/imagenes/muestrario_circones.jpg`). Si Lía rebautiza una bolsita en
#: el panel, la foto no cambia sola: el panel lo avisa en ese color.
NOMBRE_EN_LA_FOTO: dict[ColorCircon, str] = dict(NOMBRE_COLOR)

#: Un punto de color para cada circón, para el resumen.
#:
#: El resumen se lee de un vistazo en WhatsApp. Con el emoji delante se ve la
#: joya; sin él se ve una factura. Es el formato que Camilo escribió a mano:
#: «Color: 🖤 Negro / Dedos: Negro-Blanco-Negro-Blanco» (20/09).
EMOJI_COLOR: dict[ColorCircon, str] = {
    ColorCircon.BLANCO: "🤍",
    ColorCircon.NEGRO: "🖤",
    ColorCircon.LILA: "🪻",
    ColorCircon.MORADO: "💜",
    ColorCircon.CELESTE: "🩵",
    ColorCircon.AZUL_REY: "💙",
    ColorCircon.ROSADO: "🩷",
    ColorCircon.FUCSIA: "💗",
    ColorCircon.ROJO: "❤️",
    ColorCircon.NARANJA: "🧡",
    ColorCircon.DURAZNO: "🍑",
    ColorCircon.AMARILLO: "💛",
    ColorCircon.VERDE_OLIVA: "🫒",
    ColorCircon.VERDE_ESMERALDA: "💚",
}

#: De qué color se ve cada circón, en hexadecimal.
#:
#: ════════════════════════════════════════════════════════════════════════
#: PARA QUÉ HACE FALTA UN NÚMERO Y NO BASTA EL NOMBRE
#: ════════════════════════════════════════════════════════════════════════
#: Para enseñarle a la clienta CÓMO LE VA A QUEDAR antes de fabricar. La
#: previsualización tiñe la foto real de la huellita con estos valores, y una
#: clienta que ve su anillo decide en un mensaje lo que si no le costaría
#: cinco.
#:
#: MEDIDOS en la foto del muestrario (30/09/2026, `scripts/medir_muestrario.py`):
#: balance de blancos con la cartulina, tono dominante de cada bolsita,
#: saturación sin el reflejo del plástico. Antes estaban puestos a ojo y se
#: notaba: el morado salía rojizo (la piedra es azul-violeta), el rosado era
#: rosa chicle (es rosa durazno) y el amarillo, limón intenso (es citrino
#: claro). Si Lía compra un color, se mide con ese script y se pone aquí: es el
#: único sitio, y cambia en todas las previsualizaciones a la vez.
#:
#: Desde el 30/09 el blanco y el negro también se pintan con su tinte: la
#: piedra dibujada da, en promedio, EXACTAMENTE este color. El blanco NO es el
#: de la foto del muestrario (#EDEFF2, la bolsita de plástico): es el color
#: promedio del diamante de la foto base, para que la piedra quede igual a esa
#: foto (ver `ACABADO_COLOR`).
HEX_COLOR: dict[ColorCircon, str] = {
    ColorCircon.BLANCO: "#BCBEBE",
    ColorCircon.NEGRO: "#12181B",
    ColorCircon.LILA: "#947FBE",
    ColorCircon.MORADO: "#5B47AB",
    ColorCircon.CELESTE: "#0A8AD3",
    ColorCircon.AZUL_REY: "#002475",
    ColorCircon.ROSADO: "#C2889A",
    ColorCircon.FUCSIA: "#AF0255",
    ColorCircon.ROJO: "#C60026",
    ColorCircon.NARANJA: "#CF2806",
    ColorCircon.DURAZNO: "#C07945",
    ColorCircon.AMARILLO: "#C4A63C",
    ColorCircon.VERDE_OLIVA: "#8F931A",
    ColorCircon.VERDE_ESMERALDA: "#007F51",
}


@dataclass(frozen=True)
class Acabado:
    """CÓMO se ve la piedra dibujada, además de su color (30/09).

    Son los números con los que Python dibuja cada piedra, puestos en el panel
    (Colores) para que Lía los mueva y vea el cambio al instante. Ninguno
    cambia el color promedio de la piedra: ese lo da siempre `HEX_COLOR`.
    """

    #: 0 = piedra plana de un solo color; 100 = facetas muy marcadas.
    facetas: int = 50
    #: Cuánto se van hacia blanco las facetas más claras: 0 = la piedra es del
    #: color parejo; 100 = las facetas de luz quedan blancas, como un hielo.
    destellos: int = 10
    #: El arcoíris del diamante de la foto (sus destellos de colores): 0 = la
    #: piedra es solo de su color; 100 = pasa todo, como el blanco de fábrica,
    #: que es la foto del diamante tal cual.
    fuego: int = 0

    def __post_init__(self) -> None:
        for campo, tope in TOPES_DEL_ACABADO.items():
            if not 0 <= getattr(self, campo) <= tope:
                raise ValueError(f"{campo} va de 0 a {tope}")


TOPES_DEL_ACABADO = {"facetas": 100, "destellos": 100, "fuego": 100}

#: El acabado de cada bolsita. De fábrica, el mismo para todas menos el
#: blanco, que es el circón transparente: con el color de la foto (`HEX_COLOR`),
#: facetas 31 (contraste 1), sin reflejos y con todo el fuego, la piedra
#: dibujada ES la foto del diamante (Camilo, 30/09: «estaba mejor antes»). El
#: panel manda.
ACABADO_COLOR: dict[ColorCircon, Acabado] = {
    c: Acabado(facetas=31, destellos=0, fuego=100)
    if c is ColorCircon.BLANCO
    else Acabado()
    for c in ColorCircon
}

#: Lo de fábrica, aparte: la paleta se cambia en su sitio y el panel ofrece
#: volver a esto («De fábrica»).
TINTE_DE_FABRICA: dict[ColorCircon, str] = dict(HEX_COLOR)
ACABADO_DE_FABRICA: dict[ColorCircon, Acabado] = dict(ACABADO_COLOR)

#: Cuántas veces cambió la paleta desde que arrancó el bot. Quien arma algo con
#: los nombres (el prompt de la asesora) lo rehace cuando este número cambia.
VERSION_PALETA = 0


def aplicar_paleta(
    colores: dict[ColorCircon, tuple[str, str]],
    acabados: dict[ColorCircon, Acabado] | None = None,
) -> None:
    """Pone los nombres, tintes y acabados que dice la tabla (`colores_circon`).

    Se cambian los diccionarios EN SU SITIO: todo el sistema los lee de aquí
    (resúmenes, pies de foto, previsualizador, el vigilante), así que un
    nombre nuevo aparece en todas partes a la vez, sin reiniciar.
    """
    global VERSION_PALETA
    for color, (nombre, tinte) in colores.items():
        NOMBRE_COLOR[color] = nombre
        HEX_COLOR[color] = tinte
    ACABADO_COLOR.update(acabados or {})
    VERSION_PALETA += 1


def nombres_del_muestrario() -> list[str]:
    """Los 14 nombres, en el orden del muestrario."""
    return [NOMBRE_COLOR[c] for c in ColorCircon]


#: Nombre de un color: letras (con tildes), espacios y guion. Lo lee la
#: clienta y la IA lo repite: nada de números ni emojis.
NOMBRE_DE_COLOR_VALIDO = re.compile(
    r"^[A-Za-zÁÉÍÓÚÜÑáéíóúüñ][A-Za-zÁÉÍÓÚÜÑáéíóúüñ \-]{1,29}$"
)


def validar_nombre_de_color(nombre: str, color: ColorCircon) -> str:
    """El nombre limpio (minúsculas), o ValueError con el motivo en claro."""
    limpio = re.sub(r"\s+", " ", (nombre or "").strip()).lower()
    if not NOMBRE_DE_COLOR_VALIDO.match(limpio):
        raise ValueError(
            "el nombre lleva solo letras y espacios, de 2 a 30 (ej.: azul zafiro)"
        )
    for otro, suyo in NOMBRE_COLOR.items():
        if otro is not color and suyo == limpio:
            raise ValueError(f"«{limpio}» ya es el nombre de otra bolsita")
    return limpio


def hsv_a_hex(tono: float, saturacion: float, brillo: float) -> str:
    """Tono 0–360°, saturación y brillo 0–100 % -> «#RRGGBB»."""
    import colorsys

    if not (0 <= tono <= 360 and 0 <= saturacion <= 100 and 0 <= brillo <= 100):
        raise ValueError("tono de 0 a 360; saturación y brillo de 0 a 100")
    r, g, b = colorsys.hsv_to_rgb((tono % 360) / 360, saturacion / 100, brillo / 100)
    return f"#{round(r * 255):02X}{round(g * 255):02X}{round(b * 255):02X}"


def hex_a_hsv(tinte: str) -> tuple[int, int, int]:
    """«#RRGGBB» -> (tono 0–360°, saturación %, brillo %), redondeados."""
    import colorsys

    t = tinte.lstrip("#")
    r, g, b = (int(t[i : i + 2], 16) / 255 for i in (0, 2, 4))
    h, s, v = colorsys.rgb_to_hsv(r, g, b)
    return round(h * 360) % 360, round(s * 100), round(v * 100)


#: Tope de nombres grabados en el aro. Es una restricción FÍSICA: no cabe más.
MAX_GRABADOS = 5
#: Lo que se quita de los bordes de cada nombre antes de unirlos (el ❤️ trae
#: un selector de variante invisible).
_CORAZONES_DE_BORDE = "♡❤️ "


def unir_grabados(renglones: list[str]) -> str:
    """«Lulú», «Pepito», «Nala» -> «Lulú ♡ Pepito ♡ Nala».

    Regla de Lía (02/10): SIEMPRE corazones ENTRE los nombres, nunca uno
    colgando al final. Con varios renglones se quitan los corazones de los
    bordes de cada uno y el ♡ va entre ellos: el modelo escribía «Lulú ♡»,
    «Pepito ♡», «Nala ♡» y quedaba «Lulú ♡ Pepito ♡ Nala ♡». Si un renglón
    empieza o termina en ∞ o &, ese es el separador.

    Con UN renglón va tal cual lo pidió («Luna ∞», «Lulú - Pepito»): así se
    respeta cuando ella NO quiere corazones o los quiere en otro sitio.
    """
    limpios = [" ".join(r.split()) for r in renglones if r and r.strip()]
    if len(limpios) <= 1:
        return limpios[0] if limpios else ""
    salida = ""
    for parte in (r.strip(_CORAZONES_DE_BORDE) for r in limpios):
        if not parte:
            continue
        if not salida:
            salida = parte
        elif salida.endswith(("∞", "&")) or parte.startswith(("∞", "&")):
            salida = f"{salida} {parte}"
        elif not re.search(r"[^\W\d_]", parte):
            # Una fecha o un número no es otro nombre: va pegado al anterior.
            # Prueba de verdad (04/10): «Morita 21/09/23» salió «Morita ♡ 21/09/23».
            salida = f"{salida} {parte}"
        else:
            salida = f"{salida} ♡ {parte}"
    return salida


#: Largo de cada renglón grabado. En las conversaciones reales Lía grabó
#: «Lilú ♡ Angélica 15/09/2017» (26): el tope de 15 rechazaba pedidos que sí se
#: fabricaron. 30 deja pasar lo real y frena lo que no cabe en el aro.
MAX_LARGO_NOMBRE = 30

#: Letras (con tildes y ñ), números, espacios y unos pocos signos. Se prohíben
#: emojis y símbolos raros porque el grabador no los puede hacer, y descubrirlo
#: en el taller es tarde.
#: Además de letras y números: los símbolos que Lía SÍ graba (♡ corazón, ∞
#: infinito, & entre nombres, / en fechas, paréntesis para «(carita de gato)» o
#: «(alitas)»). Los emojis siguen fuera: el grabador hace el dibujo, no el emoji.
NOMBRE_VALIDO = re.compile(r"^[A-Za-zÁÉÍÓÚÜÑáéíóúüñ0-9 .,:'&/()♡∞\-]+$")


# ---------------------------------------------------------------------------
# La cadena (03/10): una huellita y el nombre grabado, hasta 2 por lado
# ---------------------------------------------------------------------------

#: Qué pieza es. El anillo es lo de siempre; la cadena (03/10) lleva UNA
#: huellita (corazón + 4 deditos), no lleva talla, y el nombre grabado es
#: obligatorio: hasta 2 nombres por lado, en sus 2 lados (regla de Camilo).
ANILLO = "anillo"
CADENA = "cadena"
#: El anillo de corazón (17/10): un corazón de circón del color que elija, en
#: vez de huellitas. Es un ANILLO en todo lo demás: talla, grabado al interior
#: (hasta 5 nombres), plata 925, abono y tiempos. Su color va en la única
#: «huellita» del pedido (corazón = dedos = el color de la piedra).
CORAZON = "corazon"
#: Un solo corazón, siempre.
PIEDRAS_DEL_CORAZON = 1
MAX_NOMBRES_POR_LADO = 2
LADOS_DE_LA_CADENA = 2
#: La cadena lleva UNA huellita, siempre (Camilo, 03/10 y 09/10). No hay cadena de
#: 2 ni de 3: si la piden, se le dice y el sistema no lo anota (`asesora.aplicar`).
HUELLITAS_DE_LA_CADENA = 1
#: Lo que separa nombres dentro de un renglón («Luna ♡ Mara», «Luna y Mara»).
_SEPARA_NOMBRES = re.compile(r"\s*(?:♡|❤️?|&|∞|,|/|\+|\by\b)\s*", re.I)


def nombres_en(renglon: str) -> int:
    """Cuántos nombres hay en un renglón de grabado («Luna ♡ Mara» = 2).

    Una frase («Siempre en mí») cuenta como uno: es lo que va en un lado."""
    partes = _SEPARA_NOMBRES.split(renglon or "")
    return sum(1 for p in partes if re.search(r"[A-Za-zÁÉÍÓÚÜÑáéíóúüñ0-9]", p or ""))


def lados_de_la_cadena(renglones: list[str]) -> tuple[list[str], list[str]]:
    """El grabado de la cadena: un renglón por lado, hasta 2 nombres por lado.

    Devuelve (los lados, lo que hay que decirle al modelo). Si llegan los
    nombres sueltos (uno por renglón, como en el anillo) y caben, se acomodan
    de a dos por lado y se avisa para que se lo confirme. Si no caben, no se
    guarda nada y se pide preguntarle cómo los reparte.
    """
    limpios = [" ".join(r.split()) for r in renglones if r and r.strip()]
    por_renglon = [nombres_en(r) for r in limpios]
    if len(limpios) <= LADOS_DE_LA_CADENA and all(
        n <= MAX_NOMBRES_POR_LADO for n in por_renglon
    ):
        return limpios, []
    if all(n == 1 for n in por_renglon) and len(limpios) <= (
        LADOS_DE_LA_CADENA * MAX_NOMBRES_POR_LADO
    ):
        lados = [
            unir_grabados(limpios[i : i + MAX_NOMBRES_POR_LADO])
            for i in range(0, len(limpios), MAX_NOMBRES_POR_LADO)
        ]
        return lados, [
            "en la cadena van hasta 2 nombres por lado: quedó "
            + " · ".join(f"Lado {i}: {lado}" for i, lado in enumerate(lados, 1))
            + "; confírmaselo"
        ]
    return [], [
        "en la cadena caben hasta 2 nombres por lado (2 lados, 4 en total): no se "
        "guardó; pregúntale cuáles van en cada lado"
    ]


def texto_del_grabado(grabados: list[str], pieza: str = ANILLO, sin_grabado=False) -> str:
    """El grabado como se lee: en la cadena, lado por lado; en el anillo, con ♡."""
    if pieza == CADENA and grabados:
        return " · ".join(f"Lado {i}: {lado}" for i, lado in enumerate(grabados, 1))
    if grabados:
        return unir_grabados(grabados)
    return "sin grabado" if sin_grabado else ""


class Huellita(BaseModel):
    """Una patita. Un circón grande en forma de corazón + 4 chiquitos.

    Es la unidad de precio Y la unidad de color: en el anillo de 3 huellitas
    cada patita puede ir de un color distinto. Modelarlo como una lista de
    huellitas (y no como dos colores sueltos en el pedido) es lo que hace que
    eso sea representable sin inventar campos `color_2`, `color_3`.
    """

    corazon: ColorCircon
    dedos: ColorCircon
    #: Los CUATRO deditos, de izquierda a derecha, cuando no van todos
    #: iguales («negro-blanco-negro-blanco»). Vacío = los cuatro de `dedos`.
    #:
    #: Vive aquí y no solo en el borrador porque es lo que se fabrica: antes
    #: se guardaba `dedos_alternos[0]` y los otros tres colores se iban a una
    #: nota suelta, así que el dibujo enseñaba los cuatro iguales y al taller
    #: le llegaba un anillo unicolor (20/09).
    dedos_alternos: list[ColorCircon] = Field(default_factory=list)

    @field_validator("dedos_alternos")
    @classmethod
    def _son_cuatro(cls, v: list[ColorCircon]) -> list[ColorCircon]:
        if v and len(v) != 4:
            raise ValueError("los deditos alternos son los CUATRO o ninguno")
        return v

    @property
    def colores_de_los_dedos(self) -> list[ColorCircon]:
        """Los cuatro deditos, de izquierda a derecha. Siempre cuatro."""
        return list(self.dedos_alternos) or [self.dedos] * 4

    def describir(self) -> str:
        if self.dedos_alternos:
            dedos = "-".join(NOMBRE_COLOR[c] for c in self.dedos_alternos)
        else:
            dedos = NOMBRE_COLOR[self.dedos]
        return f"corazón {NOMBRE_COLOR[self.corazon]} / dedos {dedos}"


def nombres_de_los_colores(huellitas: list[Huellita]) -> str:
    """Los colores de cada huellita con su NOMBRE DEL MUESTRARIO, para el pie
    de la foto «así se te va a ver».

    La clienta escribe «verde menta» o «azul clarito» y la IA escoge el circón
    que más se parece. Sin el nombre al pie, ella nunca se entera de cuál es:
    con él aprende cómo se llama lo que pidió y lo ve dibujado (30/09).
    """

    def uno(c: ColorCircon) -> str:
        return f"{EMOJI_COLOR[c]} {NOMBRE_COLOR[c]}"

    lineas = []
    for i, h in enumerate(huellitas, 1):
        if h.dedos_alternos:
            dedos = " · ".join(uno(c) for c in h.dedos_alternos)
        else:
            dedos = uno(h.dedos)
        if not h.dedos_alternos and h.dedos is h.corazon:
            linea = f"Toda en {uno(h.corazon)}"
        else:
            linea = f"Corazón {uno(h.corazon)} · deditos {dedos}"
        lineas.append(f"Huellita {i}: {linea}" if len(huellitas) > 1 else linea)
    return "\n".join(lineas)


class Personalizacion(BaseModel):
    """Todo lo que la clienta decide. Puede estar incompleta a propósito.

    Los campos son opcionales porque se van llenando a lo largo de la
    conversación, y porque el flujo cobra el abono ANTES de tener la talla.
    Quien decide si ya se puede fabricar es `falta()`, no el tipo del campo.
    """

    talla: float | None = None
    talla_revisar: bool = False
    talla_motivo: str = ""
    huellitas: list[Huellita] = Field(default_factory=list)
    grabados: list[str] = Field(default_factory=list)
    #: Dijo que lo quiere sin grabado. Es una RESPUESTA, no una ausencia de
    #: respuesta: sin esta bandera, `falta()` pediría el grabado para siempre
    #: y la conversación entraría en bucle con quien no quiere ninguno.
    sin_grabado: bool = False
    #: «anillo» o «cadena» (03/10). La cadena no lleva talla y su grabado es
    #: obligatorio, un renglón por lado (`lados_de_la_cadena`).
    pieza: str = ANILLO

    @field_validator("talla")
    @classmethod
    def _talla_existe(cls, v: float | None) -> float | None:
        if v is not None and v not in DIAMETRO_MM:
            raise ValueError(
                f"la talla {v} no existe en el mandril "
                f"(válidas: {min(DIAMETRO_MM):g} a {max(DIAMETRO_MM):g})"
            )
        return v

    @field_validator("grabados")
    @classmethod
    def _grabados_fabricables(cls, v: list[str]) -> list[str]:
        if len(v) > MAX_GRABADOS:
            raise ValueError(f"no caben más de {MAX_GRABADOS} nombres en el aro")
        limpios = []
        for nombre in v:
            n = nombre.strip()
            if not n:
                continue
            if len(n) > MAX_LARGO_NOMBRE:
                raise ValueError(
                    f"«{n}» no cabe en el aro (máximo {MAX_LARGO_NOMBRE} letras)"
                )
            if not NOMBRE_VALIDO.match(n):
                raise ValueError(f"«{n}» tiene símbolos que el grabador no puede hacer")
            limpios.append(n)
        return limpios

    # -- lo que el flujo necesita preguntar --------------------------------

    def falta(self, huellitas_esperadas: int) -> list[str]:
        """Qué falta para poder fabricar. Vacío = listo para producción.

        Devuelve claves, no frases: la redacción vive en las plantillas. Así
        el mismo hueco se puede preguntar distinto por WhatsApp y por
        Instagram sin tocar el dominio.
        """
        pendientes = []
        # Menos parejas de las que tiene el anillo: falta escoger.
        # Más: alguien acumuló de más y el anillo saldría con patitas de
        # sobra. Las dos son «colores», porque las dos se arreglan hablando
        # de colores con la clienta.
        if len(self.huellitas) != huellitas_esperadas:
            pendientes.append("colores")
        if not self.grabados and (self.pieza == CADENA or not self.sin_grabado):
            pendientes.append("grabado")
        if self.talla is None and self.pieza != CADENA:
            pendientes.append("talla")
        return pendientes

    def completa(self, huellitas_esperadas: int) -> bool:
        return not self.falta(huellitas_esperadas)

    def describir(self) -> str:
        """El resumen que se le confirma a la clienta antes de fabricar."""
        lineas = (
            ["Cadena con huellita"]
            if self.pieza == CADENA
            else ["Anillo de corazón"]
            if self.pieza == CORAZON
            else []
        )
        if self.talla is not None:
            lineas.append(f"Talla: {talla_texto(self.talla)}")
        if self.pieza == CORAZON:
            if self.huellitas:
                lineas.append(
                    "Color del corazón: " + NOMBRE_COLOR[self.huellitas[0].corazon]
                )
            if grabado := texto_del_grabado(self.grabados, self.pieza, self.sin_grabado):
                lineas.append("Grabado: " + grabado)
            return "\n".join(lineas)
        for i, h in enumerate(self.huellitas, 1):
            prefijo = f"Huellita {i}: " if len(self.huellitas) > 1 else "Colores: "
            lineas.append(prefijo + h.describir())
        if grabado := texto_del_grabado(self.grabados, self.pieza, self.sin_grabado):
            lineas.append("Grabado: " + grabado)
        return "\n".join(lineas)
