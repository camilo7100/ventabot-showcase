"""El webhook ya contesta con el gestor nuevo. De punta a punta.

Esto es lo que cierra el rediseño: un mensaje entra por el webhook de Meta y
sale por la outbox convertido en las piezas que la clienta va a leer. Sin
esto, todo lo anterior era código que nadie llamaba.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.domain.models import Channel, InboundMessage

CONV = "wa:573001112233"


@pytest.fixture
def entorno(monkeypatch, tmp_path):
    import app.infra.container as contenedor
    from app.infra.settings import get_settings

    monkeypatch.setenv("REPOSITORY_BACKEND", "sqlite")
    monkeypatch.setenv("CHANNEL_BACKEND", "console")
    monkeypatch.setenv("LLM_BACKEND", "fake")
    monkeypatch.setenv("SQLITE_PATH", str(tmp_path / "t.db"))
    monkeypatch.setenv("URL_PUBLICA", "https://prueba.ngrok-free.dev")
    get_settings.cache_clear()
    contenedor._singleton = None
    yield contenedor.get_container()
    get_settings.cache_clear()
    contenedor._singleton = None


def _entra(c, texto, *, id_="wamid.1"):
    return c.procesar_mensaje(
        InboundMessage(
            channel=Channel.WHATSAPP,
            sender_id="573001112233",
            conversation_id=CONV,
            external_message_id=id_,
            text=texto,
            raw={},
        )
    )


class TestElWebhookContesta:
    def test_un_saludo_produce_una_respuesta(self, entorno):
        mensajes = _entra(entorno, "hola")
        assert mensajes
        assert "Luna Joyas" in mensajes[0].text

    def test_pedir_ejemplos_manda_TEXTO_FOTO_Y_LOS_DOS_VIDEOS(self, entorno):
        """El techo de un mensaje por turno era la causa real de que las
        imágenes no salieran nunca. Este test es el que lo vigila.

        Los videos van con la foto porque son lo que más vende: un anillo de
        plata con circones no se ve en una foto fija.
        """
        mensajes = _entra(entorno, "quiero ver ejemplos")
        tipos = [m.kind for m in mensajes]
        assert tipos[0] == "text", "las fotos llegan sin decir qué son"
        assert tipos.count("image") >= 1
        assert tipos.count("video") == 2

    def test_las_imagenes_llevan_una_URL_publica_absoluta(self, entorno):
        """Meta las baja desde internet: una ruta relativa no existe para
        sus servidores."""
        mensajes = _entra(entorno, "quiero ver ejemplos")
        for m in (x for x in mensajes if x.kind == "image"):
            assert m.media_url.startswith("https://prueba.ngrok-free.dev/media/")

    def test_todo_va_a_la_outbox(self, entorno):
        _entra(entorno, "hola")
        assert entorno.outbox.pending(10)

    def test_cada_pieza_tiene_su_clave_de_idempotencia(self, entorno):
        """Sin el índice en la clave, un turno de cuatro mensajes se
        deduplicaría a uno cuando Meta reenvíe el webhook — y lo reenvía."""
        mensajes = _entra(entorno, "quiero ver ejemplos")
        claves = [m.idempotency_key for m in mensajes]
        assert len(set(claves)) == len(claves)

    def test_el_webhook_repetido_no_manda_nada_dos_veces(self, entorno):
        _entra(entorno, "quiero ver ejemplos", id_="wamid.repetido")
        cuantos = len(entorno.outbox.pending(50))
        _entra(entorno, "quiero ver ejemplos", id_="wamid.repetido")
        assert len(entorno.outbox.pending(50)) == cuantos


class TestElContextoSobrevive:
    def test_la_conversacion_recuerda_entre_mensajes(self, entorno):
        """Lo que hace posible «el segundo»: el contexto se guarda en SQLite
        y se recupera en el turno siguiente."""
        _entra(entorno, "quiero un anillo de dos huellitas", id_="wamid.1")
        ctx = entorno.contexto.cargar(CONV)
        assert ctx.abiertos(), "no guardó la compra a medias"

        _entra(entorno, "corazon lila y dedos morados", id_="wamid.2")
        compra = entorno.contexto.cargar(CONV).abiertos()[0]
        assert compra.datos["huellitas"] == 2, "olvidó lo del mensaje anterior"
        assert len(compra.datos["colores"]) == 1

    def test_la_clienta_se_crea_sola_en_su_primer_mensaje(self, entorno):
        _entra(entorno, "hola")
        assert entorno.customers.get_by_channel_user("whatsapp", "573001112233")


class TestSinURLPublica:
    def test_las_imagenes_se_saltan_pero_el_texto_sale(self, monkeypatch, tmp_path):
        """Que falte una foto no puede dejar a la clienta sin la respuesta
        que la acompañaba."""
        import app.infra.container as contenedor
        from app.infra.settings import get_settings

        monkeypatch.setenv("REPOSITORY_BACKEND", "sqlite")
        monkeypatch.setenv("CHANNEL_BACKEND", "console")
        monkeypatch.setenv("LLM_BACKEND", "fake")
        monkeypatch.setenv("SQLITE_PATH", str(tmp_path / "t.db"))
        monkeypatch.setenv("URL_PUBLICA", "")
        get_settings.cache_clear()
        contenedor._singleton = None
        try:
            c = contenedor.get_container()
            mensajes = _entra(c, "quiero ver ejemplos")
            assert mensajes, "se quedó sin respuesta por no tener túnel"
            assert all(m.kind != "image" for m in mensajes)
        finally:
            get_settings.cache_clear()
            contenedor._singleton = None


class TestLaRutaDeMedia:
    def test_sirve_el_muestrario_sin_token(self, entorno):
        """Meta hace un GET anónimo: no puede mandar ningún token nuestro."""
        from app.api.main import app

        r = TestClient(app).get("/media/muestrario_circones")
        assert r.status_code == 200
        assert r.content[:3] == b"\xff\xd8\xff", "no es un JPEG"

    def test_no_se_puede_salir_de_la_carpeta(self, entorno):
        from app.api.main import app

        cliente = TestClient(app)
        for malicioso in ("../../.env", "..%2f..%2f.env", "noexiste"):
            assert cliente.get(f"/media/{malicioso}").status_code == 404

    def test_las_imagenes_del_catalogo_existen_en_disco(self):
        """Los nombres lógicos del redactor tienen que tener archivo. Si no,
        el bot promete una foto que nunca llega."""
        from app.conversacion.redactor import ADJUNTOS, ADJUNTOS_DEL_HUECO
        from app.conversacion.salida import ruta_de_imagen
        from app.infra.settings import get_settings

        carpeta = get_settings().imagenes_dir
        todos = [
            adjunto
            for tabla in (ADJUNTOS, ADJUNTOS_DEL_HUECO)
            for grupo in tabla.values()
            for adjunto in grupo
        ]
        faltan = [n for _, n, _ in todos if ruta_de_imagen(carpeta, n) is None]
        assert not faltan, f"nombres sin archivo: {faltan}"
        assert ruta_de_imagen(carpeta, "muestrario_circones") is not None
        assert ruta_de_imagen(carpeta, "anillo_video_1") is not None


class TestLosVideosSePuedenBajar:
    """Meta baja cada archivo con un GET ANÓNIMO desde internet.

    Si el content-type no cuadra, descarta el mensaje con un 400 que no
    explica nada. Es la parte que nadie prueba y la que rompe los videos.
    """

    def test_un_video_sale_como_video_mp4(self, entorno):
        from fastapi.testclient import TestClient

        from app.api.main import app

        r = TestClient(app).get("/media/anillo_video_1")
        assert r.status_code == 200
        assert r.headers["content-type"] == "video/mp4"
        assert len(r.content) > 100_000

    def test_una_foto_sigue_saliendo_como_jpeg(self, entorno):
        from fastapi.testclient import TestClient

        from app.api.main import app

        r = TestClient(app).get("/media/muestrario_circones")
        assert r.status_code == 200
        assert r.headers["content-type"] == "image/jpeg"

    def test_los_videos_caben_en_lo_que_Meta_acepta(self):
        """16 MB es el tope de Meta para un video."""
        from app.infra.settings import get_settings

        carpeta = get_settings().imagenes_dir
        for nombre in ("anillo_video_1.mp4", "anillo_video_2.mp4"):
            assert (carpeta / nombre).stat().st_size < 16 * 1024 * 1024

    def test_una_previsualizacion_recien_dibujada_tambien_se_puede_bajar(self, entorno):
        """Las vistas viven en otra carpeta que el catálogo. Si `/media` solo
        mirara una, el bot prometería una foto que nunca llega."""
        from fastapi.testclient import TestClient

        from app.adapters.render.huellita import RenderDeHuellitas
        from app.api.main import app
        from app.domain.personalizacion import ColorCircon, Huellita
        from app.infra.settings import get_settings

        s = get_settings()
        render = RenderDeHuellitas(
            s.imagenes_fuentes_dir / "huellita_base.jpg",
            s.imagenes_fuentes_dir / "huellita_mascaras.png",
            s.renders_dir,
        )
        nombre = render.previsualizar(
            [Huellita(corazon=ColorCircon.FUCSIA, dedos=ColorCircon.CELESTE)]
        )
        try:
            r = TestClient(app).get(f"/media/{nombre}")
            assert r.status_code == 200
            assert r.headers["content-type"] == "image/jpeg"
        finally:
            (s.renders_dir / f"{nombre}.jpg").unlink(missing_ok=True)


class TestUnFalloPuntualNoCuestaLaVenta:
    """El webhook contesta 200 a Meta y ATIENDE EN SEGUNDO PLANO.

    Eso convierte cualquier excepción del turno en silencio absoluto: Meta ya
    recibió su 200 y no reintenta, el mensaje ya está marcado como procesado
    así que el reintento se descartaría igual, y la clienta se queda mirando un
    chat donde nadie contestó nunca. Probándolo con la base de datos caída a
    mitad de turno, era exactamente lo que pasaba.
    """

    def test_con_la_base_caida_la_clienta_recibe_algo(self, entorno):
        _entra(entorno, "quiero un anillo de 1 huellita", id_="wamid.antes")
        entorno.contexto._db.cerrar()  # como si se cayera el disco

        mensajes = _entra(entorno, "corazón lila y dedos morados", id_="wamid.despues")
        assert mensajes, "silencio: la venta se pierde y no queda rastro"
        assert "personita" in mensajes[0].text

    def test_el_aviso_no_se_confunde_con_otro_mensaje(self, entorno):
        """Su clave de idempotencia es propia: si Meta reenvía el webhook, el
        aviso no se duplica ni pisa la respuesta de verdad."""
        entorno.contexto._db.cerrar()
        mensajes = _entra(entorno, "hola", id_="wamid.roto")
        assert mensajes[0].idempotency_key == "auxilio:wamid.roto"

    def test_el_turno_normal_no_pasa_por_el_aviso(self, entorno):
        mensajes = _entra(entorno, "hola")
        assert "personita" not in mensajes[0].text
