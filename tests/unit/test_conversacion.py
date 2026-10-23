"""Los siete casos del rediseño, contra el pipeline de verdad.

No hay red, no hay LLM y no hay WhatsApp: el intérprete es un doble que
devuelve la `Interpretacion` que devolvería un modelo bien afinado. Eso es
deliberado — aquí se prueba EL SISTEMA, no el modelo. Si el modelo entiende
mal, eso lo mide el golden dataset; si el sistema hace tonterías con lo que
entendió bien, se mide aquí.
"""

from __future__ import annotations

import pytest

from app.adapters.repositories.memory import (
    InMemoryCustomerRepository,
    InMemoryOrderRepository,
    InMemoryProductRepository,
)
from app.conversacion.ejecutor import Ejecutor
from app.conversacion.mundo import Mundo
from app.conversacion.pipeline import Pipeline
from app.conversacion.redactor import Redactor
from app.domain.acciones import Accion
from app.domain.contexto import ContextoConversacional, TipoProceso
from app.domain.interpretacion import (
    Acto,
    Atributo,
    DatosSueltos,
    Entidad,
    Interpretacion,
    Referencia,
    TipoReferencia,
)
from app.domain.models import Channel, Customer, Order, OrderItem, Product
from app.domain.order_state import OrderState
from app.domain.personalizacion import ColorCircon
from app.domain.validacion import Veredicto

CONV = "wa:573001112233"


class ContextoEnMemoria:
    def __init__(self):
        self._d: dict[str, ContextoConversacional] = {}

    def cargar(self, conv_id):
        return self._d.get(conv_id) or ContextoConversacional(conversation_id=conv_id)

    def guardar(self, ctx):
        self._d[ctx.conversation_id] = ctx


class InterpreteFalso:
    """Devuelve lo que le pongas, en orden. Es el modelo, sin el modelo."""

    def __init__(self):
        self.cola: list[Interpretacion] = []

    def dira(self, *interpretaciones):
        self.cola.extend(interpretaciones)
        return self

    def interpretar(self, texto, media, contexto):
        return self.cola.pop(0) if self.cola else Interpretacion(acto=Acto.OTRO)


@pytest.fixture
def mundo():
    productos = InMemoryProductRepository(
        [
            Product(
                sku="ANI-HUE-1",
                nombre="Anillo huellita x1",
                precio_cop=200_000,
                iva_pct=0,
                dias_produccion=10,
                dias_produccion_max=15,
                anticipo_fijo_cop=60_000,
                huellitas=1,
            ),
            Product(
                sku="ANI-HUE-2",
                nombre="Anillo huellita x2",
                precio_cop=250_000,
                iva_pct=0,
                dias_produccion=10,
                dias_produccion_max=15,
                anticipo_fijo_cop=60_000,
                huellitas=2,
            ),
            Product(
                sku="ANI-HUE-3",
                nombre="Anillo huellita x3",
                precio_cop=300_000,
                iva_pct=0,
                dias_produccion=10,
                dias_produccion_max=15,
                anticipo_fijo_cop=60_000,
                huellitas=3,
            ),
        ]
    )
    customers = InMemoryCustomerRepository()
    customers.upsert(
        Customer(
            id="c1",
            channel=Channel.WHATSAPP,
            channel_user_id="573001112233",
            nombre="Ángela",
        )
    )
    return Mundo(InMemoryOrderRepository(), customers, productos, ContextoEnMemoria())


@pytest.fixture
def interprete():
    return InterpreteFalso()


@pytest.fixture
def bot(mundo, interprete):
    return Pipeline(interprete, mundo, Ejecutor(mundo), Redactor())


def _pedido(
    mundo,
    codigo,
    estado,
    *,
    nombre="Anillo huellita x1",
    total=200_000,
    abonado=0,
    saldo_pagado=0,
    idem="k",
) -> Order:
    o = Order(
        codigo=codigo,
        customer_id="c1",
        estado=estado.value,
        items=[
            OrderItem(
                sku="ANI-HUE-1", nombre=nombre, cantidad=1, precio_unitario_cop=total
            )
        ],
        total_cop=total,
        anticipo_cop=60_000,
        saldo_cop=total - 60_000,
        anticipo_pagado_cop=abonado,
        saldo_pagado_cop=saldo_pagado,
    )
    return mundo._orders.create(o, idem_key=idem)


