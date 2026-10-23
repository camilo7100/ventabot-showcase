"""Lo que se le mandó a una clienta y NO le llegó, dicho (Camilo, 16/10).

Chatwoot muestra el mensaje como enviado apenas se encola, lo mande el bot o
Lía. Si después no sale —24 h vencidas, cinco intentos fallidos, o Meta lo
acepta y luego avisa «failed»— tiene que quedar una nota en la conversación y
llegar al celular.
"""

from __future__ import annotations

import asyncio

from app.adapters.channels.whatsapp import entregas_fallidas, motivo_de_meta
from app.domain.models import Channel, OutboundMessage
from app.workers.outbox_dispatcher import OutboxDispatcher


class _Outbox:
    def __init__(self, mensajes, *, se_rinde: bool = False):
        self._mensajes = list(mensajes)
        self.se_rinde = se_rinde
        self.pospuestos: list[str] = []

    def pending(self, limit: int = 50):
        return list(self._mensajes)

    def mark_sent(self, clave, external_id=None):
        pass

    def mark_failed(self, clave, error):
        return self.se_rinde

    def posponer(self, clave, segundos, motivo):
        self.pospuestos.append(clave)

    def descartar(self, clave, motivo):
        self.descartados = [*getattr(self, "descartados", []), clave]


class _VentanaAbierta:
    def ventana_abierta(self, conv):
        return True

    def registrar_saliente(self, *a, **kw):
        pass


class _CanalQueManda:
    def __init__(self):
        self.enviados = []

    def send(self, m, ventana_abierta=True):
        self.enviados.append(m)
        return "wamid.ok"


class _VentanaCerrada:
    def ventana_abierta(self, conv):
        return False

    def registrar_saliente(self, *a, **kw):
        pass


class _CanalQueFalla:
    def send(self, m, ventana_abierta=True):
        raise RuntimeError("Meta rechazó el mensaje (#131026)")


def _mensaje(texto="Tu anillo ya está listo 💍") -> OutboundMessage:
    return OutboundMessage(
        channel=Channel.WHATSAPP,
        to="573001112233",
        text=texto,
        conversation_id="wa:573001112233",
        idempotency_key="k1",
    )


def test_con_la_ventana_cerrada_se_informa_una_sola_vez():
    informados = []
    m = _mensaje()
    despachador = OutboxDispatcher(
        _Outbox([m]),
        {"whatsapp": _CanalQueFalla()},
        _VentanaCerrada(),
        informar=lambda *a: informados.append(a),
    )
    asyncio.run(despachador._enviar(m))
    asyncio.run(despachador._enviar(m))  # cinco minutos después, sigue cerrada
    [(conv, texto, motivo, definitivo)] = informados
    assert conv == "wa:573001112233" and "anillo" in texto
    assert "24 h" in motivo and "#retomar" in motivo and definitivo is False


def test_cuando_se_rinde_tras_cinco_intentos_se_informa():
    informados = []
    m = _mensaje()
    despachador = OutboxDispatcher(
        _Outbox([m], se_rinde=True),
        {"whatsapp": _CanalQueFalla()},
        informar=lambda *a: informados.append(a),
    )
    asyncio.run(despachador._enviar(m))
    [(_conv, _texto, motivo, definitivo)] = informados
    assert "5 intentos" in motivo and definitivo is True


def test_mientras_reintenta_no_se_informa():
    informados = []
    m = _mensaje()
    despachador = OutboxDispatcher(
        _Outbox([m], se_rinde=False),
        {"whatsapp": _CanalQueFalla()},
        informar=lambda *a: informados.append(a),
    )
    asyncio.run(despachador._enviar(m))
    assert not informados


def test_el_acuse_failed_de_meta_se_lee_con_su_motivo():
    payload = {
        "entry": [
            {
                "changes": [
                    {
                        "field": "messages",
                        "value": {
                            "statuses": [
                                {"id": "wamid.ok", "status": "delivered"},
                                {
                                    "id": "wamid.malo",
                                    "status": "failed",
                                    "errors": [{"code": 131049, "title": "x"}],
                                },
                            ]
                        },
                    }
                ]
            }
        ]
    }
    [fallida] = entregas_fallidas(payload)
    assert fallida["wamid"] == "wamid.malo" and fallida["codigo"] == 131049
    assert "marketing" in fallida["motivo"]


