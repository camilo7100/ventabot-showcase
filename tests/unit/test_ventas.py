"""La base de ventas y su Excel (ADR 0015).

Lo que tiene que ser verdad pase lo que pase:
  · cada pedido es una fila con su ID que no cambia;
  · lo que Camilo escribe en sus columnas llega a la base y nunca se pisa;
  · lo que se toca en una columna del sistema se corrige en la siguiente vuelta;
  · si el Excel está abierto, lo de Camilo igual queda guardado.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

openpyxl = pytest.importorskip("openpyxl")

from app.adapters.excel.libro_ventas import LibroDeVentas  # noqa: E402
from app.adapters.repositories.sqlite_store import (  # noqa: E402
    SqliteCustomerRepository,
    SqliteDB,
    SqliteOrderRepository,
)
from app.adapters.repositories.ventas import BaseDeVentas  # noqa: E402
from app.domain.models import Channel, Customer, Order, OrderItem  # noqa: E402
from app.domain.personalizacion import ColorCircon as C  # noqa: E402
from app.domain.personalizacion import Huellita, Personalizacion  # noqa: E402
from app.domain.ventas import COLUMNAS_VENTAS, fila_de_venta  # noqa: E402
from app.workers.ventas import SincronizadorDeVentas, sincronizar  # noqa: E402

TITULO = {c.clave: c.titulo for c in COLUMNAS_VENTAS}


@pytest.fixture
def mundo(tmp_path):
    db = SqliteDB(tmp_path / "ventas.db")
    clientas = SqliteCustomerRepository(db)
    clientas.upsert(
        Customer(id="c1", channel=Channel.WHATSAPP, channel_user_id="573001112233")
    )
    pedidos = SqliteOrderRepository(db)
    pedido = pedidos.create(
        Order(
            codigo="PED-2026-0417",
            customer_id="c1",
            estado="EN_REVISION_PAGO",
            total_cop=200_000,
            anticipo_cop=60_000,
            saldo_cop=140_000,
            items=[
                OrderItem(
                    sku="ANI-HUE-1",
                    nombre="Anillo huellita x1",
                    cantidad=1,
                    precio_unitario_cop=200_000,
                    personalizacion=Personalizacion(
                        talla=7,
                        huellitas=[Huellita(corazon=C.LILA, dedos=C.MORADO)],
                        grabados=["Rocky ♡"],
                    ),
                )
            ],
        ),
        idem_key="t1",
    )
    base = BaseDeVentas(db)
    libro = LibroDeVentas(tmp_path / "Ventas.xlsx")
    return base, libro, pedido


def _celda(ruta, id_venta, clave):
    hoja = openpyxl.load_workbook(ruta)["Ventas"]
    titulos = [c.value for c in hoja[1]]
    col = titulos.index(TITULO[clave]) + 1
    idc = titulos.index(TITULO["id_venta"]) + 1
    for fila in range(2, hoja.max_row + 1):
        if hoja.cell(fila, idc).value == id_venta:
            return hoja, fila, col
    raise AssertionError("no está la fila")


def _escribir(ruta, id_venta, clave, valor):
    libro = openpyxl.load_workbook(ruta)
    hoja = libro["Ventas"]
    titulos = [c.value for c in hoja[1]]
    col = titulos.index(TITULO[clave]) + 1
    idc = titulos.index(TITULO["id_venta"]) + 1
    for fila in range(2, hoja.max_row + 1):
        if hoja.cell(fila, idc).value == id_venta:
            hoja.cell(fila, col).value = valor
    libro.save(ruta)


class TestFila:
    def test_una_venta_con_abono_reportado_cuenta_como_venta(self, mundo):
        _, _, pedido = mundo
        fila = fila_de_venta(pedido, None, {})
        assert fila["es_venta"] == "SÍ"
        assert fila["colores"] == "H1: lila/morado"
        assert fila["grabado"] == "Rocky ♡"
        assert fila["precio"] == 200_000


class TestSincronizar:
    def test_crea_el_excel_con_sus_cuatro_hojas(self, mundo):
        base, libro, pedido = mundo
        informe = sincronizar(base, libro)
        assert informe.escrito and informe.ventas == 1 and informe.clientas == 1
        assert openpyxl.load_workbook(libro.ruta).sheetnames == [
            "Ventas",
            "Clientas",
            "Diccionario",
            "Registro",
        ]
        hoja, fila, col = _celda(libro.ruta, pedido.id, "codigo")
        assert hoja.cell(fila, col).value == "PED-2026-0417"

    def test_lo_que_camilo_escribe_llega_a_la_base_y_no_se_pisa(self, mundo):
        base, libro, pedido = mundo
        sincronizar(base, libro)
        _escribir(libro.ruta, pedido.id, "costo_material", 85000)
        _escribir(libro.ruta, pedido.id, "fuente", "Instagram")

        informe = sincronizar(base, libro)
        assert informe.anotaciones_guardadas == 2
        assert base.anotaciones()[pedido.id] == {
            "costo_material": "85000",
            "fuente": "Instagram",
        }
        hoja, fila, col = _celda(libro.ruta, pedido.id, "fuente")
        assert hoja.cell(fila, col).value == "Instagram", "sigue en el Excel reescrito"

        informe = sincronizar(base, libro)
        assert informe.anotaciones_guardadas == 0, "sin cambios no hay escrituras"

    def test_tocar_una_columna_del_sistema_se_corrige_sola(self, mundo):
        base, libro, pedido = mundo
        sincronizar(base, libro)
        _escribir(libro.ruta, pedido.id, "precio", 1)
        sincronizar(base, libro)
        hoja, fila, col = _celda(libro.ruta, pedido.id, "precio")
        assert hoja.cell(fila, col).value == 200_000

    def test_las_columnas_del_sistema_quedan_bloqueadas_y_las_de_camilo_no(self, mundo):
        base, libro, pedido = mundo
        sincronizar(base, libro)
        hoja, fila, col_precio = _celda(libro.ruta, pedido.id, "precio")
        _, _, col_notas = _celda(libro.ruta, pedido.id, "notas_camilo")
        assert hoja.protection.sheet
        assert hoja.cell(fila, col_precio).protection.locked
        assert not hoja.cell(fila, col_notas).protection.locked

    def test_con_el_excel_abierto_lo_de_camilo_igual_queda_guardado(
        self, mundo, monkeypatch
    ):
        base, libro, pedido = mundo
        sincronizar(base, libro)
        _escribir(libro.ruta, pedido.id, "etiqueta", "regalo")

        def abierto(*_):
            raise PermissionError("el archivo está abierto en Excel")

        monkeypatch.setattr("app.adapters.excel.libro_ventas.os.replace", abierto)
        informe = sincronizar(base, libro)
        assert not informe.escrito and "abierto" in informe.detalle
        assert base.anotaciones()[pedido.id]["etiqueta"] == "regalo"

    def test_borrar_una_anotacion_queda_en_la_bitacora(self, mundo):
        base, libro, pedido = mundo
        sincronizar(base, libro)
        _escribir(libro.ruta, pedido.id, "notas_camilo", "llamar el lunes")
        sincronizar(base, libro)
        _escribir(libro.ruta, pedido.id, "notas_camilo", None)
        sincronizar(base, libro)
        assert "notas_camilo" not in base.anotaciones().get(pedido.id, {})
        log = base._db.consultar(
            "SELECT antes, despues FROM ventas_anotaciones_log ORDER BY id"
        )
        assert [(f["antes"], f["despues"]) for f in log] == [
            ("", "llamar el lunes"),
            ("llamar el lunes", ""),
        ]


class TestVueltaAutomatica:
    def test_sin_cambios_no_toca_el_disco(self, mundo):
        base, libro, _ = mundo
        vuelta = SincronizadorDeVentas(base, libro, intervalo_s=1)
        assert vuelta.una_vuelta() is not None
        assert vuelta.una_vuelta() is None

    def test_las_fechas_van_en_hora_de_colombia(self, mundo):
        _, libro, pedido = mundo
        pedido = pedido.model_copy(
            update={"created_at": datetime(2026, 9, 17, 3, 0, tzinfo=UTC)}
        )
        fila = fila_de_venta(pedido, None, {})
        libro.escribir([fila], [], [])
        hoja, f, col = _celda(libro.ruta, pedido.id, "fecha_pedido")
        assert hoja.cell(f, col).value == datetime(2026, 9, 16, 22, 0)  # noqa: DTZ001 - Excel no guarda zona
