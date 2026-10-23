"""Formato de las hojas del ERP: colores, títulos, anchos y gráficas (01/10)."""

from __future__ import annotations


def rgb(hexa: str) -> dict:
    hexa = hexa.lstrip("#")
    return {
        k: int(hexa[j : j + 2], 16) / 255
        for k, j in zip(("red", "green", "blue"), (0, 2, 4), strict=True)
    }


AZUL_CALCULADO = "#E8F0FE"
AMARILLO_CAPTURA = "#FFF2CC"
TITULO = "#4C1D95"
ENCABEZADO = "#EDE9FE"


def celdas(
    sid: int, r0: int, r1: int, c0: int, c1: int, formato: dict, campos: str
) -> dict:
    return {
        "repeatCell": {
            "range": {
                "sheetId": sid,
                "startRowIndex": r0,
                "endRowIndex": r1,
                "startColumnIndex": c0,
                "endColumnIndex": c1,
            },
            "cell": {"userEnteredFormat": formato},
            "fields": f"userEnteredFormat({campos})",
        }
    }


def ancho(sid: int, c0: int, c1: int, pixeles: int) -> dict:
    return {
        "updateDimensionProperties": {
            "range": {
                "sheetId": sid,
                "dimension": "COLUMNS",
                "startIndex": c0,
                "endIndex": c1,
            },
            "properties": {"pixelSize": pixeles},
            "fields": "pixelSize",
        }
    }


FORMATO_NUMERO = {
    "pesos": {"type": "CURRENCY", "pattern": '"$"#,##0'},
    "pct": {"type": "PERCENT", "pattern": "0.0%"},
    "mes": {"type": "DATE", "pattern": "mmm yyyy"},
    "x": {"type": "NUMBER", "pattern": '0.0"x"'},
    "gramos": {"type": "NUMBER", "pattern": '0.0# "g"'},
    "entero": {"type": "NUMBER", "pattern": "#,##0"},
}


def titulo(sid: int, fila: int, columnas: int, grande: bool = False) -> list[dict]:
    return [
        celdas(
            sid,
            fila,
            fila + 1,
            0,
            columnas,
            {
                "backgroundColor": rgb(TITULO),
                "textFormat": {
                    "bold": True,
                    "fontSize": 14 if grande else 11,
                    "foregroundColor": rgb("#FFFFFF"),
                },
            },
            "backgroundColor,textFormat",
        ),
    ]


def encabezado(sid: int, fila: int, columnas: int) -> dict:
    return celdas(
        sid,
        fila,
        fila + 1,
        0,
        columnas,
        {
            "backgroundColor": rgb(ENCABEZADO),
            "textFormat": {"bold": True},
            "wrapStrategy": "WRAP",
        },
        "backgroundColor,textFormat,wrapStrategy",
    )


def rango(sid: int, r0: int, r1: int, c: int) -> dict:
    return {
        "sourceRange": {
            "sources": [
                {
                    "sheetId": sid,
                    "startRowIndex": r0,
                    "endRowIndex": r1,
                    "startColumnIndex": c,
                    "endColumnIndex": c + 1,
                }
            ]
        }
    }


def limpiar(sid: int, r0: int, r1: int, c0: int, c1: int) -> dict:
    """Todo el formato de un rango en blanco: un color viejo no queda en una fila
    que cambió de lugar (pasó en Costeo el 01/10)."""
    return {
        "repeatCell": {
            "range": {
                "sheetId": sid,
                "startRowIndex": r0,
                "endRowIndex": r1,
                "startColumnIndex": c0,
                "endColumnIndex": c1,
            },
            "cell": {},
            "fields": "userEnteredFormat",
        }
    }


def pestana(sid: int, color: str, congeladas: int) -> dict:
    """Color de la pestaña y filas fijas arriba."""
    return {
        "updateSheetProperties": {
            "properties": {
                "sheetId": sid,
                "gridProperties": {"frozenRowCount": congeladas},
                "tabColorStyle": {"rgbColor": rgb(color)},
            },
            "fields": "gridProperties.frozenRowCount,tabColorStyle",
        }
    }


def lista(sid: int, fila: int, col: int, fuente: str) -> dict:
    """Una celda con lista desplegable que sale de un rango (p. ej. los años)."""
    return {
        "setDataValidation": {
            "range": {
                "sheetId": sid,
                "startRowIndex": fila,
                "endRowIndex": fila + 1,
                "startColumnIndex": col,
                "endColumnIndex": col + 1,
            },
            "rule": {
                "condition": {
                    "type": "ONE_OF_RANGE",
                    "values": [{"userEnteredValue": fuente}],
                },
                "showCustomUi": True,
                "strict": False,
            },
        }
    }
