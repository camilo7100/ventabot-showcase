"""La conversación real que se rompió, convertida en pruebas.

════════════════════════════════════════════════════════════════════════════
DE DÓNDE SALE ESTE ARCHIVO
════════════════════════════════════════════════════════════════════════════
De hablar con el bot. Ni un solo fallo de los de aquí lo cazó un test ni la
medición del golden dataset: los dos miran un mensaje aislado, y todos estos
fallos son de CONVERSACIÓN — de lo que pasa entre un mensaje y el siguiente.

  · «dame uno de una huella y otro de 2»  -> se perdía el segundo anillo
  · «morado y talla 5»                    -> se guardaba la talla, el color no
  · «morado» (x2), «dedos morados»        -> el MISMO párrafo cuatro veces
  · «carmen» (contestando el grabado)     -> se leía como «quiero un humano»
  · «ya pagué»                            -> «no tienes ningún pedido»
  · «bancolombia»                         -> repetía la lista de medios entera

════════════════════════════════════════════════════════════════════════════
POR QUÉ EL MODELO AQUÍ ES UN TROZO DE MADERA
════════════════════════════════════════════════════════════════════════════
El LLM falso devuelve siempre OTRO: no entiende nada, nunca. Si estos tests
pasan, es porque la inteligencia está en Python —en la expectativa, en los
parsers, en la tabla— y no en el modelo.

Ese es justo el punto: lo que faltaba no era un modelo más listo, era que la
pregunta pendiente entrara en la interpretación.
"""

from __future__ import annotations

import pytest

from app.adapters.repositories.memory import (
    InMemoryCustomerRepository,
    InMemoryOrderRepository,
    InMemoryProductRepository,
)
from app.conversacion.ejecutor import Ejecutor
from app.conversacion.interprete import Interprete
from app.conversacion.mundo import Mundo
from app.conversacion.pipeline import Pipeline
from app.conversacion.redactor import Redactor
from app.domain.acciones import Accion
from app.domain.contexto import ContextoConversacional, TipoProceso
from app.domain.interpretacion import Acto, Atributo, Entidad, Interpretacion
from app.domain.models import Channel, Customer, Product
from app.domain.order_state import OrderState
from app.domain.personalizacion import ColorCircon

CONV = "wa:573001112233"


class ContextoEnMemoria:
    def __init__(self):
        self._d: dict[str, ContextoConversacional] = {}

    def cargar(self, conv_id):
        return self._d.get(conv_id) or ContextoConversacional(conversation_id=conv_id)

    def guardar(self, ctx):
        self._d[ctx.conversation_id] = ctx


class ModeloDeMadera:
    """Un modelo malo de verdad: acierta el VERBO y nada más.

    Ni colores, ni tallas, ni nombres, ni referencias, ni atributos. Es el
    techo de lo que se le puede pedir a un modelo de 3B, y es exactamente el
    reparto que persigue todo el diseño: el modelo dice de qué va la frase y
    Python saca los datos.

    Si estos tests pasan con esto, pasan con cualquier modelo mejor.
    """

    QUE_OYE: tuple[tuple[str, Acto, Entidad], ...] = (
        ("anillo", Acto.COMPRAR, Entidad.PRODUCTO),
        ("dame", Acto.COMPRAR, Entidad.PRODUCTO),
        ("quiero", Acto.COMPRAR, Entidad.PRODUCTO),
        ("pagar", Acto.PREGUNTAR, Entidad.PAGO),
        ("pago", Acto.PREGUNTAR, Entidad.PAGO),
    )

    def extract(self, prompt, texto, esquema):
        bajo = (texto or "").lower()
        for pista, acto, entidad in self.QUE_OYE:
            if pista in bajo:
                atributo = (
                    Atributo.MEDIOS_DE_PAGO
                    if entidad is Entidad.PAGO
                    else Atributo.NINGUNO
                )
                return Interpretacion(
                    acto=acto, entidad=entidad, atributo=atributo, confianza="MEDIA"
                )
        return Interpretacion(acto=Acto.OTRO, confianza="BAJA")


