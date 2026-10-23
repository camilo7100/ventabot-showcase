"""El lector de imágenes, de punta a punta y sin modelo de visión de verdad.

La regla que se prueba aquí es una sola, y es la que pidió el negocio:

    Si se entiende con seguridad -> se guarda.
    Si no -> se guarda LO QUE SE VIO, se marca para que lo mire una
    persona, y la conversación SIGUE.

Nunca se bloquea y nunca se inventa. El modelo de visión es un doble que
devuelve lo que se le ponga: lo que se está midiendo es la POLÍTICA, no la
puntería del modelo — eso se mide con fotos reales, no con tests.
"""

from __future__ import annotations

import pytest

from app.adapters.repositories.memory import (
    InMemoryCustomerRepository,
    InMemoryOrderRepository,
)
from app.conversacion.ejecutor import Ejecutor
from app.conversacion.interprete import Interprete
from app.conversacion.mundo import Mundo
from app.conversacion.ojos import Ojos
from app.conversacion.pipeline import Pipeline
from app.conversacion.redactor import Redactor
from app.domain.acciones import Accion
from app.domain.contexto import TipoProceso
from app.domain.models import Channel, Customer
from app.domain.order_state import OrderState
from app.domain.personalizacion import ColorCircon
from app.domain.vision import LecturaDeImagen, TipoDeImagen
from tests.unit.test_inteligencia_conversacional import (
    CONV,
    ContextoEnMemoria,
    ModeloDeMadera,
    _productos,
)

FOTO = [{"kind": "image", "media_id": "wamid-foto"}]


class VisionFalsa:
    """Devuelve la lectura que le pongas. Es el modelo, sin el modelo."""

    def __init__(self, lectura: LecturaDeImagen | None = None) -> None:
        self.lectura = lectura or LecturaDeImagen()
        self.pistas: list[str] = []

    def leer(self, imagen: bytes, *, pista: str = "") -> LecturaDeImagen:
        self.pistas.append(pista)
        return self.lectura


class MediaFalsa:
    def download(self, referencia: str) -> bytes:
        return b"\xff\xd8\xff\xe0jpeg-de-mentira"

    def store(self, data: bytes, *, filename: str) -> str:
        return f"/tmp/{filename}"


def _armar(vision=None, media=None):
    customers = InMemoryCustomerRepository()
    customers.upsert(
        Customer(id="c1", channel=Channel.WHATSAPP, channel_user_id="573001112233")
    )
    mundo = Mundo(InMemoryOrderRepository(), customers, _productos(), ContextoEnMemoria())
    interprete = Interprete(
        ModeloDeMadera(),
        prompt="",
        catalogo_txt="",
        ojos=Ojos(vision=vision, media=media),
    )
    return Pipeline(interprete, mundo, Ejecutor(mundo), Redactor()), mundo


def hablar(bot, *mensajes):
    return [bot.ejecutar(CONV, m).respuesta.texto_plano for m in mensajes]


def _hasta_la_talla(bot):
    """Deja la compra esperando ÚNICAMENTE la talla."""
    hablar(bot, "quiero un anillo de 1 huellita", "corazón lila y dedos morados")
    hablar(bot, "carmen")


def _envio(bot):
    """Los datos de envío. Sin ellos ya no nace ningún pedido."""
    hablar(bot, "Carlos Pérez", "Bucaramanga", "Calle 45 #12-30")


def _pedido_completo(bot):
    """Todo lo que hay que preguntar antes de que exista un pedido.

    Incluye los datos de envío: el bot ya no nombra el abono hasta que no le
    queda nada por preguntar.
    """
    _hasta_la_talla(bot)
    hablar(bot, "talla 8")
    _envio(bot)


# ═══════════════════════════════════════════════════════════════════════════
# LA TALLA, DESDE LA FOTO
# ═══════════════════════════════════════════════════════════════════════════


