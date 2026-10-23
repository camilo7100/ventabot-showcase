"""Los colores de circón en la base, para que Lía los cambie desde el panel (30/09).

Igual que los fletes: la primera vez la tabla se llena con los valores de
fábrica (`NOMBRE_COLOR`, `HEX_COLOR`, `ACABADO_COLOR` en
`app/domain/personalizacion.py`) y desde ahí manda la tabla, que vive en el
volumen del servidor y se edita en el panel (Colores) sin tocar código ni
desplegar.

Se cambian el NOMBRE (lo que lee la clienta y repite la IA), el TINTE (el color
de la piedra en la previsualización) y el ACABADO (facetas, reflejos y
fuego: cómo brilla esa piedra dibujada). La CLAVE (AZUL_REY…) no: es la que
guardan los pedidos. Agregar o quitar una bolsita sí es cambiar código
(`ColorCircon`).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

from app.domain.colores_texto import SINONIMOS, normalizar
from app.domain.personalizacion import (
    ACABADO_COLOR,
    HEX_COLOR,
    NOMBRE_COLOR,
    Acabado,
    ColorCircon,
    aplicar_paleta,
    validar_nombre_de_color,
)

_ESQUEMA = """
CREATE TABLE IF NOT EXISTS colores_circon (
    clave       TEXT PRIMARY KEY,
    nombre      TEXT NOT NULL,
    tinte       TEXT NOT NULL,
    actualizado TEXT NOT NULL
)
"""

#: Columnas del acabado (30/09). Se agregan a la tabla si aún no están (la de
#: producción ya existía sin ellas) y cada bolsita recibe SU valor de fábrica:
#: el blanco lleva otro. SQL fijo, sin armar textos con nombres de columnas.
_AGREGAR = {
    "facetas": (
        "ALTER TABLE colores_circon ADD COLUMN facetas INTEGER NOT NULL DEFAULT 50",
        "UPDATE colores_circon SET facetas = ? WHERE clave = ?",
    ),
    "destellos": (
        "ALTER TABLE colores_circon ADD COLUMN destellos INTEGER NOT NULL DEFAULT 10",
        "UPDATE colores_circon SET destellos = ? WHERE clave = ?",
    ),
    "fuego": (
        "ALTER TABLE colores_circon ADD COLUMN fuego INTEGER NOT NULL DEFAULT 0",
        "UPDATE colores_circon SET fuego = ? WHERE clave = ?",
    ),
}
#: Las «estrellitas» (brillos en estrella) se quitaron el mismo 30/09: Camilo
#: no las quiere. La columna se borra donde alcanzó a crearse.
_QUITAR = {"estrellas": "ALTER TABLE colores_circon DROP COLUMN estrellas"}


@dataclass(frozen=True)
class ColorDelMuestrario:
    color: ColorCircon
    nombre: str
    tinte: str
    acabado: Acabado = field(default_factory=Acabado)


class SqliteColores:
    """Tabla de colores editable. Al crearla y al guardar, aplica la paleta."""

    def __init__(self, db) -> None:
        self._db = db
        self._db.ejecutar(_ESQUEMA)
        columnas = {
            f["name"] for f in self._db.consultar("PRAGMA table_info(colores_circon)")
        }
        for campo, (agregar, fijar) in _AGREGAR.items():
            if campo not in columnas:
                self._db.ejecutar(agregar)
                for color in ColorCircon:
                    valor = getattr(ACABADO_COLOR[color], campo)
                    self._db.ejecutar(fijar, (valor, color.value))
        for campo, quitar in _QUITAR.items():
            if campo in columnas:
                self._db.ejecutar(quitar)
        hay = {f["clave"] for f in self._db.consultar("SELECT clave FROM colores_circon")}
        ahora = datetime.now(UTC).isoformat()
        for color in ColorCircon:
            if color.value not in hay:
                a = ACABADO_COLOR[color]
                self._db.ejecutar(
                    "INSERT INTO colores_circon (clave, nombre, tinte, actualizado, "
                    "facetas, destellos, fuego) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (
                        color.value,
                        NOMBRE_COLOR[color],
                        HEX_COLOR[color],
                        ahora,
                        a.facetas,
                        a.destellos,
                        a.fuego,
                    ),
                )
        self._aplicar()

    def todos(self) -> list[ColorDelMuestrario]:
        """Los 14, en el orden del muestrario."""
        filas = {
            f["clave"]: f
            for f in self._db.consultar(
                "SELECT clave, nombre, tinte, facetas, destellos, fuego "
                "FROM colores_circon"
            )
        }
        return [
            ColorDelMuestrario(
                c,
                f["nombre"],
                f["tinte"],
                Acabado(f["facetas"], f["destellos"], f["fuego"]),
            )
            for c in ColorCircon
            if (f := filas.get(c.value)) is not None
        ]

    def fijar(
        self,
        color: ColorCircon,
        nombre: str,
        tinte: str,
        acabado: Acabado | None = None,
    ) -> ColorDelMuestrario:
        """Cambia nombre, tinte y acabado de una bolsita. ValueError si no sirve.

        Sin acabado, se queda el que tenía."""
        limpio = validar_nombre_de_color(nombre, color)
        # «violeta» ya quiere decir MORADO cuando lo escribe una clienta: si
        # fuera el nombre de la lila, el bot leería mal su propio nombre.
        otro = SINONIMOS.get(" ".join(normalizar(limpio).split()))
        if otro is not None and otro is not color:
            raise ValueError(
                f"«{limpio}» ya quiere decir {NOMBRE_COLOR[otro]} cuando lo escribe "
                "una clienta: escoge otro nombre"
            )
        tinte = (tinte or "").strip().upper()
        if len(tinte) != 7 or not tinte.startswith("#"):
            raise ValueError("el tinte va como #RRGGBB")
        int(tinte[1:], 16)  # ValueError si no es hexadecimal
        acabado = acabado or ACABADO_COLOR[color]
        self._db.ejecutar(
            "UPDATE colores_circon SET nombre = ?, tinte = ?, facetas = ?, "
            "destellos = ?, fuego = ?, actualizado = ? WHERE clave = ?",
            (
                limpio,
                tinte,
                acabado.facetas,
                acabado.destellos,
                acabado.fuego,
                datetime.now(UTC).isoformat(),
                color.value,
            ),
        )
        self._aplicar()
        return ColorDelMuestrario(color, limpio, tinte, acabado)

    def _aplicar(self) -> None:
        filas = self.todos()
        aplicar_paleta(
            {c.color: (c.nombre, c.tinte) for c in filas},
            {c.color: c.acabado for c in filas},
        )
