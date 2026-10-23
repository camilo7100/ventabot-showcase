"""Una compra de VARIOS anillos (Camilo y Lía, 02/10).

Lo que pasó con la clienta de prueba de Lía: pidió uno de 3 huellitas y otro de
1, y el bot mezcló los colores de los dos, perdió la talla 6, le pisó una
huellita al primero, cobró el abono de UN anillo y dejó un ♡ colgando al final
del grabado. Las reglas:

  · los anillos se describen DE A UNO y en orden; hasta que uno no está
    completo no se pasa al siguiente;
  · la talla se pregunta una vez («¿son de la misma talla?»);
  · un pedido, un abono y un saldo por TODOS los anillos;
  · el grabado lleva corazones ENTRE los nombres, nunca al final.
"""

from app.domain.asesora import (
    ANILLO_SIGUIENTE,
    AnilloListo,
    Borrador,
    CambiosDelBorrador,
    HuellitaDelBorrador,
    anillo_del_mensaje,
    contar_anillos,
)
from app.domain.edicion import aplicar_edicion
from app.domain.erp import por_anillo
from app.domain.models import Order, OrderItem
from app.domain.personalizacion import Huellita, Personalizacion, unir_grabados
from tests.unit.test_asesora import (  # noqa: F401  (mundo es un fixture)
    CONV,
    AccionAsesora,
    C,
    HuellitaPropuesta,
    _asesora,
    _jugada,
    mundo,
)
from tests.unit.test_panel import app_con_panel  # noqa: F401  (fixture)

A = AccionAsesora


def _huellita(corazon=C.NEGRO, dedos=C.ROSADO):
    return HuellitaDelBorrador(corazon=corazon, dedos=dedos)


def _primer_anillo_completo(**extra) -> Borrador:
    return Borrador(
        por_empezar=[AnilloListo()],
        cantidad=3,
        talla=7,
        huellitas=[_huellita(), _huellita(C.LILA), _huellita(C.ROJO)],
        grabado=["Lulú", "Pepito", "Nala"],
        **extra,
    )


class TestElGrabado:
    def test_corazones_entre_los_nombres_y_ninguno_al_final(self):
        assert unir_grabados(["Lulú ♡", "Pepito ♡", "Nala ♡"]) == "Lulú ♡ Pepito ♡ Nala"
        assert unir_grabados(["Lulú", "Pepito", "Nala"]) == "Lulú ♡ Pepito ♡ Nala"
        assert unir_grabados(["♡ Luna", "Mara ❤️"]) == "Luna ♡ Mara"

    def test_si_pide_otra_cosa_se_respeta(self):
        # Un solo renglón va tal cual: sin corazones, o con otro símbolo.
        assert unir_grabados(["Lulú Pepito Nala"]) == "Lulú Pepito Nala"
        assert unir_grabados(["Luna ♡"]) == "Luna ♡"
        assert unir_grabados(["Luna", "∞ Mara"]) == "Luna ∞ Mara"

    def test_el_taller_lo_lee_igual(self):
        p = Personalizacion(grabados=["Lulú ♡", "Nala ♡"])
        assert "Grabado: Lulú ♡ Nala" in p.describir()


class TestDeAUno:
    def test_no_pasa_al_siguiente_con_el_anillo_a_medias(self):
        b = _primer_anillo_completo()
        b.grabado = []
        assert not b.pasar_al_siguiente()
        assert b.numero_del_anillo == 1
        falta = b.falta_para_abono()
        assert falta.index("grabado") < falta.index(f"{ANILLO_SIGUIENTE} 2 de 2")

    def test_completo_se_guarda_y_el_siguiente_empieza_vacio(self):
        b = _primer_anillo_completo()
        assert b.pasar_al_siguiente()
        assert b.numero_del_anillo == 2 and len(b.anillos) == 1
        assert b.anillos[0].cantidad == 3 and len(b.anillos[0].huellitas) == 3
        assert b.cantidad is None and b.huellitas == [] and b.grabado == []
        assert b.talla is None, "sin «misma talla», la del segundo se pregunta"
        assert b.falta_del_anillo()[:2] == ["cantidad de huellitas", "talla"]
        assert not b.pasar_al_siguiente(), "el último no se archiva"

    def test_misma_talla_pasa_al_siguiente(self):
        b = _primer_anillo_completo(misma_talla=True)
        b.pasar_al_siguiente()
        assert b.talla == 7
        assert "talla" not in b.falta_del_anillo()

    def test_el_resumen_lleva_los_dos_anillos(self):
        b = _primer_anillo_completo()
        b.pasar_al_siguiente()
        b.cantidad, b.talla = 1, 6
        b.huellitas = [_huellita(C.ROJO, C.AZUL_REY)]
        b.grabado = ["Bonnie (alitas)", "Panchito"]
        b.nombre_clienta = "Lía"
        assert b.falta_para_abono() == []
        resumen = b.resumen()
        assert resumen.startswith("•Pedido de 2 anillos•")
        assert "•Anillo 1: 3 huellitas•" in resumen
        assert "•Anillo 2: 1 huellita•" in resumen
        assert "Talla: 6" in resumen and "Talla: 7" in resumen
        assert "Grabado: Lulú ♡ Pepito ♡ Nala" in resumen
        anillos = b.anillos_del_pedido()
        assert [c for c, _, _ in anillos] == [3, 1]
        assert [p.talla for _, p, _ in anillos] == [7, 6]


