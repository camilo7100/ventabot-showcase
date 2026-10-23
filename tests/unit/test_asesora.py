"""La asesora (ADR 0014): lo que el modelo propone y lo que Python deja pasar.

Cada test de aquí sale de algo que pasó al repasar las siete conversaciones
reales de Lía contra el bot (`vb repasar`). Ninguno necesita red: el modelo es
un guion de jugadas escritas a mano.
"""

from __future__ import annotations

import pytest

from app.adapters.repositories.memory import (
    InMemoryCustomerRepository,
    InMemoryOrderRepository,
    InMemoryProductRepository,
)
from app.conversacion.asesora import Asesora, HechosDelNegocio
from app.conversacion.mundo import Mundo
from app.domain.asesora import (
    AccionAsesora,
    Borrador,
    CambiosDelBorrador,
    Confianza,
    HuellitaDelBorrador,
    HuellitaPropuesta,
    Jugada,
    MensajeReescrito,
    aplicar,
    repite_lo_dicho,
    vigilar,
)
from app.domain.contexto import ContextoConversacional
from app.domain.models import Channel, Customer, Product
from app.domain.personalizacion import ColorCircon as C

CONV = "wa:573001112233"
PERMITIDOS = {60_000, 200_000, 250_000, 300_000, 15_000, 140_000}
#: Lo que además del anillo hace falta ANTES del abono (regla de Camilo, 19/09).
ENVIO = dict(
    talla=7,
    nombre_clienta="Laura Gómez",
    ciudad="Bogotá",
    direccion="Calle 45 #12-30 apto 301",
)


# ══════════════════════════════════════════════════════════════════════════
#  1. APLICAR: el modelo propone, Python valida
# ══════════════════════════════════════════════════════════════════════════


class TestAplicar:
    def test_colores_de_dos_huellitas(self):
        b, rechazos = aplicar(
            Borrador(),
            CambiosDelBorrador(
                cantidad_huellitas=2,
                huellitas=[
                    HuellitaPropuesta(numero=1, corazon=C.MORADO, dedos=C.ROSADO),
                    HuellitaPropuesta(
                        numero=2, corazon=C.VERDE_ESMERALDA, dedos=C.VERDE_OLIVA
                    ),
                ],
            ),
        )
        assert not rechazos
        assert b.cantidad == 2
        # En el orden en que se pregunta (Camilo, 20/09): la talla va segunda.
        assert b.falta_para_abono() == ["talla", "grabado", "nombre completo"]
        assert [h.corazon for h in b.huellitas] == [C.MORADO, C.VERDE_ESMERALDA]

    def test_una_cantidad_que_no_existe_no_se_guarda(self):
        b, rechazos = aplicar(Borrador(), CambiosDelBorrador(cantidad_huellitas=4))
        assert b.cantidad is None and rechazos

    def test_una_huellita_de_mas_no_se_guarda(self):
        b, rechazos = aplicar(
            Borrador(cantidad=1),
            CambiosDelBorrador(huellitas=[HuellitaPropuesta(numero=2, corazon=C.NEGRO)]),
        )
        assert b.huellitas == [] and rechazos

    def test_deditos_intercalados(self):
        b, _ = aplicar(
            Borrador(cantidad=1),
            CambiosDelBorrador(
                huellitas=[
                    HuellitaPropuesta(
                        numero=1,
                        corazon=C.NEGRO,
                        dedos_alternos=[C.NEGRO, C.BLANCO, C.NEGRO, C.BLANCO],
                    )
                ]
            ),
        )
        assert b.huellitas[0].completa
        assert "Negro-Blanco-Negro-Blanco" in b.resumen()

    def test_talla_que_no_existe_se_rechaza(self):
        """El modelo dijo «talla 16» con una medida de 1,80 cm."""
        b, rechazos = aplicar(Borrador(), CambiosDelBorrador(talla=16))
        assert b.talla is None and "no existe" in rechazos[0]

    def test_la_medida_escrita_da_talla_pero_se_marca_para_revisar(self):
        b, rechazos = aplicar(Borrador(), CambiosDelBorrador(medida_cm=1.73))
        assert not rechazos
        assert b.talla == 7 and b.talla_revisar
        assert any("ESCRITA" in n for n in b.notas)

    def test_el_nombre_de_la_clienta_no_se_graba(self):
        """«María José Orozco» se dio para el taller, no para el aro."""
        b, rechazos = aplicar(
            Borrador(nombre_clienta="María José Orozco"),
            CambiosDelBorrador(grabado=["Luna", "María José Orozco"]),
        )
        assert b.grabado == ["Luna"]
        assert rechazos

    def test_su_propio_nombre_como_parte_del_grabado_si_vale(self):
        """«Lilú ❤ Angélica 15/09/2017» lo pidió así la clienta María Angélica."""
        b, rechazos = aplicar(
            Borrador(nombre_clienta="María Angélica Casas Poveda"),
            CambiosDelBorrador(grabado=["Lilú ♡ Angélica 15/09/2017"]),
        )
        assert b.grabado == ["Lilú ♡ Angélica 15/09/2017"]
        assert not rechazos

    def test_no_caben_seis_nombres(self):
        b, rechazos = aplicar(
            Borrador(),
            CambiosDelBorrador(grabado=["Ana", "Bo", "Cid", "Di", "Ema", "Fito"]),
        )
        assert b.grabado == [] and rechazos

    def test_sin_grabado_y_con_todo_lo_demas_libera_el_abono(self):
        b, _ = aplicar(
            Borrador(
                cantidad=1, huellitas=[HuellitaDelBorrador(corazon=C.LILA, dedos=C.LILA)]
            ),
            CambiosDelBorrador(sin_grabado=True, **ENVIO),
        )
        assert b.falta_para_abono() == []

    def test_sin_talla_no_hay_abono(self):
        """19/09: se pidió el abono con «Talla: por confirmar»."""
        b, _ = aplicar(
            Borrador(
                cantidad=1, huellitas=[HuellitaDelBorrador(corazon=C.LILA, dedos=C.LILA)]
            ),
            CambiosDelBorrador(grabado=["Roberto"]),
        )
        assert "talla" in b.falta_para_abono()

    def test_la_direccion_no_se_pide_antes_del_abono(self):
        """Regla de Camilo (19/09): la dirección va DESPUÉS del abono."""
        b, _ = aplicar(
            Borrador(
                cantidad=1, huellitas=[HuellitaDelBorrador(corazon=C.LILA, dedos=C.LILA)]
            ),
            CambiosDelBorrador(
                grabado=["Roberto"],
                talla=7,
                nombre_clienta="Laura Gómez",
                ciudad="Bogotá",
            ),
        )
        assert b.falta_para_abono() == [], "la dirección no bloquea el abono"
        # Lo que se le pide AL FINAL, con las fotos del anillo terminado.
        assert b.falta_para_despachar() == [
            "cédula",
            "celular",
            "dirección completa con barrio y nomenclatura",
        ]

    def test_si_lo_recoge_no_hace_falta_direccion(self):
        b, _ = aplicar(
            Borrador(
                cantidad=1, huellitas=[HuellitaDelBorrador(corazon=C.LILA, dedos=C.LILA)]
            ),
            CambiosDelBorrador(
                grabado=["Roberto"],
                talla=7,
                nombre_clienta="Laura Gómez",
                recoge_en_tienda=True,
            ),
        )
        assert b.recoge and b.falta_para_abono() == []
        assert b.falta_para_despachar() == []
        assert "Lo recoges en Floridablanca" in b.resumen()

    def test_si_luego_da_la_direccion_deja_de_recoger(self):
        b, _ = aplicar(
            Borrador(recoge=True), CambiosDelBorrador(direccion="Cra 27 #45-10")
        )
        assert b.direccion == "Cra 27 #45-10" and not b.recoge

    def test_una_medida_en_cm_no_es_una_talla(self):
        """19/09: el modelo puso «1,8» (cm de la foto de la regla) en `talla`."""
        b, rechazos = aplicar(Borrador(), CambiosDelBorrador(talla=1.8))
        assert not rechazos, "antes decía «la talla 1.8 no existe en el mandril»"
        assert b.talla is not None and b.talla_revisar, "sale de una medida escrita"

    def test_una_direccion_sin_numero_no_se_guarda(self):
        b, rechazos = aplicar(
            Borrador(), CambiosDelBorrador(direccion="el barrio San Luis")
        )
        assert b.direccion == "" and rechazos
        b, rechazos = aplicar(Borrador(), CambiosDelBorrador(direccion="Cra 27 #45-10"))
        assert b.direccion == "Cra 27 #45-10" and not rechazos


