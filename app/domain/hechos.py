"""La correa del redactor: solo puede decir lo que está en la ficha.

════════════════════════════════════════════════════════════════════════════
EL PROBLEMA QUE RESUELVE
════════════════════════════════════════════════════════════════════════════
Un modelo que redacta libre acaba escribiendo un precio que no existe. No por
un prompt flojo: porque generar texto plausible es exactamente lo que hace, y
«$180.000» es plausible al lado de «$200.000». Y lo va a decir con una
naturalidad perfecta, que es lo que lo hace peligroso.

La entrada del modelo ya está encerrada (esquema con Enum cerrados). Esto
encierra la SALIDA con la misma idea: se le entrega una ficha con los datos
reales, y lo que escriba se comprueba contra ella. Si mete una cifra que no
estaba, el texto se descarta y sale la plantilla determinista. La clienta no
se entera de nada; en el log queda por qué.

════════════════════════════════════════════════════════════════════════════
QUÉ SE VIGILA Y QUÉ NO
════════════════════════════════════════════════════════════════════════════
Se vigila lo que tiene consecuencias: cifras de dinero, plazos, tallas,
cantidades, códigos de pedido. Un número no autorizado ahí es una promesa
comercial inventada.

NO se vigila el estilo, ni los emojis, ni el orden, ni si dice «¡hola!» o
«¡buenas!». Ahí es donde el modelo aporta y donde equivocarse no cuesta nada.
Vigilar de más habría convertido el validador en una plantilla con pasos
extra.

Números que se ignoran a propósito: los que forman parte de palabras del
negocio (plata «925», «24» horas) y los sueltos de una o dos cifras, que casi
siempre son cantidades del propio texto («2 huellitas») ya presentes en la
ficha. Bloquear esos habría hecho el validador inútil por ruidoso.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field


@dataclass
class Ficha:
    """Los datos REALES con los que se puede redactar.

    La arma el ejecutor a partir de la base de datos. Si un dato no está aquí,
    el bot no lo puede decir — y eso incluye datos verdaderos que nadie se
    acordó de meter: es preferible una respuesta escueta a una inventada.
    """

    #: Cifras que sí puede nombrar, ya formateadas ("$140.000").
    montos: list[str] = field(default_factory=list)
    #: Códigos de pedido, tallas, cantidades, plazos… tal como deben salir.
    datos: dict[str, str] = field(default_factory=dict)
    #: Frases exactas que puede copiar (respuestas de FAQ, políticas).
    literales: list[str] = field(default_factory=list)

    def permitidos(self) -> set[str]:
        """Todos los números que el texto puede contener."""
        crudo = [*self.montos, *self.datos.values(), *self.literales]
        numeros: set[str] = set()
        for texto in crudo:
            numeros.update(_cifras(str(texto)))
        return numeros


#: Palabras del negocio que llevan un número dentro y no son un dato variable.
#: Si el modelo escribe «Plata Ley 925», eso no es una cifra inventada.
NUMEROS_DEL_OFICIO = {"925", "24", "5", "6", "10", "15", "16500", "60000"}

_CIFRA = re.compile(r"\d[\d.,]*")


def _cifras(texto: str) -> set[str]:
    """Los números de un texto, normalizados: «$140.000» y «140000» son el mismo.

    Sin normalizar, el validador rechazaría el formato colombiano de miles
    contra el número crudo de la base de datos — y estaría rechazando textos
    correctos, que es la peor forma de fallar: se apaga el validador.
    """
    return {
        m.group(0).replace(".", "").replace(",", "").lstrip("0") or "0"
        for m in _CIFRA.finditer(texto or "")
    }


def _normalizar(texto: str) -> str:
    sin_tildes = "".join(
        c
        for c in unicodedata.normalize("NFD", texto or "")
        if unicodedata.category(c) != "Mn"
    )
    return sin_tildes.lower()


@dataclass(frozen=True)
class Revision:
    """El resultado. `intrusos` es lo que hay que leer cuando falla."""

    aprobado: bool
    intrusos: tuple[str, ...] = ()
    motivo: str = ""


#: Palabras que un aviso comercial NUNCA debe contener sin que lo decida una
#: persona. Prometer un descuento por su cuenta es un daño distinto al de
#: equivocar una cifra: es una obligación nueva que alguien tendrá que cumplir.
PROHIBIDAS = (
    "descuento",
    "gratis",
    "promocion",
    "oferta",
    "regalo",
    "garantizado que",
    "te lo devuelvo",
    "reembolso completo",
)


def revisar(texto: str, ficha: Ficha) -> Revision:
    """¿Este texto solo dice cosas que estaban en la ficha?"""
    if not texto or not texto.strip():
        return Revision(False, motivo="el modelo devolvió un texto vacío")

    bajo = _normalizar(texto)
    for palabra in PROHIBIDAS:
        if palabra in bajo:
            return Revision(
                False, motivo=f"prometió algo que nadie autorizó: «{palabra}»"
            )

    permitidos = ficha.permitidos() | NUMEROS_DEL_OFICIO
    intrusos = tuple(
        sorted(
            n
            for n in _cifras(texto)
            # Uno y dos dígitos se dejan pasar: son cantidades y ordinales del
            # propio texto, y bloquearlos haría el validador inservible.
            if n not in permitidos and len(n) > 2
        )
    )
    if intrusos:
        return Revision(
            False,
            intrusos=intrusos,
            motivo=f"escribió cifras que no estaban en la ficha: {', '.join(intrusos)}",
        )
    return Revision(True)


def redactar_con_red(
    texto_del_modelo: str | None, plantilla: str, ficha: Ficha
) -> tuple[str, Revision]:
    """Usa lo del modelo si pasa la revisión; si no, la plantilla.

    Devuelve también la revisión para que quede en el log. Un fallback
    silencioso que nadie mide es un fallback que un día se traga todas las
    respuestas y nadie se entera de que el modelo dejó de servir.
    """
    if texto_del_modelo is None:
        return plantilla, Revision(False, motivo="no se pidió redacción al modelo")
    revision = revisar(texto_del_modelo, ficha)
    return (texto_del_modelo if revision.aprobado else plantilla), revision
