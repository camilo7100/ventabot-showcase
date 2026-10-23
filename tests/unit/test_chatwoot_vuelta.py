"""Lo que Lía escribe desde Chatwoot tiene que salirle a la clienta.

Sin esto Chatwoot solo sirve para mirar. Con esto se atiende desde el celular:
por eso el camino de vuelta está probado como cualquier otra entrada al sistema
—con su token, sin eco y sin dejar al bot contestando encima—.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.infra import container as contenedor
from app.infra.settings import Settings

NUMERO = "573001112233"
CONV = f"wa:{NUMERO}"
TOKEN = "token-de-chatwoot"


def _aviso(texto: str, **cambios) -> dict:
    """Un `message_created` de Chatwoot, como los manda de verdad."""
    datos = {
        "event": "message_created",
        "id": 4242,
        "content": texto,
        "message_type": "outgoing",
        "private": False,
        "content_attributes": {},
        "conversation": {
            "meta": {"sender": {"identifier": CONV, "name": "Clienta"}},
            "contact_inbox": {"source_id": CONV},
        },
    }
    datos.update(cambios)
    return datos


@pytest.fixture
def cliente(tmp_path, monkeypatch):
    s = Settings(
        sqlite_path=tmp_path / "cw.db",
        repository_backend="memory",
        llm_backend="fake",
        payment_backend="fake",
        channel_backend="console",
        meta_app_secret="secreto",
        meta_verify_token="verify",
        chatwoot_webhook_token=TOKEN,
        dispatcher_interval_s=0.05,
        ventas_excel=tmp_path / "ventas.xlsx",
    )
    c = contenedor.build_container(s)
    monkeypatch.setattr(contenedor, "_singleton", c)
    from app.api.main import app

    with TestClient(app) as tc:
        tc.contenedor = c
        yield tc


def _salio(c, texto: str) -> bool:
    """Quedó en la outbox en CUALQUIER estado, o ya en el historial.

    `pending()` no basta: si el despachador ya lo pospuso (ventana de 24 h
    cerrada en la prueba) deja de salir ahí sin haber llegado al historial.
    """
    import sqlite3

    with sqlite3.connect(str(c.settings.sqlite_path)) as cx:
        filas = cx.execute("SELECT payload FROM outbox").fetchall()
    if any(texto in (p or "") for (p,) in filas):
        return True
    return any(
        texto in (m.get("texto") or "")
        for m in c.conversaciones.historial(CONV, limite=50)
    )


class TestWebhookDeChatwoot:
    def test_lo_que_escribe_lia_sale_a_la_clienta_y_calla_al_bot(self, cliente):
        r = cliente.post(
            f"/webhook/chatwoot?token={TOKEN}", json=_aviso("Hola, soy Lía 💜")
        )
        assert r.status_code == 200 and r.json()["status"] == "enviado"
        assert _salio(cliente.contenedor, "soy Lía")
        assert cliente.contenedor.bot._mundo.la_atiende_una_persona(CONV)

    def test_retomar_manda_la_plantilla_de_emergencia(self, cliente, monkeypatch):
        """16/10: pasadas las 24 h solo llega una plantilla; `#retomar` la manda
        y lo que ella conteste lo atiende el bot. 17/10: y en Chatwoot queda lo
        que le llegó a ella, no solo el «#retomar» de Lía."""
        import json
        import sqlite3

        from app.adapters.crm.chatwoot import CrmDeMentira
        from app.domain import plantilla_de_emergencia as emergencia

        espejo = CrmDeMentira()
        monkeypatch.setattr(cliente.contenedor, "crm", espejo)
        r = cliente.post(f"/webhook/chatwoot?token={TOKEN}", json=_aviso(" #Retomar "))
        assert r.json()["status"] == "plantilla de emergencia"
        with sqlite3.connect(str(cliente.contenedor.settings.sqlite_path)) as cx:
            [(payload,)] = cx.execute("SELECT payload FROM outbox").fetchall()
        enviado = json.loads(payload)
        assert enviado["template_name"] == emergencia.NOMBRE
        assert "#retomar" not in (enviado.get("text") or "").lower()
        assert not cliente.contenedor.bot._mundo.la_atiende_una_persona(CONV)
        salientes = [t for _, t, kw in espejo.copias if kw.get("entrante") is False]
        assert salientes == [emergencia.CUERPO]

    def test_sin_token_configurado_el_webhook_no_existe(self, tmp_path, monkeypatch):
        s = Settings(
            sqlite_path=tmp_path / "sin.db",
            repository_backend="memory",
            llm_backend="fake",
            payment_backend="fake",
            channel_backend="console",
            meta_app_secret="secreto",
            meta_verify_token="verify",
            # Explícito: si no, hereda el token del .env de verdad y la prueba
            # deja de probar lo que dice probar.
            chatwoot_webhook_token="",
            ventas_excel=tmp_path / "v.xlsx",
        )
        monkeypatch.setattr(contenedor, "_singleton", contenedor.build_container(s))
        from app.api.main import app

        with TestClient(app) as tc:
            assert tc.post("/webhook/chatwoot", json=_aviso("hola")).status_code == 404

    def test_con_token_equivocado_no_pasa(self, cliente):
        r = cliente.post("/webhook/chatwoot?token=otro", json=_aviso("hola"))
        assert r.status_code == 403
        assert not _salio(cliente.contenedor, "hola")

    def test_no_se_reenvia_lo_que_el_propio_bot_copio(self, cliente):
        """El espejo escribe en Chatwoot y eso vuelve como webhook: sin la marca
        se le reenviaría a la clienta su propio mensaje, en bucle."""
        aviso = _aviso("Precio del anillo…", content_attributes={"origen": "ventabot"})
        r = cliente.post(f"/webhook/chatwoot?token={TOKEN}", json=aviso)
        assert r.json()["status"] == "ignorado"
        assert not _salio(cliente.contenedor, "Precio del anillo")
        assert not cliente.contenedor.bot._mundo.la_atiende_una_persona(CONV)

    def test_no_se_reenvia_lo_que_firmo_el_agente_bot(self, cliente):
        """Así llega de verdad: Chatwoot descarta la marca y solo queda la firma."""
        aviso = _aviso(
            "¿De cuántas huellitas?",
            sender={"id": 1, "name": "VentaBot", "type": "agent_bot"},
        )
        r = cliente.post(f"/webhook/chatwoot?token={TOKEN}", json=aviso)
        assert r.json()["status"] == "ignorado"
        assert not _salio(cliente.contenedor, "cuántas huellitas")
        assert not cliente.contenedor.bot._mundo.la_atiende_una_persona(CONV)

    def test_no_se_reenvia_lo_que_el_bot_acaba_de_copiar(self, cliente, monkeypatch):
        """Respaldo: sin firma (Chatwoot sin agente bot), se reconoce por el texto."""

        class Espejo:
            def es_eco(self, conv, texto):
                return conv == CONV and texto == "Te muestro el muestrario"

        monkeypatch.setattr(cliente.contenedor, "crm", Espejo())
        aviso = _aviso(
            "Te muestro el muestrario", sender={"id": 3, "name": "Lía", "type": "user"}
        )
        r = cliente.post(f"/webhook/chatwoot?token={TOKEN}", json=aviso)
        assert r.json()["status"] == "ignorado"
        assert not cliente.contenedor.bot._mundo.la_atiende_una_persona(CONV)

    def test_cuando_lia_contesta_queda_asignada_a_ella(self, cliente, monkeypatch):
        """Asignada a una persona = «Abierta» en Chatwoot (lo hace Chatwoot)."""
        from app.adapters.crm.chatwoot import CrmDeMentira

        espejo = CrmDeMentira()
        monkeypatch.setattr(cliente.contenedor, "crm", espejo)
        cliente.post(
            f"/webhook/chatwoot?token={TOKEN}",
            json=_aviso("Hola, soy Lía", sender={"id": 4, "type": "user"}),
        )
        assert (CONV, "[asignar] 4", {}) in espejo.copias

    def test_las_notas_privadas_no_salen(self, cliente):
        r = cliente.post(
            f"/webhook/chatwoot?token={TOKEN}",
            json=_aviso("ojo: esta clienta ya reclamó", private=True),
        )
        assert r.json()["status"] == "ignorado"
        assert not _salio(cliente.contenedor, "reclamó")

    def test_lo_que_escribe_la_clienta_en_chatwoot_no_se_le_devuelve(self, cliente):
        r = cliente.post(
            f"/webhook/chatwoot?token={TOKEN}",
            json=_aviso("hola, quiero un anillo", message_type="incoming"),
        )
        assert r.json()["status"] == "ignorado"
        assert not _salio(cliente.contenedor, "quiero un anillo")

    def test_otros_eventos_se_ignoran(self, cliente):
        r = cliente.post(
            f"/webhook/chatwoot?token={TOKEN}",
            json=_aviso("x", event="conversation_status_changed"),
        )
        assert r.json()["status"] == "ignorado"

    def test_si_no_se_sabe_de_qué_conversación_es_no_se_manda_nada(self, cliente):
        aviso = _aviso("hola")
        aviso["conversation"] = {"meta": {}, "contact_inbox": {}}
        r = cliente.post(f"/webhook/chatwoot?token={TOKEN}", json=aviso)
        assert r.json()["status"] == "ignorado"


