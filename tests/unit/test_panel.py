"""El panel del taller: que Lía pueda trabajar, y que nadie más pueda mirar.

Se prueban tres cosas, en este orden de importancia:

  1. SEGURIDAD. El panel muestra nombres, teléfonos y montos de clientas
     reales, y el servidor se publica por un túnel al internet abierto.
  2. QUE LA REGLA DE NEGOCIO MANDE. El botón «despachar» no puede existir si
     no se ha cobrado el saldo, y no porque alguien se acuerde de esconderlo.
  3. QUE SE VEA LO QUE HAY QUE HACER.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.domain.models import Order, OrderItem
from app.domain.operacion import acciones_de, bandejas, dias_esperando
from app.domain.order_state import TRANSICIONES, OrderState
from app.domain.personalizacion import ColorCircon, Huellita, Personalizacion

TOKEN = "token-de-prueba-1234"


def _pedido(estado: OrderState, codigo: str = "PED-2026-0417", **kw) -> Order:
    base = dict(
        codigo=codigo,
        customer_id="c1",
        estado=estado.value,
        items=[
            OrderItem(
                sku="ANI-HUE-1",
                nombre="Anillo huellita x1",
                cantidad=1,
                precio_unitario_cop=200_000,
            )
        ],
        total_cop=200_000,
        anticipo_cop=60_000,
        saldo_cop=140_000,
    )
    return Order(**{**base, **kw})


def _completo(estado: OrderState, **kw) -> Order:
    """Un pedido al 100 %: diseño, talla y envío. Solo así entra al taller."""
    from app.domain.envio import DatosDeEnvio
    from app.domain.personalizacion import ColorCircon, Huellita, Personalizacion

    diseno = Personalizacion(
        talla=7,
        huellitas=[Huellita(corazon=ColorCircon.NEGRO, dedos=ColorCircon.NEGRO)],
        grabados=["Rocky"],
    )
    item = OrderItem(
        sku="ANI-HUE-1",
        nombre="Anillo huellita x1",
        cantidad=1,
        precio_unitario_cop=200_000,
        personalizacion=diseno,
    )
    envio = DatosDeEnvio(nombre="Ángela Pérez", ciudad="Bogotá", direccion="Cl 45 #12-30")
    return _pedido(estado, **{"items": [item], "envio": envio, **kw})


@pytest.fixture
def app_con_panel(monkeypatch, tmp_path):
    """Servidor con el panel ENCENDIDO y un pedido dentro."""
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
    yield app, c

    get_settings.cache_clear()
    contenedor._singleton = None


@pytest.fixture
def cliente(app_con_panel):
    app, _ = app_con_panel
    return TestClient(app)


class TestSeguridad:
    def test_sin_token_no_hay_panel(self, cliente):
        assert cliente.get("/panel").status_code == 404

    def test_con_token_equivocado_tampoco(self, cliente):
        assert cliente.get("/panel?token=otracosa").status_code == 404

    def test_responde_404_y_no_403(self, cliente):
        """Un 403 le confirma a quien sondea que aquí hay algo que abrir.
        Un 404 no dice nada."""
        r = cliente.get("/panel?token=x")
        assert r.status_code == 404
        assert "panel" not in r.text.lower()

    def test_con_PANEL_TOKEN_vacio_el_panel_NO_EXISTE(self, monkeypatch, tmp_path):
        """El valor por defecto. Un panel abierto por olvido es una fuga de
        datos de clientas, así que encenderlo tiene que ser deliberado."""
        import app.infra.container as contenedor
        from app.infra.settings import get_settings

        monkeypatch.setenv("PANEL_TOKEN", "")
        monkeypatch.setenv("REPOSITORY_BACKEND", "memory")
        monkeypatch.setenv("CHANNEL_BACKEND", "console")
        monkeypatch.setenv("LLM_BACKEND", "fake")
        monkeypatch.setenv("SQLITE_PATH", str(tmp_path / "t.db"))
        get_settings.cache_clear()
        contenedor._singleton = None
        try:
            from app.api.main import app

            assert TestClient(app).get("/panel?token=").status_code == 404
        finally:
            get_settings.cache_clear()
            contenedor._singleton = None

    def test_no_se_deja_indexar_ni_filtra_el_enlace(self, cliente):
        """El token va en la URL. Si Google indexa la página o el navegador
        manda el Referer a otro sitio, el token se escapa con él."""
        r = cliente.get(f"/panel?token={TOKEN}")
        assert "noindex" in r.text
        assert "no-referrer" in r.text

    def test_mover_tambien_exige_token(self, cliente, app_con_panel):
        _, c = app_con_panel
        pedido = c.orders.create(_pedido(OrderState.ANTICIPO_PAGADO), idem_key="k")
        r = cliente.post(
            "/panel/mover?token=malo",
            data={"pedido_id": pedido.id, "destino": "EN_PRODUCCION"},
        )
        assert r.status_code == 404
        assert c.orders.get(pedido.id).estado == OrderState.ANTICIPO_PAGADO.value


class TestLaReglaDeNegocioMandaSobreLaPantalla:
    def test_desde_produccion_lista_NO_hay_boton_de_despachar(
        self, cliente, app_con_panel
    ):
        """LA prueba. No se despacha sin cobrar el saldo, y el botón no
        existe porque la transición no existe — no porque alguien lo escondió."""
        _, c = app_con_panel
        c.orders.create(_pedido(OrderState.PRODUCCION_LISTA), idem_key="k")
        texto = cliente.get(f"/panel?token={TOKEN}").text
        assert "Cobrar el saldo" in texto
        assert "Despachado" not in texto

    def test_los_botones_salen_de_la_tabla_de_transiciones(self):
        """Para todos los estados, no solo para el que probamos a mano."""
        for estado in OrderState:
            botones = {a.destino for a in acciones_de(_pedido(estado))}
            permitidos = TRANSICIONES[estado] - {estado}
            if estado is OrderState.EN_REVISION_PAGO:
                # Solo los del pago que se revisa (abono o saldo), nunca los dos.
                assert botones < permitidos
            else:
                assert botones == permitidos, f"el panel miente en {estado.value}"

    def test_con_un_pago_en_revision_solo_salen_sus_botones(self):
        S = OrderState
        abono = {a.destino for a in acciones_de(_pedido(S.EN_REVISION_PAGO))}
        assert S.ANTICIPO_PAGADO in abono and S.SALDO_PAGADO not in abono
        saldo = {
            a.destino
            for a in acciones_de(_pedido(S.EN_REVISION_PAGO, anticipo_pagado_cop=60_000))
        }
        assert S.SALDO_PAGADO in saldo and S.ANTICIPO_PAGADO not in saldo

    def test_un_estado_inventado_se_rechaza(self, cliente, app_con_panel):
        _, c = app_con_panel
        pedido = c.orders.create(_pedido(OrderState.ANTICIPO_PAGADO), idem_key="k")
        r = cliente.post(
            f"/panel/mover?token={TOKEN}",
            data={"pedido_id": pedido.id, "destino": "REGALADO"},
        )
        assert r.status_code == 400
        assert "Ese botón no es válido" in r.text

    def test_un_pedido_que_ya_no_existe_se_dice(self, cliente, app_con_panel):
        r = cliente.post(
            f"/panel/mover?token={TOKEN}",
            data={"pedido_id": "x", "destino": "EN_PRODUCCION", "mensaje": "hola"},
        )
        assert r.status_code == 404 and "No encontré ese pedido" in r.text
        assert "no se mandó" in r.text, "el mensaje que escribió se perdía"

    def test_una_talla_que_no_existe_se_explica(self, cliente, app_con_panel):
        _, c = app_con_panel
        pedido = c.orders.create(_completo(OrderState.ANTICIPO_PAGADO), idem_key="k")
        r = cliente.post(
            f"/panel/talla?token={TOKEN}", data={"pedido_id": pedido.id, "talla": "7.3"}
        )
        assert r.status_code == 400 and "Esa talla no existe" in r.text
        assert '{"detail"' not in r.text

    def test_una_foto_rechazada_se_dice_por_que(self, cliente, app_con_panel):
        """Antes solo quedaba en el registro: en el panel la foto no aparecía."""
        _, c = app_con_panel
        pedido = c.orders.create(_completo(OrderState.PRODUCCION_LISTA), idem_key="k")
        r = cliente.post(
            f"/panel/fotos?token={TOKEN}",
            data={"pedido_id": pedido.id},
            files=[("archivos", ("recibo.txt", b"esto no es una foto", "text/plain"))],
        )
        assert r.status_code == 400
        assert "Algunas fotos no se subieron" in r.text and "recibo.txt" in r.text

    def test_una_transicion_ilegal_no_pasa(self, cliente, app_con_panel):
        """Aunque alguien arme el formulario a mano: la validación está en el
        dominio, no en el HTML."""
        _, c = app_con_panel
        pedido = c.orders.create(_pedido(OrderState.PRODUCCION_LISTA), idem_key="k")
        r = cliente.post(
            f"/panel/mover?token={TOKEN}",
            data={"pedido_id": pedido.id, "destino": "DESPACHADO"},
        )
        # 28/09: antes era «Internal Server Error». Es lo que pasa con una
        # página vieja (lo movió otro celular): se dice, y dónde está ahora.
        assert r.status_code == 409
        assert "Ese pedido ya cambió" in r.text and "producción terminada" in r.text
        assert c.orders.get(pedido.id).estado == OrderState.PRODUCCION_LISTA.value

    def test_sin_el_100_por_ciento_no_entra_al_taller(self, cliente, app_con_panel):
        """Regla de Camilo (19/09): sin talla no se funde nada."""
        _, c = app_con_panel
        pedido = c.orders.create(_pedido(OrderState.ANTICIPO_PAGADO), idem_key="k")
        r = cliente.post(
            f"/panel/mover?token={TOKEN}",
            data={"pedido_id": pedido.id, "destino": "EN_PRODUCCION"},
            follow_redirects=False,
        )
        assert r.status_code == 409 and "talla" in r.text
        assert c.orders.get(pedido.id).estado == OrderState.ANTICIPO_PAGADO.value

    def test_sin_direccion_no_se_despacha(self, cliente, app_con_panel):
        """La dirección se pide DESPUÉS del abono, y se exige aquí (19/09)."""
        from app.domain.envio import DatosDeEnvio

        _, c = app_con_panel
        pedido = c.orders.create(
            _completo(
                OrderState.SALDO_PAGADO,
                envio=DatosDeEnvio(nombre="Ángela Pérez", ciudad="Bogotá"),
            ),
            idem_key="k",
        )
        r = cliente.post(
            f"/panel/mover?token={TOKEN}",
            data={"pedido_id": pedido.id, "destino": "DESPACHADO"},
            follow_redirects=False,
        )
        assert r.status_code == 409 and "dirección" in r.text
        assert "No se puede despachar todavía" in r.text, "decía «entrar al taller»"
        assert c.orders.get(pedido.id).estado == OrderState.SALDO_PAGADO.value

    def test_si_lo_recoge_si_se_despacha(self, cliente, app_con_panel):
        from app.domain.envio import DatosDeEnvio

        _, c = app_con_panel
        pedido = c.orders.create(
            _completo(
                OrderState.SALDO_PAGADO,
                envio=DatosDeEnvio(nombre="Ángela Pérez", recoge=True),
            ),
            idem_key="k",
        )
        cliente.post(
            f"/panel/mover?token={TOKEN}",
            data={"pedido_id": pedido.id, "destino": "DESPACHADO"},
        )
        assert c.orders.get(pedido.id).estado == OrderState.DESPACHADO.value

    def test_confirmar_el_abono_deja_el_monto_pagado(self, cliente, app_con_panel):
        """19/09: el panel decía «abonado $0» de un pedido con abono confirmado."""
        _, c = app_con_panel
        pedido = c.orders.create(_completo(OrderState.EN_REVISION_PAGO), idem_key="k")
        cliente.post(
            f"/panel/mover?token={TOKEN}",
            data={"pedido_id": pedido.id, "destino": "ANTICIPO_PAGADO"},
        )
        assert c.orders.get(pedido.id).anticipo_pagado_cop == 60_000

    def test_mover_funciona_y_deja_rastro(self, cliente, app_con_panel):
        _, c = app_con_panel
        pedido = c.orders.create(_completo(OrderState.ANTICIPO_PAGADO), idem_key="k")
        r = cliente.post(
            f"/panel/mover?token={TOKEN}",
            data={"pedido_id": pedido.id, "destino": "EN_PRODUCCION"},
            follow_redirects=False,
        )
        assert r.status_code == 303, "sin redirección, recargar movería otra vez"
        assert c.orders.get(pedido.id).estado == OrderState.EN_PRODUCCION.value
        actores = {e.actor for e in c.orders.eventos(pedido.id)}
        assert "panel" in actores, "no quedó quién lo movió"


class TestLoQueSeVe:
    def test_la_talla_dudosa_sale_avisada_y_de_primeras(self, cliente, app_con_panel):
        _, c = app_con_panel
        pedido = c.orders.create(_pedido(OrderState.EN_PRODUCCION), idem_key="k")
        c.orders.guardar_personalizacion(
            pedido.id,
            Personalizacion(
                talla=14,
                talla_revisar=True,
                talla_motivo="puede ser el borde exterior",
                huellitas=[Huellita(corazon=ColorCircon.LILA, dedos=ColorCircon.MORADO)],
                grabados=["Rocky"],
            ),
        )
        texto = cliente.get(f"/panel?token={TOKEN}").text
        assert "Confirma la talla" in texto
        assert "borde exterior" in texto
        # La bandeja de tallas va primera: es la única donde demorarse daña.
        assert texto.index("Tallas por confirmar") < texto.index("En el taller")

    def test_se_ve_el_diseno_para_poder_fabricarlo(self, cliente, app_con_panel):
        _, c = app_con_panel
        pedido = c.orders.create(_pedido(OrderState.ANTICIPO_PAGADO), idem_key="k")
        c.orders.guardar_personalizacion(
            pedido.id,
            Personalizacion(
                talla=7,
                huellitas=[Huellita(corazon=ColorCircon.LILA, dedos=ColorCircon.MORADO)],
                grabados=["Rocky"],
            ),
        )
        texto = cliente.get(f"/panel?token={TOKEN}").text
        assert "corazón lila / dedos morado" in texto
        assert "Rocky" in texto
        assert "Talla: 7" in texto

    def test_avisa_de_lo_que_falta_preguntarle_a_la_clienta(self, cliente, app_con_panel):
        """Evita la peor llamada posible: preguntarle a alguien que ya pagó
        de qué color quería su anillo."""
        _, c = app_con_panel
        c.orders.create(_pedido(OrderState.ANTICIPO_PAGADO), idem_key="k")
        texto = cliente.get(f"/panel?token={TOKEN}").text
        assert "Falta por preguntarle" in texto

    def test_el_HTML_escapa_lo_que_escribe_la_clienta(self, cliente, app_con_panel):
        """Un nombre de mascota es texto de un desconocido metido en una
        página. El validador de grabados ya prohíbe símbolos raros, pero el
        escapado es la segunda cerradura: no se depende de una sola."""
        _, c = app_con_panel
        pedido = c.orders.create(
            _pedido(OrderState.ANTICIPO_PAGADO, codigo="PED-<script>"), idem_key="k"
        )
        assert pedido  # creado
        texto = cliente.get(f"/panel?token={TOKEN}").text
        assert "<script>" not in texto
        assert "&lt;script&gt;" in texto


class TestBandejas:
    def test_un_pedido_terminado_no_estorba(self):
        assert sum(b.cuantos for b in bandejas([_pedido(OrderState.ENTREGADO)])) == 0

    def test_la_talla_dudosa_aparece_ADEMAS_de_su_etapa(self):
        """A propósito: la bandeja de tallas es un aviso, no una etapa.
        Esconderlo porque «ya está en otra lista» es cómo se cuela un anillo
        mal medido."""
        pedido = _pedido(OrderState.EN_PRODUCCION)
        pedido = pedido.model_copy(
            update={
                "items": [
                    pedido.items[0].model_copy(
                        update={"personalizacion": Personalizacion(talla_revisar=True)}
                    )
                ]
            }
        )
        cuentas = {b.clave: b.cuantos for b in bandejas([pedido])}
        assert cuentas["talla_por_revisar"] == 1
        assert cuentas["en_produccion"] == 1

    def test_los_mas_viejos_van_primero(self):
        from datetime import UTC, datetime, timedelta

        viejo = _pedido(OrderState.EN_PRODUCCION, codigo="VIEJO").model_copy(
            update={"created_at": datetime.now(UTC) - timedelta(days=9)}
        )
        nuevo = _pedido(OrderState.EN_PRODUCCION, codigo="NUEVO")
        taller = next(b for b in bandejas([nuevo, viejo]) if b.clave == "en_produccion")
        assert [p.codigo for p in taller.pedidos] == ["VIEJO", "NUEVO"]

    def test_dias_esperando_cuenta_desde_el_ultimo_movimiento(self):
        from datetime import UTC, datetime, timedelta

        pedido = _pedido(OrderState.EN_PRODUCCION).model_copy(
            update={"updated_at": datetime.now(UTC) - timedelta(days=7)}
        )
        assert dias_esperando(pedido) == 7


class TestLaFichaDeTraspaso:
    """Todo lo que el bot detectó y no pudo confirmar tiene que verse aquí.

    Es la otra mitad de la política de imágenes: el bot no se bloquea ante la
    duda, guarda lo que vio y sigue. Eso solo vale si lo apuntado le llega a
    una persona antes de fabricar. Un aviso que nadie mira es no avisar.
    """

    def _con_notas(self, app_con_panel, *notas):
        from app.domain.models import Channel, Customer, conversation_id

        app, c = app_con_panel
        cliente = c.customers.upsert(
            Customer(id="c1", channel=Channel.WHATSAPP, channel_user_id="573001112233")
        )
        c.orders.create(_pedido(OrderState.ESPERANDO_ANTICIPO), idem_key="ficha")
        conv = conversation_id(cliente.channel, cliente.channel_user_id)
        ctx = c.contexto.cargar(conv)
        for nota in notas:
            ctx = ctx.anotar_revision(nota)
        c.contexto.guardar(ctx)
        return TestClient(app)

    def test_lo_que_hay_que_confirmar_sale_en_la_tarjeta(self, app_con_panel):
        cliente = self._con_notas(
            app_con_panel,
            "Talla 8 sacada de la foto (18.2 mm) — CONFIRMAR: la foto no se ve bien",
            "Mandó un comprobante ($60.000, Nequi): verificar el pago.",
        )
        html = cliente.get(f"/panel?token={TOKEN}").text
        assert "Confirma antes de fabricar" in html
        assert "18.2 mm" in html
        assert "Nequi" in html

    def test_sin_nada_pendiente_no_aparece_el_recuadro(self, app_con_panel):
        cliente = self._con_notas(app_con_panel)
        html = cliente.get(f"/panel?token={TOKEN}").text
        assert "Confirma antes de fabricar" not in html

    def test_lo_que_escribe_la_clienta_se_escapa_tambien_aqui(self, app_con_panel):
        cliente = self._con_notas(app_con_panel, "<script>alert(1)</script>")
        html = cliente.get(f"/panel?token={TOKEN}").text
        assert "<script>alert(1)</script>" not in html
        assert "&lt;script&gt;" in html


class TestLasFotosSeVenEnElPanel:
    """En el chat del panel una foto era la palabra «[image]».

    Lía no podía ver el prototipo que el bot le acababa de mandar a la clienta,
    ni los videos de la presentación (Camilo, 20/09).
    """

    def _burbuja(self, payload):
        import json

        from app.api.panel import _medio_del_mensaje

        return _medio_del_mensaje(
            {"payload": json.dumps(payload) if payload is not None else None}
        )

    def test_una_foto_nuestra_sale_como_imagen(self):
        html = self._burbuja(
            {"kind": "image", "media_url": "https://x.ngrok-free.dev/media/muestrario"}
        )
        assert html.startswith("<img") and "/media/muestrario" in html

    def test_un_video_sale_con_su_reproductor(self):
        html = self._burbuja(
            {"kind": "video", "media_url": "https://x.ngrok-free.dev/media/presenta_1"}
        )
        assert "<video" in html and "controls" in html

    def test_las_fotos_del_anillo_terminado_tambien(self):
        html = self._burbuja(
            {"kind": "image", "media_url": "https://x.ngrok-free.dev/panel/foto/abc.jpg"}
        )
        assert "<img" in html

    def test_un_mensaje_de_texto_no_trae_nada(self):
        assert self._burbuja(None) == ""
        assert self._burbuja({}) == ""

    def test_una_url_DE_FUERA_no_se_mete_en_la_pagina(self):
        """Lo que venga escrito en un mensaje ajeno no se renderiza: sería
        cargar lo que otro decida dentro del panel de Lía."""
        for url in (
            "https://sitio-de-otro.com/pixel.png",
            "javascript:alert(1)",
            "https://x.ngrok-free.dev/otra-cosa/abc.png",
        ):
            assert self._burbuja({"kind": "image", "media_url": url}) == "", url


class TestElCentroDeMando:
    """Camilo, 20/09: «necesito en algún lugar para darle click y siempre ver
    el panel, el chatwoot y demás… también la base de datos, el erp, etc.
    TODO».

    Antes había que acordarse de seis direcciones. Esto es la portada de las
    seis, con el estado de cada pieza en vivo.
    """

    def test_sin_token_no_existe(self, cliente):
        assert cliente.get("/panel/todo").status_code == 404
        assert cliente.get("/panel/registro").status_code == 404

    def test_con_token_lleva_a_todo(self, cliente):
        r = cliente.get(f"/panel/todo?token={TOKEN}")
        assert r.status_code == 200
        for enlace in ("/panel?token=", "/panel/chats?token=", "/panel/metricas?token="):
            assert enlace in r.text, enlace
        assert "docs.google.com/spreadsheets" in r.text, "falta el ERP"
        assert "/panel/registro?token=" in r.text, "falta el registro"

    def test_el_registro_no_enseña_la_llave_del_panel(self, cliente):
        """Esta pantalla puede quedarse abierta delante de cualquiera."""
        r = cliente.get(f"/panel/registro?token={TOKEN}")
        assert r.status_code == 200
        cuerpo = r.text.split("<pre", 1)[-1]
        assert TOKEN not in cuerpo, "el registro enseñó el token"

    def test_desde_el_taller_se_llega(self, cliente):
        assert "/panel/todo?token=" in cliente.get(f"/panel?token={TOKEN}").text


class TestUnTokenRaroEsUnTokenMaloNoUnError:
    """20/09. Abriendo el centro de mando:

        File "app/api/panel.py", in _exigir_token
            if not hmac.compare_digest(token or "", esperado):
        TypeError: comparing strings with non-ASCII characters is not supported

    La página pintaba el enlace del celular con «…» en lugar del token, y al
    abrirlo así el «…» llegaba como token. `compare_digest` con `str` solo
    admite ASCII: con cualquier otra cosa no dice «no cuadra», revienta. Y
    como todo el panel pasa por la misma puerta, se caía todo.
    """

    @pytest.mark.parametrize("raro", ["…", "ñandú", "🐾", "token…"])
    @pytest.mark.parametrize(
        "ruta", ["/panel", "/panel/todo", "/panel/chats", "/panel/registro"]
    )
    def test_da_404_como_cualquier_token_malo(self, cliente, ruta, raro):
        assert cliente.get(ruta, params={"token": raro}).status_code == 404

    def test_el_bueno_sigue_entrando(self, cliente):
        assert cliente.get(f"/panel/todo?token={TOKEN}").status_code == 200

    def test_la_pagina_da_el_enlace_entero_y_no_uno_a_medias(
        self, cliente, app_con_panel
    ):
        _, c = app_con_panel
        c.settings.public_url = "https://ejemplo.ngrok-free.dev"
        texto = cliente.get(f"/panel/todo?token={TOKEN}").text
        assert "token=…" not in texto, "volvió el enlace con puntos suspensivos"
        assert f"/panel/todo?token={TOKEN}" in texto