class TestResumen:
    def test_el_grabado_no_duplica_el_corazon(self):
        from app.domain.asesora import unir_grabado

        assert unir_grabado(["Luna", "Mara"]) == "Luna ♡ Mara"
        assert unir_grabado(["Sakura ♡", "Muñeco (carita de gato)"]) == (
            "Sakura ♡ Muñeco (carita de gato)"
        )


class TestPersonalizacion:
    def test_grabado_con_emoji_va_a_notas_y_no_tumba_el_pedido(self):
        b = Borrador(
            cantidad=1,
            huellitas=[HuellitaDelBorrador(corazon=C.NEGRO, dedos=C.NEGRO)],
            grabado=["Rocky 🐶"],
        )
        personalizacion, notas = b.a_personalizacion()
        assert personalizacion.grabados == []
        assert any("Rocky" in n for n in notas)


# ══════════════════════════════════════════════════════════════════════════
#  2. EL VIGILANTE
# ══════════════════════════════════════════════════════════════════════════


class TestVigilante:
    def test_un_monto_inventado_se_quita_con_su_frase(self):
        limpio, problemas = vigilar(
            "¡Listo! El envío te sale en $9.000. Quedo atenta", PERMITIDOS
        )
        assert "9.000" not in limpio and "Listo" in limpio and problemas

    def test_un_monto_real_si_pasa(self):
        limpio, problemas = vigilar("Son $250.000 + $15.000 del envío", PERMITIDOS)
        assert "250.000" in limpio and not problemas

    def test_un_numero_de_cuenta_nunca_lo_escribe_el_modelo(self):
        limpio, problemas = vigilar("Nequi 3001110003. Quedo atenta", PERMITIDOS)
        assert "3001110003" not in limpio and problemas

    def test_nunca_confirma_un_pago(self):
        limpio, _ = vigilar("¡Recibido! Pago confirmado 🙌. Gracias", PERMITIDOS)
        assert "confirmado" not in limpio.lower()

    def test_no_dice_una_talla_distinta_a_la_guardada(self):
        limpio, problemas = vigilar(
            "Con esa medida tu talla es la 16. ¿Colores?",
            PERMITIDOS,
            Borrador(talla=None),
        )
        assert "16" not in limpio and problemas

    def test_la_talla_guardada_si_la_puede_decir(self):
        limpio, problemas = vigilar("¡Talla 7 anotada!", PERMITIDOS, Borrador(talla=7))
        assert "Talla 7" in limpio and not problemas

    def test_no_da_el_pedido_por_tomado_sin_abono(self):
        """Pasó en «Medio»: «Ya tomé tu pedido» antes de que la clienta pagara."""
        mensaje = "Perfecto 🫶 Ya tomé tu pedido. Te escribo pronto"
        limpio, _ = vigilar(mensaje, PERMITIDOS, Borrador(abono_reportado=False))
        assert "tomé tu pedido" not in limpio
        limpio, _ = vigilar(mensaje, PERMITIDOS, Borrador(abono_reportado=True))
        assert "tomé tu pedido" in limpio

    def test_no_dice_que_mando_las_cuentas_si_no_las_mando(self):
        limpio, _ = vigilar(
            "Ya te pasé los datos arriba 💓", PERMITIDOS, Borrador(cuentas_enviadas=False)
        )
        assert "pasé los datos" not in limpio

    def test_no_inventa_redes_ni_trayectoria(self):
        """Pasó con una clienta desconfiada: «@lia_accesorios con cientos de clientes»."""
        limpio, problemas = vigilar(
            "Tenemos Instagram @lia_accesorios con cientos de clientes. "
            "Solo abonas una parte y ves fotos antes del saldo.",
            PERMITIDOS,
        )
        assert "@" not in limpio and "cientos" not in limpio and problemas
        assert "Solo abonas una parte" in limpio

    def test_no_inventa_anos_en_el_mercado(self):
        limpio, _ = vigilar("Llevamos más de 5 años. Te muestro fotos.", PERMITIDOS)
        assert limpio == "Te muestro fotos."

    def test_conserva_los_saltos_de_linea(self):
        limpio, _ = vigilar("¡Hola!\n\n¿Sabes tu talla?", PERMITIDOS)
        assert limpio == "¡Hola!\n\n¿Sabes tu talla?"


# ══════════════════════════════════════════════════════════════════════════
#  3. EL TURNO ENTERO, con un modelo de guion
# ══════════════════════════════════════════════════════════════════════════


class Guion:
    """Devuelve las jugadas en orden. Falla si le piden más de las que tiene."""

    def __init__(self, *jugadas):
        self._jugadas = list(jugadas)
        self.entradas: list[str] = []
        self.reescrituras: list[str] = []
        self.pedidas_de_reescritura: list[str] = []

    def extract(self, system_prompt, user_text, schema, *, images=None):
        if schema is not Jugada:
            # Una reescritura: solo si la prueba trae alguna preparada.
            if not self.reescrituras:
                raise RuntimeError("el guion no reescribe")
            self.pedidas_de_reescritura.append(user_text)
            return MensajeReescrito(mensaje=self.reescrituras.pop(0))
        self.entradas.append(user_text)
        jugada = self._jugadas.pop(0)
        if isinstance(jugada, Exception):
            raise jugada
        return jugada


class ContextoEnMemoria:
    def __init__(self):
        self._d: dict[str, ContextoConversacional] = {}

    def cargar(self, conv_id):
        return self._d.get(conv_id) or ContextoConversacional(conversation_id=conv_id)

    def guardar(self, ctx):
        self._d[ctx.conversation_id] = ctx


@pytest.fixture
def mundo():
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
    mundo = Mundo(InMemoryOrderRepository(), customers, productos, ContextoEnMemoria())
    # La conversación llega YA EMPEZADA. El primer mensaje de una charla en
    # blanco no pasa por el modelo —recibe la presentación fija, ver
    # `Asesora._apertura`— y casi todo lo que se prueba aquí es lo que viene
    # después. Los tests de la apertura usan `_mundo_en_blanco()`.
    abrir_conversacion(mundo)
    return mundo


def abrir_conversacion(mundo, conv: str = CONV) -> None:
    """Deja la conversación como si ya se hubiera mandado la presentación."""
    ctx = mundo.contexto(conv)
    mundo.guardar_contexto(
        ctx.model_copy(update={"charla": [{"de": "lia", "texto": "(ya saludada)"}]})
    )


def _asesora(mundo, *jugadas, respaldo=None, nueva=False):
    """La asesora con un guion de jugadas.

    `nueva=False` deja la conversación YA EMPEZADA, porque el primer mensaje
    de una conversación en blanco no pasa por el modelo: recibe la
    presentación fija (ver `Asesora._apertura`). Casi todos los tests de aquí
    prueban lo que pasa DESPUÉS de eso; los que prueban la apertura misma
    piden `nueva=True`.
    """
    hechos = HechosDelNegocio(precios={1: 200_000, 2: 250_000, 3: 300_000})
    if not nueva:
        abrir_conversacion(mundo)
    return Asesora(mundo, Guion(*jugadas), "{hechos}", hechos, respaldo=respaldo)


