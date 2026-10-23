"""La base de ventas sobre el mismo SQLite (ADR 0015).

No hay tabla «ventas» con copias de los pedidos: una venta ES un pedido, y
duplicarlo sería tener dos verdades que un día dicen distinto. Aquí solo vive
lo que el pedido no sabe:

  · `ventas_anotaciones`      lo que Camilo escribe en las columnas suyas del
                              Excel (costo, fuente, notas). Una fila por celda.
  · `ventas_anotaciones_log`  cada cambio de una anotación: antes, después y
                              cuándo. Append-only. Es la trazabilidad.
  · `ventas_sincronizaciones` cada vez que se escribió el Excel y qué pasó.
"""

# ruff: noqa: E501  (SQL y textos del diccionario: partirlos los hace ilegibles)

from __future__ import annotations

from datetime import UTC, datetime

from app.domain.models import Customer, Order

ESQUEMA = """
CREATE TABLE IF NOT EXISTS ventas_anotaciones (
    order_id    TEXT NOT NULL,
    columna     TEXT NOT NULL,
    valor       TEXT NOT NULL,
    actualizado TEXT NOT NULL,
    PRIMARY KEY (order_id, columna)
);
CREATE TABLE IF NOT EXISTS ventas_anotaciones_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id    TEXT NOT NULL,
    columna     TEXT NOT NULL,
    antes       TEXT,
    despues     TEXT,
    origen      TEXT NOT NULL,
    created_at  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS ventas_sincronizaciones (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at        TEXT NOT NULL,
    ventas            INTEGER NOT NULL,
    clientas          INTEGER NOT NULL,
    anotaciones_nuevas INTEGER NOT NULL,
    resultado         TEXT NOT NULL
);
"""


def _ahora() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class BaseDeVentas:
    def __init__(self, db) -> None:
        self._db = db
        for sentencia in ESQUEMA.split(";"):
            if sentencia.strip():
                self._db.ejecutar(sentencia)

    # -- lo que ya existe --------------------------------------------------

    def pedidos(self) -> list[Order]:
        return [
            Order.model_validate_json(f["payload"])
            for f in self._db.consultar("SELECT payload FROM orders ORDER BY created_at")
        ]

    def clientas(self) -> dict[str, Customer]:
        return {
            c.id: c
            for c in (
                Customer.model_validate_json(f["payload"])
                for f in self._db.consultar("SELECT payload FROM customers")
            )
        }

    def cuando(self) -> dict[str, dict[str, datetime]]:
        """pedido -> estado -> la PRIMERA vez que llegó a ese estado."""
        salida: dict[str, dict[str, datetime]] = {}
        for f in self._db.consultar(
            "SELECT order_id, estado_nuevo, MIN(created_at) AS cuando "
            "FROM order_events GROUP BY order_id, estado_nuevo"
        ):
            salida.setdefault(f["order_id"], {})[f["estado_nuevo"]] = (
                datetime.fromisoformat(f["cuando"])
            )
        return salida

    def huella(self) -> str:
        """Cambia cuando cambia algo que va al Excel. Barato de calcular."""
        fila = self._db.consultar(
            "SELECT COUNT(*) AS n, COALESCE(MAX(updated_at), '') AS u FROM orders"
        )[0]
        notas = self._db.consultar(
            "SELECT COUNT(*) AS n, COALESCE(MAX(actualizado), '') AS u "
            "FROM ventas_anotaciones"
        )[0]
        return f"{fila['n']}|{fila['u']}|{notas['n']}|{notas['u']}"

    # -- lo de Camilo ------------------------------------------------------

    def anotaciones(self) -> dict[str, dict[str, str]]:
        salida: dict[str, dict[str, str]] = {}
        for f in self._db.consultar(
            "SELECT order_id, columna, valor FROM ventas_anotaciones"
        ):
            salida.setdefault(f["order_id"], {})[f["columna"]] = f["valor"]
        return salida

    def guardar_anotaciones(
        self, leidas: dict[str, dict[str, str]], validas: set[str], origen: str = "excel"
    ) -> int:
        """Guarda lo que cambió. Solo pedidos que existen y columnas editables."""
        existentes = {f["id"] for f in self._db.consultar("SELECT id FROM orders")}
        actuales = self.anotaciones()
        cambios = 0
        for order_id, columnas in leidas.items():
            if order_id not in existentes:
                continue
            for columna, valor in columnas.items():
                if columna not in validas:
                    continue
                antes = actuales.get(order_id, {}).get(columna, "")
                if valor == antes:
                    continue
                ahora = _ahora()
                if valor:
                    self._db.ejecutar(
                        "INSERT INTO ventas_anotaciones (order_id, columna, valor, actualizado) "
                        "VALUES (?,?,?,?) ON CONFLICT(order_id, columna) DO UPDATE SET "
                        "valor = excluded.valor, actualizado = excluded.actualizado",
                        (order_id, columna, valor, ahora),
                    )
                else:
                    self._db.ejecutar(
                        "DELETE FROM ventas_anotaciones WHERE order_id = ? AND columna = ?",
                        (order_id, columna),
                    )
                self._db.ejecutar(
                    "INSERT INTO ventas_anotaciones_log "
                    "(order_id, columna, antes, despues, origen, created_at) "
                    "VALUES (?,?,?,?,?,?)",
                    (order_id, columna, antes, valor, origen, ahora),
                )
                cambios += 1
        return cambios

    # -- bitácora ----------------------------------------------------------

    def registrar(self, ventas: int, clientas: int, nuevas: int, resultado: str) -> None:
        self._db.ejecutar(
            "INSERT INTO ventas_sincronizaciones "
            "(created_at, ventas, clientas, anotaciones_nuevas, resultado) VALUES (?,?,?,?,?)",
            (_ahora(), ventas, clientas, nuevas, resultado),
        )

    def ultimas_sincronizaciones(self, limite: int = 50) -> list[dict]:
        return [
            dict(f)
            for f in self._db.consultar(
                "SELECT created_at, ventas, clientas, anotaciones_nuevas, resultado "
                "FROM ventas_sincronizaciones ORDER BY id DESC LIMIT ?",
                (limite,),
            )
        ]
