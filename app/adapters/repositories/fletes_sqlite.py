"""Los fletes en la base, para que Lía los cambie desde el panel (29/09).

`data/fletes.csv` sigue siendo la SEMILLA: la primera vez que arranca, la
tabla se llena con lo que diga el archivo. Desde ahí manda la tabla, que vive
en el volumen del servidor y se edita en el panel (Envíos) sin tocar código ni
desplegar. La misma interfaz que `CsvFletes`: `buscar`, `costo_por_defecto`.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from app.adapters.repositories.csv_files import CsvFletes, Flete

FILA_POR_DEFECTO = CsvFletes.FILA_POR_DEFECTO

_ESQUEMA = """
CREATE TABLE IF NOT EXISTS fletes (
    ciudad_clave   TEXT PRIMARY KEY,
    ciudad         TEXT NOT NULL,
    departamento   TEXT NOT NULL DEFAULT '',
    zona           TEXT NOT NULL DEFAULT '',
    costo_cop      INTEGER NOT NULL,
    dias_transporte INTEGER NOT NULL DEFAULT 4,
    actualizado    TEXT NOT NULL
)
"""


class SqliteFletes:
    """Tabla de envíos editable. Nunca falla: sin ciudad, el valor por defecto."""

    normalizar = staticmethod(CsvFletes.normalizar)

    def __init__(self, db, semilla: Path | None = None) -> None:
        self._db = db
        self._db.ejecutar(_ESQUEMA)
        vacia = not self._db.consultar("SELECT 1 FROM fletes LIMIT 1")
        if vacia and semilla is not None and semilla.exists():
            csv = CsvFletes(semilla)
            self.fijar(FILA_POR_DEFECTO, csv.costo_por_defecto, csv.dias_por_defecto)
            for f in csv._por_ciudad.values():
                self.fijar(
                    f.ciudad, f.costo_cop, f.dias_transporte, f.departamento, f.zona
                )

    # -- lectura (la misma que CsvFletes) ------------------------------------

    def _fila(self, clave: str) -> Flete | None:
        filas = self._db.consultar(
            "SELECT ciudad, departamento, zona, costo_cop, dias_transporte "
            "FROM fletes WHERE ciudad_clave = ?",
            (clave,),
        )
        if not filas:
            return None
        f = filas[0]
        return Flete(
            ciudad=f["ciudad"],
            departamento=f["departamento"],
            zona=f["zona"],
            costo_cop=int(f["costo_cop"]),
            dias_transporte=int(f["dias_transporte"]),
        )

    @property
    def costo_por_defecto(self) -> int:
        fila = self._fila(self.normalizar(FILA_POR_DEFECTO))
        return fila.costo_cop if fila else CsvFletes.COSTO_ULTIMO_RECURSO

    @property
    def dias_por_defecto(self) -> int:
        fila = self._fila(self.normalizar(FILA_POR_DEFECTO))
        return fila.dias_transporte if fila else CsvFletes.DIAS_ULTIMO_RECURSO

    def buscar(self, ciudad: str | None) -> Flete:
        if ciudad:
            fila = self._fila(self.normalizar(ciudad))
            if fila is not None and fila.ciudad != FILA_POR_DEFECTO:
                return fila
        return Flete(
            ciudad=ciudad or "(sin especificar)",
            departamento="",
            zona="DEFAULT",
            costo_cop=self.costo_por_defecto,
            dias_transporte=self.dias_por_defecto,
        )

    def ciudades(self) -> list[Flete]:
        """Todas las ciudades (sin la fila por defecto), por nombre."""
        filas = self._db.consultar(
            "SELECT ciudad, departamento, zona, costo_cop, dias_transporte FROM fletes "
            "WHERE ciudad <> ? ORDER BY ciudad",
            (FILA_POR_DEFECTO,),
        )
        return [
            Flete(
                ciudad=f["ciudad"],
                departamento=f["departamento"],
                zona=f["zona"],
                costo_cop=int(f["costo_cop"]),
                dias_transporte=int(f["dias_transporte"]),
            )
            for f in filas
        ]

    # -- escritura (el panel) -------------------------------------------------

    def fijar(
        self,
        ciudad: str,
        costo_cop: int,
        dias_transporte: int | None = None,
        departamento: str = "",
        zona: str = "",
    ) -> None:
        """Pone (o cambia) el flete de una ciudad. `(DEFECTO)` es el general."""
        ciudad = " ".join((ciudad or "").split())
        if not ciudad:
            raise ValueError("falta la ciudad")
        if not 0 <= int(costo_cop) <= 500_000:
            raise ValueError("el flete tiene que estar entre $0 y $500.000")
        clave = self.normalizar(ciudad)
        actual = self._fila(clave)
        dias = (
            dias_transporte
            if dias_transporte is not None
            else (actual.dias_transporte if actual else self.dias_por_defecto)
        )
        self._db.ejecutar(
            "INSERT INTO fletes (ciudad_clave, ciudad, departamento, zona, costo_cop, "
            "dias_transporte, actualizado) VALUES (?,?,?,?,?,?,?) "
            "ON CONFLICT(ciudad_clave) DO UPDATE SET ciudad=excluded.ciudad, "
            "costo_cop=excluded.costo_cop, dias_transporte=excluded.dias_transporte, "
            "departamento=CASE WHEN excluded.departamento <> '' "
            "THEN excluded.departamento ELSE fletes.departamento END, "
            "zona=CASE WHEN excluded.zona <> '' THEN excluded.zona ELSE fletes.zona END, "
            "actualizado=excluded.actualizado",
            (
                clave,
                ciudad,
                departamento,
                zona,
                int(costo_cop),
                int(dias),
                datetime.now(UTC).isoformat(timespec="seconds"),
            ),
        )

    def tarifa_unica(self, costo_cop: int) -> int:
        """El mismo flete para TODAS las ciudades y el general. Devuelve cuántas."""
        if not 0 <= int(costo_cop) <= 500_000:
            raise ValueError("el flete tiene que estar entre $0 y $500.000")
        cursor = self._db.ejecutar(
            "UPDATE fletes SET costo_cop = ?, actualizado = ?",
            (int(costo_cop), datetime.now(UTC).isoformat(timespec="seconds")),
        )
        if not self._fila(self.normalizar(FILA_POR_DEFECTO)):
            self.fijar(FILA_POR_DEFECTO, int(costo_cop))
        return cursor.rowcount

    def quitar(self, ciudad: str) -> None:
        """Quita una ciudad: se le cobra el general. La general no se quita."""
        clave = self.normalizar(ciudad)
        if clave == self.normalizar(FILA_POR_DEFECTO):
            raise ValueError("el flete general no se puede quitar")
        self._db.ejecutar("DELETE FROM fletes WHERE ciudad_clave = ?", (clave,))