def _jugada(mensaje="", *acciones, final="", **cambios):
    return Jugada(
        lectura="prueba",
        cambios=CambiosDelBorrador(**cambios),
        acciones=list(acciones),
        mensaje=mensaje,
        mensaje_final=final,
        confianza=Confianza.ALTA,
    )


class TestTurno:
    def test_precios_saludo_ficha_y_pregunta_en_ese_orden(self, mundo):
        a = _asesora(
            mundo,
            _jugada(
                "¡Hola! Buen día 🌞",
                AccionAsesora.MOSTRAR_PRECIOS,
                final="¿Sabes tu talla de anillo o te comparto la guía? 💍💜",
            ),
        )
        t = a.ejecutar(CONV, "¿Qué precio tiene el anillo?")
        piezas = t.respuesta.piezas
        textos = [p.texto for p in piezas if p.texto]
        assert textos[0].startswith("¡Hola!")
        assert "$250.000" in textos[1]
        # La pregunta va de PIE del último medio, no en un mensaje aparte:
        # así WhatsApp la deja debajo del álbum (Camilo, 20/09).
        assert piezas[-1].imagen and piezas[-1].texto.startswith("¿Sabes tu talla")
        assert sum(1 for p in piezas if "talla" in (p.texto or "")) == 1, (
            "la pregunta salió dos veces"
        )

    def test_la_venta_entera_hasta_el_comprobante(self, mundo):
        a = _asesora(
            mundo,
            _jugada(
                "¿Así está bien? 🥰",
                AccionAsesora.MOSTRAR_RESUMEN,
                cantidad_huellitas=1,
                huellitas=[HuellitaPropuesta(numero=1, corazon=C.NEGRO, dedos=C.NEGRO)],
                grabado=["Lukas ♡ Simón ♡ Orión"],
                **{**ENVIO, "talla": 5},
            ),
            _jugada("¡Qué emoción! 🫶", AccionAsesora.PEDIR_ABONO),
            _jugada(
                "¡Recibido! 🙌 ¿Me regalas tu nombre?", AccionAsesora.RECIBIR_COMPROBANTE
            ),
        )
        t1 = a.ejecutar(
            CONV, "Solo con una huellita negra, adentro Lukas ♥ Simón ♥ Orión"
        )
        assert "•Anillo 1 huellita•" in t1.respuesta.texto_plano
        assert "Calle 45 #12-30" in t1.respuesta.texto_plano, "el resumen trae el envío"
        t2 = a.ejecutar(CONV, "Si la que dije 🙂")
        assert "LÍA GÓMEZ" in t2.respuesta.texto_plano
        assert t2.respuesta.texto_plano.count("•Anillo") == 0, "no repite el resumen"
        borrador = mundo.contexto(CONV).borrador
        pedido = mundo.pedido(borrador["pedido_id"])
        assert pedido is not None and pedido.estado == "ESPERANDO_ANTICIPO"
        a.ejecutar(CONV, "", [{"kind": "image", "descripcion": "comprobante $60.000"}])
        pedido = mundo.pedido(borrador["pedido_id"])
        assert pedido.estado == "EN_REVISION_PAGO", "el pago lo confirma una persona"

    def test_falta_el_grabado_pero_ella_quiere_pagar(self, mundo):
        """Antes no se le daba la cuenta con algo por escoger. Camilo (05/10):
        si ELLA quiere pagar, se le da; el pedido nace cuando esté completo."""
        a = _asesora(
            mundo,
            _jugada(
                "¡Listo!",
                AccionAsesora.PEDIR_ABONO,
                cantidad_huellitas=1,
                huellitas=[HuellitaPropuesta(numero=1, corazon=C.NEGRO, dedos=C.NEGRO)],
            ),
        )
        t = a.ejecutar(CONV, "¿a qué número te envío los 60?")
        texto = t.respuesta.texto_plano
        assert "LÍA GÓMEZ" in texto
        # Lo que falta va DEBAJO de los datos (aquí, la cantidad: no la escribió).
        assert texto.index("LÍA GÓMEZ") < texto.index("huellita")
        assert mundo.contexto(CONV).borrador["pedido_id"] is None

    def test_el_muestrario_no_se_manda_dos_turnos_seguidos(self, mundo):
        a = _asesora(
            mundo,
            _jugada("Mira 🩵", AccionAsesora.MOSTRAR_MUESTRARIO),
            _jugada("¿Cuál te gusta?", AccionAsesora.MOSTRAR_MUESTRARIO),
        )
        a.ejecutar(CONV, "¿qué colores hay?")
        t = a.ejecutar(CONV, "a ver")
        assert "muestrario_circones" not in t.respuesta.imagenes()

    def test_si_el_modelo_falla_contesta_el_respaldo(self, mundo):
        class Respaldo:
            llamado = False

            def ejecutar(self, conv, texto, media=None):
                Respaldo.llamado = True
                return "turno del respaldo"

        a = _asesora(mundo, RuntimeError("sin red"), respaldo=Respaldo())
        assert a.ejecutar(CONV, "hola") == "turno del respaldo"
        assert Respaldo.llamado

    def test_en_produccion_si_la_ia_falla_pasa_a_lia_y_avisa(self, mundo):
        """Sin gestor de reglas (producción, 25/09): la clienta no se queda
        hablando sola, Lía la toma en Chatwoot y a Camilo le llega el aviso."""
        avisos = []
        abrir_conversacion(mundo)
        a = Asesora(
            mundo,
            Guion(RuntimeError("sin saldo")),
            "{hechos}",
            HechosDelNegocio(precios={1: 200_000, 2: 250_000, 3: 300_000}),
            avisar=lambda titulo, detalle, clave: avisos.append(titulo),
        )
        t = a.ejecutar(CONV, "quiero el de 2 huellitas")
        assert t.respuesta.escalar, "no pasó a Lía"
        assert "momentico" in t.respuesta.texto_plano
        assert avisos == ["La IA no respondió"]

    def _pedido_creado(self, mundo, *mas_jugadas):
        """Una venta hasta pedir el abono, y luego lo que se quiera probar.

        Dos turnos, como en la vida real: el resumen, y las cuentas cuando dice que sí.
        """
        a = _asesora(
            mundo,
            _jugada(
                "¿Así está bien? 🥰",
                AccionAsesora.MOSTRAR_RESUMEN,
                cantidad_huellitas=2,
                huellitas=[
                    HuellitaPropuesta(numero=1, corazon=C.LILA, dedos=C.MORADO),
                    HuellitaPropuesta(numero=2, corazon=C.CELESTE, dedos=C.BLANCO),
                ],
                grabado=["Luna", "Mara"],
                **ENVIO,
            ),
            _jugada("¡Qué emoción! 🫶", AccionAsesora.PEDIR_ABONO),
            *mas_jugadas,
        )
        a.ejecutar(CONV, "Las dos huellitas, lila con morado y celeste con blanco")
        a.ejecutar(CONV, "Sí, escojo esta opción")
        return a

    def test_agregar_un_nombre_con_el_pedido_creado_llega_al_pedido(self, mundo):
        """En «Medio» la clienta agregó a Pancho y el bot lo escalaba 3 veces."""
        a = self._pedido_creado(
            mundo,
            _jugada("¡Claro! Luna, Mara y Pancho 💓", grabado=["Luna", "Mara", "Pancho"]),
        )
        t = a.ejecutar(CONV, "¿Me puedes agregar a Pancho?")
        assert not t.respuesta.escalar
        pedido_id = mundo.contexto(CONV).borrador["pedido_id"]
        item = mundo.pedido(pedido_id).items[0]
        assert item.personalizacion.grabados == ["Luna", "Mara", "Pancho"]

    def test_otra_cantidad_de_huellitas_con_pedido_creado_la_decide_lia(self, mundo):
        a = self._pedido_creado(mundo, _jugada("¡Dale!", cantidad_huellitas=3))
        t = a.ejecutar(CONV, "mejor de 3 huellitas")
        assert t.respuesta.escalar
        assert mundo.contexto(CONV).borrador["cantidad"] == 2

    def test_una_mentira_sobre_el_estado_descarta_el_mensaje_entero(self, mundo):
        """«Ya tomé tu pedido. Tan pronto esté listo te comparto las fotos…» sin pago."""
        a = _asesora(
            mundo,
            _jugada("Ya tomé tu pedido. Tan pronto esté listo te mando fotos"),
        )
        t = a.ejecutar(CONV, "Si la que dije")
        assert "fotos" not in t.respuesta.texto_plano
        assert "tomé tu pedido" not in t.respuesta.texto_plano

    def test_con_el_comprobante_de_este_turno_el_cierre_si_vale(self, mundo):
        a = self._pedido_creado(
            mundo,
            _jugada(
                "¡Recibido! 🙌 Ya tomé tu pedido, te comparto las fotos cuando esté",
                AccionAsesora.RECIBIR_COMPROBANTE,
            ),
        )
        t = a.ejecutar(
            CONV, "", [{"kind": "image", "descripcion": "comprobante $60.000"}]
        )
        assert "Ya tomé tu pedido" in t.respuesta.texto_plano

    def test_paga_antes_de_que_se_le_pidan_las_cuentas(self, mundo):
        """Repaso «requiero más información»: el comprobante llegó sin pedido creado."""
        a = _asesora(
            mundo,
            _jugada(
                "¿Así está bien? 🥰",
                AccionAsesora.MOSTRAR_RESUMEN,
                cantidad_huellitas=1,
                huellitas=[HuellitaPropuesta(numero=1, corazon=C.NEGRO, dedos=C.NEGRO)],
                grabado=["Sakura ♡ Muñeco (carita de gato)"],
                **ENVIO,
            ),
            _jugada("¡Recibido! 🙌", AccionAsesora.RECIBIR_COMPROBANTE),
        )
        a.ejecutar(CONV, "Una huellita. Nombres: Sakura y Muñeco")
        t = a.ejecutar(
            CONV, "", [{"kind": "image", "descripcion": "comprobante $60.000"}]
        )
        borrador = mundo.contexto(CONV).borrador
        assert borrador["abono_reportado"]
        assert mundo.pedido(borrador["pedido_id"]).estado == "EN_REVISION_PAGO"
        assert "LÍA GÓMEZ" not in t.respuesta.texto_plano, "no reenvía las cuentas"

    def test_las_cuentas_no_se_reenvian_en_el_turno_siguiente(self, mundo):
        """Prueba de punta a punta: «sí, así está perfecto» reenviaba las cuentas."""
        a = self._pedido_creado(mundo, _jugada("¡Dale! 🙌", AccionAsesora.PEDIR_ABONO))
        t = a.ejecutar(CONV, "sí, así está perfecto")
        assert "LÍA GÓMEZ" not in t.respuesta.texto_plano

    def test_nota_de_voz_y_pdf_no_van_como_imagen(self, mundo):
        """Un PDF mandado como foto tumba la llamada; una nota de voz ignorada
        deja a la asesora contestándole a un mensaje vacío."""
        guion = Guion(_jugada("¿Me lo escribes porfa? 🙏"), _jugada("¡Recibido! 🙌"))
        descargadas = []
        a = Asesora(
            mundo,
            guion,
            "{hechos}",
            HechosDelNegocio(precios={1: 200_000}),
            descargar=lambda m: descargadas.append(m) or b"\x89PNG",
        )
        a.ejecutar(CONV, None, [{"kind": "audio", "media_id": "a1"}])
        assert "nota de voz" in guion.entradas[0]
        a.ejecutar(CONV, None, [{"kind": "document", "media_id": "d1"}])
        assert "documento o PDF" in guion.entradas[1]
        assert descargadas == [], "ni el audio ni el PDF se descargan como imagen"

    def test_un_si_no_elige_la_cantidad_entre_opciones(self, mundo):
        """«¿De 1 huellita con los dos nombres, o de 2?» -> «Sí perfecto» no elige."""
        a = _asesora(
            mundo,
            _jugada("¿Lo quieres de 1 huellita con los dos nombres, o de 2 huellitas?"),
            _jugada("¡Dale!", cantidad_huellitas=2),
        )
        a.ejecutar(CONV, "Nombres: Sakura y Muñeco")
        t = a.ejecutar(CONV, "Sí perfecto")
        assert mundo.contexto(CONV).borrador["cantidad"] is None
        assert "2 huellitas" not in t.respuesta.texto_plano.split("o de 2")[0]
        assert "cuántas huellitas" in t.respuesta.texto_plano

    def test_con_la_cantidad_en_duda_solo_vale_una_cantidad_escrita(self, mundo):
        a = _asesora(
            mundo,
            _jugada("¿De 1 huellita con los dos nombres, o de 2 huellitas?"),
            _jugada("¡Dale!", cantidad_huellitas=2),
            _jugada("¡Listo!", cantidad_huellitas=2),
            _jugada("¡Perfecto! 🫶", cantidad_huellitas=1),
        )
        a.ejecutar(CONV, "Nombres: Sakura y Muñeco")
        a.ejecutar(CONV, "Sí perfecto")
        a.ejecutar(CONV, "", [{"kind": "image", "descripcion": "comprobante"}])
        assert mundo.contexto(CONV).borrador["cantidad"] is None
        a.ejecutar(CONV, "de una sola huellita")
        borrador = mundo.contexto(CONV).borrador
        assert borrador["cantidad"] == 1 and not borrador["cantidad_en_duda"]

    def test_dos_nombres_no_son_dos_huellitas(self, mundo):
        a = _asesora(mundo, _jugada("¡Qué lindos!", cantidad_huellitas=2))
        a.ejecutar(CONV, "Nombres:\n-Sakura (con un corazón)\n-Muñeco (carita de gatito)")
        assert mundo.contexto(CONV).borrador["cantidad"] is None

    def test_la_cantidad_escrita_si_vale(self, mundo):
        from app.domain.asesora import cantidad_respaldada

        assert cantidad_respaldada(2, "Son dos huellitas", "")
        assert cantidad_respaldada(1, "Toda la huellita en el mismo tono porfa", "")
        assert cantidad_respaldada(2, "Primera huellita: morado. Segunda: negro", "")
        assert cantidad_respaldada(1, "sí", "¿Es de una sola huellita?")
        assert not cantidad_respaldada(2, "sí", "¿De 1 huellita o de 2 huellitas?")
        # La pregunta que hace el propio sistema también es con opciones.
        assert not cantidad_respaldada(
            2, "Listo", "¿De 1 huellita con los nombres, o de 2 (una por cada uno)?"
        )
        assert not cantidad_respaldada(2, "Sí perfecto", "¿De una, dos o tres huellitas?")

    def test_sin_comprobante_ni_pago_no_se_registra_abono(self, mundo):
        """Pasó con el duelo: «sí, así está perfecto» -> RECIBIR_COMPROBANTE."""
        a = self._pedido_creado(
            mundo, _jugada("¡Dale! Quedo atenta 🙌", AccionAsesora.RECIBIR_COMPROBANTE)
        )
        a.ejecutar(CONV, "sí, así está perfecto")
        borrador = mundo.contexto(CONV).borrador
        assert not borrador["abono_reportado"]
        assert mundo.pedido(borrador["pedido_id"]).estado == "ESPERANDO_ANTICIPO"

    def test_la_charla_llega_al_modelo_en_el_turno_siguiente(self, mundo):
        guion = Guion(_jugada("¡Hola! 🌞"), _jugada("¡Dale!"))
        hechos = HechosDelNegocio(precios={1: 200_000})
        a = Asesora(mundo, guion, "{hechos}", hechos)
        a.ejecutar(CONV, "Hola! Quiero hacer un pedido")
        a.ejecutar(CONV, "Perfecto ahorita lo realizo y te confirmo")
        assert "Clienta: Hola! Quiero hacer un pedido" in guion.entradas[1]
        assert "Lía: ¡Hola! 🌞" in guion.entradas[1]