# ══════════════════════════════════════════════════════════════════════════
#  COMO WHATSAPP BUSINESS: tomar el control, fotos, y devolverle al bot
# ══════════════════════════════════════════════════════════════════════════

JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 200


class _RespuestaFalsa:
    def __init__(self, contenido: bytes) -> None:
        self.content = contenido

    def raise_for_status(self) -> None:
        return None


class _ClienteHttpFalso:
    """Chatwoot sirviendo el archivo adjunto que mandó Lía."""

    def __init__(self, *a, **kw) -> None:
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a) -> None:
        return None

    async def get(self, url: str):
        return _RespuestaFalsa(JPEG)


def _asignada_a(tipo: str, quien: int) -> dict:
    """Un `conversation_updated` de un cambio de asignación (Chatwoot 4.17)."""
    clave = "assignee_agent_bot_id" if tipo == "AgentBot" else "assignee_id"
    return {
        "event": "conversation_updated",
        **_conversacion_como_evento(),
        "meta": {
            "sender": {"identifier": CONV},
            "assignee": {"id": quien, "name": "VentaBot"},
            "assignee_type": tipo,
        },
        "changed_attributes": [{clave: {"previous_value": None, "current_value": quien}}],
    }


def _conversacion_como_evento(**cambios) -> dict:
    datos = {
        "id": 77,
        "meta": {"sender": {"identifier": CONV}},
        "contact_inbox": {"source_id": CONV},
    }
    datos.update(cambios)
    return datos


