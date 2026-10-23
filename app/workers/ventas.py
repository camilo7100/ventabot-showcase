"""Mantiene el Excel de ventas al día, solo (ADR 0015).

Cada vuelta hace tres cosas, en este orden, y el orden es la garantía:

  1. LEE del Excel lo que Camilo escribió en sus columnas y lo GUARDA en la base
     (con bitácora de antes/después). Si esto no va primero, reescribir el
     Excel borraría lo que acaba de escribir.
  2. CONSTRUYE las filas desde la base: pedidos, clientas, eventos y anotaciones.
  3. ESCRIBE el Excel entero. Si está abierto, no se puede: queda para la
     siguiente vuelta y nada se pierde, porque lo de Camilo ya está en la base.

La vuelta automática solo trabaja si algo cambió (pedidos, anotaciones o el
propio archivo): con el negocio quieto no toca el disco.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from dataclasses import dataclass

from app.domain.ventas import EDITABLES, fila_de_venta, filas_de_clientas

log = logging.getLogger("ventabot.ventas")


@dataclass
class Informe:
    ventas: int
    clientas: int
    anotaciones_guardadas: int
    escrito: bool
    detalle: str


def sincronizar(base, libro) -> Informe:
    leidas = {}
    try:
        leidas = libro.leer_editables()
    except Exception as exc:  # un Excel dañado no puede tumbar la base
        log.warning("no se pudo leer el Excel de ventas (%s): no se toca", exc)
        base.registrar(0, 0, 0, f"no se pudo leer el Excel: {exc}")
        return Informe(0, 0, 0, False, f"no se pudo leer el Excel: {exc}")
    guardadas = base.guardar_anotaciones(leidas, set(EDITABLES))

    clientas = base.clientas()
    cuando = base.cuando()
    anotaciones = base.anotaciones()
    ventas = [
        fila_de_venta(
            p, clientas.get(p.customer_id), cuando.get(p.id, {}), anotaciones.get(p.id)
        )
        for p in base.pedidos()
    ]
    resumen_clientas = filas_de_clientas(ventas)

    try:
        registro = [
            {
                "created_at": "(esta vuelta)",
                "ventas": len(ventas),
                "clientas": len(resumen_clientas),
                "anotaciones_nuevas": guardadas,
                "resultado": "ok",
            },
            *base.ultimas_sincronizaciones(49),
        ]
        libro.escribir(ventas, resumen_clientas, registro)
        detalle, escrito = "ok", True
    except PermissionError:
        detalle, escrito = (
            "el Excel está abierto: se reintenta en la próxima vuelta",
            False,
        )
    base.registrar(len(ventas), len(resumen_clientas), guardadas, detalle)
    return Informe(len(ventas), len(resumen_clientas), guardadas, escrito, detalle)


class SincronizadorDeVentas:
    """La vuelta automática, dentro del servidor."""

    def __init__(self, base, libro, intervalo_s: float = 120.0, despues=None) -> None:
        #: Lo que se hace en cada vuelta, después del Excel: la tabla de
        #: análisis de pedidos (`Container.refrescar_analitica`).
        self._despues = despues
        self._base = base
        self._libro = libro
        self._intervalo = intervalo_s
        self._tarea: asyncio.Task | None = None
        self._ultima = ""

    def _huella(self) -> str:
        ruta = self._libro.ruta
        mtime = ruta.stat().st_mtime if ruta.is_file() else 0
        return f"{self._base.huella()}|{mtime}"

    def una_vuelta(self) -> Informe | None:
        huella = self._huella()
        if huella == self._ultima:
            return None
        informe = sincronizar(self._base, self._libro)
        if informe.escrito:
            self._ultima = self._huella()
        log.info(
            "ventas: %s ventas, %s clientas, %s anotaciones nuevas (%s)",
            informe.ventas,
            informe.clientas,
            informe.anotaciones_guardadas,
            informe.detalle,
        )
        return informe

    def arrancar(self) -> None:
        self._tarea = asyncio.create_task(self._bucle(), name="ventas-excel")
        log.info("Excel de ventas: %s (cada %.0fs)", self._libro.ruta, self._intervalo)

    async def detener(self) -> None:
        if self._tarea:
            self._tarea.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._tarea

    async def _bucle(self) -> None:
        while True:
            try:
                await asyncio.to_thread(self.una_vuelta)
            except Exception:
                log.exception("error sincronizando el Excel de ventas")
            if self._despues is not None:
                try:
                    await asyncio.to_thread(self._despues)
                except Exception:
                    log.exception("error en la vuelta de después del Excel")
            await asyncio.sleep(self._intervalo)
