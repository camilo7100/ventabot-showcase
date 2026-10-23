"""La tabla `pedidos_analitica`: una fila por pedido, siempre al día (29/09).

Se reconstruye entera desde los pedidos (idempotente): nunca queda desfasada
ni hay que migrarla. Con decenas o miles de pedidos tarda milisegundos. Las
columnas nuevas de `COLUMNAS` se agregan solas (ALTER TABLE) sin tocar las viejas.
"""

from __future__ import annotations

import csv
import io
import json
import logging

from app.domain.analitica import COLUMNAS, NOMBRES, fila_de_pedido
from app.domain.erp import por_anillo
from app.domain.models import Customer, Order

TABLA = "pedidos_analitica"

log = logging.getLogger("ventabot.analitica")

# Los nombres de tabla y columnas que se pegan en el SQL son CONSTANTES de este
# código (`TABLA`, `COLUMNAS`), nunca texto que escribe alguien: de ahí los
# `noqa: S608`. Los valores van siempre como parámetros (?).


class SqliteAnalitica:
    def __init__(self, db) -> None:
        self._db = db
        definicion = ", ".join(
            f"{nombre} {tipo}" + (" PRIMARY KEY" if nombre == "codigo" else "")
            for nombre, tipo, _ in COLUMNAS
        )
        self._db.ejecutar(f"CREATE TABLE IF NOT EXISTS {TABLA} ({definicion})")
        hay = {f["name"] for f in self._db.consultar(f"PRAGMA table_info({TABLA})")}
        for nombre, tipo, _ in COLUMNAS:
            if nombre not in hay:
                self._db.ejecutar(f"ALTER TABLE {TABLA} ADD COLUMN {nombre} {tipo}")

    def reconstruir(self) -> int:
        """Vuelve a aplanar TODOS los pedidos. Devuelve cuántos."""
        clientas = {
            f["id"]: Customer.model_validate_json(f["payload"])
            for f in self._db.consultar("SELECT id, payload FROM customers")
        }
        eventos: dict[str, list[tuple[str, str]]] = {}
        for f in self._db.consultar(
            "SELECT order_id, estado_nuevo, created_at FROM order_events "
            "ORDER BY created_at"
        ):
            eventos.setdefault(f["order_id"], []).append(
                (f["estado_nuevo"], f["created_at"])
            )
        filas = []
        for f in self._db.consultar("SELECT payload FROM orders"):
            try:
                pedido = Order.model_validate(json.loads(f["payload"]))
            except Exception as exc:  # pragma: no cover - uno raro no tumba el resto
                log.warning("pedido que no se pudo leer para el análisis (%s)", exc)
                continue
            clienta = clientas.get(pedido.customer_id)
            # Un pedido de varios anillos: una fila por anillo (PED-…-A1, -A2).
            filas.extend(
                fila_de_pedido(
                    anillo,
                    nombre_clienta=(clienta.nombre or "") if clienta else "",
                    canal=clienta.channel.value if clienta else "",
                    telefono=clienta.channel_user_id if clienta else "",
                    eventos=eventos.get(pedido.id, []),
                )
                for anillo in por_anillo(pedido)
            )
        marcas = ",".join("?" * len(NOMBRES))
        insertar = f"INSERT INTO {TABLA} ({','.join(NOMBRES)}) VALUES ({marcas})"  # noqa: S608
        self._db.ejecutar(f"DELETE FROM {TABLA}")  # noqa: S608
        for fila in filas:
            self._db.ejecutar(insertar, tuple(fila[n] for n in NOMBRES))
        return len(filas)

    def filas(self) -> list[dict]:
        return [
            dict(f)
            for f in self._db.consultar(
                f"SELECT * FROM {TABLA} ORDER BY creado DESC"  # noqa: S608
            )
        ]

    def csv(self) -> str:
        """Para abrir en Excel: separado por punto y coma, con BOM (tildes bien)."""
        salida = io.StringIO()
        escritor = csv.writer(salida, delimiter=";")
        escritor.writerow(NOMBRES)
        for fila in self.filas():
            escritor.writerow(
                ["" if fila.get(n) is None else fila.get(n) for n in NOMBRES]
            )
        return "﻿" + salida.getvalue()
