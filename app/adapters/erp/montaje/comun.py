"""Lo que comparten las partes del montaje: nombres de hojas, piezas y listas."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from app.adapters.erp.sheets import Hoja

COSTEO = "Costeo"
GRAFICAS = "Gráficas"
PLATA = "Precio_Plata"
BALANCE = "Balance"
#: El parámetro de Config que usa el marketing: el costo completo de Costeo.
PARAMETRO_COSTO = "Costo real por anillo ($)"
PLATA_925 = "Plata 925 (g)"
CIRCON = "Circón corazón"
#: Las 4 piedritas de los deditos de cada huellita (02/10: antes no se contaban).
CIRCON_DEDITO = "Circón dedito"
CADENA_DE_PLATA = "Cadena plata 925 (45 cm)"

#: Los productos del costeo (columnas B..E de Costeo) y de las gráficas.
PIEZAS = ("Anillos 1 huella", "Anillos 2 huella", "Anillos 3 huella", "Cadena")
PRODUCTOS = (*PIEZAS, "Manilla", "Dije")
#: Lo que se gasta en el taller al hacer una pieza (no es plata, piedra ni empaque).
INSUMOS_DEL_TALLER = (
    "Cera de modelado",
    "Yeso refractario",
    "Lija agua #220",
    "Lija agua #400",
    "Lija agua #600",
    "Lija agua #1000",
    "Pulidor liquido",
    "Gasolina encendedor",
    "Silicona moldes",
)
EMPAQUE = ("Estuche básico", "Caja de envío", "Tarjeta regalo", "Papel seda")
CANALES = ("Instagram", "Clienta antigua", "WhatsApp", "Referido", "Por clasificar")
TALLAS = (
    "TALLA 4.5",
    "TALLA 5",
    "TALLA 5.5",
    "TALLA 6",
    "TALLA 6.5",
    "TALLA 6.75",
    "TALLA 7",
    "TALLA 7.25",
    "TALLA 7.5",
    "TALLA 8",
    "TALLA 8.5",
    "TALLA 9",
    "TALLA 10",
)
#: (cómo se muestra, lo que se busca en Color_Detalle). La sábana usa nombres
#: viejos (amatista, rosa claro, azul oscuro); el bot, los del muestrario.
COLORES = (
    ("Blanco", "*blanco*"),
    ("Rosa / rosa claro", "*rosa*"),
    ("Fucsia", "*fucsia*"),
    ("Lila", "*lila*"),
    ("Morado", "*morad*"),
    ("Amatista", "*amatista*"),
    ("Celeste / turquesa", "*celeste*"),
    ("Azul", "*azul*"),
    ("Verde oliva", "*oliva*"),
    ("Verde (todos)", "*verde*"),
    ("Amarillo", "*amarillo*"),
    ("Champagne", "*champa*"),
    ("Naranja", "*naranja*"),
    ("Rojo", "*rojo*"),
    ("Negro", "*negro*"),
)
DIAS = ("Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo")


class HojaConFormato(Hoja, Protocol):
    def pestanas(self) -> dict[str, dict]: ...

    def lote(self, pedidos: list[dict]) -> None: ...


@dataclass
class ResultadoMontaje:
    hechos: list[str] = field(default_factory=list)

    def __str__(self) -> str:
        return " · ".join(self.hechos)


def primera_vacia(filas: list[list], desde: int = 4) -> int:
    """La primera fila (1-based, desde `desde`) sin nada en la columna A."""
    n = desde
    while n <= len(filas) and filas[n - 1] and str(filas[n - 1][0]).strip():
        n += 1
    return n


def fila_de(filas: list[list], nombre: str, desde: int = 4) -> int | None:
    """La fila (1-based) cuya columna A es `nombre`, desde `desde`."""
    for i, f in enumerate(filas):
        if i + 1 >= desde and f and str(f[0]).strip() == nombre:
            return i + 1
    return None


def filas_libres(filas: list[list], desde: int = 4):
    """Las filas (1-based) sin nada en la columna A: primero los huecos de adentro,
    después las de abajo. Escribir «desde la primera vacía en adelante» pisaba
    una fila llena si había un hueco antes (BOM, 02/10)."""
    for i in range(desde, len(filas) + 1):
        f = filas[i - 1]
        if not (f and str(f[0]).strip()):
            yield i
    n = max(len(filas) + 1, desde)
    while True:
        yield n
        n += 1
