"""Todo llega a Chatwoot, aunque sea horas después (07/10).

Chatwoot es la ÚNICA forma en que Camilo y Lía ven la charla y contestan. Si
Chatwoot se cae, si el bot se reinicia o si quien mandó el mensaje fue un script
que ya terminó, la copia espera en la base de datos y llega cuando se pueda, en
orden. Solo se aparta lo que Chatwoot RECHAZA por sí mismo, para que no tape lo
que viene detrás.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta

import httpx
import pytest

import app.adapters.crm.chatwoot as cw
from app.adapters.crm.chatwoot import ChatwootCRM, _cuando_paso
from app.adapters.crm.cola import ColaEnSqlite
from app.adapters.repositories.sqlite_store import SqliteDB

CONV = "wa:573000000001"


@pytest.fixture(autouse=True)
def _rapido(monkeypatch):
    """Las pausas de verdad son de minutos; aquí, milisegundos."""
    monkeypatch.setattr(cw, "REINTENTOS_S", (0.01,))
    monkeypatch.setattr(cw, "MIRAR_S", 0.05)
    monkeypatch.setattr(cw, "ESPERA_SI_CAIDO_S", 0.3)


@pytest.fixture
def base(tmp_path):
    return tmp_path / "ventabot.db"


def _crm(base, hacer, avisos=None) -> ChatwootCRM:
    crm = ChatwootCRM(
        base_url="http://127.0.0.1:9",
        token="x",
        account_id=1,
        inbox_id=1,
        cola=ColaEnSqlite(SqliteDB(base)),
        avisar=(lambda *a: avisos.append(a)) if avisos is not None else None,
    )
    crm._hacer = hacer  # type: ignore[method-assign]
    return crm


def _esperar(condicion, tope_s: float = 5.0) -> bool:
    fin = time.monotonic() + tope_s
    while time.monotonic() < fin:
        if condicion():
            return True
        time.sleep(0.02)
    return False


def _caido(tarea, creada=None):
    raise httpx.ConnectError("Chatwoot no responde")


class TestLaCola:
    def test_en_orden_y_una_sola_vez(self, base):
        cola = ColaEnSqlite(SqliteDB(base))
        for i in range(3):
            cola.poner(["copia", CONV, f"m{i}"])
        vistas = []
        while (p := cola.tomar()) is not None:
            vistas.append(p.tarea[2])
            cola.hecha(p.id)
        assert vistas == ["m0", "m1", "m2"]

    def test_lo_reservado_por_otro_no_se_toca(self, base):
        """El servidor y un script mirando la misma cola: nada sale repetido."""
        uno, otro = ColaEnSqlite(SqliteDB(base)), ColaEnSqlite(SqliteDB(base))
        uno.poner(["copia", CONV, "hola"])
        uno.poner(["copia", CONV, "segundo"])
        assert uno.tomar() is not None
        # Ni la misma, ni la siguiente: el orden se respeta esperando.
        assert otro.tomar() is None

    def test_si_falla_la_retoma_cualquiera(self, base):
        uno, otro = ColaEnSqlite(SqliteDB(base)), ColaEnSqlite(SqliteDB(base))
        uno.poner(["copia", CONV, "hola"])
        p = uno.tomar()
        uno.fallo(p.id, "caído")
        q = otro.tomar()
        assert q is not None and q.id == p.id and q.intentos == 1

    def test_sobrevive_un_reinicio(self, base):
        ColaEnSqlite(SqliteDB(base)).poner(["copia", CONV, "hola"])
        despues = ColaEnSqlite(SqliteDB(base))
        assert despues.pendientes() == 1
        assert despues.tomar().tarea == ["copia", CONV, "hola"]


class TestChatwootCaidoPorHoras:
    def test_se_reintenta_sin_limite(self, base):
        crm = _crm(base, _caido)
        try:
            crm.registrar(CONV, "la cadena", entrante=False)
            assert _esperar(lambda: _intentos(base) >= 30), "dejó de intentar"
            assert crm.pendientes() == 1, "la copia no puede perderse"
        finally:
            crm.cerrar()

    def test_cuando_vuelve_llega_todo_en_orden(self, base):
        hechas: list[str] = []
        caido = {"si": True}

        def hacer(tarea, creada=None):
            if caido["si"]:
                raise httpx.ConnectError("caído")
            hechas.append(tarea[2])

        crm = _crm(base, hacer)
        try:
            for texto in ("uno", "dos", "tres"):
                crm.registrar(CONV, texto, entrante=True)
            assert _esperar(lambda: _intentos(base) >= 5)
            caido["si"] = False
            assert _esperar(lambda: crm.pendientes() == 0)
            assert hechas == ["uno", "dos", "tres"]
        finally:
            crm.cerrar()

    def test_lo_que_dejo_un_script_lo_copia_el_servidor(self, base):
        """El script encola con Chatwoot caído y termina; el servidor lo copia."""
        script = _crm(base, _caido)
        script.registrar(CONV, "info de la cadena", entrante=False)
        assert _esperar(lambda: _intentos(base) >= 1)
        assert not script.vaciar(5), "con Chatwoot caído no se queda esperando"
        script._al_salir()

        hechas: list[str] = []
        servidor = _crm(base, lambda tarea, creada=None: hechas.append(tarea[2]))
        try:
            assert _esperar(lambda: hechas == ["info de la cadena"])
            assert _esperar(lambda: servidor.pendientes() == 0)
        finally:
            servidor.cerrar()

    def test_se_avisa_si_lleva_rato_caido_y_cuando_vuelve(self, base, monkeypatch):
        monkeypatch.setattr(cw, "AVISAR_TRAS", timedelta(seconds=0.1))
        avisos: list = []
        caido = {"si": True}

        def hacer(tarea, creada=None):
            if caido["si"]:
                raise httpx.ConnectError("caído")

        crm = _crm(base, hacer, avisos)
        try:
            crm.registrar(CONV, "hola", entrante=True)
            assert _esperar(lambda: any("no está recibiendo" in a[0] for a in avisos))
            caido["si"] = False
            assert _esperar(lambda: any("volvió" in a[0] for a in avisos))
            assert len([a for a in avisos if "no está recibiendo" in a[0]]) == 1
        finally:
            crm.cerrar()


class TestLoQueChatwootRechaza:
    def test_se_aparta_y_no_tapa_lo_demas(self, base):
        hechas: list[str] = []
        avisos: list = []

        def hacer(tarea, creada=None):
            if tarea[2] == "malo":
                pedido = httpx.Request("POST", "http://x")
                raise httpx.HTTPStatusError(
                    "422", request=pedido, response=httpx.Response(422, request=pedido)
                )
            hechas.append(tarea[2])

        crm = _crm(base, hacer, avisos)
        try:
            crm.registrar(CONV, "malo", entrante=True)
            crm.registrar(CONV, "bueno", entrante=True)
            assert crm.vaciar(5)
            assert hechas == ["bueno"]
            filas = SqliteDB(base).consultar(
                "SELECT apartada, intentos FROM chatwoot_pendientes"
            )
            assert [(f["apartada"], f["intentos"]) for f in filas] == [
                (1, cw.INTENTOS_SI_LA_RECHAZA)
            ], "se guarda para mirarla, no se borra"
            assert any("no entró" in a[0] for a in avisos)
        finally:
            crm.cerrar()

    def test_un_500_no_se_aparta_nunca(self):
        pedido = httpx.Request("POST", "http://x")
        caido = httpx.HTTPStatusError(
            "502", request=pedido, response=httpx.Response(502, request=pedido)
        )
        assert cw._cuantas_veces(caido) is None
        assert cw._cuantas_veces(httpx.ConnectError("x")) is None
        assert cw._cuantas_veces(httpx.ReadTimeout("x")) is None


class TestLlegaTarde:
    def test_dice_a_que_hora_paso(self):
        creada = datetime(2026, 10, 7, 19, 32, tzinfo=UTC)  # 2:32 p. m. en Colombia
        assert _cuando_paso(creada) == "🕓 07/10 2:32 p. m."

    def test_la_copia_tardia_lleva_la_hora_y_se_reconoce_su_eco(self, monkeypatch):
        crm = ChatwootCRM("http://127.0.0.1:9", "x", 1, 1)
        enviados: list[dict] = []
        monkeypatch.setattr(crm, "_asegurar", lambda conv, nombre: (1, 2))
        monkeypatch.setattr(
            crm,
            "_pedir",
            lambda metodo, ruta, cuerpo=None, token=None: enviados.append(cuerpo),
        )
        try:
            hace_rato = datetime.now(UTC) - timedelta(hours=3)
            crm._hacer(
                ["copia", CONV, "Te cuento de la cadena", False, "", [], {}, []],
                hace_rato,
            )
            contenido = enviados[0]["content"]
            assert contenido.startswith("🕓 ") and contenido.endswith(
                "· Te cuento de la cadena"
            )
            # El webhook devuelve la copia con la hora: sigue siendo del bot.
            assert crm.es_eco(CONV, contenido)
        finally:
            crm.cerrar()

    def test_la_que_llega_a_tiempo_va_tal_cual(self, monkeypatch):
        crm = ChatwootCRM("http://127.0.0.1:9", "x", 1, 1)
        enviados: list[dict] = []
        monkeypatch.setattr(crm, "_asegurar", lambda conv, nombre: (1, 2))
        monkeypatch.setattr(
            crm,
            "_pedir",
            lambda metodo, ruta, cuerpo=None, token=None: enviados.append(cuerpo),
        )
        try:
            crm._hacer(["copia", CONV, "hola", True, "", [], {}, []], datetime.now(UTC))
            assert enviados[0]["content"] == "hola"
        finally:
            crm.cerrar()

    def test_un_mensaje_del_bot_deja_una_sola_marca_de_eco(self, monkeypatch):
        """Si quedaran dos, la segunda se tragaría un mensaje igual de Lía."""
        crm = ChatwootCRM("http://127.0.0.1:9", "x", 1, 1)
        monkeypatch.setattr(crm, "_asegurar", lambda conv, nombre: (1, 2))
        monkeypatch.setattr(crm, "_pedir", lambda *a, **kw: None)
        try:
            crm.registrar(CONV, "Listo 💜", entrante=False)
            crm._hacer(["copia", CONV, "Listo 💜", False, "", [], {}, []])
            assert crm.es_eco(CONV, "Listo 💜")
            assert not crm.es_eco(CONV, "Listo 💜")
        finally:
            crm.cerrar()


class TestTodoPasaPorLaBase:
    def test_el_seguimiento_se_guarda_y_se_rehace(self, base, monkeypatch):
        from app.domain.seguimiento import Seguimiento

        vistos: list = []
        crm = ChatwootCRM(
            "http://127.0.0.1:9", "x", 1, 1, cola=ColaEnSqlite(SqliteDB(base))
        )
        monkeypatch.setattr(crm, "_asegurar", lambda conv, nombre: (1, 2))
        monkeypatch.setattr(crm, "_etiquetas", lambda conversacion: [])
        monkeypatch.setattr(
            crm,
            "_pedir",
            lambda metodo, ruta, cuerpo=None, token=None: (
                vistos.append((metodo, ruta, cuerpo)) or {"status": "open"}
            ),
        )
        try:
            crm.seguimiento(
                CONV, Seguimiento("diseno", frozenset({"necesita-persona"})), {"a": 1}
            )
            assert crm.vaciar(5)
            etiquetas = [c for m, r, c in vistos if r.endswith("/labels")]
            assert etiquetas and "necesita-persona" in etiquetas[0]["labels"]
        finally:
            crm.cerrar()

    def test_el_contenedor_usa_la_cola_de_la_base(self):
        import inspect

        from app.infra import container

        assert "cola=ColaEnSqlite(db)" in inspect.getsource(container.build_container)


def _intentos(base) -> int:
    filas = SqliteDB(base).consultar(
        "SELECT COALESCE(SUM(intentos), 0) AS n FROM chatwoot_pendientes"
    )
    return int(filas[0]["n"])
