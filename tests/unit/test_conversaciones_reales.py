"""Conversaciones enteras, calcadas de las que vendieron de verdad.

════════════════════════════════════════════════════════════════════════════
DE DÓNDE SALEN
════════════════════════════════════════════════════════════════════════════
De `Downloads/Ejemplos conversaciones`: siete PDF con charlas reales de Lía
que terminaron en venta. No se copian como guion —una clienta nunca repite la
misma frase— pero el ESQUELETO sí es el que funciona, y es el que el bot tiene
que poder recorrer sin atascarse:

    presentación (UNA vez) → talla → colores → grabado → resumen → cuentas
    → comprobante → «ya tomé tu pedido»

Cada test de aquí es una conversación completa con el modelo simulado: no
gastan ni un peso y corren en milisegundos. Lo que comprueban no es que el bot
diga una frase bonita, sino que **la venta pueda avanzar**: que lo que ella
pide llegue, que lo que ya se dijo no se repita, y que nada se quede a medias.

Los fallos que cada uno vigila pasaron con Camilo probando desde su celular
los días 19 y 20 de septiembre.
"""

from __future__ import annotations

from typing import ClassVar

import pytest

from app.domain.asesora import (
    AccionAsesora,
    Borrador,
    CambiosDelBorrador,
    Confianza,
    DisenoParaVer,
    HuellitaDelBorrador,
    HuellitaPropuesta,
    Jugada,
)
from app.domain.personalizacion import ColorCircon as C
from tests.unit.test_asesora import CONV, _asesora, _jugada


class _LapizDeMentira:
    """Dibuja sin dibujar: devuelve un nombre por combinación de colores.

    El render de verdad escribe un JPG; aquí solo hace falta saber QUÉ se
    enseñó y cuántas veces."""

    def previsualizar(self, huellitas) -> str:
        return "vista_" + "_".join(
            f"{h.corazon.value}-{h.dedos.value}" for h in huellitas
        )


@pytest.fixture
def mundo():
    """El mismo mundo de siempre, pero con lápiz: si no, `previsualizar`
    devuelve None y un test de «enséñame cómo queda» no prueba nada."""
    from app.adapters.repositories.memory import (
        InMemoryCustomerRepository,
        InMemoryOrderRepository,
    )
    from app.conversacion.mundo import Mundo
    from app.domain.models import Channel, Customer
    from tests.unit.test_inteligencia_conversacional import (
        ContextoEnMemoria,
        _productos,
    )

    customers = InMemoryCustomerRepository()
    customers.upsert(
        Customer(id="c1", channel=Channel.WHATSAPP, channel_user_id="573001112233")
    )
    return Mundo(
        InMemoryOrderRepository(),
        customers,
        _productos(),
        ContextoEnMemoria(),
        render=_LapizDeMentira(),
    )


def _ver(*disenos) -> Jugada:
    """Una jugada que enseña diseños SIN escogerlos («muéstrame en rosado»)."""
    return Jugada(
        lectura="quiere ver colores",
        cambios=CambiosDelBorrador(),
        acciones=[AccionAsesora.MOSTRAR_COMO_QUEDA],
        mensaje="¡Claro! Te muestro 🫶",
        confianza=Confianza.ALTA,
        vistas_previas=[
            DisenoParaVer(
                nombre=nombre,
                huellitas=[HuellitaPropuesta(numero=1, corazon=color, dedos=color)],
            )
            for nombre, color in disenos
        ],
    )


def _fotos(respuesta) -> list[str]:
    return [p.imagen for p in respuesta.piezas if p.imagen]


def _texto(respuesta) -> str:
    return " ".join(p.texto or "" for p in respuesta.piezas)


# ══════════════════════════════════════════════════════════════════════════
#  1. «Muéstrame cómo queda»: ver ANTES de escoger
# ══════════════════════════════════════════════════════════════════════════


class TestVerAntesDeEscoger:
    """20/09: pidió ver colores tres veces y el bot contestó «¡Claro! Te
    muestro cómo se ve rosado con rojo» sin mandar NI UNA foto. Tres veces.

    Ver cómo le queda es lo que vende el anillo (ADR 0008). Un «te muestro»
    que no llega es peor que no ofrecerlo."""

    def test_pedir_ver_un_color_manda_la_foto(self, mundo):
        a = _asesora(mundo, _ver(("Todo rosado", C.ROSADO)))
        r = a.ejecutar(CONV, "me gustaría ver cómo queda el rosado").respuesta
        assert _fotos(r), "prometió enseñarlo y no mandó nada"

    def test_pedir_DOS_colores_manda_LAS_DOS_fotos(self, mundo):
        """«Uno completamente rosado y otro completamente rojo, muéstrame
        ambos» — literal, de la conversación del 20/09."""
        a = _asesora(mundo, _ver(("Todo rosado", C.ROSADO), ("Todo rojo", C.ROJO)))
        r = a.ejecutar(CONV, "uno rosado y otro rojo, muéstrame ambos").respuesta
        assert len(_fotos(r)) == 2
        # Con el nombre DEL MUESTRARIO debajo, no el que le puso el modelo (30/09).
        assert "rosa" in _texto(r) and "rojo" in _texto(r), (
            "sin el nombre debajo, dos fotos seguidas no se distinguen"
        )

    def test_ver_un_color_NO_lo_deja_escogido(self, mundo):
        """Mirar no es decidir. Si se guardara, el resumen diría que escogió
        un color que ella solo estaba comparando."""
        a = _asesora(mundo, _ver(("Todo rosado", C.ROSADO)))
        t = a.ejecutar(CONV, "muéstrame el rosado")
        guardado = Borrador.model_validate(t.contexto.borrador)
        assert not [h for h in guardado.huellitas if h.completa]
        assert guardado.cantidad is None, "tampoco fijó la cantidad"

    def test_mas_de_tres_disenos_no_se_convierten_en_una_rafaga(self, mundo):
        a = _asesora(
            mundo,
            _ver(
                ("Rosado", C.ROSADO),
                ("Rojo", C.ROJO),
                ("Azul", C.AZUL_REY),
                ("Negro", C.NEGRO),
                ("Blanco", C.BLANCO),
            ),
        )
        r = a.ejecutar(CONV, "muéstrame varios").respuesta
        assert len(_fotos(r)) <= 3

    def test_si_ya_escogio_se_le_enseña_LO_SUYO(self, mundo):
        """El camino de siempre: sin `vistas_previas`, se dibuja su anillo."""
        a = _asesora(
            mundo,
            _jugada(
                "¡Qué lindo! 💜",
                AccionAsesora.MOSTRAR_COMO_QUEDA,
                cantidad_huellitas=1,
                huellitas=[HuellitaPropuesta(numero=1, corazon=C.LILA, dedos=C.LILA)],
            ),
        )
        r = a.ejecutar(CONV, "lila toda la huellita").respuesta
        assert _fotos(r)


# ══════════════════════════════════════════════════════════════════════════
#  2. La talla: si se calcula, se dice
# ══════════════════════════════════════════════════════════════════════════


class TestLaTallaSeDice:
    """20/09: mandó la foto de la regla y le llegó «¡Perfecto!» a secas.

    El sistema había sacado talla 6.5, el modelo escribió «talla 7», y el
    vigilante le borró la frase por no cuadrar. Ella tuvo que escribir «?»
    para enterarse de su talla. Lía siempre dice el número: «Si perfecto, es
    una talla 6»."""

    def test_de_una_medida_el_sistema_dice_la_talla(self, mundo):
        a = _asesora(mundo, _jugada("¡Perfecto!", medida_cm=1.73))
        r = a.ejecutar(CONV, "[foto de la regla]").respuesta
        assert "talla 7" in _texto(r).lower(), _texto(r)

    def test_aunque_el_modelo_diga_otro_numero_gana_el_calculado(self, mundo):
        """Esta es LA prueba: el modelo se equivoca de redondeo y la clienta
        se tiene que enterar igual."""
        a = _asesora(mundo, _jugada("¡Te da talla 9! 💍", medida_cm=1.73))
        texto = _texto(a.ejecutar(CONV, "[foto de la regla]").respuesta).lower()
        assert "talla 7" in texto
        assert "talla 9" not in texto, "dejó pasar una talla que no es la suya"

    def test_si_ella_dice_su_talla_no_se_la_repite_como_si_la_hubiera_medido(self, mundo):
        a = _asesora(mundo, _jugada("¡Listo, talla 7! 💍", talla=7))
        assert "¡Es una talla" not in _texto(a.ejecutar(CONV, "soy talla 7").respuesta)


# ══════════════════════════════════════════════════════════════════════════
#  3. La presentación: una vez y nunca más
# ══════════════════════════════════════════════════════════════════════════


class TestNoRepetirse:
    def test_la_ficha_no_vuelve_ni_aunque_el_modelo_insista(self, mundo):
        a = _asesora(
            mundo,
            _jugada("", AccionAsesora.MOSTRAR_PRECIOS, final="¿Sabes tu talla?"),
            _jugada("", AccionAsesora.MOSTRAR_PRECIOS),
            _jugada("", AccionAsesora.MOSTRAR_PRECIOS),
        )
        assert "$250.000" in _texto(a.ejecutar(CONV, "hola, precios?").respuesta)
        for mensaje in ("1", "¿y cuánto vale?"):
            r = a.ejecutar(CONV, mensaje).respuesta
            assert "$250.000" not in _texto(r), f"la repitió tras «{mensaje}»"
            assert not _fotos(r), f"repitió los videos tras «{mensaje}»"

    def test_la_presentacion_completa_sale_entera_la_primera_vez(self, mundo):
        a = _asesora(
            mundo, _jugada("", AccionAsesora.MOSTRAR_PRECIOS, final="¿Sabes tu talla?")
        )
        r = a.ejecutar(CONV, "hola").respuesta
        assert len(_fotos(r)) == 3, "la foto del anillo y los dos videos"
        assert "$200.000" in _texto(r) and "$300.000" in _texto(r)
        assert "talla" in _texto(r).lower(), "la apertura termina preguntando la talla"