class TestComoWhatsAppBusiness:
    def test_cuando_lia_empieza_a_escribir_el_bot_se_calla(self, cliente):
        r = cliente.post(
            f"/webhook/chatwoot?token={TOKEN}",
            json={
                "event": "conversation_typing_on",
                "conversation": _conversacion_como_evento(),
                "user": {"id": 1, "name": "Lía", "type": "user"},
                "is_private": False,
            },
        )
        assert r.json()["status"] == "pausado"
        assert cliente.contenedor.bot._mundo.la_atiende_una_persona(CONV)

    def test_si_la_que_escribe_es_la_clienta_no_pausa(self, cliente):
        r = cliente.post(
            f"/webhook/chatwoot?token={TOKEN}",
            json={
                "event": "conversation_typing_on",
                "conversation": _conversacion_como_evento(),
                "user": {"id": 9, "type": "contact"},
            },
        )
        assert r.json()["status"] == "ignorado"
        assert not cliente.contenedor.bot._mundo.la_atiende_una_persona(CONV)

    def test_una_nota_privada_no_pausa(self, cliente):
        cliente.post(
            f"/webhook/chatwoot?token={TOKEN}",
            json={
                "event": "conversation_typing_on",
                "conversation": _conversacion_como_evento(),
                "user": {"id": 1, "type": "user"},
                "is_private": True,
            },
        )
        assert not cliente.contenedor.bot._mundo.la_atiende_una_persona(CONV)

    def test_asignarse_la_conversacion_calla_al_bot(self, cliente):
        r = cliente.post(
            f"/webhook/chatwoot?token={TOKEN}",
            json={
                "event": "conversation_updated",
                **_conversacion_como_evento(),
                "meta": {
                    "sender": {"identifier": CONV},
                    "assignee": {"id": 1, "name": "Lía"},
                    "assignee_type": "User",
                },
                "changed_attributes": [
                    {"assignee_id": {"previous_value": None, "current_value": 1}}
                ],
            },
        )
        assert r.json()["status"] == "pausado"
        assert cliente.contenedor.bot._mundo.la_atiende_una_persona(CONV)

    def test_otra_edicion_de_la_conversacion_no_pausa(self, cliente):
        r = cliente.post(
            f"/webhook/chatwoot?token={TOKEN}",
            json={
                "event": "conversation_updated",
                **_conversacion_como_evento(),
                "meta": {
                    "sender": {"identifier": CONV},
                    "assignee": {"id": 1, "name": "Lía"},
                },
                "changed_attributes": [{"label_list": {"current_value": ["vip"]}}],
            },
        )
        assert r.json()["status"] == "ignorado"
        assert not cliente.contenedor.bot._mundo.la_atiende_una_persona(CONV)

    def test_sin_asignar_vuelve_a_ventabot(self, cliente):
        """«None» no existe (09/10): si queda sin asignar, la toma VentaBot."""
        mundo = cliente.contenedor.bot._mundo
        mundo.pausar_por_humano(CONV)
        r = cliente.post(
            f"/webhook/chatwoot?token={TOKEN}",
            json={
                "event": "conversation_updated",
                **_conversacion_como_evento(),
                "meta": {"sender": {"identifier": CONV}, "assignee": None},
                "changed_attributes": [
                    {"assignee_id": {"previous_value": 1, "current_value": None}}
                ],
            },
        )
        assert r.json()["status"] == "devuelta al bot"
        assert not mundo.la_atiende_una_persona(CONV)

    def test_resolver_no_se_la_devuelve_al_bot(self, cliente):
        """09/10: resolver es CERRAR. Devolver al bot es otra acción."""
        mundo = cliente.contenedor.bot._mundo
        mundo.pausar_por_humano(CONV)
        r = cliente.post(
            f"/webhook/chatwoot?token={TOKEN}",
            json={
                "event": "conversation_status_changed",
                **_conversacion_como_evento(status="resolved"),
            },
        )
        assert r.json()["status"] == "resuelta"
        assert mundo.la_atiende_una_persona(CONV), "resolver no devuelve al bot"

    def test_asignarla_a_ventabot_se_la_devuelve_al_bot(self, cliente):
        mundo = cliente.contenedor.bot._mundo
        mundo.pausar_por_humano(CONV)
        r = cliente.post(
            f"/webhook/chatwoot?token={TOKEN}",
            json=_asignada_a("AgentBot", 1),
        )
        assert r.json()["status"] == "devuelta al bot"
        assert not mundo.la_atiende_una_persona(CONV)

    def test_el_eco_de_cuando_el_bot_se_la_asigna_no_hace_nada(self, cliente):
        mundo = cliente.contenedor.bot._mundo
        mundo.contexto(CONV)
        r = cliente.post(
            f"/webhook/chatwoot?token={TOKEN}",
            json=_asignada_a("AgentBot", 1),
        )
        assert r.json()["status"] == "ignorado"

    def test_reabrir_no_cambia_quien_atiende(self, cliente):
        mundo = cliente.contenedor.bot._mundo
        mundo.pausar_por_humano(CONV)
        cliente.post(
            f"/webhook/chatwoot?token={TOKEN}",
            json={
                "event": "conversation_status_changed",
                **_conversacion_como_evento(status="open"),
            },
        )
        assert mundo.la_atiende_una_persona(CONV)

    def test_la_foto_que_manda_lia_le_llega_a_la_clienta(self, cliente, monkeypatch):
        import httpx

        monkeypatch.setattr(httpx, "AsyncClient", _ClienteHttpFalso)
        aviso = _aviso(
            "Así quedó tu anillo 💍",
            attachments=[
                {"file_type": "image", "data_url": "http://chatwoot/archivo.jpg"}
            ],
        )
        r = cliente.post(f"/webhook/chatwoot?token={TOKEN}", json=aviso)
        assert r.json() == {"status": "enviado", "fotos": 1, "sin_mandar": 0}

        c = cliente.contenedor
        salientes = c.outbox.pending(limit=20)
        fotos = [m for m in salientes if m.kind == "image"]
        historial = c.conversaciones.historial(CONV, limite=20)
        assert fotos or historial, "la foto tiene que salir por el mismo canal"
        if fotos:
            assert "/panel/foto/" in fotos[0].media_url
            assert fotos[0].text == "Así quedó tu anillo 💍", (
                "el texto va como pie de foto"
            )
        assert c.bot._mundo.la_atiende_una_persona(CONV)

    def test_un_adjunto_que_no_es_foto_no_se_manda_a_ciegas(self, cliente, monkeypatch):
        import httpx

        monkeypatch.setattr(httpx, "AsyncClient", _ClienteHttpFalso)
        aviso = _aviso(
            "", attachments=[{"file_type": "audio", "data_url": "http://x/a.ogg"}]
        )
        r = cliente.post(f"/webhook/chatwoot?token={TOKEN}", json=aviso)
        assert r.json()["status"] == "ignorado"
        assert r.json()["motivo"] == "adjunto que no es foto"