# ══════════════════════════════════════════════════════════════════════════
#  CALIDEZ: nada de frases repetidas ni frases fijas que suenan a bot
# ══════════════════════════════════════════════════════════════════════════


def _con_guion(mundo, guion):
    hechos = HechosDelNegocio(precios={1: 200_000, 2: 250_000, 3: 300_000})
    return Asesora(mundo, guion, "{hechos}", hechos)


class TestCalidez:
    def test_detecta_la_misma_frase_con_otro_arranque(self):
        dichos = ["¡Dale! Quedo atenta al comprobante 🙌"]
        assert repite_lo_dicho("¡Perfecto! 🙌 Quedo atenta al comprobante.", dichos)
        assert repite_lo_dicho(
            "Perfecto María José 🫶 ¿En cuál ciudad te lo enviamos?",
            ["¿En cuál ciudad te lo enviamos? 🙌"],
        )

    def test_lo_corto_y_lo_distinto_no_cuenta_como_repetido(self):
        assert not repite_lo_dicho("¡Con gusto! 💓", ["¡Con gusto! 💓"])
        assert not repite_lo_dicho(
            "¡Listo, Pancho también! 🐾 ¿Y a qué ciudad va?",
            ["¡Dale! Quedo atenta al comprobante 🙌"],
        )

    def test_mira_cada_renglon_de_un_mensaje_largo(self):
        ficha = "•Anillo 2 huellitas•\nTalla: 7\n¿Así está bien el diseño entonces? 🥰"
        assert repite_lo_dicho("¿Así está bien el diseño entonces? 🥰", [ficha])

    def test_orden_lista_sin_abono_es_pedido_tomado(self):
        b = Borrador()
        for frase in (
            "Gordo con carita de gato. Perfecto, ya queda lista tu orden 🫶",
            "Ya quedó tu orden lista para pasar al taller 🫶",
        ):
            limpio, problemas = vigilar(frase, PERMITIDOS, b)
            assert any(p.startswith("da el pedido por tomado") for p in problemas)
            assert "orden" not in limpio

    def test_un_mensaje_repetido_se_reescribe_con_lo_que_dijo(self, mundo):
        guion = Guion(
            _jugada("¡Dale! Quedo pendiente de tu medida 🙌"),
            _jugada("¡Dale! Quedo pendiente de tu medida 🙌", ciudad="Bogotá"),
        )
        guion.reescrituras = ["¡Listo, a Bogotá entonces! 🚚"]
        a = _con_guion(mundo, guion)
        a.ejecutar(CONV, "Okis")
        t = a.ejecutar(CONV, "Estoy en Bogotá")
        # Lo que importa es que se manda la reescritura y no una frase fija.
        # Debajo va además la pregunta de lo que falta: desde el 20/09 ningún
        # mensaje se queda sin preguntar nada (ver `_le_falta_la_pregunta`).
        assert t.respuesta.texto_plano.startswith("¡Listo, a Bogotá entonces! 🚚")
        assert "Estoy en Bogotá" in guion.pedidas_de_reescritura[0]
        assert "Quedo pendiente de tu medida" in guion.pedidas_de_reescritura[0]

    def test_si_la_reescritura_falla_se_manda_el_mensaje_del_modelo(self, mundo):
        guion = Guion(
            _jugada("¡Dale! Quedo pendiente de tu medida 🙌"),
            _jugada("¡Dale! Quedo pendiente de tu medida 🙌"),
        )
        a = _con_guion(mundo, guion)
        a.ejecutar(CONV, "Okis")
        t = a.ejecutar(CONV, "Ok")
        assert "Quedo pendiente" in t.respuesta.texto_plano

    def test_una_mentira_se_reescribe_y_la_reescritura_tambien_se_vigila(self, mundo):
        guion = Guion(_jugada("¡Listo! Ya quedó tu orden lista para el taller 🫶"))
        guion.reescrituras = ["Ya tomé tu pedido 🫶"]
        a = _con_guion(mundo, guion)
        t = a.ejecutar(CONV, "Gordo con carita de gato")
        # La reescritura también mentía: queda la frase segura, nunca la mentira.
        assert "pedido" not in t.respuesta.texto_plano.lower()
        assert "orden" not in t.respuesta.texto_plano.lower()

    def test_si_el_vigilante_lo_vacia_se_reescribe_en_vez_de_listo(self, mundo):
        guion = Guion(_jugada("El envío a Bogotá te sale en $99.000 🚚"))
        guion.reescrituras = ["¡A Bogotá entonces! 🚚 Quedo pendiente 💓"]
        a = _con_guion(mundo, guion)
        t = a.ejecutar(CONV, "Estoy en Bogotá")
        assert t.respuesta.texto_plano.startswith(
            "¡A Bogotá entonces! 🚚 Quedo pendiente 💓"
        )
        assert "99.000" in guion.pedidas_de_reescritura[0]

    def test_una_sola_cantidad_ofrecida_no_es_pregunta_con_opciones(self):
        from app.domain.asesora import cantidad_respaldada, pregunto_cantidad_con_opciones

        propuesta = (
            "Entonces serían 2 huellitas: una para Sakura con corazón y otra para "
            "Muñeco con carita de gatito, ¿así es? ✨"
        )
        assert not pregunto_cantidad_con_opciones(propuesta)
        assert cantidad_respaldada(2, "Sí perfecto", propuesta)
        assert pregunto_cantidad_con_opciones("¿Lo hacemos de 1 huellita o de 2? 🐾")
        assert pregunto_cantidad_con_opciones("¿De una o de dos huellitas?")
        assert pregunto_cantidad_con_opciones(
            "Para el precio exacto: ¿1, 2 o 3 huellitas?"
        )

    def test_la_pregunta_fija_de_cantidad_no_sale_igual_dos_veces(self, mundo):
        guion = Guion(
            _jugada("Listo, dos huellitas 🐾", cantidad_huellitas=2),
            _jugada("Perfecto, dos huellitas 🐾", cantidad_huellitas=2),
        )
        a = _con_guion(mundo, guion)
        primera = a.ejecutar(CONV, "Luna y Mara").respuesta.texto_plano.strip()
        segunda = a.ejecutar(CONV, "sí").respuesta.texto_plano.strip()
        assert "huellita" in primera and "huellita" in segunda
        assert primera != segunda

    def test_dar_el_nombre_no_llama_a_lia_pero_una_queja_si(self, mundo):
        from app.domain.asesora import pasar_a_lia_sin_motivo

        assert pasar_a_lia_sin_motivo(
            CambiosDelBorrador(nombre_clienta="Valentina Pérez"), "Valentina Pérez"
        )
        assert not pasar_a_lia_sin_motivo(
            CambiosDelBorrador(nombre_clienta="Valentina"),
            "Soy Valentina y el anillo me llegó dañado",
        )
        assert not pasar_a_lia_sin_motivo(CambiosDelBorrador(), "quiero hablar con Lía")

        guion = Guion(
            _jugada(
                "Perfecto Valentina 🫶",
                AccionAsesora.PASAR_A_LIA,
                nombre_clienta="Valentina Pérez",
            )
        )
        t = _con_guion(mundo, guion).ejecutar(CONV, "Valentina Pérez")
        assert not t.respuesta.escalar

    def test_una_descripcion_no_se_graba(self):
        from app.domain.asesora import parece_descripcion

        b, rechazos = aplicar(
            Borrador(), CambiosDelBorrador(grabado=["Gato pantera ♡ Gata calico"])
        )
        assert b.grabado == []
        assert any("describe a la mascota" in r for r in rechazos)
        assert parece_descripcion("una gata calico")
        assert not parece_descripcion("Gordo (carita de gato)")
        assert not parece_descripcion("Luna ♡ Mara")
        assert not parece_descripcion("Pan (pancito)")

    def test_una_huella_negra_no_baja_un_anillo_de_dos(self, mundo):
        guion = Guion(
            _jugada("¡Dos huellitas! 🐾", cantidad_huellitas=2),
            _jugada("¡Negra! 🖤", cantidad_huellitas=1),
            _jugada("Listo, solo una 🖤", cantidad_huellitas=1),
        )
        a = _con_guion(mundo, guion)
        a.ejecutar(CONV, "Son dos huellitas")
        a.ejecutar(CONV, "Una huella negra")
        assert mundo.contexto(CONV).borrador["cantidad"] == 2
        a.ejecutar(CONV, "mejor solo una huellita")
        assert mundo.contexto(CONV).borrador["cantidad"] == 1

    def test_no_se_cobra_un_resumen_que_la_clienta_no_ha_visto(self, mundo):
        completo = dict(
            cantidad_huellitas=1,
            huellitas=[HuellitaPropuesta(numero=1, corazon=C.NEGRO, dedos=C.NEGRO)],
            grabado=["Kira"],
            **ENVIO,
        )
        guion = Guion(
            _jugada(
                "¡Listo! Te dejo los datos 💓",
                AccionAsesora.MOSTRAR_RESUMEN,
                AccionAsesora.PEDIR_ABONO,
                **completo,
            ),
            _jugada("¡Listo! 🫶", AccionAsesora.PEDIR_ABONO),
        )
        a = _con_guion(mundo, guion)
        t = a.ejecutar(CONV, "una huellita negra que diga Kira, ¿a dónde pago?")
        texto = t.respuesta.texto_plano
        assert "Kira" in texto and "LÍA GÓMEZ" not in texto
        assert "¿Así está bien?" in texto
        assert mundo.contexto(CONV).borrador["pedido_id"] is None
        t = a.ejecutar(CONV, "sí, así está bien")
        assert "LÍA GÓMEZ" in t.respuesta.texto_plano
        assert mundo.contexto(CONV).borrador["pedido_id"]

    def test_toda_la_huellita_es_un_anillo_de_una(self):
        from app.domain.asesora import habla_de_una_sola_huellita

        assert habla_de_una_sola_huellita("Toda la huellita en el mismo tono porfa")
        assert not habla_de_una_sola_huellita("la huellita negra y la otra rosada")
        assert not habla_de_una_sola_huellita("dos huellitas")

    def test_si_pago_antes_de_completar_el_pedido_nace_al_completarse(self, mundo):
        negra = [HuellitaPropuesta(numero=1, corazon=C.NEGRO, dedos=C.NEGRO)]
        guion = Guion(
            _jugada("¡Negra y Kira! 🖤", huellitas=negra, grabado=["Kira"], **ENVIO),
            _jugada("¡Recibido! 🙌", AccionAsesora.RECIBIR_COMPROBANTE),
            _jugada("¡Listo, de una! 🫶", cantidad_huellitas=1),
        )
        a = _con_guion(mundo, guion)
        a.ejecutar(CONV, "negra y que diga Kira")
        a.ejecutar(CONV, "", [{"kind": "image", "descripcion": "comprobante $60.000"}])
        b = mundo.contexto(CONV).borrador
        assert b["pedido_id"] is None and b["pagado_sin_pedido"]
        a.ejecutar(CONV, "de una huellita")
        b = mundo.contexto(CONV).borrador
        assert b["pedido_id"] and b["abono_reportado"]
        assert mundo.pedido(b["pedido_id"]).estado == "EN_REVISION_PAGO"


