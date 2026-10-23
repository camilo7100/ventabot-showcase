"""«El flujo» del panel: Lía ve cada mensaje preestablecido, tal cual sale.

Lo que importa: que los textos sean LOS DE VERDAD (salen de las mismas
constantes que usa el bot), que cada mensaje tenga un código único para poder
pedir un cambio («cambia el B2»), y que ningún `{hueco}` quede sin llenar.
"""

from __future__ import annotations

import html
import re

import pytest
from fastapi.testclient import TestClient

TOKEN = "token-de-prueba-1234"


@pytest.fixture
def pagina(monkeypatch, tmp_path):
    import app.infra.container as contenedor
    from app.infra.settings import get_settings

    monkeypatch.setenv("PANEL_TOKEN", TOKEN)
    monkeypatch.setenv("REPOSITORY_BACKEND", "memory")
    monkeypatch.setenv("CHANNEL_BACKEND", "console")
    monkeypatch.setenv("LLM_BACKEND", "fake")
    monkeypatch.setenv("TALLA_LA_CONFIRMA_LIA", "true")
    monkeypatch.setenv("SQLITE_PATH", str(tmp_path / "t.db"))
    get_settings.cache_clear()
    contenedor._singleton = None

    from app.api.main import app

    r = TestClient(app).get(f"/panel/flujo?token={TOKEN}")
    yield r
    get_settings.cache_clear()
    contenedor._singleton = None


def _texto(r) -> str:
    return html.unescape(r.text)


class TestLaPagina:
    def test_abre(self, pagina):
        assert pagina.status_code == 200

    def test_sin_la_llave_no_abre(self, pagina):
        from app.api.main import app

        assert TestClient(app).get("/panel/flujo").status_code == 404

    def test_los_textos_son_los_de_verdad(self, pagina):
        from app.conversacion.asesora import (
            CONFIRMA_EL_RESUMEN,
            GUIA_TALLA,
            PREGUNTA_DE_LA_TALLA,
            SALUDO_DE_APERTURA,
            TALLA_EN_ESPERA,
            TALLA_EN_REVISION,
        )
        from app.domain.recordatorios import CUERPO_DE_LA_PLANTILLA, PRIMEROS

        texto = _texto(pagina)
        for real in (
            SALUDO_DE_APERTURA,
            PREGUNTA_DE_LA_TALLA,
            TALLA_EN_REVISION,
            TALLA_EN_ESPERA,
            CONFIRMA_EL_RESUMEN,
            PRIMEROS["talla_guia"],
            CUERPO_DE_LA_PLANTILLA.split("{{2}}")[1].strip(),
        ):
            assert real in texto, f"falta: {real[:40]}"
        assert GUIA_TALLA.split("*")[0] in texto
        assert "Tu anillo *PED-2026-0417* ya entró al taller" in texto

    def test_cada_mensaje_tiene_un_codigo_unico(self, pagina):
        codigos = re.findall(r"<span class=cod>([A-Z]\d+)</span>", pagina.text)
        assert len(codigos) >= 30
        assert len(codigos) == len(set(codigos)), "dos mensajes con el mismo código"
        assert {"A1", "B2", "E1", "F3", "G1"} <= set(codigos)

    def test_ningun_hueco_queda_sin_llenar(self, pagina):
        cuerpo = _texto(pagina).split("<section id='la-ia'>")[0]
        cuerpo = re.sub(r"<style>.*?</style>", "", cuerpo, flags=re.S)
        assert not re.findall(r"\{[a-z_]+\}", cuerpo)

    def test_trae_las_fotos_y_los_videos(self, pagina):
        for archivo in ("presentacion_video_1", "medir_talla_guia", "muestrario"):
            assert f"/media/{archivo}" in pagina.text

    def test_trae_las_instrucciones_de_la_ia(self, pagina):
        assert "Sus instrucciones completas" in pagina.text
        assert "EL FLUJO DE UNA VENTA" in _texto(pagina)

    def test_el_taller_enlaza_al_flujo(self, pagina):
        from app.api.main import app

        taller = TestClient(app).get(f"/panel?token={TOKEN}").text
        assert f"/panel/flujo?token={TOKEN}" in taller