def test_un_codigo_desconocido_dice_lo_que_dijo_meta():
    assert "algo nuevo" in motivo_de_meta(999999, "algo nuevo")


def test_el_failed_de_meta_encuentra_su_mensaje_y_lo_informa(tmp_path, monkeypatch):
    from app.infra import container as contenedor
    from app.infra.settings import Settings

    s = Settings(
        sqlite_path=tmp_path / "f.db",
        repository_backend="memory",
        llm_backend="fake",
        payment_backend="fake",
        channel_backend="console",
        meta_app_secret="secreto",
        meta_verify_token="verify",
        chatwoot_webhook_token="",
        ventas_excel=tmp_path / "v.xlsx",
    )
    c = contenedor.build_container(s)
    try:
        informados = []
        monkeypatch.setattr(c, "informar_que_no_llego", lambda *a: informados.append(a))
        m = _mensaje()
        c.outbox.enqueue(m)
        c.outbox.mark_sent(m.idempotency_key, "wamid.123")
        assert c.no_llego_segun_meta("wamid.123", "ella bloqueó el número")
        [(conv, texto, motivo)] = informados
        assert conv == "wa:573001112233" and "anillo" in texto and "bloque" in motivo
        assert not c.no_llego_segun_meta("wamid.que-no-existe", "x")
    finally:
        c.cerrar()


def _disculpa(**cambios) -> OutboundMessage:
    datos = {
        "channel": Channel.WHATSAPP,
        "to": "573001112233",
        "kind": "template",
        "text": "Hola 😊 Te escribimos de Luna Joyas…",
        "template_name": "retomar_conversacion",
        "conversation_id": "wa:573001112233",
        "idempotency_key": "retomar:wa:573001112233:2026-10-17",
        "copiar_al_salir": True,
    }
    return OutboundMessage(**(datos | cambios))


def test_la_disculpa_programada_se_copia_a_chatwoot_al_salir():
    """Jannet, 17/10: queda en Chatwoot a la hora en que de verdad salió."""
    copiados, canal = [], _CanalQueManda()
    m = _disculpa()
    despachador = OutboxDispatcher(
        _Outbox([m]),
        {"whatsapp": canal},
        _VentanaCerrada(),
        copiar=lambda conv, msg: copiados.append((conv, msg.text)),
    )
    assert asyncio.run(despachador._enviar(m))
    assert canal.enviados == [m]
    assert copiados == [("wa:573001112233", m.text)]


def test_la_disculpa_no_sale_si_ella_ya_volvio_a_escribir():
    """Si la clienta escribió antes de las 8 a. m., el bot ya la atiende: la
    disculpa sobra. No sale, no se copia, y queda una nota que lo dice."""
    copiados, notas, canal = [], [], _CanalQueManda()
    m = _disculpa()
    bandeja = _Outbox([m])
    despachador = OutboxDispatcher(
        bandeja,
        {"whatsapp": canal},
        _VentanaAbierta(),
        copiar=lambda *a: copiados.append(a),
        anotar=lambda conv, texto: notas.append(texto),
    )
    assert not asyncio.run(despachador._enviar(m))
    assert canal.enviados == [] and copiados == []
    assert bandeja.descartados == [m.idempotency_key]
    assert "NO salió" in notas[0]


def test_retomar_desde_chatwoot_sale_aunque_la_ventana_este_abierta():
    """`#retomar` lo decide Lía: su clave no es «retomar:», sale siempre."""
    canal = _CanalQueManda()
    m = _disculpa(idempotency_key="chatwoot:99", copiar_al_salir=False)
    despachador = OutboxDispatcher(_Outbox([m]), {"whatsapp": canal}, _VentanaAbierta())
    assert asyncio.run(despachador._enviar(m))
    assert canal.enviados == [m]