# ══════════════════════════════════════════════════════════════════════════
#  LA CONVERSACIÓN DEL 19/09: lo que Camilo pidió corregir
# ══════════════════════════════════════════════════════════════════════════


NEGRA = [HuellitaPropuesta(numero=1, corazon=C.NEGRO, dedos=C.NEGRO)]


def _con_render(mundo, monkeypatch):
    vistas = []

    def previsualizar(huellitas):
        vistas.append([h.corazon for h in huellitas])
        return f"vista_{len(vistas)}.png"

    monkeypatch.setattr(mundo, "previsualizar", previsualizar)
    return vistas


class TestLoQuePidioCamilo:
    def test_apenas_dice_el_color_se_le_manda_como_queda(self, mundo, monkeypatch):
        vistas = _con_render(mundo, monkeypatch)
        a = _con_guion(
            mundo, Guion(_jugada("¡Qué lindo! 🖤", cantidad_huellitas=1, huellitas=NEGRA))
        )
        t = a.ejecutar(CONV, "una huellita toda negra")
        assert vistas == [[C.NEGRO]], "el prototipo sale sin que ella lo pida"
        assert "vista_1.png" in t.respuesta.imagenes()

    def test_si_no_cambian_los_colores_no_se_repite_el_prototipo(
        self, mundo, monkeypatch
    ):
        vistas = _con_render(mundo, monkeypatch)
        a = _con_guion(
            mundo,
            Guion(
                _jugada("¡Negra! 🖤", cantidad_huellitas=1, huellitas=NEGRA),
                _jugada("¡Rocky! 🐶", grabado=["Rocky"]),
            ),
        )
        a.ejecutar(CONV, "una huellita negra")
        a.ejecutar(CONV, "que diga Rocky")
        assert len(vistas) == 1

    def test_si_pide_consejo_van_los_cuatro_de_un_color(self, mundo, monkeypatch):
        vistas = _con_render(mundo, monkeypatch)
        a = _con_guion(
            mundo,
            Guion(_jugada("¡Te muestro! 💓", AccionAsesora.MOSTRAR_SUGERENCIAS)),
        )
        t = a.ejecutar(CONV, "¿cuál me recomiendas?")
        assert vistas == [[C.ROSADO], [C.AZUL_REY], [C.BLANCO], [C.AMARILLO]]
        pies = [p.texto for p in t.respuesta.piezas if p.texto]
        for pie in ("Todo rosa", "Todo azul zafiro", "Todo blanco", "Todo amarillo"):
            assert pie in pies

    def test_hablar_de_plata_manda_las_cuentas_aunque_falten_datos(self, mundo):
        a = _con_guion(
            mundo,
            Guion(
                _jugada(
                    "¡Claro! Y para pasarlo al taller me falta tu talla 💍",
                    AccionAsesora.MANDAR_CUENTAS,
                    cantidad_huellitas=1,
                    huellitas=NEGRA,
                )
            ),
        )
        t = a.ejecutar(CONV, "¿a dónde te transfiero?")
        assert "LÍA GÓMEZ" in t.respuesta.texto_plano
        assert "$60.000" in t.respuesta.texto_plano
        assert mundo.contexto(CONV).borrador["pedido_id"] is None, "no nace a medias"

    def test_quedo_atenta_al_comprobante_sin_cuentas_no_sale(self, mundo):
        """19/09: «¡Dale! Quedo atenta al comprobante» y nunca se mandaron las cuentas."""
        limpio, problemas = vigilar(
            "¡Dale! Quedo atenta al comprobante 🙌", PERMITIDOS, Borrador()
        )
        assert "comprobante" not in limpio and problemas

    def test_despues_del_comprobante_nunca_se_vuelve_a_pedir_el_abono(self, mundo):
        """19/09: dio su nombre después de pagar y le llegaron las cuentas otra vez."""
        a = TestTurno()._pedido_creado(
            mundo,
            _jugada("¡Recibido! 🙌", AccionAsesora.RECIBIR_COMPROBANTE),
            _jugada("Perfecto Camilo 🫶", AccionAsesora.PEDIR_ABONO),
        )
        a.ejecutar(CONV, "", [{"kind": "image", "descripcion": "comprobante $60.000"}])
        t = a.ejecutar(CONV, "Carlos Pérez")
        assert "LÍA GÓMEZ" not in t.respuesta.texto_plano

    def _anillo_listo(self, mundo, *jugadas):
        from app.domain.order_state import OrderState
        from app.domain.services import transicionar

        a = TestTurno()._pedido_creado(
            mundo,
            _jugada("¡Recibido! 🙌", AccionAsesora.RECIBIR_COMPROBANTE),
            *jugadas,
        )
        a.ejecutar(CONV, "", [{"kind": "image", "descripcion": "comprobante $60.000"}])
        pedido_id = mundo.contexto(CONV).borrador["pedido_id"]
        for estado in (
            OrderState.ANTICIPO_PAGADO,
            OrderState.EN_PRODUCCION,
            OrderState.PRODUCCION_LISTA,
            OrderState.ESPERANDO_SALDO,
        ):
            transicionar(mundo._orders, mundo.pedido(pedido_id), estado, actor="test")
        return a, pedido_id

    def test_el_comprobante_del_saldo_queda_por_verificar(self, mundo):
        """19/09: mandó el comprobante del saldo y nadie se enteró."""
        a, pedido_id = self._anillo_listo(
            mundo, _jugada("¡Recibido! 🙌", AccionAsesora.RECIBIR_COMPROBANTE)
        )
        a.ejecutar(CONV, "", [{"kind": "image", "descripcion": "comprobante $140.000"}])
        assert mundo.pedido(pedido_id).estado == "EN_REVISION_PAGO"
        ctx = mundo.contexto(CONV)
        assert ctx.borrador["saldo_reportado"]
        assert any("SALDO" in n for n in ctx.revisar)

    def test_con_el_anillo_listo_no_dice_que_sigue_en_el_taller(self, mundo):
        """19/09: «Ya está en el taller, te aviso cuando esté listo», y ya estaba."""
        a, _ = self._anillo_listo(
            mundo,
            _jugada("¡Hola! 🥰 Ya está en el taller, te aviso cuando esté listo"),
        )
        t = a.ejecutar(CONV, "¿cómo va mi anillo?")
        assert "taller" not in t.respuesta.texto_plano

    def test_el_modelo_lee_donde_va_el_pedido_en_palabras(self, mundo):
        guion_extra = _jugada("¡Hola! 🥰")
        a, _ = self._anillo_listo(mundo, guion_extra)
        a.ejecutar(CONV, "¿cómo va?")
        entrada = a._llm.entradas[-1]
        assert "YA ESTÁ TERMINADO" in entrada
        assert "saldo por pagar $190.000" in entrada


