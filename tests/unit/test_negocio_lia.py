"""Las reglas del negocio REAL de Luna Joyas, convertidas en tests.

Esto no prueba código: prueba la política comercial. Si alguien —tú dentro de
seis meses, o un asistente de IA refactorizando— cambia el abono a un
porcentaje o mete el flete en el total, CI se pone rojo ANTES de que una
clienta pague de más.

Las cifras salen de las conversaciones reales de septiembre de 2026.
"""

from __future__ import annotations

import csv
from decimal import Decimal
from pathlib import Path

import pytest

from app.adapters.repositories.csv_files import cargar_catalogo_csv
from app.domain.faq import RESPUESTAS, Pregunta, responder, sin_respuesta
from app.domain.models import Intent, Product
from app.domain.personalizacion import (
    MAX_GRABADOS,
    ColorCircon,
    Huellita,
    Personalizacion,
)
from app.domain.pricing import cotizar, formatear_cop
from app.domain.tallas import DIAMETRO_MM, medir

RAIZ = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def catalogo() -> dict[str, Product]:
    return {p.sku: p for p in cargar_catalogo_csv(RAIZ / "data" / "catalogo.csv")}


class TestPreciosReales:
    """Los tres precios que Lía le dice a sus clientas, tal cual."""

    @pytest.mark.parametrize(
        ("sku", "precio", "huellitas"),
        [("ANI-HUE-1", 200_000, 1), ("ANI-HUE-2", 250_000, 2), ("ANI-HUE-3", 300_000, 3)],
    )
    def test_el_catalogo_tiene_los_precios_del_negocio(
        self, catalogo, sku, precio, huellitas
    ):
        p = catalogo[sku]
        assert p.precio_cop == precio
        assert p.huellitas == huellitas

    def test_no_se_cobra_iva(self, catalogo):
        """Los precios que ve la clienta son finales. [POR DEFINIR] Si Lía
        pasa a ser responsable de IVA, se cambia el CSV y este test."""
        for p in catalogo.values():
            assert p.iva_pct == Decimal("0")

    def test_la_fabricacion_es_de_10_a_15_dias(self, catalogo):
        for p in catalogo.values():
            assert (p.dias_produccion, p.dias_produccion_max) == (10, 15)


class TestAbonoFijo:
    """La regla que más plata mueve: $60.000 para arrancar, cueste lo que cueste."""

    @pytest.mark.parametrize(
        ("sku", "total", "saldo"),
        [
            ("ANI-HUE-1", 200_000, 140_000),
            ("ANI-HUE-2", 250_000, 190_000),
            ("ANI-HUE-3", 300_000, 240_000),
        ],
    )
    def test_el_abono_son_60000_en_los_tres_anillos(self, catalogo, sku, total, saldo):
        c = cotizar(catalogo, [(sku, 1)])
        assert c.anticipo_cop == 60_000
        assert c.total_cop == total
        assert c.saldo_cop == saldo

    def test_abono_mas_saldo_siempre_es_el_total(self, catalogo):
        for sku in catalogo:
            for cantidad in (1, 2, 5):
                c = cotizar(catalogo, [(sku, cantidad)])
                assert c.anticipo_cop + c.saldo_cop == c.total_cop

    def test_dos_anillos_son_dos_abonos(self, catalogo):
        """Cada anillo es una fundición y cada fundición gasta su plata.
        Cobrar un solo abono por dos anillos financia la mitad del material."""
        c = cotizar(catalogo, [("ANI-HUE-1", 2)])
        assert c.anticipo_cop == 120_000

    def test_el_abono_nunca_supera_el_total(self, catalogo):
        """Un producto barato con abono fijo alto no puede cobrar de más."""
        barato = {
            "X": Product(
                sku="X",
                nombre="Dije",
                precio_cop=30_000,
                iva_pct=Decimal("0"),
                anticipo_fijo_cop=60_000,
            )
        }
        c = cotizar(barato, [("X", 1)])
        assert c.anticipo_cop == 30_000
        assert c.saldo_cop == 0

    def test_el_porcentaje_sigue_funcionando_si_no_hay_abono_fijo(self):
        """La línea vieja de accesorios no se rompe por este cambio."""
        otro = {
            "Y": Product(
                sku="Y",
                nombre="Aretes",
                precio_cop=100_000,
                iva_pct=Decimal("0"),
                anticipo_pct=Decimal("0.50"),
            )
        }
        assert cotizar(otro, [("Y", 1)]).anticipo_cop == 50_000


