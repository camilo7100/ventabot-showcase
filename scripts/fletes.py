"""`vb fletes` — mirar y revisar la tabla de envíos SIN abrir el código.

Para qué sirve
==============
`data/fletes.csv` es el único sitio donde vive el precio del envío. Este
comando existe para tres cosas que Camilo va a querer hacer sin llamar a
nadie:

    vb fletes                 ver la tabla entera, ordenada por zona
    vb fletes medellin        cuánto le cuesta a UNA clienta concreta
    vb fletes --revisar       buscar errores de dedo antes de que cobren mal

El tercero es el importante. Un cero de más en una fila —14000 escrito
140000— no lo ve nadie leyendo el archivo, y se descubre cuando una clienta
pregunta por qué el envío cuesta más que el anillo.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.infra.consola import preparar_salida

# UTF-8 pase lo que pase: sin esto, redirigir la salida a un archivo (o
# leerla desde otro proceso) revienta en Windows al imprimir un ✔.
preparar_salida()


from app.adapters.repositories.csv_files import CsvFletes
from app.infra.settings import get_settings

#: Un flete de Coordinadora dentro de Colombia cae siempre entre estos dos
#: números. Fuera de aquí es casi seguro un error de tecleo, no una tarifa.
MINIMO, MAXIMO = 5_000, 60_000

ORDEN_ZONAS = ("LOCAL", "PRINCIPAL", "INTERMEDIA", "ESPECIAL")


def pesos(valor: int) -> str:
    return f"${valor:,.0f}".replace(",", ".")


def tabla(fletes: CsvFletes) -> None:
    print()
    print("  TABLA DE ENVÍOS  ·  data/fletes.csv")
    print("  " + "─" * 62)
    print(
        f"  Sin ciudad (fila DEFECTO): {pesos(fletes.costo_por_defecto)} · "
        f"{fletes.dias_por_defecto} día(s)"
    )
    print("  " + "─" * 62)

    ciudades = fletes.ciudades()
    por_zona: dict[str, list[str]] = {}
    for ciudad in ciudades:
        por_zona.setdefault(fletes.buscar(ciudad).zona, []).append(ciudad)

    zonas = [z for z in ORDEN_ZONAS if z in por_zona]
    zonas += sorted(z for z in por_zona if z not in ORDEN_ZONAS)

    for zona in zonas:
        print(f"\n  {zona}")
        for ciudad in por_zona[zona]:
            f = fletes.buscar(ciudad)
            linea = f"    {ciudad:<22} {pesos(f.costo_cop):>10}"
            print(f"{linea}   {f.dias_transporte} día(s)")

    print()
    print(f"  {len(ciudades)} ciudades. Para cambiar un valor: abre data/fletes.csv,")
    print("  edítalo con Excel o el Bloc de notas y reinicia el bot.")
    print()


def una_ciudad(fletes: CsvFletes, ciudad: str) -> int:
    f = fletes.buscar(ciudad)
    print()
    if f.zona == "DEFAULT":
        print(f"  «{ciudad}» NO está en la tabla.")
        print(
            f"  Se le cobraría el valor por defecto: {pesos(f.costo_cop)} · "
            f"{f.dias_transporte} día(s)."
        )
        print()
        print("  Si vendes seguido allá, agrégala como una fila más en")
        print("  data/fletes.csv y deja de cobrar de menos (o de más).")
    else:
        print(f"  {f.ciudad} ({f.departamento})")
        print(f"    Envío .......... {pesos(f.costo_cop)}")
        print(f"    Transporte ..... {f.dias_transporte} día(s) después de fabricado")
        print(f"    Zona ........... {f.zona}")
    print()
    return 0


def revisar(fletes: CsvFletes) -> int:
    """Errores de dedo. Devuelve 1 si encuentra alguno, para poder usarlo en CI."""
    problemas: list[str] = []

    for ciudad in fletes.ciudades():
        f = fletes.buscar(ciudad)
        if f.costo_cop < MINIMO:
            problemas.append(
                f"{ciudad}: {pesos(f.costo_cop)} es demasiado barato "
                f"(¿faltó un cero?). Lo estarías pagando tú."
            )
        if f.costo_cop > MAXIMO:
            problemas.append(
                f"{ciudad}: {pesos(f.costo_cop)} es demasiado caro "
                f"(¿sobra un cero?). Con eso se cae la venta."
            )
        if not 1 <= f.dias_transporte <= 15:
            problemas.append(
                f"{ciudad}: {f.dias_transporte} días de transporte no tiene sentido."
            )
        if not f.departamento:
            problemas.append(f"{ciudad}: le falta el departamento (no es grave).")

    print()
    if not problemas:
        print(f"  ✓ Todos los valores se ven bien ({len(fletes.ciudades())} ciudades).")
        print(f"  ✓ Sin ciudad se cobra {pesos(fletes.costo_por_defecto)}.")
        print()
        return 0

    print(f"  Encontré {len(problemas)} cosa(s) que revisar en data/fletes.csv:")
    print()
    for p in problemas:
        print(f"    · {p}")
    print()
    return 1


def main(argv: list[str]) -> int:
    ruta = get_settings().fletes_csv
    if not ruta.is_file():
        print()
        print(f"  No encuentro {ruta}")
        print("  Sin ese archivo el bot cobra el envío nacional a todo el mundo.")
        print()
        return 1

    fletes = CsvFletes(ruta)

    if not argv:
        tabla(fletes)
        return 0
    if argv[0] in ("--revisar", "-r", "revisar"):
        return revisar(fletes)
    return una_ciudad(fletes, " ".join(argv))


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