def test_ya_lo_despachamos_con_el_saldo_en_revision_no_sale():
    """Ensayo real 19/09: «Ya lo despachamos para ti 🚚» con el saldo sin verificar."""
    b = Borrador(abono_reportado=True, cuentas_enviadas=True, saldo_reportado=True)
    limpio, problemas = vigilar(
        "Perfecto Camilo 🫶 Ya lo despachamos para ti 🚚",
        PERMITIDOS,
        b,
        "EN_REVISION_PAGO",
    )
    assert "despachamos" not in limpio and problemas
    limpio, problemas = vigilar(
        "Apenas Lía lo verifique te lo despachamos 🚚", PERMITIDOS, b, "EN_REVISION_PAGO"
    )
    assert "despachamos" in limpio and not problemas


# ══════════════════════════════════════════════════════════════════════════
#  EL PRIMER MENSAJE (Camilo, 20/09)
# ══════════════════════════════════════════════════════════════════════════


class TestLaAperturaDeLia:
    """El primer mensaje es la presentación entera de Lía, no un «hola».

    El 20/09 el bot abrió con «Bienvenida a Anillo Vial»: se inventó el nombre
    del negocio leyendo la calle del punto de recogida. Y preguntaba la
    cantidad de huellitas, cuando lo que Lía pregunta de primeras es la talla.
    """

    def _hechos(self):
        from app.conversacion.asesora import HechosDelNegocio

        return HechosDelNegocio(precios={1: 200_000, 2: 250_000, 3: 300_000})

    def test_la_ficha_dice_los_tres_precios_y_el_abono(self):
        ficha = self._hechos().ficha()
        for trozo in ("$200.000", "$250.000", "$300.000", "$60.000"):
            assert trozo in ficha

    def test_la_ficha_es_la_de_Lía_palabra_por_palabra(self):
        ficha = self._hechos().ficha()
        for frase in (
            "🎀*Anillo personalizado huellita* 💍 🐾",
            "🪄 Precios según la cantidad de huellitas:",
            "✨ *Elaborado en Plata Ley 925 y circones (No se pela, no se oxida, "
            "es una joya para toda la vida)*",
            "📏 Se fabrica en tu medida.",
            "🎨 Escoge el color/combinación que quieras para la huellita.",
            "⏳ Tiempo de fabricación: 10 a 15 días calendario.",
        ):
            assert frase in ficha, f"falta o cambió: {frase!r}"

    def test_el_nombre_del_negocio_va_en_los_hechos_del_modelo(self):
        assert "Luna Joyas" in self._hechos().para_el_prompt()

    def test_llamar_al_negocio_de_otra_forma_no_sale(self):
        """La frase exacta que mandó el 20/09."""
        limpio, problemas = vigilar(
            "¡Hola! 👋 ¿Cómo estás? 😊 Bienvenida a Anillo Vial.",
            PERMITIDOS,
            Borrador(),
            "",
        )
        assert "Anillo Vial" not in limpio and problemas

    @pytest.mark.parametrize(
        "bueno",
        [
            "¡Hola! Buen día 🌞 Bienvenida a Luna Joyas 💍",
            "¡Hola! 🥰 Bienvenida a Luna Joyas 💍✨",
            "Bienvenida a nuestra tienda 💍",
            "Somos de Bucaramanga 🥰",
        ],
    )
    def test_el_nombre_de_verdad_si_pasa(self, bueno):
        limpio, problemas = vigilar(bueno, PERMITIDOS, Borrador(), "")
        assert limpio.strip() and not problemas

    def test_los_medios_de_la_presentacion_existen_en_disco(self):
        """Si falta el archivo, el mensaje sale sin foto y nadie se entera."""
        from pathlib import Path

        carpeta = Path(__file__).resolve().parents[2] / "data" / "imagenes"
        for nombre, ext in (
            ("presentacion_anillo", ".jpg"),
            ("presentacion_video_1", ".mp4"),
            ("presentacion_video_2", ".mp4"),
        ):
            assert (carpeta / f"{nombre}{ext}").is_file(), f"falta {nombre}{ext}"

    def test_la_presentacion_va_UNA_SOLA_VEZ_en_la_conversacion(self, mundo):
        """20/09: la clienta contestó «1» y el bot le soltó otra vez la ficha
        entera con los dos videos. Cinco mensajes y 7 MB para un «1».

        En las conversaciones reales de Lía la ficha sale al principio y no
        vuelve a aparecer nunca.
        """
        a = _asesora(
            mundo,
            _jugada("", AccionAsesora.MOSTRAR_PRECIOS, final="¿Sabes tu talla?"),
            _jugada("", AccionAsesora.MOSTRAR_PRECIOS, final="¿Y el color?"),
        )
        primera = a.ejecutar(CONV, "hola, ¿qué precio tiene?").respuesta
        assert any("$250.000" in (p.texto or "") for p in primera.piezas)
        assert sum(1 for p in primera.piezas if p.imagen) == 3, "foto y dos videos"

        segunda = a.ejecutar(CONV, "1").respuesta
        assert not any("$250.000" in (p.texto or "") for p in segunda.piezas), (
            "volvió a mandar la ficha de precios"
        )
        assert not [p for p in segunda.piezas if p.imagen], "repitió los videos"