class TestElEspejoConFotos:
    def test_la_foto_de_la_clienta_se_sube_como_foto(self, monkeypatch):
        import httpx

        from app.adapters.crm.chatwoot import ChatwootCRM

        subidas = []

        def _post(url, **kw):
            subidas.append((url, kw))
            return _RespuestaFalsa(b"")

        monkeypatch.setattr(httpx, "post", _post)
        crm = ChatwootCRM("http://127.0.0.1:9", "t", 1, 2, descargar=lambda ref: JPEG)
        crm._cache[CONV] = (5, 6)
        crm._copiar(
            CONV,
            "[adjunto]",
            True,
            "Clienta",
            (),
            {},
            ({"media_id": "m1", "kind": "image", "mime_type": "image/jpeg"},),
        )
        assert subidas, "tiene que subir el archivo"
        url, kw = subidas[0]
        assert url.endswith("/conversations/6/messages")
        nombre, datos, mime = kw["files"][0][1]
        assert datos == JPEG and mime == "image/jpeg" and nombre.endswith(".jpg")
        assert kw["data"]["content"] == "", "«[adjunto]» no se escribe: se ve la foto"
        assert kw["data"]["message_type"] == "incoming"

    def test_si_no_se_puede_bajar_se_copia_el_texto(self, monkeypatch):
        import httpx

        from app.adapters.crm.chatwoot import ChatwootCRM

        mandados = []
        monkeypatch.setattr(httpx, "post", lambda *a, **kw: mandados.append(kw))
        monkeypatch.setattr(
            httpx, "request", lambda *a, **kw: mandados.append(kw) or _RespuestaFalsa(b"")
        )

        def _falla(ref):
            raise RuntimeError("Meta no respondió")

        crm = ChatwootCRM("http://127.0.0.1:9", "t", 1, 2, descargar=_falla)
        crm._cache[CONV] = (5, 6)
        crm._copiar(CONV, "mira mi talla", True, "", (), {}, ({"media_id": "m1"},))
        assert any(
            (kw.get("json") or {}).get("content") == "mira mi talla" for kw in mandados
        )


