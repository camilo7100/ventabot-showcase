"""Adaptador de solo lectura sobre archivos CSV.

Sirve para tres cosas:
  1. Que el catálogo semilla de `data/` sea REAL desde la Fase 0, no un
     `CATALOGO_DEMO` incrustado en el código.
  2. Que tengas un segundo adaptador del mismo Protocol desde el día 1 — la
     prueba de que la arquitectura hexagonal no es teoría.
  3. Fallback: si Google Sheets se cae, puedes servir el catálogo desde un CSV
     versionado en Git sin cambiar nada más.

Implementa `ProductRepository`. En la Fase 2 llega `SheetsProductRepository`
con los mismos tres métodos, y en la Fase 6 el de SQL.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from app.domain.models import Product

VERDADEROS = {"TRUE", "SI", "SÍ", "1", "YES", "X"}


def _bool(v: str | None, *, default: bool = True) -> bool:
    if v is None or v == "":
        return default
    return v.strip().upper() in VERDADEROS


def _entero_o_nada(v: str | None) -> int | None:
    """Columna vacía = campo ausente, no cero.

    La diferencia importa: `anticipo_fijo_cop` vacío significa "usa el
    porcentaje"; un 0 significaría "no cobres abono". Un producto que arranca
    producción sin abono es exactamente el error que este proyecto existe para
    no cometer.
    """
    if v is None or not v.strip():
        return None
    return int(v)


def cargar_catalogo_csv(path: Path) -> list[Product]:
    """Lee `data/catalogo.csv` y devuelve modelos de dominio validados.

    Falla ruidosamente si el CSV está mal: es mejor no arrancar que cotizar mal.
    """
    productos: list[Product] = []
    with path.open(encoding="utf-8") as fh:
        for n, fila in enumerate(csv.DictReader(fh), start=2):
            sku = (fila.get("sku") or "").strip()
            if not sku:
                continue
            try:
                productos.append(
                    Product(
                        sku=sku,
                        nombre=(fila["nombre"] or "").strip(),
                        descripcion=(fila.get("descripcion") or "").strip(),
                        precio_cop=int(fila["precio_cop"]),
                        iva_pct=Decimal(fila.get("iva_pct") or "0.19"),
                        dias_produccion=int(fila.get("dias_produccion") or 7),
                        dias_produccion_max=_entero_o_nada(
                            fila.get("dias_produccion_max")
                        ),
                        anticipo_pct=Decimal(fila.get("anticipo_pct") or "0.50"),
                        anticipo_fijo_cop=_entero_o_nada(fila.get("anticipo_fijo_cop")),
                        huellitas=int(fila.get("huellitas") or 0),
                        categoria=(fila.get("categoria") or "anillos").strip(),
                        activo=_bool(fila.get("activo")),
                        imagen_url=(fila.get("imagen_url") or "").strip() or None,
                    )
                )
            except (KeyError, ValueError, TypeError) as exc:
                raise ValueError(f"{path.name} línea {n} (sku={sku!r}): {exc}") from exc

    if not productos:
        raise ValueError(f"{path} no tiene ningún producto")

    duplicados = {p.sku for p in productos if [q.sku for q in productos].count(p.sku) > 1}
    if duplicados:
        raise ValueError(f"{path.name}: SKUs duplicados: {sorted(duplicados)}")

    return productos


def cargar_promociones_csv(path: Path) -> list:
    """`data/promociones.csv` (17/10): nombre, detalle, desde, hasta, activa.

    Fechas AAAA-MM-DD (vacías = sin límite). Una fila que no se entiende NO
    tumba el bot: se salta (una promoción mal escrita no puede inventar nada).
    Sin archivo, no hay promociones.
    """
    from datetime import date

    from app.domain.promociones import Promocion

    if not path.exists():
        return []

    def fecha(v: str | None) -> date | None:
        v = (v or "").strip()
        return date.fromisoformat(v) if v else None

    salida = []
    with path.open(encoding="utf-8-sig", newline="") as f:
        for fila in csv.DictReader(f):
            try:
                salida.append(
                    Promocion(
                        nombre=(fila.get("nombre") or "").strip(),
                        detalle=(fila.get("detalle") or "").strip(),
                        desde=fecha(fila.get("desde")),
                        hasta=fecha(fila.get("hasta")),
                        activa=_bool(fila.get("activa")),
                    )
                )
            except ValueError:
                continue
    return [p for p in salida if p.nombre]


@dataclass(frozen=True)
class Flete:
    ciudad: str
    departamento: str
    zona: str
    costo_cop: int
    dias_transporte: int


class CsvFletes:
    """Tabla de envíos. Normaliza tildes y mayúsculas para poder buscar por
    lo que el cliente escriba ("medellin", "MEDELLÍN", "Medellin").

    ════════════════════════════════════════════════════════════════════════
    POR QUÉ EL FLETE ES UN ARCHIVO Y NO UN NÚMERO EN EL CÓDIGO
    ════════════════════════════════════════════════════════════════════════
    El valor del envío cambia cada vez que la transportadora sube tarifas —
    varias veces al año — y cambia por ciudad. Un número escrito en el código
    obliga a tocar Python, correr los tests y volver a desplegar para algo
    que es una decisión comercial de treinta segundos.

    Con este archivo, Camilo abre `data/fletes.csv`, cambia la cifra, guarda,
    reinicia el bot y ya. Ese es todo el procedimiento.

    LA FILA `(DEFECTO)`
    -------------------
    Vive DENTRO del mismo CSV, no en el código, por la misma razón: es el
    flete que se cobra cuando la clienta no ha dicho su ciudad todavía (que
    es el caso más común de todos, porque el envío se pregunta antes que la
    dirección). Tenerla aquí significa que el valor por defecto también se
    cambia sin programar.
    """

    #: La ciudad reservada que marca la fila del valor por defecto.
    FILA_POR_DEFECTO = "(DEFECTO)"

    #: Último recurso del último recurso: si el CSV no existe o no trae fila
    #: `(DEFECTO)` y quien construye la tabla tampoco pasó un valor. Nunca
    #: debería usarse; existe para que el bot no se caiga por un archivo.
    COSTO_ULTIMO_RECURSO = 15_000
    DIAS_ULTIMO_RECURSO = 4

    def __init__(
        self,
        path: Path,
        costo_default_cop: int | None = None,
        dias_default: int | None = None,
    ) -> None:
        self._costo_default = (
            costo_default_cop
            if costo_default_cop is not None
            else self.COSTO_ULTIMO_RECURSO
        )
        self._dias_default = (
            dias_default if dias_default is not None else self.DIAS_ULTIMO_RECURSO
        )
        self._por_ciudad: dict[str, Flete] = {}
        with path.open(encoding="utf-8") as fh:
            # Las líneas que empiezan por `#` son la explicación que lee
            # Camilo cuando abre el archivo. `csv` no las conoce, así que se
            # filtran antes: sin esto, el archivo documentado no se puede leer.
            filas = (ln for ln in fh if not ln.lstrip().startswith("#"))
            for fila in csv.DictReader(filas):
                if not (fila.get("ciudad") or "").strip():
                    continue
                f = Flete(
                    ciudad=fila["ciudad"].strip(),
                    departamento=(fila.get("departamento") or "").strip(),
                    zona=(fila.get("zona") or "").strip(),
                    costo_cop=int(fila["costo_cop"]),
                    dias_transporte=int(fila["dias_transporte"]),
                )
                if f.ciudad == self.FILA_POR_DEFECTO:
                    self._costo_default = f.costo_cop
                    self._dias_default = f.dias_transporte
                    continue
                self._por_ciudad[self.normalizar(f.ciudad)] = f

    @property
    def costo_por_defecto(self) -> int:
        """Lo que se cobra sin saber la ciudad. Sale de la fila `(DEFECTO)`."""
        return self._costo_default

    @property
    def dias_por_defecto(self) -> int:
        return self._dias_default

    @staticmethod
    def normalizar(texto: str) -> str:
        import unicodedata

        sin_tildes = "".join(
            c
            for c in unicodedata.normalize("NFD", texto)
            if unicodedata.category(c) != "Mn"
        )
        return sin_tildes.strip().lower()

    def buscar(self, ciudad: str | None) -> Flete:
        """Nunca falla: si la ciudad no está, devuelve el costo por defecto.

        Un pedido no se puede caer porque el cliente escribió un pueblo que no
        está en la tabla. Se cotiza con el default y un humano lo ajusta.
        """
        if ciudad:
            f = self._por_ciudad.get(self.normalizar(ciudad))
            if f is not None:
                return f
        return Flete(
            ciudad=ciudad or "(sin especificar)",
            departamento="",
            zona="DEFAULT",
            costo_cop=self._costo_default,
            dias_transporte=self._dias_default,
        )

    def ciudades(self) -> list[str]:
        return sorted(f.ciudad for f in self._por_ciudad.values())