def _contar(b, acciones, texto, cambios=None, hay_pedido=False):
    return contar_anillos(
        b, acciones, texto, cambios or CambiosDelBorrador(), hay_pedido=hay_pedido
    )


class TestCuantosAnillos:
    def test_otro_anillo_se_suma_solo_si_ella_habla_de_otro(self):
        b = Borrador(cantidad=3)
        rechazos, _, _, nuevos = _contar(b, [A.OTRO_ANILLO], "Y otro de 1")
        assert b.anillos_total == 2 and not rechazos and nuevos == 1
        assert b.por_empezar[0].cantidad == 1, "«otro de 1»: el nuevo es de 1"
        # El modelo repite la acción al turno siguiente: no suma otro.
        rechazos, *_ = _contar(b, [A.OTRO_ANILLO], "Rojo y azul")
        assert b.anillos_total == 2 and rechazos

    def test_la_cantidad_de_otro_de_1_es_del_nuevo_no_del_que_va(self):
        # Ensayo con la IA (02/10): «3» y luego «Y otro de 1» -> el modelo puso
        # cantidad 1 al que iba y el de 3 se perdió.
        b = Borrador(cantidad=3)
        _, _, cambios, _ = _contar(
            b, [A.OTRO_ANILLO], "Y otro de 1", CambiosDelBorrador(cantidad_huellitas=1)
        )
        assert cambios.cantidad_huellitas is None
        assert b.cantidad == 3 and b.por_empezar[0].cantidad == 1

    def test_uno_de_3_y_otro_de_1_en_un_mensaje(self):
        b = Borrador()
        _, _, cambios, _ = _contar(
            b, [A.OTRO_ANILLO], "quiero uno de 3 y otro de 1", CambiosDelBorrador()
        )
        assert cambios.cantidad_huellitas == 3 and b.por_empezar[0].cantidad == 1

    def test_si_dice_cuantos_se_toma_ese_numero(self):
        b = Borrador()
        _contar(b, [A.OTRO_ANILLO], "Son tres anillos")
        assert b.anillos_total == 3

    def test_con_el_pedido_creado_lo_toma_lia(self):
        b = Borrador(pedido_id="x")
        rechazos, nota, *_ = _contar(
            b, [A.OTRO_ANILLO], "quiero otro anillo", hay_pedido=True
        )
        assert b.anillos_total == 1 and rechazos and nota

    def test_un_anillo_menos_descarta_el_que_iba(self):
        b = _primer_anillo_completo()
        b.pasar_al_siguiente()
        b.cantidad = 1
        _contar(b, [A.UN_ANILLO_MENOS], "ya no, solo uno")
        assert b.anillos_total == 1 and not b.anillos
        assert b.cantidad == 3, "vuelve el anillo que ya estaba completo"

    def test_misma_talla_solo_si_ella_lo_dice(self):
        b = Borrador(por_empezar=[AnilloListo(cantidad=1)])
        rechazos, *_ = contar_anillos(
            b,
            [A.MISMA_TALLA],
            "Si",
            CambiosDelBorrador(),
            hay_pedido=False,
            ultimo_de_lia="¿Y el de 3 huellitas?",
        )
        assert not b.misma_talla and rechazos
        contar_anillos(
            b,
            [A.MISMA_TALLA],
            "Si",
            CambiosDelBorrador(),
            hay_pedido=False,
            ultimo_de_lia="¿Los dos son de la misma talla?",
        )
        assert b.misma_talla

    def test_misma_talla_solo_con_varios(self):
        b = Borrador()
        _contar(b, [A.MISMA_TALLA], "sí, la misma")
        assert not b.misma_talla