class TestEnvioContraentrega:
    """El flete lo paga la clienta al transportador. No es nuestro."""

    def test_el_flete_no_entra_en_el_total(self, catalogo):
        c = cotizar(catalogo, [("ANI-HUE-1", 1)], envio_contraentrega_cop=16_500)
        assert c.total_cop == 200_000, "se le está cobrando el flete dos veces"
        assert c.saldo_cop == 140_000
        assert c.envio_contraentrega_cop == 16_500

    def test_pero_si_se_le_informa(self, catalogo):
        c = cotizar(catalogo, [("ANI-HUE-1", 1)], envio_contraentrega_cop=16_500)
        assert c.slots()["envio_contraentrega"] == 16_500


class TestTallas:
    def test_las_medidas_reales_dan_las_tallas_que_dice_lia(self):
        assert medir(17.3).talla == 7.0
        assert medir(16.5).talla == 6.0
        assert medir(18.2).talla == 8.0

    def test_siempre_devuelve_una_talla_aunque_la_foto_sea_mala(self):
        """Decisión de negocio: la clienta nunca se queda esperando. Una talla
        dudosa se marca para revisar, no detiene la conversación."""
        for mm in (2.0, 17.3, 40.0):
            m = medir(mm, foto_clara=False)
            assert m.talla in DIAMETRO_MM
            assert m.revisar is True
            assert m.motivo, "se marcó para revisar sin decir por qué"

    def test_una_medida_del_borde_exterior_se_detecta(self):
        """Es el error real de una de las fotos: mide el anillo por fuera."""
        m = medir(25.0)
        assert m.revisar is True
        assert "exterior" in m.motivo

    def test_una_medida_limpia_no_se_marca(self):
        m = medir(17.3, foto_clara=True)
        assert m.revisar is False
        assert m.etiqueta == "7"

    def test_las_medias_tallas_se_escriben_con_decimal(self):
        assert medir(17.7).etiqueta == "7.5"


class TestPersonalizacion:
    def test_cada_huellita_lleva_sus_dos_colores(self):
        p = Personalizacion(
            huellitas=[
                Huellita(corazon=ColorCircon.LILA, dedos=ColorCircon.MORADO),
                Huellita(corazon=ColorCircon.ROJO, dedos=ColorCircon.BLANCO),
            ]
        )
        assert "corazón lila / dedos morado" in p.describir()
        assert "Huellita 2" in p.describir()

    def test_no_se_puede_fabricar_sin_talla(self):
        p = Personalizacion(
            huellitas=[Huellita(corazon=ColorCircon.LILA, dedos=ColorCircon.MORADO)],
            grabados=["Rocky"],
        )
        assert p.falta(1) == ["talla"]
        assert not p.completa(1)

    def test_un_anillo_de_3_huellitas_necesita_3_pares_de_colores(self):
        p = Personalizacion(
            talla=7,
            huellitas=[Huellita(corazon=ColorCircon.LILA, dedos=ColorCircon.LILA)],
            grabados=["Rocky"],
        )
        assert "colores" in p.falta(3)
        assert p.completa(1)

    def test_no_caben_mas_de_cinco_nombres(self):
        with pytest.raises(ValueError, match="no caben"):
            Personalizacion(grabados=[f"N{i}" for i in range(MAX_GRABADOS + 1)])

    def test_el_grabador_no_puede_hacer_emojis(self):
        with pytest.raises(ValueError, match="símbolos"):
            Personalizacion(grabados=["Rocky 🐶"])

    def test_un_nombre_larguisimo_no_cabe_en_el_aro(self):
        with pytest.raises(ValueError, match="no cabe"):
            Personalizacion(grabados=["Bartolomeo Maximiliano de la Santísima"])

    def test_los_grabados_reales_de_lia_si_valen(self):
        """Salen de sus conversaciones: fechas, corazones, infinito, carita de gato."""
        reales = [
            "Lilú ♡ Angélica 15/09/2017",
            "Paz ♡ 05/01/2025",
            "Pancho ∞",
            "Gordo (carita de gato) & Pan",
            "Luna (alitas)",
        ]
        assert Personalizacion(grabados=reales).grabados == reales

    def test_los_nombres_con_tilde_y_enie_si_valen(self):
        p = Personalizacion(grabados=["Muñeca", "José", "Lucía"])
        assert len(p.grabados) == 3

    def test_una_talla_que_no_existe_en_el_mandril_se_rechaza(self):
        with pytest.raises(ValueError, match="no existe"):
            Personalizacion(talla=7.2)

    def test_los_colores_son_los_del_muestrario_y_ninguno_mas(self):
        """Si el LLM pudiera devolver texto libre, habría que fabricar un
        circón que no existe. El Enum lo hace imposible."""
        with pytest.raises(ValueError):
            Huellita(corazon="lila pastel", dedos=ColorCircon.MORADO)


