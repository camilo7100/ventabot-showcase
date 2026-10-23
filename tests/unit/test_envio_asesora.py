"""Los datos de envío van en el pedido DESDE QUE NACE (regla de Camilo, 19/09):
nombre, ciudad y dirección se piden antes del abono. Es lo que Lía usa para
despachar y lo que sale en el Excel de ventas; y si la clienta corrige la
dirección después, la corrección tiene que llegar al pedido.
"""

from tests.unit.test_asesora import (  # noqa: F401  (mundo es un fixture)
    CONV,
    ENVIO,
    AccionAsesora,
    C,
    Guion,
    HuellitaPropuesta,
    _con_guion,
    _jugada,
    mundo,
)


def test_el_pedido_nace_con_los_datos_de_envio_y_las_correcciones_llegan(
    mundo,  # noqa: F811
):
    guion = Guion(
        _jugada(
            "¿Así está todo bien? 🥰",
            AccionAsesora.MOSTRAR_RESUMEN,
            cantidad_huellitas=1,
            huellitas=[HuellitaPropuesta(numero=1, corazon=C.NEGRO, dedos=C.NEGRO)],
            grabado=["Rocky"],
            **ENVIO,
        ),
        _jugada("¡Listo! 🫶", AccionAsesora.PEDIR_ABONO),
        _jugada("¡Dale, corregido! 🏡", direccion="Carrera 27 #45-10 casa 2"),
    )
    a = _con_guion(mundo, guion)
    a.ejecutar(CONV, "una huellita negra que diga Rocky, talla 7, Laura Gómez ...")
    a.ejecutar(CONV, "sí, así está perfecto")

    borrador = mundo.contexto(CONV).borrador
    pedido = mundo.pedido(borrador["pedido_id"])
    assert pedido.envio.nombre == ENVIO["nombre_clienta"]
    assert pedido.envio.ciudad == ENVIO["ciudad"]
    assert pedido.envio.direccion == ENVIO["direccion"]
    assert pedido.envio.telefono, "el teléfono de WhatsApp no se pierde"
    # NO está «completo»: faltan la cédula y el celular de la guía, que se
    # piden al final con las fotos del anillo (Camilo, 20/09). Lo que importa
    # aquí es que lo que ella SÍ dijo quedó guardado.
    assert pedido.envio.falta() == ["cedula", "celular"]
    assert pedido.envio.falta_para_tomar_el_pedido() == []

    a.ejecutar(CONV, "ay perdón, la dirección es Carrera 27 #45-10 casa 2")
    pedido = mundo.pedido(borrador["pedido_id"])
    assert pedido.envio.direccion == "Carrera 27 #45-10 casa 2"