class TestDeCualHabla:
    def _dos(self):
        # Va el de 3 (sin talla); el de 1 está anunciado.
        return Borrador(cantidad=3, por_empezar=[AnilloListo(cantidad=1)])

    def test_por_sus_huellitas(self):
        b = self._dos()
        cambios = CambiosDelBorrador(talla=6)
        assert anillo_del_mensaje(b, "Talla 6 el de una y el otro no sé", cambios) == 1
        assert anillo_del_mensaje(b, "para el de tres: talla 7", cambios) is None
        assert anillo_del_mensaje(b, "talla 6", cambios) is None, (
            "sin decir cuál: el que va"
        )

    def test_una_medida_no_es_un_anillo(self):
        b = self._dos()
        cambios = CambiosDelBorrador(medida_cm=1.8)
        assert anillo_del_mensaje(b, "el de 1,8 cm", cambios) is None

    def test_por_su_lugar(self):
        b = self._dos()
        cambios = CambiosDelBorrador(grabado=["Bonnie"])
        assert anillo_del_mensaje(b, "en el segundo va Bonnie", cambios) == 1

    def test_la_foto_de_la_regla_va_al_que_no_tiene_talla(self):
        b = Borrador(cantidad=1, talla=6, por_empezar=[AnilloListo(cantidad=3)])
        vacio = CambiosDelBorrador()
        assert anillo_del_mensaje(b, "", vacio, foto_de_talla=True) == 1
        b.talla = None
        assert anillo_del_mensaje(b, "", vacio, foto_de_talla=True) is None

    def test_enfocar_anota_en_ese_y_respeta_el_orden(self):
        b = self._dos()
        b.enfocar(1)
        assert b.cantidad == 1, "durante el turno, el de 1 ocupa el lugar del actual"
        b.talla = 6
        assert [v.cantidad for v in b.vistas()] == [3, 1], "el orden de ella no cambia"
        b.desenfocar()
        assert b.cantidad == 3 and b.talla is None
        assert b.por_empezar[0].talla == 6


class TestLaTallaDeCadaAnillo:
    def test_lia_confirma_la_del_anillo_que_la_esperaba(self):
        b = Borrador(
            talla_exige_lia=True,
            anillos=[AnilloListo(cantidad=3, talla_fotos=["regla.jpg"])],
            cantidad=1,
        )
        assert b.pendiente_de_talla() == 0 and b.talla_por_confirmar
        b.fijar_talla(None, 7, "Confirmada por Lía")
        assert b.anillos[0].talla == 7 and b.anillos[0].talla_confirmada
        assert b.talla is None, "la del segundo anillo no se toca"


class TestLaConversacion:
    def test_dos_anillos_de_a_uno_con_un_solo_abono(self, mundo):  # noqa: F811
        tres = [
            HuellitaPropuesta(numero=1, corazon=C.CELESTE, dedos=C.ROSADO),
            HuellitaPropuesta(numero=2, corazon=C.VERDE_OLIVA, dedos=C.VERDE_ESMERALDA),
            HuellitaPropuesta(numero=3, corazon=C.NEGRO, dedos=C.MORADO),
        ]
        a = _asesora(
            mundo,
            _jugada(
                "¡Dos anillos! ¿Son de la misma talla?",
                A.OTRO_ANILLO,
                A.MISMA_TALLA,
                cantidad_huellitas=3,
                talla=7,
            ),
            _jugada(
                "¡Listo el de 3! Ahora el segundo: ¿de cuántas huellitas?",
                huellitas=tres,
                grabado=["Lulú ♡", "Pepito ♡", "Nala ♡"],
            ),
            _jugada(
                "¿Así está bien? 🥰",
                cantidad_huellitas=1,
                huellitas=[HuellitaPropuesta(numero=1, corazon=C.ROJO, dedos=C.AZUL_REY)],
                grabado=["Bonnie (alitas)", "Panchito"],
                nombre_clienta="Lía Gómez",
            ),
            _jugada("¡Listo! 🫶 Te dejo los datos 💓", A.PEDIR_ABONO),
        )
        a.ejecutar(
            CONV, "Quiero dos anillos, uno de 3 huellitas y otro de 1, talla 7 los dos"
        )
        b = mundo.contexto(CONV).borrador
        assert len(b["por_empezar"]) == 1 and b["misma_talla"]

        a.ejecutar(CONV, "Turquesa con rosa, oliva con esmeralda, negro con morado")
        b = mundo.contexto(CONV).borrador
        assert len(b["anillos"]) == 1, "el de 3 quedó completo y se guardó"
        # El segundo empieza con lo que ya se sabía de él: «otro de 1».
        assert b["cantidad"] == 1 and b["talla"] == 7 and b["huellitas"] == []

        t3 = a.ejecutar(CONV, "El otro de 1 huellita, rojo y azul, Bonnie y Panchito")
        texto = t3.respuesta.texto_plano
        assert "•Pedido de 2 anillos•" in texto
        assert "Grabado: Lulú ♡ Pepito ♡ Nala\n" in texto + "\n"

        t4 = a.ejecutar(CONV, "Sí")
        texto = t4.respuesta.texto_plano
        assert "$120.000" in texto and "de los 2 anillos" in texto
        pedido = mundo.pedido(mundo.contexto(CONV).borrador["pedido_id"])
        assert pedido.anticipo_cop == 120_000 and pedido.total_cop == 500_000
        assert [len(i.personalizacion.huellitas) for i in pedido.items] == [3, 1]
        assert pedido.items[0].personalizacion.huellitas[0].corazon == C.CELESTE
        assert pedido.items[1].personalizacion.grabados == ["Bonnie (alitas)", "Panchito"]

        a2 = _asesora(mundo, _jugada("¡Recibido! 🙌", A.RECIBIR_COMPROBANTE))
        a2.ejecutar(CONV, "", [{"kind": "image", "descripcion": "comprobante $120.000"}])
        assert mundo.pedido(pedido.id).estado == "EN_REVISION_PAGO"


