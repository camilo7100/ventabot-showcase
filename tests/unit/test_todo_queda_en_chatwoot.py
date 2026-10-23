"""Todo lo que le llega a una clienta queda en Chatwoot.

26/09/2026: Lía verificó un abono desde el panel, a la clienta le llegó «tu
anillo ya entró al taller» y en Chatwoot no aparecía. La auditoría encontró el
mismo hueco en cinco caminos más: cada uno encolaba por su lado. Ahora todo pasa
por `Container.enviar_a_la_clienta`, que encola Y copia a Chatwoot.

Una prueba por camino. Si alguien vuelve a encolar por fuera de la puerta, se
cae la suya.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.adapters.crm.chatwoot import CrmDeMentira
from app.domain.models import (
    Channel,
    Customer,
    Order,
    OrderItem,
    Payment,
    PaymentKind,
)

TOKEN = "token-de-prueba-1234"
NUMERO = "573001112233"
CONV = f"wa:{NUMERO}"
CLIENTA = Customer(
    id="c1", channel=Channel.WHATSAPP, channel_user_id=NUMERO, nombre="Ángela"
)


@pytest.fixture
def entorno(monkeypatch, tmp_path):
    import app.infra.container as contenedor
    from app.infra.settings import get_settings

    monkeypatch.setenv("PANEL_TOKEN", TOKEN)
    monkeypatch.setenv("REPOSITORY_BACKEND", "memory")
    monkeypatch.setenv("CHANNEL_BACKEND", "console")
    monkeypatch.setenv("LLM_BACKEND", "fake")
    monkeypatch.setenv("SQLITE_PATH", str(tmp_path / "t.db"))
    get_settings.cache_clear()
    contenedor._singleton = None

    from app.api.main import app

    c = contenedor.get_container()
    c.customers.upsert(CLIENTA)
    espejo = CrmDeMentira()
    monkeypatch.setattr(c, "crm", espejo)
    yield TestClient(app), c, espejo

    get_settings.cache_clear()
    contenedor._singleton = None


def _salientes(espejo: CrmDeMentira) -> list[str]:
    return [t for conv, t, kw in espejo.copias if kw.get("entrante") is False]


class TestLaPuertaUnica:
    def test_encola_y_copia(self, entorno):
        from app.domain.models import OutboundMessage

        _, c, espejo = entorno
        c.enviar_a_la_clienta(
            CONV,
            OutboundMessage(
                channel=Channel.WHATSAPP, to=NUMERO, text="hola", idempotency_key="k"
            ),
        )
        assert [m.text for m in c.outbox.pending(10)] == ["hola"]
        assert _salientes(espejo) == ["hola"]

    def test_si_chatwoot_falla_el_mensaje_sale_igual(self, entorno, monkeypatch):
        from app.domain.models import OutboundMessage

        _, c, espejo = entorno

        def revienta(*a, **kw):
            raise RuntimeError("Chatwoot caído")

        monkeypatch.setattr(espejo, "registrar", revienta)
        c.enviar_a_la_clienta(
            CONV,
            OutboundMessage(
                channel=Channel.WHATSAPP, to=NUMERO, text="hola", idempotency_key="k"
            ),
        )
        assert [m.text for m in c.outbox.pending(10)] == ["hola"]


class TestCadaCamino:
    def test_lo_que_lia_escribe_en_el_panel(self, entorno):
        cliente, _, espejo = entorno
        cliente.post(
            f"/panel/responder?token={TOKEN}",
            data={"conv": CONV, "texto": "Hola Ángela, soy Lía 💓"},
        )
        assert "Hola Ángela, soy Lía 💓" in _salientes(espejo)

    def test_el_auxilio_cuando_el_turno_se_cae(self, entorno, monkeypatch):
        from app.domain.models import InboundMessage

        _, c, espejo = entorno

        def se_cae(m):
            raise RuntimeError("se cayó el turno")

        monkeypatch.setattr(c, "_atender", se_cae)
        m = InboundMessage(
            channel=Channel.WHATSAPP,
            sender_id=NUMERO,
            conversation_id=CONV,
            text="hola, quiero un anillo",
            external_message_id="wamid.1",
        )
        c.procesar_mensaje(m)
        entrantes = [t for _, t, kw in espejo.copias if kw.get("entrante") is True]
        assert "hola, quiero un anillo" in entrantes, "no quedó lo que ella escribió"
        assert c.AUXILIO in _salientes(espejo), "no quedó lo que se le respondió"

    def test_el_pago_confirmado_va_a_su_numero_y_queda(self, entorno):
        _, c, espejo = entorno
        pedido = Order(
            codigo="PED-2026-0001",
            customer_id="c1",
            estado="ESPERANDO_ANTICIPO",
            items=[
                OrderItem(
                    sku="ANI-HUE-1", nombre="Anillo", cantidad=1, precio_unitario_cop=1
                )
            ],
            total_cop=1,
        )
        pago = Payment(
            order_id="o1", tipo=PaymentKind.ANTICIPO, monto_esperado_cop=60_000
        )
        c.notificar_pago_confirmado(pedido, pago)
        (mensaje,) = c.outbox.pending(10)
        assert mensaje.to == NUMERO, "iba al id interno de la clienta, no a su número"
        assert _salientes(espejo) == [mensaje.text]

    def test_el_recordatorio(self, entorno):
        from datetime import UTC, datetime

        from app.workers.recordatorios import Envio, mandar

        _, c, espejo = entorno

        class Registro:
            def anotar(self, *a):
                return True

        r = Envio(
            conversation_id=CONV,
            numero=1,
            etapa="abono",
            ancla="2026-10-04T12:00:00+00:00",
            cuando=datetime.now(UTC),
            texto="Hola Ángela 💜 Te escribo por si te quedó alguna duda",
        )
        assert mandar(r, Registro(), c.enviar_a_la_clienta)
        assert _salientes(espejo) == [r.texto]
        (mensaje,) = c.outbox.pending(10)
        assert mensaje.to == NUMERO


class TestLaDisculpaALasAtrasadas:
    """17/10: las 28 disculpas de las 8 a. m. salieron por WhatsApp y en
    Chatwoot no se veía ninguna: `vb retomar` encolaba por su lado."""

    def _atrasado(self, wamid: str, dias: int = 3):
        from datetime import UTC, datetime, timedelta

        from app.domain.models import InboundMessage

        escrito = datetime.now(UTC) - timedelta(days=dias)
        return InboundMessage(
            channel=Channel.WHATSAPP,
            sender_id=NUMERO,
            conversation_id=CONV,
            text=f"hola {wamid}",
            external_message_id=wamid,
            timestamp=escrito,
            raw={"timestamp": str(int(escrito.timestamp()))},
        )

    def test_la_del_bot_solo_queda_en_chatwoot_una_vez(self, entorno, monkeypatch):
        from datetime import UTC, datetime

        from app.domain import plantilla_de_emergencia as emergencia
        from app.domain.plantilla_de_emergencia import NOMBRE, PLANTILLAS

        _, c, espejo = entorno
        monkeypatch.setattr(emergencia, "cuando_mandarla", lambda ahora: None)  # de día
        c._emergencia = (datetime.now(UTC), NOMBRE)
        c.procesar_mensaje(self._atrasado("wamid.a"))
        c.procesar_mensaje(self._atrasado("wamid.a"))  # Meta reintenta
        c.procesar_mensaje(self._atrasado("wamid.b", dias=4))  # otro atrasado suyo
        assert _salientes(espejo) == [PLANTILLAS[NOMBRE]], "una sola disculpa"
        assert len(c.outbox.pending(10)) == 1

    def test_la_de_vb_retomar_queda_en_chatwoot(self, entorno, monkeypatch):
        import sys
        from datetime import UTC, datetime

        from app.domain.plantilla_de_emergencia import NOMBRE, PLANTILLAS
        from scripts import retomar_atrasadas

        _, c, espejo = entorno
        c._emergencia = (datetime.now(UTC), NOMBRE)
        monkeypatch.setattr(retomar_atrasadas, "build_container", lambda: c)
        monkeypatch.setattr(
            retomar_atrasadas,
            "atrasadas_sin_atender",
            lambda _c: [
                {"conv": CONV, "id": 1, "escrito": datetime(2026, 10, 10, tzinfo=UTC)}
            ],
        )
        monkeypatch.setattr(sys, "argv", ["retomar", "--enviar", "--ya"])
        assert retomar_atrasadas.main() == 0
        assert _salientes(espejo) == [PLANTILLAS[NOMBRE]]


def test_lo_programado_no_se_copia_hasta_que_sale(entorno):
    """La disculpa de las 8 a. m. se copiaba al programarla, de noche: en
    Chatwoot quedaba antes de tiempo, o fuera de orden (Jannet, 17/10)."""
    from datetime import UTC, datetime, timedelta

    from app.domain.models import OutboundMessage

    _, c, espejo = entorno
    c.enviar_a_la_clienta(
        CONV,
        OutboundMessage(
            channel=Channel.WHATSAPP, to=NUMERO, text="disculpa", idempotency_key="k"
        ),
        enviar_despues=datetime.now(UTC) + timedelta(hours=8),
    )
    assert _salientes(espejo) == []
    [fila] = c.db.consultar("SELECT payload FROM outbox")
    assert OutboundMessage.model_validate_json(fila["payload"]).copiar_al_salir


def test_nadie_encola_por_fuera_de_la_puerta():
    """Lo que le llega a una clienta pasa por `enviar_a_la_clienta` (encola Y
    copia a Chatwoot). Las únicas excepciones: el turno del bot (lo copia
    `_copiar_al_crm`), la puerta misma y lo que Lía escribe EN Chatwoot (ya
    está ahí). Un `outbox.enqueue(` nuevo en otro lado tumba esta prueba."""
    from pathlib import Path

    raiz = Path(__file__).resolve().parents[2]
    permitidos = {"app/infra/container.py": 2, "app/api/main.py": 2}
    encontrados = {}
    for carpeta in ("app", "scripts"):
        for archivo in (raiz / carpeta).rglob("*.py"):
            n = archivo.read_text(encoding="utf-8").count("outbox.enqueue(")
            if n:
                encontrados[archivo.relative_to(raiz).as_posix()] = n
    assert encontrados == permitidos