class TestFaq:
    def test_toda_pregunta_del_enum_tiene_respuesta_escrita(self):
        """Agregar un miembro al Enum y olvidar el texto dejaría al bot mudo
        justo cuando cree que entendió."""
        assert sin_respuesta() == []

    def test_ninguna_no_responde_nada(self):
        assert responder(Pregunta.NINGUNA) is None

    def test_las_respuestas_de_plata_dicen_925(self):
        assert "925" in RESPUESTAS[Pregunta.MATERIAL]

    def test_la_garantia_dice_seis_meses(self):
        assert "6 meses" in RESPUESTAS[Pregunta.GARANTIA]

    def test_el_envio_dice_el_precio_bien_formateado(self):
        from app.domain.faq import responder

        texto = responder(Pregunta.ENVIO, envio="$8.000")
        assert "$8.000" in texto
        assert "8,000" not in texto, "formato gringo de miles"
        assert "COORDINADORA, y" in texto, "se comió una coma de la redacción"

    def test_el_envio_sin_ciudad_cae_al_valor_nacional(self):
        """El hueco `{envio}` NUNCA puede llegarle a la clienta sin rellenar."""
        from app.domain.faq import responder

        texto = responder(Pregunta.ENVIO)
        assert "{envio}" not in texto
        from app.domain.faq import ENVIO_NACIONAL_COP

        assert f"${ENVIO_NACIONAL_COP:,.0f}".replace(",", ".") in texto

    def test_contraentrega_explica_el_abono(self):
        assert "$60.000" in RESPUESTAS[Pregunta.CONTRAENTREGA]

    def test_ninguna_respuesta_promete_algo_que_lia_no_hace(self):
        """Red de seguridad boba pero valiosa: si alguien pega un texto nuevo
        que dice «sí manejamos contraentrega», esto lo caza."""
        juntas = " ".join(RESPUESTAS.values()).lower()
        assert "sí manejamos contraentrega" not in juntas
        assert "dorado" not in juntas or "no manejamos baños" in juntas


class TestGoldenDataset:
    """El dataset todavía no se corre contra el LLM (eso es el paso siguiente),
    pero su FORMA sí se valida: un dataset mal escrito da métricas mentirosas."""

    @pytest.fixture(scope="class")
    @classmethod
    def filas(cls):
        ruta = RAIZ / "tests" / "golden" / "mensajes.csv"
        with ruta.open(encoding="utf-8") as fh:
            return list(csv.DictReader(fh))

    def test_hay_suficientes_mensajes(self, filas):
        assert len(filas) >= 50, "menos de 50 ejemplos no mide nada"

    def test_todas_las_intenciones_existen(self, filas):
        validas = {i.value for i in Intent}
        for f in filas:
            assert f["intencion"] in validas, f"intención inventada: {f['intencion']}"

    def test_todas_las_preguntas_existen(self, filas):
        validas = {p.value for p in Pregunta}
        for f in filas:
            assert f["pregunta"] in validas, f"pregunta inventada: {f['pregunta']}"

    def test_solo_las_preguntas_de_faq_traen_pregunta(self, filas):
        for f in filas:
            if f["pregunta"] != "NINGUNA":
                assert f["intencion"] in {"PREGUNTA", "TALLA"}, (
                    f"«{f['mensaje']}» trae pregunta pero no es de FAQ"
                )

    def test_los_sku_etiquetados_existen_en_el_catalogo(self, filas, catalogo):
        for f in filas:
            if f["sku"]:
                assert f["sku"] in catalogo, f"SKU inventado: {f['sku']}"

    def test_no_hay_mensajes_repetidos(self, filas):
        vistos = [f["mensaje"].strip().lower() for f in filas]
        repetidos = {m for m in vistos if vistos.count(m) > 1}
        assert not repetidos, f"repetidos (inflan la métrica): {repetidos}"

    def test_cada_intencion_tiene_al_menos_tres_ejemplos(self, filas):
        from collections import Counter

        cuenta = Counter(f["intencion"] for f in filas)
        flacas = {k: v for k, v in cuenta.items() if v < 3}
        assert not flacas, f"con menos de 3 ejemplos no se mide nada: {flacas}"


