"""De qué anuncio llegó la clienta, y a qué venta se le cuenta (ADR 0028).

Lo que tiene que ser verdad:
  · el `referral` del primer mensaje se lee (si no se lee ahí, no vuelve);
  · la clienta guarda el PRIMER anuncio (no cambia) y el ÚLTIMO;
  · el pedido nace con el último anuncio, si fue hace menos de 28 días, y ya
    no se mueve;
  · guardar otra cosa de la clienta no borra de dónde llegó;
  · el Excel de ventas lo muestra en sus columnas;
  · nada de esto puede tumbar un turno.

Los payloads tienen la forma del ejemplo de la documentación de Meta
(Cloud API → Webhooks → messages → «Click to WhatsApp ad»).
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from datetime import UTC, datetime, timedelta

import pytest

from app.adapters.channels.whatsapp import WhatsAppAdapter, referido_de
from app.adapters.repositories.memory import InMemoryCustomerRepository
from app.adapters.repositories.sqlite_store import SqliteCustomerRepository, SqliteDB
from app.domain.anuncios import (
    VENTANA_DE_ATRIBUCION_DIAS,
    Referido,
    anuncio_del_pedido,
    con_toque,
    dias_desde,
)
from app.domain.models import Channel, Customer, Order
from app.domain.personalizacion import ColorCircon, Huellita, Personalizacion
from app.domain.ventas import COLUMNAS_VENTAS, fila_de_venta
from app.workers.agrupador import fundir

NUMERO = "573001112233"
CONV = f"wa:{NUMERO}"
#: 2025-08-24 01:46:40 UTC
TS = 1756000000
#: El `ctwa_clid` del ejemplo de Meta (guía de la Conversions API).
CLID = (
    "ARAkLkA8rmlFeiCktEJQ-QTwRiyYHAFDLMNDBH0CD3qpjd0HR4irJ6LEkR7JwFF4XvnO2E4Nx0-"
    "eM-GABDLOPaOdRMv-_zfUQ2a"
)


def referral(
    anuncio_id: str = "120210000000000001",
    *,
    medio: str = "image",
    clid: str | None = CLID,
) -> dict:
    """El objeto `referral` tal como lo documenta Meta para un anuncio CTWA."""
    r = {
        "source_url": "https://fb.me/3cr4Wqqkv",
        "source_id": anuncio_id,
        "source_type": "ad",
        "body": "Tu mascota, en plata 925, para siempre contigo 🐾",
        "headline": "Anillo con las huellitas de tu peludo",
        "media_type": medio,
        "welcome_message": {"text": "¡Hola! ¿Me cuentas más del anillo?"},
    }
    if medio == "image":
        r["image_url"] = "https://scontent.xx.fbcdn.net/v/t45.1600-4/anuncio.jpg"
    else:
        r["video_url"] = "https://video.xx.fbcdn.net/v/t42.1790-2/anuncio.mp4"
        r["thumbnail_url"] = "https://scontent.xx.fbcdn.net/v/t15.5256-10/mini.jpg"
    if clid is not None:
        r["ctwa_clid"] = clid
    return r


def payload(texto: str, mid: str, *, ref: dict | None = None, ts: int = TS) -> dict:
    """Un webhook de Meta con un mensaje de texto, con o sin `referral`."""
    mensaje = {
        "from": NUMERO,
        "id": mid,
        "timestamp": str(ts),
        "type": "text",
        "text": {"body": texto},
    }
    if ref is not None:
        mensaje["referral"] = ref
    return {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": "WHATSAPP_BUSINESS_ACCOUNT_ID",
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
                                {"profile": {"name": "Sheena"}, "wa_id": NUMERO}
                            ],
                            "messages": [mensaje],
                        },
                    }
                ],
            }
        ],
    }


def adaptador() -> WhatsAppAdapter:
    return WhatsAppAdapter("TEST", "token", "secreto", "verify")


def toque(anuncio_id: str = "A1", cuando: datetime | None = None) -> Referido:
    return Referido(
        anuncio_id=anuncio_id,
        tipo="ad",
        titulo=f"Anuncio {anuncio_id}",
        ctwa_clid=f"clid-{anuncio_id}",
        cuando=cuando or datetime(2026, 9, 1, tzinfo=UTC),
    )


# ══════════════════════════════════════════════════════════════════════════
#  1. LEER EL REFERRAL DEL WEBHOOK
# ══════════════════════════════════════════════════════════════════════════


class TestElParser:
    def test_lee_el_anuncio_del_ejemplo_de_meta(self):
        [m] = adaptador().parse_webhook(payload("Hola", "wamid.1", ref=referral()))

        r = m.referido
        assert r is not None
        assert r.anuncio_id == "120210000000000001"
        assert r.tipo == "ad"
        assert r.url == "https://fb.me/3cr4Wqqkv"
        assert r.titulo == "Anillo con las huellitas de tu peludo"
        assert r.texto.startswith("Tu mascota, en plata 925")
        assert r.medio == "image"
        assert r.ctwa_clid.startswith("ARAkLkA8rmlFeiCktEJQ")
        assert r.cuando == datetime.fromtimestamp(TS, tz=UTC)
        # El mensaje sigue siendo el mismo de siempre.
        assert m.text == "Hola"
        assert m.sender_name == "Sheena"

    def test_un_anuncio_de_video_tambien(self):
        [m] = adaptador().parse_webhook(
            payload("Hola", "wamid.1", ref=referral(medio="video"))
        )
        assert m.referido is not None
        assert m.referido.medio == "video"

    def test_las_url_de_la_imagen_no_se_guardan_porque_caducan(self):
        [m] = adaptador().parse_webhook(payload("Hola", "wamid.1", ref=referral()))
        guardado = m.referido.model_dump_json()
        assert "fbcdn" not in guardado

    def test_un_anuncio_en_estados_llega_sin_ctwa_clid(self):
        """Meta omite `ctwa_clid` en los anuncios de Estados de WhatsApp. El
        anuncio igual cuenta: el id es lo que cruza con el costo."""
        [m] = adaptador().parse_webhook(
            payload("Hola", "wamid.1", ref=referral(clid=None))
        )
        assert m.referido is not None
        assert m.referido.anuncio_id == "120210000000000001"
        assert m.referido.ctwa_clid == ""

    def test_sin_referral_no_hay_anuncio(self):
        [m] = adaptador().parse_webhook(payload("Hola", "wamid.1"))
        assert m.referido is None

    def test_un_referral_sin_id_de_anuncio_no_cuenta(self):
        r = referral()
        del r["source_id"]
        [m] = adaptador().parse_webhook(payload("Hola", "wamid.1", ref=r))
        assert m.referido is None

    def test_un_referral_raro_no_tumba_el_webhook(self):
        assert referido_de({"timestamp": str(TS), "referral": "no-es-un-objeto"}) is None
        r = referido_de({"referral": {"source_id": 12345}})  # sin timestamp
        assert r is not None and r.anuncio_id == "12345"

    def test_la_foto_del_anuncio_con_texto_tambien_trae_el_anuncio(self):
        """El primer mensaje puede ser una foto: el referral va igual."""
        p = payload("x", "wamid.1", ref=referral())
        msg = p["entry"][0]["changes"][0]["value"]["messages"][0]
        msg["type"] = "image"
        msg["image"] = {"id": "MEDIA", "mime_type": "image/jpeg", "caption": "mira"}
        del msg["text"]
        [m] = adaptador().parse_webhook(p)
        assert m.referido is not None and m.media[0].kind == "image"


# ══════════════════════════════════════════════════════════════════════════
#  2. PRIMER Y ÚLTIMO TOQUE, Y LA VENTANA
# ══════════════════════════════════════════════════════════════════════════


class TestToques:
    def test_el_primer_toque_es_el_primero_y_el_ultimo_tambien(self):
        a = toque("A")
        assert con_toque(None, a) == (a, a)

    def test_un_toque_nuevo_cambia_el_ultimo_y_no_el_primero(self):
        a, b = toque("A"), toque("B")
        assert con_toque(a, b) == (a, b)

    def test_el_pedido_se_le_cuenta_al_ultimo_anuncio_dentro_de_la_ventana(self):
        clic = datetime(2026, 9, 1, tzinfo=UTC)
        assert (
            anuncio_del_pedido(toque("A", clic), clic + timedelta(days=3)).anuncio_id
            == "A"
        )
        limite = clic + timedelta(days=VENTANA_DE_ATRIBUCION_DIAS)
        assert anuncio_del_pedido(toque("A", clic), limite - timedelta(minutes=1))
        assert anuncio_del_pedido(toque("A", clic), limite) is None

    def test_sin_anuncio_no_hay_a_quien_contarle_el_pedido(self):
        assert anuncio_del_pedido(None, datetime.now(UTC)) is None

    def test_dias_desde_el_anuncio(self):
        clic = datetime(2026, 9, 1, 10, tzinfo=UTC)
        assert dias_desde(toque("A", clic), clic + timedelta(days=2, hours=3)) == 2
        assert dias_desde(toque("A", clic), clic - timedelta(seconds=5)) == 0
        assert dias_desde(None, clic) is None


class TestNoSeBorraDeDondeLlego:
    """Guardar la clienta por otro motivo (un nombre, el motor viejo que la
    crea de cero) no puede borrar de qué anuncio llegó."""

    @pytest.mark.parametrize("repo", ["sqlite", "memoria"])
    def test_guardar_una_clienta_sin_anuncios_conserva_los_que_tenia(
        self, tmp_path, repo
    ):
        clientas = (
            SqliteCustomerRepository(SqliteDB(tmp_path / "c.db"))
            if repo == "sqlite"
            else InMemoryCustomerRepository()
        )
        clientas.upsert(
            Customer(
                channel=Channel.WHATSAPP,
                channel_user_id=NUMERO,
                primer_anuncio=toque("A"),
                ultimo_anuncio=toque("B"),
            )
        )
        clientas.upsert(
            Customer(channel=Channel.WHATSAPP, channel_user_id=NUMERO, nombre="Sara")
        )
        c = clientas.get_by_channel_user("whatsapp", NUMERO)
        assert c.nombre == "Sara"
        assert c.primer_anuncio.anuncio_id == "A"
        assert c.ultimo_anuncio.anuncio_id == "B"


# ══════════════════════════════════════════════════════════════════════════
#  3. DE PUNTA A PUNTA: WEBHOOK → CLIENTA → PEDIDO → EXCEL
# ══════════════════════════════════════════════════════════════════════════


@pytest.fixture
def cliente(tmp_path, monkeypatch):
    """App real con base SQLite temporal, sin modelo y sin Meta."""
    from fastapi.testclient import TestClient

    import app.infra.container as contenedor
    from app.infra.settings import Settings

    s = Settings(
        sqlite_path=tmp_path / "test.db",
        repository_backend="sqlite",
        llm_backend="fake",
        payment_backend="fake",
        channel_backend="console",
        meta_app_secret="secreto-de-prueba",
        meta_verify_token="verify-de-prueba",
        dispatcher_interval_s=0.05,
        ventas_excel=tmp_path / "v.xlsx",
        ventas_cada_s=0,
    )
    c = contenedor.build_container(s)
    monkeypatch.setattr(contenedor, "_singleton", c)
    from app.api.main import app

    with TestClient(app) as tc:
        tc.contenedor = c
        yield tc
    c.cerrar()


def postear(tc, cuerpo_dict: dict):
    cuerpo = json.dumps(cuerpo_dict).encode()
    firma = "sha256=" + hmac.new(b"secreto-de-prueba", cuerpo, hashlib.sha256).hexdigest()
    r = tc.post(
        "/webhook/whatsapp",
        content=cuerpo,
        headers={"Content-Type": "application/json", "X-Hub-Signature-256": firma},
    )
    assert r.status_code == 200
    return r


def _pedido(c):
    return c.bot._mundo.crear_pedido(
        CONV,
        1,
        Personalizacion(
            huellitas=[Huellita(corazon=ColorCircon.NEGRO, dedos=ColorCircon.NEGRO)],
            grabados=["Rocky"],
            talla=7,
        ),
    )


class TestDePuntaAPunta:
    def test_el_anuncio_del_webhook_queda_en_la_clienta(self, cliente):
        ahora = int(datetime.now(UTC).timestamp())
        postear(cliente, payload("Hola", "wamid.1", ref=referral("AD-1"), ts=ahora))

        c = cliente.contenedor.bot._mundo.cliente_de(CONV)
        assert c.primer_anuncio.anuncio_id == "AD-1"
        assert c.ultimo_anuncio.anuncio_id == "AD-1"
        assert c.ultimo_anuncio.ctwa_clid.startswith("ARAkLkA8")

    def test_vuelve_por_otro_anuncio_cambia_el_ultimo_y_no_el_primero(self, cliente):
        ahora = int(datetime.now(UTC).timestamp())
        postear(cliente, payload("Hola", "wamid.1", ref=referral("AD-1"), ts=ahora))
        postear(cliente, payload("¿Precio?", "wamid.2", ts=ahora + 5))
        postear(
            cliente,
            payload("Hola otra vez", "wamid.3", ref=referral("AD-2"), ts=ahora + 60),
        )

        c = cliente.contenedor.bot._mundo.cliente_de(CONV)
        assert c.primer_anuncio.anuncio_id == "AD-1"
        assert c.ultimo_anuncio.anuncio_id == "AD-2"

    def test_el_pedido_nace_con_el_anuncio_y_no_se_mueve(self, cliente):
        c = cliente.contenedor
        ahora = int(datetime.now(UTC).timestamp())
        postear(cliente, payload("Hola", "wamid.1", ref=referral("AD-1"), ts=ahora))

        pedido = _pedido(c)
        assert pedido.anuncio is not None
        assert pedido.anuncio.anuncio_id == "AD-1"
        assert c.orders.get(pedido.id).anuncio.anuncio_id == "AD-1"

        # Después toca otro anuncio: el pedido que ya existía sigue con el suyo.
        postear(cliente, payload("Hola", "wamid.2", ref=referral("AD-2"), ts=ahora + 60))
        assert c.orders.get(pedido.id).anuncio.anuncio_id == "AD-1"

    def test_sin_anuncio_el_pedido_nace_sin_anuncio(self, cliente):
        postear(cliente, payload("Hola", "wamid.1"))
        assert _pedido(cliente.contenedor).anuncio is None

    def test_un_clic_viejo_no_se_cuenta(self, cliente):
        viejo = datetime.now(UTC) - timedelta(days=VENTANA_DE_ATRIBUCION_DIAS + 1)
        postear(
            cliente,
            payload("Hola", "wamid.1", ref=referral("AD-1"), ts=int(viejo.timestamp())),
        )
        c = cliente.contenedor
        assert c.bot._mundo.cliente_de(CONV).ultimo_anuncio.anuncio_id == "AD-1"
        assert _pedido(c).anuncio is None

    def test_el_excel_de_ventas_trae_el_anuncio(self, cliente):
        openpyxl = pytest.importorskip("openpyxl")
        from app.adapters.excel.libro_ventas import LibroDeVentas
        from app.adapters.repositories.ventas import BaseDeVentas
        from app.workers.ventas import sincronizar

        c = cliente.contenedor
        ahora = int(datetime.now(UTC).timestamp())
        postear(cliente, payload("Hola", "wamid.1", ref=referral("AD-1"), ts=ahora))
        pedido = _pedido(c)

        ruta = c.settings.ventas_excel
        sincronizar(BaseDeVentas(c.db), LibroDeVentas(ruta))

        hoja = openpyxl.load_workbook(ruta)["Ventas"]
        titulos = [x.value for x in hoja[1]]
        fila = next(
            [x.value for x in f]
            for f in hoja.iter_rows(min_row=2)
            if f[titulos.index("ID venta")].value == pedido.id
        )
        assert fila[titulos.index("Anuncio")] == "AD-1"
        assert fila[titulos.index("Anuncio (titular)")] == (
            "Anillo con las huellitas de tu peludo"
        )
        assert fila[titulos.index("Días desde el anuncio")] == 0
        assert fila[titulos.index("Primer anuncio")] == "AD-1"


class TestRafaga:
    def test_en_una_rafaga_el_anuncio_del_primer_mensaje_no_se_pierde(self, cliente):
        """La ráfaga se funde sobre el ÚLTIMO mensaje, y el anuncio viene en
        el PRIMERO."""
        ahora = int(datetime.now(UTC).timestamp())
        primero, segundo = (
            adaptador().parse_webhook(p)[0]
            for p in (
                payload("Hola", "wamid.1", ref=referral("AD-1"), ts=ahora),
                payload("quiero el anillo", "wamid.2", ts=ahora + 2),
            )
        )
        rafaga = fundir([primero, segundo])
        assert rafaga.referido is None  # la base es el último…

        c = cliente.contenedor
        c.procesar_mensaje(rafaga)
        assert c.bot._mundo.cliente_de(CONV).primer_anuncio.anuncio_id == "AD-1"


class TestNuncaTumbaElTurno:
    def test_si_anotar_el_anuncio_falla_igual_se_contesta(self, cliente, monkeypatch):
        c = cliente.contenedor

        def roto(*a, **k):
            raise RuntimeError("disco lleno")

        monkeypatch.setattr(c.bot._mundo, "anotar_anuncio", roto)
        # Reciente: uno escrito hace más de 24 h llega «atrasado» y no se contesta.
        ahora = int(time.time())
        [m] = adaptador().parse_webhook(
            payload("Hola", "wamid.1", ref=referral(), ts=ahora)
        )
        salida = c.procesar_mensaje(m)
        assert salida
        assert all(x.text != c.AUXILIO for x in salida)


# ══════════════════════════════════════════════════════════════════════════
#  4. LA FILA DEL EXCEL
# ══════════════════════════════════════════════════════════════════════════


class TestFilaDeVenta:
    def test_las_columnas_del_anuncio_son_del_sistema(self):
        duenos = {c.clave: c.dueno for c in COLUMNAS_VENTAS}
        for clave in (
            "anuncio",
            "anuncio_titulo",
            "dias_desde_anuncio",
            "primer_anuncio",
        ):
            assert duenos[clave] == "sistema"

    def test_sin_anuncio_las_columnas_quedan_vacias(self):
        pedido = Order(codigo="PED-1", customer_id="c1", estado="BORRADOR")
        fila = fila_de_venta(pedido, None, {})
        assert fila["anuncio"] == ""
        assert fila["anuncio_titulo"] == ""
        assert fila["dias_desde_anuncio"] is None
        assert fila["primer_anuncio"] == ""

    def test_primer_y_ultimo_pueden_ser_distintos(self):
        clic = datetime(2026, 9, 10, tzinfo=UTC)
        pedido = Order(
            codigo="PED-1",
            customer_id="c1",
            estado="ANTICIPO_PAGADO",
            anuncio=toque("B", clic),
            created_at=clic + timedelta(days=4),
        )
        clienta = Customer(
            id="c1",
            channel=Channel.WHATSAPP,
            channel_user_id=NUMERO,
            primer_anuncio=toque("A"),
            ultimo_anuncio=toque("B", clic),
        )
        fila = fila_de_venta(pedido, clienta, {})
        assert fila["anuncio"] == "B"
        assert fila["anuncio_titulo"] == "Anuncio B"
        assert fila["dias_desde_anuncio"] == 4
        assert fila["primer_anuncio"] == "A"

    def test_el_ctwa_clid_no_va_al_excel(self):
        """Es un id de clic para devolverle a Meta, no un dato para leer."""
        pedido = Order(
            codigo="PED-1", customer_id="c1", estado="BORRADOR", anuncio=toque("A")
        )
        fila = fila_de_venta(pedido, None, {})
        assert "clid-A" not in {str(v) for v in fila.values()}
