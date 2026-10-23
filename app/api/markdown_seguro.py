"""Markdown → HTML, sin librerías y sin dejar pasar HTML (01/10).

Para mostrar en el panel los documentos de la carpeta de marketing (el plan,
el estado, los ganchos, la bitácora…). No hay librería de Markdown en la
imagen del bot, y para documentos escritos por nosotros basta con lo que de
verdad se usa: títulos, párrafos, listas (con sangría y casillas), tablas,
citas, bloques de código, separadores, **negrita**, *cursiva*, `código` y
enlaces.

LA REGLA DE SEGURIDAD: todo el texto se ESCAPA antes de darle formato. Lo
que venga como HTML dentro del documento sale como texto, y un enlace solo
es enlace si va a http(s); abre fuera del panel.
"""

from __future__ import annotations

import html
import re

_ENLACE = re.compile(r"\[([^\]]+)\]\((https?://[^)\s]+)\)")
_URL_SUELTA = re.compile(r"(?<![\"'=>])(https?://[^\s<)]+)")
_NEGRITA = re.compile(r"\*\*(.+?)\*\*")
_CURSIVA = re.compile(r"(?<![\w*])[*_](?![\s*_])(.+?)(?<![\s*_])[*_](?![\w*])")
_CODIGO = re.compile(r"`([^`]+)`")
_LISTA = re.compile(r"^(\s*)([-*+]|\d+[.)])\s+(.*)$")
_TITULO = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
_SEPARADOR_TABLA = re.compile(r"^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$")
#: El número de la cuenta de anuncios no hace falta entero en el panel.
_CUENTA_DE_ANUNCIOS = re.compile(r"\bact_(\d+)(\d{4})\b")


def enmascarar(texto: str) -> str:
    """«act_957048212868257» -> «act_…8257»."""
    return _CUENTA_DE_ANUNCIOS.sub(lambda m: f"act_…{m.group(2)}", texto)


def en_linea(texto: str) -> str:
    """El formato de una línea. Recibe texto CRUDO y lo escapa primero."""
    # El código y los enlaces se apartan ANTES de la negrita y la cursiva: un
    # «_» de una dirección (o de «target=_blank») no puede volverse cursiva.
    apartados: list[str] = []

    def apartar(html_hecho: str) -> str:
        apartados.append(html_hecho)
        return f"\x00{len(apartados) - 1}\x00"

    def enlace(url: str, texto: str) -> str:
        return apartar(
            f"<a href='{url}' target=_blank rel='noopener noreferrer'>{texto}</a>"
        )

    t = html.escape(enmascarar(texto), quote=True)
    t = _CODIGO.sub(lambda m: apartar(f"<code>{m.group(1)}</code>"), t)
    t = _ENLACE.sub(lambda m: enlace(m.group(2), m.group(1)), t)
    t = _URL_SUELTA.sub(lambda m: enlace(m.group(1), m.group(1)), t)
    t = _NEGRITA.sub(r"<b>\1</b>", t)
    t = _CURSIVA.sub(r"<i>\1</i>", t)
    while "\x00" in t:  # un enlace puede llevar código adentro
        t = re.sub(r"\x00(\d+)\x00", lambda m: apartados[int(m.group(1))], t)
    return t


def _celdas(linea: str) -> list[str]:
    linea = linea.strip()
    if linea.startswith("|"):
        linea = linea[1:]
    if linea.endswith("|"):
        linea = linea[:-1]
    return [c.strip() for c in linea.split("|")]


def _item(texto: str) -> str:
    """Un renglón de lista; «[ ]» y «[x]» al principio son casillas (de ver)."""
    if m := re.match(r"^\[([ xX])\]\s+(.*)$", texto):
        marca = "☑" if m.group(1).lower() == "x" else "☐"
        return f"{marca} {en_linea(m.group(2))}"
    return en_linea(texto)