# ══════════════════════════════════════════════════════════════════════════
#  4. La venta entera, como las de los PDF
# ══════════════════════════════════════════════════════════════════════════


class TestLaVentaCompleta:
    """El esqueleto de «Sexta.pdf»: pregunta → talla de una foto → colores →
    grabado → resumen → cuentas → comprobante."""

    def test_de_hola_al_comprobante_sin_atascarse(self, mundo):
        a = _asesora(
            mundo,
            _jugada("", AccionAsesora.MOSTRAR_PRECIOS, final="¿Sabes tu talla?"),
            # «No sé la talla, me regalas la guía» ya NO pasa por el modelo:
            # es la respuesta a una pregunta nuestra y siempre es la misma.
            _jugada("¡Perfecto!", medida_cm=1.73),
            _jugada("Estos son los colores 🩵", AccionAsesora.MOSTRAR_MUESTRARIO),
            _jugada(
                "¡Qué lindo! ¿Y el grabado?",
                cantidad_huellitas=1,
                huellitas=[HuellitaPropuesta(numero=1, corazon=C.MORADO, dedos=C.MORADO)],
            ),
            _jugada("¿Así está bien? 🥰", grabado=["Lilú"], nombre_clienta="Angélica"),
            _jugada("¡Listo! 🫶", AccionAsesora.PEDIR_ABONO),
            _jugada("¡Recibido! 🙌", AccionAsesora.RECIBIR_COMPROBANTE),
        )
        guion = [
            "Hola! Quiero hacer un pedido 🌷",
            "No sé la talla, me regalas la guía",
            "[foto del anillo con la regla]",
            "¿qué colores tienes?",
            "me gusta el morado, toda la huellita",
            "Lilú, y soy Angélica",
            "sí, así está perfecto",
            "[comprobante]",
        ]
        for mensaje in guion:
            if mensaje == "[comprobante]":
                # El comprobante llega como FOTO: escribir la palabra no es pagar
                # (regla de Camilo, 21/09: sin comprobante ni «ya pagué», no hay pago).
                comprobante = [{"kind": "image", "descripcion": "comprobante $60.000"}]
                turno = a.ejecutar(CONV, "", comprobante)
            else:
                turno = a.ejecutar(CONV, mensaje)
            assert turno.respuesta.piezas, f"se quedó mudo en «{mensaje}»"

        b = Borrador.model_validate(turno.contexto.borrador)
        assert b.falta_para_abono() == [], f"el pedido quedó a medias: {b.resumen()}"
        assert b.talla == 7 and b.grabado == ["Lilú"]
        assert b.pedido_id, "no nació el pedido"
        assert b.abono_reportado, "no quedó registrado que mandó el comprobante"
        assert mundo.pedidos_de(CONV)[0].estado == "EN_REVISION_PAGO"

    def test_las_cuentas_salen_UNA_vez_y_con_el_abono(self, mundo):
        a = _asesora(
            mundo,
            _jugada(
                "¿Así está bien? 🥰",
                cantidad_huellitas=1,
                huellitas=[HuellitaPropuesta(numero=1, corazon=C.NEGRO, dedos=C.NEGRO)],
                grabado=["Rocky"],
                talla=7,
                nombre_clienta="Laura",
            ),
            _jugada("¡Listo! 🫶", AccionAsesora.PEDIR_ABONO),
        )
        a.ejecutar(CONV, "una negra que diga Rocky, talla 7, soy Laura")
        texto = _texto(a.ejecutar(CONV, "sí").respuesta)
        assert "60.000" in texto and "Nequi" in texto
        assert texto.count("Nequi") == 1


# ══════════════════════════════════════════════════════════════════════════
#  5. Lo que pasa cuando la clienta no sigue el guion
# ══════════════════════════════════════════════════════════════════════════


class TestCaminosTorcidos:
    @pytest.mark.parametrize(
        "mensaje",
        [
            "?",
            "hola?",
            "ahí?",
            "...",
            "👋",
        ],
    )
    def test_un_mensaje_minimo_no_deja_al_bot_mudo(self, mundo, mensaje):
        """Un «?» es lo que escribe alguien a quien dejaste sin respuesta.
        Contestarle con silencio es perderla."""
        a = _asesora(mundo, _jugada("¡Aquí estoy! 🥰"))
        assert a.ejecutar(CONV, mensaje).respuesta.piezas

    def test_manda_el_comprobante_sin_haber_pedido_nada(self, mundo):
        """Pasa: transfiere antes de terminar de escoger. El pedido NO nace,
        el pago queda apuntado y se le pide lo que falta."""
        a = _asesora(mundo, _jugada("¡Recibido! 🙌", AccionAsesora.RECIBIR_COMPROBANTE))
        t = a.ejecutar(CONV, "ya te transferí los 60")
        b = Borrador.model_validate(t.contexto.borrador)
        assert b.pagado_sin_pedido and not b.pedido_id
        assert b.falta_para_abono(), "no puede estar completo: no escogió nada"

    def test_cambia_de_opinion_con_el_color(self, mundo):
        a = _asesora(
            mundo,
            _jugada(
                "¡Lila, qué lindo! 💜",
                cantidad_huellitas=1,
                huellitas=[HuellitaPropuesta(numero=1, corazon=C.LILA, dedos=C.LILA)],
            ),
            _jugada(
                "¡Cambiado a negro! 🖤",
                huellitas=[HuellitaPropuesta(numero=1, corazon=C.NEGRO, dedos=C.NEGRO)],
            ),
        )
        a.ejecutar(CONV, "lila toda")
        t = a.ejecutar(CONV, "mejor negro")
        b = Borrador.model_validate(t.contexto.borrador)
        assert b.huellitas[0].corazon is C.NEGRO


class TestNoRepiteLasMismasFotos:
    """20/09: enseñó «Todo rosado» y «Todo rojo», y al turno siguiente —cuando
    ella ya hablaba de la talla— volvió a mandar las mismas dos fotos."""

    def test_las_mismas_vistas_dos_turnos_seguidos_no_se_repiten(self, mundo):
        a = _asesora(
            mundo,
            _ver(("Todo rosado", C.ROSADO), ("Todo rojo", C.ROJO)),
            _ver(("Todo rosado", C.ROSADO), ("Todo rojo", C.ROJO)),
        )
        assert len(_fotos(a.ejecutar(CONV, "muéstrame ambos").respuesta)) == 2
        assert not _fotos(a.ejecutar(CONV, "mi anillo mide 1.7").respuesta)

    def test_pero_un_color_NUEVO_si_se_enseña(self, mundo):
        """Lo que no puede pasar es lo contrario: que pida otro color y no se
        lo enseñe por haber enseñado algo antes."""
        a = _asesora(
            mundo,
            _ver(("Todo rosado", C.ROSADO)),
            _ver(("Todo azul", C.AZUL_REY)),
        )
        a.ejecutar(CONV, "muéstrame el rosado")
        assert _fotos(a.ejecutar(CONV, "y en azul?").respuesta)

    def test_la_de_lo_que_escogio_tampoco_se_repite(self, mundo):
        """Prueba de verdad (05/10): escogió los colores, le llegó «Así se te va a
        ver», contestó «sí, así está bien» y le llegó otra vez idéntica."""
        negro = [HuellitaPropuesta(numero=1, corazon=C.NEGRO, dedos=C.NEGRO)]
        a = _asesora(
            mundo,
            _jugada(
                "¡Toda en negro! ¿Qué nombre grabamos?",
                AccionAsesora.MOSTRAR_COMO_QUEDA,
                cantidad_huellitas=1,
                huellitas=negro,
            ),
            _jugada(
                "¡Listo! ¿A nombre de quién va el pedido?",
                AccionAsesora.MOSTRAR_COMO_QUEDA,
                huellitas=negro,
            ),
        )
        assert _fotos(a.ejecutar(CONV, "una huellita toda negra").respuesta)
        assert not _fotos(a.ejecutar(CONV, "sí, así está bien").respuesta)


# ══════════════════════════════════════════════════════════════════════════
#  6. La apertura no cuesta nada
# ══════════════════════════════════════════════════════════════════════════


class _GuionQueSeQueja:
    """Un modelo que revienta si alguien lo llama. Es el test."""

    entradas: ClassVar[list] = []

    def jugar(self, *a, **kw):
        raise AssertionError("la apertura NO puede llamar al modelo")

    def __getattr__(self, nombre):
        return self.jugar


def _mundo_en_blanco():
    from app.adapters.repositories.memory import (
        InMemoryCustomerRepository,
        InMemoryOrderRepository,
    )
    from app.conversacion.mundo import Mundo
    from app.domain.models import Channel, Customer
    from tests.unit.test_inteligencia_conversacional import (
        ContextoEnMemoria,
        _productos,
    )

    customers = InMemoryCustomerRepository()
    customers.upsert(
        Customer(id="c1", channel=Channel.WHATSAPP, channel_user_id="573001112233")
    )
    return Mundo(
        InMemoryOrderRepository(),
        customers,
        _productos(),
        ContextoEnMemoria(),
        render=_LapizDeMentira(),
    )


def _asesora_en_blanco(*jugadas):
    from app.conversacion.asesora import Asesora, HechosDelNegocio
    from tests.unit.test_asesora import Guion

    mundo = _mundo_en_blanco()
    hechos = HechosDelNegocio(precios={1: 200_000, 2: 250_000, 3: 300_000})
    modelo = Guion(*jugadas) if jugadas else _GuionQueSeQueja()
    return Asesora(mundo, modelo, "{hechos}", hechos), mundo


