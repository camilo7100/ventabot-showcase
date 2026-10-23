"""Pagar el envío por adelantado: con el SALDO, nunca con el abono.

════════════════════════════════════════════════════════════════════════════
LO QUE PASÓ (Camilo probando, 21/09)
════════════════════════════════════════════════════════════════════════════
Con las cuentas del abono ya mandadas:

    clienta: Puedo pagar el envío ? Es que a veces no estoy en casa
    bot:     Lo coordinas directamente con el transportista…   + «¡Recibido! 🙌»
    clienta: Yo quiero pagarlo antes porque nunca estoy en casa pa q me lo
             dejen en portería
    bot:     ¿Transfieres los $60.000 del abono + los $18.000 del envío en una
             sola transferencia, o los haces por separado?
    clienta: Yo los pago cuando esté listo el anillo
    clienta: ok
    bot:     Tu pedido entra al taller ahora mismo. En 10 a 15 días te
             comparto las fotos…                        ← SIN abono pagado
    clienta: ok
    bot:     (las cuentas otra vez) «…ese valor lo puedes cancelar al recibir
             tu anillo»                                 ← lo contrario de lo acordado

La regla de negocio: lo normal —y lo que se dice sin que pregunte— es pagar
el envío al recibir. Si ELLA pide pagarlo antes, se puede: va JUNTO CON EL
SALDO, cuando el anillo está listo. Nunca con el abono, y el anillo entra al
taller solo con el abono.
"""

from __future__ import annotations

from typing import ClassVar

import pytest

from app.adapters.repositories.memory import (
    InMemoryCustomerRepository,
    InMemoryOrderRepository,
    InMemoryProductRepository,
)
from app.conversacion.mundo import Mundo
from app.domain.asesora import (
    AccionAsesora,
    Borrador,
    CambiosDelBorrador,
    acordar_envio,
    aplicar,
    vigilar,
)
from app.domain.guion import aviso, aviso_de_cierre
from app.domain.models import Channel, Customer, Product
from tests.unit import test_asesora as base
from tests.unit.test_asesora import (
    CONV,
    PERMITIDOS,
    ContextoEnMemoria,
    _jugada,
    abrir_conversacion,
)

PREGUNTA = "Puedo pagar el envío ? Es que a veces no estoy en casa"
LO_PIDE = (
    "Yo quiero pagarlo antes porque nunca estoy en casa pa q me lo dejen en portería"
)
CON_EL_SALDO = "junto con el saldo"
AL_RECIBIR = "cancelar al recibir"


@pytest.fixture
def mundo():
    """El mismo mundo de `test_asesora`, con la conversación ya empezada."""
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
    m = Mundo(InMemoryOrderRepository(), customers, productos, ContextoEnMemoria())
    abrir_conversacion(m)
    return m


def _pedido_creado(mundo, *jugadas):
    """Resumen confirmado y cuentas del abono ya mandadas (sin pagar)."""
    return base.TestTurno()._pedido_creado(mundo, *jugadas)


def _texto(t) -> str:
    return t.respuesta.texto_plano


def _pedido(mundo):
    return mundo.pedido(mundo.contexto(CONV).borrador["pedido_id"])


def _flete(mundo) -> str:
    """El envío que se cotiza a la ciudad de la prueba, escrito como en el chat."""
    from app.domain.pricing import formatear_cop

    return formatear_cop(mundo.envio_a("Bogotá"))


# ══════════════════════════════════════════════════════════════════════════
#  1. EL VIGILANTE: lo que no puede salir aunque el modelo lo escriba
# ══════════════════════════════════════════════════════════════════════════