def a_html(texto: str) -> str:
    """El documento entero, como HTML seguro (sin `<html>` ni estilos)."""
    lineas = (texto or "").replace("\r\n", "\n").split("\n")
    salida: list[str] = []
    parrafo: list[str] = []
    listas: list[tuple[int, str]] = []  # (sangría, "ul"|"ol") abiertas
    i = 0

    def cerrar_parrafo() -> None:
        if parrafo:
            salida.append(f"<p>{en_linea(' '.join(parrafo))}</p>")
            parrafo.clear()

    def cerrar_listas(hasta: int = -1) -> None:
        while listas and listas[-1][0] > hasta:
            salida.append(f"</li></{listas.pop()[1]}>")

    while i < len(lineas):
        linea = lineas[i]
        crudo = linea.strip()

        if crudo.startswith("```"):
            cerrar_parrafo()
            cerrar_listas()
            bloque = []
            i += 1
            while i < len(lineas) and not lineas[i].strip().startswith("```"):
                bloque.append(lineas[i])
                i += 1
            salida.append(f"<pre>{html.escape(enmascarar(chr(10).join(bloque)))}</pre>")
            i += 1
            continue

        if not crudo:
            cerrar_parrafo()
            # Una línea en blanco dentro de una lista no la cierra si sigue.
            siguiente = next((x for x in lineas[i + 1 :] if x.strip()), "")
            if listas and not _LISTA.match(siguiente) and not siguiente.startswith(" "):
                cerrar_listas()
            i += 1
            continue

        if m := _TITULO.match(crudo):
            cerrar_parrafo()
            cerrar_listas()
            nivel = min(len(m.group(1)) + 1, 6)  # el h1 del panel es la página
            salida.append(f"<h{nivel}>{en_linea(m.group(2))}</h{nivel}>")
            i += 1
            continue

        if re.fullmatch(r"(-{3,}|\*{3,}|_{3,})", crudo):
            cerrar_parrafo()
            cerrar_listas()
            salida.append("<hr>")
            i += 1
            continue

        if (
            crudo.startswith("|")
            and i + 1 < len(lineas)
            and _SEPARADOR_TABLA.match(lineas[i + 1])
        ):
            cerrar_parrafo()
            cerrar_listas()
            cabeza = "".join(f"<th>{en_linea(c)}</th>" for c in _celdas(crudo))
            filas = []
            i += 2
            while i < len(lineas) and lineas[i].strip().startswith("|"):
                filas.append(
                    "<tr>"
                    + "".join(f"<td>{en_linea(c)}</td>" for c in _celdas(lineas[i]))
                    + "</tr>"
                )
                i += 1
            salida.append(
                f"<div class=desliza><table class=md><tr>{cabeza}</tr>"
                f"{''.join(filas)}</table></div>"
            )
            continue

        if crudo.startswith(">"):
            cerrar_parrafo()
            cerrar_listas()
            cita = []
            while i < len(lineas) and lineas[i].strip().startswith(">"):
                cita.append(lineas[i].strip()[1:].strip())
                i += 1
            salida.append(f"<blockquote>{en_linea(' '.join(cita))}</blockquote>")
            continue

        if m := _LISTA.match(linea):
            cerrar_parrafo()
            sangria = len(m.group(1).replace("\t", "    "))
            tipo = "ol" if m.group(2)[0].isdigit() else "ul"
            if listas and sangria < listas[-1][0]:
                cerrar_listas(sangria)
            if not listas or sangria > listas[-1][0]:
                salida.append(f"<{tipo}><li>{_item(m.group(3))}")
                listas.append((sangria, tipo))
            else:
                salida.append(f"</li><li>{_item(m.group(3))}")
            i += 1
            continue

        if listas and linea.startswith(" "):
            # Continuación de un renglón de lista (texto con sangría).
            salida.append(" " + en_linea(crudo))
            i += 1
            continue

        cerrar_listas()
        parrafo.append(crudo)
        i += 1

    cerrar_parrafo()
    cerrar_listas()
    return "\n".join(salida)