class TestLaAperturaNoGastaTokens:
    """La respuesta al primer mensaje es SIEMPRE la misma, en las siete
    conversaciones reales de Lía. Pagarle a un modelo por elegir entre una
    sola opción es pagar por una decisión ya tomada — y encima tarda 2-4
    segundos justo donde la clienta decide si esto va en serio."""

    @pytest.mark.parametrize(
        "primer_mensaje",
        [
            "Hola",
            "hola, ¿qué precio tiene el anillo?",
            "Hola! Quiero hacer un pedido 🌷",
            "Buenas, vi tu anuncio en Instagram",
            "Hola, requiero más información",
            "¡Hola! Cuánto vale un anillo con dos huellitas",
            "buenas noches",
            "😍",
            # Se parece a una queja y no lo es: la apertura gratis sigue.
            "Hola, me llegó la publicidad del anillo",
        ],
    )
    def test_el_primer_mensaje_no_llama_al_modelo(self, primer_mensaje):
        a, _ = _asesora_en_blanco()  # el modelo revienta si lo llaman
        r = a.ejecutar(CONV, primer_mensaje).respuesta
        assert "$200.000" in _texto(r) and "$300.000" in _texto(r)
        assert len(_fotos(r)) == 3, "la foto del anillo y los dos videos"
        assert "talla" in _texto(r).lower()

    @pytest.mark.parametrize(
        "primer_mensaje",
        [
            # Cuenta algo suyo: la lee la IA (Camilo, 17/10). A «es para mi
            # hermana, se le murió su perrita» le llegaba «¿Cómo se llama tu
            # peludito?» sin que nadie la leyera.
            "Hola, se lo quiero regalar a mi mamá",
            "se me ocurrió regalarle uno a mi novia",
            "Hola! Quiero uno para Roberta, mi perrita",
            "es para mi hermana, se le murió su perrita hace un mes",
        ],
    )
    def test_si_cuenta_algo_suyo_la_lee_el_modelo(self, primer_mensaje):
        from app.conversacion.asesora import es_un_arranque_de_cajon

        assert not es_un_arranque_de_cajon(primer_mensaje)

    @pytest.mark.parametrize(
        "primer_mensaje",
        [
            "Hola, ¿tienen cadenas?",
            # Tocó «Enviar mensaje» en la cadena del catálogo de WhatsApp (03/10).
            "[Escribe desde la vitrina de WhatsApp, mirando: Cadena huellita con "
            "nombre]\nHola, ¿cuánto se demora?",
        ],
    )
    def test_si_de_entrada_pregunta_por_la_cadena_la_lee_el_modelo(self, primer_mensaje):
        a, _ = _asesora_en_blanco(_jugada("¡Claro! 💗", AccionAsesora.MOSTRAR_CADENA))
        r = a.ejecutar(CONV, primer_mensaje).respuesta
        assert "$250.000" in _texto(r) and "$65.000" in _texto(r)
        assert "talla" not in _texto(r).lower(), "no la ficha del anillo"

    def test_la_apertura_dice_el_nombre_del_negocio(self):
        a, _ = _asesora_en_blanco()
        assert "Luna Joyas" in _texto(a.ejecutar(CONV, "hola").respuesta)

    def test_el_SEGUNDO_mensaje_si_pasa_por_el_modelo(self):
        a, _ = _asesora_en_blanco(_jugada("¡Dale! Te la comparto 📏"))
        a.ejecutar(CONV, "hola")
        assert "Te la comparto" in _texto(a.ejecutar(CONV, "no sé mi talla").respuesta)

    def test_despues_de_la_apertura_no_se_repite_la_ficha(self):
        """La apertura cuenta como la presentación: si el modelo pide
        MOSTRAR_PRECIOS después, ya no sale."""
        a, _ = _asesora_en_blanco(_jugada("", AccionAsesora.MOSTRAR_PRECIOS))
        a.ejecutar(CONV, "hola")
        r = a.ejecutar(CONV, "y cuánto vale?").respuesta
        assert "$250.000" not in _texto(r)
        assert not _fotos(r)

    def test_una_FOTO_de_entrada_si_va_al_modelo(self):
        """Puede ser la huella de su mascota o la regla de la talla: eso no se
        contesta con una presentación fija."""
        a, _ = _asesora_en_blanco(_jugada("¡Qué lindo tu peludito! 🐾"))
        r = a.ejecutar(CONV, "", media=[{"kind": "image", "media_id": "m1"}]).respuesta
        assert "peludito" in _texto(r)

    @pytest.mark.parametrize(
        "queja",
        [
            "ustedes son unos estafadores de mierda, devuélvanme la plata",
            "Quiero la devolución de mi dinero",
            "el anillo llegó dañado",
            "hola, no me llegó el pedido",
            "quiero poner un reclamo",
            "Hola, me llegó el anillo y se le cayó una piedrita del corazón 😡",
            "buenas, ¿el anillo tiene garantía? se me peló",
        ],
    )
    def test_una_QUEJA_de_entrada_no_recibe_el_catalogo(self, queja):
        """Repaso del 21/09: a «estafadores… devuélvanme la plata» le llegó la
        bienvenida con los precios, y a Lía no le avisó nadie."""
        a, _ = _asesora_en_blanco(
            _jugada(
                "Lamento mucho esto. Ya le paso tu mensaje a Lía 💓",
                AccionAsesora.PASAR_A_LIA,
            )
        )
        r = a.ejecutar(CONV, queja).respuesta
        assert "$200.000" not in _texto(r), "le mandó el catálogo a una queja"
        assert r.escalar, "a Lía no le avisó nadie"

    def test_la_apertura_queda_guardada_en_la_charla(self):
        """El turno siguiente tiene que saber qué se dijo, o el modelo
        saludaría otra vez."""
        a, mundo = _asesora_en_blanco(_jugada("¡Dale!"))
        a.ejecutar(CONV, "hola")
        ctx = mundo.contexto(CONV)
        assert ctx.charla, "la apertura no quedó en la memoria de la charla"
        # Se guarda el FINAL del mensaje: la ficha es fija y el modelo ya la
        # tiene en sus hechos; lo que hace falta recordar es qué preguntamos.
        assert "talla" in ctx.charla[-1]["texto"].lower()


# ══════════════════════════════════════════════════════════════════════════
#  7. Los datos de envío del final, que es donde se rompió
# ══════════════════════════════════════════════════════════════════════════


class TestLosDatosDeEnvioSeGuardan:
    """20/09, 02:20. El bot le pidió los datos con las fotos del anillo
    terminado. Ella mandó exactamente eso:

        Ciudad: … · Nombre completo: Roberto Hernández Rosas
        Cédula: 823838283 · Celular: … · Dirección: …

    y el sistema los RECHAZÓ enteros y escaló la conversación a una persona:

        «el pedido PED-2026-1543 está en ESPERANDO_SALDO: el cambio de
         cedula, ciudad, direccion lo decide Lía (no se guardó)»

    La política de cambios se escribió antes de que existieran `cedula` y
    `celular`, así que el conjunto no encajaba con lo permitido. Es el peor
    sitio para fallar: el anillo está hecho, el abono pagado, y lo único que
    falta para despacharlo es justo lo que ella acaba de escribir.
    """

    def _pedido_listo(self, mundo):
        """Un pedido con el anillo hecho, esperando el saldo."""
        from app.domain.envio import DatosDeEnvio
        from app.domain.models import Order, OrderItem
        from app.domain.personalizacion import Huellita, Personalizacion

        diseno = Personalizacion(
            talla=7,
            huellitas=[Huellita(corazon=C.NEGRO, dedos=C.NEGRO)],
            grabados=["Rocky"],
        )
        return mundo._orders.create(
            Order(
                codigo="PED-2026-1543",
                customer_id="c1",
                estado="ESPERANDO_SALDO",
                items=[
                    OrderItem(
                        sku="ANI-HUE-1",
                        nombre="Anillo huellita x1",
                        cantidad=1,
                        precio_unitario_cop=200_000,
                        personalizacion=diseno,
                    )
                ],
                total_cop=200_000,
                anticipo_cop=60_000,
                saldo_cop=140_000,
                anticipo_pagado_cop=60_000,
                envio=DatosDeEnvio(nombre="Roberto", telefono="573001112233"),
            ),
            idem_key="k",
        )

    def _con_pedido(self, mundo, *jugadas):
        from app.domain.asesora import Borrador as B

        pedido = self._pedido_listo(mundo)
        a = _asesora(mundo, *jugadas)
        ctx = mundo.contexto(CONV)
        b = B(
            cantidad=1,
            talla=7,
            grabado=["Rocky"],
            nombre_clienta="Roberto",
            pedido_id=pedido.id,
            pedido_codigo=pedido.codigo,
            abono_reportado=True,
            turnos=8,
        )
        mundo.guardar_contexto(
            ctx.model_copy(update={"borrador": b.model_dump(mode="json")})
        )
        return a, pedido

    def test_los_cinco_datos_de_la_guia_se_guardan(self, mundo):
        a, pedido = self._con_pedido(
            mundo,
            _jugada(
                "¡Listo, ya quedaron anotados! 🥰",
                ciudad="Bucaramanga",
                nombre_clienta="Roberto Hernández Rosas",
                cedula="823838283",
                celular="3001110003",
                direccion="Calle 87 #17-70",
            ),
        )
        t = a.ejecutar(CONV, "Bucaramanga, Roberto Hernández Rosas, CC 823838283…")
        assert not t.respuesta.escalar, "escaló en vez de guardar lo que le pidió"
        envio = mundo.pedido(pedido.id).envio
        assert envio.ciudad == "Bucaramanga"
        assert envio.cedula == "823838283"
        assert envio.celular == "3001110003"
        assert "Calle 87" in envio.direccion

    def test_con_los_datos_puestos_YA_SE_PUEDE_despachar(self, mundo):
        from app.domain.operacion import falta_para_despachar

        a, pedido = self._con_pedido(
            mundo,
            _jugada(
                "¡Anotado! 🥰",
                ciudad="Bucaramanga",
                nombre_clienta="Roberto Hernández Rosas",
                cedula="823838283",
                celular="3001110003",
                direccion="Calle 87 #17-70",
            ),
        )
        a.ejecutar(CONV, "ahí van mis datos")
        # De ella no falta nada; lo único que queda es la guía, que la pone Lía
        # al despacharlo (obligatoria desde el 29/09).
        assert falta_para_despachar(mundo.pedido(pedido.id)) == ["número de guía"]

    def test_pero_cambiar_el_COLOR_con_el_anillo_hecho_sigue_yendo_a_Lía(self, mundo):
        """Lo que la política protege de verdad no se toca: el anillo ya
        existe, y «mejor rosado» aquí es plata fundida."""
        a, _ = self._con_pedido(
            mundo,
            _jugada(
                "Déjame consultarlo 🥺",
                huellitas=[HuellitaPropuesta(numero=1, corazon=C.ROSADO, dedos=C.ROSADO)],
            ),
        )
        t = a.ejecutar(CONV, "¿lo puedo cambiar a rosado?")
        assert t.respuesta.escalar


