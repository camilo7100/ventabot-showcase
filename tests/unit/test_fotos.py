"""Las fotos del anillo terminado: guardarlas, servirlas y mandarlas.

El mensaje que le pide $140.000 a una clienta funciona por una sola razón:
porque va con la foto de SU anillo. Sin la foto es un cobro; con la foto es
la entrega de algo que ella reconoce.

La parte delicada es que Meta baja esas imágenes con un GET ANÓNIMO desde
internet — no puede mandar nuestro token. La foto tiene que ser pública, y la
única defensa es que la URL no se pueda adivinar. Casi todos los tests de
aquí abajo son sobre eso.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.adapters.almacen_fotos import (
    MAX_BYTES,
    AlmacenDeFotos,
    FotoInvalida,
    detectar_tipo,
)
from app.domain.models import Channel, Customer, Order, OrderItem
from app.domain.operacion import CON_FOTOS, mensajes_con_fotos
from app.domain.order_state import OrderState

TOKEN = "token-de-prueba-1234"
JPG = b"\xff\xd8\xff" + b"contenido" * 10
PNG = b"\x89PNG\r\n\x1a\n" + b"contenido" * 10
WEBP = b"RIFF" + b"1234" + b"WEBP" + b"contenido" * 10

CLIENTA = Customer(
    id="c1", channel=Channel.WHATSAPP, channel_user_id="573001112233", nombre="Ángela"
)


@pytest.fixture
def almacen(tmp_path):
    return AlmacenDeFotos(tmp_path / "fotos")


def _pedido(estado=OrderState.PRODUCCION_LISTA, **kw) -> Order:
    base = {
        "codigo": "PED-2026-0417",
        "customer_id": "c1",
        "estado": estado.value,
        "items": [
            OrderItem(
                sku="ANI-HUE-1", nombre="Anillo", cantidad=1, precio_unitario_cop=200_000
            )
        ],
        "total_cop": 200_000,
        "anticipo_cop": 60_000,
        "saldo_cop": 140_000,
        "anticipo_pagado_cop": 60_000,
    }
    return Order(**{**base, **kw})


class TestQueSeAcepta:
    @pytest.mark.parametrize(
        ("datos", "tipo"),
        [(JPG, "image/jpeg"), (PNG, "image/png"), (WEBP, "image/webp")],
    )
    def test_los_tres_formatos_que_entiende_whatsapp(self, almacen, datos, tipo):
        assert almacen.guardar(datos).tipo == tipo

    def test_se_mira_el_CONTENIDO_y_no_la_extension(self):
        """El navegador manda el content-type que le da la gana. Un archivo
        que se llama .jpg y no lo es es la forma clásica de colar algo."""
        assert detectar_tipo(b"MZ\x90\x00esto es un ejecutable") is None
        assert detectar_tipo(b"<?php echo 1; ?>") is None
        assert detectar_tipo(JPG) == "image/jpeg"

    def test_un_RIFF_que_no_es_webp_se_rechaza(self):
        """RIFF también lo usan los .wav. Hay que mirar los cuatro bytes
        siguientes o se colaría un audio como si fuera una imagen."""
        assert detectar_tipo(b"RIFF1234WAVEfmt ") is None

    def test_una_foto_muy_pesada_se_explica_en_castellano(self, almacen):
        with pytest.raises(FotoInvalida, match="5 MB"):
            almacen.guardar(b"\xff\xd8\xff" + b"x" * MAX_BYTES)

    def test_un_archivo_vacio_no_se_guarda(self, almacen):
        with pytest.raises(FotoInvalida, match="vacío"):
            almacen.guardar(b"")

    def test_lo_que_no_es_imagen_dice_que_hacer(self, almacen):
        with pytest.raises(FotoInvalida, match="JPG, PNG o WEBP"):
            almacen.guardar(b"esto es un pdf o algo")


class TestLaURLNoSePuedeAdivinar:
    """La única defensa que hay, porque la foto tiene que ser pública."""

    def test_el_nombre_es_largo_y_aleatorio(self, almacen):
        nombre = almacen.guardar(JPG).nombre
        assert len(nombre) >= 32

    def test_dos_fotos_iguales_dan_nombres_distintos(self, almacen):
        """Si el nombre saliera del contenido, subir la misma foto para dos
        clientas daría la misma URL, y una vería la del otra."""
        assert almacen.guardar(JPG).nombre != almacen.guardar(JPG).nombre

    def test_no_hay_numeros_correlativos(self, almacen):
        """`/foto/1`, `/foto/2`… habría dejado las fotos de todas las
        clientas a la vista de cualquiera que supiera contar."""
        nombres = [almacen.guardar(JPG).nombre for _ in range(5)]
        assert not any(n.split(".")[0].isdigit() for n in nombres)
        assert len(set(nombres)) == 5


class TestNoSeEscapaDeLaCarpeta:
    @pytest.mark.parametrize(
        "malicioso",
        [
            "../../.env",
            "../../../etc/passwd",
            "..\\..\\.env",
            "/etc/passwd",
            "subcarpeta/foto.jpg",
            "",
            ".",
            "..",
        ],
    )
    def test_los_intentos_de_salir_devuelven_None(self, almacen, malicioso):
        """La vulnerabilidad más antigua que existe, y sigue apareciendo:
        sin esto, `/panel/foto/../../.env` serviría el archivo de secretos
        por una URL pública y sin token."""
        assert almacen.ruta_de(malicioso) is None

    def test_un_nombre_que_no_existe_devuelve_None(self, almacen):
        assert almacen.ruta_de("noexiste.jpg") is None

    def test_pero_una_foto_de_verdad_si_se_encuentra(self, almacen):
        nombre = almacen.guardar(JPG).nombre
        ruta = almacen.ruta_de(nombre)
        assert ruta is not None
        assert ruta.read_bytes() == JPG


class TestLasFotosViajanConElCobro:
    def test_van_solo_con_el_cobro_del_saldo(self):
        """Mandarlas también al despachar sería repetirle lo que ya vio."""
        assert {OrderState.ESPERANDO_SALDO} == CON_FOTOS
        pedido = _pedido(fotos=["a.jpg"])
        assert (
            mensajes_con_fotos(
                pedido, CLIENTA, OrderState.DESPACHADO, base_url="https://x"
            )
            == []
        )

    def test_una_imagen_por_mensaje_porque_asi_funciona_whatsapp(self):
        pedido = _pedido(fotos=["a.jpg", "b.jpg", "c.jpg"])
        ms = mensajes_con_fotos(
            pedido, CLIENTA, OrderState.ESPERANDO_SALDO, base_url="https://x.dev"
        )
        assert len(ms) == 3
        assert all(m.kind == "image" for m in ms)

    def test_la_url_es_absoluta_y_publica(self):
        """Meta baja la imagen desde internet: una ruta relativa o un
        localhost no existen para sus servidores."""
        ms = mensajes_con_fotos(
            _pedido(fotos=["abc.jpg"]),
            CLIENTA,
            OrderState.ESPERANDO_SALDO,
            base_url="https://algo.ngrok-free.dev/",
        )
        assert ms[0].media_url == "https://algo.ngrok-free.dev/panel/foto/abc.jpg"

    def test_sin_tunel_levantado_no_se_manda_ninguna(self):
        """Es preferible un cobro sin fotos a un cobro que no sale."""
        assert (
            mensajes_con_fotos(
                _pedido(fotos=["a.jpg"]),
                CLIENTA,
                OrderState.ESPERANDO_SALDO,
                base_url="",
            )
            == []
        )

    def test_un_pedido_sin_fotos_no_encola_nada(self):
        assert (
            mensajes_con_fotos(
                _pedido(), CLIENTA, OrderState.ESPERANDO_SALDO, base_url="https://x"
            )
            == []
        )

    def test_mandar_dos_veces_no_duplica(self):
        """La clave lleva el nombre del archivo, que ya es único."""
        pedido = _pedido(fotos=["a.jpg", "b.jpg"])
        unas = mensajes_con_fotos(
            pedido, CLIENTA, OrderState.ESPERANDO_SALDO, base_url="https://x"
        )
        otras = mensajes_con_fotos(
            pedido, CLIENTA, OrderState.ESPERANDO_SALDO, base_url="https://x"
        )
        assert [m.idempotency_key for m in unas] == [m.idempotency_key for m in otras]


# ---------------------------------------------------------------------------
# Contra el panel de verdad
# ---------------------------------------------------------------------------


@pytest.fixture
def entorno(monkeypatch, tmp_path):
    import app.infra.container as contenedor
    from app.infra.settings import get_settings

    monkeypatch.setenv("PANEL_TOKEN", TOKEN)
    monkeypatch.setenv("REPOSITORY_BACKEND", "memory")
    monkeypatch.setenv("CHANNEL_BACKEND", "console")
    monkeypatch.setenv("LLM_BACKEND", "fake")
    monkeypatch.setenv("SQLITE_PATH", str(tmp_path / "t.db"))
    monkeypatch.setenv("URL_PUBLICA", "https://prueba.ngrok-free.dev")
    get_settings.cache_clear()
    contenedor._singleton = None

    from app.api.main import app

    c = contenedor.get_container()
    c.customers.upsert(CLIENTA)
    yield TestClient(app), c

    get_settings.cache_clear()
    contenedor._singleton = None


class TestSubirYVer:
    def test_subir_una_foto_y_verla_en_el_panel(self, entorno):
        cliente, c = entorno
        pedido = c.orders.create(_pedido(), idem_key="k")

        cliente.post(
            f"/panel/fotos?token={TOKEN}",
            data={"pedido_id": pedido.id},
            files={"archivos": ("anillo.jpg", JPG, "image/jpeg")},
        )

        guardado = c.orders.get(pedido.id)
        assert len(guardado.fotos) == 1
        assert (
            f"/panel/foto/{guardado.fotos[0]}"
            in cliente.get(f"/panel?token={TOKEN}").text
        )

    def test_la_foto_se_sirve_SIN_token(self, entorno):
        """Tiene que ser así: los servidores de Meta no pueden mandarlo."""
        cliente, c = entorno
        pedido = c.orders.create(_pedido(), idem_key="k")
        cliente.post(
            f"/panel/fotos?token={TOKEN}",
            data={"pedido_id": pedido.id},
            files={"archivos": ("anillo.jpg", JPG, "image/jpeg")},
        )
        nombre = c.orders.get(pedido.id).fotos[0]

        r = cliente.get(f"/panel/foto/{nombre}")
        assert r.status_code == 200
        assert r.content == JPG
        assert "noindex" in r.headers.get("x-robots-tag", "")

    def test_una_foto_inventada_da_404(self, entorno):
        cliente, _ = entorno
        assert cliente.get("/panel/foto/loquesea.jpg").status_code == 404

    def test_subir_exige_token(self, entorno):
        cliente, c = entorno
        pedido = c.orders.create(_pedido(), idem_key="k")
        r = cliente.post(
            "/panel/fotos?token=malo",
            data={"pedido_id": pedido.id},
            files={"archivos": ("x.jpg", JPG, "image/jpeg")},
        )
        assert r.status_code == 404
        assert c.orders.get(pedido.id).fotos == []

    def test_una_foto_mala_no_tumba_las_buenas(self, entorno):
        """Que una foto pesada arruine la subida entera obligaría a Lía a
        adivinar cuál era."""
        cliente, c = entorno
        pedido = c.orders.create(_pedido(), idem_key="k")
        cliente.post(
            f"/panel/fotos?token={TOKEN}",
            data={"pedido_id": pedido.id},
            files=[
                ("archivos", ("buena.jpg", JPG, "image/jpeg")),
                ("archivos", ("mala.txt", b"no soy una imagen", "image/jpeg")),
                ("archivos", ("otra.png", PNG, "image/png")),
            ],
        )
        assert len(c.orders.get(pedido.id).fotos) == 2

    def test_subir_fotos_NO_cambia_el_estado_del_pedido(self, entorno):
        """`guardar_pedido` no puede ser una puerta trasera al candado que
        impide despachar sin cobrar."""
        cliente, c = entorno
        pedido = c.orders.create(_pedido(OrderState.ANTICIPO_PAGADO), idem_key="k")
        cliente.post(
            f"/panel/fotos?token={TOKEN}",
            data={"pedido_id": pedido.id},
            files={"archivos": ("x.jpg", JPG, "image/jpeg")},
        )
        assert c.orders.get(pedido.id).estado == OrderState.ANTICIPO_PAGADO.value

    def test_el_cobro_sale_con_las_fotos_EN_MEDIO(self, entorno):
        """El mensaje de Lía va partido y las fotos van dentro (Camilo, 20/09):

            1. «Hola 🌷 ¡Tu anillo ya está listo!» + los datos que necesita
               para la guía;
            2. las fotos del anillo;
            3. el cobro del saldo.

        Así ve su anillo entre el «ya está listo» y el número. Al revés, el
        número llega antes que el motivo."""
        cliente, c = entorno
        pedido = c.orders.create(_pedido(), idem_key="k")
        cliente.post(
            f"/panel/fotos?token={TOKEN}",
            data={"pedido_id": pedido.id},
            files=[
                ("archivos", ("a.jpg", JPG, "image/jpeg")),
                ("archivos", ("b.png", PNG, "image/png")),
            ],
        )
        cliente.post(
            f"/panel/mover?token={TOKEN}",
            data={"pedido_id": pedido.id, "destino": "ESPERANDO_SALDO"},
        )

        cola = c.outbox.pending(10)
        assert [m.kind for m in cola] == ["text", "image", "image", "text"]
        assert "ya está listo" in cola[0].text
        assert "Cédula" in cola[0].text, "no le pidió los datos de envío"
        assert all(
            m.media_url.startswith("https://prueba.ngrok-free.dev/panel/foto/")
            for m in cola[1:3]
        )
        assert "$140.000" in cola[-1].text