class TestElComprobanteNoSeJuzga:
    """04/10, en producción: llegó la foto del comprobante; el modelo leyó
    «$59.700 enviados a otra persona», no pidió registrarlo y preguntó
    «¿Querías enviarme otro comprobante?». Camilo: el bot no juzga pagos; lo
    recibe, Lía lo verifica, y desde ahí puede esperar a una persona."""

    LECTURA = (
        "Envió una captura de un movimiento realizado por $59.700, pero no coincide "
        "con el abono de $60.000; parece estar dirigido a otra persona."
    )

    def _con_la_foto(self, mundo, mensaje: str, *acciones):
        jugada = Jugada(
            lectura=self.LECTURA,
            cambios=CambiosDelBorrador(),
            acciones=list(acciones),
            mensaje=mensaje,
            confianza=Confianza.ALTA,
        )
        a = TestTurno()._pedido_creado(mundo, jugada)
        t = a.ejecutar(CONV, "", [{"kind": "image", "descripcion": ""}])
        return t, mundo.contexto(CONV)

    def test_se_recibe_aunque_el_modelo_no_lo_pida_y_dude(self, mundo):
        t, ctx = self._con_la_foto(
            mundo,
            "La captura muestra $59.700 enviados a otra persona, no a Lía. "
            "¿Querías enviarme otro comprobante?",
        )
        texto = t.respuesta.texto_plano
        assert "otro comprobante" not in texto and "otra persona" not in texto
        assert "¡Recibido!" in texto and "Lía" in texto
        pedido = mundo.pedido(ctx.borrador["pedido_id"])
        assert pedido.estado == "EN_REVISION_PAGO"
        assert t.respuesta.escalar, "con un pago que no cuadra, a una persona"
        assert any("$59.700" in n for n in ctx.revisar), "Lía ve lo que se leyó"
        assert any("no parece cuadrar" in n for n in ctx.revisar)

    def test_si_el_modelo_lo_recibe_bien_no_se_toca(self, mundo):
        t, ctx = self._con_la_foto(
            mundo, "¡Recibido! 🙌", AccionAsesora.RECIBIR_COMPROBANTE
        )
        assert t.respuesta.texto_plano.startswith("¡Recibido! 🙌")
        assert any("$59.700" in n for n in ctx.revisar)