class TestLaGuiaDeLaTallaTampocoGastaTokens:
    """La apertura termina preguntando por la talla, así que el SEGUNDO turno
    de casi toda conversación es «no sé, mándame la guía». Esa respuesta es
    fija: la guía y su foto, siempre igual.

    La condición es estrecha a propósito — solo justo después de nuestra
    pregunta y sin ningún número —, porque adivinar intenciones en general ya
    se intentó con el gestor por etiquetas y no funcionó (ADR 0014)."""

    @pytest.mark.parametrize(
        "respuesta_de_ella",
        [
            "no sé",
            "No sé la talla",
            "ni idea",
            "me regalas la guia por favor 🙏",
            "mándame la guía",
            "la guía porfa",
            "compártemela",
            "dale",
            "guia",
        ],
    )
    def test_no_llama_al_modelo(self, respuesta_de_ella):
        a, _ = _asesora_en_blanco()  # el modelo revienta si lo llaman
        a.ejecutar(CONV, "hola")
        r = a.ejecutar(CONV, respuesta_de_ella).respuesta
        assert "toda la mitad del anillo" in _texto(r)
        assert _fotos(r) == ["medir_talla_guia"]

    @pytest.mark.parametrize(
        "respuesta_de_ella",
        [
            "soy talla 7",
            "7",
            "creo que soy 5 pero no estoy segura",
            "mide 1.8 cm",
            "¿y de qué material es?",
            "¿cuánto se demora?",
            "quiero dos huellitas",
        ],
    )
    def test_cualquier_otra_cosa_SÍ_va_al_modelo(self, respuesta_de_ella):
        """Un número puede ser su talla, y una pregunta es una pregunta. Ante
        la duda, al modelo."""
        a, _ = _asesora_en_blanco(_jugada("¡Lo miro! 🥰"))
        a.ejecutar(CONV, "hola")
        assert "¡Lo miro!" in _texto(a.ejecutar(CONV, respuesta_de_ella).respuesta)

    def test_solo_justo_despues_de_NUESTRA_pregunta(self):
        """«Dale» a mitad de una conversación de colores no es pedir la guía."""
        a, _ = _asesora_en_blanco(
            _jugada("Estos son los colores 🩵", AccionAsesora.MOSTRAR_MUESTRARIO),
            _jugada("¡Perfecto! 💜"),
        )
        a.ejecutar(CONV, "hola")
        a.ejecutar(CONV, "quiero ver colores")
        assert "¡Perfecto!" in _texto(a.ejecutar(CONV, "dale").respuesta)

    def test_si_ya_tiene_talla_no_se_le_manda_la_guia(self):
        a, _ = _asesora_en_blanco(_jugada("¡Talla 7! 💍", talla=7), _jugada("¡Claro! 🥰"))
        a.ejecutar(CONV, "hola")
        a.ejecutar(CONV, "soy talla 7")
        assert "¡Claro!" in _texto(a.ejecutar(CONV, "dale").respuesta)


class TestNoPreguntarLoQueYaSABEMOS:
    """20/09, 06:01. Mandó la foto de la regla como PRIMER mensaje y el bot
    contestó, en este orden:

        ¡Es una talla 6.5! 💍
        ¡Hola! 👋 Muy bien, gracias por la foto.
        [la ficha entera] [video] [video]
        ¿Sabes tu talla de anillo o te comparto la guía? 💍💜

    Le acababa de decir su talla y a renglón seguido le preguntaba si la
    sabe."""

    def test_con_la_talla_ya_sabida_la_presentacion_no_la_pregunta(self, mundo):
        a = _asesora(
            mundo,
            _jugada(
                "¡Gracias por la foto! 🥰",
                AccionAsesora.MOSTRAR_PRECIOS,
                final="¿De cuántas huellitas lo quieres? 🐾",
                medida_cm=1.73,
            ),
        )
        r = a.ejecutar(CONV, "[foto de la regla]").respuesta
        texto = _texto(r)
        assert "talla 7" in texto.lower(), "tiene que decirle su talla"
        assert "¿Sabes tu talla" not in texto, "le preguntó la talla que acaba de darle"
        assert "cuántas huellitas" in texto, "el cierre lo pone el modelo"

    def test_sin_talla_la_presentacion_SÍ_la_pregunta(self, mundo):
        """Lo de siempre no se rompe."""
        a = _asesora(mundo, _jugada("", AccionAsesora.MOSTRAR_PRECIOS))
        assert "¿Sabes tu talla" in _texto(a.ejecutar(CONV, "hola, precios?").respuesta)


class TestUnTurnoNuncaSeQuedaMudo:
    """20/09, 02:17. Camilo mandó «Roberto» —su nombre, que ya estaba anotado—
    y el modelo devolvió un mensaje vacío: no había nada nuevo que contestar.

        02:17:23  entra: 'Roberto'
        02:17:26  no pasó: el mensaje quedó vacío tras vigilarlo

    Lo que le llegó fue «¡Listo! 🙌» y nada más, así que la conversación se
    quedó parada esperando a que ella adivinara el siguiente paso. Lía nunca
    deja un turno muerto: si no hay nada que responder, pregunta lo que falta.
    """

    def test_sin_nada_que_decir_pregunta_lo_que_falta(self, mundo):
        a = _asesora(mundo, _jugada(""))
        b = Borrador(nombre_clienta="Roberto")
        assert "cuántas huellitas" in a._lo_que_falta(b)

    def test_con_el_anillo_listo_pregunta_su_nombre(self, mundo):
        a = _asesora(mundo, _jugada(""))
        b = Borrador(
            cantidad=1,
            talla=7,
            huellitas=[HuellitaDelBorrador(corazon=C.ROSADO, dedos=C.BLANCO)],
            sin_grabado=True,
        )
        assert "nombre completo" in a._lo_que_falta(b)

    def test_tras_el_abono_pregunta_los_datos_de_la_guia(self, mundo):
        a = _asesora(mundo, _jugada(""))
        b = Borrador(nombre_clienta="Roberto", abono_reportado=True)
        assert "ciudad" in a._lo_que_falta(b)

    def test_sin_nada_que_pedir_no_se_inventa_una_pregunta(self, mundo):
        """Esperando a una persona no se le pregunta nada más."""
        a = _asesora(mundo, _jugada(""))
        b = Borrador(
            nombre_clienta="Roberto",
            ciudad="Medellín",
            cedula="1017",
            celular="3001110003",
            direccion="Cra 1 # 2-3, Laureles",
            abono_reportado=True,
        )
        assert "?" not in a._lo_que_falta(b)


class TestLaPreguntaDeCierreNoSeRepite:
    """Repaso del 20/09, sint-02-descuento. Cuatro turnos seguidos pidiendo lo
    mismo, cada vez detrás de una frase distinta:

        [4] ¡Perfecto! 3 huellitas 🫶 ¿Sabes tu talla o te comparto la guía?
        [5] ¡Qué combinación tan linda! 🔥 … Ahora sí, ¿sabes tu talla…? 💍
        [6] Perfecto, liso sin grabado 🫶 Ahora sí, ¿sabes tu talla…? 💍

    La rama que quita una pregunta de cierre repetida ya existía, pero nunca se
    encendía: se comparaba el mensaje ENTERO, y como la frase de arriba cambiaba
    cada vez, el parecido total no llegaba al 75%. La pregunta, idéntica, pasaba
    de contrabando.
    """

    def test_la_misma_pregunta_detras_de_otra_frase_se_quita(self, mundo):
        a = _asesora(
            mundo,
            _jugada(
                "¡Perfecto! 3 huellitas 🫶",
                final="¿Sabes tu talla o te comparto la guía? 💍",
            ),
            _jugada(
                "Perfecto, liso sin grabado 🫶",
                final="Ahora sí, ¿sabes tu talla de anillo o te comparto la guía? 💍",
            ),
        )
        a.ejecutar(CONV, "dame uno de 3 huellitas")
        segundo = _texto(a.ejecutar(CONV, "sin grabado, liso").respuesta)
        assert "liso sin grabado" in segundo, "se perdió la respuesta a lo que dijo"
        assert "te comparto la guía" not in segundo, "pidió la talla dos turnos seguidos"

    def test_una_pregunta_de_cierre_distinta_sí_pasa(self, mundo):
        """Lo de siempre no se rompe: preguntar otra cosa es lo normal."""
        a = _asesora(
            mundo,
            _jugada("¡Perfecto! 3 huellitas 🫶", final="¿Sabes tu talla? 💍"),
            _jugada(
                "Perfecto, liso sin grabado 🫶",
                final="¿Me regalas tu nombre completo, porfa? 🥰",
            ),
        )
        a.ejecutar(CONV, "dame uno de 3 huellitas")
        segundo = _texto(a.ejecutar(CONV, "sin grabado, liso").respuesta)
        assert "nombre completo" in segundo


