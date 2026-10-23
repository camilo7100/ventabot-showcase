"""Los colores en el panel (30/09): nombre y coordenadas de cada bolsita.

Lía los cambia como cambia los envíos, sin tocar código. Lo que importa es que
el nombre nuevo llegue a TODAS partes: el resumen, el pie de la foto, lo que
dice la IA y lo que el vigilante deja pasar.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.domain import personalizacion as p
from app.domain.personalizacion import ColorCircon as C

TOKEN = "token-de-prueba-1234"


@pytest.fixture
def entorno(monkeypatch, tmp_path):
    import app.infra.container as contenedor
    from app.infra.settings import get_settings

    monkeypatch.setenv("PANEL_TOKEN", TOKEN)
    monkeypatch.setenv("REPOSITORY_BACKEND", "sqlite")
    monkeypatch.setenv("CHANNEL_BACKEND", "console")
    monkeypatch.setenv("LLM_BACKEND", "fake")
    monkeypatch.setenv("SQLITE_PATH", str(tmp_path / "t.db"))
    get_settings.cache_clear()
    contenedor._singleton = None
    from app.api.main import app

    c = contenedor.get_container()
    yield TestClient(app), c
    get_settings.cache_clear()
    contenedor._singleton = None


class TestLaPaleta:
    def test_los_nombres_de_la_foto_del_muestrario(self):
        assert p.NOMBRE_COLOR[C.CELESTE] == "celeste turquesa"
        assert p.NOMBRE_COLOR[C.AZUL_REY] == "azul zafiro"
        assert p.NOMBRE_COLOR[C.ROSADO] == "rosa"
        assert p.NOMBRE_COLOR[C.DURAZNO] == "champagne"

    def test_coordenadas_de_ida_y_vuelta(self):
        assert p.hsv_a_hex(0, 100, 100) == "#FF0000"
        assert p.hex_a_hsv("#FF0000") == (0, 100, 100)
        assert p.hex_a_hsv(p.hsv_a_hex(255, 58, 67)) == (255, 58, 67)

    @pytest.mark.parametrize("malo", ["", "a", "azul 2", "rosa 🌸", "x" * 31])
    def test_nombres_que_no_sirven(self, malo):
        with pytest.raises(ValueError):
            p.validar_nombre_de_color(malo, C.ROSADO)

    def test_no_se_repite_el_nombre_de_otra_bolsita(self):
        with pytest.raises(ValueError, match="otra bolsita"):
            p.validar_nombre_de_color("Lila", C.MORADO)


class TestElPanel:
    def test_la_pagina_lista_las_catorce(self, entorno):
        cliente, _ = entorno
        pagina = cliente.get(f"/panel/colores?token={TOKEN}").text
        assert pagina.count("<form method=post class=color") == 14
        assert "azul zafiro" in pagina and "Tono (°)" in pagina

    def test_cambiar_nombre_y_coordenadas_llega_a_todas_partes(self, entorno):
        cliente, c = entorno
        r = cliente.post(
            f"/panel/colores?token={TOKEN}",
            data={
                "clave": "DURAZNO",
                "nombre": "Champaña",
                "tono": "28",
                "saturacion": "60",
                "brillo": "80",
            },
            follow_redirects=False,
        )
        assert r.status_code == 303
        assert p.NOMBRE_COLOR[C.DURAZNO] == "champaña"
        assert p.HEX_COLOR[C.DURAZNO] == p.hsv_a_hex(28, 60, 80)
        # Quedó en la tabla, que es la que manda al volver a arrancar.
        fila = next(f for f in c.colores.todos() if f.color is C.DURAZNO)
        assert (fila.nombre, fila.tinte) == ("champaña", p.hsv_a_hex(28, 60, 80))
        h = p.Huellita(corazon=C.DURAZNO, dedos=C.BLANCO)
        assert "champaña" in p.nombres_de_los_colores([h])

    def test_un_nombre_malo_se_explica(self, entorno):
        cliente, _ = entorno
        r = cliente.post(
            f"/panel/colores?token={TOKEN}",
            data={
                "clave": "LILA",
                "nombre": "morado",
                "tono": "0",
                "saturacion": "0",
                "brillo": "0",
            },
        )
        assert r.status_code == 400 and "otra bolsita" in r.text


class TestLaIAUsaLosNombresVigentes:
    def test_el_prompt_cambia_cuando_cambia_la_paleta(self):
        from app.conversacion.asesora import Asesora, HechosDelNegocio
        from tests.unit.test_asesora import Guion

        a = Asesora(
            None,
            Guion(),
            "{hechos} Colores: {colores}. Nombres: {nombres_colores}.",
            HechosDelNegocio(precios={1: 200_000}),
        )
        assert "AZUL_REY = azul zafiro" in a._system
        p.aplicar_paleta({C.AZUL_REY: ("azul noche", p.HEX_COLOR[C.AZUL_REY])})
        assert "AZUL_REY = azul noche" in a._system and "azul zafiro" not in a._system

    def test_el_vigilante_deja_decir_los_nombres_nuevos(self):
        from app.domain.asesora import vigilar

        frase = "Te queda divino en celeste turquesa y champagne 😍"
        assert vigilar(frase, set()) == (frase, [])


class TestProbarAntesDeGuardar:
    """Cada número que se mueve redibuja «Ahora» al instante, sin guardar nada;
    «Guardado» es lo que recibe la clienta hasta tocar Guardar (30/09)."""

    def test_probar_dibuja_sin_guardar_nada(self, entorno):
        cliente, c = entorno
        antes = dict(p.HEX_COLOR), dict(p.ACABADO_COLOR)
        en_disco = set(c.settings.renders_dir.glob("*"))
        r = cliente.get(
            f"/panel/colores/vista?token={TOKEN}&clave=LILA&tono=200&saturacion=80"
            "&brillo=90&facetas=70&destellos=40&fuego=6"
        )
        assert r.status_code == 200 and r.headers["content-type"] == "image/jpeg"
        assert r.headers["cache-control"] == "no-store"
        assert antes == (p.HEX_COLOR, p.ACABADO_COLOR), "probar no guarda nada"
        assert set(c.settings.renders_dir.glob("*")) == en_disco

    def test_sin_numeros_es_la_imagen_de_la_clienta(self, entorno):
        cliente, _ = entorno
        r = cliente.get(
            f"/panel/colores/vista?token={TOKEN}&clave=LILA", follow_redirects=False
        )
        assert r.status_code == 302 and r.headers["location"].startswith("/media/vista_")

    def test_un_numero_fuera_de_rango_no_dibuja(self, entorno):
        cliente, _ = entorno
        r = cliente.get(f"/panel/colores/vista?token={TOKEN}&clave=LILA&fuego=150")
        assert r.status_code == 400

    def test_la_pagina_tiene_los_seis_numeros_y_las_dos_vistas(self, entorno):
        cliente, _ = entorno
        pagina = cliente.get(f"/panel/colores?token={TOKEN}").text
        for campo in (
            "tono",
            "saturacion",
            "brillo",
            "facetas",
            "destellos",
            "fuego",
        ):
            assert pagina.count(f"type=range data-de={campo} ") == 14
            assert pagina.count(f"type=number name={campo} ") == 14
        assert pagina.count("class=antes") == 14 and pagina.count("class=ahora") == 14
        assert pagina.count("class=deshacer>") == 14 and "Sin guardar" in pagina
        assert pagina.count("class=fabrica>") == 14

    def test_guardar_lo_probado_es_lo_que_recibe_la_clienta(self, entorno):
        cliente, c = entorno
        numeros = {
            "tono": "280",
            "saturacion": "40",
            "brillo": "90",
            "facetas": "75",
            "destellos": "30",
            "fuego": "8",
        }
        r = cliente.post(
            f"/panel/colores?token={TOKEN}",
            data={"clave": "LILA", "nombre": "lila", **numeros},
            follow_redirects=False,
        )
        assert r.status_code == 303
        fila = next(f for f in c.colores.todos() if f.color is C.LILA)
        assert fila.tinte == p.hsv_a_hex(280, 40, 90)
        assert fila.acabado == p.Acabado(facetas=75, destellos=30, fuego=8)
        assert p.ACABADO_COLOR[C.LILA] == fila.acabado, "aplicado sin reiniciar"
        guardada = cliente.get(
            f"/panel/colores/vista?token={TOKEN}&clave=LILA", follow_redirects=False
        ).headers["location"]
        h = p.Huellita(corazon=C.LILA, dedos=C.LILA)
        assert guardada == f"/media/{c.render.nombre_de([h])}"

    def test_la_tabla_vieja_recibe_las_columnas_del_acabado(self, tmp_path):
        """Producción ya tenía `colores_circon` sin facetas/destellos/fuego."""
        from app.adapters.repositories.colores_sqlite import SqliteColores
        from app.adapters.repositories.sqlite_store import SqliteDB

        db = SqliteDB(tmp_path / "vieja.db")
        db.ejecutar(
            "CREATE TABLE colores_circon (clave TEXT PRIMARY KEY, nombre TEXT NOT "
            "NULL, tinte TEXT NOT NULL, actualizado TEXT NOT NULL)"
        )
        db.ejecutar(
            "INSERT INTO colores_circon VALUES ('LILA', 'lavanda', '#947FBE', 'x')"
        )
        fila = next(f for f in SqliteColores(db).todos() if f.color is C.LILA)
        assert (fila.nombre, fila.acabado) == ("lavanda", p.Acabado())


class TestUnCambioLlegaATodoLoDemas:
    """Camilo, 30/09: «si muevo algo en el panel se debe editar todo lo demás».
    Un nombre nuevo se ENTIENDE cuando lo escribe la clienta, no solo se dice."""

    def _rebautizar(self, cliente, clave: str, nombre: str):
        return cliente.post(
            f"/panel/colores?token={TOKEN}",
            data={
                "clave": clave,
                "nombre": nombre,
                "tono": "26",
                "saturacion": "64",
                "brillo": "75",
            },
            follow_redirects=False,
        )

    def test_el_bot_entiende_el_nombre_nuevo(self, entorno):
        from app.conversacion.interprete import describe_una_huellita
        from app.domain.colores_texto import leer_colores

        cliente, _ = entorno
        assert leer_colores("corazón atardecer y dedos negros").corazon is None
        assert self._rebautizar(cliente, "DURAZNO", "Atardecer").status_code == 303
        lectura = leer_colores("corazón atardecer y dedos negros")
        assert (lectura.corazon, lectura.dedos) == (C.DURAZNO, C.NEGRO)
        assert describe_una_huellita().match("una huellita atardecer")

    def test_un_nombre_que_ya_es_otro_color_no_se_guarda(self, entorno):
        cliente, _ = entorno
        r = self._rebautizar(cliente, "LILA", "violeta")
        assert r.status_code == 400 and "ya quiere decir" in r.text
        assert p.NOMBRE_COLOR[C.LILA] == "lila"

    def test_los_nombres_de_fabrica_se_pueden_volver_a_guardar(self, entorno):
        _, c = entorno
        for fila in c.colores.todos():
            c.colores.fijar(fila.color, fila.nombre, fila.tinte)

    def test_avisa_que_la_foto_del_muestrario_dice_otro_nombre(self, entorno):
        cliente, _ = entorno
        assert (
            "La foto del muestrario dice"
            not in cliente.get(f"/panel/colores?token={TOKEN}").text
        )
        self._rebautizar(cliente, "DURAZNO", "Champaña")
        pagina = cliente.get(f"/panel/colores?token={TOKEN}").text
        assert pagina.count("La foto del muestrario dice «champagne»") == 1

    def test_guardar_sin_tocar_el_color_deja_el_tinte_exacto(self, entorno):
        """Los números van redondeados: #947FBE ida y vuelta da #9580BF."""
        cliente, c = entorno
        tono, saturacion, brillo = p.hex_a_hsv("#947FBE")
        cliente.post(
            f"/panel/colores?token={TOKEN}",
            data={
                "clave": "LILA",
                "nombre": "lila",
                "tono": str(tono),
                "saturacion": str(saturacion),
                "brillo": str(brillo),
                "facetas": "60",
            },
        )
        fila = next(f for f in c.colores.todos() if f.color is C.LILA)
        assert (fila.tinte, fila.acabado.facetas) == ("#947FBE", 60)