class TestElVigilante:
    ESPERANDO_ABONO = Borrador(cuentas_enviadas=True, pedido_id="p1")

    def test_no_junta_el_envio_con_el_abono(self):
        """La frase exacta del 21/09."""
        mensaje = (
            "Perfecto, entendido 💓 El envío son $15.000. ¿Transfieres los "
            "$60.000 del abono + los $15.000 del envío en una sola "
            "transferencia, o los haces por separado?"
        )
        limpio, problemas = vigilar(
            mensaje, PERMITIDOS, self.ESPERANDO_ABONO, "ESPERANDO_ANTICIPO"
        )
        assert "abono +" not in limpio
        assert any(p.startswith("junta el envío con el abono") for p in problemas)

    def test_otras_formas_de_juntarlos_tampoco(self):
        for frase in (
            "Puedes pagar el envío ahora con el abono 💓",
            "Me transfieres el abono junto con el envío y listo",
            "Son $60.000 del abono más el envío",
            "Si quieres pagas el envío de una vez 🚚",
        ):
            limpio, problemas = vigilar(frase, PERMITIDOS, self.ESPERANDO_ABONO)
            assert problemas, frase
            assert limpio == "", frase

    def test_decir_cuando_se_paga_de_verdad_si_pasa(self):
        """No es juntarlos si la frase dice que el envío va con el saldo o al
        recibir: eso es justo lo que hay que decir."""
        for frase in (
            "El envío lo pagas junto con el saldo cuando tu anillo esté listo 🚚",
            "Por ahora el abono de $60.000 y el envío con el saldo 💓",
            "El abono es de $60.000 y el envío de $15.000 lo pagas al recibir",
        ):
            limpio, problemas = vigilar(frase, PERMITIDOS, self.ESPERANDO_ABONO)
            assert not problemas, (frase, problemas)
            assert limpio == frase

    def test_sin_abono_no_entra_al_taller(self):
        """«Tu pedido entra al taller ahora mismo» sin haber pagado nada."""
        mensaje = (
            "Listo 🙌 Tu pedido entra al taller ahora mismo. En 10 a 15 días te "
            "comparto las fotos de cómo quedó 💓"
        )
        limpio, problemas = vigilar(
            mensaje, PERMITIDOS, self.ESPERANDO_ABONO, "ESPERANDO_ANTICIPO"
        )
        assert "taller" not in limpio
        assert "10 a 15 días" not in limpio
        assert any(p.startswith("dice que el pedido entra al taller") for p in problemas)

    def test_otras_formas_de_darlo_por_arrancado(self):
        for frase in (
            "Ya empezamos a fabricarlo 💍",
            "Tu anillo pasa directo al taller 🫶",
            "Tu pedido queda para el taller hoy mismo",
        ):
            _, problemas = vigilar(
                frase, PERMITIDOS, self.ESPERANDO_ABONO, "ESPERANDO_ANTICIPO"
            )
            assert problemas, frase

    def test_como_condicion_si_se_puede_decir(self):
        """Es lo que hay que decirle: el abono es lo que lo hace entrar."""
        for frase in (
            "Apenas hagas el abono, tu pedido entra al taller 💓",
            "Cuando me mandes el comprobante del abono pasa al taller 🙌",
            "Con el abono empezamos a fabricarlo 💍",
            "Por ahora solo el abono de $60.000 para que tu anillo entre al taller 💓",
        ):
            limpio, problemas = vigilar(
                frase, PERMITIDOS, self.ESPERANDO_ABONO, "ESPERANDO_ANTICIPO"
            )
            assert not problemas, (frase, problemas)
            assert limpio == frase

    def test_con_el_abono_ya_verificado_si_entra_al_taller(self):
        verificado = Borrador(cuentas_enviadas=True, abono_reportado=True)
        limpio, problemas = vigilar(
            "Tu anillo entra al taller hoy 🥳", PERMITIDOS, verificado, "ANTICIPO_PAGADO"
        )
        assert not problemas and limpio


# ══════════════════════════════════════════════════════════════════════════
#  2. LO QUE SE GUARDA
# ══════════════════════════════════════════════════════════════════════════


