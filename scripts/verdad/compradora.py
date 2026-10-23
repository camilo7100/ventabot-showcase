"""La clienta que CONTESTA a lo que el bot le pregunta (prueba de verdad, 04/10).

Un libreto fijo se rompe en cuanto el modelo pregunta en otro orden («¿Talla
6?» y la clienta del libreto contesta «Una»). Una persona no: contesta lo que
le preguntan. La compradora sabe sus datos —talla (o que no la sabe y tiene la
regla), huellitas, colores, grabado, su nombre— y los dice CON SU FORMA DE
ESCRIBIR (dictado por voz, mayúsculas, a ráfagas…), según lo que el bot
pregunte en su último mensaje.

`que_pregunta` lee el último mensaje del bot y dice de qué es la pregunta.
`respuesta` saca la frase de ella para eso. Si el bot pregunta lo mismo tres
veces seguidas, o algo que ella no sabe contestar, o no llega al abono en
`TOPE_DE_TURNOS`, eso es una falla del bot (se quedó dando vueltas).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from scripts.verdad.revisiones import Salida, dice, no_dice, plano

#: Turnos que se le dan para llegar del primer mensaje al comprobante.
TOPE_DE_TURNOS = 16


@dataclass
class Compradora:
    """Sus datos, dichos como ella los dice. Cada clave puede tener varias
    respuestas: se usan en orden (con varios anillos, una por anillo) y la
    última se repite. `|` parte la respuesta en una ráfaga de mensajes."""

    talla: list[str] = field(default_factory=list)
    #: No sabe la talla: pide la guía y manda la foto de la regla.
    no_sabe_la_talla: str = ""
    #: La talla que confirma Lía si mandó la regla o una medida.
    talla_de_lia: float | None = None
    cantidad: list[str] = field(default_factory=list)
    colores: list[str] = field(default_factory=list)
    grabado: list[str] = field(default_factory=list)
    nombre: str = ""
    confirma: str = "Sí, así está perfecto"
    #: Cómo paga: el nombre de la foto (`fotos.FOTOS`) o un texto («ya transferí»).
    paga_con: str = "comprobante_60000"
    misma_talla: str = "no, distintas"
    #: Lo que tiene que cumplir el pedido al final.
    abono: str = "60.000"
    total: int = 200_000
    #: Lo que el resumen tiene que decir (talla, colores, grabado…).
    en_el_resumen: tuple[str, ...] = ()
    #: Al ver el primer resumen cambia algo («mejor el corazón morado»): el bot
    #: tiene que mandar el resumen nuevo en ese mismo turno.
    cambio_tras_resumen: str = ""
    usadas: dict[str, int] = field(default_factory=dict)

    def siguiente(self, clave: str) -> str:
        opciones = getattr(self, clave)
        i = self.usadas.get(clave, 0)
        self.usadas[clave] = i + 1
        return opciones[min(i, len(opciones) - 1)] if opciones else ""


def que_pregunta(s: Salida, pago_reportado: bool) -> str:
    """De qué es la última pregunta del bot (o qué toca hacer)."""
    t = s.todo
    medios = " ".join(s.medios)
    if "paula mantilla" in t and not pago_reportado:
        return "pagar"
    if pago_reportado and ("recibido" in t or "lia" in t):
        return "fin"
    if any(m in t for m in ("•anillo", "•cadena", "•pedido")) and "?" in t:
        return "confirmar"
    if "lo dejo a nombre de" in t:
        return "confirmar_nombre"
    # No acosar (09/10): si la talla la trae ella (joyería, «te la confirmo en
    # la tarde»), el bot ya no se la pide: espera. La compradora la da cuando
    # la tiene, como haría una clienta. Va ANTES de «ya casi» (13/10: «Ya casi
    # queda; apenas tengas la talla de la joyería, seguimos» es esperar SU talla,
    # no a Lía).
    # «Si quieres, ya lo puedes separar con el abono y la talla me la mandas…»
    # (13/10): la compradora que ya tiene su talla, la da.
    if "separar con el abono" in t:
        return "talla"
    if "?" not in t and re.search(
        r"(apenas|cuando)\s+(la\s+)?tengas\s+(la|tu)\s+talla|atenta\s+a\s+(la|tu)\s+talla"
        r"|pendiente\s+de\s+(la|tu)\s+talla",
        t,
    ):
        return "talla"
    if "ya casi" in t:
        return "esperar_a_lia"
    # Solo la ÚLTIMA pregunta: «Listo, sin nombres 🫶 ¿Qué color quieres?» es
    # de colores, aunque la frase de antes diga «nombres». Y si hay una
    # pregunta, se contesta ella aunque arriba diga «en unos minutos te
    # confirmo la talla» (eso es de Lía; la pregunta es para ella).
    con_pregunta = plano(next((x for x in reversed(s.textos) if "?" in x), ""))
    fin = con_pregunta.rfind("?")
    inicio = con_pregunta.rfind("¿", 0, fin)
    ultima = con_pregunta[max(inicio, 0) : fin + 1]
    if not ultima and "en unos minutos te" in t:
        return "esperar_a_lia"
    # «¿Qué color quieres para cada huellita?» es de colores, no de una por nombre.
    if (
        "huellita" in ultima
        and "color" not in ultima
        and any(
            x in ultima for x in ("por cada", "para cada", "una con los", "con ambos")
        )
    ):
        return "una_por_cada"
    if (
        "a nombre de quien" in ultima
        or "tu nombre" in ultima
        or "para el pedido" in ultima
    ):
        return "nombre"
    # «¿QUÉ fecha te gustaría grabar?» pide la fecha, no un «sí» (13/10: la
    # compradora contestaba «sí, con la fecha» dos veces y el pedido se trababa).
    if re.search(r"\b(?:que|cual)\s+fecha", ultima):
        return "grabado"
    if "fecha" in ultima and "grab" in ultima:
        return "fecha"
    if "misma talla" in ultima:
        return "misma_talla"
    if "grab" in ultima or "nombre" in ultima:
        return "grabado"
    if "color" in ultima or "tono" in ultima:
        return "colores"
    if "huellita" in ultima:
        return "cantidad"
    if "medir_talla" in medios:
        return "regla"
    if "talla" in ultima or "guia" in ultima:
        return "talla"
    if "para cuando" in ultima or ("fecha" in ultima and "listo" in ultima):
        return "para_cuando"
    if "en unos minutos" in t:
        return "esperar_a_lia"
    # Se fue a la joyería y el bot se lo recuerda: es la hora de dar la talla.
    if "talla" in t and ("joyeria" in t or "cuando tengas" in t):
        return "talla"
    # «Cuando tengas la talla que te midan en una joyería, ¿me la compartes?»:
    # la pregunta es corta y de qué habla está en su misma frase (05/10). Va
    # DESPUÉS de lo de Lía: «en unos minutos te confirmo la talla… ¿sí?» no le
    # pide la talla a ella.
    frase = con_pregunta[
        max(con_pregunta.rfind(p, 0, max(inicio, 0)) for p in ".!\n") + 1 : fin + 1
    ]
    if "talla" in frase:
        return "talla"
    return "otra"


def respuesta(c: Compradora, pregunta: str) -> tuple[str | None, str | None]:
    """(texto, foto) de ella para esa pregunta. (None, None) = no sabe qué decir."""
    if pregunta == "pagar":
        if c.paga_con in _FOTOS_DE_PAGO:
            return None, c.paga_con
        return c.paga_con, None
    if pregunta == "talla":
        if c.no_sabe_la_talla and not c.usadas.get("talla"):
            c.usadas["talla"] = 1
            return c.no_sabe_la_talla, None
        if c.no_sabe_la_talla:
            return None, "regla"
        return c.siguiente("talla"), None
    if pregunta == "regla":
        return None, "regla"
    if pregunta in ("cantidad", "colores", "grabado"):
        return c.siguiente(pregunta), None
    if pregunta == "nombre":
        return c.nombre, None
    if pregunta == "confirmar" and c.cambio_tras_resumen and not c.usadas.get("cambio"):
        c.usadas["cambio"] = 1
        return c.cambio_tras_resumen, None
    if pregunta in ("confirmar", "confirmar_nombre"):
        return c.confirma, None
    if pregunta == "fecha":
        con_fecha = any(ch.isdigit() for ch in " ".join(c.grabado))
        return ("sí, con la fecha" if con_fecha else "no, solo el nombre"), None
    if pregunta == "una_por_cada":
        return "una por cada uno", None
    if pregunta == "misma_talla":
        return c.misma_talla, None
    if pregunta == "para_cuando":
        return "no tengo afán 😊", None
    if pregunta == "otra":
        # «¿Te parece bien así?», «¿Los dejamos así?»: lo que diría ella.
        return "sí, así está bien 😊", None
    return None, None


_FOTOS_DE_PAGO = (
    "comprobante_60000",
    "comprobante_59700",
    "comprobante_65000",
    "comprobante_120000",
    "comprobante_pdf_60000",
)


def lo_que_se_espera(c: Compradora, pregunta: str, texto: str | None) -> tuple:
    """(etapa, revisiones) de la respuesta del bot a lo que ella contestó."""
    if pregunta == "confirmar" and texto == c.cambio_tras_resumen:
        # Cambió algo después del resumen: el resumen nuevo, sin cuentas.
        return "cambio", (dice("•"), no_dice("paula mantilla"))
    if pregunta in ("confirmar", "confirmar_nombre") and texto == c.confirma:
        if pregunta == "confirmar":
            return "cuentas", (dice("paula mantilla", c.abono),)
        return "nombre", ()
    if pregunta == "pagar" and texto:
        # Dijo que pagó sin mandar nada: se le pide el comprobante.
        return "comprobante", (dice("comprobante"),)
    if pregunta == "pagar":
        return "comprobante", (dice("recibido"),)
    return pregunta, ()