def test_las_fotos_del_bot_se_ven_con_un_nombre_que_se_entiende():
    from app.domain.models import Channel, OutboundMessage
    from app.infra.container import _etiqueta_de_media

    foto = OutboundMessage(
        channel=Channel.WHATSAPP,
        to="1",
        kind="image",
        media_url="https://x/media/muestrario_circones.jpg",
    )
    assert _etiqueta_de_media(foto) == "[📷 muestrario circones]"


# ══════════════════════════════════════════════════════════════════════════
#  ACCIONES DESDE CHATWOOT: Lía pone una etiqueta `hacer-…` y el sistema lo hace
# ══════════════════════════════════════════════════════════════════════════


def _pedido_de_la_clienta(c, estado, completo=True, **kw):
    from tests.unit.test_panel import _completo, _pedido

    cliente = c.bot._mundo.asegurar_cliente(CONV)
    armar = _completo if completo else _pedido
    return c.orders.create(
        armar(estado, customer_id=cliente.id, **kw), idem_key=f"k-{estado.value}"
    )


def _orden(cliente, etiqueta):
    return cliente.post(
        f"/webhook/chatwoot?token={TOKEN}",
        json={
            "event": "conversation_updated",
            **_conversacion_como_evento(),
            "labels": ["05-en-taller", etiqueta],
            "changed_attributes": [{"label_list": {"current_value": [etiqueta]}}],
        },
    )


class TestAccionesDesdeChatwoot:
    @pytest.fixture
    def espejo(self, cliente, monkeypatch):
        from app.adapters.crm.chatwoot import CrmDeMentira

        falso = CrmDeMentira()
        monkeypatch.setattr(cliente.contenedor, "crm", falso)
        return falso

    def test_abono_ok_lo_pasa_al_taller_y_le_avisa(self, cliente, espejo):
        from app.domain.order_state import OrderState

        c = cliente.contenedor
        pedido = _pedido_de_la_clienta(c, OrderState.EN_REVISION_PAGO)
        r = _orden(cliente, "hacer-abono-ok")
        assert r.json()["status"] == "accion"
        movido = c.orders.get(pedido.id)
        assert movido.estado == "EN_PRODUCCION"
        assert movido.anticipo_pagado_cop == 60_000
        textos = [x[1] for x in espejo.copias]
        assert "[quitar] hacer-abono-ok" in textos
        assert any(t.startswith("[nota] ✅") for t in textos)
        assert _salio(c, "taller"), "la clienta se entera de que entró al taller"

    def test_sin_datos_completos_no_entra_y_se_explica(self, cliente, espejo):
        from app.domain.order_state import OrderState

        c = cliente.contenedor
        pedido = _pedido_de_la_clienta(c, OrderState.EN_REVISION_PAGO, completo=False)
        _orden(cliente, "hacer-abono-ok")
        assert c.orders.get(pedido.id).estado == "ANTICIPO_PAGADO"
        notas = [x[1] for x in espejo.copias if x[1].startswith("[nota] ⚠️")]
        assert notas and "talla" in notas[0]

    def test_una_accion_que_no_aplica_no_mueve_nada(self, cliente, espejo):
        from app.domain.order_state import OrderState

        c = cliente.contenedor
        pedido = _pedido_de_la_clienta(c, OrderState.EN_PRODUCCION)
        _orden(cliente, "hacer-saldo-ok")
        assert c.orders.get(pedido.id).estado == "EN_PRODUCCION"
        assert any("no aplica" in x[1] for x in espejo.copias)

    def test_resolver_quita_la_alerta_de_persona(self, cliente, espejo):
        c = cliente.contenedor
        c.actualizar_seguimiento(CONV, escalada=True)
        assert c.bot._mundo.contexto(CONV).necesita_persona
        cliente.post(
            f"/webhook/chatwoot?token={TOKEN}",
            json={
                "event": "conversation_status_changed",
                **_conversacion_como_evento(status="resolved"),
            },
        )
        assert not c.bot._mundo.contexto(CONV).necesita_persona