class TestLoQueSeGuarda:
    def test_pedir_pagarlo_antes_queda_anotado(self):
        b, rechazos = acordar_envio(Borrador(), [AccionAsesora.ENVIO_CON_SALDO])
        assert b.envio_con_saldo and not rechazos

    def test_puede_volver_a_pagarlo_al_recibir(self):
        b, _ = acordar_envio(
            Borrador(envio_con_saldo=True), [AccionAsesora.ENVIO_AL_RECIBIR]
        )
        assert not b.envio_con_saldo

    def test_si_lo_recoge_no_hay_envio_que_pagar(self):
        b, rechazos = acordar_envio(
            Borrador(recoge=True), [AccionAsesora.ENVIO_CON_SALDO]
        )
        assert not b.envio_con_saldo and rechazos

    def test_cambiar_a_recoger_borra_el_envio_con_el_saldo(self):
        b, _ = aplicar(
            Borrador(envio_con_saldo=True), CambiosDelBorrador(recoge_en_tienda=True)
        )
        assert b.recoge and not b.envio_con_saldo

    def test_si_no_habla_del_envio_no_cambia_nada(self):
        b, _ = acordar_envio(
            Borrador(envio_con_saldo=True), [AccionAsesora.MOSTRAR_MUESTRARIO]
        )
        assert b.envio_con_saldo

    def test_no_es_un_campo_mas_del_esquema(self):
        """21/09: un campo opcional más en los cambios y Claude rechazó el
        esquema entero («Schema is too complex»): el bot se quedaba sin modelo.
        Cuándo paga el envío va como ACCIÓN, que no agranda el esquema."""
        assert "envio_con_saldo" not in CambiosDelBorrador.model_fields
        acciones = {a.value for a in AccionAsesora}
        assert {"ENVIO_CON_SALDO", "ENVIO_AL_RECIBIR"} <= acciones


# ══════════════════════════════════════════════════════════════════════════
#  3. LA CONVERSACIÓN DEL 21/09, TURNO POR TURNO
# ══════════════════════════════════════════════════════════════════════════