class TestElAbonoBloqueadoNoDejaLaPromesaColgando:
    """Repaso del 20/09, sint-03-mascota-fallecida (y 10 escenarios más):

        [8] bot: … ¿A nombre de quién va el pedido? 🥰
        [9] clienta: sí, así está perfecto
        [9] bot: ¡Listo! 🫶 Te dejo los datos 💓
            no pasó: no se pidió abono: falta nombre completo

    Ella entendió «¿a nombre de quién?» como una formalidad. El modelo pidió el
    abono, el sistema lo bloqueó con razón —sin nombre no nace el pedido— y a
    ella le llegó la promesa sin lo prometido: ni los datos para transferir, ni
    la noticia de que faltaba algo. Ahí se acaba la venta.
    """

    def test_sin_el_nombre_le_pide_el_nombre_y_no_promete_datos(self, mundo):
        a = _asesora(
            mundo,
            _jugada(
                "¡Perfecto! Una huellita 🐾",
                cantidad_huellitas=1,
                talla=7,
                huellitas=[HuellitaPropuesta(numero=1, corazon=C.NEGRO, dedos=C.BLANCO)],
                sin_grabado=True,
            ),
            _jugada("¡Listo! 🫶 Te dejo los datos 💓", AccionAsesora.PEDIR_ABONO),
        )
        a.ejecutar(CONV, "de 1 huellita, corazón negro y deditos blancos, sin grabado")
        r = a.ejecutar(CONV, "sí, así está perfecto").respuesta
        texto = _texto(r)
        assert "nombre" in texto.lower(), f"no le dijo qué falta: {texto!r}"
        assert "3001110003" not in texto, "prometió datos de pago sin tomar el pedido"


class TestALaTerceraSeLlamaALia:
    """Repaso del 20/09, sint-05-color-que-no-existe y sint-10-ya-pague-sin-foto:

        [3] bot: ¿Lo quieres de 1, 2 o 3 huellitas?
        [4] bot: Y dime, ¿lo quieres de 1, 2 o 3 huellitas?
        [5] bot: Perfecto, talla 5 💍 ¿Lo quieres de 1, 2 o 3 huellitas?
        [6] clienta: listo, así
        [6] bot: ¿Me confirmas cuántas huellitas? 😊 ¿De 1 huellita o de 2?

    La guardia de la cantidad está bien —cambia el precio, y un «listo, así» no
    elige— pero no tenía salida. En sint-10 la clienta llegó a decir que ya
    había pagado y el bot seguía preguntando lo mismo.
    """

    def test_a_la_tercera_pasa_a_lia(self, mundo):
        jugadas = [_jugada("¿De cuántas?", cantidad_huellitas=2) for _ in range(3)]
        a = _asesora(mundo, *jugadas)
        for _ in range(2):
            r = a.ejecutar(CONV, "listo, así").respuesta
            assert not r.escalar, "se rindió antes de tiempo"
        r = a.ejecutar(CONV, "listo, así").respuesta
        assert r.escalar, "siguió dando vueltas en vez de llamar a Lía"
        assert "momentico" in _texto(r)

    def test_si_escribe_el_número_no_pasa_a_lia(self, mundo):
        """Lo de siempre no se rompe: con un número, se sigue de largo."""
        a = _asesora(
            mundo,
            _jugada("¿De cuántas?", cantidad_huellitas=2),
            _jugada("¡Dos huellitas! 🐾", cantidad_huellitas=2),
        )
        a.ejecutar(CONV, "listo, así")
        r = a.ejecutar(CONV, "de 2 huellitas").respuesta
        assert not r.escalar
        assert "Dos huellitas" in _texto(r)


class TestNingunMensajeSeQuedaSinPreguntar:
    """Camilo, 20/09. Dio su nombre, le llegó el resumen del pedido y debajo:

        •Anillo 1 huellita•
        Talla: 9 · Color: Celeste / Dedos: Azul rey · Grabado: Roberto ♡
        •Entrega• A nombre de: Camilo

        ¡Perfecto Camilo! 🫶

    Y ahí se acabó. Faltaba «¿así está bien?»: ella no sabe si tiene que
    contestar ni qué, y se queda mirando el chat. Quien vende termina
    preguntando — salvo cuando de verdad hay que esperar a alguien.
    """

    def test_tras_el_resumen_le_pide_que_lo_confirme(self, mundo):
        a = _asesora(
            mundo,
            _jugada(
                "¡Listo! Una huellita celeste 💚",
                cantidad_huellitas=1,
                talla=9,
                huellitas=[
                    HuellitaPropuesta(numero=1, corazon=C.CELESTE, dedos=C.AZUL_REY)
                ],
                sin_grabado=True,
            ),
            _jugada(
                "¡Perfecto Camilo! 🫶",
                AccionAsesora.MOSTRAR_RESUMEN,
                nombre_clienta="Camilo",
            ),
        )
        a.ejecutar(CONV, "de 1 huellita, celeste con deditos azul rey, sin grabado")
        texto = _texto(a.ejecutar(CONV, "Camilo").respuesta)
        assert "¡Perfecto Camilo!" in texto, "se perdió lo que había escrito"
        assert "?" in texto, f"se quedó sin preguntar nada: {texto!r}"

    def test_un_mensaje_que_ya_pregunta_se_queda_igual(self, mundo):
        a = _asesora(mundo, _jugada("¡Perfecto! ¿De qué color lo quieres? 🩵"))
        texto = _texto(a.ejecutar(CONV, "listo").respuesta)
        assert texto.count("?") == 1, f"le metió una segunda pregunta: {texto!r}"

    def test_con_el_pago_reportado_no_se_le_pregunta_encima(self, mundo):
        """Ya pagó: lo siguiente lo hace Lía, mirando el banco. Una pregunta
        encima no le deja nada que contestar.

        Ojo, no es lo mismo que esperar SU transferencia: ahí sí se cierra con
        pregunta, «Quedo atenta a tu comprobante 💓 ¿Te puedo ayudar con algo
        más?» (ADR 0022, 21/09). Esta prueba decía antes «la pelota la tiene
        ella», que era la regla del 20/09."""
        a = _asesora(mundo, _jugada("¡Recibido! 🙌"))
        ctx = mundo.contexto(CONV)
        b = Borrador(**ctx.borrador) if ctx.borrador else Borrador()
        b.abono_reportado = True
        mundo.guardar_contexto(
            ctx.model_copy(update={"borrador": b.model_dump(mode="json")})
        )
        assert "?" not in _texto(a.ejecutar(CONV, "ya transferí").respuesta)


class TestLaCantidadQueYaDijoNoSeVuelveAPreguntar:
    """Probando el anillo de tres el 20/09:

        clienta: hola, quiero el de 3 huellitas
        bot:     [la presentación] ¿Sabes tu talla de anillo…?
        clienta: talla 8
        bot:     Perfecto, talla 8 💍 ¿De cuántas huellitas lo quieres?

    Lo acababa de decir. El primer mensaje va a la apertura fija —de cero
    tokens, y así se queda—, y al turno siguiente la guardia de la cantidad la
    volvía a tumbar porque solo miraba el mensaje de ESE turno.
    """

    def test_lo_dicho_en_el_primer_mensaje_cuenta(self, mundo):
        from app.domain.asesora import cantidad_respaldada

        assert cantidad_respaldada(
            3, "talla 8", "¿Sabes tu talla?", ["hola, quiero el de 3 huellitas"]
        )

    def test_un_si_suelto_sigue_sin_elegir_por_ella(self):
        """Lo de siempre no se rompe: la cantidad cambia el precio."""
        from app.domain.asesora import cantidad_respaldada

        assert not cantidad_respaldada(
            2, "sí", "¿De 1 o de 2 huellitas?", ["hola", "me gusta el rosado"]
        )

    def test_en_la_charla_completa_no_vuelve_a_preguntarla(self, mundo):
        a = _asesora(
            mundo,
            _jugada("¡Listo, talla 8! 💍", talla=8, cantidad_huellitas=3),
            nueva=True,
        )
        a.ejecutar(CONV, "hola, quiero el de 3 huellitas")
        r = a.ejecutar(CONV, "talla 8").respuesta
        assert "cuántas huellitas" not in _texto(r), (
            "le volvió a preguntar la cantidad que abrió diciendo"
        )

    def test_lo_que_escribio_de_entrada_queda_en_la_memoria(self, mundo):
        """La apertura no le contesta a su primer mensaje —la respuesta es
        siempre la misma— pero tiene que acordarse de él. Guardaba el relleno
        «(su primer mensaje)» y se perdía todo: la cantidad, la mascota, el
        color, la ciudad."""
        a = _asesora(mundo, _jugada(""), nueva=True)
        a.ejecutar(CONV, "hola, quiero el de 3 huellitas para mi perrita Luna")
        charla = mundo.contexto(CONV).charla
        assert "3 huellitas" in charla[0]["texto"]
        assert "Luna" in charla[0]["texto"]

    def test_la_pregunta_de_relleno_no_se_repite_turno_tras_turno(self, mundo):
        """La pregunta que se añade es una frase FIJA. Ponerla en cada mensaje
        es peor que callarse: en el repaso del 20/09 salió la misma línea en
        nueve conversaciones seguidas. Si ya se la hicimos, el mensaje se queda
        como está."""
        a = _asesora(
            mundo,
            _jugada("¡Listo! 🫶", cantidad_huellitas=1),
            _jugada("Perfecto 🫶"),
        )
        primero = _texto(a.ejecutar(CONV, "de 1 huellita").respuesta)
        assert "?" in primero, "el primero sí tenía que preguntar algo"
        pregunta = primero[primero.index("¿") :]
        segundo = _texto(a.ejecutar(CONV, "ok").respuesta)
        assert "Perfecto" in segundo, "se perdió lo que había escrito"
        assert pregunta not in segundo, f"repitió la misma pregunta: {segundo!r}"