class TestFormatoDePlata:
    def test_los_pesos_se_escriben_como_en_colombia(self):
        assert formatear_cop(200_000) == "$200.000"
        assert formatear_cop(60_000) == "$60.000"


class TestNodoFaq:
    """El FAQ tiene que llegar íntegro a la clienta, sin pasar por plantilla."""

    def test_responde_con_el_texto_exacto(self):
        from app.graph.nodes.faq import faq

        r = faq({"entities": {"pregunta": "GARANTIA"}})
        assert r["reply_text"] == RESPUESTAS[Pregunta.GARANTIA]
        assert r["reply_kind"] == "faq"
        assert not r.get("needs_human")

    def test_una_pregunta_desconocida_llama_a_un_humano_y_no_inventa(self):
        from app.graph.nodes.faq import faq

        r = faq({"entities": {"pregunta": "ALGO_QUE_NO_EXISTE"}})
        assert r["needs_human"] is True
        assert "reply_text" not in r

    def test_redactar_no_pisa_el_texto_del_faq(self):
        """El validador de números existe para vigilar al LLM. Aplicado a una
        respuesta literal, borraría un texto correcto porque contiene $16.500."""
        from app.domain.faq import responder
        from app.graph.nodes.respond import redactar

        original = responder(Pregunta.ENVIO)
        r = redactar({"reply_kind": "faq", "reply_text": original, "reply_slots": {}})
        assert r["reply_text"] == original
        from app.domain.faq import ENVIO_NACIONAL_COP

        assert f"${ENVIO_NACIONAL_COP:,.0f}".replace(",", ".") in r["reply_text"]


class TestRouterConLasIntencionesNuevas:
    def test_una_pregunta_va_al_faq(self):
        from app.graph.router import router

        assert router({"intent": Intent.PREGUNTA.value}) == "faq"

    def test_talla_y_personalizar_van_al_nodo_de_diseno(self):
        from app.graph.router import router

        for intent in (Intent.TALLA.value, Intent.PERSONALIZAR.value):
            assert router({"intent": intent}) == "personalizar"

    def test_una_duda_a_media_conversacion_no_queda_atrapada(self):
        """Si pregunta «¿es plata de verdad?» mientras elige colores, se le
        responde. Encerrarla en el formulario es perderla."""
        from app.graph.router import router

        assert router({"paso": "COLORES", "intent": Intent.PREGUNTA.value}) == "faq"
        assert router({"paso": "GRABADO", "intent": Intent.HUMANO.value}) == "handoff"

    def test_pero_una_respuesta_normal_si_sigue_el_guion(self):
        from app.graph.router import router

        assert router({"paso": "COLORES", "intent": Intent.OTRO.value}) == "personalizar"

    def test_una_foto_esperando_la_talla_no_es_un_comprobante(self):
        """Sin esta regla, cada clienta que mide su dedo abre un caso falso
        de revisión de pago."""
        from app.graph.router import router

        assert router({"paso": "TALLA", "inbound_media": [{"kind": "image"}]}) == (
            "personalizar"
        )
        assert router({"inbound_media": [{"kind": "image"}]}) == "comprobante"