class TestLaConversacionBorradaSeRehace:
    """20/09. `ChatwootCRM` recuerda en memoria `wa:57…` → (contacto,
    conversación) para no buscarlos en cada mensaje. Cuando esa conversación se
    borra en Chatwoot —al borrar el contacto, que es lo que hace `vb reiniciar`
    y lo que Camilo pidió para empezar de cero con su número— la memoria seguía
    apuntando a un id muerto y CADA mensaje de esa persona acababa así:

        WARNING chatwoot  no se pudo copiar a Chatwoot (Client error '404 Not
        Found' for url '.../conversations/34/messages'

    Para siempre, hasta reiniciar el bot. Por WhatsApp todo se veía bien, pero
    en Chatwoot no aparecía nada: Lía no veía la conversación ni podía
    intervenir. Es lo que se reportó como «no me llegan todos los mensajes».
    """

    def _crm(self, monkeypatch, viva: int | None):
        """Un Chatwoot donde la conversación `viva` existe y el resto no."""
        import httpx

        from app.adapters.crm.chatwoot import ChatwootCRM

        hechas: list[str] = []

        class _Resp:
            def __init__(self, datos):
                self._datos = datos
                self.content = b"x"

            def raise_for_status(self):
                return None

            def json(self):
                return self._datos

        class _404(Exception):
            def __init__(self) -> None:
                self.response = type("r", (), {"status_code": 404})()

        def _request(metodo, url, **kw):
            hechas.append(f"{metodo} {url}")
            if "/conversations/" in url and f"/conversations/{viva}/" not in url:
                raise _404()
            if "/contacts/search" in url:
                return _Resp({"payload": []})
            if url.endswith("/contacts"):
                return _Resp({"payload": {"contact": {"id": 9}}})
            if url.endswith("/conversations"):
                return _Resp({"id": viva})
            if "/conversations" in url:
                return _Resp({"payload": []})
            return _Resp({})

        monkeypatch.setattr(httpx, "request", _request)
        crm = ChatwootCRM("http://127.0.0.1:9", "t", 1, 2)
        return crm, hechas

    def test_un_404_hace_que_se_rehaga_y_el_mensaje_llega(self, monkeypatch):
        crm, hechas = self._crm(monkeypatch, viva=77)
        crm._cache[CONV] = (5, 34)  # la que se borró
        crm.registrar(CONV, "hola", entrante=True)
        assert crm.vaciar(5)
        assert crm._cache.get(CONV) != (5, 34), "siguió recordando la borrada"
        assert any("/conversations/77/messages" in h for h in hechas), (
            f"no reintentó contra la conversación nueva: {hechas}"
        )

    def test_sin_404_no_se_rehace_nada(self, monkeypatch):
        """Lo de siempre no se rompe: una conversación viva se usa tal cual."""
        crm, hechas = self._crm(monkeypatch, viva=34)
        crm._cache[CONV] = (5, 34)
        crm.registrar(CONV, "hola", entrante=True)
        assert crm.vaciar(5)
        assert crm._cache[CONV] == (5, 34), "tiró una conversación que sí existía"
        assert not any("/contacts" in h for h in hechas), "buscó contacto sin hacer falta"


class TestQuienLaLleva:
    """09/10. UN criterio en el PC, el celular y el panel: quien está asignado
    en Chatwoot es quien atiende. VentaBot por defecto; una persona cuando la
    toma; devolver al bot es una acción propia; resolver solo cierra."""

    @pytest.fixture
    def espejo(self, cliente, monkeypatch):
        from app.adapters.crm.chatwoot import CrmDeMentira

        falso = CrmDeMentira()
        monkeypatch.setattr(cliente.contenedor, "crm", falso)
        return falso

    def test_la_etiqueta_devolver_al_bot_se_la_devuelve(self, cliente, espejo):
        mundo = cliente.contenedor.bot._mundo
        mundo.pausar_por_humano(CONV)
        r = _orden(cliente, "hacer-devolver-al-bot")
        assert r.json()["status"] == "accion"
        assert not mundo.la_atiende_una_persona(CONV)
        hechas = [x[1] for x in espejo.copias]
        assert "[asignar] bot" in hechas, "en Chatwoot vuelve a VentaBot"
        assert "[quitar] hacer-devolver-al-bot" in hechas
        assert any("De vuelta con VentaBot" in h for h in hechas)

    def test_quien_escribe_desde_chatwoot_se_queda_con_ella(self, cliente, espejo):
        cliente.post(
            f"/webhook/chatwoot?token={TOKEN}",
            json=_aviso("Hola, soy Lía", sender={"id": 4, "type": "user"}),
        )
        assert cliente.contenedor.bot._mundo.la_atiende_una_persona(CONV)
        assert "[asignar] 4" in [x[1] for x in espejo.copias]

    def test_quien_empieza_a_escribir_se_queda_con_ella(self, cliente, espejo):
        cliente.post(
            f"/webhook/chatwoot?token={TOKEN}",
            json={
                "event": "conversation_typing_on",
                "conversation": _conversacion_como_evento(),
                "user": {"id": 3, "type": "user"},
                "is_private": False,
            },
        )
        assert cliente.contenedor.bot._mundo.la_atiende_una_persona(CONV)
        assert "[asignar] 3" in [x[1] for x in espejo.copias]

    def test_el_boton_del_panel_tambien_la_asigna_a_ventabot(self, cliente, espejo):
        c = cliente.contenedor
        c.bot._mundo.pausar_por_humano(CONV)
        from app.infra.quien_atiende import devolver_al_bot

        devolver_al_bot(c, CONV)
        assert not c.bot._mundo.la_atiende_una_persona(CONV)
        assert "[asignar] bot" in [x[1] for x in espejo.copias]


