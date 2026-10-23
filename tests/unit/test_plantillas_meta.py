"""Las plantillas de Meta dicen lo mismo que el texto libre, y en el mismo orden.

DOS RIESGOS, LOS DOS CAROS
==========================
1. QUE DIGAN COSAS DISTINTAS. Cada aviso existe por duplicado: texto libre
   (dentro de las 24 h) y plantilla aprobada (fuera). Si alguien cambia uno y
   olvida el otro, la clienta recibe un mensaje u otro según la hora a la que
   Lía tocó el botón. Eso no lo nota nadie hasta que una clienta reclama.

2. QUE LOS HUECOS SE CRUCEN. Meta no recibe nombres, recibe una lista
   posicional. Si {{1}} y {{2}} se invierten, la clienta lee el código del
   pedido donde iba el monto, y nadie se entera hasta que pregunta qué
   significa «PED-2026-0417 pesos».
"""

from __future__ import annotations

import re

import pytest

from app.adapters.channels.whatsapp import _componentes_plantilla
from app.domain.guion import (
    AVISOS,
    CATEGORIA_META,
    CUERPOS_META,
    PLANTILLAS_META,
    plantilla_de,
)
from app.domain.models import Channel, Customer, Order, OrderItem
from app.domain.operacion import avisa_este_estado, mensaje_de_aviso
from app.domain.order_state import OrderState

CLIENTA = Customer(
    id="c1", channel=Channel.WHATSAPP, channel_user_id="573001112233", nombre="Ángela"
)


def _pedido() -> Order:
    return Order(
        codigo="PED-2026-0417",
        customer_id="c1",
        estado=OrderState.PRODUCCION_LISTA.value,
        items=[
            OrderItem(
                sku="ANI-HUE-1", nombre="Anillo", cantidad=1, precio_unitario_cop=200_000
            )
        ],
        total_cop=200_000,
        anticipo_cop=60_000,
        saldo_cop=140_000,
    )


class TestCoberturaDeAvisos:
    def test_todo_aviso_tiene_su_plantilla(self):
        """Un aviso sin plantilla se queda encolado hasta que la clienta
        escriba. Para el cobro del saldo, eso puede ser nunca."""
        sin_plantilla = sorted(set(AVISOS) - set(PLANTILLAS_META))
        assert not sin_plantilla, (
            f"avisos que no pueden salir fuera de ventana: {sin_plantilla}"
        )

    def test_toda_plantilla_corresponde_a_un_aviso(self):
        """Una plantilla de sobra es una que Meta revisó para nada."""
        assert set(PLANTILLAS_META) <= set(AVISOS)

    def test_toda_plantilla_tiene_su_cuerpo_escrito(self):
        nombres = {n for n, _ in PLANTILLAS_META.values()}
        assert nombres == set(CUERPOS_META)


class TestReglasDeMeta:
    @pytest.mark.parametrize("nombre", sorted(CUERPOS_META))
    def test_el_nombre_cumple_lo_que_meta_acepta(self, nombre):
        """Solo minúsculas, números y guion bajo. Meta rechaza el resto."""
        assert re.fullmatch(r"[a-z0-9_]+", nombre), nombre
        assert len(nombre) <= 512

    @pytest.mark.parametrize("nombre", sorted(CUERPOS_META))
    def test_los_huecos_son_correlativos_desde_uno(self, nombre):
        """Meta exige {{1}}, {{2}}, {{3}}… sin saltos. Un {{1}} y un {{3}}
        sin {{2}} es rechazo automático."""
        huecos = [int(n) for n in re.findall(r"\{\{(\d+)\}\}", CUERPOS_META[nombre])]
        assert huecos == list(range(1, len(huecos) + 1)), huecos

    @pytest.mark.parametrize("nombre", sorted(CUERPOS_META))
    def test_no_empieza_ni_termina_en_un_hueco(self, nombre):
        """Otra regla de Meta: el cuerpo no puede abrir ni cerrar con
        variable, porque no pueden revisar qué va a decir."""
        cuerpo = CUERPOS_META[nombre].strip()
        assert not cuerpo.startswith("{{")
        assert not cuerpo.endswith("}}")

    @pytest.mark.parametrize("nombre", sorted(CUERPOS_META))
    def test_cabe_en_el_limite_de_meta(self, nombre):
        assert len(CUERPOS_META[nombre]) <= 1024

    def test_son_UTILITY_y_por_tanto_no_venden_nada(self):
        """UTILITY es «información de un pedido que ya hiciste»: se aprueba
        fácil y cuesta menos. Una palabra de promoción la convierte en
        MARKETING y Meta la rechaza."""
        assert CATEGORIA_META == "UTILITY"
        juntos = " ".join(CUERPOS_META.values()).lower()
        for promocion in ("descuento", "promoción", "oferta", "aprovecha", "% off"):
            assert promocion not in juntos, f"«{promocion}» la vuelve MARKETING"

    def test_cada_plantilla_declara_tantos_campos_como_huecos_tiene(self):
        """Si el cuerpo tiene {{1}} y {{2}} pero solo se manda un valor, Meta
        rechaza el envío entero."""
        for nombre, campos in PLANTILLAS_META.values():
            huecos = len(set(re.findall(r"\{\{\d+\}\}", CUERPOS_META[nombre])))
            assert huecos == len(campos), (
                f"{nombre}: {huecos} huecos, {len(campos)} campos"
            )


