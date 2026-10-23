"""El tablero de métricas: los números tienen que decir la verdad.

Un tablero que miente es peor que no tener tablero: se toman decisiones con él.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app.adapters.repositories.sqlite_store import SqliteDB
from app.adapters.repositories.tablero import tablero
from app.infra import container as contenedor
from app.infra.settings import Settings

AHORA = datetime.now(UTC)


def _iso(minutos_atras: float) -> str:
    return (AHORA - timedelta(minutes=minutos_atras)).isoformat()


def _mensaje(db: SqliteDB, conv: str, direccion: str, minutos_atras: float) -> None:
    db._con.execute(
        "INSERT INTO messages (conversation_id, direccion, channel, texto, created_at) "
        "VALUES (?, ?, 'whatsapp', 'x', ?)",
        (conv, direccion, _iso(minutos_atras)),
    )


def _pedido(db: SqliteDB, codigo: str, estado: str, total: int, minutos_atras: float):
    db._con.execute(
        "INSERT INTO orders (id, codigo, customer_id, estado, payload, created_at, "
        "updated_at) VALUES (?, ?, 'c', ?, ?, ?, ?)",
        (
            codigo,
            codigo,
            estado,
            json.dumps({"total_cop": total}),
            _iso(minutos_atras),
            _iso(minutos_atras),
        ),
    )


@pytest.fixture
def db(tmp_path):
    base = SqliteDB(tmp_path / "t.db")
    yield base
    base.cerrar()


class TestNumeros:
    def test_sin_nada_todo_en_cero(self, db):
        t = tablero(db, _iso(60))
        assert t["conversaciones"] == 0 and t["pagados"] == 0
        assert t["respuesta_p50_s"] is None and t["conversion_pct"] == 0.0

    def test_cuenta_conversaciones_y_clientas_nuevas(self, db):
        _mensaje(db, "wa:1", "IN", 30)
        _mensaje(db, "wa:1", "OUT", 29.9)
        _mensaje(db, "wa:2", "IN", 60 * 24 * 3)  # vieja: escribió hace 3 días
        _mensaje(db, "wa:2", "IN", 10)
        t = tablero(db, _iso(60))
        assert t["conversaciones"] == 2
        assert t["nuevas"] == 1  # wa:2 ya había escrito antes del periodo
        assert (t["recibidos"], t["enviados"]) == (2, 1)

    def test_el_tiempo_de_respuesta_cuenta_desde_el_primer_mensaje(self, db):
        """Si la clienta manda tres mensajes seguidos, esperó desde el primero."""
        _mensaje(db, "wa:1", "IN", 10)
        _mensaje(db, "wa:1", "IN", 9.5)
        _mensaje(db, "wa:1", "OUT", 9)  # 60 s después del primero
        assert tablero(db, _iso(60))["respuesta_p50_s"] == 60.0

    def test_una_vuelta_al_dia_siguiente_no_es_tiempo_de_respuesta(self, db):
        _mensaje(db, "wa:1", "IN", 600)
        _mensaje(db, "wa:1", "OUT", 60)  # 9 horas después: otra charla
        assert tablero(db, _iso(700))["respuesta_p50_s"] is None

    def test_ventas_solo_cuentan_los_pagados(self, db):
        _mensaje(db, "wa:1", "IN", 30)
        _mensaje(db, "wa:2", "IN", 30)
        _pedido(db, "PED-1", "ESPERANDO_ANTICIPO", 200_000, 20)
        _pedido(db, "PED-2", "EN_PRODUCCION", 250_000, 20)
        _pedido(db, "PED-3", "CANCELADO", 300_000, 20)
        t = tablero(db, _iso(60))
        assert (t["pedidos"], t["pagados"], t["ventas_cop"]) == (3, 1, 250_000)
        assert t["conversion_pct"] == 50.0

    def test_lo_de_antes_del_periodo_no_entra(self, db):
        _pedido(db, "PED-1", "ENTREGADO", 200_000, 60 * 24 * 10)
        assert tablero(db, _iso(60))["ventas_cop"] == 0


class TestLaPagina:
    @pytest.fixture
    def cliente(self, tmp_path, monkeypatch):
        s = Settings(
            sqlite_path=tmp_path / "p.db",
            repository_backend="sqlite",
            llm_backend="fake",
            payment_backend="fake",
            channel_backend="console",
            panel_token="secreto-del-panel",
            ventas_excel=tmp_path / "v.xlsx",
        )
        monkeypatch.setattr(contenedor, "_singleton", contenedor.build_container(s))
        from app.api.main import app

        with TestClient(app) as tc:
            yield tc

    def test_sin_token_no_se_ve(self, cliente):
        assert cliente.get("/panel/metricas?token=otro").status_code in (403, 404)

    @pytest.mark.parametrize("periodo", ["hoy", "7", "30", "cualquiera"])
    def test_se_ve_en_cada_periodo(self, cliente, periodo):
        r = cliente.get(f"/panel/metricas?token=secreto-del-panel&periodo={periodo}")
        assert r.status_code == 200
        assert "El negocio" in r.text and "El bot" in r.text