class TestLaConversacionDel21:
    def test_una_pregunta_no_recibe_recibido(self, mundo):
        """Preguntó por el envío y le llegó la respuesta y debajo «¡Recibido! 🙌»
        —como si hubiera pagado— porque el turno «no preguntaba nada»."""
        a = _pedido_creado(
            mundo,
            _jugada(
                "Claro, sin problema 💓 Lo coordinas directamente con el "
                "transportista cuando te llegue el anillo y listo 🚚"
            ),
        )
        t = a.ejecutar(CONV, PREGUNTA)
        assert "Recibido" not in _texto(t)
        assert _pedido(mundo).estado == "ESPERANDO_ANTICIPO"

    def test_pedirlo_antes_nunca_ofrece_juntarlo_con_el_abono(self, mundo):
        """El modelo lo ofreció junto con el abono: no sale, se reescribe."""
        a = _pedido_creado(
            mundo,
            _jugada(
                "Perfecto, entendido 💓 El envío son "
                + _flete(mundo)
                + ". ¿Transfieres los $60.000 del abono + los "
                + _flete(mundo)
                + " del envío en una sola transferencia, o los haces por separado?",
                AccionAsesora.ENVIO_CON_SALDO,
            ),
        )
        a._llm.reescrituras.append(
            "¡Claro! 💓 El envío lo pagas junto con el saldo cuando tu anillo "
            "esté listo, así te lo dejan en portería sin pagar nada al recibirlo"
        )
        t = a.ejecutar(CONV, LO_PIDE)
        texto = _texto(t)
        assert "abono +" not in texto and "sola transferencia" not in texto
        assert CON_EL_SALDO in texto
        # Se le explicó al modelo por qué se reescribía.
        assert "junta el envío con el abono" in a._llm.pedidas_de_reescritura[0]
        assert "JUNTO CON EL SALDO" in a._llm.pedidas_de_reescritura[0]

    def test_sin_reescritura_python_dice_lo_acordado(self, mundo):
        """Si la reescritura tampoco llega, lo acordado lo escribe Python —con
        el recordatorio de que el abono va primero— y no queda en el aire."""
        a = _pedido_creado(
            mundo,
            _jugada(
                "¿Me transfieres el abono junto con el envío de una vez? 💓",
                AccionAsesora.ENVIO_CON_SALDO,
            ),
        )
        t = a.ejecutar(CONV, LO_PIDE)
        texto = _texto(t)
        assert "junto con el envío" not in texto
        assert CON_EL_SALDO in texto
        assert "abono de $60.000 para que tu anillo entre al taller" in texto

    def test_queda_en_el_pedido_y_en_las_notas_de_lia(self, mundo):
        a = _pedido_creado(
            mundo,
            _jugada(
                "¡Claro! 💓 El envío lo pagas junto con el saldo cuando tu anillo "
                "esté listo 🚚",
                AccionAsesora.ENVIO_CON_SALDO,
            ),
        )
        t = a.ejecutar(CONV, LO_PIDE)
        assert _pedido(mundo).envio.envio_con_saldo
        # Lo dijo bien el modelo: Python no lo repite.
        assert _texto(t).count(CON_EL_SALDO) == 1
        revisar = " ".join(mundo.contexto(CONV).revisar)
        assert "ENVÍO junto con el SALDO" in revisar

    def test_no_da_el_pedido_por_entrado_al_taller_sin_abono(self, mundo):
        """«ok» → «Tu pedido entra al taller ahora mismo», sin abono."""
        a = _pedido_creado(
            mundo,
            _jugada("¡Claro! 💓", AccionAsesora.ENVIO_CON_SALDO),
            _jugada(
                "Listo 🙌 Tu pedido entra al taller ahora mismo. En 10 a 15 días "
                "te comparto las fotos de cómo quedó 💓"
            ),
        )
        a._llm.reescrituras.append(
            "¡Perfecto! 🙌 Apenas hagas el abono, tu anillo entra al taller 💓"
        )
        a.ejecutar(CONV, LO_PIDE)
        t = a.ejecutar(CONV, "ok")
        texto = _texto(t)
        assert "ahora mismo" not in texto
        assert "10 a 15 días" not in texto
        assert "Apenas hagas el abono" in texto
        assert _pedido(mundo).estado == "ESPERANDO_ANTICIPO"

    def test_sin_reescritura_le_dice_que_el_abono_va_primero(self, mundo):
        """Repaso del 21/09: el vigilante quitó «entra al taller» y, sin
        reescritura, quedaba «¡Dale! Quedo atenta al comprobante», que no le
        aclara nada a quien cree que paga todo cuando esté listo."""
        a = _pedido_creado(
            mundo,
            _jugada("¡Claro! 💓", AccionAsesora.ENVIO_CON_SALDO),
            _jugada("¡Listo! Ya empezamos a fabricar tu anillo 💍"),
        )
        a.ejecutar(CONV, LO_PIDE)
        t = a.ejecutar(CONV, "Yo los pago cuando esté listo el anillo")
        texto = _texto(t)
        assert "empezamos a fabricar" not in texto
        assert "Apenas hagas el abono de $60.000, tu anillo entra al taller" in texto
        assert "El saldo y el envío los pagas cuando esté listo" in texto

    def test_las_cuentas_ya_no_dicen_que_se_paga_al_recibir(self, mundo):
        """Las cuentas del abono, después de acordar el envío con el saldo."""
        a = _pedido_creado(
            mundo,
            _jugada("¡Claro! 💓", AccionAsesora.ENVIO_CON_SALDO),
            _jugada("¡Listo! Te dejo los datos 💓", AccionAsesora.PEDIR_ABONO),
        )
        a.ejecutar(CONV, LO_PIDE)
        t = a.ejecutar(CONV, "Yo los pago cuando esté listo el anillo")
        texto = _texto(t)
        assert "LÍA GÓMEZ" in texto
        assert "los $60.000 del abono" in texto
        assert AL_RECIBIR not in texto
        assert CON_EL_SALDO in texto

    def test_sin_pedirlo_las_cuentas_siguen_igual(self, mundo):
        """Lo normal no cambia: contraentrega, y no se le ofrece pagarlo antes."""
        a = _pedido_creado(mundo)
        texto = " ".join(
            m.get("texto", "")
            for m in mundo.contexto(CONV).charla
            if m.get("de") == "lia"
        )
        assert AL_RECIBIR in texto
        assert CON_EL_SALDO not in texto
        assert a is not None

    def test_si_se_arrepiente_vuelve_a_ser_al_recibir(self, mundo):
        a = _pedido_creado(
            mundo,
            _jugada("¡Claro! 💓", AccionAsesora.ENVIO_CON_SALDO),
            _jugada("¡Dale! Lo pagas al recibir 🚚", AccionAsesora.ENVIO_AL_RECIBIR),
            _jugada("¡Listo! Te dejo los datos 💓", AccionAsesora.PEDIR_ABONO),
        )
        a.ejecutar(CONV, LO_PIDE)
        a.ejecutar(CONV, "mejor lo pago cuando llegue")
        assert not _pedido(mundo).envio.envio_con_saldo
        t = a.ejecutar(CONV, "dale")
        assert AL_RECIBIR in _texto(t)

    def test_despues_de_pagar_el_saldo_ya_no_se_cambia(self, mundo):
        from app.domain.order_state import OrderState
        from app.domain.services import transicionar

        a = _pedido_creado(
            mundo,
            _jugada("¡Recibido! 🙌", AccionAsesora.RECIBIR_COMPROBANTE),
            _jugada("¡Claro! 💓", AccionAsesora.ENVIO_CON_SALDO),
        )
        a.ejecutar(CONV, "", [{"kind": "image", "descripcion": "comprobante $60.000"}])
        for estado in (
            OrderState.ANTICIPO_PAGADO,
            OrderState.EN_PRODUCCION,
            OrderState.PRODUCCION_LISTA,
            OrderState.ESPERANDO_SALDO,
            OrderState.SALDO_PAGADO,
        ):
            transicionar(mundo._orders, _pedido(mundo), estado, actor="test")
        t = a.ejecutar(CONV, LO_PIDE)
        assert not _pedido(mundo).envio.envio_con_saldo
        assert t.respuesta.escalar