class TestAnilloConRegla:
    def test_una_foto_clara_da_la_talla_y_cierra_la_compra(self):
        vision = VisionFalsa(
            LecturaDeImagen(
                tipo=TipoDeImagen.ANILLO_CON_REGLA,
                seguro=True,
                diametro_mm=18.2,
                foto_clara=True,
            )
        )
        bot, mundo = _armar(vision, MediaFalsa())
        _hasta_la_talla(bot)

        turno = bot.ejecutar(CONV, None, FOTO)
        _envio(bot)

        pedidos = mundo.pedidos_de(CONV)
        assert len(pedidos) == 1
        personalizacion = pedidos[0].items[0].personalizacion
        assert personalizacion.talla == 8.0
        assert "talla 8" in turno.respuesta.texto_plano.lower()

    def test_la_talla_de_una_foto_SIEMPRE_se_confirma(self):
        """Aunque el modelo jure que está seguro.

        Midiendo con fotos reales dijo «seguro» y «foto clara» en todas,
        incluidas las que leyó mal. Su autoconfianza es el único número que
        no puede calibrar, y aquí equivocarse cuesta el anillo entero.
        """
        vision = VisionFalsa(
            LecturaDeImagen(
                tipo=TipoDeImagen.ANILLO_CON_REGLA,
                seguro=True,
                diametro_mm=18.2,
                foto_clara=True,
            )
        )
        bot, mundo = _armar(vision, MediaFalsa())
        _hasta_la_talla(bot)
        turno = bot.ejecutar(CONV, None, FOTO)
        _envio(bot)

        assert mundo.pedidos_de(CONV)[0].items[0].personalizacion.talla_revisar is True
        assert any("CONFIRMAR" in nota for nota in turno.contexto.revisar)

    def test_si_la_regla_venia_en_centimetros_se_convierte(self):
        """El modelo lee «1.82» de una regla impresa en cm. Antes se perdía
        la lectura entera por un error de unidad."""
        vision = VisionFalsa(
            LecturaDeImagen(
                tipo=TipoDeImagen.ANILLO_CON_REGLA,
                seguro=True,
                diametro_mm=1.82,
                foto_clara=True,
            )
        )
        bot, mundo = _armar(vision, MediaFalsa())
        _hasta_la_talla(bot)
        bot.ejecutar(CONV, None, FOTO)
        _envio(bot)
        assert mundo.pedidos_de(CONV)[0].items[0].personalizacion.talla == 8.0

    def test_una_foto_dudosa_TAMBIEN_da_talla_pero_marcada(self):
        vision = VisionFalsa(
            LecturaDeImagen(
                tipo=TipoDeImagen.ANILLO_CON_REGLA,
                seguro=True,
                diametro_mm=18.2,
                foto_clara=False,
            )
        )
        bot, mundo = _armar(vision, MediaFalsa())
        _hasta_la_talla(bot)
        turno = bot.ejecutar(CONV, None, FOTO)
        _envio(bot)

        personalizacion = mundo.pedidos_de(CONV)[0].items[0].personalizacion
        assert personalizacion.talla == 8.0, "se bloqueó en vez de seguir"
        assert personalizacion.talla_revisar is True
        assert any("CONFIRMAR" in nota for nota in turno.contexto.revisar)
        # A la clienta NO se le cuenta que dudamos: eso es del taller.
        assert "confirmar" not in turno.respuesta.texto_plano.lower()

    def test_una_medida_imposible_no_para_la_conversacion(self):
        vision = VisionFalsa(
            LecturaDeImagen(
                tipo=TipoDeImagen.ANILLO_CON_REGLA,
                seguro=True,
                diametro_mm=35.0,  # eso no es un dedo
                foto_clara=True,
            )
        )
        bot, _mundo = _armar(vision, MediaFalsa())
        _hasta_la_talla(bot)
        turno = bot.ejecutar(CONV, None, FOTO)

        assert turno.respuesta.texto_plano, "se quedó mudo"
        assert any("CONFIRMAR" in nota for nota in turno.contexto.revisar)

    def test_sin_medida_legible_se_pide_revision_y_se_sigue(self):
        vision = VisionFalsa(
            LecturaDeImagen(tipo=TipoDeImagen.ANILLO_CON_REGLA, seguro=False)
        )
        bot, mundo = _armar(vision, MediaFalsa())
        _hasta_la_talla(bot)
        turno = bot.ejecutar(CONV, None, FOTO)

        assert not mundo.pedidos_de(CONV)
        assert any("a mano" in nota for nota in turno.contexto.revisar)
        assert "foto" in turno.respuesta.texto_plano.lower()

    def test_lo_que_ella_escribe_gana_sobre_lo_que_dice_la_foto(self):
        vision = VisionFalsa(
            LecturaDeImagen(
                tipo=TipoDeImagen.ANILLO_CON_REGLA,
                seguro=True,
                diametro_mm=15.7,  # talla 5
                foto_clara=True,
            )
        )
        bot, mundo = _armar(vision, MediaFalsa())
        _hasta_la_talla(bot)
        bot.ejecutar(CONV, "mi talla es 8", FOTO)
        _envio(bot)

        assert mundo.pedidos_de(CONV)[0].items[0].personalizacion.talla == 8.0


