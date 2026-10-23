"""Pedidos activos, pedidos cerrados, historial, fotos y capas de modelo.

════════════════════════════════════════════════════════════════════════════
DE DÓNDE SALE ESTE ARCHIVO
════════════════════════════════════════════════════════════════════════════
De la conversación de prueba con el número de Meta (11/09/2026). El pedido
PED-2026-4826 se despachó y, cinco minutos después:

  · «me puedes montar cómo quedaría uno completamente azul?» -> el bot le
    CAMBIÓ LOS COLORES AL PEDIDO DESPACHADO
  · «comencemos de 0» -> le volvió a enseñar ese mismo pedido
  · «quiero nombre Roberto y color rosado todo» -> grabado «Roberto, color»
  · «Cambio la dirección a …» -> contestó el tiempo de fabricación
  · «Cuántos pedidos he hecho» -> solo el activo, «te queda por pagar $200.000»

Y de los diez casos de la especificación de la arquitectura de contexto. Cada
test dice qué capa respondió (reglas, modelo básico, potente) y con qué
contexto, porque eso es exactamente lo que se quería controlar.

Los modelos aquí son dobles que APUNTAN cuándo se les llama: el punto de
varios tests es demostrar que NO se les llamó.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.adapters.repositories.memory import (
    InMemoryCustomerRepository,
    InMemoryOrderRepository,
    InMemoryProductRepository,
)
from app.conversacion.desempate import DesempateHistorico, EleccionHistorica
from app.conversacion.ejecutor import Ejecutor
from app.conversacion.interprete import Interprete, leer_datos, leer_grabado
from app.conversacion.mundo import Mundo
from app.conversacion.ojos import Ojos
from app.conversacion.pipeline import Pipeline
from app.conversacion.redactor import Redactor
from app.domain import consumo
from app.domain.acciones import Accion
from app.domain.cambios import Permiso, permiso
from app.domain.contexto import ContextoConversacional, Proceso, TipoProceso
from app.domain.historial import (
    FiltroHistorico,
    buscar,
    es_referencia_historica,
    leer_filtro,
)
from app.domain.interpretacion import Acto, Atributo, Entidad, Interpretacion
from app.domain.models import Channel, Customer, Order, OrderItem, Product
from app.domain.operativo import pendiente_de_pago, sanear
from app.domain.order_state import OrderState
from app.domain.personalizacion import ColorCircon, Huellita, Personalizacion
from app.domain.vision import LecturaDeImagen, TipoDeImagen

CONV = "wa:573001112233"
FOTO = [{"kind": "image", "media_id": "wamid-foto-1"}]
HOY = datetime.now(UTC)
S = OrderState


# ═══════════════════════════════════════════════════════════════════════════
# DOBLES
# ═══════════════════════════════════════════════════════════════════════════


class ContextoEnMemoria:
    def __init__(self):
        self._d: dict[str, ContextoConversacional] = {}

    def cargar(self, conv_id):
        return self._d.get(conv_id) or ContextoConversacional(conversation_id=conv_id)

    def guardar(self, ctx):
        self._d[ctx.conversation_id] = ctx


class Modelo:
    """Un modelo que devuelve lo que se le diga y apunta cada llamada."""

    def __init__(self, respuesta: Interpretacion | None = None, *, contexto=False):
        self.visto: list[str] = []
        self.respuesta = respuesta or Interpretacion(acto=Acto.OTRO, confianza="BAJA")
        self.acepta_contexto = contexto

    def extract(self, prompt, texto, esquema):
        self.visto.append(texto)
        if esquema is EleccionHistorica:
            return EleccionHistorica(numero=2, confianza="ALTA")
        return self.respuesta


class Vision:
    def __init__(self, lectura: LecturaDeImagen):
        self.lectura = lectura
        self.pistas: list[str] = []

    def leer(self, imagen, *, pista=""):
        self.pistas.append(pista)
        return self.lectura


class Media:
    def download(self, referencia):
        return b"\xff\xd8\xff\xe0foto"


def _productos():
    return InMemoryProductRepository(
        [
            Product(
                sku=f"ANI-HUE-{n}",
                nombre="Anillo personalizado huellita",
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
        Customer(id="c1", channel=Channel.WHATSAPP, channel_user_id="573001112233")
    )
    return Mundo(InMemoryOrderRepository(), customers, _productos(), ContextoEnMemoria())


def _bot(mundo, *, basico=None, fuerte=None, vision=None, vision_fuerte=None):
    basico = basico or Modelo()
    interprete = Interprete(
        basico,
        prompt="",
        catalogo_txt="",
        ojos=Ojos(vision=vision, media=Media(), vision_fuerte=vision_fuerte),
        llm_fuerte=fuerte,
    )
    desempate = DesempateHistorico(fuerte) if fuerte else None
    return Pipeline(interprete, mundo, Ejecutor(mundo, desempate=desempate), Redactor())


def _pedido(
    mundo,
    codigo: str,
    estado: OrderState,
    *,
    creado: datetime | None = None,
    color=ColorCircon.ROSADO,
    talla: float | None = 8,
    grabados=("Sonia", "Roberto"),
) -> Order:
    o = Order(
        codigo=codigo,
        customer_id="c1",
        estado=estado.value,
        items=[
            OrderItem(
                sku="ANI-HUE-1",
                nombre="Anillo personalizado huellita",
                cantidad=1,
                precio_unitario_cop=200_000,
                personalizacion=Personalizacion(
                    talla=talla,
                    huellitas=[Huellita(corazon=color, dedos=color)],
                    grabados=list(grabados),
                ),
            )
        ],
        total_cop=200_000,
        anticipo_cop=60_000,
        saldo_cop=140_000,
        created_at=creado or HOY,
    )
    return mundo._orders.create(o, idem_key=f"t:{codigo}")


def _compra_de(pedido: Order, *, hace_dias: int = 0) -> Proceso:
    """El proceso de compra que dejó ese pedido en la conversación."""
    cuando = HOY - timedelta(days=hace_dias)
    return Proceso(
        tipo=TipoProceso.COMPRA,
        pedido_id=pedido.id,
        datos={
            "pedido_id": pedido.id,
            "codigo": pedido.codigo,
            "huellitas": 1,
            "colores": [{"corazon": "ROSADO", "dedos": "ROSADO"}],
            "grabados": ["Sonia", "Roberto"],
            "talla": 8,
            "nombre_envio": "Camilo",
            "ciudad": "Bucaramanga",
            "direccion": "Torre 1 apto 301",
        },
        creado=cuando,
        tocado=cuando,
    )


def _guardar_ctx(mundo, **kw):
    mundo.guardar_contexto(ContextoConversacional(conversation_id=CONV, **kw))


def _mes_pasado_con_agosto() -> int:
    return HOY.year if HOY.month >= 8 else HOY.year - 1


# ═══════════════════════════════════════════════════════════════════════════
# LOS DIEZ CASOS
# ═══════════════════════════════════════════════════════════════════════════


class TestCaso1ClienteNuevo:
    def test_hola_se_resuelve_sin_ia(self, mundo):
        basico, fuerte = Modelo(), Modelo()
        turno = _bot(mundo, basico=basico, fuerte=fuerte).ejecutar(CONV, "Hola")

        assert turno.decision.accion is Accion.SALUDAR
        assert not basico.visto and not fuerte.visto
        assert turno.registro.routing_layer == "reglas"
        assert turno.registro.cost_usd == 0
        assert "Bienvenida" in turno.respuesta.texto_plano


class TestCaso2ConsultaSencilla:
    def test_el_precio_no_gasta_modelo(self, mundo):
        """Antes se llamaba al modelo y luego una regla tiraba su respuesta."""
        basico = Modelo()
        turno = _bot(mundo, basico=basico).ejecutar(CONV, "Cuánto cuesta el anillo?")

        assert turno.decision.accion is Accion.MOSTRAR_PRODUCTO
        assert not basico.visto
        assert turno.registro.routing_layer == "reglas"
        assert turno.registro.motivo == "precio"
        assert "$200.000" in turno.respuesta.texto_plano  # sale del catálogo

    def test_treinta_mensajes_resolubles_por_reglas_no_llaman_al_modelo(self, mundo):
        """La capa NO depende del número de mensajes."""
        basico = Modelo()
        bot = _bot(mundo, basico=basico)
        for _ in range(15):
            bot.ejecutar(CONV, "hola")
            bot.ejecutar(CONV, "cuanto vale?")
        assert not basico.visto


class TestCaso3PedidoActivo:
    def test_ya_te_mande_la_foto_usa_el_pedido_activo(self, mundo):
        activo = _pedido(mundo, "PED-2026-0901", S.ESPERANDO_ANTICIPO)
        basico = Modelo()
        turno = _bot(mundo, basico=basico).ejecutar(CONV, "Ya te mandé la foto")

        assert turno.decision.accion is Accion.REGISTRAR_PAGO_REPORTADO
        assert turno.decision.objetivo_id == activo.id
        # Queda EN REVISIÓN (nunca pagado) y se le dice la verdad: no llegó.
        assert mundo.pedido(activo.id).estado == S.EN_REVISION_PAGO.value
        assert "no me alcanzó a llegar" in turno.respuesta.texto_plano
        assert not basico.visto
        assert turno.registro.context_source == "pedido_activo"

    def test_si_la_foto_si_llego_hace_un_momento_se_le_dice(self, mundo):
        _pedido(mundo, "PED-2026-0902", S.ESPERANDO_ANTICIPO)
        vision = Vision(LecturaDeImagen(tipo=TipoDeImagen.COMPROBANTE, seguro=True))
        bot = _bot(mundo, vision=vision)
        bot.ejecutar(CONV, None, FOTO)
        turno = bot.ejecutar(CONV, "ya te mandé la foto")
        assert "ya me llegó" in turno.respuesta.texto_plano.lower()


class TestCaso4ActivoMasCerrado:
    def test_ya_te_mande_la_foto_NO_toca_el_pedido_cerrado(self, mundo):
        cerrado = _pedido(
            mundo,
            "PED-2026-0801",
            S.ENTREGADO,
            creado=datetime(_mes_pasado_con_agosto(), 8, 10, tzinfo=UTC),
        )
        activo = _pedido(mundo, "PED-2026-0903", S.ESPERANDO_ANTICIPO)
        # El contexto guardado todavía apunta al de agosto: así estaba la base
        # de datos real de pruebas.
        _guardar_ctx(
            mundo,
            procesos=[
                _compra_de(cerrado, hace_dias=3),
                Proceso(tipo=TipoProceso.PAGO_REPORTADO, pedido_id=cerrado.id),
            ],
            foco_tipo="PEDIDO",
            foco_id=cerrado.id,
        )

        turno = _bot(mundo).ejecutar(CONV, "Ya te mandé la foto")

        assert turno.decision.objetivo_id == activo.id
        assert mundo.pedido(cerrado.id).estado == S.ENTREGADO.value
        assert all(
            (p.pedido_id or p.datos.get("pedido_id")) != cerrado.id
            for p in turno.contexto.procesos
        )
        assert turno.contexto.foco_id != cerrado.id
        assert turno.registro.context_archived, "no quedó rastro de lo que se archivó"


class TestCaso5ConsultaHistorica:
    def test_que_paso_con_mi_pedido_de_agosto(self, mundo):
        cerrado = _pedido(
            mundo,
            "PED-2026-0802",
            S.ENTREGADO,
            creado=datetime(_mes_pasado_con_agosto(), 8, 14, tzinfo=UTC),
        )
        _pedido(mundo, "PED-2026-0904", S.EN_PRODUCCION)
        basico = Modelo()
        turno = _bot(mundo, basico=basico).ejecutar(
            CONV, "Qué pasó con mi pedido de agosto?"
        )

        assert turno.decision.accion is Accion.CONSULTAR_HISTORIAL
        assert cerrado.codigo in turno.respuesta.texto_plano
        assert "PED-2026-0904" not in turno.respuesta.texto_plano
        assert turno.registro.historical_lookup
        assert turno.registro.context_source == "historial"
        assert not basico.visto
        # Solo LEE: no pasa a ser el foco ni abre nada.
        assert turno.contexto.foco_id != cerrado.id

    def test_que_talla_habia_pedido_la_vez_pasada(self, mundo):
        _pedido(
            mundo,
            "PED-2026-0701",
            S.ENTREGADO,
            creado=HOY - timedelta(days=60),
            talla=7.5,
        )
        turno = _bot(mundo).ejecutar(
            CONV, "¿Me puedes decir qué talla había pedido la vez pasada?"
        )
        assert turno.decision.accion is Accion.CONSULTAR_HISTORIAL
        assert "7½" in turno.respuesta.texto_plano

    def test_el_de_un_color_que_compre_antes(self, mundo):
        _pedido(mundo, "PED-2026-0601", S.ENTREGADO, creado=HOY - timedelta(days=90))
        azul = _pedido(
            mundo,
            "PED-2026-0602",
            S.ENTREGADO,
            creado=HOY - timedelta(days=80),
            color=ColorCircon.AZUL_REY,
        )
        turno = _bot(mundo).ejecutar(CONV, "el pedido azul que compré antes")
        assert azul.codigo in turno.respuesta.texto_plano


class TestVariasPreguntasSobreElPasado:
    def test_tres_preguntas_distintas_del_mismo_pedido_no_escalan(self, mundo):
        """En la prueba E2E la tercera acabó en «mejor te paso con una personita»."""
        _pedido(
            mundo,
            "PED-2026-0806",
            S.ENTREGADO,
            creado=datetime(_mes_pasado_con_agosto(), 8, 20, tzinfo=UTC),
        )
        activo = _pedido(mundo, "PED-2026-0913", S.ESPERANDO_ANTICIPO)
        bot = _bot(mundo)
        bot.ejecutar(CONV, "ya pagué")  # el activo queda en foco
        for frase in (
            "Qué pasó con mi pedido de agosto?",
            "¿qué talla había pedido la vez pasada?",
            "El otro pedido",
        ):
            turno = bot.ejecutar(CONV, frase)
            assert "PED-2026-0806" in turno.respuesta.texto_plano, frase
            assert not turno.respuesta.escalar, frase
        assert mundo.pedido(activo.id).estado == S.EN_REVISION_PAGO.value

    def test_un_resumen_con_un_solo_pedido_no_ofrece_el_segundo(self, mundo):
        _pedido(mundo, "PED-2026-0914", S.DESPACHADO)
        turno = _bot(mundo).ejecutar(CONV, "cuantos pedidos he hecho")
        assert "PED-2026-0914" in turno.respuesta.texto_plano
        assert "el segundo" not in turno.respuesta.texto_plano


class TestCaso6ReferenciaHistoricaAmbigua:
    def test_el_otro_pedido_con_varios_candidatos_pregunta(self, mundo):
        _pedido(mundo, "PED-2026-0501", S.ENTREGADO, creado=HOY - timedelta(days=120))
        _pedido(mundo, "PED-2026-0502", S.CANCELADO, creado=HOY - timedelta(days=100))
        fuerte = Modelo()
        turno = _bot(mundo, fuerte=fuerte).ejecutar(CONV, "El otro pedido")

        texto = turno.respuesta.texto_plano
        assert turno.decision.accion is Accion.CONSULTAR_HISTORIAL
        assert "PED-2026-0501" in texto and "PED-2026-0502" in texto
        assert turno.registro.candidate_orders == 2
        # «El otro» sin descripción: ningún modelo sabe cuál. No se gasta.
        assert not fuerte.visto

    def test_con_una_descripcion_que_no_esta_en_los_campos_decide_el_potente(self, mundo):
        _pedido(mundo, "PED-2026-0401", S.ENTREGADO, creado=HOY - timedelta(days=200))
        _pedido(mundo, "PED-2026-0402", S.ENTREGADO, creado=HOY - timedelta(days=150))
        fuerte = Modelo()
        turno = _bot(mundo, fuerte=fuerte).ejecutar(CONV, "el pedido anterior de navidad")

        assert fuerte.visto and "PEDIDOS:" in fuerte.visto[0]
        # El doble elige el número 2 de la lista (del más reciente al más viejo).
        assert "PED-2026-0401" in turno.respuesta.texto_plano
        assert "PED-2026-0402" not in turno.respuesta.texto_plano

    def test_el_resolver_de_referencias_no_deja_pagar_un_pedido_historico(self, mundo):
        """«El segundo» de una lista de pedidos viejos se mira, no se paga."""
        _pedido(mundo, "PED-2026-0301", S.ENTREGADO, creado=HOY - timedelta(days=90))
        _pedido(mundo, "PED-2026-0302", S.ENTREGADO, creado=HOY - timedelta(days=80))
        activo = _pedido(mundo, "PED-2026-0905", S.ESPERANDO_ANTICIPO)
        bot = _bot(mundo)
        bot.ejecutar(CONV, "cuantos pedidos he hecho")
        turno = bot.ejecutar(CONV, "ya pagué el segundo")
        assert turno.decision.objetivo_id in (None, activo.id)
        assert mundo._orders.get_by_code("PED-2026-0301").estado == S.ENTREGADO.value


class TestCaso7VuelveDespuesDeVariosDias:
    def test_quiero_cambiar_la_talla_encuentra_el_pedido_activo(self, mundo):
        """El proceso de la conversación caducó; el pedido en la base de datos no."""
        activo = _pedido(
            mundo, "PED-2026-0810", S.ESPERANDO_ANTICIPO, creado=HOY - timedelta(days=20)
        )
        _guardar_ctx(mundo, procesos=[_compra_de(activo, hace_dias=20)])
        bot = _bot(mundo)

        pregunta = bot.ejecutar(CONV, "Quiero cambiar la talla")
        assert activo.codigo in pregunta.respuesta.texto_plano
        assert pregunta.registro.routing_layer == "reglas"

        bot.ejecutar(CONV, "7")
        assert mundo.pedido(activo.id).items[0].personalizacion.talla == 7

    def test_el_pedido_manda_sobre_un_proceso_guardado_con_menos_datos(self, mundo):
        """Salió de la prueba E2E: con «7» el bot preguntaba colores que el
        pedido ya tenía, porque el proceso del chat había quedado incompleto."""
        activo = _pedido(mundo, "PED-2026-0813", S.ANTICIPO_PAGADO, talla=None)
        incompleto = Proceso(
            tipo=TipoProceso.COMPRA,
            pedido_id=activo.id,
            datos={"pedido_id": activo.id, "codigo": activo.codigo, "huellitas": 1},
        )
        _guardar_ctx(mundo, procesos=[incompleto])
        bot = _bot(mundo)
        bot.ejecutar(CONV, "Quiero cambiar la talla")
        turno = bot.ejecutar(CONV, "7")

        assert mundo.pedido(activo.id).items[0].personalizacion.talla == 7
        assert mundo.pedido(activo.id).items[0].personalizacion.huellitas
        assert "color" not in turno.respuesta.texto_plano.lower()

    def test_sin_proceso_en_la_conversacion_se_reconstruye_desde_el_pedido(self, mundo):
        activo = _pedido(mundo, "PED-2026-0811", S.EN_PRODUCCION, talla=None)
        turno = _bot(mundo).ejecutar(CONV, "mi talla es 6")
        assert mundo.pedido(activo.id).items[0].personalizacion.talla == 6
        # En producción se aplica, pero Lía lo ve antes de seguir.
        assert any(activo.codigo in n for n in turno.contexto.revisar)

    def test_cambiar_una_talla_que_ya_se_esta_fundiendo_pasa_a_una_persona(self, mundo):
        activo = _pedido(mundo, "PED-2026-0812", S.EN_PRODUCCION, talla=6)
        turno = _bot(mundo).ejecutar(CONV, "talla 7")

        assert mundo.pedido(activo.id).items[0].personalizacion.talla == 6
        assert turno.respuesta.escalar
        assert "persona" in turno.respuesta.texto_plano
        assert any("NO se aplicó" in n for n in turno.contexto.revisar)


class TestCaso8ComprobanteInesperado:
    def test_llega_un_comprobante_sin_que_se_lo_pidieran(self, mundo):
        cerrado = _pedido(
            mundo, "PED-2026-0803", S.ENTREGADO, creado=HOY - timedelta(days=40)
        )
        activo = _pedido(mundo, "PED-2026-0906", S.ESPERANDO_ANTICIPO)
        vision = Vision(
            LecturaDeImagen(tipo=TipoDeImagen.COMPROBANTE, seguro=True, monto_cop=60_000)
        )
        bot = _bot(mundo, vision=vision)
        bot.ejecutar(CONV, "hola")
        turno = bot.ejecutar(CONV, None, FOTO)

        assert turno.decision.accion is Accion.RECIBIR_COMPROBANTE
        assert turno.decision.objetivo_id == activo.id
        assert mundo.pedido(activo.id).estado == S.EN_REVISION_PAGO.value
        assert mundo.pedido(cerrado.id).estado == S.ENTREGADO.value
        assert vision.pistas[-1] == "comprobante"

    def test_una_foto_ilegible_cuando_solo_se_espera_el_pago_es_el_comprobante(
        self, mundo
    ):
        activo = _pedido(mundo, "PED-2026-0907", S.ESPERANDO_SALDO)
        vision = Vision(LecturaDeImagen(tipo=TipoDeImagen.OTRA))
        turno = _bot(mundo, vision=vision).ejecutar(CONV, None, FOTO)

        assert turno.decision.accion is Accion.RECIBIR_COMPROBANTE
        assert mundo.pedido(activo.id).estado == S.EN_REVISION_PAGO.value
        assert any("por el estado del pedido" in n for n in turno.contexto.revisar)


class TestCaso9ImagenAmbigua:
    def _dos_posibilidades(self, mundo):
        """Un pedido esperando el abono Y otra compra esperando la talla."""
        _pedido(mundo, "PED-2026-0908", S.ESPERANDO_ANTICIPO)
        _guardar_ctx(
            mundo,
            procesos=[
                Proceso(
                    tipo=TipoProceso.COMPRA,
                    datos={
                        "huellitas": 1,
                        "colores": [{"corazon": "LILA", "dedos": "LILA"}],
                    },
                    faltan=["talla"],
                )
            ],
        )

    def test_escala_al_lector_potente_y_si_sigue_ambigua_pregunta(self, mundo):
        self._dos_posibilidades(mundo)
        basica = Vision(LecturaDeImagen(tipo=TipoDeImagen.OTRA))
        potente = Vision(LecturaDeImagen(tipo=TipoDeImagen.OTRA))
        bot = _bot(mundo, vision=basica, vision_fuerte=potente)

        turno = bot.ejecutar(CONV, None, FOTO)
        assert potente.pistas, "no se escaló al lector potente"
        assert "comprobante" in turno.respuesta.texto_plano
        assert "talla" in turno.respuesta.texto_plano
        assert turno.contexto.foto_pendiente
        assert turno.registro.escalated

        respuesta = bot.ejecutar(CONV, "es el comprobante")
        assert respuesta.decision.accion is Accion.RECIBIR_COMPROBANTE
        assert not respuesta.contexto.foto_pendiente

    def test_si_el_potente_la_entiende_no_se_pregunta(self, mundo):
        self._dos_posibilidades(mundo)
        basica = Vision(LecturaDeImagen(tipo=TipoDeImagen.OTRA))
        potente = Vision(LecturaDeImagen(tipo=TipoDeImagen.COMPROBANTE, seguro=True))
        turno = _bot(mundo, vision=basica, vision_fuerte=potente).ejecutar(
            CONV, None, FOTO
        )

        assert turno.decision.accion is Accion.RECIBIR_COMPROBANTE
        assert turno.registro.routing_layer == "fuerte"
        assert turno.registro.escalation_reason == "foto_ambigua"

    def test_una_foto_clara_no_escala(self, mundo):
        self._dos_posibilidades(mundo)
        basica = Vision(LecturaDeImagen(tipo=TipoDeImagen.MASCOTA, seguro=True))
        potente = Vision(LecturaDeImagen(tipo=TipoDeImagen.OTRA))
        _bot(mundo, vision=basica, vision_fuerte=potente).ejecutar(CONV, None, FOTO)
        assert not potente.pistas


class TestCaso10PedidoCerradoFueraDelContexto:
    def test_el_operativo_no_carga_pedidos_cerrados(self, mundo):
        cerrado = _pedido(
            mundo, "PED-2026-0804", S.ENTREGADO, creado=HOY - timedelta(days=30)
        )
        activo = _pedido(mundo, "PED-2026-0909", S.ESPERANDO_ANTICIPO)
        ctx = mundo.resolver_contexto(mundo.contexto(CONV))

        assert ctx.operativo.ids_activos == {activo.id}
        assert ctx.operativo.cerrados == 1
        assert cerrado.codigo not in ctx.operativo.resumen_para_modelo()

    def test_el_modelo_recibe_el_estado_pero_nunca_el_pedido_cerrado(self, mundo):
        cerrado = _pedido(
            mundo, "PED-2026-0805", S.ENTREGADO, creado=HOY - timedelta(days=30)
        )
        _pedido(mundo, "PED-2026-0910", S.ESPERANDO_ANTICIPO)
        basico = Modelo(
            Interpretacion(acto=Acto.CONVERSAR, confianza="ALTA"), contexto=True
        )
        _bot(mundo, basico=basico).ejecutar(CONV, "jajaja bueno dejame pensarlo")

        assert basico.visto, "esta frase sí necesitaba al modelo"
        mandado = basico.visto[0]
        assert "pedidos activos: 1" in mandado
        assert cerrado.codigo not in mandado and cerrado.id not in mandado
        assert "573001112233" not in mandado

    def test_un_modelo_sin_contexto_recibe_solo_el_texto(self, mundo):
        _pedido(mundo, "PED-2026-0911", S.ESPERANDO_ANTICIPO)
        basico = Modelo(Interpretacion(acto=Acto.CONVERSAR, confianza="ALTA"))
        _bot(mundo, basico=basico).ejecutar(CONV, "jajaja bueno dejame pensarlo")
        assert basico.visto == ["jajaja bueno dejame pensarlo"]

    def test_los_procesos_de_un_pedido_activo_no_caducan(self):
        viejo = Proceso(
            tipo=TipoProceso.COMPRA,
            pedido_id="vivo",
            tocado=HOY - timedelta(days=40),
            creado=HOY - timedelta(days=40),
        )
        suelto = Proceso(tipo=TipoProceso.COMPRA, tocado=HOY - timedelta(days=40))
        ctx = ContextoConversacional(conversation_id=CONV, procesos=[viejo, suelto])
        saneado = sanear(ctx, cerrados=set(), activos={"vivo"})
        assert [p.id for p in saneado.contexto.procesos] == [viejo.id]


# ═══════════════════════════════════════════════════════════════════════════
# LA CONVERSACIÓN REAL CON EL NÚMERO DE PRUEBA DE META
# ═══════════════════════════════════════════════════════════════════════════


#: Textual, de la conversación con el número de prueba de Meta.
MONTAR_AZUL = (
    "Gracias mientras me llegas me puedes montar como quedaría uno completamente azul ?"
)


class TestLaConversacionDePruebaConMeta:
    @pytest.fixture
    def despachado(self, mundo):
        pedido = _pedido(mundo, "PED-2026-4826", S.DESPACHADO)
        _guardar_ctx(
            mundo,
            procesos=[_compra_de(pedido)],
            foco_tipo="PEDIDO",
            foco_id=pedido.id,
        )
        return pedido

    def test_montar_uno_azul_NO_cambia_el_pedido_despachado(self, mundo, despachado):
        turno = _bot(mundo).ejecutar(
            CONV,
            MONTAR_AZUL,
        )
        colores = mundo.pedido(despachado.id).items[0].personalizacion.huellitas
        assert colores[0].corazon is ColorCircon.ROSADO
        assert "lo cambié" not in turno.respuesta.texto_plano.lower()

    def test_comencemos_de_cero_empieza_de_verdad_de_cero(self, mundo, despachado):
        bot = _bot(mundo)
        bot.ejecutar(
            CONV,
            MONTAR_AZUL,
        )
        turno = bot.ejecutar(CONV, "Okey quiero hacer uno diferente comencemos de 0")
        texto = turno.respuesta.texto_plano
        assert "PED-2026-4826" not in texto
        assert "Sonia" not in texto
        assert turno.decision.accion is Accion.INICIAR_COMPRA

    def test_el_grabado_no_se_come_la_palabra_color(self):
        nombres, _ = leer_grabado("No ahorita quiero nombre Roberto y color rosado todo")
        assert nombres == ["Roberto"]

    def test_cambio_la_direccion_se_lee(self):
        datos = leer_datos("Cambio la dirección a calle 18a #29 30 Girón")
        assert datos.direccion == "calle 18a #29 30 Girón"

    def test_cambiar_la_direccion_de_un_despachado_pasa_a_una_persona(
        self, mundo, despachado
    ):
        turno = _bot(mundo).ejecutar(CONV, "Cambio la dirección a calle 18a #29 30 Girón")
        assert mundo.pedido(despachado.id).envio.direccion == ""
        assert turno.respuesta.escalar
        assert "10 a 15 días" not in turno.respuesta.texto_plano

    def test_el_despachado_no_debe_nada(self, mundo, despachado):
        turno = _bot(mundo).ejecutar(CONV, "como va mi pedido")
        texto = turno.respuesta.texto_plano
        assert "te queda por pagar $0" in texto
        assert "te queda por pagar $200.000" not in texto

    def test_cuantos_pedidos_he_hecho_los_lista_todos(self, mundo, despachado):
        _pedido(mundo, "PED-2026-0001", S.ENTREGADO, creado=HOY - timedelta(days=90))
        turno = _bot(mundo).ejecutar(
            CONV, "Cuantos pedidos he hecho y en que vamos dame un resumen"
        )
        texto = turno.respuesta.texto_plano
        assert turno.decision.accion is Accion.CONSULTAR_HISTORIAL
        assert "PED-2026-4826" in texto and "PED-2026-0001" in texto

    def test_una_compra_de_pruebas_anteriores_se_avisa_al_retomarla(self, mundo):
        """«Me gustaría pedir 1» completaba en silencio un anillo de otro día."""
        vieja = Proceso(
            tipo=TipoProceso.COMPRA,
            datos={
                "colores": [{"corazon": "ROJO", "dedos": "ROJO"}],
                "grabados": ["Sonia", "Roberto"],
                "talla": 8,
            },
            faltan=["huellitas"],
            tocado=HOY - timedelta(hours=2),
        )
        _guardar_ctx(mundo, procesos=[vieja], ultima_clave="accion:MOSTRAR_PRODUCTO")
        # Así lo leyó Haiku en la conversación real: una compra.
        basico = Modelo(Interpretacion(acto=Acto.COMPRAR, entidad=Entidad.PRODUCTO))
        turno = _bot(mundo, basico=basico).ejecutar(CONV, "Me gustaría pedir 1")
        assert "Retomo el anillo" in turno.respuesta.texto_plano
        assert "empecemos de cero" in turno.respuesta.texto_plano


# ═══════════════════════════════════════════════════════════════════════════
# ROUTING: POR MOTIVO, NO POR NÚMERO DE MENSAJES
# ═══════════════════════════════════════════════════════════════════════════


class TestElRouting:
    def test_confianza_alta_del_basico_no_escala(self, mundo):
        basico = Modelo(Interpretacion(acto=Acto.CONVERSAR, confianza="ALTA"))
        fuerte = Modelo()
        turno = _bot(mundo, basico=basico, fuerte=fuerte).ejecutar(
            CONV, "jajaja que cosa"
        )
        assert basico.visto and not fuerte.visto
        assert turno.registro.routing_layer == "basico"

    def test_confianza_baja_escala_con_motivo(self, mundo):
        basico = Modelo(
            Interpretacion(
                acto=Acto.CONSULTAR, entidad=Entidad.PRODUCTO, confianza="BAJA"
            )
        )
        fuerte = Modelo(
            Interpretacion(acto=Acto.CONSULTAR, entidad=Entidad.IMAGEN, confianza="ALTA")
        )
        turno = _bot(mundo, basico=basico, fuerte=fuerte).ejecutar(
            CONV, "y eso como seria"
        )
        assert fuerte.visto
        assert turno.registro.routing_layer == "fuerte"
        assert turno.registro.escalation_reason == "confianza_baja"
        assert turno.decision.accion is Accion.MOSTRAR_IMAGENES

    def test_si_el_potente_tambien_duda_se_queda_la_primera_lectura(self, mundo):
        basico = Modelo(
            Interpretacion(
                acto=Acto.CONSULTAR, entidad=Entidad.PRODUCTO, confianza="BAJA"
            )
        )
        fuerte = Modelo(
            Interpretacion(acto=Acto.CONSULTAR, entidad=Entidad.IMAGEN, confianza="BAJA")
        )
        turno = _bot(mundo, basico=basico, fuerte=fuerte).ejecutar(
            CONV, "y eso como seria"
        )
        assert turno.decision.accion is Accion.MOSTRAR_PRODUCTO
        assert "sin_mejora" in turno.registro.escalation_reason

    def test_una_accion_sensible_sin_confianza_alta_escala(self, mundo):
        _pedido(mundo, "PED-2026-0912", S.ESPERANDO_ANTICIPO)
        basico = Modelo(
            Interpretacion(acto=Acto.CANCELAR, entidad=Entidad.PEDIDO, confianza="MEDIA")
        )
        fuerte = Modelo(Interpretacion(acto=Acto.CONVERSAR, confianza="ALTA"))
        turno = _bot(mundo, basico=basico, fuerte=fuerte).ejecutar(
            CONV, "mejor lo dejamos asi"
        )
        assert fuerte.visto
        assert turno.registro.escalation_reason == "accion_sensible"
        assert turno.decision.accion is Accion.CHARLAR

    def test_si_python_corrigio_al_modelo_no_se_escala(self, mundo):
        """La corrección es un hecho de la frase; el potente no lo ve mejor."""
        basico = Modelo(Interpretacion(acto=Acto.HUMANO, confianza="BAJA"))
        fuerte = Modelo(Interpretacion(acto=Acto.CONVERSAR, confianza="ALTA"))
        turno = _bot(mundo, basico=basico, fuerte=fuerte).ejecutar(
            CONV, "quiero uno de 2 huellitas"
        )
        assert turno.interpretacion.datos.huellitas == 2
        assert not fuerte.visto
        assert turno.registro.corrected

    def test_el_potente_puede_entrar_en_el_primer_mensaje(self, mundo):
        fuerte = Modelo(
            Interpretacion(acto=Acto.COMPRAR, entidad=Entidad.PRODUCTO, confianza="ALTA")
        )
        turno = _bot(mundo, fuerte=fuerte).ejecutar(
            CONV, "regalo para mi mamá, algo bonito"
        )
        assert turno.registro.routing_layer == "fuerte"
        assert turno.registro.escalation_reason == "sin_entender"

    def test_el_registro_no_guarda_datos_personales(self, mundo):
        turno = _bot(mundo).ejecutar(CONV, "Cambio la dirección a calle 18a #29 30 Girón")
        linea = turno.registro.linea()
        assert "573001112233" not in linea
        assert "calle 18a" not in linea


# ═══════════════════════════════════════════════════════════════════════════
# PIEZAS PURAS
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.parametrize(
    "frase",
    [
        "¿Qué pasó con mi pedido anterior?",
        "¿Cuándo enviaron el pedido de agosto?",
        "El pedido que hice el mes pasado",
        "El de la huella de perro que compré antes",
        "¿Me puedes decir qué talla había pedido la vez pasada?",
        "El otro pedido",
        "Cuantos pedidos he hecho",
        "mi pedido PED-2026-0417",
    ],
)
def test_se_reconoce_una_referencia_historica(frase):
    assert es_referencia_historica(frase)


@pytest.mark.parametrize(
    "frase",
    [
        "Hola",
        "Cuánto cuesta el anillo?",
        "Ya te mandé la foto",
        "Quiero cambiar la talla",
        "que me llegue en diciembre porfa",
        "corazón lila y dedos morados",
        "ya pagué",
    ],
)
def test_no_se_confunde_con_el_presente(frase):
    assert not es_referencia_historica(frase)


def test_el_mes_se_lee_con_su_anio():
    filtro = leer_filtro("el pedido de agosto", hoy=datetime(2026, 9, 14, tzinfo=UTC))
    assert filtro.meses == [8]
    filtro = leer_filtro(
        "lo que pedí en noviembre", hoy=datetime(2026, 9, 14, tzinfo=UTC)
    )
    assert filtro.meses == [11]


def test_buscar_por_mes_no_confunde_anios():
    class P:
        def __init__(self, i, creado):
            self.id, self.codigo, self.created_at, self.items, self.envio = (
                i,
                f"PED-{i}",
                creado,
                [],
                None,
            )

    hoy = datetime(2026, 9, 14, tzinfo=UTC)
    este = P("a", datetime(2026, 8, 3, tzinfo=UTC))
    otro = P("b", datetime(2025, 8, 3, tzinfo=UTC))
    r = buscar([este, otro], FiltroHistorico(meses=[8]), hoy=hoy)
    assert r.candidatos == [este]


@pytest.mark.parametrize(
    ("estado", "campos", "sobrescribe", "esperado"),
    [
        (S.ESPERANDO_ANTICIPO, {"colores"}, set(), Permiso.APLICAR),
        (S.ANTICIPO_PAGADO, {"colores"}, {"colores"}, Permiso.APLICAR_Y_REVISAR),
        (S.EN_PRODUCCION, {"talla"}, set(), Permiso.APLICAR_Y_REVISAR),
        (S.EN_PRODUCCION, {"talla"}, {"talla"}, Permiso.PEDIR_A_PERSONA),
        (S.EN_PRODUCCION, {"colores"}, {"colores"}, Permiso.PEDIR_A_PERSONA),
        # Los datos de la GUÍA con el anillo ya hecho: es justo lo que el
        # sistema le acaba de pedir con las fotos (ADR 0020), así que se
        # escriben sin molestar a nadie. El 20/09 se rechazaban enteros y la
        # conversación se escalaba con el anillo listo y pagado.
        (S.PRODUCCION_LISTA, {"direccion"}, {"direccion"}, Permiso.APLICAR),
        (S.ESPERANDO_SALDO, {"cedula", "ciudad", "direccion"}, set(), Permiso.APLICAR),
        (S.ESPERANDO_SALDO, {"celular"}, set(), Permiso.APLICAR),
        (S.SALDO_PAGADO, {"nombre", "cedula"}, set(), Permiso.APLICAR),
        # Pero el ANILLO no se toca con el anillo hecho.
        (S.ESPERANDO_SALDO, {"colores"}, set(), Permiso.PEDIR_A_PERSONA),
        (S.ESPERANDO_SALDO, {"direccion", "talla"}, set(), Permiso.PEDIR_A_PERSONA),
        # Y una vez despachado, la guía ya está impresa.
        (S.DESPACHADO, {"direccion"}, {"direccion"}, Permiso.PEDIR_A_PERSONA),
        (S.DESPACHADO, {"cedula"}, set(), Permiso.PEDIR_A_PERSONA),
        # En el taller, los datos de la guía sí, y la talla que faltaba también.
        (S.EN_PRODUCCION, {"cedula", "celular"}, set(), Permiso.APLICAR_Y_REVISAR),
        (S.ENTREGADO, {"talla"}, set(), Permiso.NUNCA),
        (S.CANCELADO, set(), set(), Permiso.NUNCA),
    ],
)
def test_la_politica_de_cambios(estado, campos, sobrescribe, esperado):
    assert permiso(estado, campos, sobrescribe=sobrescribe) is esperado


def test_lo_pendiente_de_pago_sale_del_estado_confirmado(mundo):
    assert pendiente_de_pago(_pedido(mundo, "PED-1", S.DESPACHADO)) == 0
    assert pendiente_de_pago(_pedido(mundo, "PED-2", S.EN_PRODUCCION)) == 140_000
    assert pendiente_de_pago(_pedido(mundo, "PED-3", S.ESPERANDO_ANTICIPO)) == 200_000


def test_el_costo_de_una_llamada_se_calcula_con_la_cache():
    consumo.abrir_turno()
    with consumo.capa("basico"):
        consumo.registrar(
            "claude-haiku-4-5", entrada=20, salida=50, cache_leida=4700, ms=1800
        )
    gasto = consumo.actual()
    assert gasto.llamadas[0].capa == "basico"
    # 20*1 + 4700*0.1 + 50*5 = 740 por millón
    assert gasto.usd == pytest.approx(740 / 1_000_000)


def test_las_metricas_salen_del_registro(tmp_path):
    from app.adapters.repositories.sqlite_store import SqliteDB, SqliteDecisiones
    from app.domain.decisiones import RegistroDeDecision

    registro = SqliteDecisiones(SqliteDB(tmp_path / "m.db"))

    def fila(capa, **kw):
        base = dict(
            ts=HOY.isoformat(),
            conversacion="abc",
            routing_layer=capa,
            motivo="",
            escalated=capa == "fuerte",
            escalation_reason="",
            intent="",
            action="",
            verdict="",
            confidence="",
            context_source="",
            active_orders=0,
            closed_orders=0,
            historical_lookup=False,
            candidate_orders=0,
            human_review=False,
            image="",
            corrected=False,
            model_said="",
        )
        base.update(kw)
        return RegistroDeDecision(**base)

    registro.guardar(fila("reglas", latency_ms=5))
    registro.guardar(fila("reglas", latency_ms=7, historical_lookup=True))
    registro.guardar(fila("basico", latency_ms=1900, cost_usd=0.001))
    registro.guardar(fila("fuerte", latency_ms=2500, cost_usd=0.004, corrected=True))
    m = registro.metricas()
    assert m["turnos"] == 4
    assert m["sin_ia_pct"] == 50.0
    assert m["basico_pct"] == 25.0 and m["potente_pct"] == 25.0
    assert m["escaladas"] == 1 and m["consultas_historicas"] == 1
    assert m["acciones_corregidas"] == 1
    assert m["costo_total_usd"] == pytest.approx(0.005)


def test_el_saludo_y_la_pregunta_del_modelo_no_tienen_atributo_historial_raro():
    """Interpretación con HISTORIAL del modelo -> Python llena el filtro."""
    i = Interpretacion(
        acto=Acto.CONSULTAR, entidad=Entidad.PEDIDO, atributo=Atributo.HISTORIAL
    )
    assert i.historial is None  # lo llena el intérprete, no el modelo