# ══════════════════════════════════════════════════════════════════════════
#  4. CUANDO EL ANILLO ESTÁ LISTO: el cobro y el despacho
# ══════════════════════════════════════════════════════════════════════════


class TestElCobroDelSaldo:
    def test_el_saldo_se_cobra_con_el_envio_incluido(self):
        texto = aviso_de_cierre(recoge=False, saldo_cop=140_000, envio_con_saldo=True)
        assert "con el envío incluido" in texto
        assert "sin envío" not in texto and "contraentrega" not in texto
        assert "LÍA GÓMEZ" in texto

    def test_lo_normal_sigue_dando_las_dos_opciones(self):
        texto = aviso_de_cierre(recoge=False, saldo_cop=140_000)
        assert "sin envío" in texto and "con envío incluido" in texto

    def test_el_aviso_del_anillo_listo_no_le_pregunta_si_lo_incluye(self):
        texto = aviso("ESPERANDO_SALDO", envio_con_saldo=True)
        assert "Como lo acordamos" in texto and "Si deseas" not in texto

    def test_el_despacho_no_le_cobra_el_envio_otra_vez(self):
        texto = aviso(
            "DESPACHADO",
            envio_con_saldo=True,
            codigo="PA-001",
            envio_contraentrega="$18.000",
        )
        assert "se cancela al recibir" not in texto
        assert "no tienes que pagar nada al recibirlo" in texto

    def test_el_despacho_normal_sigue_igual(self):
        texto = aviso("DESPACHADO", codigo="PA-001", envio_contraentrega="$18.000")
        assert "se cancela al recibir" in texto

    def test_si_lo_recoge_manda_el_aviso_de_recoger(self):
        texto = aviso(
            "DESPACHADO",
            recoge=True,
            envio_con_saldo=True,
            codigo="PA-001",
            envio_contraentrega="$18.000",
        )
        assert "Coordinadora" not in texto

    def test_el_aviso_sale_del_pedido(self, mundo):
        """De punta a punta: la marca del chat llega al aviso del despacho."""
        from app.domain.operacion import mensaje_de_aviso
        from app.domain.order_state import OrderState

        a = _pedido_creado(mundo, _jugada("¡Claro! 💓", AccionAsesora.ENVIO_CON_SALDO))
        a.ejecutar(CONV, LO_PIDE)
        pedido = _pedido(mundo)
        cliente = Customer(
            id="c1", channel=Channel.WHATSAPP, channel_user_id="573001112233"
        )
        msg = mensaje_de_aviso(pedido, cliente, OrderState.DESPACHADO)
        assert msg is not None
        assert "no tienes que pagar nada al recibirlo" in (msg.text or "")


# ══════════════════════════════════════════════════════════════════════════
#  5. «LOS PAGO CUANDO ESTÉ LISTO» NO ES UN PAGO
# ══════════════════════════════════════════════════════════════════════════