class TestLasDosVersionesDicenLoMismo:
    def test_el_cobro_lleva_el_monto_en_las_dos(self):
        """El monto vive en la SEGUNDA parte del aviso (después de las fotos),
        porque así lo manda Lía: primero ve su anillo, después el número."""
        from app.domain.guion import AVISO_LISTO_PARTE_2

        plantilla = CUERPOS_META["pedido_listo_cobro_saldo"]
        assert "{saldo}" in AVISO_LISTO_PARTE_2
        assert "{{2}}" in plantilla

    def test_las_dos_versiones_hablan_del_mismo_momento(self):
        for estado, (nombre, _) in PLANTILLAS_META.items():
            libre = AVISOS[estado].lower()
            if estado == "ESPERANDO_SALDO":
                # Su aviso va partido en dos, con las fotos en medio.
                from app.domain.guion import AVISO_LISTO_PARTE_2

                libre += " " + AVISO_LISTO_PARTE_2.lower()
            plantilla = CUERPOS_META[nombre].lower()
            # Una palabra ancla por aviso: si alguien reescribe uno de los dos
            # para decir otra cosa, esto se cae.
            ancla = {
                "EN_PRODUCCION": "taller",
                "ESPERANDO_SALDO": "saldo",
                "DESPACHADO": "camino",
            }[estado]
            assert ancla in libre and ancla in plantilla


class TestElMensajeLlevaLasDosVersiones:
    def test_siempre_van_juntas_texto_y_plantilla(self):
        """Quién de las dos sale lo decide el despachador en el momento del
        envío, que puede ser horas después. Decidirlo antes sería calcular con
        la ventana de ahora y enviar con la de dentro de un rato."""
        for estado in OrderState:
            if not avisa_este_estado(estado):
                continue
            m = mensaje_de_aviso(_pedido(), CLIENTA, estado)
            assert m.text, f"{estado.value} sin texto libre"
            assert m.template_name, f"{estado.value} sin plantilla"

    def test_los_valores_van_numerados_como_los_espera_meta(self):
        m = mensaje_de_aviso(_pedido(), CLIENTA, OrderState.ESPERANDO_SALDO)
        assert m.template_params == {"1": "PED-2026-0417", "2": "$140.000"}

    def test_el_orden_de_los_valores_es_el_de_la_plantilla(self):
        """{{1}} es el código y {{2}} el monto, en ese orden. Invertirlo manda
        el código donde va la plata."""
        m = mensaje_de_aviso(_pedido(), CLIENTA, OrderState.ESPERANDO_SALDO)
        textos = [
            p["text"] for p in _componentes_plantilla(m.template_params)[0]["parameters"]
        ]
        assert textos == ["PED-2026-0417", "$140.000"]

    def test_el_orden_no_depende_de_como_se_construyo_el_diccionario(self):
        """Antes esto se apoyaba en el orden de inserción del dict. Funcionaba
        y era una apuesta a que nadie lo construyera de otra forma."""
        al_reves = _componentes_plantilla({"2": "$140.000", "1": "PED-2026-0417"})
        assert [p["text"] for p in al_reves[0]["parameters"]] == [
            "PED-2026-0417",
            "$140.000",
        ]

    def test_un_estado_sin_aviso_no_trae_plantilla(self):
        assert plantilla_de("CANCELADO") is None

    def test_despachado_sin_plantilla_si_ya_pago_el_envio_o_recoge(self):
        """La plantilla dice «el envío se cancela al recibir» y «Coordinadora»:
        a quien pagó el envío con el saldo o recoge, le diría algo falso."""
        assert plantilla_de("DESPACHADO") is not None
        assert plantilla_de("DESPACHADO", envio_con_saldo=True) is None
        assert plantilla_de("DESPACHADO", recoge=True) is None