# ═══════════════════════════════════════════════════════════════════════════
# EL COMPROBANTE
# ═══════════════════════════════════════════════════════════════════════════


class TestComprobante:
    def _con_pedido(self):
        vision = VisionFalsa(
            LecturaDeImagen(
                tipo=TipoDeImagen.COMPROBANTE,
                seguro=True,
                monto_cop=60_000,
                banco="Nequi",
            )
        )
        bot, mundo = _armar(vision, MediaFalsa())
        _pedido_completo(bot)
        return bot, mundo

    def test_se_acusa_recibo_y_no_se_vuelve_a_pedir(self):
        bot, _ = self._con_pedido()
        turno = bot.ejecutar(CONV, None, FOTO)

        assert turno.decision.accion is Accion.RECIBIR_COMPROBANTE
        texto = turno.respuesta.texto_plano.lower()
        assert "comprobante" in texto
        assert "¿me compartes" not in texto, "lo volvió a pedir"

    def test_el_pedido_queda_pendiente_de_validar_NUNCA_pagado(self):
        bot, mundo = self._con_pedido()
        bot.ejecutar(CONV, None, FOTO)

        pedido = mundo.pedidos_de(CONV)[0]
        assert pedido.estado == OrderState.EN_REVISION_PAGO.value
        assert pedido.anticipo_pagado_cop == 0

    def test_lo_que_se_leyo_queda_apuntado_para_quien_verifique(self):
        bot, _ = self._con_pedido()
        turno = bot.ejecutar(CONV, None, FOTO)
        notas = " ".join(turno.contexto.revisar)
        assert "60.000" in notas and "Nequi" in notas

    def test_queda_constancia_del_pago_reportado(self):
        bot, _ = self._con_pedido()
        turno = bot.ejecutar(CONV, None, FOTO)
        assert any(
            p.tipo is TipoProceso.PAGO_REPORTADO for p in turno.contexto.abiertos()
        )


# ═══════════════════════════════════════════════════════════════════════════
# LOS COLORES SEÑALADOS EN EL MUESTRARIO
# ═══════════════════════════════════════════════════════════════════════════


class TestCircones:
    def test_lo_que_cree_ver_se_PREGUNTA_no_se_guarda(self):
        """Ni con marca ni con seguridad se escribe un color en el pedido.

        Con las fotos reales del muestrario —sin nada señalado— el modelo
        contestó «seguro» y se inventó dos colores, tres veces de tres. Lo
        que ve entra en la pregunta, no en el anillo.
        """
        vision = VisionFalsa(
            LecturaDeImagen(
                tipo=TipoDeImagen.CIRCONES_SENALADOS,
                seguro=True,
                hay_marca=True,
                color_corazon=ColorCircon.LILA,
                color_dedos=ColorCircon.MORADO,
            )
        )
        bot, _mundo = _armar(vision, MediaFalsa())
        hablar(bot, "quiero un anillo de 1 huellita")
        turno = bot.ejecutar(CONV, None, FOTO)

        proceso = turno.contexto.abiertos(TipoProceso.COMPRA)[0]
        assert not proceso.datos.get("colores"), "escribió un color sacado de una foto"
        texto = turno.respuesta.texto_plano.lower()
        assert "lila" in texto and "morado" in texto, "perdió lo que había visto"
        assert any("parecía señalar" in nota for nota in turno.contexto.revisar)

    def test_y_luego_ella_lo_escribe_y_ENTONCES_si_se_guarda(self):
        vision = VisionFalsa(
            LecturaDeImagen(
                tipo=TipoDeImagen.CIRCONES_SENALADOS,
                seguro=True,
                hay_marca=True,
                color_corazon=ColorCircon.LILA,
                color_dedos=ColorCircon.MORADO,
            )
        )
        bot, _mundo = _armar(vision, MediaFalsa())
        hablar(bot, "quiero un anillo de 1 huellita")
        bot.ejecutar(CONV, None, FOTO)
        turno = bot.ejecutar(CONV, "corazón lila y dedos morados")

        proceso = turno.contexto.abiertos(TipoProceso.COMPRA)[0]
        assert proceso.datos["colores"] == [{"corazon": "LILA", "dedos": "MORADO"}]

    def test_sin_marca_en_la_foto_ni_se_menciona_un_color(self):
        """Las bolsitas del muestrario a secas no son una elección."""
        vision = VisionFalsa(
            LecturaDeImagen(
                tipo=TipoDeImagen.CIRCONES_SENALADOS,
                seguro=True,
                hay_marca=False,
                color_corazon=ColorCircon.LILA,
                color_dedos=ColorCircon.MORADO,
            )
        )
        bot, _mundo = _armar(vision, MediaFalsa())
        hablar(bot, "quiero un anillo de 1 huellita")
        turno = bot.ejecutar(CONV, None, FOTO)

        proceso = turno.contexto.abiertos(TipoProceso.COMPRA)[0]
        assert not proceso.datos.get("colores")
        # No le dice «me parece que señalaste el lila»: no señaló nada.
        # (El ejemplo de la pregunta sí nombra colores; por eso se mira la
        # frase concreta y no la palabra suelta.)
        assert "me parece que señalaste" not in turno.respuesta.texto_plano.lower()
        # …y le pregunta a ella, en vez de quedarse callado.
        assert "color" in turno.respuesta.texto_plano.lower()