def _pedido_de_dos(**montos) -> Order:
    def item(n, precio, grabado):
        return OrderItem(
            sku=f"ANI-HUE-{n}",
            nombre=f"Anillo x{n}",
            cantidad=1,
            precio_unitario_cop=precio,
            personalizacion=Personalizacion(
                talla=7,
                huellitas=[Huellita(corazon=C.NEGRO, dedos=C.ROSADO)] * n,
                grabados=[grabado],
            ),
        )

    return Order(
        codigo="PED-2026-0001",
        customer_id="c1",
        estado="ANTICIPO_PAGADO",
        items=[item(3, 300_000, "Lulú"), item(1, 200_000, "Bonnie")],
        total_cop=500_000,
        anticipo_cop=120_000,
        saldo_cop=380_000,
        **montos,
    )


class TestElErpYElPanel:
    def test_cada_anillo_es_una_venta_en_el_erp(self):
        uno, dos = por_anillo(_pedido_de_dos(anticipo_pagado_cop=120_000))
        assert (uno.codigo, dos.codigo) == ("PED-2026-0001-A1", "PED-2026-0001-A2")
        assert (uno.total_cop, uno.anticipo_cop, uno.saldo_cop) == (
            300_000,
            60_000,
            240_000,
        )
        assert (dos.total_cop, dos.anticipo_pagado_cop) == (200_000, 60_000)
        assert dos.saldo_pagado_cop == 0
        assert len(dos.items) == 1 and dos.items[0].personalizacion.grabados == ["Bonnie"]

    def test_un_pedido_de_un_anillo_sale_tal_cual(self):
        pedido = _pedido_de_dos()
        pedido = pedido.model_copy(update={"items": pedido.items[:1]})
        assert por_anillo(pedido) == [pedido]

    def test_lia_corrige_solo_el_anillo_que_escoge(self):
        pedido = _pedido_de_dos()
        nuevo, _, cambios = aplicar_edicion(
            pedido, None, {"anillo": "2", "grabado": "Bonnie ♡ Pan"}
        )
        assert nuevo.items[0].personalizacion.grabados == ["Lulú"]
        assert nuevo.items[1].personalizacion.grabados == ["Bonnie", "Pan"]
        assert cambios and cambios[0].startswith("anillo 2:")


def test_el_taller_muestra_cada_anillo(app_con_panel):  # noqa: F811
    """Un pedido de 2 anillos en el panel: los dos, cada uno con su formulario."""
    from fastapi.testclient import TestClient

    from app.domain.models import Channel, Customer
    from tests.unit.test_panel import TOKEN

    app, c = app_con_panel
    c.customers.upsert(
        Customer(id="c1", channel=Channel.WHATSAPP, channel_user_id="573001112233")
    )
    pedido = _pedido_de_dos(anticipo_pagado_cop=120_000)
    c.orders.create(pedido, idem_key="dos-anillos")
    html = TestClient(app).get(f"/panel?token={TOKEN}").text
    assert "Anillo 1 de 2" in html and "Anillo 2 de 2" in html
    assert "Talla del anillo 2" in html
    assert "name=anillo value=2" in html, "cada anillo se corrige por separado"
    assert "Datos de la guía" in html
