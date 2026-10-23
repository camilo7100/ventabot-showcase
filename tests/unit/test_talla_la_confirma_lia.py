"""La talla la confirma Lía, siempre, antes del abono (regla de Lía, 29/09).

Lo que se pidió:
  · cuando manda la foto de la regla (o escribe la medida), el bot NO le dice
    ninguna talla: le dice que en unos minutos se la confirman;
  · la conversación sigue con cantidad, colores, grabado y nombre;
  · el abono espera a que Lía confirme la talla en el panel;
  · al confirmarla, a la clienta le llega su talla y, si ya estaba todo, el
    resumen para que diga que sí y siga el abono de siempre.

La IA sí mira la foto (es la misma llamada: no cuesta más, y hace falta para
saber si es la regla, un comprobante o la mascota). Lo que lee queda como
SUGERENCIA para Lía en el panel, nada más.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.conversacion.asesora import (
    CONFIRMA_EL_RESUMEN,
    TALLA_EN_ESPERA,
    TALLA_EN_REVISION,
    Asesora,
    HechosDelNegocio,
)
from app.domain.asesora import (
    TALLA_DE_LIA,
    AccionAsesora,
    Borrador,
    CambiosDelBorrador,
    Confianza,
    HuellitaDelBorrador,
    Jugada,
    aplicar,
    vigilar,
)
from app.domain.models import Channel, Customer
from app.domain.personalizacion import ColorCircon as C
from tests.unit.test_asesora import (
    CONV,
    ContextoEnMemoria,
    Guion,
    abrir_conversacion,
)

TOKEN = "token-de-prueba-1234"


@pytest.fixture
def mundo():
    """El mismo mundo de `test_asesora`: una clienta y los tres anillos."""
    from app.adapters.repositories.memory import (
        InMemoryCustomerRepository,
        InMemoryOrderRepository,
        InMemoryProductRepository,
    )
    from app.conversacion.mundo import Mundo
    from app.domain.models import Product

    customers = InMemoryCustomerRepository()
    customers.upsert(
        Customer(id="c1", channel=Channel.WHATSAPP, channel_user_id="573001112233")
    )
    productos = InMemoryProductRepository(
        [
            Product(
                sku=f"ANI-HUE-{n}",
                nombre=f"Anillo huellita x{n}",
                precio_cop=150_000 + 50_000 * n,
                iva_pct=0,
                dias_produccion=10,
                dias_produccion_max=15,
                anticipo_fijo_cop=60_000,
                huellitas=n,
            )
            for n in (1, 2, 3)
        ]
    )
    return Mundo(InMemoryOrderRepository(), customers, productos, ContextoEnMemoria())


def _guardar(mundo, b: Borrador) -> None:
    ctx = mundo.contexto(CONV)
    mundo.guardar_contexto(ctx.model_copy(update={"borrador": b.model_dump(mode="json")}))


FOTO = {"kind": "image", "media_id": "regla-1", "mime_type": "image/jpeg"}


def _completo(**kw) -> Borrador:
    """Todo escogido: 1 huellita, colores, grabado y su nombre."""
    base = dict(
        talla_exige_lia=True,
        cantidad=1,
        huellitas=[HuellitaDelBorrador(corazon=C.ROSADO, dedos=C.ROSADO)],
        grabado=["Rocky"],
        nombre_clienta="Laura Gómez",
    )
    return Borrador(**{**base, **kw})


def _jugada(mensaje="", *acciones, lectura="prueba", **cambios):
    return Jugada(
        lectura=lectura,
        cambios=CambiosDelBorrador(**cambios),
        acciones=list(acciones),
        mensaje=mensaje,
        mensaje_final="",
        confianza=Confianza.ALTA,
    )


def _asesora(mundo, *jugadas, fotos=None, avisos=None):
    abrir_conversacion(mundo)
    return Asesora(
        mundo,
        Guion(*jugadas),
        "{hechos}",
        HechosDelNegocio(precios={1: 200_000, 2: 250_000, 3: 300_000}),
        descargar=lambda m: b"\xff\xd8foto",
        talla_la_confirma_lia=True,
        guardar_foto=(lambda datos: fotos.append(datos) or f"regla{len(fotos)}")
        if fotos is not None
        else None,
        avisar=(lambda titulo, detalle, clave: avisos.append(titulo))
        if avisos is not None
        else None,
    )


def _borrador(mundo) -> Borrador:
    return Borrador.model_validate(mundo.contexto(CONV).borrador)


class TestLoQueFaltaParaElAbono:
    def test_una_talla_sin_confirmar_bloquea_el_abono(self):
        b = _completo(talla=7.75, talla_revisar=True)
        assert b.falta_para_abono() == [TALLA_DE_LIA]

    def test_la_confirmacion_va_de_ultima(self):
        """Mientras Lía revisa, el bot le sigue preguntando lo demás a ella."""
        b = _completo(talla=7.75, talla_revisar=True, grabado=[], huellitas=[])
        falta = b.falta_para_abono()
        assert falta[-1] == TALLA_DE_LIA and "colores" in falta

    def test_con_la_foto_no_se_le_vuelve_a_pedir_la_talla(self):
        """La IA no pudo leerla: la decide Lía al verla, no se le pide otra vez."""
        b = _completo(talla_fotos=["regla1"])
        assert "talla" not in b.falta_para_abono()
        assert b.falta_para_abono() == [TALLA_DE_LIA]

    def test_confirmada_ya_no_falta_nada(self):
        assert _completo(talla=8.0, talla_confirmada=True).falta_para_abono() == []

    def test_si_la_dice_ella_no_hay_nada_que_confirmar(self):
        """Camilo (04/10): «si dan la talla no hay nada que verificar». Pasó:
        escribió «talla seis» y el bot la puso a esperar a Lía."""
        b, _ = aplicar(_completo(), CambiosDelBorrador(talla=6))
        assert b.talla == 6 and b.talla_confirmada and not b.talla_revisar
        assert b.falta_para_abono() == []
        assert not b.talla_por_confirmar

    def test_la_foto_de_la_regla_en_revision_no_se_la_salta_un_numero(self):
        """Si hay una foto de la regla esperando a Lía y el modelo repite el
        número que leyó, sigue esperando a Lía."""
        en_revision = _completo(talla=7.0, talla_revisar=True, talla_fotos=["r.jpg"])
        b, _ = aplicar(en_revision, CambiosDelBorrador(talla=7))
        assert b.talla_revisar and not b.talla_confirmada
        assert b.falta_para_abono() == [TALLA_DE_LIA]

    def test_una_medida_que_no_se_entiende_tambien_la_decide_lia(self):
        b, rechazos = aplicar(_completo(), CambiosDelBorrador(medida_cm=3.5))
        assert not rechazos, "no se le pregunta otra vez: la mira Lía"
        assert b.talla_escrita == "3.5" and b.falta_para_abono() == [TALLA_DE_LIA]

    def test_sin_la_regla_de_paula_todo_es_como_antes(self):
        b = _completo(talla=7.75, talla_revisar=True, talla_exige_lia=False)
        assert b.falta_para_abono() == []


class TestNoSeLeDiceNingunaTalla:
    def test_el_modelo_no_puede_decir_la_talla_estimada(self):
        b = _completo(talla=7.75, talla_revisar=True)
        _, problemas = vigilar("¡Te da talla 7¾! 💍 ¿Seguimos?", set(), b)
        assert any("confirmar Lía" in p for p in problemas)

    def test_la_que_dijo_ella_si_la_puede_repetir(self):
        b = _completo(talla=7.0)
        _, problemas = vigilar("¡Anotado, talla 7! 💍", set(), b)
        assert not problemas


class TestElTurno:
    def test_la_foto_de_la_regla(self, mundo):
        fotos, avisos = [], []
        a = _asesora(
            mundo,
            _jugada(
                "¿De qué colores la quieres? 🩵",
                lectura="Mandó la foto del anillo sobre la regla",
                medida_cm=1.8,
            ),
            fotos=fotos,
            avisos=avisos,
        )
        _guardar(mundo, Borrador(cantidad=1))
        t = a.ejecutar(CONV, None, [FOTO])
        texto = t.respuesta.texto_plano
        assert TALLA_EN_REVISION in texto
        assert "7¾" not in texto and "talla 8" not in texto, "le dijo una talla"
        assert "¿De qué colores" in texto, "no siguió con el flujo"
        b = _borrador(mundo)
        assert b.talla == 7.75 and b.talla_revisar and not b.talla_confirmada
        assert b.talla_fotos == ["regla1"], "Lía no va a poder ver la foto"
        assert "📏 Talla por confirmar" in avisos

    def test_una_foto_que_no_es_de_la_talla_no_se_guarda(self, mundo):
        fotos = []
        a = _asesora(
            mundo,
            _jugada("¡Qué lindo! 🐾", lectura="Mandó la foto de su gatito"),
            fotos=fotos,
        )
        t = a.ejecutar(CONV, None, [FOTO])
        assert TALLA_EN_REVISION not in t.respuesta.texto_plano
        assert not fotos

    def test_la_medida_escrita(self, mundo):
        a = _asesora(mundo, _jugada("¿Y el grabado? 🖊️", medida_cm=1.8))
        t = a.ejecutar(CONV, "1.8")
        assert TALLA_EN_REVISION in t.respuesta.texto_plano
        assert _borrador(mundo).talla_escrita == "1.8"

    def test_el_abono_espera_a_lia(self, mundo):
        avisos = []
        a = _asesora(
            mundo,
            _jugada("¡Listo! 🫶 Te dejo los datos 💓", AccionAsesora.PEDIR_ABONO),
            avisos=avisos,
        )
        ctx = mundo.contexto(CONV)
        b = _completo(talla=7.75, talla_revisar=True)
        mundo.guardar_contexto(
            ctx.model_copy(update={"borrador": b.model_dump(mode="json")})
        )
        t = a.ejecutar(CONV, "sí, así")
        assert _borrador(mundo).pedido_id is None, "nació el pedido sin la talla de Lía"
        assert "Bancolombia" not in t.respuesta.texto_plano.title()
        assert any("falta" in r for r in t.respuesta.traza)

    def test_si_solo_falta_la_talla_se_le_dice_que_ya_casi(self):
        assert Asesora._lo_que_falta(_completo(talla=7.75, talla_revisar=True)) == (
            TALLA_EN_ESPERA
        )


class TestCuandoPaoLaConfirma:
    def test_le_llega_el_resumen_para_seguir_con_el_abono(self, mundo):
        a = _asesora(mundo)
        ctx = mundo.contexto(CONV)
        b = _completo(talla=7.75, talla_revisar=True)
        mundo.guardar_contexto(
            ctx.model_copy(update={"borrador": b.model_dump(mode="json")})
        )
        mundo.fijar_talla_de_lia(CONV, 8.0, "Corregida por Lía")
        r = a.tras_confirmar_talla(CONV)
        assert "Talla: 8" in r.texto_plano and CONFIRMA_EL_RESUMEN in r.texto_plano
        despues = _borrador(mundo)
        assert despues.talla_confirmada and despues.ultimo_resumen

    def test_si_falta_algo_no_se_manda_el_resumen(self, mundo):
        a = _asesora(mundo)
        ctx = mundo.contexto(CONV)
        b = _completo(talla=7.75, talla_revisar=True, grabado=[])
        mundo.guardar_contexto(
            ctx.model_copy(update={"borrador": b.model_dump(mode="json")})
        )
        mundo.fijar_talla_de_lia(CONV, 8.0, "Confirmada por Lía")
        assert not a.tras_confirmar_talla(CONV).texto_plano


# ---------------------------------------------------------------------------
# De punta a punta: el panel
# ---------------------------------------------------------------------------


@pytest.fixture
def entorno(monkeypatch, tmp_path):
    import app.infra.container as contenedor
    from app.adapters.crm.chatwoot import CrmDeMentira
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

    c = contenedor.get_container()
    c.customers.upsert(
        Customer(id="c1", channel=Channel.WHATSAPP, channel_user_id="573001112233")
    )
    # La asesora de verdad (con un guion vacío: aquí no se habla con el modelo).
    asesora = Asesora(
        c.bot._mundo,
        Guion(),
        "{hechos}",
        HechosDelNegocio(precios={1: 200_000, 2: 250_000, 3: 300_000}),
        talla_la_confirma_lia=True,
    )
    monkeypatch.setattr(c, "bot", asesora)
    espejo = CrmDeMentira()
    monkeypatch.setattr(c, "crm", espejo)
    ctx = asesora._mundo.contexto(CONV)
    b = _completo(talla=7.75, talla_revisar=True, talla_rango="entre 7½ y 8")
    b.talla_fotos = ["regla-de-prueba"]
    asesora._mundo.guardar_contexto(
        ctx.model_copy(update={"borrador": b.model_dump(mode="json")})
    )
    yield TestClient(app), c, espejo

    get_settings.cache_clear()
    contenedor._singleton = None


class TestEnElPanel:
    def test_sale_en_tallas_por_confirmar_con_su_foto(self, entorno):
        cliente, _, _ = entorno
        pagina = cliente.get(f"/panel?token={TOKEN}").text
        assert "📏 Tallas por confirmar" in pagina
        assert "/panel/foto/regla-de-prueba" in pagina
        assert "La IA sugiere: <b>7¾</b> (entre 7½ y 8)" in pagina
        assert "Ya escogió todo." in pagina
        assert "<option value='7.75' selected>7¾</option>" in pagina

    def test_confirmarla_le_manda_su_talla_y_el_resumen(self, entorno):
        cliente, c, espejo = entorno
        r = cliente.post(
            f"/panel/talla-charla?token={TOKEN}",
            data={"conv": CONV, "talla": "8", "nota": "La mejor con la foto"},
            follow_redirects=False,
        )
        assert r.status_code == 303
        textos = [m.text for m in c.outbox.pending(20) if m.text]
        assert textos[0] == "¡Listo! 💍 Ya revisé tu medida: tu talla es la 8."
        assert any("Talla: 8" in x for x in textos), "no le llegó el resumen"
        assert textos[-1] == CONFIRMA_EL_RESUMEN
        b = Borrador.model_validate(c.bot._mundo.contexto(CONV).borrador)
        assert b.talla == 8.0 and b.talla_confirmada and not b.falta_para_abono()
        assert any("NOTA INTERNA · talla" in t for _, t, _ in espejo.copias)
        pagina = cliente.get(f"/panel?token={TOKEN}").text
        assert "/panel/foto/regla-de-prueba" not in pagina, "sigue saliendo pendiente"

    def test_el_mensaje_de_lia_reemplaza_al_de_siempre(self, entorno):
        cliente, c, _ = entorno
        cliente.post(
            f"/panel/talla-charla?token={TOKEN}",
            data={"conv": CONV, "talla": "7.75", "mensaje": "Te queda perfecta la 7¾ 💍"},
        )
        textos = [m.text for m in c.outbox.pending(20) if m.text]
        assert textos[0] == "Te queda perfecta la 7¾ 💍"
        assert "Ya revisé tu medida" not in " ".join(textos)

    def test_una_talla_invalida_se_explica(self, entorno):
        cliente, c, _ = entorno
        r = cliente.post(
            f"/panel/talla-charla?token={TOKEN}", data={"conv": CONV, "talla": ""}
        )
        assert r.status_code == 400 and "Esa talla no existe" in r.text
        assert not c.outbox.pending(20)


class TestLosChatsDePruebaDel29:
    """Lo que se vio al revisar los chats de prueba del 29/09."""

    def test_sin_resumen_no_se_pregunta_si_asi_esta_bien(self, mundo):
        """Llegó la foto de la regla y el modelo no preguntó nada: debajo del
        «te confirmo tu talla» salía «¿Así está bien? 🥰» sin ningún resumen."""
        a = _asesora(
            mundo,
            _jugada("¡Eso es perfecto! 🥰", lectura="la regla", medida_cm=1.8),
            fotos=[],
        )
        _guardar(mundo, Borrador(cantidad=1))
        texto = a.ejecutar(CONV, None, [FOTO]).respuesta.texto_plano
        assert TALLA_EN_REVISION in texto
        assert CONFIRMA_EL_RESUMEN not in texto
        assert "?" in texto, "igual tiene que preguntarle lo que falta"

    def test_las_cuentas_esperan_a_la_talla_de_lia(self, mundo):
        """«Lía te confirma la talla en unos minutos y te paso todo» y, justo
        debajo, los datos del abono."""
        a = _asesora(
            mundo,
            _jugada(
                "¡Perfecto Nancy! 🫶 Lía te confirma la talla en unos minutos",
                AccionAsesora.MANDAR_CUENTAS,
            ),
        )
        _guardar(mundo, _completo(talla=7.75, talla_revisar=True))
        texto = a.ejecutar(CONV, "Nancy Vásquez").respuesta.texto_plano
        assert "Bancolombia" not in texto

    def test_si_pide_la_cuenta_se_le_da(self, mundo):
        """ADR 0022: si pide la cuenta con todas las letras, se le manda."""
        a = _asesora(mundo, _jugada("¡Claro! 🫶", AccionAsesora.MANDAR_CUENTAS))
        _guardar(mundo, _completo(talla=7.75, talla_revisar=True))
        texto = a.ejecutar(CONV, "me pasas la cuenta para ir adelantando?").respuesta
        assert "Bancolombia" in texto.texto_plano

    def test_la_cantidad_escrita_se_anota_aunque_el_modelo_no(self, mundo):
        """«Quisiera un anillo de 2 huellitas pero no sé mi talla» -> «¡Perfecto,
        dos huellitas!» sin anotarla, y después se la volvía a preguntar."""
        a = _asesora(mundo, _jugada("¡Perfecto, dos huellitas! 🐾"))
        _guardar(mundo, Borrador(talla_exige_lia=True))
        a.ejecutar(CONV, "Quisiera un anillo de 2 huellitas pero no sé mi talla")
        assert _borrador(mundo).cantidad == 2

    def test_al_confirmar_la_cantidad_es_la_del_pedido(self):
        b = _completo(cantidad=2)
        limpio, problemas = vigilar(
            "Déjame confirmar: 1 huellita, corazón rosado. ¿Así está todo bien?",
            set(),
            b,
        )
        assert "1 huellita" not in limpio and any("huellita" in p for p in problemas)
        _, nada = vigilar("¿La quieres de 1, 2 o 3 huellitas?", set(), b)
        assert not nada, "ofrecer opciones no es confirmar"

    @pytest.mark.parametrize(
        "frase", ["Perfecto, naranja claro 🧡.", "Va en rojo fuerte."]
    )
    def test_no_confirma_un_tono_que_no_es_una_bolsita(self, frase):
        limpio, problemas = vigilar(frase + " ¿Y el grabado?", set())
        assert "¿Y el grabado?" in limpio and frase not in limpio
        assert any("muestrario" in p for p in problemas)


class TestUnaPreguntaALaVez:
    """ADR 0024 en Python, no solo en el prompt (30/09)."""

    def test_se_queda_la_primera(self):
        from app.domain.asesora import una_sola_pregunta

        mensaje, _, quitadas = una_sola_pregunta(
            "¡Roja y verde oliva! ❤️💚 ¿Quieres cada huellita toda de ese color? "
            "Y, ¿qué nombres te gustaría grabar? 🐾",
            "",
        )
        assert "¿Quieres cada huellita" in mensaje and "grabar" not in mensaje
        assert mensaje.startswith("¡Roja y verde oliva!") and quitadas == 1

    def test_la_del_cierre_sobra_si_el_mensaje_ya_pregunta(self):
        from app.domain.asesora import una_sola_pregunta

        _, final, quitadas = una_sola_pregunta(
            "¡Qué lindo! ¿Es para ti?", "¿De qué colores la quieres? 🩵"
        )
        assert final == "" and quitadas == 1

    def test_una_sola_no_se_toca(self):
        from app.domain.asesora import una_sola_pregunta

        assert una_sola_pregunta("¡Listo! 🫶", "¿Así está bien?") == (
            "¡Listo! 🫶",
            "¿Así está bien?",
            0,
        )


# ══════════════════════════════════════════════════════════════════════════
#  LA TALLA DICTADA (prueba de verdad, 05/10)
# ══════════════════════════════════════════════════════════════════════════
#  «talla seis» dictado por voz llegó como «Gamma seis». El modelo no la anotó
#  en ese turno; en el siguiente la anotó y dudó de ella («¿la talla 6 es la
#  definitiva o te comparto la guía?»), le mandó la guía, ella mandó la regla y
#  la talla terminó esperando a Lía. Otra vez, con la talla ya lista, escribió
#  «en unos minutos te confirmo la talla».


class TestLaTallaDictada:
    @pytest.mark.parametrize(
        "texto, talla",
        [
            ("Gamma seis", 6),
            ("talla 7", 7),
            ("Taya siete y medio", 7.5),
            ("mi talla es la 8", 8),
            ("talla 6½", 6.5),
            ("Soy talla nueve", 9),
        ],
    )
    def test_con_la_palabra(self, texto, talla):
        from app.domain.tallas import talla_dictada

        assert talla_dictada(texto) == talla

    @pytest.mark.parametrize("texto, talla", [("seis", 6), ("7", 7), ("creo que 8", 8)])
    def test_un_numero_suelto_despues_de_preguntarla(self, texto, talla):
        from app.conversacion.asesora import PREGUNTA_DE_LA_TALLA
        from app.domain.tallas import talla_dictada

        assert talla_dictada(texto, PREGUNTA_DE_LA_TALLA) == talla
        assert talla_dictada(texto, "¿De qué colores la quieres?") is None

    @pytest.mark.parametrize(
        "texto",
        [
            "Una",  # la cantidad de huellitas, no una talla
            "dos",
            "tengo cinco perritos",
            "18 mm",  # una medida: la mira Lía
            "1.8 cm",
            "¿tienen talla 7?",  # pregunta, no dice la suya
            "talla 20",  # no existe
            "no sé mi talla",
        ],
    )
    def test_lo_que_no_es_una_talla_dicha(self, texto):
        from app.conversacion.asesora import PREGUNTA_DE_LA_TALLA
        from app.domain.tallas import talla_dictada

        assert talla_dictada(texto, PREGUNTA_DE_LA_TALLA) is None

    def test_el_turno_la_anota_aunque_el_modelo_no(self, mundo):
        from app.conversacion.asesora import PREGUNTA_DE_LA_TALLA

        a = _asesora(mundo, _jugada("😊 ¿Y de cuántas huellitas quieres el anillo?"))
        ctx = mundo.contexto(CONV)
        mundo.guardar_contexto(
            ctx.model_copy(
                update={"charla": [{"de": "lia", "texto": PREGUNTA_DE_LA_TALLA}]}
            )
        )
        _guardar(mundo, Borrador(talla_exige_lia=True, turnos=1))
        a.ejecutar(CONV, "Gamma seis")
        b = _borrador(mundo)
        assert b.talla == 6 and b.talla_confirmada and not b.talla_revisar
        assert not b.talla_por_confirmar

    def test_no_se_duda_de_la_talla_que_dijo(self, mundo):
        from app.conversacion.asesora import GUIA_TALLA

        a = _asesora(
            mundo,
            _jugada(
                "Listo, una huellita 🐾 ¿La talla 6 es la definitiva o quieres que te "
                "comparta la guía? 💍",
                AccionAsesora.MOSTRAR_GUIA_TALLA,
                cantidad_huellitas=1,
            ),
        )
        _guardar(mundo, Borrador(talla_exige_lia=True, talla=6, talla_confirmada=True))
        texto = a.ejecutar(CONV, "Una").respuesta.texto_plano
        assert GUIA_TALLA not in texto, "le mandó la guía a quien ya dijo su talla"
        assert "definitiva" not in texto

    def test_si_ella_pide_la_guia_si_se_le_manda(self, mundo):
        from app.conversacion.asesora import GUIA_TALLA

        a = _asesora(mundo, _jugada("¡Claro! 📏", AccionAsesora.MOSTRAR_GUIA_TALLA))
        _guardar(mundo, Borrador(talla_exige_lia=True, talla=6, talla_confirmada=True))
        texto = a.ejecutar(CONV, "mejor mándame la guía para medirla").respuesta
        assert GUIA_TALLA in texto.texto_plano

    @pytest.mark.parametrize(
        "frase",
        [
            "Ya casi; en unos minutos te confirmo la talla y te paso el resumen.",
            "Lía te confirma tu talla en un momento 🫶",
            "¿La talla 6 es la definitiva?",
        ],
    )
    def test_el_vigilante_no_deja_dudar_de_la_talla_lista(self, frase):
        b = _completo(talla=6.0, talla_confirmada=True)
        limpio, problemas = vigilar(f"¡Listo, Lía! 🫶 {frase}", set(), b)
        assert problemas and limpio.startswith("¡Listo, Lía!")
        assert "confirm" not in limpio and "definitiva" not in limpio

    def test_con_la_regla_en_revision_si_se_le_dice_que_se_confirma(self):
        b = _completo(talla=7.0, talla_revisar=True, talla_fotos=["r.jpg"])
        _, problemas = vigilar("En unos minutos te confirmo la talla 💍", set(), b)
        assert not problemas


# ══════════════════════════════════════════════════════════════════════════
#  SIN ANILLOS PARA MEDIR: A LA JOYERÍA, NUNCA EL DEDO (05/10)
# ══════════════════════════════════════════════════════════════════════════
#  Real: «Es que no tengo anillos 🫣» y la IA le propuso medirse el dedo con una
#  tira de papel. Lía: «si no tienes anillos, sí te tocaría pasar por una
#  joyería, porque medir el dedo es muy inexacto y la talla puede quedar mal».


class TestSinAnillos:
    @pytest.mark.parametrize(
        "texto",
        [
            "Es que no tengo anillos 🫣",
            "no uso anillos",
            "No tengo ningún anillo",
            "nunca he usado anillos",
            "no tengo con qué medir",
        ],
    )
    def test_lo_reconoce(self, texto):
        from app.domain.tallas import no_tiene_anillos

        assert no_tiene_anillos(texto)

    def test_no_tengo_a_secas_solo_despues_de_la_guia(self):
        from app.conversacion.asesora import GUIA_TALLA
        from app.domain.tallas import no_tiene_anillos

        assert no_tiene_anillos("No tengo", GUIA_TALLA)
        assert not no_tiene_anillos("No tengo", "¿Quieres grabarle el nombre? 🖊️")

    @pytest.mark.parametrize(
        "texto", ["no tengo idea", "no sé mi talla", "tengo un anillo de mi mamá"]
    )
    def test_lo_que_no_es(self, texto):
        from app.conversacion.asesora import GUIA_TALLA
        from app.domain.tallas import no_tiene_anillos

        assert not no_tiene_anillos(texto, GUIA_TALLA)

    # Camilo, 13/10: sin anillos, el contorno del DEDO con papel o hilo y el video
    # (antes, la joyería: «es un cuello de botella»). Así abonó Laura el 05/10.

    def test_la_respuesta_fija_es_el_dedo_con_el_video_sin_llamar_a_la_ia(self, mundo):
        from app.conversacion.asesora import (
            GUIA_TALLA,
            TALLA_SIN_ANILLOS,
            VIDEO_DEL_DEDO,
        )

        a = _asesora(mundo)  # sin jugadas: si llamara a la IA, fallaría
        ctx = mundo.contexto(CONV)
        mundo.guardar_contexto(
            ctx.model_copy(update={"charla": [{"de": "lia", "texto": GUIA_TALLA}]})
        )
        _guardar(mundo, Borrador(talla_exige_lia=True, turnos=2))
        t = a.ejecutar(CONV, "Es que no tengo anillos 🫣")
        texto = t.respuesta.texto_plano
        assert TALLA_SIN_ANILLOS in texto and "joyería" not in texto
        assert VIDEO_DEL_DEDO in [p.imagen for p in t.respuesta.piezas if p.imagen]
        assert "¿De cuántas huellitas lo quieres? 🐾" in texto, "no siguió armando"
        assert texto.count("?") == 1, "una pregunta a la vez"
        assert t.capa == "fija"

    def test_con_la_ia_no_va_la_guia_de_la_regla(self, mundo):
        from app.conversacion.asesora import GUIA_TALLA, TALLA_SIN_ANILLOS

        a = _asesora(
            mundo,
            _jugada(
                "¡Dos huellitas! 🐾 Puedes medir el contorno de tu dedo con una tira "
                "de papel y una regla. ¿De qué colores las quieres?",
                AccionAsesora.MOSTRAR_GUIA_TALLA,
                cantidad_huellitas=2,
            ),
        )
        _guardar(mundo, Borrador(talla_exige_lia=True, turnos=2))
        texto = a.ejecutar(
            CONV, "quiero el de 2 huellitas pero no tengo anillos"
        ).respuesta.texto_plano
        assert TALLA_SIN_ANILLOS in texto
        assert GUIA_TALLA not in texto, "le mandó la guía de medir un anillo"
        assert texto.count("contorno") == 1, "lo del dedo, una sola vez"
        assert "¿De qué colores" in texto

    def test_si_la_ia_propone_el_dedo_va_el_del_sistema_con_el_video(self, mundo):
        from app.conversacion.asesora import TALLA_SIN_ANILLOS, VIDEO_DEL_DEDO

        a = _asesora(
            mundo,
            _jugada(
                "Siii 😊 Puedes medir el contorno de tu dedo con una tira de papel. "
                "¿Me cuentas cuántos centímetros te da?"
            ),
        )
        _guardar(mundo, Borrador(talla_exige_lia=True, turnos=3, cantidad=1))
        r = a.ejecutar(CONV, "Si por favor").respuesta
        assert TALLA_SIN_ANILLOS in r.texto_plano
        assert r.texto_plano.count("contorno") == 1
        assert VIDEO_DEL_DEDO in [p.imagen for p in r.piezas if p.imagen]

    def test_el_vigilante_ya_no_lo_quita(self):
        limpio, _ = vigilar(
            "Puedes medir el contorno de tu dedo con una tira de papel.",
            set(),
            _completo(talla=None),
        )
        assert "contorno de tu dedo" in limpio

    def test_los_deditos_de_la_huellita_no_son_el_dedo(self):
        _, problemas = vigilar(
            "¿Y los deditos de qué color? La cinta de colores te ayuda 🩵",
            set(),
            _completo(),
        )
        assert not problemas


class TestOtraFotoDeLaRegla:
    def test_no_le_repite_la_misma_frase(self, mundo):
        """Prueba de verdad (05/10): mandó otra foto de la regla y le llegó otra
        vez «¡Gracias por la medida!…» palabra por palabra."""
        from app.conversacion.asesora import OTRA_MEDIDA

        jugada = _jugada(
            "¿Y los colores? 🩵",
            lectura="Mandó la foto del anillo sobre la regla",
            medida_cm=1.8,
        )
        a = _asesora(mundo, jugada, jugada)
        _guardar(mundo, Borrador(cantidad=1))
        primera = a.ejecutar(CONV, None, [FOTO]).respuesta.texto_plano
        segunda = a.ejecutar(CONV, None, [FOTO]).respuesta.texto_plano
        assert TALLA_EN_REVISION in primera
        assert TALLA_EN_REVISION not in segunda and OTRA_MEDIDA in segunda


class TestLaGuiaDelDedoUnaVez:
    def test_si_la_ia_la_menciona_otra_vez_no_se_repite(self, mundo):
        """Prueba de verdad del 13/10: ya tenía la guía del dedo y el video; al dar
        su nombre, la IA habló del papel y le llegó la guía entera otra vez."""
        from app.conversacion.asesora import SIN_ANILLOS, VIDEO_DEL_DEDO

        a = _asesora(
            mundo,
            _jugada(
                "¡Gracias, Laura! 🫶 Cuando te midas el dedo con la tira de papel, "
                "me cuentas cuántos centímetros te da."
            ),
        )
        _guardar(
            mundo,
            _completo(
                talla=None,
                mostrado_en={SIN_ANILLOS: 2},
                lo_manda_despues={"talla": 2},
                turnos=6,
            ),
        )
        r = a.ejecutar(CONV, "Laura Contreras").respuesta
        assert VIDEO_DEL_DEDO not in [p.imagen for p in r.piezas if p.imagen]
        assert "contorno" not in r.texto_plano and "papel" not in r.texto_plano
        assert "separar con el abono" in r.texto_plano, r.texto_plano
