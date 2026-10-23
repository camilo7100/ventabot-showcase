"""Adaptador Google Sheets — ESQUELETO CON ADVERTENCIAS.

Funciona, y es cómodo para arrancar y para que tu equipo comercial vea los
datos. Pero necesitas conocer sus límites REALES antes de confiarle dinero:

  Cuotas oficiales (developers.google.com/workspace/sheets/api/limits):
      300 lecturas/min por proyecto  ·  60 por usuario por proyecto
      300 escrituras/min por proyecto ·  60 por usuario por proyecto
      Se recargan cada minuto. NO hay límite diario.
      Payload recomendado <= 2 MB. Timeout duro: 180 s.

  Límites de tamaño:
      10.000.000 celdas por hoja de cálculo (18.278 columnas máx.)
      50.000 caracteres por celda

  LO QUE NO TIENE, Y ES LO QUE IMPORTA:
      * NO hay transacciones (no existe BEGIN/COMMIT).
      * NO hay control de concurrencia (no existe SELECT ... FOR UPDATE).
      * Dos webhooks simultáneos que hagan "leer última fila -> escribir la
        siguiente" SE PISAN y pierdes un pedido, sin ningún error visible.

  A ~1 lectura + 1 escritura por mensaje, saturas con ~30 mensajes/minuto.
  Un buen día de ventas lo alcanza.

  La cuota "per user per project" se cuenta POR IDENTIDAD: si toda tu app usa
  una sola service account, compartes esos 60 req/min entre todos tus clientes.
  Ese es el cuello de botella real.

MITIGACIONES OBLIGATORIAS SI USAS ESTO EN SERIO
-----------------------------------------------
  1. Un ÚNICO worker serializado para escrituras, con mutex de Redis.
  2. batchGet / batchUpdate SIEMPRE (N operaciones -> 1 request).
  3. Cache en Redis con TTL para el catálogo.
  4. Nunca get_all_records() sobre hojas grandes.
  5. Backoff exponencial con jitter en 429 y 503.
  6. Columna updated_at + verificación optimista al actualizar.

RECOMENDACIÓN
-------------
  Postgres es la fuente de verdad; Sheets es una VISTA de solo lectura que un
  job sincroniza cada N minutos con un solo `values.batchUpdate`. Así tu equipo
  sigue viendo su hoja y tú no pierdes pedidos.

NOTA: `gspread` (6.2.1) no tiene release desde mayo de 2025. Si Sheets está en
tu camino crítico, usa `google-api-python-client` para controlar batchUpdate.
Y no olvides COMPARTIR la hoja con el email de la service account
(...@....iam.gserviceaccount.com) — es el paso que todo el mundo olvida.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any, ClassVar, TypeVar

from app.domain.models import Order, OrderEvent, Product
from app.domain.order_state import OrderState
from app.domain.ports import ConflictoDeEstado

T = TypeVar("T")


def con_backoff(fn: Callable[[], T], *, intentos: int = 5, base: float = 0.5) -> T:
    """Backoff exponencial con jitter para 429/503 de la API de Sheets."""
    import random

    ultimo: Exception | None = None
    for i in range(intentos):
        try:
            return fn()
        except Exception as exc:
            ultimo = exc
            if "429" not in str(exc) and "503" not in str(exc):
                raise
            # Jitter de backoff, no criptografía.
            time.sleep(base * (2**i) + random.random() * 0.3)  # noqa: S311
    raise RuntimeError(f"Sheets agotó reintentos: {ultimo}")


class SheetsProductRepository:
    """Catálogo desde una pestaña. Fila 1 = encabezados.

    Columnas esperadas:
        sku | nombre | descripcion | precio_cop | iva_pct |
        dias_produccion | anticipo_pct | activo | imagen_url
    """

    def __init__(self, worksheet: Any, cache_ttl_s: int = 300) -> None:
        self._ws = worksheet
        self._cache: list[Product] | None = None
        self._cache_at: float = 0.0
        self._ttl = cache_ttl_s

    def _load(self) -> list[Product]:
        ahora = time.monotonic()
        if self._cache is not None and (ahora - self._cache_at) < self._ttl:
            return self._cache

        filas = con_backoff(lambda: self._ws.get_all_records())
        productos = [
            Product(
                sku=str(f["sku"]).strip(),
                nombre=str(f["nombre"]),
                descripcion=str(f.get("descripcion", "")),
                precio_cop=int(f["precio_cop"]),
                dias_produccion=int(f.get("dias_produccion", 7)),
                activo=str(f.get("activo", "TRUE")).upper() in {"TRUE", "SI", "SÍ", "1"},
                imagen_url=f.get("imagen_url") or None,
            )
            for f in filas
            if str(f.get("sku", "")).strip()
        ]
        self._cache, self._cache_at = productos, ahora
        return productos

    def list_active(self) -> list[Product]:
        return [p for p in self._load() if p.activo]

    def get(self, sku: str) -> Product | None:
        return next((p for p in self._load() if p.sku == sku), None)

    def search(self, query: str, limit: int = 10) -> list[Product]:
        q = query.lower()
        return [p for p in self.list_active() if q in p.nombre.lower()][:limit]


class SheetsOrderRepository:
    """Pedidos en una pestaña.

    ⚠️ ESTE ADAPTADOR NO ES SEGURO BAJO CONCURRENCIA.
    Úsalo solo con UN worker serializado (mutex de Redis) y volumen bajo.
    `update_status` simula bloqueo optimista con read-then-write, que tiene una
    ventana de carrera real. En Postgres es una sola sentencia atómica.

    Está deliberadamente sin terminar: complétalo en la Fase 2 como ejercicio.
    Lo importante es que implementa el MISMO Protocol que el adaptador SQL.
    """

    COLUMNAS: ClassVar[list[str]] = [
        "id",
        "codigo",
        "customer_id",
        "estado",
        "subtotal_cop",
        "iva_cop",
        "envio_cop",
        "total_cop",
        "anticipo_cop",
        "saldo_cop",
        "anticipo_pagado_cop",
        "saldo_pagado_cop",
        "notas",
        "created_at",
        "updated_at",
    ]

    def __init__(self, worksheet: Any, eventos_worksheet: Any) -> None:
        self._ws = worksheet
        self._ev = eventos_worksheet

    def _fila_a_order(self, fila: dict) -> Order:
        return Order(
            id=str(fila["id"]),
            codigo=str(fila["codigo"]),
            customer_id=str(fila["customer_id"]),
            estado=str(fila["estado"]),
            subtotal_cop=int(fila.get("subtotal_cop") or 0),
            iva_cop=int(fila.get("iva_cop") or 0),
            envio_cop=int(fila.get("envio_cop") or 0),
            total_cop=int(fila.get("total_cop") or 0),
            anticipo_cop=int(fila.get("anticipo_cop") or 0),
            saldo_cop=int(fila.get("saldo_cop") or 0),
        )

    def get(self, order_id: str) -> Order | None:
        filas = con_backoff(lambda: self._ws.get_all_records())
        f = next((f for f in filas if str(f.get("id")) == order_id), None)
        return self._fila_a_order(f) if f else None

    def get_by_code(self, codigo: str) -> Order | None:
        filas = con_backoff(lambda: self._ws.get_all_records())
        f = next((f for f in filas if str(f.get("codigo")) == codigo), None)
        return self._fila_a_order(f) if f else None

    def get_active_for_customer(self, customer_id: str) -> Order | None:
        terminales = {"ENTREGADO", "CANCELADO", "REEMBOLSO"}
        filas = con_backoff(lambda: self._ws.get_all_records())
        candidatos = [
            f
            for f in filas
            if str(f.get("customer_id")) == customer_id
            and str(f.get("estado")) not in terminales
        ]
        return self._fila_a_order(candidatos[-1]) if candidatos else None

    def create(self, order: Order, idem_key: str) -> Order:
        # append_row colisiona menos que calcular la fila siguiente a mano.
        existente = self.get(order.id)
        if existente is not None:
            return existente
        valores = [str(getattr(order, c, "")) for c in self.COLUMNAS]
        con_backoff(lambda: self._ws.append_row(valores))
        return order

    def update_status(
        self, order_id: str, nuevo: OrderState, *, expected_current: OrderState
    ) -> Order:
        # ⚠️ VENTANA DE CARRERA: entre esta lectura y la escritura, otro proceso
        # puede cambiar el estado. En Postgres esto es una sola sentencia atómica.
        actual = self.get(order_id)
        if actual is None:
            raise ConflictoDeEstado(f"pedido {order_id} no existe")
        if OrderState(actual.estado) is not expected_current:
            raise ConflictoDeEstado(
                f"esperaba {expected_current.value}, encontró {actual.estado}"
            )
        raise NotImplementedError(
            "Ejercicio de la Fase 2: implementar la escritura de la celda "
            "'estado' con batchUpdate. Ver README.md sección 'Ejercicios'."
        )

    def append_event(self, event: OrderEvent) -> None:
        con_backoff(
            lambda: self._ev.append_row(
                [
                    event.id,
                    event.order_id,
                    event.estado_anterior or "",
                    event.estado_nuevo,
                    event.actor,
                    event.motivo,
                    event.idempotency_key,
                    event.created_at.isoformat(),
                ]
            )
        )