# ═══════════════════════════════════════════════════════════════════════════
# CASO 1 — INTERRUPCIÓN
# ═══════════════════════════════════════════════════════════════════════════


class TestCaso1Interrupcion:
    def test_comprar_consultar_y_retomar_sin_perder_nada(self, bot, mundo, interprete):
        _pedido(mundo, "PED-2026-0001", OrderState.EN_PRODUCCION, idem="a")

        interprete.dira(
            # "quiero comprar un anillo de dos huellitas"
            Interpretacion(
                acto=Acto.COMPRAR,
                entidad=Entidad.PRODUCTO,
                datos=DatosSueltos(huellitas=2),
            ),
            # "¿cómo va mi pedido anterior?"  <- cambia de tema
            Interpretacion(
                acto=Acto.CONSULTAR, entidad=Entidad.PEDIDO, atributo=Atributo.ESTADO
            ),
            # "mi talla es 8"  <- vuelve, sin decir a qué
            Interpretacion(
                acto=Acto.INFORMAR, entidad=Entidad.TALLA, datos=DatosSueltos(talla=8)
            ),
        )

        t1 = bot.ejecutar(CONV, "quiero comprar un anillo de dos huellitas")
        assert t1.decision.accion is Accion.INICIAR_COMPRA
        assert t1.contexto.abiertos(TipoProceso.COMPRA)

        t2 = bot.ejecutar(CONV, "¿cómo va mi pedido anterior?")
        assert t2.decision.accion is Accion.CONSULTAR_PEDIDO
        assert "PED-2026-0001" in t2.respuesta.texto_plano
        # LA prueba: la compra sigue viva mientras se contesta otra cosa.
        assert t2.contexto.abiertos(TipoProceso.COMPRA), "se perdió la compra"

        t3 = bot.ejecutar(CONV, "mi talla es 8")
        compra = t3.contexto.abiertos(TipoProceso.COMPRA)[0]
        assert compra.datos["huellitas"] == 2, "olvidó las huellitas"
        assert compra.datos["talla"] == 8, "no asoció la talla a la compra"


# ═══════════════════════════════════════════════════════════════════════════
# CASO 2 — VARIOS PEDIDOS Y REFERENCIAS
# ═══════════════════════════════════════════════════════════════════════════


class TestCaso2VariosPedidos:
    @pytest.fixture
    def con_pedidos(self, mundo):
        _pedido(mundo, "PED-0001", OrderState.EN_PRODUCCION, abonado=60_000, idem="a")
        _pedido(
            mundo,
            "PED-0002",
            OrderState.ESPERANDO_SALDO,
            nombre="Anillo huellita x2",
            total=250_000,
            abonado=60_000,
            idem="b",
        )
        _pedido(
            mundo,
            "PED-0003",
            OrderState.DESPACHADO,
            abonado=60_000,
            saldo_pagado=140_000,
            idem="c",
        )
        return mundo

    def test_los_lista_y_luego_resuelve_el_segundo(self, bot, con_pedidos, interprete):
        interprete.dira(
            Interpretacion(acto=Acto.CONSULTAR, entidad=Entidad.PEDIDO),
            Interpretacion(
                acto=Acto.CONSULTAR,
                entidad=Entidad.PEDIDO,
                atributo=Atributo.SALDO,
                referencia=Referencia(tipo=TipoReferencia.ORDINAL, posicion=2),
            ),
        )
        t1 = bot.ejecutar(CONV, "¿cómo van mis pedidos?")
        assert len(t1.contexto.menciones) == 3, "no guardó la lista que mostró"

        t2 = bot.ejecutar(CONV, "¿y el segundo?")
        segundo = t1.contexto.menciones[1].id
        assert t2.decision.objetivo_id == segundo
        assert t2.decision.veredicto is Veredicto.EJECUTAR

    def test_luego_ya_pague_hereda_la_referencia(self, bot, con_pedidos, interprete):
        """CASO 6: si acabamos de hablar de UNO, «ya pagué» no es ambiguo."""
        interprete.dira(
            Interpretacion(
                acto=Acto.CONSULTAR,
                entidad=Entidad.PEDIDO,
                referencia=Referencia(tipo=TipoReferencia.ORDINAL, posicion=2),
            ),
            Interpretacion(acto=Acto.INFORMAR, entidad=Entidad.PAGO),
        )
        bot.ejecutar(CONV, "¿cómo van mis pedidos?")  # sin menciones aún -> lista
        t2 = bot.ejecutar(CONV, "ya pagué")
        assert t2.decision.accion is Accion.REGISTRAR_PAGO_REPORTADO

    def test_el_pago_NUNCA_se_confirma_solo(self, bot, con_pedidos, interprete):
        """Decirlo no es haberlo hecho. Ni con el pedido perfectamente claro.

        Lo que sí pasa es que el pedido queda EN REVISIÓN, para que Lía lo
        vea en el panel: un aviso que nadie mira es lo mismo que no avisar.
        Pero desde revisión no se puede producir ni despachar — lo impide la
        tabla de transiciones, no la buena voluntad de nadie.
        """
        interprete.dira(
            Interpretacion(
                acto=Acto.INFORMAR,
                entidad=Entidad.PAGO,
                referencia=Referencia(tipo=TipoReferencia.CODIGO, texto="PED-0002"),
            ),
        )
        t = bot.ejecutar(CONV, "ya pagué el PED-0002")
        pedido = con_pedidos._orders.get_by_code("PED-0002")
        assert pedido.estado == OrderState.EN_REVISION_PAGO.value
        assert pedido.saldo_pagado_cop == 0, "dio por pagado lo que solo dijo"

        from app.domain.order_state import TRANSICIONES

        desde_revision = TRANSICIONES[OrderState.EN_REVISION_PAGO]
        assert OrderState.EN_PRODUCCION not in desde_revision
        assert OrderState.DESPACHADO not in desde_revision
        assert "comprobante" in t.respuesta.texto_plano.lower()
        assert any(p.tipo is TipoProceso.PAGO_REPORTADO for p in t.contexto.abiertos()), (
            "no dejó constancia de que lo reportó"
        )


