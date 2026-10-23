"""La cuenta, cuando ELLA la quiere, aunque falten datos (Camilo, 05/10).

Real (Yesi, 05/10): «Regálame por fis la cuenta para realizar el abono» con la
talla y su nombre por llegar. El bot contestó «para poder iniciar me faltan la
talla y el nombre» y no mandó la cuenta: tuvo que mandarla una persona.

La regla de Camilo: el bot no persigue el pago con el pedido a medias (eso se
queda), pero si ella lo pide —o lo insinúa: «sí lo quiero, ¿cómo te pago?»— se
le manda, y debajo se le pide con cariño lo que falta.
"""

from __future__ import annotations

import pytest

from app.conversacion.asesora import SIN_ANILLOS
from app.domain.asesora import (
    AccionAsesora,
    Borrador,
    HuellitaDelBorrador,
    quiere_la_cuenta,
)
from app.domain.personalizacion import ColorCircon as C
from tests.unit.test_talla_la_confirma_lia import (  # noqa: F401  (la fixture)
    CONV,
    _asesora,
    _guardar,
    _jugada,
    mundo,
)


class TestLaIntencion:
    @pytest.mark.parametrize(
        "texto",
        [
            "Regálame por fis la cuenta para realizar el abono",  # real, Yesi
            "Si lo quiero, cómo te pago?",
            "como hago el abono?",
            "¿cómo es el pago?",
            "quiero ir abonando",
            "ya te transfiero",
            "¿a dónde te transfiero?",
            "me pasas el nequi porfa",
            "cuál es la cuenta?",
            "Cuenta",
            "listo para pagar",
            "me regalas los datos para pagar",
        ],
    )
    def test_quiere_pagar(self, texto):
        assert quiere_la_cuenta(texto)

    @pytest.mark.parametrize(
        "texto",
        [
            "después te pago",
            "todavía no tengo para el abono",
            "ya pagué",  # eso es el comprobante, no la cuenta
            "me di cuenta que no sé mi talla",
            "¿cuánto es el abono?",
            "dale, sigamos",
            "Will",
            "cuando me paguen la quincena te transfiero",
        ],
    )
    def test_no_es_querer_pagar_ya(self, texto):
        assert not quiere_la_cuenta(texto)


def _yesi() -> Borrador:
    """Como estaba Yesi: escogió todo menos la talla (va a la joyería) y su nombre."""
    return Borrador(
        talla_exige_lia=True,
        turnos=8,
        cantidad=1,
        huellitas=[HuellitaDelBorrador(corazon=C.NEGRO, dedos=C.NEGRO)],
        grabado=["Will"],
        mostrado_en={SIN_ANILLOS: 3},
    )


class TestElTurno:
    def test_el_caso_de_yesi(self, mundo):  # noqa: F811
        a = _asesora(
            mundo,
            _jugada(
                "¡Claro! 💓 Para poder iniciar, me faltan la talla que te midieron en "
                "la joyería y el nombre completo para el pedido, ¿me los compartes?",
                AccionAsesora.PEDIR_ABONO,
            ),
        )
        _guardar(mundo, _yesi())
        texto = a.ejecutar(
            CONV, "Regálame por fis la cuenta para realizar el abono"
        ).respuesta.texto_plano
        assert "Bancolombia" in texto and "$60.000" in texto, "no salió la cuenta"
        assert "Para poder iniciar" not in texto, "le frena el pago"
        # Una cosa a la vez (09/10): la talla la está midiendo en la joyería,
        # así que lo útil ahora es su nombre.
        assert (
            "Cuando puedas, ¿me compartes tu nombre completo para dejar tu pedido "
            "completo? 🫶" in texto
        )
        assert texto.index("Bancolombia") < texto.index("Cuando puedas")

    def test_insinuado_tambien(self, mundo):  # noqa: F811
        a = _asesora(mundo, _jugada("¡Claro! Te dejo los datos 💓"))
        _guardar(mundo, _yesi())
        texto = a.ejecutar(CONV, "Si lo quiero, cómo te pago?").respuesta.texto_plano
        assert "Bancolombia" in texto

    def test_si_la_ia_entendio_que_quiere_pagar(self, mundo):  # noqa: F811
        a = _asesora(
            mundo, _jugada("¡Claro! Te dejo los datos 💓", AccionAsesora.MANDAR_CUENTAS)
        )
        _guardar(mundo, _yesi())
        texto = a.ejecutar(CONV, "ok y lo del pago?").respuesta.texto_plano
        assert "Bancolombia" in texto

    def test_si_no_habla_de_pagar_no_se_le_apura(self, mundo):  # noqa: F811
        """La regla que se queda: con datos por llegar, el bot no pide el pago."""
        a = _asesora(
            mundo,
            _jugada("¡Listo! 🫶 Te dejo los datos 💓", AccionAsesora.PEDIR_ABONO),
        )
        _guardar(mundo, _yesi())
        texto = a.ejecutar(CONV, "Will").respuesta.texto_plano
        assert "Bancolombia" not in texto

    def test_si_lo_deja_para_despues_tampoco(self, mundo):  # noqa: F811
        a = _asesora(
            mundo, _jugada("¡Dale! Quedo atenta 🙌", AccionAsesora.MANDAR_CUENTAS)
        )
        _guardar(mundo, _yesi())
        texto = a.ejecutar(CONV, "después te pago, cuando tenga la talla").respuesta
        assert "Bancolombia" not in texto.texto_plano


class TestLoQueFaltaDebajo:
    def test_una_sola_cosa_a_la_vez(self):
        """Camilo, 09/10: una pregunta útil a la vez (antes se juntaban 3)."""
        from app.conversacion.asesora import lo_que_falta_al_pagar

        texto = lo_que_falta_al_pagar(["grabado", "nombre completo"], Borrador())
        assert texto == (
            "Cuando puedas, ¿me compartes el nombre que quieres grabar para dejar tu "
            "pedido completo? 🫶"
        )

    def test_la_primera_que_falta_sin_volver_a_la_talla_mientras_mide(self):
        from app.conversacion.asesora import lo_que_falta_al_pagar

        falta = [
            "cantidad de huellitas",
            "talla",
            "colores",
            "grabado",
            "nombre completo",
        ]
        texto = lo_que_falta_al_pagar(falta, Borrador())
        assert "de cuántas huellitas lo quieres" in texto
        midiendo = _yesi()
        texto = lo_que_falta_al_pagar(falta[1:], midiendo)
        # Sus colores ya están anotados: no se le piden (09/10); sigue su nombre.
        assert "guía" not in texto and "talla" not in texto
        assert "nombre completo" in texto

    def test_lo_que_es_de_lia_no_se_le_pide(self):
        from app.conversacion.asesora import lo_que_falta_al_pagar
        from app.domain.asesora import TALLA_DE_LIA

        assert lo_que_falta_al_pagar([TALLA_DE_LIA], _yesi()) == ""
