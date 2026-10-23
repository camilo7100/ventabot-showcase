"""El ERP (HUELLAS_ERP_v1) se llena solo: Ventas, Pagos y Producción.

Se prueba contra una hoja EN MEMORIA con la misma estructura que el ERP real
(títulos en las filas 1-2, encabezados en la 3, fórmulas copiadas hacia abajo),
sin red y sin datos de clientas reales.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.adapters.erp.sheets import HojaEnMemoria, ReconciliadorDelErp
from app.domain import erp
from app.domain.envio import DatosDeEnvio
from app.domain.models import Order, OrderItem
from app.domain.personalizacion import ColorCircon as C
from app.domain.personalizacion import Huellita, Personalizacion

VENTAS = [
    "Venta_ID", "Fecha", "Producto", "Celular_Cliente", "Canal", "Ciudad", "Talla",
    "Color_Detalle", "Grabado", "Cantidad", "Precio_Unit", "Abono_Inicial",
    "Medio_Pago", "Estado", "Total", "Precio_Lista", "Descuento", "Pagos_Post",
    "Saldo", "Costo_Std", "Margen_Bruto", "Año", "Mes", "MesKey", "Trim", "Semana",
    "N_Compra_Cli", "Cliente_Nuevo", "RankBase", "Chequeo", "Estado_Fila",
]  # fmt: skip
PAGOS = ["Fecha", "Venta_ID", "Celular (auto)", "Monto", "Medio_Pago", "Nota", "MesKey"]
PRODUCCION = [
    "Fecha", "Lote", "Producto", "Cantidad", "Tiempo_Total_Min", "Responsable",
    "Tiempo_x_Und", "Gramos_Plata", "Costo_MO", "MesKey", "Nota",
]  # fmt: skip
AHORA = datetime(2026, 9, 19, 15, tzinfo=UTC)


def _hoja_del_erp():
    """Como el ERP de verdad: una venta vieja escrita a mano y filas vacías que
    ya traen fórmulas (por eso «añadir al final» escribiría en la fila 2004)."""
    formula = '=IF($B5="","",$J5*$K5)'
    ventas = [["💰 VENTAS"], ["Escribe solo en amarillo"], VENTAS]
    ventas.append(["V0142", "2026-03-31", "Anillos 1 huella", "3000000000"] + [""] * 27)
    ventas += [[""] * 14 + [formula] for _ in range(5)]
    return HojaEnMemoria(
        {
            "Ventas": ventas,
            "Pagos": [["💵 PAGOS"], [""], PAGOS] + [[""] * 2 + ["=auto"]] * 3,
            "Produccion": [["🔧"], [""], PRODUCCION] + [[""] * 6 + ["=x"]] * 3,
        }
    )


def _pedido(estado: str, **kw) -> Order:
    diseno = Personalizacion(
        talla=7,
        huellitas=[Huellita(corazon=C.NEGRO, dedos=C.NEGRO)],
        grabados=["Rocky", "Luna"],
    )
    base = dict(
        id="p1",
        codigo="PED-2026-0417",
        customer_id="c1",
        estado=estado,
        items=[
            OrderItem(
                sku="ANI-HUE-1",
                nombre="Anillo huellita x1",
                cantidad=1,
                precio_unitario_cop=200_000,
                personalizacion=diseno,
            )
        ],
        total_cop=200_000,
        anticipo_cop=60_000,
        saldo_cop=140_000,
        anticipo_pagado_cop=60_000,
        envio=DatosDeEnvio(
            nombre="Laura Gómez",
            ciudad="Bogotá",
            direccion="Cl 45 #12-30",
            telefono="573001112233",
        ),
        created_at=AHORA,
        updated_at=AHORA,
    )
    return Order(**{**base, **kw})


def _fila(hoja, nombre, numero):
    return hoja.hojas[nombre][numero - 1]


class TestLoQueEscribe:
    def test_una_venta_nueva_con_el_formato_del_erp(self):
        hoja = _hoja_del_erp()
        r = ReconciliadorDelErp(hoja).reconciliar([_pedido("EN_PRODUCCION")], {})
        assert r.ventas_nuevas == 1
        fila = _fila(hoja, "Ventas", 5)  # la primera vacía, no la 2004
        v = dict(zip([*VENTAS, erp.REFERENCIA], fila, strict=False))
        assert v["Venta_ID"] == "V0143", "sigue la numeración del ERP"
        assert v["Producto"] == "Anillos 1 huella"
        assert v["Celular_Cliente"] == "'3001112233", "como texto, igual que los viejos"
        assert v["Talla"] == "TALLA 7"
        assert v["Color_Detalle"] == "♡ Negro / Dedos: Negro"
        assert v["Grabado"] == "Rocky♡Luna"
        assert v["Precio_Unit"] == 200_000 and v["Abono_Inicial"] == 60_000
        assert v["Estado"] == "Producción"
        assert v[erp.REFERENCIA] == "PED-2026-0417", "auditable: del ERP al pedido"
        assert _fila(hoja, "Ventas", 3)[31] == erp.REFERENCIA, "se crea la columna"
        assert fila[14].startswith("="), "la fórmula de la fila no se toca"

    def test_un_prospecto_sin_abono_no_es_venta(self):
        hoja = _hoja_del_erp()
        r = ReconciliadorDelErp(hoja).reconciliar(
            [_pedido("ESPERANDO_ANTICIPO", anticipo_pagado_cop=0)], {}
        )
        assert r.ventas_nuevas == 0

    def test_correrlo_dos_veces_no_duplica_nada(self):
        hoja = _hoja_del_erp()
        rec = ReconciliadorDelErp(hoja)
        rec.reconciliar([_pedido("EN_PRODUCCION")], {})
        antes = len(hoja.escrituras)
        r = rec.reconciliar([_pedido("EN_PRODUCCION")], {})
        assert not r.algo and len(hoja.escrituras) == antes

    def test_el_estado_sigue_al_pedido_y_el_saldo_va_a_pagos(self):
        hoja = _hoja_del_erp()
        rec = ReconciliadorDelErp(hoja)
        rec.reconciliar([_pedido("EN_PRODUCCION")], {})
        despachado = _pedido("DESPACHADO", saldo_pagado_cop=140_000)
        r = rec.reconciliar([despachado], {})
        assert r.ventas_actualizadas == 1 and r.pagos_nuevos == 1
        assert r.produccion_nueva == 1
        assert _fila(hoja, "Ventas", 5)[13] == "Enviado"
        pago = dict(zip(PAGOS, _fila(hoja, "Pagos", 4), strict=False))
        assert pago["Venta_ID"] == "V0143" and pago["Monto"] == 140_000
        assert "PED-2026-0417" in pago["Nota"]
        lote = dict(zip(PRODUCCION, _fila(hoja, "Produccion", 4), strict=False))
        assert lote["Lote"] == "PED-2026-0417" and lote["Producto"] == "Anillos 1 huella"
        assert lote["Tiempo_Total_Min"] == erp.MINUTOS_POR_UNIDAD

    def test_dos_huellitas_llevan_el_detalle_de_cada_una(self):
        diseno = Personalizacion(
            talla=6.5,
            huellitas=[
                Huellita(corazon=C.ROSADO, dedos=C.BLANCO),
                Huellita(corazon=C.NEGRO, dedos=C.NEGRO),
            ],
            grabados=["Kira"],
        )
        p = _pedido("ANTICIPO_PAGADO")
        p.items[0].personalizacion = diseno
        hoja = _hoja_del_erp()
        ReconciliadorDelErp(hoja).reconciliar([p], {})
        v = dict(zip(VENTAS, _fila(hoja, "Ventas", 5), strict=False))
        assert v["Producto"] == "Anillos 2 huella"
        assert v["Color_Detalle"].startswith("HUELLA 1: ♡ Rosa / Dedos: Blanco |")
        assert v["Talla"] == "TALLA 6.5" and v["Estado"] == "Pedido"


@pytest.mark.parametrize(
    ("estado", "esperado"),
    [
        ("ANTICIPO_PAGADO", "Pedido"),
        ("EN_PRODUCCION", "Producción"),
        ("ESPERANDO_SALDO", "Pendiente pago"),
        ("DESPACHADO", "Enviado"),
        ("ENTREGADO", "Entregado"),
        ("CANCELADO", "Cancelado"),
    ],
)
def test_el_estado_usa_la_lista_del_erp(estado, esperado):
    assert erp.ESTADO_ERP[erp.S(estado)] == esperado


def test_una_credencial_oauth_se_rechaza_con_un_motivo_claro(tmp_path):
    """19/09: se descargó la credencial «OAuth / app de escritorio» (caduca y es
    para personas) en vez de la llave de una cuenta de servicio."""
    import json

    from app.adapters.erp.sheets import SheetsDeGoogle

    oauth = tmp_path / "erp.json"
    oauth.write_text(json.dumps({"installed": {"client_id": "x"}}), encoding="utf-8")
    with pytest.raises(ValueError, match="cuenta de servicio"):
        SheetsDeGoogle("id", oauth)