class TestLasNotasParaPaoNoSeAmontonan:
    """Repaso del 20/09, sint-10. La clienta dijo que ya había pagado con el
    pedido incompleto y en el panel quedaron tres notas para el mismo hecho:

        · La clienta dice que pagó el abono y el pedido NO está completo…
        · Clienta dice que pagó por Nequi pero no se envió comprobante…
        · Clienta pagó abono ($60k Nequi) antes de completar el pedido…

    El modelo lo vuelve a anotar cada turno con otras palabras. Una lista donde
    tres avisos dicen lo mismo se deja de mirar, y el día que haya uno de verdad
    se pierde entre el ruido.
    """

    def _ctx(self):
        from app.domain.contexto import ContextoConversacional

        return ContextoConversacional(conversation_id=CONV)

    def test_la_misma_nota_con_otras_palabras_no_se_repite(self):
        ctx = self._ctx()
        ctx = ctx.anotar_revision(
            "La clienta dice que pagó el abono y el pedido NO está completo "
            "(falta talla, nombre completo): no entra al taller hasta tenerlo"
        )
        ctx = ctx.anotar_revision(
            "Clienta dice que pagó el abono y el pedido no está completo "
            "(falta la talla y el nombre completo): no entra al taller"
        )
        assert len(ctx.revisar) == 1, ctx.revisar

    def test_un_aviso_distinto_sí_entra(self):
        """Perder un aviso de verdad es peor que repetir uno."""
        ctx = self._ctx()
        ctx = ctx.anotar_revision("Clienta pagó el abono antes de dar la talla")
        ctx = ctx.anotar_revision("Pidió cambiar el grabado de Kira a Kiara")
        assert len(ctx.revisar) == 2, ctx.revisar

    def test_las_identicas_siguen_sin_duplicarse(self):
        ctx = self._ctx()
        ctx = ctx.anotar_revision("Revisar la talla: la escribió ella")
        ctx = ctx.anotar_revision("Revisar la talla: la escribió ella")
        assert len(ctx.revisar) == 1


class TestLasCuentasNoSalenAntesDeQueConfirme:
    """Repaso del 20/09, sint-03. Ella da su nombre —lo último que faltaba— y
    el modelo manda MOSTRAR_RESUMEN + PEDIR_ABONO + MANDAR_CUENTAS. La guardia
    bloqueó PEDIR_ABONO… y MANDAR_CUENTAS mandó el Nequi de todos modos:

        > •Anillo 1 huellita• … ¿Está todo bien así? 💍
        > *Para el abono de $60.000 puedes transferir a:* …
        no pasó: no se pidieron las cuentas: el resumen es nuevo y ella no lo
                 ha confirmado

    El mismo mensaje le preguntaba si estaba bien y debajo le pedía la plata.
    Son la misma decisión, así que caen juntas — venga como venga el orden de
    las acciones.
    """

    def test_con_el_resumen_nuevo_no_se_manda_el_numero_de_cuenta(self, mundo):
        a = _asesora(
            mundo,
            _jugada(
                "¡Perfecto Diana! 🫶",
                AccionAsesora.MOSTRAR_RESUMEN,
                AccionAsesora.PEDIR_ABONO,
                AccionAsesora.MANDAR_CUENTAS,
                cantidad_huellitas=1,
                talla=7,
                huellitas=[HuellitaPropuesta(numero=1, corazon=C.NEGRO, dedos=C.BLANCO)],
                sin_grabado=True,
                nombre_clienta="Diana Restrepo",
            ),
        )
        texto = _texto(a.ejecutar(CONV, "de 1 huellita. Diana Restrepo").respuesta)
        assert "Diana" in texto, "se perdió el resumen"
        assert "LÍA GÓMEZ" not in texto, "le pidió la plata sin que confirmara"
        assert "3001110003" not in texto, "le pidió la plata sin que confirmara"


class TestSuNombreNoSePideACiegas:
    """Conversación REAL (`real-c-hola-cuanto-vale-un-anillo-con-dos-huellitas`).
    Pagó los $60.000 y el pedido no nació porque nunca escribió su nombre
    completo. Se lo pidieron CUATRO veces:

        [32] 📷 [Comprobante de $60.000]
        bot: ¡Recibido! 🙌 Apenas me des tu nombre completo paso tu pedido…
        [33] Pd cuando esté el anillo te puedo mandar el pago del envío?
        bot: … Ahora me das tu nombre completo y pasamos tu pedido, ¿dale?
        [34] Gracias
        bot: ¡Con gusto! 💓 Solo me falta tu nombre para pasarlo al taller 🥰

        nota: «Ha rechazado darlo dos veces»

    Con Lía esa venta se cerró: Lía lo tiene delante, en el contacto de
    WhatsApp. Nadie escribe su nombre en un chat donde el otro ya lo ve.
    """

    def _lista(self, mundo, **borrador):
        """Una clienta con el anillo escogido y sin nombre."""
        a = _asesora(mundo, *[_jugada("¡Listo! 🫶") for _ in range(3)])
        ctx = mundo.contexto(CONV)
        b = Borrador(
            cantidad=1,
            talla=7,
            huellitas=[HuellitaDelBorrador(corazon=C.NEGRO, dedos=C.BLANCO)],
            sin_grabado=True,
            **borrador,
        )
        mundo.guardar_contexto(
            ctx.model_copy(update={"borrador": b.model_dump(mode="json")})
        )
        return a

    def test_se_le_propone_el_de_whatsapp(self, mundo):
        a = self._lista(mundo)
        r = a.ejecutar(CONV, "ok", None, "Laura Gómez").respuesta
        assert "¿Lo dejo a nombre de Laura Gómez?" in _texto(r)

    def test_sin_nombre_de_whatsapp_no_se_inventa_ninguno(self, mundo):
        a = self._lista(mundo)
        assert "a nombre de" not in _texto(a.ejecutar(CONV, "ok").respuesta).lower()

    def test_un_perfil_sin_letras_no_se_propone(self, mundo):
        """Una clienta tenía «.» de nombre en WhatsApp y le llegó «¿Lo dejo a
        nombre de .? 🥰» (29/09)."""
        a = self._lista(mundo)
        assert "a nombre de ." not in _texto(a.ejecutar(CONV, "ok", None, ".").respuesta)

    def test_si_ya_pago_y_falta_el_nombre_lo_cierra_lia(self, mundo):
        """Dinero recibido con el pedido a medias no espera en un chat."""
        a = self._lista(mundo, abono_reportado=True)
        t = a.ejecutar(CONV, "Gracias", None, "Laura Gómez")
        assert t.respuesta.escalar, "se quedó insistiendo con la plata ya adentro"
        assert any("falta su nombre" in n for n in t.contexto.revisar), t.contexto.revisar
        assert any("Laura Gómez" in n for n in t.contexto.revisar), (
            "Lía necesita el nombre que sí tenemos para confirmarlo"
        )

    def test_a_lia_se_la_llama_una_vez_no_en_cada_turno(self, mundo):
        a = self._lista(mundo, abono_reportado=True)
        a.ejecutar(CONV, "Gracias", None, "Laura Gómez")
        segundo = a.ejecutar(CONV, "ahí te confirmo", None, "Laura Gómez")
        assert not segundo.respuesta.escalar, "le llenó la bandeja del mismo aviso"

    def test_con_el_nombre_ya_puesto_no_se_propone_nada(self, mundo):
        a = self._lista(mundo, nombre_clienta="Laura Gómez")
        assert "¿Lo dejo a nombre" not in _texto(
            a.ejecutar(CONV, "ok", None, "Laura Gómez").respuesta
        )

    def _pidiendo(self, mundo, *textos):
        """Como `_lista`, pero el modelo contesta lo que se le diga."""
        self._lista(mundo)
        return _asesora(mundo, *[_jugada(t) for t in textos])

    def test_la_segunda_vez_ya_no_se_pregunta_se_propone(self, mundo):
        """Prueba en vivo del 21/09: se lo pidió con tres frases distintas.

        bot: ¿A nombre de quién va el pedido? 🥰
        ella: Sí
        bot: ¿Cuál es tu nombre para el pedido? 🥰
        """
        a = self._pidiendo(
            mundo,
            "¿A nombre de quién va el pedido? 🥰",
            "¿Cuál es tu nombre para el pedido? 🥰",
        )
        primero = _texto(a.ejecutar(CONV, "así", None, "Laura Gómez").respuesta)
        assert "¿A nombre de quién va el pedido?" in primero, "la primera vez se pregunta"
        segundo = _texto(a.ejecutar(CONV, "Sí", None, "Laura Gómez").respuesta)
        assert "¿Lo dejo a nombre de Laura Gómez?" in segundo
        assert "tu nombre" not in segundo, f"lo volvió a preguntar: {segundo!r}"
        assert segundo.count("?") == 1, segundo

    def test_se_queda_lo_demas_de_la_frase(self, mundo):
        a = self._pidiendo(
            mundo,
            "¿A nombre de quién va? 🥰",
            "¡Listo! 🫶 Para pasar tu pedido al taller me confirmas tu nombre"
            " completo, ¿dale?",
        )
        a.ejecutar(CONV, "así", None, "Laura Gómez")
        texto = _texto(a.ejecutar(CONV, "ok", None, "Laura Gómez").respuesta)
        assert texto.startswith("¡Listo!"), texto
        assert "¿dale?" not in texto and "nombre completo" not in texto, texto
        assert "¿Lo dejo a nombre de Laura Gómez?" in texto

    def test_si_pregunta_otra_cosa_se_deja_como_venia(self, mundo):
        """Una pregunta por mensaje: no se cambia una por dos."""
        a = self._pidiendo(
            mundo,
            "¿A nombre de quién va? 🥰",
            "¿Te lo mando a Bogotá? ¿Y a nombre de quién va?",
        )
        a.ejecutar(CONV, "así", None, "Laura Gómez")
        texto = _texto(a.ejecutar(CONV, "ok", None, "Laura Gómez").respuesta)
        assert "¿Lo dejo a nombre" not in texto, texto

    def test_ya_propuesto_no_se_le_vuelve_a_meter(self, mundo):
        """Repaso del 21/09: contestó «No» a la propuesta y se la repitieron
        dos veces más en vez de dejar que el modelo le preguntara."""
        a = self._pidiendo(
            mundo,
            "¿A nombre de quién va? 🥰",
            "¿Cuál es tu nombre? 🥰",
            "Entonces, ¿a nombre de quién lo dejo? 🥰",
        )
        a.ejecutar(CONV, "así", None, "Laura Gómez")
        assert "Laura Gómez" in _texto(
            a.ejecutar(CONV, "ok", None, "Laura Gómez").respuesta
        )
        tercero = _texto(a.ejecutar(CONV, "No", None, "Laura Gómez").respuesta)
        assert "¿a nombre de quién lo dejo?" in tercero, tercero
        assert "Laura Gómez" not in tercero, (
            f"le volvió a proponer el que dijo que no: {tercero!r}"
        )

    def test_sin_nombre_de_whatsapp_se_sigue_preguntando(self, mundo):
        a = self._pidiendo(mundo, "¿A nombre de quién va? 🥰", "¿Cuál es tu nombre? 🥰")
        a.ejecutar(CONV, "así")
        assert "¿Cuál es tu nombre?" in _texto(a.ejecutar(CONV, "ok").respuesta)


