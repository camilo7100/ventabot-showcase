"""El catálogo del perfil de WhatsApp sale del mismo catálogo del bot (03/10)."""

from __future__ import annotations

import csv
import io
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.adapters.repositories.csv_files import cargar_catalogo_csv
from app.domain.catalogo_meta import COLUMNAS, catalogo_csv, imagen, titulo
from app.domain.models import Product

RAIZ = Path(__file__).resolve().parents[2]
PUBLICO = "https://bot.ejemplo.co"


def _filas(texto: str) -> list[dict]:
    return list(csv.DictReader(io.StringIO(texto)))


def _producto(**cambios) -> Product:
    base = {
        "sku": "ANI-HUE-2",
        "nombre": "Anillo huellita x2",
        "descripcion": "Dos huellitas.",
        "precio_cop": 250_000,
        "huellitas": 2,
        "imagen_url": "catalogo_anillo_2",
    }
    return Product(**(base | cambios))


class TestLaLista:
    def test_cada_producto_del_catalogo_con_su_precio_y_su_foto(self):
        productos = cargar_catalogo_csv(RAIZ / "data" / "catalogo.csv")
        filas = _filas(catalogo_csv(productos, PUBLICO))
        assert len(filas) == len([p for p in productos if p.activo])
        for fila, p in zip(filas, productos, strict=True):
            assert fila["id"] == p.sku
            assert fila["price"] == f"{p.precio_cop} COP"
            assert fila["image_link"].startswith(f"{PUBLICO}/media/")
            assert fila["availability"] == "in stock"
            assert fila["brand"] == "Luna Joyas"

    def test_las_fotos_existen(self):
        for p in cargar_catalogo_csv(RAIZ / "data" / "catalogo.csv"):
            nombre = imagen(p, PUBLICO).rsplit("/", 1)[1]
            assert list((RAIZ / "data" / "imagenes").glob(f"{nombre}.*")), nombre

    def test_columnas_de_meta(self):
        assert tuple(_filas(catalogo_csv([_producto()], PUBLICO))[0]) == COLUMNAS

    def test_titulo_para_la_clienta(self):
        assert titulo(_producto(huellitas=1)) == "Anillo de 1 huellita"
        assert titulo(_producto()) == "Anillo de 2 huellitas"
        cadena = _producto(categoria="cadenas", nombre="Cadena huellita con nombre")
        assert titulo(cadena) == "Cadena huellita con nombre"

    def test_direccion_completa_se_respeta(self):
        p = _producto(imagen_url="https://cdn.x/foto.jpg")
        assert imagen(p, PUBLICO) == "https://cdn.x/foto.jpg"

    def test_sin_foto_no_va(self):
        assert _filas(catalogo_csv([_producto(imagen_url=None)], PUBLICO)) == []


@pytest.fixture
def cliente(monkeypatch, tmp_path):
    import app.infra.container as contenedor
    from app.infra.settings import get_settings

    monkeypatch.setenv("REPOSITORY_BACKEND", "memory")
    monkeypatch.setenv("CHANNEL_BACKEND", "console")
    monkeypatch.setenv("LLM_BACKEND", "fake")
    monkeypatch.setenv("PUBLIC_URL", PUBLICO)
    monkeypatch.setenv("SQLITE_PATH", str(tmp_path / "t.db"))
    get_settings.cache_clear()
    contenedor._singleton = None
    from app.api.main import app

    yield TestClient(app)
    get_settings.cache_clear()
    contenedor._singleton = None


def test_la_direccion_publica_sirve_el_csv(cliente):
    r = cliente.get("/catalogo/whatsapp.csv")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/csv")
    filas = _filas(r.text)
    assert {f["id"] for f in filas} >= {"ANI-HUE-1", "ANI-HUE-2", "ANI-HUE-3"}
    assert all(f["image_link"].startswith(f"{PUBLICO}/media/") for f in filas)


class TestDesdeUnProducto:
    """La clienta toca «Enviar mensaje» en un producto del catálogo (03/10)."""

    @staticmethod
    def _mensaje(texto: str | None, sku: str | None):
        from app.domain.models import Channel, InboundMessage

        raw = {"type": "text"}
        if sku:
            raw["context"] = {
                "referred_product": {"catalog_id": "1", "product_retailer_id": sku}
            }
        return InboundMessage(
            channel=Channel.WHATSAPP,
            external_message_id="wamid.X",
            conversation_id="whatsapp:57300",
            sender_id="57300",
            text=texto,
            raw=raw,
        )

    def test_desde_la_cadena_el_texto_nombra_la_cadena(self):
        from app.domain.asesora import habla_de_cadena
        from app.domain.catalogo_meta import con_el_producto

        productos = cargar_catalogo_csv(RAIZ / "data" / "catalogo.csv")
        m = con_el_producto(self._mensaje("¿Cuánto se demora?", "CAD-HUE-1"), productos)
        assert m.text == (
            "[Escribe desde la vitrina de WhatsApp, mirando: Cadena huellita con "
            "nombre]\n¿Cuánto se demora?"
        )
        # Y así el bot SÍ puede hablarle de la cadena: ella la está mirando.
        assert habla_de_cadena(m.text)

    def test_desde_un_anillo(self):
        from app.domain.catalogo_meta import con_el_producto

        productos = cargar_catalogo_csv(RAIZ / "data" / "catalogo.csv")
        m = con_el_producto(self._mensaje(None, "ANI-HUE-2"), productos)
        assert m.text == (
            "[Escribe desde la vitrina de WhatsApp, mirando: Anillo de 2 huellitas]"
        )

    def test_sin_producto_no_cambia_nada(self):
        from app.domain.catalogo_meta import con_el_producto

        m = self._mensaje("hola", None)
        assert con_el_producto(m, []) is m

    def test_un_sku_que_ya_no_existe_se_dice_tal_cual(self):
        from app.domain.catalogo_meta import con_el_producto

        m = con_el_producto(self._mensaje("hola", "VIEJO-1"), [])
        assert m.text.startswith("[Escribe desde la vitrina de WhatsApp, mirando: VIEJO")


def test_mirar_un_anillo_no_abre_la_puerta_a_la_cadena():
    """La nota no puede sonar a «¿qué más tienen?»: con «catálogo» sonaba (03/10)."""
    from app.domain.asesora import pregunta_por_cadenas
    from app.domain.catalogo_meta import con_el_producto

    productos = cargar_catalogo_csv(RAIZ / "data" / "catalogo.csv")
    for p in productos:
        m = con_el_producto(TestDesdeUnProducto._mensaje("Hola", p.sku), productos)
        assert pregunta_por_cadenas(m.text) == (p.categoria == "cadenas"), p.sku
