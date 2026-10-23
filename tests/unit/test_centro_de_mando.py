"""La hoja CENTRO DE MANDO del ERP: dónde está el bot, escrito por el bot.

Camilo, 20/09: «si lo pongo en un servidor no sé dónde voy a ver ese link…
tal vez una hoja más del ERP, algo fácil y supremamente estándar para siempre
saber dónde buscar el panel total».

La dirección del bot cambia con el túnel y con la máquina; el ERP no. Así que
el bot escribe su dirección ahí al arrancar y cada 10 minutos, y la hora de
«visto vivo» dice además si sigue encendido.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from app.adapters.erp.sheets import ErpEnSheets, HojaEnMemoria
from app.infra.centro_de_mando import FILAS, NOMBRE_DE_LA_HOJA, filas_del_centro_de_mando

AHORA = datetime(2026, 9, 21, 2, 50, tzinfo=UTC)
TOKEN = "llave-del-panel-de-prueba"


def _filas(**cambios):
    datos = dict(
        publico="https://algo.ngrok-free.dev",
        local="http://127.0.0.1:8000",
        token=TOKEN,
        chatwoot_local="http://localhost:3000",
        arrancado=AHORA - timedelta(hours=3),
        ahora=AHORA,
        maquina="PC-DE-CAMILO",
        carpeta=Path(r"C:\Proyectos\ventabot"),
        excel=r"C:\Ventas.xlsx",
    )
    datos.update(cambios)
    return filas_del_centro_de_mando(**datos)


def _texto(filas) -> str:
    return "\n".join(" | ".join(str(c) for c in f) for f in filas)


class TestLoQueDice:
    def test_con_dominio_propio_chatwoot_tiene_su_direccion(self):
        """Desde el 25/09 el bot y Chatwoot tienen cada uno su subdominio."""
        texto = _texto(
            _filas(
                publico="https://bot.lunajoyas.example",
                chatwoot_publico="https://chat.lunajoyas.example",
            )
        )
        assert "https://chat.lunajoyas.example" in texto
        assert "https://bot.lunajoyas.example/panel" in texto

    def test_los_enlaces_llevan_la_direccion_publica_y_la_llave(self):
        texto = _texto(_filas())
        assert f"https://algo.ngrok-free.dev/panel/todo?token={TOKEN}" in texto
        assert f"https://algo.ngrok-free.dev/panel/chats?token={TOKEN}" in texto

    def test_sin_tunel_se_da_la_direccion_de_la_maquina(self):
        """Mejor un enlace que funciona en el PC que ninguno."""
        texto = _texto(_filas(publico=""))
        assert f"http://127.0.0.1:8000/panel/todo?token={TOKEN}" in texto

    def test_dice_donde_corre_y_cuando_se_le_vio_vivo(self):
        texto = _texto(_filas())
        assert "PC-DE-CAMILO" in texto
        # 02:50 UTC son las 21:50 del 20/09 en Colombia.
        assert "20/09/2026 · 21:50" in texto
        assert "APAGADO" in texto, "no explica cómo saber si está apagado"

    def test_siempre_ocupa_lo_mismo(self):
        """Si la lista se acorta, lo de la vez anterior se tiene que borrar
        en vez de quedarse ahí con datos viejos que parecen actuales."""
        assert len(_filas()) == FILAS
        assert all(len(f) == 3 for f in _filas())


class TestLasClavesQueNoVan:
    """La del panel sí: abre los enlaces, y quien ve el ERP ya ve lo mismo
    que el panel. Las de Meta, Claude, Chatwoot y Google NO: con ellas se
    gasta plata y se escribe por WhatsApp a nombre del negocio, y Google
    guarda el historial de cada celda para siempre."""

    def test_ninguna_clave_de_afuera_llega_a_la_hoja(self, monkeypatch, tmp_path):
        import app.infra.container as contenedor
        from app.infra.settings import get_settings

        secretos = {
            "ANTHROPIC_API_KEY": "sk-ant-NO-DEBE-SALIR-111",
            "WA_ACCESS_TOKEN": "EAAG-NO-DEBE-SALIR-222",
            "CHATWOOT_TOKEN": "cw-NO-DEBE-SALIR-333",
            "META_APP_SECRET": "meta-NO-DEBE-SALIR-444",
        }
        for k, v in secretos.items():
            monkeypatch.setenv(k, v)
        monkeypatch.setenv("PANEL_TOKEN", TOKEN)
        monkeypatch.setenv("SQLITE_PATH", str(tmp_path / "t.db"))
        get_settings.cache_clear()
        try:
            texto = _texto(contenedor._filas_de_accesos(get_settings()))
        finally:
            get_settings.cache_clear()
        for nombre, valor in secretos.items():
            assert valor not in texto, f"{nombre} se coló en la hoja del ERP"
        assert TOKEN in texto, "la llave del panel sí tiene que estar"
        assert ".env" in texto, "tiene que decir DÓNDE están las demás"


@pytest.fixture
def erp(monkeypatch):
    """El ERP sin su hilo de fondo: aquí se le llama a mano."""
    import app.adapters.erp.sheets as sheets

    class _SinHilo:
        def __init__(self, *a, **kw):
            pass

        def start(self):
            pass

    monkeypatch.setattr(sheets.threading, "Thread", _SinHilo)
    hoja = HojaEnMemoria({"Ventas": [], "Pagos": [], "Produccion": []})
    return hoja, ErpEnSheets(
        hoja,
        pedidos=list,
        cuando=dict,
        accesos=_filas,
        hoja_de_accesos=NOMBRE_DE_LA_HOJA,
    )


class TestLaHojaEnElErp:
    def test_se_crea_y_queda_la_primera(self, erp):
        """Es lo que se ve al abrir el ERP: el sitio de siempre."""
        hoja, e = erp
        e.publicar_accesos()
        assert next(iter(hoja.hojas)) == NOMBRE_DE_LA_HOJA

    def test_se_escribe_entera(self, erp):
        hoja, e = erp
        e.publicar_accesos()
        texto = _texto(hoja.hojas[NOMBRE_DE_LA_HOJA])
        assert f"/panel/todo?token={TOKEN}" in texto

    def test_si_ya_existe_no_se_mueve(self, erp):
        """Si alguien la cambió de sitio, se respeta."""
        hoja, e = erp
        hoja.hojas = {"Ventas": [], NOMBRE_DE_LA_HOJA: []}
        e.publicar_accesos()
        assert next(iter(hoja.hojas)) == "Ventas"

    def test_un_fallo_aqui_no_tumba_nada(self, erp):
        """Las ventas son lo que importa del ERP: esta hoja no puede
        costarlas."""
        hoja, e = erp

        def _rota(*a, **kw):
            raise RuntimeError("hoja protegida")

        hoja.escribir = _rota
        e.publicar_accesos()  # no revienta

    def test_sin_accesos_no_se_toca_nada(self, monkeypatch):
        import app.adapters.erp.sheets as sheets

        monkeypatch.setattr(
            sheets.threading,
            "Thread",
            type("_", (), {"__init__": lambda s, *a, **k: None, "start": lambda s: None}),
        )
        hoja = HojaEnMemoria({"Ventas": []})
        ErpEnSheets(hoja, pedidos=list, cuando=dict).publicar_accesos()
        assert NOMBRE_DE_LA_HOJA not in hoja.hojas


class TestLasPruebasNoTocanElErpDeVerdad:
    """20/09. Una prueba con REPOSITORY_BACKEND=sqlite construía el contenedor
    con el ID y la credencial del `.env` y arrancaba un ERP DE VERDAD. La suite
    y el bot crearon a la vez la hoja CENTRO DE MANDO y Google dejó una
    segunda «_conflict». Con pedidos pagados, habrían sido ventas de mentira
    en el ERP del negocio."""

    def test_un_contenedor_sqlite_de_prueba_no_tiene_erp(self, monkeypatch, tmp_path):
        import app.infra.container as contenedor
        from app.infra.settings import get_settings

        monkeypatch.setenv("REPOSITORY_BACKEND", "sqlite")
        monkeypatch.setenv("SQLITE_PATH", str(tmp_path / "t.db"))
        get_settings.cache_clear()
        contenedor._singleton = None
        try:
            assert contenedor.get_container().erp is None, (
                "la suite arrancó el ERP de verdad"
            )
        finally:
            get_settings.cache_clear()
            contenedor._singleton = None

    def test_los_repasos_tampoco(self, monkeypatch, tmp_path):
        """21/09: 33 repasos escribieron en la hoja CENTRO DE MANDO del ERP de
        verdad enlaces a `https://ejemplo.local`. `repasar.py` apagaba WhatsApp
        y Chatwoot, pero no el ERP. Aquí se monta el contenedor con SU entorno,
        el mismo que usa cada repaso, y con el ERP del `.env` disponible."""
        import app.adapters.erp.sheets as sheets
        import app.infra.container as contenedor
        from app.infra.settings import get_settings
        from scripts.repasar import ENTORNO_DEL_REPASO

        # Un Google de mentira que SIEMPRE abre: así, si el ERP no está
        # apagado, arranca de verdad y la prueba lo ve. Con una credencial
        # inválida el ERP no arrancaría nunca y la prueba pasaría sin probar
        # nada (primera versión de esta prueba, 21/09).
        monkeypatch.setattr(sheets, "SheetsDeGoogle", lambda *a, **k: object())
        monkeypatch.setattr(
            sheets.threading,
            "Thread",
            type("_", (), {"__init__": lambda s, *a, **k: None, "start": lambda s: None}),
        )
        # Lo que habría en el .env de quien corre el repaso.
        monkeypatch.setenv("SHEETS_SPREADSHEET_ID", "hoja-de-verdad")
        credencial = tmp_path / "cuenta.json"
        credencial.write_text("{}", encoding="utf-8")
        monkeypatch.setenv("GOOGLE_SERVICE_ACCOUNT_JSON", str(credencial))
        monkeypatch.setenv("CHATWOOT_URL", "http://chatwoot-de-verdad")
        for clave, valor in ENTORNO_DEL_REPASO.items():
            monkeypatch.setenv(clave, valor)
        monkeypatch.setenv("LLM_BACKEND", "fake")  # aquí no se paga al modelo
        monkeypatch.setenv("SQLITE_PATH", str(tmp_path / "repaso.db"))
        get_settings.cache_clear()
        contenedor._singleton = None
        try:
            c = contenedor.get_container()
            assert c.erp is None, "el repaso arrancó el ERP de verdad"
            assert c.crm is None, "el repaso copia a Chatwoot"
        finally:
            get_settings.cache_clear()
            contenedor._singleton = None