class TestChatwootMuestraQuienLaLleva:
    """Lo que el adaptador le pide a Chatwoot después de cada turno."""

    def _crm(self, monkeypatch, conversacion: dict):
        from app.adapters.crm.chatwoot import ChatwootCRM

        pedidos: list[tuple] = []

        def _pedir(metodo, ruta, cuerpo=None, token=None):
            pedidos.append((metodo, ruta, cuerpo))
            if ruta.endswith("/agent_bot"):
                return {"agent_bot": {"id": 1, "name": "VentaBot"}}
            if metodo == "GET":
                return conversacion
            return {}

        crm = ChatwootCRM("http://127.0.0.1:9", "t", 1, 2)
        monkeypatch.setattr(crm, "_pedir", _pedir)
        return crm, pedidos

    def _seguir(self, crm, persona=False, alertas=frozenset()):
        from app.domain.seguimiento import Seguimiento

        crm._poner_al_dia_quien_la_lleva(
            6,
            crm._pedir("GET", "/conversations/6"),
            Seguimiento("02-disenando", alertas),
            persona,
        )

    def test_sin_asignar_se_la_asigna_a_ventabot(self, monkeypatch):
        crm, pedidos = self._crm(monkeypatch, {"status": "open", "meta": {}})
        try:
            self._seguir(crm)
            assert (
                "POST",
                "/conversations/6/assignments",
                {"assignee_id": 1, "assignee_type": "AgentBot"},
            ) in pedidos
        finally:
            crm.cerrar()

    def test_si_ya_la_tiene_ventabot_no_la_toca(self, monkeypatch):
        conversacion = {
            "status": "pending",
            "meta": {"assignee": {"id": 1}, "assignee_type": "AgentBot"},
        }
        crm, pedidos = self._crm(monkeypatch, conversacion)
        try:
            self._seguir(crm)
            assert not [p for p in pedidos if p[1].endswith("/assignments")]
        finally:
            crm.cerrar()

    def test_si_la_atiende_una_persona_no_se_la_quita(self, monkeypatch):
        conversacion = {
            "status": "open",
            "meta": {"assignee": {"id": 4}, "assignee_type": "User"},
        }
        crm, pedidos = self._crm(monkeypatch, conversacion)
        try:
            self._seguir(crm, persona=True)
            assert not [p for p in pedidos if p[1].endswith("/assignments")]
        finally:
            crm.cerrar()

    def test_pasadas_las_12_horas_vuelve_a_ventabot_con_una_nota(self, monkeypatch):
        conversacion = {
            "status": "open",
            "meta": {"assignee": {"id": 4}, "assignee_type": "User"},
        }
        crm, pedidos = self._crm(monkeypatch, conversacion)
        try:
            self._seguir(crm, persona=False)
            assert any(p[1].endswith("/assignments") for p in pedidos)
            notas = [p[2] for p in pedidos if p[1].endswith("/messages")]
            assert notas and notas[0]["private"] and "12 h" in notas[0]["content"]
        finally:
            crm.cerrar()

    def test_una_resuelta_no_se_reabre_sola(self, monkeypatch):
        crm, pedidos = self._crm(monkeypatch, {"status": "resolved", "meta": {}})
        try:
            self._seguir(crm)
            assert [p for p in pedidos if p[0] == "POST"] == []
        finally:
            crm.cerrar()

    def test_lo_que_necesita_a_una_persona_queda_urgente(self, monkeypatch):
        conversacion = {
            "status": "pending",
            "meta": {"assignee": {"id": 1}, "assignee_type": "AgentBot"},
        }
        crm, pedidos = self._crm(monkeypatch, conversacion)
        try:
            self._seguir(crm, alertas=frozenset({"necesita-persona"}))
            assert (
                "POST",
                "/conversations/6/toggle_priority",
                {"priority": "urgent"},
            ) in (pedidos)
        finally:
            crm.cerrar()

    def test_asignar_no_repite_si_ya_la_tiene(self, monkeypatch):
        conversacion = {
            "status": "open",
            "meta": {"assignee": {"id": 4}, "assignee_type": "User"},
        }
        crm, pedidos = self._crm(monkeypatch, conversacion)
        crm._cache[CONV] = (5, 6)
        try:
            crm._asignar(CONV, 4)
            assert not [p for p in pedidos if p[1].endswith("/assignments")]
            crm._asignar(CONV, "bot")
            assert [p for p in pedidos if p[1].endswith("/assignments")]
        finally:
            crm.cerrar()