def _productos() -> InMemoryProductRepository:
    return InMemoryProductRepository(
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


@pytest.fixture
def mundo():
    customers = InMemoryCustomerRepository()
    customers.upsert(
        Customer(
            id="c1",
            channel=Channel.WHATSAPP,
            channel_user_id="573001112233",
            nombre="Ángela",
        )
    )
    return Mundo(InMemoryOrderRepository(), customers, _productos(), ContextoEnMemoria())


@pytest.fixture
def bot(mundo):
    interprete = Interprete(ModeloDeMadera(), prompt="", catalogo_txt="")
    return Pipeline(interprete, mundo, Ejecutor(mundo), Redactor())


def hablar(bot, *mensajes) -> list[str]:
    """Manda los mensajes en orden y devuelve lo que contestó a cada uno."""
    return [bot.ejecutar(CONV, m).respuesta.texto_plano for m in mensajes]


def envio(bot):
    """Los datos de envío: lo último que se pregunta, antes del precio."""
    hablar(bot, "Carlos Pérez", "Bucaramanga", "Calle 45 #12-30 apto 301")


def proceso(mundo, tipo=TipoProceso.COMPRA):
    abiertos = mundo.contexto(CONV).abiertos(tipo)
    return abiertos[0] if abiertos else None


# ═══════════════════════════════════════════════════════════════════════════
# 1. MEDIA RESPUESTA ES MEDIA RESPUESTA, NO RUIDO
# ═══════════════════════════════════════════════════════════════════════════


class TestColoresAMedias:
    def test_un_color_suelto_se_guarda_y_afina_la_pregunta(self, bot, mundo):
        hablar(bot, "quiero un anillo de 2 huellitas")
        respuesta = hablar(bot, "morado")[0]

        assert proceso(mundo).datos["color_suelto"] == ColorCircon.MORADO.value
        assert "morado" in respuesta.lower()
        # No vuelve a soltar la pregunta larga de siempre.
        assert "corazón" in respuesta and "deditos" in respuesta

    def test_la_parte_llega_despues_y_cierra_la_pareja(self, bot, mundo):
        hablar(bot, "quiero un anillo de 1 huellita", "morado")
        hablar(bot, "para el corazón")
        # Sigue faltando el color de los deditos, pero el morado YA está puesto.
        p = proceso(mundo)
        assert p.datos["media_pareja"] == {"corazon": ColorCircon.MORADO.value}

    def test_media_pareja_pregunta_solo_lo_que_falta(self, bot, mundo):
        hablar(bot, "quiero un anillo de 1 huellita")
        respuesta = hablar(bot, "dedos morados")[0]

        assert proceso(mundo).datos["media_pareja"] == {"dedos": ColorCircon.MORADO.value}
        assert "corazón" in respuesta.lower()

    def test_color_y_talla_en_la_misma_frase_no_se_pierde_ninguno(self, bot, mundo):
        hablar(bot, "quiero un anillo de 1 huellita")
        hablar(bot, "morado y talla 5")

        p = proceso(mundo)
        assert p.datos["talla"] == 5.0
        assert p.datos["color_suelto"] == ColorCircon.MORADO.value

    def test_la_pareja_completa_sigue_funcionando(self, bot, mundo):
        hablar(bot, "quiero un anillo de 1 huellita")
        hablar(bot, "corazón lila y dedos morados")

        assert proceso(mundo).datos["colores"] == [{"corazon": "LILA", "dedos": "MORADO"}]


# ═══════════════════════════════════════════════════════════════════════════
# 2. NUNCA EL MISMO MENSAJE DOS VECES
# ═══════════════════════════════════════════════════════════════════════════


class TestNoRepetirse:
    def test_tres_intentos_tres_mensajes_distintos(self, bot):
        hablar(bot, "quiero un anillo de 1 huellita")
        # Tres mensajes que no aportan nada: el bot tiene que insistir SIN
        # copiarse a sí mismo.
        dichos = hablar(bot, "mmm", "ehh", "no sé")
        assert len(set(dichos)) == 3, "repitió un mensaje palabra por palabra"

    def test_a_la_tercera_ofrece_una_persona(self, bot):
        hablar(bot, "quiero un anillo de 1 huellita")
        hablar(bot, "mmm", "ehh")
        turno = bot.ejecutar(CONV, "no sé")
        assert turno.respuesta.escalar is True

    def test_una_respuesta_util_reinicia_la_cuenta(self, bot, mundo):
        hablar(bot, "quiero un anillo de 1 huellita", "mmm")
        hablar(bot, "corazón lila y dedos morados")
        assert mundo.contexto(CONV).veces == 0


# ═══════════════════════════════════════════════════════════════════════════
# 3. LO QUE YO PREGUNTÉ CAMBIA LO QUE SIGNIFICA LA RESPUESTA
# ═══════════════════════════════════════════════════════════════════════════


class TestExpectativa:
    def test_una_palabra_suelta_es_el_nombre_a_grabar(self, bot, mundo):
        hablar(
            bot,
            "quiero un anillo de 1 huellita",
            "corazón lila y dedos morados",
        )
        turno = bot.ejecutar(CONV, "carmen")

        assert turno.decision.accion is not Accion.LLAMAR_HUMANO
        assert proceso(mundo).datos["grabados"] == ["carmen"]

    def test_dos_nombres_separados_por_y(self, bot, mundo):
        hablar(bot, "quiero un anillo de 1 huellita", "corazón lila y dedos morados")
        hablar(bot, "Luna y Simba")
        assert proceso(mundo).datos["grabados"] == ["Luna", "Simba"]

    def test_una_pregunta_NO_es_un_nombre_de_mascota(self, bot, mundo):
        hablar(bot, "quiero un anillo de 1 huellita", "corazón lila y dedos morados")
        hablar(bot, "cuanto cuesta")
        assert not proceso(mundo).datos.get("grabados")

    def test_sin_grabado_sigue_valiendo(self, bot, mundo):
        hablar(bot, "quiero un anillo de 1 huellita", "corazón lila y dedos morados")
        hablar(bot, "sin grabado")
        assert proceso(mundo).datos["sin_grabado"] is True

    def test_una_queja_manda_a_una_persona_aunque_espere_un_nombre(self, bot):
        hablar(bot, "quiero un anillo de 1 huellita", "corazón lila y dedos morados")
        turno = bot.ejecutar(CONV, "me llegó partido el anillo")
        assert turno.decision.accion is Accion.LLAMAR_HUMANO


# ═══════════════════════════════════════════════════════════════════════════
# 4. LA COMPRA TERMINADA SE CONVIERTE EN UN PEDIDO DE VERDAD
# ═══════════════════════════════════════════════════════════════════════════


def _compra_completa(bot):
    """Hasta que no queda NADA por preguntar. Solo entonces hay pedido.

    Los datos de envío van dentro a propósito: pedir el abono antes de saber
    a dónde mandar el anillo se siente como que están cobrando, no
    atendiendo.
    """
    hablar(
        bot,
        "quiero un anillo de 1 huellita",
        "corazón lila y dedos morados",
        "carmen",
        "talla 8",
        "Carlos Pérez",
        "Bucaramanga",
        "Calle 45 #12-30 apto 301",
    )


class TestElCircuitoSeCierra:
    def test_al_terminar_existe_un_pedido(self, bot, mundo):
        _compra_completa(bot)
        pedidos = mundo.pedidos_de(CONV)
        assert len(pedidos) == 1
        assert pedidos[0].estado == OrderState.ESPERANDO_ANTICIPO.value
        assert pedidos[0].total_cop > 0

    def test_el_pedido_lleva_lo_que_ella_eligio(self, bot, mundo):
        _compra_completa(bot)
        p = mundo.pedidos_de(CONV)[0].items[0].personalizacion
        assert p.talla == 8
        assert p.grabados == ["carmen"]
        assert p.huellitas[0].corazon is ColorCircon.LILA

    def test_ya_pague_encuentra_su_pedido(self, bot, mundo):
        _compra_completa(bot)
        turno = bot.ejecutar(CONV, "ya pagué")

        assert turno.decision.accion is Accion.REGISTRAR_PAGO_REPORTADO
        assert turno.decision.objetivo_id == mundo.pedidos_de(CONV)[0].id
        assert "comprobante" in turno.respuesta.texto_plano.lower()

    def test_el_pago_reportado_va_a_revision_NUNCA_a_pagado(self, bot, mundo):
        """Lía tiene que enterarse, y aun así nada queda confirmado."""
        _compra_completa(bot)
        bot.ejecutar(CONV, "ya pagué")
        pedido = mundo.pedidos_de(CONV)[0]
        assert pedido.estado == OrderState.EN_REVISION_PAGO.value
        assert pedido.anticipo_pagado_cop == 0

    def test_no_se_crea_el_pedido_dos_veces(self, bot, mundo):
        _compra_completa(bot)
        hablar(bot, "talla 9")  # corrige la talla
        assert len(mundo.pedidos_de(CONV)) == 1
        assert mundo.pedidos_de(CONV)[0].items[0].personalizacion.talla == 9

    def test_sin_pedido_ni_compra_se_dice_la_verdad(self, bot):
        turno = bot.ejecutar(CONV, "ya pagué")
        texto = turno.respuesta.texto_plano.lower()
        assert "no te entendí" not in texto
        assert "huellitas" in texto  # ofrece el paso siguiente


# ═══════════════════════════════════════════════════════════════════════════
# 5. DOS ANILLOS EN UNA SOLA FRASE
# ═══════════════════════════════════════════════════════════════════════════


class TestDosAnillos:
    def test_el_segundo_anillo_no_se_pierde(self, bot, mundo):
        hablar(bot, "dame uno de una huella y otro de 2 huellas")
        p = proceso(mundo)
        assert p.datos["huellitas"] == 1
        assert p.datos["cola"] == [2]

    def test_al_cerrar_el_primero_se_abre_el_segundo(self, bot, mundo):
        hablar(
            bot,
            "dame uno de una huella y otro de 2 huellas",
            "corazón lila y dedos morados",
            "carmen",
            "talla 8",
        )
        envio(bot)
        abiertas = mundo.contexto(CONV).abiertos(TipoProceso.COMPRA)
        assert len(abiertas) == 2
        assert abiertas[0].datos["huellitas"] == 2

    def test_con_el_mismo_reloj_manda_el_ultimo_guardado(self):
        """En un equipo rápido los dos procesos salen con el MISMO `tocado`.

        Pasó en el portátil nuevo: este archivo fallaba 1 de cada 6 corridas
        porque el empate dejaba primero al anillo ya cerrado.
        """
        from datetime import UTC, datetime

        from app.domain.contexto import Proceso

        mismo = datetime(2026, 9, 17, 5, 6, 17, tzinfo=UTC)
        primero = Proceso(tipo=TipoProceso.COMPRA, datos={"huellitas": 1}, tocado=mismo)
        segundo = Proceso(tipo=TipoProceso.COMPRA, datos={"huellitas": 2}, tocado=mismo)
        ctx = (
            ContextoConversacional(conversation_id=CONV)
            .guardar_proceso(primero)
            .guardar_proceso(segundo)
        )
        abiertas = ctx.abiertos(TipoProceso.COMPRA, ahora=mismo)
        assert [p.datos["huellitas"] for p in abiertas] == [2, 1]

    def test_se_le_dice_que_el_otro_va_despues(self, bot):
        hablar(
            bot,
            "dame uno de una huella y otro de 2 huellas",
            "corazón lila y dedos morados",
            "carmen",
            "talla 8",
        )
        assert "2 huellitas" in hablar(bot, "Carlos Pérez")[0]


# ═══════════════════════════════════════════════════════════════════════════
# 6. NOMBRAR UN MEDIO DE PAGO NO ES VOLVER A PREGUNTAR POR LOS MEDIOS
# ═══════════════════════════════════════════════════════════════════════════


class TestMedioDePagoConcreto:
    def test_bancolombia_no_devuelve_la_lista_entera(self, bot):
        hablar(bot, "cómo puedo pagar")
        respuesta = hablar(bot, "bancolombia")[0]
        assert "Nequi" not in respuesta
        assert "Davivienda" not in respuesta

    def test_mientras_no_haya_cuenta_se_dice_la_verdad(self, bot):
        respuesta = hablar(bot, "bancolombia")[0]
        assert "[POR DEFINIR]" not in respuesta
        assert "Bancolombia" in respuesta

    def test_la_lista_completa_sigue_saliendo_si_no_nombra_ninguno(self, bot):
        respuesta = hablar(bot, "cómo puedo pagar")[0]
        assert "Nequi" in respuesta and "Bancolombia" in respuesta


# ═══════════════════════════════════════════════════════════════════════════
# 7. UN «SÍ» VALE LO QUE VALÍA LA PREGUNTA
# ═══════════════════════════════════════════════════════════════════════════


class TestElSiTieneContexto:
    def test_siii_al_saludo_muestra_el_producto(self, bot):
        hablar(bot, "hola")
        respuesta = hablar(bot, "siii")[0]
        assert "Precios" in respuesta

    def test_siii_al_catalogo_empieza_la_compra(self, bot):
        hablar(bot, "hola", "siii")
        respuesta = hablar(bot, "siii")[0]
        assert "huellitas" in respuesta.lower()

    def test_siii_al_cobro_da_los_medios_de_pago(self, bot):
        _compra_completa(bot)
        respuesta = hablar(bot, "siii")[0]
        assert "Bancolombia" in respuesta

    def test_las_letras_de_mas_no_estorban(self, bot):
        from app.conversacion.interprete import normalizar

        assert normalizar("Siiiii") == "si"
        assert normalizar("holaaaa") == "hola"
        assert normalizar("perfectooo") == "perfecto"
        # Las dobles de verdad se quedan como están.
        assert normalizar("carro") == "carro"
        assert normalizar("llave") == "llave"
        assert normalizar("acción") == "accion"

    def test_un_si_sin_pregunta_detras_no_inventa_una_compra(self, bot, mundo):
        hablar(bot, "siii")
        assert not mundo.pedidos_de(CONV)


# ═══════════════════════════════════════════════════════════════════════════
# 8. RESPUESTAS CORTAS: «1» ES UNA HUELLITA
# ═══════════════════════════════════════════════════════════════════════════


class TestRespuestasCortas:
    def test_un_numero_solo_contesta_cuantas_huellitas(self, bot, mundo):
        hablar(bot, "quiero un anillo")
        hablar(bot, "1")
        assert proceso(mundo).datos["huellitas"] == 1

    def test_tambien_escrito_con_letra(self, bot, mundo):
        hablar(bot, "quiero un anillo")
        hablar(bot, "dos")
        assert proceso(mundo).datos["huellitas"] == 2

    def test_un_numero_solo_contesta_la_talla_cuando_toca(self, bot, mundo):
        hablar(bot, "quiero un anillo de 1 huellita", "corazón lila y dedos morados")
        hablar(bot, "carmen")
        hablar(bot, "8")
        envio(bot)
        assert mundo.pedidos_de(CONV)[0].items[0].personalizacion.talla == 8

    def test_no_vuelve_a_preguntar_lo_que_ya_dijo(self, bot):
        dichos = hablar(bot, "quiero un anillo", "1", "corazón lila y dedos morados")
        # Ya sabe cuántas huellitas: no puede volver a preguntarlas.
        assert "¿Cuántas huellitas" not in dichos[-1]


# ═══════════════════════════════════════════════════════════════════════════
# 9. UN ANILLO DE UNA HUELLITA LLEVA UNA HUELLITA
# ═══════════════════════════════════════════════════════════════════════════


class TestCuantasHuellitasLleva:
    def test_el_segundo_par_en_un_anillo_de_una_es_una_correccion(self, bot, mundo):
        hablar(bot, "quiero un anillo de 1 huellita", "corazón lila y dedos morados")
        hablar(bot, "no mejor corazón rojo y dedos blancos")

        colores = proceso(mundo).datos["colores"]
        assert len(colores) == 1, "grabó dos patitas en el anillo de una"
        assert colores[0] == {"corazon": "ROJO", "dedos": "BLANCO"}

    def test_el_de_dos_acumula_las_dos(self, bot, mundo):
        hablar(bot, "quiero un anillo de 2 huellitas")
        hablar(bot, "corazón lila y dedos morados")
        hablar(bot, "corazón rojo y dedos blancos")
        assert len(proceso(mundo).datos["colores"]) == 2

    def test_el_de_dos_no_se_manda_a_fabricar_con_una_sola(self, bot, mundo):
        hablar(
            bot,
            "quiero un anillo de 2 huellitas",
            "corazón lila y dedos morados",
            "carmen",
            "talla 8",
        )
        assert not mundo.pedidos_de(CONV), "creó el pedido sin los dos pares"
        assert "colores" in proceso(mundo).faltan

    def test_con_los_dos_pares_si_nace_el_pedido(self, bot, mundo):
        hablar(
            bot,
            "quiero un anillo de 2 huellitas",
            "corazón lila y dedos morados",
            "corazón rojo y dedos blancos",
            "carmen",
            "talla 8",
        )
        envio(bot)
        pedidos = mundo.pedidos_de(CONV)
        assert len(pedidos) == 1
        assert len(pedidos[0].items[0].personalizacion.huellitas) == 2

    def test_si_los_colores_llegan_antes_que_la_cantidad_se_recortan(self, bot, mundo):
        hablar(bot, "corazón lila y dedos morados")
        hablar(bot, "corazón rojo y dedos blancos")
        hablar(bot, "que sea de 1 huellita")
        assert len(proceso(mundo).datos["colores"]) == 1


# ═══════════════════════════════════════════════════════════════════════════
# 10. QUE NO SUENE SIEMPRE IGUAL
# ═══════════════════════════════════════════════════════════════════════════


class TestQueNoSuenAIgual:
    def test_los_ecos_van_cambiando(self, bot):
        dichos = hablar(
            bot,
            "quiero un anillo de 3 huellitas",
            "corazón lila y dedos morados",
            "corazón rojo y dedos blancos",
            "corazón negro y dedos celestes",
        )
        arranques = [d.split("\n")[0] for d in dichos[1:]]
        assert len(set(arranques)) > 1, "empieza siempre con la misma frase"

    def test_la_variacion_es_reproducible(self, mundo):
        from app.conversacion.redactor import ECOS, variar

        class Ctx:
            turnos = 5

        assert variar(ECOS, Ctx()) == variar(ECOS, Ctx())


# ═══════════════════════════════════════════════════════════════════════════
# 11. EL MATERIAL DE VENTA
# ═══════════════════════════════════════════════════════════════════════════


class TestMaterialDeVenta:
    def test_el_catalogo_lleva_la_foto_los_videos_y_como_medir(self, bot):
        hablar(bot, "hola")
        turno = bot.ejecutar(CONV, "siii")  # «¿te cuento cómo funciona?»
        adjuntos = turno.respuesta.adjuntos()
        tipos = [t for t, _ in adjuntos]
        nombres = [n for _, n in adjuntos]

        assert tipos.count("VIDEO") == 2, "faltan los videos del producto"
        assert "anillo_ejemplo_1" in nombres
        assert any("medir_talla" in n for n in nombres), (
            "no le enseña cómo tomarse la medida, y esa foto es la que "
            "después tiene que leer el lector de imágenes"
        )

    def test_preguntar_los_colores_manda_el_muestrario(self, bot):
        turno = bot.ejecutar(CONV, "quiero un anillo de 1 huellita")
        assert "muestrario_circones" in turno.respuesta.imagenes()

    def test_preguntar_la_talla_manda_las_fotos_de_la_regla(self, bot):
        hablar(bot, "quiero un anillo de 1 huellita", "corazón lila y dedos morados")
        turno = bot.ejecutar(CONV, "carmen")
        assert any("medir_talla" in n for n in turno.respuesta.imagenes())

    def test_al_insistir_NO_se_reenvian_las_mismas_fotos(self, bot):
        primera = bot.ejecutar(CONV, "quiero un anillo de 1 huellita")
        segunda = bot.ejecutar(CONV, "mmm")
        assert primera.respuesta.imagenes(), "no mandó el muestrario la primera vez"
        assert not segunda.respuesta.imagenes(), "reenvió las mismas fotos al insistir"


# ═══════════════════════════════════════════════════════════════════════════
# 12. EL TRAMO DEL COBRO, QUE ES DONDE SE GANA O SE PIERDE
# ═══════════════════════════════════════════════════════════════════════════


class TestElTramoDelCobro:
    def test_que_mas_debo_hacer_contesta_el_abono_y_las_cuentas(self, bot):
        _compra_completa(bot)
        respuesta = hablar(bot, "Si el pedido está bien, ¿qué más debo hacer?")[0]

        assert "no te entendí" not in respuesta.lower()
        assert "$60.000" in respuesta
        assert "Bancolombia" in respuesta

    def test_confirmo_lleva_a_como_pagar_y_no_repite_el_resumen(self, bot):
        _compra_completa(bot)
        respuesta = hablar(bot, "Confirmo")[0]
        assert "Te confirmo tu anillo" not in respuesta
        assert "Bancolombia" in respuesta

    def test_donde_pago_trae_los_numeros_no_solo_los_nombres(self, bot):
        """Una lista de bancos sin cuentas obliga a preguntar otra vez."""
        _compra_completa(bot)
        respuesta = hablar(bot, "¿Dónde pago?")[0]
        assert "12345678901" in respuesta

    def test_el_resumen_no_arrastra_el_eco_del_mensaje_anterior(self, bot):
        _compra_completa(bot)
        respuesta = hablar(bot, "listo")[0]
        assert "Anoté" not in respuesta and "Ya tengo" not in respuesta


# ═══════════════════════════════════════════════════════════════════════════
# 13. VARIAS HUELLITAS EN UN MISMO MENSAJE
# ═══════════════════════════════════════════════════════════════════════════


class TestVariasHuellitasDeUnaVez:
    def test_dos_parejas_en_una_frase(self, bot, mundo):
        hablar(bot, "quiero un anillo de 3 huellitas", "corazón rojo dedos lila")
        hablar(bot, "corazón lila dedos rojos y el tercero verde corazón azul dedos")

        assert proceso(mundo).datos["colores"] == [
            {"corazon": "ROJO", "dedos": "LILA"},
            {"corazon": "LILA", "dedos": "ROJO"},
            {"corazon": "VERDE_ESMERALDA", "dedos": "AZUL_REY"},
        ]

    def test_no_vuelve_a_preguntar_por_las_que_ya_dio(self, bot):
        hablar(bot, "quiero un anillo de 3 huellitas", "corazón rojo dedos lila")
        respuesta = hablar(
            bot, "corazón lila dedos rojos y el tercero verde corazón azul dedos"
        )[0]
        assert "huellita 3" not in respuesta
        assert "grabamos" in respuesta.lower()

    def test_el_eco_repite_las_dos_que_llegaron(self, bot):
        hablar(bot, "quiero un anillo de 3 huellitas", "corazón rojo dedos lila")
        respuesta = hablar(
            bot, "corazón lila dedos rojos y el tercero verde corazón azul dedos"
        )[0]
        assert "lila" in respuesta and "verde esmeralda" in respuesta

    def test_las_tres_de_golpe_tambien(self, bot, mundo):
        hablar(bot, "quiero un anillo de 3 huellitas")
        hablar(
            bot,
            "corazón rojo dedos lila, corazón lila dedos rojos "
            "y el tercero verde corazón azul dedos",
        )
        assert len(proceso(mundo).datos["colores"]) == 3


# ═══════════════════════════════════════════════════════════════════════════
# 14. LAS SIETE CONVERSACIONES REALES DE LIA
# ═══════════════════════════════════════════════════════════════════════════
#
# Salen de replicar, mensaje por mensaje, las conversaciones que Lía tuvo de
# verdad por WhatsApp. Cada test de aquí es un fallo que el bot cometía sobre
# un mensaje que una clienta escribió tal cual, y ninguno lo cazaba nada de lo
# que había: los tests de arriba usan frases que escribimos nosotros.


class TestElNumeroDeUnaPatitaNoEsLaCantidad:
    """«Son dos huellitas» … «Una huellita negra por mi panterita».

    El «una» del segundo mensaje se leía como la cantidad y pisaba el dos. El
    anillo pasaba de $250.000 a $200.000 y se fabricaba con una patita en vez
    de dos. Es el fallo más caro de todos los encontrados.
    """

    def test_describir_una_patita_no_baja_la_cantidad(self, bot, mundo):
        hablar(bot, "quiero un anillo", "son dos huellitas")
        assert proceso(mundo).datos["huellitas"] == 2

        hablar(bot, "una huellita negra por mi panterita")
        assert proceso(mundo).datos["huellitas"] == 2, "el «una» pisó el dos"

    def test_el_color_si_se_anota_en_el_corazon(self, bot, mundo):
        hablar(bot, "quiero un anillo", "son dos huellitas")
        hablar(bot, "una huellita negra por mi panterita")
        assert proceso(mundo).datos["media_pareja"] == {"corazon": "NEGRO"}

    def test_los_ordinales_de_cada_patita_no_abren_otro_anillo(self, bot, mundo):
        """«1 huella morado… 2 huella verde…» son las DOS patitas de un anillo.

        Se leían como dos anillos distintos y se abría un pedido fantasma de
        una huellita que la clienta nunca pidió.
        """
        hablar(
            bot,
            "Quiero el de dos huellitas. 1 huella color morado para el centro y "
            "los deditos rosado. 2 huella color verde oscuro en el centro y los "
            "deditos color verde claro",
        )
        p = proceso(mundo)
        assert p.datos["huellitas"] == 2
        assert not p.datos.get("cola"), "abrió un segundo anillo que nadie pidió"

    def test_pedir_dos_anillos_de_verdad_sigue_funcionando(self, bot, mundo):
        """La salvedad no puede cargarse el caso que sí es de dos anillos."""
        hablar(bot, "dame uno de una huella y otro de 2 huellas")
        assert proceso(mundo).datos["cola"] == [2]

    def test_bajar_la_cantidad_a_proposito_sigue_valiendo(self, bot, mundo):
        """Sin color detrás, el número SÍ es la cantidad: puede cambiarla."""
        hablar(bot, "quiero un anillo de 3 huellitas")
        hablar(bot, "mejor de 2 huellitas")
        assert proceso(mundo).datos["huellitas"] == 2


class TestUnColorSueltoCierraLaParejaAMedias:
    """«Anotado negro en el corazón, ¿y de qué color los deditos?» — «rosado».

    Ese «rosado» se aparcaba como un color sin dueño y el bot volvía a soltar
    la MISMA pregunta, palabra por palabra. En la conversación real pasó cuatro
    veces seguidas y acabó escalando a una persona por una respuesta que estaba
    perfectamente clara.
    """

    def test_el_color_suelto_va_a_la_parte_que_faltaba(self, bot, mundo):
        hablar(bot, "quiero un anillo de 1 huellita", "una huellita negra")
        assert proceso(mundo).datos["media_pareja"] == {"corazon": "NEGRO"}

        hablar(bot, "creo que lo voy a escoger rosado")
        p = proceso(mundo)
        assert p.datos["colores"] == [{"corazon": "NEGRO", "dedos": "ROSADO"}]
        assert "media_pareja" not in p.datos

    def test_ya_no_repite_la_misma_pregunta(self, bot):
        hablar(bot, "quiero un anillo de 1 huellita", "una huellita negra")
        respuesta = hablar(bot, "creo que lo voy a escoger rosado")[0]
        assert "¿Y de qué color quieres los *deditos*?" not in respuesta

    def test_sin_media_pareja_el_color_sigue_quedando_suelto(self, bot, mundo):
        """Sin nada puesto, un color a secas SÍ hay que preguntarlo: no hay
        forma de saber si va en el corazón o en los deditos."""
        hablar(bot, "quiero un anillo de 1 huellita", "morado")
        assert proceso(mundo).datos["color_suelto"] == "MORADO"


class TestLaMedidaEscritaEnCentimetros:
    """«1,80 cm» contestando a «mídelo por la mitad».

    El bot contestaba «no te entendí» al dato que más cuesta conseguir de toda
    la venta. La medida se lee, se convierte con la tabla de tallas y queda
    marcada para confirmarla con la foto — que es lo que hace Lía.
    """

    def test_la_medida_en_centimetros_se_convierte_en_talla(self, bot, mundo):
        """18 mm es 7¾ en la tabla de Lía (27/09): cae entre 7½ y 8, no «8»."""
        hablar(bot, "quiero un anillo de 1 huellita", "1,80 cm")
        assert proceso(mundo).datos["talla"] == 7.75

    def test_tambien_en_milimetros(self, bot, mundo):
        """17 mm da 6¾ y no 7: la 6¾ mide 17.08 y la 7 mide 17.3. Lo decide la
        tabla de `domain.tallas` (la de Lía, con cuartos), no un redondeo."""
        hablar(bot, "quiero un anillo de 1 huellita", "mide 17 mm")
        assert proceso(mundo).datos["talla"] == 6.75

    def test_queda_marcada_para_confirmarla_con_la_foto(self, bot, mundo):
        """Nadie funde plata con una medida que no revisó nadie. Y la nota NO
        puede decir «de la foto de la clienta»: no hubo ninguna foto."""
        hablar(bot, "quiero un anillo de 1 huellita", "1,80 cm")
        d = proceso(mundo).datos
        assert d["talla_revisar"] is True
        assert d["diametro_mm"] == 18.0
        assert "ESCRIBIÓ" in d["talla_motivo"]
        assert "foto de la clienta" not in d["talla_motivo"]

    def test_llega_antes_de_que_exista_la_compra(self, bot, mundo):
        """La medida casi siempre llega ANTES: pregunta el precio, le explican
        cómo medir, y la manda sin haber dicho cuántas huellitas quiere."""
        hablar(bot, "no se mi talla", "1,80 cm")
        assert proceso(mundo).datos["talla"] == 7.75

    def test_una_cifra_absurda_no_se_convierte_en_talla(self, bot, mundo):
        """80 cm no es un dedo: es un error de tecleo, e inventarle una talla
        es peor que no entenderla."""
        hablar(bot, "quiero un anillo de 1 huellita", "80 cm")
        assert proceso(mundo).datos.get("talla") is None


class TestLosNombresNoSePierdenConLosColores:
    """«Quiero el de dos huellitas, 1 huella morado…, 2 huella verde…,
    dentro grabado los nombres Lulu & Roberta».

    La rama que guarda varias parejas de colores terminaba con un `return`, y
    con él se iba todo lo que venía después: los nombres del grabado, la
    ciudad y los datos de envío. El mensaje entraba completo y los nombres
    desaparecían sin un aviso. Es lo que se graba en plata.
    """

    def test_los_colores_y_los_nombres_llegan_juntos(self, bot, mundo):
        hablar(
            bot,
            "Quiero el de dos huellitas. 1 huella color morado para el centro y "
            "los deditos rosado. 2 huella color verde oscuro en el centro y los "
            "deditos color verde claro. Dentro grabado los nombres Lulu & Roberta",
        )
        d = proceso(mundo).datos
        assert d["grabados"] == ["Lulu", "Roberta"]
        assert len(d["colores"]) == 2

    def test_la_ciudad_tampoco_se_pierde(self, bot, mundo):
        hablar(bot, "quiero un anillo de 1 huellita")
        hablar(bot, "corazón lila y dedos morados, soy de Medellín")
        d = proceso(mundo).datos
        assert d["colores"] == [{"corazon": "LILA", "dedos": "MORADO"}]
        assert d["ciudad"] == "Medellín"

    def test_ya_no_pregunta_el_grabado_que_acaba_de_recibir(self, bot):
        respuesta = hablar(
            bot,
            "Quiero el de dos huellitas. 1 huella color morado para el centro y "
            "los deditos rosado. 2 huella color verde oscuro en el centro y los "
            "deditos color verde claro. Dentro grabado los nombres Lulu & Roberta",
        )[0]
        assert "grabamos" not in respuesta.lower()


class TestEnvioEsUnVerboYUnSustantivo:
    """«Ya te envío la foto del comprobante» no pregunta por el flete.

    La pista de atributo buscaba la palabra «envío» sin mirar si era el
    sustantivo o el verbo, y el bot le contestaba el párrafo del costo del
    envío a una clienta que le estaba avisando de un pago.
    """

    def test_avisar_de_un_comprobante_no_cotiza_el_flete(self, bot):
        hablar(bot, "quiero un anillo de 1 huellita")
        respuesta = hablar(bot, "ya te envio foto del comprobante")[0]
        assert "COORDINADORA" not in respuesta

    def test_preguntar_por_el_envio_sigue_contestandose(self, bot):
        respuesta = hablar(bot, "cuánto vale el envío?")[0]
        assert "COORDINADORA" in respuesta

    def test_el_envio_se_puede_pagar_de_una_vez(self, bot):
        """Sale textual de una conversación real."""
        respuesta = hablar(bot, "El envío se puede pagar de una vez?")[0]
        assert "COORDINADORA" in respuesta


class TestUnaSolaCompraALaVez:
    """«talla 6» … «me gustaría en negro» partía la venta en DOS compras.

    La talla se quedaba huérfana en un proceso que nadie volvía a tocar, las
    dos mitades pedían lo mismo, y todo lo que llegaba después acababa en
    «mejor te paso con una personita»: la conversación se jamaba para siempre.
    Es el fallo que más lejos llega de todos, porque no se recupera solo.
    """

    def test_describir_el_anillo_no_abre_otra_compra(self, bot, mundo):
        hablar(bot, "talla 6")
        hablar(bot, "me gustaría en negro")
        assert len(mundo.contexto(CONV).abiertos(TipoProceso.COMPRA)) == 1

    def test_no_se_pierde_nada_por_el_camino(self, bot, mundo):
        hablar(bot, "talla 6", "me gustaría en negro")
        hablar(bot, "nombres: Sakura y Muñeco")
        d = proceso(mundo).datos
        assert d["talla"] == 6.0
        assert d["color_suelto"] == "NEGRO"
        assert d["grabados"] == ["Sakura", "Muñeco"]

    def test_una_compra_ya_cerrada_deja_sitio_a_la_siguiente(self, bot, mundo):
        """Con el pedido ya creado, «quiero otro anillo» SÍ abre otra compra:
        si no, la segunda venta se pegaría encima de la primera."""
        _compra_completa(bot)
        antes = len(mundo.contexto(CONV).abiertos(TipoProceso.COMPRA))
        hablar(bot, "quiero otro anillo de 3 huellitas")
        assert len(mundo.contexto(CONV).abiertos(TipoProceso.COMPRA)) > antes


class TestLaTallaSinLaPalabraTalla:
    """«aunque creo que soy 5». Así dice su talla quien ya la sabe."""

    def test_soy_5_es_la_talla(self, bot, mundo):
        hablar(bot, "quiero un anillo de 1 huellita", "aunque creo que soy 5")
        assert proceso(mundo).datos["talla"] == 5.0

    def test_uso_la_7_tambien(self, bot, mundo):
        hablar(bot, "quiero un anillo de 1 huellita", "uso la 7")
        assert proceso(mundo).datos["talla"] == 7.0

    def test_un_numero_fuera_de_las_tallas_no_cuenta(self, bot, mundo):
        hablar(bot, "quiero un anillo de 1 huellita", "somos 30 en el grupo")
        assert proceso(mundo).datos.get("talla") is None


class TestLosNombresConCorazonesEnMedio:
    """«Y adentro: Lukas ♥ Simón ♥ Orión» y «🐱 Gordo & Pan 🍞».

    Los nombres reales del grabado vienen separados por corazones y emojis, no
    por comas. Con la lista corta de separadores los tres peluditos salían
    como UN nombre cortado por la mitad: «Lukas Simon Ori».
    """

    def test_tres_nombres_separados_por_corazones(self, bot, mundo):
        hablar(bot, "quiero un anillo de 1 huellita", "corazón negro y dedos negros")
        hablar(bot, "Y adentro: Lukas ♥ Simón ♥ Orión")
        assert proceso(mundo).datos["grabados"] == ["Lukas", "Simón", "Orión"]

    def test_dos_nombres_con_emoji_a_los_lados(self, bot, mundo):
        hablar(bot, "quiero un anillo de 1 huellita", "corazón negro y dedos negros")
        hablar(bot, "nombres: 🐱 Gordo & Pan 🍞")
        assert proceso(mundo).datos["grabados"] == ["Gordo", "Pan"]

    def test_una_pregunta_con_dentro_no_graba_nada(self, bot, mundo):
        """«¿Dentro de cuánto llega?» no es un grabado. Sin los dos puntos no
        se lee ningún nombre, y por eso son obligatorios."""
        hablar(bot, "quiero un anillo de 1 huellita", "corazón negro y dedos negros")
        hablar(bot, "dentro de cuánto llega?")
        assert not proceso(mundo).datos.get("grabados")


class TestDondeMandoElAbono:
    """«A qué número te envío los 60?» y «¿cómo hago el adelanto?».

    Es la pregunta del momento exacto en que la clienta decidió comprar. Salen
    textuales de dos conversaciones reales y se contestaban con el costo del
    flete, por la palabra «envío» del verbo.
    """

    def test_a_que_numero_da_las_cuentas(self, bot):
        hablar(bot, "quiero un anillo de 1 huellita")
        respuesta = hablar(bot, "A qué número te envío los 60?")[0]
        assert "Nequi" in respuesta
        assert "COORDINADORA" not in respuesta

    def test_como_hago_el_adelanto_tambien(self, bot):
        hablar(bot, "quiero un anillo de 1 huellita")
        respuesta = hablar(bot, "Y cómo hago el adelanto del anillo?")[0]
        assert "Nequi" in respuesta


class TestContestarAlgoResetaLaCuentaDeInsistencias:
    """Una clienta que trae un dato nuevo no es una que no contesta.

    La cuenta de insistencias solo subía, y una conversación real se murió por
    eso: faltaba la cantidad de huellitas, ella fue dando el color, el grabado y
    su nombre —contestando, uno por uno— y cada turno sumaba un punto hasta que
    el bot pasó a «mejor te paso con una personita» y contestó eso mismo a TODO
    lo demás, incluida una pregunta nueva sobre el tiempo de entrega.
    """

    def test_dar_un_dato_nuevo_no_suma_insistencia(self, bot, mundo):
        hablar(bot, "quiero hacer un pedido")  # queda pidiendo las huellitas
        hablar(bot, "me gusta este morado, toda la huellita en el mismo tono")
        assert mundo.contexto(CONV).veces == 0, "contó como que no contestó"

    def test_tres_mensajes_con_datos_no_escalan(self, bot):
        hablar(bot, "quiero hacer un pedido")
        respuestas = hablar(
            bot,
            "me gusta este morado, toda la huellita en el mismo tono",
            "nombres: Lilú",
            "talla 6",
        )
        assert not any("personita" in r for r in respuestas)

    def test_sin_aportar_nada_si_acaba_escalando(self, bot):
        """La red de seguridad sigue puesta: tres mensajes que no dicen nada
        SÍ acaban en una persona. Eso no se toca."""
        hablar(bot, "quiero un anillo de 1 huellita")
        respuestas = hablar(bot, "mmm", "no sé", "eh")
        assert any("personita" in r for r in respuestas)


class TestElTiempoDeEntrega:
    """«Son días hábiles o calendario??». Textual, y justo después de pagar."""

    def test_dias_habiles_o_calendario_se_contesta(self, bot):
        respuesta = hablar(bot, "Son días hábiles o calendario ??")[0]
        assert "calendario" in respuesta.lower()

    def test_cuanto_tiempo_tambien(self, bot):
        respuesta = hablar(bot, "cuánto tiempo se demora?")[0]
        assert "10 a 15" in respuesta

    def test_no_le_dice_que_la_saco_de_una_foto_que_no_mando(self, bot):
        """El eco lo lee la clienta: «la saqué de tu foto» cuando ella ESCRIBIÓ
        la medida la deja preguntándose qué foto mandó."""
        hablar(bot, "quiero un anillo de 1 huellita")
        respuesta = hablar(bot, "1,80 cm")[0]
        assert "talla 7¾" in respuesta
        assert "foto" not in respuesta.lower()
