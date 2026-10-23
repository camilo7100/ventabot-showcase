"""LEEME del ERP: la historia de la sábana y qué es cada hoja nueva (01–02/10)."""

from __future__ import annotations

from app.adapters.erp.sheets import Hoja

LEEME_SABANA = "DATOS REALES (01/10/2026)"


RECORDATORIO = "Recordatorio estructural"


def montar_leeme(hoja: Hoja, resumen_sabana: str) -> list[str]:
    (filas, validaciones) = hoja.leer(["LEEME!A1:B120", "Validaciones!A1:B30"])
    # El recordatorio de Validaciones decía que la mamá no estaba costeada: ya lo
    # está (Costeo → Gastos, estimado). Lo que sigue sin costear es Camilo.
    for i, f in enumerate(validaciones):
        if len(f) > 1 and str(f[1]).startswith(RECORDATORIO):
            hoja.escribir(
                [
                    (
                        f"Validaciones!B{i + 1}",
                        [
                            [
                                f"{RECORDATORIO}: el salario de Lía (la dueña), el "
                                "pago a la mamá y al tío, el taller y las diligencias se "
                                "estiman en Costeo y entran a Gastos. Camilo (TI) no "
                                "cobra: "
                                "su tiempo no se costea."
                            ]
                        ],
                    )
                ]
            )
    textos = [str(f[1]).strip() if len(f) > 1 else "" for f in filas]

    def fila_de(prefijo: str) -> int | None:
        return next((i + 1 for i, t in enumerate(textos) if t.startswith(prefijo)), None)

    e: list[tuple[str, list[list]]] = []
    # La migración vieja (142 ventas ene–mar) ya no es lo que hay: se reemplaza.
    if n := fila_de("DATOS MIGRADOS"):
        e.append((f"LEEME!B{n}", [[f"{LEEME_SABANA}: LA SÁBANA DE VENTAS"]]))
        e.append((f"LEEME!B{n + 1}", [[resumen_sabana]]))
    elif n := fila_de(LEEME_SABANA):
        e.append((f"LEEME!B{n + 1}", [[resumen_sabana]]))
    siguiente = max((i + 1 for i, t in enumerate(textos) if t), default=0) + 2
    hojas_nuevas = (
        (
            "Costeo — ",
            "Costeo — CATÁLOGO/CÁLCULO. El costo completo de cada pieza capa por "
            "capa: receta (BOM, con los gramos reales) + merma + salario de Lía + "
            "taller + familia + diligencias + equipos + colchón, y el costo MES A MES "
            "(la plata cambia). Config («Costo real por anillo») es el de hoy: lo usa "
            "el marketing. Los supuestos en amarillo los cambias tú.",
        ),
        (
            "Precio_Plata — ",
            "Precio_Plata — CATÁLOGO. El precio por gramo de la plata 925 de cada mes "
            "(lo anotas tú). El último mes es el precio de hoy; cada venta se costea "
            "con el de su mes.",
        ),
        (
            "Respuestas_Lía — ",
            "Respuestas_Lía — CAPTURA. Lo que contestó Lía en su Excel (vb erp "
            "--cuestionario lo crea; vb erp --importar-lia lo pasa). Cada respuesta "
            "con número reemplaza un supuesto de Costeo o un precio de Cat_Materiales "
            "(queda REAL); un «NO SÉ» lo deja como está. Lo del mes que el bot no ve "
            "(compras, gastos, plata, equipos, ventas fuera del bot, conteo del "
            "inventario) entra desde el mismo Excel, marcado «LIA …» (no se duplica).",
        ),
        (
            "Balance — ",
            "Balance — PROCESAMIENTO. Activos, pasivos y patrimonio al último mes con "
            "ventas (estimado: anota las deudas en amarillo).",
        ),
        (
            "Gráficas — ",
            "Gráficas — VISUALIZACIÓN. Elige año y mes arriba (amarillo): tablas con "
            "fórmulas y su gráfica al lado: mes a mes, piezas por producto, clientas, "
            "mezcla, canal, tallas, colores, día de la semana y el costo por capas.",
        ),
    )
    for prefijo, texto in hojas_nuevas:
        n = fila_de(prefijo)
        if n is None:
            n, siguiente = siguiente, siguiente + 1
        e.append((f"LEEME!B{n}", [[texto]]))
    hoja.escribir(e)
    return ["LEEME"]
