"""El tablero de marketing: leer `PARA-EL-PANEL.md` (formato `lia-marketing-panel`).

QUÉ ES
======
El marketing de Lía (la pauta de Instagram) lo lleva aparte otro Claude, en la
carpeta `Documents\\GitHub\\marketing-lia`. Lía no usa Claude: ve el marketing en el
panel del bot (`/panel/marketing`). El ÚNICO puente entre los dos es ese
archivo, que trae un bloque JSON entre las marcas `<!-- DATOS:INICIO -->` y
`<!-- DATOS:FIN -->`, y que se sube con `SUBIR-MARKETING.cmd` (Camilo, 30/09).

POR QUÉ SE LEE ASÍ, Y NO SE COPIA A LA BASE
===========================================
El contenido es del Claude de marketing: el panel lo muestra TAL CUAL, sin
resumir ni reordenar (el orden de cada lista es la prioridad). Leer el archivo
en cada carga hace que una revisión nueva aparezca sola, sin tocar código ni
desplegar, y que el formato pueda crecer «poco a poco»: una clave nueva que el
panel aún no conoce se ignora en vez de romper la página.

Aquí solo se comprueba lo que, si falla, haría mostrar algo falso: que el
bloque exista, que sea JSON, y que traiga revisión y fecha. Lo de adentro se
muestra a la defensiva (`app/api/marketing.py`).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date

FORMATO = "lia-marketing-panel"
#: La versión del formato que sabe mostrar el panel. Si llega una más nueva se
#: muestra igual (lo conocido) con un aviso: lo nuevo aún no tiene dónde verse.
VERSION_QUE_ENTIENDE = 3

INICIO = "<!-- DATOS:INICIO -->"
FIN = "<!-- DATOS:FIN -->"

_CABECERA = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.DOTALL)
_CERCO = re.compile(r"\A\s*```(?:json)?\s*\n(.*)\n\s*```\s*\Z", re.DOTALL)
#: Las marcas cuentan solo SOLAS en su renglón: el propio archivo las nombra
#: en la prosa (§4, «saca el bloque entre `<!-- DATOS:INICIO -->` y…»), y
#: tomar esa mención por el bloque fue el primer error con el archivo real.
_BLOQUE = re.compile(
    rf"^[ \t]*{re.escape(INICIO)}[ \t]*\n(.*?)\n[ \t]*{re.escape(FIN)}[ \t]*$",
    re.DOTALL | re.MULTILINE,
)


@dataclass(frozen=True)
class Tablero:
    """Una revisión del marketing, lista para mostrar."""

    revision: int
    actualizado: date
    version_formato: int
    datos: dict

    @property
    def formato_mas_nuevo(self) -> bool:
        return self.version_formato > VERSION_QUE_ENTIENDE


def leer_tablero(texto: str) -> Tablero:
    """El tablero de un `PARA-EL-PANEL.md`, o ValueError con el motivo en claro.

    El motivo lo lee una persona (o el Claude de marketing al subirlo), así
    que dice qué arreglar, no qué excepción saltó.
    """
    texto = (texto or "").replace("\r\n", "\n")
    cabecera = _leer_cabecera(texto)
    if cabecera.get("formato", FORMATO) != FORMATO:
        raise ValueError(
            f"el archivo es de formato «{cabecera['formato']}», no «{FORMATO}»"
        )
    try:
        version = int(cabecera.get("version_formato", "1"))
    except ValueError as exc:
        raise ValueError("«version_formato» de la cabecera no es un número") from exc

    m = _BLOQUE.search(texto)
    if not m:
        raise ValueError(
            f"no están las marcas {INICIO} y {FIN}, cada una sola en su renglón, "
            "alrededor de los datos"
        )
    bloque = m.group(1)
    if m := _CERCO.match(bloque):
        bloque = m.group(1)
    try:
        datos = json.loads(bloque)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"el bloque de datos no es JSON válido (línea {exc.lineno} del bloque, "
            f"columna {exc.colno}: {exc.msg})"
        ) from exc
    if not isinstance(datos, dict):
        raise ValueError("el bloque de datos tiene que ser un objeto { … }")

    meta = datos.get("meta")
    if not isinstance(meta, dict):
        raise ValueError("falta «meta» con la revisión y la fecha")
    revision = meta.get("revision")
    if isinstance(revision, bool) or not isinstance(revision, int) or revision < 1:
        raise ValueError("«meta.revision» tiene que ser un número entero desde 1")
    try:
        actualizado = date.fromisoformat(str(meta.get("actualizado", "")))
    except ValueError as exc:
        raise ValueError("«meta.actualizado» tiene que ser una fecha AAAA-MM-DD") from exc
    return Tablero(revision, actualizado, version, datos)


def _leer_cabecera(texto: str) -> dict[str, str]:
    """La cabecera `--- clave: valor ---` del principio (puede no estar)."""
    m = _CABECERA.match(texto)
    if not m:
        return {}
    pares = (linea.split(":", 1) for linea in m.group(1).splitlines() if ":" in linea)
    return {clave.strip(): valor.strip() for clave, valor in pares}