# ═══════════════════════════════════════════════════════════════════════════
# LO QUE NO SE PUEDE APROVECHAR
# ═══════════════════════════════════════════════════════════════════════════


class TestFotosQueNoAportan:
    def test_la_foto_del_peludito_se_celebra_y_se_sigue(self):
        vision = VisionFalsa(
            LecturaDeImagen(tipo=TipoDeImagen.MASCOTA, seguro=True, descripcion="un gato")
        )
        bot, _ = _armar(vision, MediaFalsa())
        hablar(bot, "quiero un anillo de 1 huellita")
        turno = bot.ejecutar(CONV, None, FOTO)

        texto = turno.respuesta.texto_plano
        assert "belleza" in texto.lower()
        # y no se olvida de lo que estaba preguntando
        assert "color" in texto.lower()

    def test_sin_lector_configurado_se_marca_y_no_se_rompe_nada(self):
        bot, _ = _armar(vision=None, media=None)
        hablar(bot, "quiero un anillo de 1 huellita")
        turno = bot.ejecutar(CONV, None, FOTO)

        assert turno.respuesta.texto_plano
        assert any("ábrela tú" in nota for nota in turno.contexto.revisar)

    def test_una_nota_no_se_apunta_dos_veces(self):
        bot, _ = _armar(vision=None, media=None)
        hablar(bot, "quiero un anillo de 1 huellita")
        bot.ejecutar(CONV, None, FOTO)
        turno = bot.ejecutar(CONV, None, FOTO)
        assert len(turno.contexto.revisar) == 1


# ═══════════════════════════════════════════════════════════════════════════
# LA PISTA: MIRAR BUSCANDO ALGO
# ═══════════════════════════════════════════════════════════════════════════


class TestLaPista:
    def test_se_le_dice_al_lector_que_estabamos_esperando(self):
        vision = VisionFalsa(LecturaDeImagen(tipo=TipoDeImagen.OTRA))
        bot, _ = _armar(vision, MediaFalsa())
        _hasta_la_talla(bot)
        bot.ejecutar(CONV, None, FOTO)
        assert vision.pistas[-1] == "talla"

    def test_si_esperamos_el_comprobante_esa_es_la_pista(self):
        vision = VisionFalsa(LecturaDeImagen(tipo=TipoDeImagen.OTRA))
        bot, _ = _armar(vision, MediaFalsa())
        _pedido_completo(bot)
        hablar(bot, "ya pagué")
        bot.ejecutar(CONV, None, FOTO)
        assert vision.pistas[-1] == "comprobante"


@pytest.mark.parametrize(
    "tipo",
    [t for t in TipoDeImagen],
)
def test_ningun_tipo_de_foto_deja_al_bot_mudo(tipo):
    """Sea lo que sea que mande, siempre hay respuesta."""
    vision = VisionFalsa(LecturaDeImagen(tipo=tipo, seguro=True))
    bot, _ = _armar(vision, MediaFalsa())
    hablar(bot, "quiero un anillo de 1 huellita")
    turno = bot.ejecutar(CONV, None, FOTO)
    assert turno.respuesta.texto_plano.strip()