class TestNoSePideLaPlataQueAcabaDeLlegar:
    """Prueba de punta a punta del 20/09, con el bot real. Último turno:

        clienta: listo ya transferí los 60
        bot:     ¡Recibido! 🙌 Ya tomé tu pedido Laura…
        bot:     *A esta cuenta puedes transferir los $60.000 del abono* …
                 ✨ Bancolombia … ✨ Nequi … ✨ Daviplata …

    El último mensaje que ve una clienta que acaba de pagar le pide que pague.
    Parece que su transferencia no llegó a ninguna parte.

    La guardia existía, pero miraba `abono_reportado`, que solo se pone al
    ejecutar RECIBIR_COMPROBANTE —más abajo—. Con las dos acciones en el mismo
    turno, que es justo lo que hace el modelo con un «ya transferí», las
    cuentas se colaban.
    """

    def _lista(self, mundo):
        a = _asesora(mundo, *[_jugada("") for _ in range(3)])
        ctx = mundo.contexto(CONV)
        b = Borrador(
            cantidad=1,
            talla=7,
            huellitas=[HuellitaDelBorrador(corazon=C.NEGRO, dedos=C.NEGRO)],
            sin_grabado=True,
            nombre_clienta="Laura Gómez",
        )
        mundo.guardar_contexto(
            ctx.model_copy(update={"borrador": b.model_dump(mode="json")})
        )
        return a

    def test_con_el_comprobante_en_el_mismo_turno_no_salen_las_cuentas(self, mundo):
        self._lista(mundo)  # el anillo ya está escogido y tiene su nombre
        a = _asesora(
            mundo,
            _jugada(
                "¡Recibido! 🙌",
                AccionAsesora.RECIBIR_COMPROBANTE,
                AccionAsesora.PEDIR_ABONO,
                AccionAsesora.MANDAR_CUENTAS,
            ),
        )
        texto = _texto(a.ejecutar(CONV, "listo ya transferí los 60").respuesta)
        assert "Recibido" in texto
        assert "puedes transferir" not in texto, "le pidió la plata que acaba de mandar"
        assert "3001110003" not in texto, "le pidió la plata que acaba de mandar"

    def test_si_pregunta_donde_paga_las_cuentas_sí_salen(self, mundo):
        """Lo de siempre no se rompe."""
        a = self._lista(mundo)
        a.ejecutar(CONV, "hola")
        guion = _asesora(
            mundo,
            _jugada("¡Claro! Te dejo los datos 💓", AccionAsesora.MANDAR_CUENTAS),
        )
        assert "3001110003" in _texto(guion.ejecutar(CONV, "¿a dónde pago?").respuesta)


class TestNoSeDaPorRecibidoUnPagoQueNadieVerifico:
    """Prueba de punta a punta del 20/09. Con el pedido en EN_REVISION_PAGO
    —es decir, ella dijo que transfirió y Lía todavía no ha mirado el banco—
    el bot contestó:

        > Ya recibí tu transferencia Laura 🙌 El anillo está en el taller y
        > cuando esté listo te mando las fotos…

    Las dos cosas son falsas. Un pago lo confirma una persona (ADR 0011) y el
    taller empieza cuando Lía lo verifica: decirle que ya está allí le arranca
    una cuenta de 10-15 días que no ha empezado.

    Había guardias para las dos, y las dos se colaban: la del pago no conocía
    la palabra «transferencia», y la del taller solo miraba cuando NO había
    pedido o cuando ya estaba terminado.
    """

    def _vigilar(self, frase, estado):
        from app.domain.asesora import vigilar

        b = Borrador(cantidad=1, talla=7, nombre_clienta="Laura", abono_reportado=True)
        return vigilar(frase, {60_000, 200_000}, b, estado)

    def test_ya_recibi_tu_transferencia_no_pasa(self):
        _, problemas = self._vigilar(
            "Ya recibí tu transferencia Laura 🙌", "EN_REVISION_PAGO"
        )
        assert any("pago confirmado" in p for p in problemas), problemas

    def test_tampoco_una_consignacion_ni_un_giro(self):
        for palabra in ("consignación", "giro"):
            _, problemas = self._vigilar(
                f"Ya recibimos tu {palabra} 🙌", "EN_REVISION_PAGO"
            )
            assert any("pago confirmado" in p for p in problemas), (palabra, problemas)

    def test_el_anillo_no_esta_en_el_taller_hasta_que_lia_verifique(self):
        _, problemas = self._vigilar("El anillo está en el taller 🫶", "EN_REVISION_PAGO")
        assert any("taller" in p for p in problemas), problemas

    def test_con_el_anillo_fabricandose_sí_se_puede_decir(self):
        """Lo de siempre no se rompe."""
        _, problemas = self._vigilar("El anillo está en el taller 🫶", "EN_PRODUCCION")
        assert not any("taller" in p for p in problemas), problemas


class TestCuandoDiceQueYaNoLeGusta:
    """Conversación REAL del 20/09 (23:44-23:46):

        >> Fucia
           ¡Fucsia para las dos! 🩷 Qué linda combinación 💕  [la foto]
        >> No ya no me  gusto
           ¡Claro! ¿Cuál color te gusta más? Te vuelvo a compartir los colores
        >> Recuerda
           Claro 🌈 Ahí van los 14 colores 💍
           ¿Quieres grabarle el nombre de tu peludito? 🖊️

    Y en el borrador, después de todo eso: `[FUCSIA/FUCSIA, FUCSIA/FUCSIA]`.
    Nunca escogió otro color y la conversación siguió al grabado: ese anillo se
    habría fabricado del color que ella rechazó.

    No había forma de DESESCOGER —un `None` significa «esto no cambia»— así que
    el modelo entendió lo que quería decir y no tuvo con qué decirlo.
    """

    def test_se_le_borran_los_colores_y_vuelven_a_faltar(self, mundo):
        from app.domain.asesora import sin_colores

        b = Borrador(
            cantidad=2,
            talla=6.5,
            huellitas=[
                HuellitaDelBorrador(corazon=C.FUCSIA, dedos=C.FUCSIA),
                HuellitaDelBorrador(corazon=C.FUCSIA, dedos=C.FUCSIA),
            ],
        )
        assert "colores" not in b.falta_del_anillo()
        sin_colores(b)
        assert "colores" in b.falta_del_anillo(), (
            "siguió con el color que acababa de rechazar"
        )
        assert all(h.corazon is None for h in b.huellitas)

    def test_si_dice_el_color_nuevo_ese_es_el_que_queda(self, mundo):
        """Quitar y poner en el mismo mensaje: manda el que acaba de escoger."""
        a = _asesora(
            mundo,
            _jugada(
                "¡Negra entonces! 🖤",
                AccionAsesora.QUITAR_COLORES,
                cantidad_huellitas=1,
                huellitas=[HuellitaPropuesta(numero=1, corazon=C.NEGRO, dedos=C.NEGRO)],
            ),
        )
        a.ejecutar(CONV, "de 1 huellita, no ya no me gusta el fucsia, mejor negra")
        b = Borrador(**mundo.contexto(CONV).borrador)
        assert b.huellitas[0].corazon is C.NEGRO


