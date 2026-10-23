"""`vb reiniciar --numeros`: borra SOLO los números de prueba (27/09/2026).

Lo usa REINICIAR-PRUEBAS.cmd sobre la base de PRODUCCIÓN, donde también hay
clientas de verdad. Lo único que no se puede equivocar: borrar a una clienta.
"""

from __future__ import annotations

import sqlite3

import pytest

from app.domain.decisiones import huella_conversacion
from scripts.reiniciar_chats import (
    _borrar_numeros,
    _contar_numeros,
    _que_borrar,
    normalizar,
)

PRUEBA = "573001110002"
CLIENTA = "573009998877"


@pytest.fixture
def base(tmp_path):
    cx = sqlite3.connect(str(tmp_path / "t.db"))
    cx.executescript(
        """
        CREATE TABLE conversations (conversation_id TEXT, channel_user_id TEXT);
        CREATE TABLE messages (conversation_id TEXT, texto TEXT);
        CREATE TABLE conv_contexto (conversation_id TEXT);
        CREATE TABLE customers (id TEXT, channel_user_id TEXT);
        CREATE TABLE orders (id TEXT, customer_id TEXT);
        CREATE TABLE order_events (order_id TEXT);
        CREATE TABLE decisiones (conversacion TEXT);
        CREATE TABLE outbox (destinatario TEXT);
        """
    )
    for numero, cliente, pedido in (
        (PRUEBA, "c-prueba", "o-prueba"),
        (CLIENTA, "c-real", "o-real"),
    ):
        conv = f"wa:{numero}"
        cx.execute("INSERT INTO conversations VALUES (?, ?)", (conv, numero))
        cx.execute("INSERT INTO messages VALUES (?, 'hola')", (conv,))
        cx.execute("INSERT INTO conv_contexto VALUES (?)", (conv,))
        cx.execute("INSERT INTO customers VALUES (?, ?)", (cliente, numero))
        cx.execute("INSERT INTO orders VALUES (?, ?)", (pedido, cliente))
        cx.execute("INSERT INTO order_events VALUES (?)", (pedido,))
        cx.execute("INSERT INTO decisiones VALUES (?)", (huella_conversacion(conv),))
        cx.execute("INSERT INTO outbox VALUES (?)", (numero,))
    cx.commit()
    yield cx
    cx.close()


def _todo(cx, tabla):
    return cx.execute(f"SELECT COUNT(*) FROM {tabla}").fetchone()[0]


class TestNormalizar:
    @pytest.mark.parametrize(
        "escrito", ["3001110002", "300 111 0002", "+57 300 111 0002", "573001110002"]
    )
    def test_como_sea_que_se_escriba(self, escrito):
        assert normalizar(escrito) == PRUEBA


class TestSoloEsosNumeros:
    def test_borra_todo_lo_del_numero_de_prueba(self, base):
        plan = _que_borrar(base, [PRUEBA])
        _borrar_numeros(base, plan)
        for tabla in ("conversations", "messages", "conv_contexto", "customers"):
            filas = base.execute(f"SELECT * FROM {tabla}").fetchall()
            assert all(PRUEBA not in str(f) for f in filas), f"quedó {tabla}"
        assert base.execute("SELECT id FROM orders").fetchall() == [("o-real",)]

    def test_no_toca_a_la_clienta_de_verdad(self, base):
        _borrar_numeros(base, _que_borrar(base, [PRUEBA]))
        for tabla in (
            "conversations",
            "messages",
            "conv_contexto",
            "customers",
            "orders",
            "order_events",
            "decisiones",
            "outbox",
        ):
            assert _todo(base, tabla) == 1, f"se borró de más en {tabla}"
        (conv,) = base.execute("SELECT conversation_id FROM conversations").fetchone()
        assert conv == f"wa:{CLIENTA}"

    def test_cuenta_antes_de_borrar(self, base):
        cuenta = _contar_numeros(base, _que_borrar(base, [PRUEBA]))
        assert cuenta["messages"] == 1 and cuenta["orders"] == 1

    def test_un_numero_que_no_existe_no_borra_nada(self, base):
        _borrar_numeros(base, _que_borrar(base, ["573000000000"]))
        assert _todo(base, "conversations") == 2


class TestAntesDePasarAReal:
    """`vb reiniciar --pedidos` es lo que se corre justo antes de atender a
    clientas de verdad (29/09): no puede quedar nada de las pruebas."""

    def test_el_analisis_se_rehace_con_lo_que_queda(self, tmp_path):
        from app.adapters.repositories.analitica_sqlite import SqliteAnalitica
        from app.adapters.repositories.sqlite_store import SqliteDB
        from scripts.reiniciar_chats import rehacer_analitica

        ruta = tmp_path / "t.db"
        db = SqliteDB(ruta)
        SqliteAnalitica(db)  # crea la tabla
        # Un pedido de prueba que ya no existe en `orders`, pero sí en el análisis.
        db.ejecutar("INSERT INTO pedidos_analitica (codigo) VALUES ('PED-PRUEBA')")
        assert rehacer_analitica(ruta) == 0
        assert not db.consultar("SELECT codigo FROM pedidos_analitica")

    def test_las_notas_del_excel_se_van_con_los_pedidos(self):
        from scripts.reiniciar_chats import TABLAS_DE_PEDIDO

        for tabla in ("ventas_anotaciones", "ventas_anotaciones_log", "orders"):
            assert tabla in TABLAS_DE_PEDIDO

    def test_las_fotos_se_apartan_y_las_previas_se_borran(self, tmp_path):
        from types import SimpleNamespace

        from scripts.reiniciar_chats import apartar_medios

        fotos, previas = tmp_path / "fotos", tmp_path / "renders"
        fotos.mkdir()
        previas.mkdir()
        (fotos / "regla.jpg").write_bytes(b"x")
        (previas / "huellita.png").write_bytes(b"x")
        excel = tmp_path / "Ventas.xlsx"
        excel.write_bytes(b"x")
        s = SimpleNamespace(fotos_dir=fotos, renders_dir=previas, ventas_excel=excel)
        respaldos = tmp_path / "respaldos"

        assert apartar_medios(s, respaldos) == (1, 1)
        assert not any(fotos.iterdir()) and not any(previas.iterdir())
        apartadas = list(respaldos.glob("fotos-de-prueba-*/regla.jpg"))
        assert len(apartadas) == 1, "la foto se aparta, no se borra"
        assert not excel.exists()