class TestElBlancoEsLaFotoDelDiamante:
    """Camilo, 30/09: el blanco «estaba mejor antes», cuando era la foto tal
    cual. Con su tinte y su acabado de fábrica, la piedra dibujada ES la foto."""

    def test_el_blanco_de_fabrica_es_la_foto(self):
        from pathlib import Path

        import numpy as np
        from PIL import Image

        from app.adapters.render.huellita import RenderDeHuellitas

        img = Path(__file__).resolve().parents[2] / "data" / "imagenes" / "fuentes"
        r = RenderDeHuellitas(
            img / "huellita_base.jpg", img / "huellita_mascaras.png", Path("/tmp")
        )
        foto = np.asarray(Image.open(img / "huellita_base.jpg").convert("RGB"))
        dibujo = np.asarray(r._una(p.Huellita(corazon=C.BLANCO, dedos=C.BLANCO), {}, {}))
        _, mascaras = r._cargar()
        diferencia = np.abs(dibujo.astype(int) - foto.astype(int))[mascaras == 1]
        assert diferencia.mean() < 3, "el corazón blanco es el diamante de la foto"

    def test_los_colores_no_llevan_el_arcoiris_de_fabrica(self):
        assert (
            all(p.ACABADO_COLOR[c].fuego == 0 for c in C if c is not C.BLANCO)
            and p.ACABADO_COLOR[C.BLANCO].fuego == 100
        )

    def test_la_tabla_de_produccion_recibe_el_fuego_por_bolsita(self, tmp_path):
        """La tabla ya tenía facetas/destellos/estrellas, sin fuego: se agrega el
        fuego de cada bolsita y se borra la columna de las estrellitas."""
        from app.adapters.repositories.colores_sqlite import SqliteColores
        from app.adapters.repositories.sqlite_store import SqliteDB

        db = SqliteDB(tmp_path / "prod.db")
        db.ejecutar(
            "CREATE TABLE colores_circon (clave TEXT PRIMARY KEY, nombre TEXT NOT "
            "NULL, tinte TEXT NOT NULL, actualizado TEXT NOT NULL, facetas INTEGER "
            "NOT NULL DEFAULT 50, destellos INTEGER NOT NULL DEFAULT 10, estrellas "
            "INTEGER NOT NULL DEFAULT 0)"
        )
        db.ejecutar(
            "INSERT INTO colores_circon VALUES "
            "('BLANCO', 'blanco', '#EDEFF2', 'x', 50, 10, 0), "
            "('ROJO', 'rojo', '#C60026', 'x', 50, 10, 0)"
        )
        filas = {f.color: f for f in SqliteColores(db).todos()}
        assert filas[C.BLANCO].acabado.fuego == 100
        assert filas[C.ROJO].acabado.fuego == 0
        columnas = {f["name"] for f in db.consultar("PRAGMA table_info(colores_circon)")}
        assert "estrellas" not in columnas