class TestUnaPreguntaPorMensaje:
    """Misma conversación real, 23:46:42. A una clienta que acababa de dar el
    nombre de su perrito le llegó:

        ¡Qué nombre tan lindo! 🐾 ¿Cooper es uno solo, o tienes dos peluditos…?
        ¿Lo dejo a nombre de Jose Pérez? 🥰

    Dos preguntas seguidas sobre cosas distintas. No volvió a escribir. Lo del
    nombre del pedido puede esperar un turno; lo que se está hablando, no.
    """

    def _lista(self, mundo, **extra):
        a = _asesora(mundo, *[_jugada("") for _ in range(3)])
        ctx = mundo.contexto(CONV)
        b = Borrador(
            cantidad=1,
            talla=7,
            huellitas=[HuellitaDelBorrador(corazon=C.NEGRO, dedos=C.NEGRO)],
            sin_grabado=True,
            **extra,
        )
        mundo.guardar_contexto(
            ctx.model_copy(update={"borrador": b.model_dump(mode="json")})
        )
        return a

    def test_si_el_mensaje_ya_pregunta_algo_el_nombre_espera(self, mundo):
        self._lista(mundo)
        a = _asesora(mundo, _jugada("¿Cooper es uno solo o tienes dos? 🐾"))
        texto = _texto(a.ejecutar(CONV, "Cooper", None, "Jose Pérez").respuesta)
        assert "Cooper" in texto
        assert "¿Lo dejo a nombre" not in texto, "le hizo dos preguntas a la vez"

    def test_sin_otra_pregunta_sí_se_le_propone(self, mundo):
        self._lista(mundo)
        a = _asesora(mundo, _jugada("¡Listo, anillo liso! 🖤"))
        texto = _texto(a.ejecutar(CONV, "sin grabado", None, "Jose Pérez").respuesta)
        assert "¿Lo dejo a nombre de Jose Pérez?" in texto


class TestMirarAtrasSeHaceConLupa:
    """Ayer hice que la cantidad valiera si la había escrito en un mensaje
    ANTERIOR —el caso real era abrir con «quiero el de 3 huellitas», que va a
    la apertura fija—. Pero reutilicé el detector suelto, y ese reconoce la
    palabra «una»:

        escribe_una_cantidad("una foto de un anillo") -> True

    En el repaso del 20/09, la descripción de la foto de la regla («una foto en
    la que dice…») validó una cantidad de 2 que la clienta nunca pidió: iba a
    comprar un anillo de UNA huellita con dos nombres grabados y el resumen le
    mostró dos huellitas.
    """

    def test_lo_que_abrio_diciendo_sigue_valiendo(self):
        from app.domain.asesora import cantidad_respaldada

        assert cantidad_respaldada(
            3, "talla 8", "¿Sabes tu talla?", ["hola, quiero el de 3 huellitas"]
        )

    def test_una_foto_no_es_una_huellita(self):
        from app.domain.asesora import cantidad_respaldada

        assert not cantidad_respaldada(
            2,
            "Nombres: Sakura y Muñeco",
            "¿Cómo se llaman?",
            ["[una foto de un anillo sobre una regla: 16.5 mm, talla 6]", "Listo"],
        )

    def test_el_numero_de_antes_tiene_que_ser_EL_que_se_propone(self):
        """«El de 3 huellitas» respalda un 3, no un 2."""
        from app.domain.asesora import cantidad_respaldada

        assert not cantidad_respaldada(
            2, "sí", "¿Así está bien?", ["quiero el de 3 huellitas"]
        )

    def test_las_formas_de_decirlo(self):
        from app.domain.asesora import cuantas_huellitas_escribio as cuantas

        assert cuantas("quiero 2 huellitas") == 2
        assert cuantas("de una huellita") == 1
        assert cuantas("el de dos") == 2
        assert cuantas("Nombres: Sakura y Muñeco") is None
        assert cuantas("una foto de un anillo") is None


class TestQuedoAtentaNoSaleDosVeces:
    """Repasos del 21/09 (también con el código final de ese día), siempre
    tarde en la conversación, tras varios «ok» mientras ella va a pagar:

        > ¡Dale! Quedo atenta a tu comprobante 🙌
        > Quedo atenta a tu comprobante 💓 ¿Te puedo ayudar con algo más?
        - no pasó: no preguntaba nada: se le puso la pregunta que faltaba

    Si el mensaje ya decía «quedo atenta», se probaba con las preguntas suaves;
    pero con las tres dichas hace poco, se volvía POR DEFECTO a la frase
    entera. Tres vueltas de «ok» bastan para gastarlas.
    """

    def _esperando_su_pago(self, mundo, dichos: list[str], mensaje: str):
        a = _asesora(mundo, _jugada(mensaje))
        ctx = mundo.contexto(CONV)
        b = Borrador(
            cantidad=1,
            talla=7,
            huellitas=[HuellitaDelBorrador(corazon=C.NEGRO, dedos=C.NEGRO)],
            sin_grabado=True,
            nombre_clienta="Laura Gómez",
            cuentas_enviadas=True,
        )
        mundo.guardar_contexto(
            ctx.model_copy(
                update={
                    "borrador": b.model_dump(mode="json"),
                    "charla": [{"de": "lia", "texto": d} for d in dichos],
                }
            )
        )
        return a

    def test_mientras_va_a_pagar_no_se_le_pregunta_nada(self, mundo):
        """Mónica (07/10): con las cuentas en la mano, a cada «gracias» le
        llegaba otra pregunta («¿Te ayudo con algo más mientras tanto?»,
        «¿Tienes alguna otra duda?»…). Camilo: solo agradecer."""
        a = self._esperando_su_pago(
            mundo, ["Quedo atenta a tu comprobante 💓"], "¡Con gusto, Mónica! 🥰"
        )
        texto = _texto(a.ejecutar(CONV, "Tan bella muchas gracias").respuesta)
        assert "?" not in texto, texto
        assert texto.lower().count("quedo atenta") == 0, texto

    def test_si_pospone_solo_se_agradece(self, mundo):
        a = self._esperando_su_pago(
            mundo,
            ["Quedo atenta a tu comprobante 💓"],
            "¡Dale, Mónica! Quedo atenta a tu comprobante mañana 🫶 ¿Tienes alguna "
            "otra duda? 🥰",
        )
        texto = _texto(
            a.ejecutar(CONV, "Yo el día de mañana le estaré consignando").respuesta
        )
        assert "?" not in texto, texto
        assert "mañana" in texto


class TestPagoConElPedidoAMediasYSinNombre:
    """Repaso del 21/09 (corrida final). Mandó el comprobante sin haber dado
    nunca su nombre, y el modelo le preguntó «¿A nombre de quién va?» en cada
    mensaje. El pago quedó anotado (`pagado_sin_pedido`, alerta
    `datos-incompletos`), pero a Lía no le llegó el nombre que SÍ teníamos de
    WhatsApp: la rama de «ya pagó» de `_lo_del_nombre` miraba solo
    `abono_reportado`, que con el pedido sin nacer nunca se enciende.
    """

    def _pago_sin_nombre(self, mundo, *jugadas):
        a = _asesora(mundo, *jugadas)
        ctx = mundo.contexto(CONV)
        b = Borrador(
            cantidad=1,
            talla=7,
            huellitas=[HuellitaDelBorrador(corazon=C.NEGRO, dedos=C.NEGRO)],
            sin_grabado=True,
            cuentas_enviadas=True,
            pagado_sin_pedido=True,
        )
        mundo.guardar_contexto(
            ctx.model_copy(update={"borrador": b.model_dump(mode="json")})
        )
        return a

    def test_a_lia_le_llega_el_nombre_de_whatsapp(self, mundo):
        a = self._pago_sin_nombre(mundo, _jugada("¿A nombre de quién va? 🥰"))
        t = a.ejecutar(CONV, "Pd, el envío lo pago con el saldo", None, "Daniela Ospina")
        assert t.respuesta.escalar, "con la plata adentro, lo cierra Lía"
        assert any("Daniela Ospina" in n for n in t.contexto.revisar), t.contexto.revisar

    def test_despues_del_aviso_no_se_le_pegan_dos_preguntas(self, mundo):
        a = self._pago_sin_nombre(
            mundo,
            _jugada("¿A nombre de quién va? 🥰"),
            _jugada("¡Con gusto! 💓 ¿Te ayudo con algo más?"),
        )
        a.ejecutar(CONV, "Pd, el envío lo pago con el saldo", None, "Daniela Ospina")
        segundo = a.ejecutar(CONV, "Gracias", None, "Daniela Ospina")
        assert not segundo.respuesta.escalar, "le llenó la bandeja del mismo aviso"
        assert "¿Lo dejo a nombre" not in _texto(segundo.respuesta), "dos preguntas"

    def test_en_el_mismo_turno_del_pago_no_se_avisa_a_lia(self, mundo):
        """Repasos del 21/09 (sint-01, sint-07): manda el comprobante y en el
        mensaje siguiente da su nombre. Avisando a Lía en el turno del pago, le
        llegaba un `necesita-persona` por algo que se resolvía solo."""
        a = _asesora(
            mundo,
            _jugada(
                "¡Recibido! 🙌 ¿A nombre de quién va? 🥰",
                AccionAsesora.RECIBIR_COMPROBANTE,
            ),
        )
        ctx = mundo.contexto(CONV)
        b = Borrador(
            cantidad=1,
            talla=7,
            huellitas=[HuellitaDelBorrador(corazon=C.NEGRO, dedos=C.NEGRO)],
            sin_grabado=True,
            cuentas_enviadas=True,
        )
        mundo.guardar_contexto(
            ctx.model_copy(update={"borrador": b.model_dump(mode="json")})
        )
        foto = [
            {"kind": "image", "descripcion": "Comprobante de transferencia por $60.000"}
        ]
        t = a.ejecutar(CONV, "", foto, "Daniela Ospina")
        assert mundo.contexto(CONV).borrador["pagado_sin_pedido"], "el pago se perdió"
        assert not t.respuesta.escalar, "avisó a Lía antes de darle la oportunidad"