class TestPagarDespuesNoEsPagar:
    """Repaso del 21/09: «Yo los pago cuando esté listo el anillo» → el modelo
    pidió RECIBIR_COMPROBANTE y el pedido quedó en revisión de pago sin que
    nadie hubiera pagado. La palabra «pago» bastaba para dejarlo pasar."""

    def test_lo_que_todavia_no_es_un_pago(self):
        from app.domain.asesora import habla_de_pago

        for frase in (
            "Yo los pago cuando esté listo el anillo",
            "Voy a transferir en un rato",
            "Te lo pago mañana",
            "Todavía no he pagado",
            "Aún no transfiero",
            "lo pago después",
            "Cuando pague el saldo te aviso",
        ):
            assert not habla_de_pago(frase), frase

    def test_lo_que_si_es_un_pago(self):
        from app.domain.asesora import habla_de_pago

        for frase in (
            "ya pagué",
            "listo ya transferí los 60",
            "Ya consigné el abono",
            "ahí va el comprobante",
            "transferí el abono, el saldo lo pago cuando esté listo",
            "Te mandé el comprobante",
        ):
            assert habla_de_pago(frase), frase

    def test_el_pedido_no_queda_en_revision_de_pago(self, mundo):
        a = _pedido_creado(
            mundo,
            _jugada("¡Perfecto! 🫶 Ya queda anotado", AccionAsesora.RECIBIR_COMPROBANTE),
        )
        a.ejecutar(CONV, "Yo los pago cuando esté listo el anillo")
        assert _pedido(mundo).estado == "ESPERANDO_ANTICIPO"
        assert not mundo.contexto(CONV).borrador["abono_reportado"]


# ══════════════════════════════════════════════════════════════════════════
#  6. «RECIBIDO» SOLO CUANDO DE VERDAD LLEGÓ UN PAGO
# ══════════════════════════════════════════════════════════════════════════


class TestRecibidoSoloConPago:
    """21/09, Camilo probando:

        clienta: Cuenta
        bot:     (las cuentas del abono)  +  «Recibido!»
        clienta: Cuál recibido si no he hecho el pago

    La regla: hay pago con un comprobante o con un «ya pagué» EXPLÍCITO. Si
    no, se le dice que quedamos atentos a SU comprobante, con una pregunta
    suave, y la palabra «recibido» no sale."""

    def test_pedir_la_cuenta_no_es_un_pago(self, mundo):
        from app.conversacion.asesora import QUEDO_ATENTA

        a = _pedido_creado(
            mundo,
            _jugada("¡Claro! 💓 ¿Te ayudo con algo más?"),
            _jugada(
                "¡Claro! Puedes transferir a cualquiera de estas tres:",
                AccionAsesora.MANDAR_CUENTAS,
                final="¡Recibido!",
            ),
        )
        a.ejecutar(CONV, "¿Cuánto se demora?")
        t = a.ejecutar(CONV, "Cuenta")
        texto = _texto(t)
        assert "LÍA GÓMEZ" in texto
        assert "Recibido" not in texto
        assert texto.rstrip().endswith(QUEDO_ATENTA)
        assert _pedido(mundo).estado == "ESPERANDO_ANTICIPO"

    def test_despues_de_las_cuentas_queda_atenta_al_comprobante(self, mundo):
        """El cierre de las cuentas: explícito y con una pregunta."""
        from app.conversacion.asesora import QUEDO_ATENTA

        _pedido_creado(mundo)
        dicho = mundo.contexto(CONV).charla[-1]["texto"]
        assert "LÍA GÓMEZ" in dicho
        assert dicho.rstrip().endswith(QUEDO_ATENTA)
        assert "Recibido" not in dicho

    def test_un_recibido_sin_pago_no_sale(self, mundo):
        from app.conversacion.asesora import QUEDO_ATENTA

        a = _pedido_creado(
            mundo, _jugada("10 a 15 días 💍 ¿Algo más?"), _jugada("¡Recibido! 🙌")
        )
        a.ejecutar(CONV, "¿Cuánto se demora?")
        t = a.ejecutar(CONV, "Cuenta")
        assert "Recibido" not in _texto(t)
        assert QUEDO_ATENTA in _texto(t) or "?" in _texto(t)

    def test_con_el_comprobante_si_es_recibido(self, mundo):
        a = _pedido_creado(
            mundo, _jugada("¡Recibido! 🙌", AccionAsesora.RECIBIR_COMPROBANTE)
        )
        t = a.ejecutar(
            CONV, "", [{"kind": "image", "descripcion": "comprobante $60.000"}]
        )
        assert "¡Recibido! 🙌" in _texto(t)
        assert _pedido(mundo).estado == "EN_REVISION_PAGO"

    def test_ya_pague_explicito_tambien_cuenta(self, mundo):
        """Sin foto, pero dicho claro: «ya pagué, revisa la cuenta»."""
        a = _pedido_creado(
            mundo, _jugada("¡Recibido! 🙌", AccionAsesora.RECIBIR_COMPROBANTE)
        )
        t = a.ejecutar(CONV, "Ya pagué por Nequi, revisa la cuenta porfa")
        assert "¡Recibido! 🙌" in _texto(t)
        assert _pedido(mundo).estado == "EN_REVISION_PAGO"

    def test_voy_a_transferir_no_registra_nada(self, mundo):
        a = _pedido_creado(
            mundo, _jugada("¡Recibido! 🙌", AccionAsesora.RECIBIR_COMPROBANTE)
        )
        t = a.ejecutar(CONV, "Voy a transferir en un rato")
        assert "Recibido" not in _texto(t)
        assert _pedido(mundo).estado == "ESPERANDO_ANTICIPO"
        assert not mundo.contexto(CONV).borrador["abono_reportado"]

    def test_disculparse_por_el_recibido_si_se_puede(self):
        limpio, problemas = vigilar(
            "¡Tienes razón! Ese recibido era porque leí mal 🙈",
            PERMITIDOS,
            Borrador(cuentas_enviadas=True),
            "ESPERANDO_ANTICIPO",
        )
        assert not problemas and limpio

    def test_los_pedidos_a_medias_siguen_preguntando_lo_que_falta(self, mundo):
        """Con las cuentas mandadas y el pedido incompleto, lo que se pregunta
        es lo que falta, no «quedo atenta»: sin eso no entra al taller."""
        a = base._asesora(
            mundo,
            _jugada(
                "¡Claro! Te dejo los datos 💓",
                AccionAsesora.MANDAR_CUENTAS,
                cantidad_huellitas=1,
            ),
        )
        t = a.ejecutar(CONV, "¿a qué cuenta te pago?")
        texto = _texto(t)
        assert "LÍA GÓMEZ" in texto
        assert "Recibido" not in texto
        assert "Quedo atenta" not in texto
        assert "?" in texto