# ═══════════════════════════════════════════════════════════════════════════
# CASO 4 — INFORMACIÓN EN CUALQUIER ORDEN
# ═══════════════════════════════════════════════════════════════════════════


class TestCaso4CualquierOrden:
    def test_se_completa_progresivamente_sin_repetir_preguntas(
        self, bot, mundo, interprete
    ):
        interprete.dira(
            # "quiero un anillo talla 8"
            Interpretacion(
                acto=Acto.COMPRAR, entidad=Entidad.PRODUCTO, datos=DatosSueltos(talla=8)
            ),
            # "con dos huellitas"
            Interpretacion(
                acto=Acto.INFORMAR,
                entidad=Entidad.PRODUCTO,
                datos=DatosSueltos(huellitas=2),
            ),
            # "que sean rosadas"
            Interpretacion(
                acto=Acto.INFORMAR,
                entidad=Entidad.COLOR,
                datos=DatosSueltos(
                    color_corazon=ColorCircon.ROSADO, color_dedos=ColorCircon.ROSADO
                ),
            ),
        )
        bot.ejecutar(CONV, "quiero un anillo talla 8")
        t2 = bot.ejecutar(CONV, "con dos huellitas")
        t3 = bot.ejecutar(CONV, "que sean rosadas")

        compra = t3.contexto.abiertos(TipoProceso.COMPRA)[0]
        assert compra.datos["talla"] == 8
        assert compra.datos["huellitas"] == 2
        assert len(compra.datos["colores"]) == 1

        # No vuelve a PEDIR lo que ya sabe. (Repetirlo para confirmar sí:
        # el eco «Anoté: 2 huellitas, talla 8» es lo que le deja corregir.)
        assert "cuántas huellitas" not in t2.respuesta.texto_plano.lower()
        assert "falta tu talla" not in t3.respuesta.texto_plano.lower()
        # Dos huellitas llevan DOS pares de colores: sigue faltando el segundo.
        # Asumir que «rosadas» valía para las dos sería adivinar un anillo.
        # …y después del anillo, su nombre y ya. Los datos de envío se piden
        # al FINAL, con las fotos del anillo terminado (Camilo, 20/09).
        assert compra.faltan == ["colores", "grabado", "nombre"]
        assert "huellita 2" in t3.respuesta.texto_plano.lower(), (
            "pide el segundo par sin decir que es el segundo: parece que no la escuchó"
        )

    def test_todo_en_una_frase_no_pregunta_lo_que_ya_dijo(self, bot, mundo, interprete):
        interprete.dira(
            Interpretacion(
                acto=Acto.COMPRAR,
                entidad=Entidad.PRODUCTO,
                datos=DatosSueltos(huellitas=2, talla=8),
            )
        )
        t = bot.ejecutar(CONV, "quiero un anillo con dos huellitas talla 8")
        compra = t.contexto.abiertos(TipoProceso.COMPRA)[0]
        assert compra.datos["huellitas"] == 2 and compra.datos["talla"] == 8
        assert "cuántas huellitas" not in t.respuesta.texto_plano.lower()
        # Solo pregunta lo que de verdad falta.
        assert "colores" in compra.faltan


