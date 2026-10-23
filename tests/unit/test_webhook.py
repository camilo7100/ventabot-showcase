"""Tests del transporte: webhook, firma, deduplicación, outbox y despachador.

Son la red de seguridad de la Fase 1. Corren sin red, sin Meta y sin servidor:
FastAPI trae un cliente de pruebas que llama a la app en memoria.

El más importante es `test_el_mismo_webhook_dos_veces_responde_una_sola_vez`.
Meta reintenta sus entregas; sin deduplicación el cliente recibe la misma
respuesta tres o cuatro veces y parece que el bot está roto.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time

import pytest
from fastapi.testclient import TestClient

import app.infra.container as contenedor
from app.adapters.repositories.sqlite_store import (
    SqliteConversaciones,
    SqliteDB,
    SqliteIdempotencyStore,
    SqliteOutbox,
)
from app.domain.models import Channel, OutboundMessage, conversation_id
from app.infra.settings import Settings

NUMERO = "573001112233"


def payload(texto: str, message_id: str) -> dict:
    """La misma forma que manda Meta. Copiada de su documentación."""
    return {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": "WABA",
                "changes": [
                    {
                        "field": "messages",
                        "value": {
                            "messaging_product": "whatsapp",
                            "metadata": {
                                "display_phone_number": "573000000000",
                                "phone_number_id": "TEST",
                            },
                            "contacts": [
                                {"profile": {"name": "Camilo"}, "wa_id": NUMERO}
                            ],
                            "messages": [
                                {
                                    "from": NUMERO,
                                    "id": message_id,
                                    "timestamp": str(int(time.time())),
                                    "type": "text",
                                    "text": {"body": texto},
                                }
                            ],
                        },
                    }
                ],
            }
        ],
    }


def firmar(cuerpo: bytes, secreto: str) -> str:
    return "sha256=" + hmac.new(secreto.encode(), cuerpo, hashlib.sha256).hexdigest()


@pytest.fixture
def cliente(tmp_path, monkeypatch):
    """App real, base de datos temporal, canal de consola."""
    s = Settings(
        sqlite_path=tmp_path / "test.db",
        repository_backend="memory",
        llm_backend="fake",
        payment_backend="fake",
        channel_backend="console",
        meta_app_secret="secreto-de-prueba",
        meta_verify_token="verify-de-prueba",
        dispatcher_interval_s=0.05,
    )
    c = contenedor.build_container(s)
    monkeypatch.setattr(contenedor, "_singleton", c)
    from app.api.main import app

    with TestClient(app) as tc:
        tc.contenedor = c
        tc.secreto = s.meta_app_secret
        yield tc
    c.cerrar()


def postear(cliente, texto: str, mid: str, *, secreto: str | None = None):
    cuerpo = json.dumps(payload(texto, mid)).encode()
    return cliente.post(
        "/webhook/whatsapp",
        content=cuerpo,
        headers={
            "Content-Type": "application/json",
            "X-Hub-Signature-256": firmar(cuerpo, secreto or cliente.secreto),
        },
    )


class TestHandshake:
    def test_con_el_token_correcto_devuelve_el_challenge(self, cliente):
        r = cliente.get(
            "/webhook/whatsapp",
            params={
                "hub.mode": "subscribe",
                "hub.verify_token": "verify-de-prueba",
                "hub.challenge": "123456",
            },
        )
        assert r.status_code == 200
        assert r.text == "123456"

    def test_con_un_token_falso_responde_403(self, cliente):
        """Sin esto, cualquiera podría registrar tu webhook."""
        r = cliente.get(
            "/webhook/whatsapp",
            params={
                "hub.mode": "subscribe",
                "hub.verify_token": "falso",
                "hub.challenge": "123456",
            },
        )
        assert r.status_code == 403


class TestFirma:
    def test_una_firma_valida_se_acepta(self, cliente):
        assert postear(cliente, "hola", "wamid.OK1").status_code == 200

    def test_una_firma_invalida_se_rechaza(self, cliente):
        r = postear(cliente, "hola", "wamid.MALA", secreto="otro-secreto")
        assert r.status_code == 403

    def test_sin_cabecera_de_firma_se_rechaza(self, cliente):
        r = cliente.post("/webhook/whatsapp", json=payload("hola", "wamid.SIN"))
        assert r.status_code == 403

    def test_si_el_cuerpo_cambia_un_byte_la_firma_deja_de_valer(self, cliente):
        """La firma va sobre los BYTES EXACTOS. Es lo que impide manipularlos."""
        cuerpo = json.dumps(payload("hola", "wamid.X")).encode()
        firma = firmar(cuerpo, cliente.secreto)
        alterado = cuerpo.replace(b"hola", b"holo")  # mismo largo, un byte distinto
        r = cliente.post(
            "/webhook/whatsapp",
            content=alterado,
            headers={"Content-Type": "application/json", "X-Hub-Signature-256": firma},
        )
        assert r.status_code == 403


class TestDeduplicacion:
    def test_el_mismo_webhook_dos_veces_responde_una_sola_vez(self, cliente):
        """EL test de la Fase 1. Meta reintenta; el cliente no puede notarlo."""
        r1 = postear(cliente, "hola", "wamid.DUP")
        r2 = postear(cliente, "hola", "wamid.DUP")
        r3 = postear(cliente, "hola", "wamid.DUP")
        assert r1.json()["encolados"] == 1
        assert r2.json()["encolados"] == 0
        assert r3.json()["encolados"] == 0
        assert all(r.status_code == 200 for r in (r1, r2, r3))

    def test_mensajes_distintos_si_pasan(self, cliente):
        assert postear(cliente, "hola", "wamid.A").json()["encolados"] == 1
        assert postear(cliente, "hola", "wamid.B").json()["encolados"] == 1

    def test_la_dedup_sobrevive_a_un_reinicio(self, tmp_path):
        """Si viviera en memoria, un reinicio dejaría pasar los duplicados."""
        ruta = tmp_path / "persistente.db"
        db1 = SqliteDB(ruta)
        assert SqliteIdempotencyStore(db1).mark_processed("whatsapp", "wamid.Z") is True
        db1.cerrar()
        db2 = SqliteDB(ruta)  # "reinicio"
        assert SqliteIdempotencyStore(db2).mark_processed("whatsapp", "wamid.Z") is False
        db2.cerrar()


class TestFlujoCompleto:
    def test_un_mensaje_produce_una_respuesta_en_la_outbox(self, cliente):
        postear(cliente, "hola buenas", "wamid.FLUJO")
        pendientes_o_enviados = cliente.contenedor.db.consultar("SELECT * FROM outbox")
        assert len(pendientes_o_enviados) == 1

    def test_la_respuesta_lleva_su_conversacion(self, cliente):
        postear(cliente, "hola", "wamid.CONV")
        fila = cliente.contenedor.db.consultar("SELECT payload FROM outbox")[0]
        m = OutboundMessage.model_validate_json(fila["payload"])
        assert m.conversation_id == conversation_id(Channel.WHATSAPP, NUMERO)

    def test_queda_registrado_en_el_historial(self, cliente):
        postear(cliente, "quiero 2 CAM-PRE-001", "wamid.HIST")
        hist = cliente.contenedor.conversaciones.historial(
            conversation_id(Channel.WHATSAPP, NUMERO)
        )
        assert hist and hist[0]["direccion"] == "IN"
        assert hist[0]["texto"] == "quiero 2 CAM-PRE-001"


class TestVentana24h:
    def test_un_mensaje_entrante_abre_la_ventana(self, tmp_path):
        db = SqliteDB(tmp_path / "v.db")
        conv = SqliteConversaciones(db)
        cid = conversation_id(Channel.WHATSAPP, NUMERO)
        assert conv.ventana_abierta(cid) is False
        conv.registrar_entrante(cid, "whatsapp", NUMERO, "wamid.1", "hola", {})
        assert conv.ventana_abierta(cid) is True
        db.cerrar()

    def test_cuenta_desde_que_ella_lo_escribio(self, tmp_path):
        """14/10: Meta reintentó mensajes de hace dos días; no abren la ventana,
        y uno viejo que llega tarde no cierra la que abrió uno nuevo."""
        import time

        db = SqliteDB(tmp_path / "v.db")
        conv = SqliteConversaciones(db)
        cid = conversation_id(Channel.WHATSAPP, NUMERO)
        hace_2_dias = {"timestamp": str(int(time.time()) - 48 * 3600)}
        conv.registrar_entrante(cid, "whatsapp", NUMERO, "wamid.1", "hola", hace_2_dias)
        assert conv.ventana_abierta(cid) is False
        conv.registrar_entrante(
            cid,
            "whatsapp",
            NUMERO,
            "wamid.2",
            "sigo",
            {"timestamp": str(int(time.time()))},
        )
        conv.registrar_entrante(cid, "whatsapp", NUMERO, "wamid.3", "viejo", hace_2_dias)
        assert conv.ventana_abierta(cid) is True
        db.cerrar()

    def test_el_prefijo_del_canal_es_estable(self):
        """Bug real: derivar el prefijo cortando el nombre daba "wh" en vez de
        "wa", y la ventana se buscaba con una clave inexistente."""
        assert conversation_id(Channel.WHATSAPP, "573001112233") == "wa:573001112233"
        assert conversation_id(Channel.INSTAGRAM, "17841400000") == "ig:17841400000"


class TestOutbox:
    @pytest.fixture
    def outbox(self, tmp_path):
        return SqliteOutbox(SqliteDB(tmp_path / "o.db"))

    def _msg(self, key: str = "k1") -> OutboundMessage:
        return OutboundMessage(
            channel=Channel.WHATSAPP, to=NUMERO, text="hola", idempotency_key=key
        )

    def test_encolar_dos_veces_lo_mismo_deja_una_sola_fila(self, outbox):
        outbox.enqueue(self._msg())
        outbox.enqueue(self._msg())
        assert len(outbox.pending()) == 1

    def test_marcado_como_enviado_sale_de_pendientes(self, outbox):
        outbox.enqueue(self._msg())
        outbox.mark_sent("k1", "wamid.OUT")
        assert outbox.pending() == []

    def test_un_fallo_programa_un_reintento_futuro(self, outbox):
        outbox.enqueue(self._msg())
        outbox.mark_failed("k1", "la API de Meta dio 500")
        # Queda con espera: no se reintenta de inmediato.
        assert outbox.pending() == []

    def test_tras_cinco_fallos_se_rinde_y_queda_marcado(self, outbox):
        outbox.enqueue(self._msg())
        for _ in range(5):
            outbox.mark_failed("k1", "error")
        atascados = outbox.atascados()
        assert len(atascados) == 1
        assert atascados[0]["intentos"] >= 5


def test_el_despachador_envia_y_marca(tmp_path):
    """Sin bucle ni esperas: se llama a `despachar_una_vez` directamente."""
    import asyncio

    from app.adapters.channels.console import ConsoleChannel
    from app.workers.outbox_dispatcher import OutboxDispatcher

    db = SqliteDB(tmp_path / "d.db")
    outbox, conv = SqliteOutbox(db), SqliteConversaciones(db)
    cid = conversation_id(Channel.WHATSAPP, NUMERO)
    conv.registrar_entrante(cid, "whatsapp", NUMERO, "wamid.1", "hola", {})

    canal = ConsoleChannel()
    d = OutboxDispatcher(outbox, {"whatsapp": canal}, conv)
    outbox.enqueue(
        OutboundMessage(
            channel=Channel.WHATSAPP,
            to=NUMERO,
            text="respuesta",
            conversation_id=cid,
            idempotency_key="k1",
        )
    )

    assert asyncio.run(d.despachar_una_vez()) == 1
    assert len(canal.enviados) == 1
    assert outbox.pending() == []
    assert asyncio.run(d.despachar_una_vez()) == 0  # ya no queda nada
    db.cerrar()


def test_si_el_canal_falla_el_mensaje_no_se_pierde(tmp_path):
    """El mensaje se queda en la outbox para reintentarlo, no desaparece."""
    import asyncio

    from app.workers.outbox_dispatcher import OutboxDispatcher

    class CanalRoto:
        def send(self, m, *, ventana_abierta=True):
            raise RuntimeError("Meta devolvió 500")

    db = SqliteDB(tmp_path / "r.db")
    outbox = SqliteOutbox(db)
    d = OutboxDispatcher(outbox, {"whatsapp": CanalRoto()})
    outbox.enqueue(
        OutboundMessage(
            channel=Channel.WHATSAPP, to=NUMERO, text="hola", idempotency_key="k1"
        )
    )

    assert asyncio.run(d.despachar_una_vez()) == 0
    assert d.fallidos == 1
    filas = db.consultar("SELECT intentos, error, sent_at FROM outbox")
    assert filas[0]["intentos"] == 1
    assert filas[0]["sent_at"] is None  # sigue pendiente: se reintentará
    assert "500" in filas[0]["error"]
    db.cerrar()


def test_desde_un_producto_del_catalogo_el_turno_sabe_cual(cliente, monkeypatch):
    """El webhook le pasa al turno el producto del catálogo que ella miraba."""
    recibidos = []

    async def guardar(m):
        recibidos.append(m)

    monkeypatch.setattr(cliente.contenedor, "recibir_mensaje", guardar)
    datos = payload("¿Cuánto se demora?", "wamid.CATALOGO")
    mensaje = datos["entry"][0]["changes"][0]["value"]["messages"][0]
    mensaje["context"] = {
        "referred_product": {"catalog_id": "1", "product_retailer_id": "CAD-HUE-1"}
    }
    cuerpo = json.dumps(datos).encode()
    r = cliente.post(
        "/webhook/whatsapp",
        content=cuerpo,
        headers={
            "Content-Type": "application/json",
            "X-Hub-Signature-256": firmar(cuerpo, cliente.secreto),
        },
    )
    assert r.status_code == 200
    (m,) = recibidos
    assert m.text.startswith("[Escribe desde la vitrina de WhatsApp, mirando: Cadena")
    assert m.text.endswith("¿Cuánto se demora?")
