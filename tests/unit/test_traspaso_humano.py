"""Cuando una persona contesta, el bot se calla en ESA conversación.

Dos voces distintas en el mismo chat —una persona y el bot— es lo que rompe la
confianza en mitad de una venta: la clienta recibe dos versiones del pedido.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from app.domain.atencion import HORAS_DE_PAUSA, en_pausa, minutos_restantes, pausar
from app.domain.models import now_utc
from app.infra import container as contenedor
from app.infra.settings import Settings

NUMERO = "573001112233"
CONV = f"wa:{NUMERO}"
SECRETO = "secreto-de-prueba"
TOKEN = "token-de-panel"


# ══════════════════════════════════════════════════════════════════════════
#  LA REGLA, SIN NADA ALREDEDOR
# ══════════════════════════════════════════════════════════════════════════


class TestLaRegla:
    def test_sin_persona_atendiendo_contesta_el_bot(self):
        assert not en_pausa(None)
        assert minutos_restantes(None) == 0

    def test_mientras_la_pausa_esta_viva_el_bot_calla(self):
        assert en_pausa(pausar(2))
        # 119 o 120: entre pausar() y contar puede pasar el cambio de segundo.
        assert minutos_restantes(pausar(2)) in (119, 120)

    def test_la_pausa_vence_sola(self):
        vencida = now_utc() - timedelta(minutes=1)
        assert not en_pausa(vencida)
        assert minutos_restantes(vencida) == 0

    def test_por_defecto_son_doce_horas(self):
        assert HORAS_DE_PAUSA == 12
        assert minutos_restantes(pausar()) == pytest.approx(12 * 60, abs=1)


# ══════════════════════════════════════════════════════════════════════════
#  EL TURNO ENTERO: WEBHOOK -> ¿CONTESTA O NO?
# ══════════════════════════════════════════════════════════════════════════


def _cuerpo(texto: str, mid: str) -> bytes:
    return json.dumps(
        {
            "object": "whatsapp_business_account",
            "entry": [
                {
                    "id": "TEST",
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
                                    {"profile": {"name": "Clienta"}, "wa_id": NUMERO}
                                ],
                                "messages": [
                                    {
                                        "from": NUMERO,
                                        "id": mid,
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
    ).encode()


@pytest.fixture
def cliente(tmp_path, monkeypatch):
    s = Settings(
        sqlite_path=tmp_path / "traspaso.db",
        repository_backend="memory",
        llm_backend="fake",
        payment_backend="fake",
        channel_backend="console",
        meta_app_secret=SECRETO,
        meta_verify_token="verify",
        panel_token=TOKEN,
        dispatcher_interval_s=0.05,
        ventas_excel=tmp_path / "ventas.xlsx",
    )
    c = contenedor.build_container(s)
    monkeypatch.setattr(contenedor, "_singleton", c)
    from app.api.main import app

    with TestClient(app) as tc:
        tc.contenedor = c
        yield tc


def _hay_respuesta(c, espera_s: float = 3.0) -> bool:
    """El bot contesta por la outbox y el despachador la manda aparte: hay que
    esperar a que el mensaje aparezca, o estar seguros de que no va a aparecer."""
    limite = time.monotonic() + espera_s
    while time.monotonic() < limite:
        if any(
            m["direccion"] == "OUT" for m in c.conversaciones.historial(CONV, limite=50)
        ) or c.outbox.pending(limit=50):
            return True
        time.sleep(0.05)
    return False


def _escribe_la_clienta(cliente, texto: str, mid: str):
    datos = _cuerpo(texto, mid)
    firma = "sha256=" + hmac.new(SECRETO.encode(), datos, hashlib.sha256).hexdigest()
    return cliente.post(
        "/webhook/whatsapp",
        content=datos,
        headers={"Content-Type": "application/json", "X-Hub-Signature-256": firma},
    )


class TestElTurno:
    def test_normalmente_el_bot_contesta(self, cliente):
        _escribe_la_clienta(cliente, "hola, cuánto vale?", "wamid.1")
        assert _hay_respuesta(cliente.contenedor)

    def test_si_una_persona_esta_atendiendo_el_bot_no_contesta(self, cliente):
        c = cliente.contenedor
        _escribe_la_clienta(cliente, "hola", "wamid.1")
        c.bot._mundo.pausar_por_humano(CONV)
        antes = len(c.conversaciones.historial(CONV, limite=50))

        _escribe_la_clienta(cliente, "y viene con garantía?", "wamid.2")

        despues = c.conversaciones.historial(CONV, limite=50)
        # Entró el mensaje de la clienta, pero el bot no puso nada encima.
        assert len(despues) == antes + 1
        assert despues[-1]["direccion"] == "IN"

    def test_cuando_se_devuelve_al_bot_vuelve_a_contestar(self, cliente):
        c = cliente.contenedor
        c.bot._mundo.pausar_por_humano(CONV)
        _escribe_la_clienta(cliente, "hola", "wamid.1")
        c.bot._mundo.devolver_al_bot(CONV)

        _escribe_la_clienta(cliente, "hola de nuevo", "wamid.2")
        assert _hay_respuesta(c)


# ══════════════════════════════════════════════════════════════════════════
#  EL PANEL: CONTESTAR A MANO DESDE EL CELULAR
# ══════════════════════════════════════════════════════════════════════════


class TestPanelDeChats:
    def test_responder_encola_el_mensaje_y_calla_al_bot(self, cliente):
        c = cliente.contenedor
        _escribe_la_clienta(cliente, "hola", "wamid.1")

        r = cliente.post(
            f"/panel/responder?token={TOKEN}",
            data={"conv": CONV, "texto": "Hola Lau, te escribo yo 💜"},
            follow_redirects=False,
        )
        assert r.status_code == 303
        assert c.bot._mundo.la_atiende_una_persona(CONV)
        salio = any("te escribo yo" in (m.text or "") for m in c.outbox.pending(limit=50))
        # El despachador puede haberlo mandado ya: entonces está en el historial.
        salio = salio or any(
            "te escribo yo" in (m.get("texto") or "")
            for m in c.conversaciones.historial(CONV, limite=50)
        )
        assert salio, "el mensaje de la persona tiene que salir por el mismo canal"

    def test_lo_que_escribe_la_persona_queda_en_la_charla_del_bot(self, cliente):
        """Si no, al volver el bot contradice lo que prometió la persona."""
        c = cliente.contenedor
        _escribe_la_clienta(cliente, "hola", "wamid.1")
        cliente.post(
            f"/panel/responder?token={TOKEN}",
            data={"conv": CONV, "texto": "Te lo dejo en $180.000"},
            follow_redirects=False,
        )
        charla = c.bot._mundo.contexto(CONV).charla
        assert any("180.000" in (m.get("texto") or "") for m in charla)

    def test_el_panel_de_chats_necesita_el_token(self, cliente):
        assert cliente.get("/panel/chats").status_code in (401, 403, 404)
        assert cliente.get(f"/panel/chats?token={TOKEN}").status_code == 200

    def test_el_chat_muestra_lo_dicho_y_el_boton_de_devolver(self, cliente):
        c = cliente.contenedor
        _escribe_la_clienta(cliente, "hola, quiero un anillo", "wamid.1")
        c.bot._mundo.pausar_por_humano(CONV)

        pagina = cliente.get(f"/panel/chat?conv={CONV}&token={TOKEN}").text
        assert "quiero un anillo" in pagina
        assert "Que siga el bot" in pagina

    def test_devolver_desde_el_panel_reactiva_al_bot(self, cliente):
        c = cliente.contenedor
        c.bot._mundo.pausar_por_humano(CONV)
        cliente.post(
            f"/panel/devolver?token={TOKEN}", data={"conv": CONV}, follow_redirects=False
        )
        assert not c.bot._mundo.la_atiende_una_persona(CONV)