# ═══════════════════════════════════════════════════════════════════════════
# CASO 5 — AMBIGÜEDAD
# ═══════════════════════════════════════════════════════════════════════════


class TestCaso5Ambiguedad:
    def test_ya_pague_con_dos_deudas_pregunta_y_no_asume(self, bot, mundo, interprete):
        _pedido(mundo, "PED-A", OrderState.ESPERANDO_ANTICIPO, idem="a")
        _pedido(mundo, "PED-B", OrderState.ESPERANDO_SALDO, abonado=60_000, idem="b")
        interprete.dira(Interpretacion(acto=Acto.INFORMAR, entidad=Entidad.PAGO))

        t = bot.ejecutar(CONV, "ya pagué")
        assert t.decision.veredicto is Veredicto.PREGUNTAR
        assert len(t.decision.candidatos) == 2
        texto = t.respuesta.texto_plano
        assert "cuál" in texto.lower()
        # Y pregunta NOMBRANDO, no con un «¿cuál?» a secas.
        assert "1." in texto and "2." in texto

    def test_pero_con_UNA_sola_deuda_no_molesta(self, bot, mundo, interprete):
        _pedido(mundo, "PED-A", OrderState.ESPERANDO_SALDO, abonado=60_000, idem="a")
        _pedido(
            mundo,
            "PED-B",
            OrderState.DESPACHADO,
            abonado=60_000,
            saldo_pagado=140_000,
            idem="b",
        )
        interprete.dira(Interpretacion(acto=Acto.INFORMAR, entidad=Entidad.PAGO))

        t = bot.ejecutar(CONV, "ya pagué")
        assert t.decision.veredicto is Veredicto.EJECUTAR

    def test_una_consulta_con_varios_NO_pregunta(self, bot, mundo, interprete):
        """Prudente en lo que cuesta dinero, natural en lo demás."""
        _pedido(mundo, "PED-A", OrderState.EN_PRODUCCION, idem="a")
        _pedido(mundo, "PED-B", OrderState.ESPERANDO_SALDO, idem="b")
        interprete.dira(
            Interpretacion(
                acto=Acto.CONSULTAR, entidad=Entidad.PEDIDO, atributo=Atributo.ESTADO
            )
        )
        t = bot.ejecutar(CONV, "¿cómo va mi pedido?")
        assert t.decision.veredicto is Veredicto.EJECUTAR


# ═══════════════════════════════════════════════════════════════════════════
# CASO 7 — IMÁGENES
# ═══════════════════════════════════════════════════════════════════════════


class TestCaso7Imagenes:
    def test_quiero_ver_ejemplos_manda_texto_y_VARIAS_imagenes(
        self, bot, mundo, interprete
    ):
        """El techo de un mensaje por turno era la causa real del fallo."""
        interprete.dira(Interpretacion(acto=Acto.CONSULTAR, entidad=Entidad.IMAGEN))
        t = bot.ejecutar(CONV, "quiero ver ejemplos")
        assert t.decision.accion is Accion.MOSTRAR_IMAGENES
        assert len(t.respuesta.piezas) >= 2, "sigue mandando un solo mensaje"
        assert len(t.respuesta.imagenes()) == 3
        assert t.respuesta.piezas[0].texto, "las fotos llegan sin decir qué son"

    def test_al_pedir_los_colores_se_manda_el_muestrario(self, bot, mundo, interprete):
        interprete.dira(
            Interpretacion(
                acto=Acto.COMPRAR,
                entidad=Entidad.PRODUCTO,
                datos=DatosSueltos(huellitas=1),
            )
        )
        t = bot.ejecutar(CONV, "quiero uno de una huellita")
        assert "muestrario_circones" in t.respuesta.imagenes()


# ═══════════════════════════════════════════════════════════════════════════
# El catálogo comercial y las reglas duras
# ═══════════════════════════════════════════════════════════════════════════