# ══════════════════════════════════════════════════════════════════════════
#  7. «CUENTA»: SI LA PIDE, SE LE MANDA
# ══════════════════════════════════════════════════════════════════════════


class TestPideLaCuenta:
    """21/09: «Cuenta» justo después de las cuentas. Python no las repetía
    (regla anti-spam) y el modelo las escribió a mano; el vigilante borró los
    números y quedó «A nombre de LÍA GÓMEZ» sin un solo dato."""

    def test_lo_que_es_pedir_la_cuenta(self):
        from app.domain.asesora import pide_las_cuentas

        for frase in ("Cuenta", "¿A qué cuenta te transfiero?", "me pasas los datos"):
            assert pide_las_cuentas(frase), frase
        for frase in ("ya transferí", "gracias", "Cuenta con dos huellitas?"):
            assert not pide_las_cuentas(frase), frase

    def test_si_la_pide_otra_vez_se_le_manda_aunque_sea_seguido(self, mundo):
        a = _pedido_creado(mundo, _jugada("¡Claro! 💓", AccionAsesora.MANDAR_CUENTAS))
        t = a.ejecutar(CONV, "Cuenta")
        texto = _texto(t)
        assert "Bancolombia: Ahorros 12345678901" in texto
        assert "Recibido" not in texto

    def test_si_el_modelo_la_escribe_a_mano_van_las_de_verdad(self, mundo):
        a = _pedido_creado(
            mundo,
            _jugada("¡Claro! 💓 Nequi 3001110003 a nombre de LÍA GÓMEZ"),
        )
        t = a.ejecutar(CONV, "Cuenta")
        texto = _texto(t)
        assert texto.startswith("¡Claro! 💓 Te las comparto de nuevo:")
        assert "Bancolombia: Ahorros 12345678901" in texto
        assert "Recibido" not in texto

    def test_sin_pedirlas_no_se_repiten_seguidas(self, mundo):
        a = _pedido_creado(mundo, _jugada("¡Con gusto! 💓", AccionAsesora.MANDAR_CUENTAS))
        t = a.ejecutar(CONV, "gracias")
        assert "LÍA GÓMEZ" not in _texto(t)

    def test_si_el_modelo_dice_que_estan_arriba_igual_se_mandan(self, mundo):
        """Repaso del 21/09: «Cuenta» → «Las tres están arriba 💓», sin datos."""
        a = _pedido_creado(
            mundo, _jugada("Las tres están arriba 💓 Bancolombia, Nequi o Daviplata")
        )
        t = a.ejecutar(CONV, "Cuenta")
        texto = _texto(t)
        assert "están arriba" not in texto
        assert "Bancolombia: Ahorros 12345678901" in texto