class TestAsesora:
    """`#asesora` (Camilo, 19/10): ella pidió una persona y pasaron las 24 h
    (Laura: el «Buen día Laura» de Lía se quedó esperando en la outbox)."""

    def test_manda_la_plantilla_con_su_nombre_y_sigue_con_la_persona(self, cliente):
        import json
        import sqlite3
        import time

        from app.domain import plantilla_de_emergencia as emergencia

        c = cliente.contenedor
        cliente.post(
            f"/webhook/chatwoot?token={TOKEN}",
            json=_aviso("Buen día Laura, cómo estás?", id=1),
        )
        db = str(c.settings.sqlite_path)
        for _ in range(60):  # el despachador lo pone en espera (ventana cerrada)
            with sqlite3.connect(db) as cx:
                fila = cx.execute(
                    "SELECT error FROM outbox WHERE idempotency_key='chatwoot:1'"
                ).fetchone()
            if fila and fila[0]:
                break
            time.sleep(0.05)
        assert fila and fila[0].startswith("ventana de 24 h cerrada")

        r = cliente.post(
            f"/webhook/chatwoot?token={TOKEN}", json=_aviso(" #Asesora ", id=2)
        )
        assert r.json()["status"] == "plantilla de asesora"
        with sqlite3.connect(db) as cx:
            (payload,) = cx.execute(
                "SELECT payload FROM outbox WHERE idempotency_key='chatwoot:2'"
            ).fetchone()
            sent_at, error = cx.execute(
                "SELECT sent_at, error FROM outbox WHERE idempotency_key='chatwoot:1'"
            ).fetchone()
        enviado = json.loads(payload)
        assert enviado["template_name"] == emergencia.NOMBRE_ASESORA
        assert enviado["template_params"] == {"1": "Clienta"}
        assert enviado["text"].startswith("Hola Clienta 🌷 Habla Lía")
        assert sent_at and error.startswith("descartado"), "el viejo ya no sale"
        assert c.bot._mundo.la_atiende_una_persona(CONV), "sigue con la persona"


@pytest.mark.parametrize(
    "nombre, queda",
    [
        ("laura garcía", "Laura"),
        ("LAURA", "Laura"),
        ("+573001110013", "de nuevo"),
        (None, "de nuevo"),
    ],
)
def test_el_nombre_de_la_plantilla_de_asesora(nombre, queda):
    from app.domain import plantilla_de_emergencia as e

    lee, params = e.la_de_asesora(e.NOMBRE_ASESORA, nombre)
    assert params == {"1": queda} and f"Hola {queda} 🌷" in lee
    lee, params = e.la_de_asesora(e.RESPALDO_ASESORA, nombre)
    assert params == {} and "{{" not in lee


def test_la_tercera_de_asesora_es_corta_y_sin_botones():
    """19/10, 7 p. m.: las dos primeras seguían en revisión; la tercera, la más
    simple, entra al final del orden (sale la primera aprobada)."""
    from app.domain import plantilla_de_emergencia as e

    assert list(e.PLANTILLAS_ASESORA) == [
        "asesora_te_atiende",
        "asesora_te_atiende_2",
        "asesora_te_atiende_3",
    ]
    lee, params = e.la_de_asesora(e.TERCERA_ASESORA, "Laura")
    assert params == {} and lee.startswith("Hola, habla Lía")
    assert e.TERCERA_ASESORA in e.SIN_BOTONES


def test_si_solo_aprueban_la_tercera_sale_esa(tmp_path, monkeypatch):
    from app.domain import plantilla_de_emergencia as e

    s = Settings(
        sqlite_path=tmp_path / "t3.db",
        repository_backend="memory",
        llm_backend="fake",
        payment_backend="fake",
        channel_backend="console",
        meta_app_secret="secreto",
        meta_verify_token="verify",
        chatwoot_webhook_token=TOKEN,
        wa_business_account_id="waba",
        ventas_excel=tmp_path / "v.xlsx",
    )
    c = contenedor.build_container(s)
    estados = {e.TERCERA_ASESORA: "APPROVED"}
    monkeypatch.setattr(
        c.whatsapp,
        "estado_de_plantilla",
        lambda waba, n: estados.get(n, "PENDING"),
        raising=False,
    )
    try:
        assert c._asesora_aprobada() == e.TERCERA_ASESORA
    finally:
        c.cerrar()