class TestCatalogoYReglas:
    def test_el_catalogo_no_parece_un_formulario(self, bot, mundo, interprete):
        interprete.dira(Interpretacion(acto=Acto.PREGUNTAR, entidad=Entidad.PRODUCTO))
        t = bot.ejecutar(CONV, "hola, me cuentas del anillo?")
        texto = t.respuesta.texto_plano
        assert "$200.000" in texto and "$60.000" in texto
        assert "Plata Ley 925" in texto
        for feo in ("seleccione", "opción 1", "presione", "proceso completado"):
            assert feo not in texto.lower()

    def test_NINGUNA_respuesta_trae_botones(self, bot, mundo, interprete):
        """La conversación tiene que funcionar entera escribiendo."""
        interprete.dira(
            Interpretacion(acto=Acto.SALUDAR),
            Interpretacion(acto=Acto.PREGUNTAR, entidad=Entidad.PRODUCTO),
            Interpretacion(
                acto=Acto.COMPRAR,
                entidad=Entidad.PRODUCTO,
                datos=DatosSueltos(huellitas=2),
            ),
        )
        for mensaje in ("hola", "info", "quiero dos huellitas"):
            t = bot.ejecutar(CONV, mensaje)
            for pieza in t.respuesta.piezas:
                assert not pieza.opciones, "se coló un botón"

    def test_pedir_humano_escala(self, bot, mundo, interprete):
        interprete.dira(Interpretacion(acto=Acto.HUMANO))
        t = bot.ejecutar(CONV, "quiero hablar con alguien")
        assert t.respuesta.escalar is True

    def test_cancelar_NO_lo_hace_el_bot(self, bot, mundo, interprete):
        """Un pedido cancelado por error es un anillo de plata ya fundido."""
        _pedido(mundo, "PED-A", OrderState.EN_PRODUCCION, idem="a")
        interprete.dira(Interpretacion(acto=Acto.CANCELAR, entidad=Entidad.PEDIDO))
        t = bot.ejecutar(CONV, "quiero cancelar")
        assert t.decision.accion is Accion.PEDIR_CANCELACION
        assert mundo._orders.get_by_code("PED-A").estado == OrderState.EN_PRODUCCION.value


# ═══════════════════════════════════════════════════════════════════════════
# La puerta a que un día sea propositivo
# ═══════════════════════════════════════════════════════════════════════════


class TestPropositivo:
    def test_se_puede_arrancar_sin_mensaje_ni_modelo(self, bot, mundo):
        """El camino que usará un recordatorio: entra por el tramo 5.

        Hoy no lo llama nadie. Este test existe para que siga funcionando
        cuando llegue el momento, en vez de descubrir entonces que la lógica
        se enredó con «el mensaje entrante»."""
        _pedido(mundo, "PED-A", OrderState.ANTICIPO_PAGADO, abonado=60_000, idem="a")
        pedido = mundo._orders.get_by_code("PED-A")
        t = bot.desde_accion(CONV, Accion.CONSULTAR_PEDIDO, objetivo_id=pedido.id)
        assert t.interpretacion is None, "no debería hacer falta el modelo"
        assert "PED-A" in t.respuesta.texto_plano


class TestElEcoNoSuenaAFormulario:
    """Repetir todo lo acumulado en cada turno hace que el bot suene a un
    formulario leyendo su propio estado en voz alta. Se nota enseguida
    hablando con él, y no lo caza ningún test de comportamiento."""

    def test_solo_repite_lo_que_acaba_de_llegar(self, bot, mundo, interprete):
        interprete.dira(
            Interpretacion(
                acto=Acto.COMPRAR,
                entidad=Entidad.PRODUCTO,
                datos=DatosSueltos(huellitas=2, talla=8),
            ),
            Interpretacion(
                acto=Acto.INFORMAR,
                entidad=Entidad.COLOR,
                datos=DatosSueltos(
                    color_corazon=ColorCircon.LILA, color_dedos=ColorCircon.MORADO
                ),
            ),
        )
        t1 = bot.ejecutar(CONV, "quiero dos huellitas talla 8")
        assert "2 huellitas" in t1.respuesta.texto_plano
        assert "talla 8" in t1.respuesta.texto_plano

        t2 = bot.ejecutar(CONV, "corazon lila y dedos morados")
        texto = t2.respuesta.texto_plano
        assert "lila" in texto, "no confirmó lo que acaba de entender"
        assert "2 huellitas, talla 8" not in texto, (
            "está repitiendo todo lo acumulado, como un formulario"
        )