class TestEsperandoElPagoNoSeInsiste:
    """Esperando el pago, NO se le pregunta nada (Camilo, 07/10, con la charla
    de Mónica). Antes cada mensaje cerraba con una «pregunta suave»."""

    def test_paga_mas_tarde_y_solo_se_le_agradece(self, mundo):
        a = _pedido_creado(
            mundo,
            _jugada("¡Dale! Quedo atenta a tu comprobante 🙌 ¿Algo más?"),
            _jugada("Perfecto 🙌 Quedo atenta entonces 💓"),
        )
        t1 = _texto(a.ejecutar(CONV, "Te transfiero más tarde"))
        t2 = _texto(a.ejecutar(CONV, "Yo te pago cuando salga del trabajo"))
        for t in (t1, t2):
            assert "?" not in t, t
            assert t.lower().count("atenta") == 1, t
            assert "Recibido" not in t


class TestUnComprobanteQueLlegoNoSePierde:
    """Repaso del 21/09: llegó la foto del comprobante, el modelo leyó
    «Envió el comprobante de pago del abono» y no pidió registrarlo."""

    FOTO: ClassVar[list[dict]] = [
        {"kind": "image", "descripcion": "Comprobante de transferencia por $60.000"}
    ]

    def test_se_registra_aunque_el_modelo_no_lo_pida(self, mundo):
        olvido = _jugada("¡Recibido! 🙌").model_copy(
            update={"lectura": "Envió el comprobante de pago del abono de $60.000"}
        )
        a = _pedido_creado(mundo, olvido)
        t = a.ejecutar(CONV, "", self.FOTO)
        assert _pedido(mundo).estado == "EN_REVISION_PAGO"
        assert "¡Recibido! 🙌" in _texto(t)

    def test_una_foto_que_no_es_comprobante_no_registra_nada(self, mundo):
        otra = _jugada("¡Qué lindo! 🥰").model_copy(
            update={"lectura": "Mandó la foto de su perrito, no es un comprobante"}
        )
        a = _pedido_creado(mundo, otra)
        a.ejecutar(CONV, "", [{"kind": "image", "descripcion": "un perrito"}])
        assert _pedido(mundo).estado == "ESPERANDO_ANTICIPO"

    def test_sin_adjunto_no_basta_con_que_lo_lea(self, mundo):
        """Sin foto ni PDF, el texto tiene que decir que pagó (explícito)."""
        dice = _jugada("¡Dale! 💓").model_copy(
            update={"lectura": "Dice que ahorita manda el comprobante"}
        )
        a = _pedido_creado(mundo, dice)
        a.ejecutar(CONV, "ahorita te mando el comprobante")
        assert _pedido(mundo).estado == "ESPERANDO_ANTICIPO"

    def test_con_el_pedido_a_medias_el_comprobante_tambien_es_recibido(self, mundo):
        """Repaso del 21/09: mandó el comprobante sin haber dado su nombre. El
        pago queda anotado para Lía (`pagado_sin_pedido`), así que «¡Recibido!»
        es verdad y no se puede borrar."""
        from app.domain.asesora import HuellitaPropuesta
        from app.domain.personalizacion import ColorCircon as C

        a = base._asesora(
            mundo,
            _jugada(
                "¡Qué lindo! 💜 ¿Me regalas tu nombre completo?",
                cantidad_huellitas=1,
                huellitas=[HuellitaPropuesta(numero=1, corazon=C.LILA, dedos=C.LILA)],
                talla=7,
                grabado=["Luna"],
            ),
            _jugada(
                "¡Recibido! 🙌 ¿Me regalas tu nombre completo?",
                AccionAsesora.RECIBIR_COMPROBANTE,
            ),
        )
        a.ejecutar(CONV, "1 huellita toda lila, talla 7, que diga Luna")
        t = a.ejecutar(CONV, "", self.FOTO)
        assert mundo.contexto(CONV).borrador["pagado_sin_pedido"]
        assert "¡Recibido! 🙌" in _texto(t)