class TestLaPlataEnLaFoto:
    def test_parece_un_pago(self):
        from app.domain.asesora import parece_un_pago

        assert parece_un_pago("captura de un movimiento por $59.700", [])
        assert parece_un_pago("pantallazo de Nequi", [])
        assert not parece_un_pago("foto de un perrito café", [])

    def test_duda_del_comprobante(self):
        from app.domain.asesora import duda_del_comprobante

        assert duda_del_comprobante("¿Querías enviarme otro comprobante?")
        assert duda_del_comprobante("El valor no coincide con el abono")
        assert not duda_del_comprobante("¡Recibido! 🙌 Lía lo verifica")


class TestLoQueEncontroLaPruebaDeVerdad:
    """04/10: lo que la prueba de verdad (IA real, varias clientas) encontró."""

    def test_varias_tallas_en_un_mensaje(self):
        from app.domain.asesora import tallas_escritas

        assert tallas_escritas("el mío talla 6 y el de ella talla 8") == [6, 8]
        assert tallas_escritas("tallas 7 y medio y 9") == [7.5, 9]
        assert tallas_escritas("talla 6.5") == [6.5]
        assert tallas_escritas("mi talla es la 6") == []  # una sola: decide el modelo

    def test_cada_talla_a_su_anillo(self):
        from app.domain.asesora import poner_tallas, tallas_para_varios

        b = Borrador(cantidad=1, por_empezar=[{"cantidad": 1}])
        asignadas = tallas_para_varios(b, "el mío talla 6 y el de ella talla 8")
        assert asignadas == [(0, 6.0), (1, 8.0)]
        poner_tallas(b, asignadas)
        assert [v.talla for v in b.vistas()] == [6.0, 8.0]
        assert all(v.talla_confirmada for v in b.vistas()), "las dijo ella: listas"

    def test_una_fecha_no_lleva_corazon(self):
        from app.domain.personalizacion import unir_grabados

        assert unir_grabados(["Morita", "21/09/23"]) == "Morita 21/09/23"
        assert unir_grabados(["Luna", "Mara"]) == "Luna ♡ Mara"

    def test_los_dos_de_una_huellita_es_para_todos(self):
        from app.domain.asesora import cantidad_de_todos, poner_cantidad_a_todos

        assert cantidad_de_todos("los dos de una huellita") == 1
        assert cantidad_de_todos("ambos de 2 huellitas") == 2
        assert cantidad_de_todos("quiero uno de una huellita") is None
        b = Borrador(cantidad=None, por_empezar=[{}])
        assert poner_cantidad_a_todos(b, 1) == [0, 1]
        assert [v.cantidad for v in b.vistas()] == [1, 1]

    def test_el_de_ella_es_el_otro_anillo(self):
        from app.domain.asesora import anillo_del_mensaje

        b = Borrador(cantidad=1, grabado=["Rocky"], por_empezar=[{"cantidad": 1}])
        kira = CambiosDelBorrador(grabado=["Kira"])
        assert anillo_del_mensaje(b, "el de ella dice Kira", kira) == 1
        assert anillo_del_mensaje(b, "el de mi hermana dice Kira", kira) == 1
        assert anillo_del_mensaje(b, "el mío dice Kira", kira) is None  # es el que va

    def test_ya_te_transferi_queda_registrado_y_pide_el_comprobante(self, mundo):
        from app.conversacion.asesora import PIDE_EL_COMPROBANTE

        a = TestTurno()._pedido_creado(
            mundo,
            _jugada(
                "¡Listo! Apenas Lía verifique el abono, te aviso. ¿Quieres que el "
                "envío vaya a una ciudad distinta?"
            ),
        )
        t = a.ejecutar(CONV, "ya te transferí los 60 mil")
        assert t.respuesta.texto_plano.startswith(PIDE_EL_COMPROBANTE)
        assert "ciudad" not in t.respuesta.texto_plano
        pedido = mundo.pedido(mundo.contexto(CONV).borrador["pedido_id"])
        assert pedido.estado == "EN_REVISION_PAGO", "Lía se entera ya"

    def test_un_si_al_resumen_trae_las_cuentas_aunque_el_modelo_pregunte_otra_cosa(
        self, mundo
    ):
        """04/10: tras el resumen, «así está bien» -> otra vez «¿Así está todo
        bien?». Con el resumen completo y sin cambios, el «sí» es la confirmación."""
        a = _asesora(
            mundo,
            _jugada(
                "¿Así está bien? 🥰",
                AccionAsesora.MOSTRAR_RESUMEN,
                cantidad_huellitas=1,
                huellitas=[HuellitaPropuesta(numero=1, corazon=C.NEGRO, dedos=C.NEGRO)],
                grabado=["Zeus"],
                **{**ENVIO, "talla": 7},
            ),
            _jugada("¡Perfecto! 🫶 ¿Así está todo bien?"),
        )
        a.ejecutar(CONV, "Una negra toda, Zeus, talla 7")
        t = a.ejecutar(CONV, "así está bien")
        assert "LÍA GÓMEZ" in t.respuesta.texto_plano

    def test_no_pregunta_la_ciudad_antes_de_tiempo(self, mundo):
        """04/10: «¡Recibido! 🙌 Ya tomé tu pedido 🫶 ¿A qué ciudad te lo
        enviamos cuando esté listo?». Los datos de envío van al final."""
        a = TestTurno()._pedido_creado(
            mundo,
            _jugada(
                "¡Recibido! 🙌 Ya tomé tu pedido 🫶 ¿A qué ciudad te lo enviamos "
                "cuando esté listo?",
                AccionAsesora.RECIBIR_COMPROBANTE,
            ),
        )
        foto = [{"kind": "image", "descripcion": "comprobante $60.000"}]
        t = a.ejecutar(CONV, "", foto)
        assert "ciudad" not in t.respuesta.texto_plano.lower()
        assert "Recibido" in t.respuesta.texto_plano
