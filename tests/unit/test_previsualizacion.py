"""Enseñarle cómo le va a quedar, y ayudarla a escoger.

Son dos cosas de SERVICIO, no de flujo: el pedido sale igual sin ellas. Pero
delante de catorce colores por catorce mucha gente no elige, y quien no elige
no compra — así que esto es donde se salva media venta.

Lo que se prueba aquí es la POLÍTICA, no la belleza del dibujo: que la foto
se genere con los colores que ella pidió, que no se mande veinte veces, que
la sugerencia siempre le devuelva la decisión, y que si el dibujante falla la
conversación no se entere.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.adapters.render.huellita import RenderDeHuellitas
from app.adapters.repositories.memory import (
    InMemoryCustomerRepository,
    InMemoryOrderRepository,
)
from app.conversacion.ejecutor import Ejecutor
from app.conversacion.interprete import Interprete
from app.conversacion.mundo import Mundo
from app.conversacion.pipeline import Pipeline
from app.conversacion.redactor import Redactor
from app.domain.acciones import Accion
from app.domain.models import Channel, Customer
from app.domain.personalizacion import HEX_COLOR, ColorCircon, Huellita
from app.domain.sugerencias import COMBINACIONES
from tests.unit.test_inteligencia_conversacional import (
    CONV,
    ContextoEnMemoria,
    ModeloDeMadera,
    _productos,
)

RAIZ = Path(__file__).resolve().parents[2]
BASE = RAIZ / "data" / "imagenes" / "fuentes" / "huellita_base.jpg"
MASCARAS = RAIZ / "data" / "imagenes" / "fuentes" / "huellita_mascaras.png"


@pytest.fixture
def render(tmp_path):
    return RenderDeHuellitas(BASE, MASCARAS, tmp_path)


@pytest.fixture
def bot(render):
    customers = InMemoryCustomerRepository()
    customers.upsert(
        Customer(id="c1", channel=Channel.WHATSAPP, channel_user_id="573001112233")
    )
    mundo = Mundo(
        InMemoryOrderRepository(),
        customers,
        _productos(),
        ContextoEnMemoria(),
        render=render,
    )
    return Pipeline(
        Interprete(ModeloDeMadera(), "", ""), mundo, Ejecutor(mundo), Redactor()
    )


def hablar(bot, *mensajes):
    return [bot.ejecutar(CONV, m) for m in mensajes]


# ═══════════════════════════════════════════════════════════════════════════
# EL DIBUJO
# ═══════════════════════════════════════════════════════════════════════════


class TestElDibujo:
    def test_la_foto_base_y_las_mascaras_estan_en_el_repositorio(self):
        """Sin ellas el bot no puede enseñar nada, y es lo que más vende."""
        assert BASE.is_file()
        assert MASCARAS.is_file()

    def test_las_mascaras_traen_las_cinco_piedras(self):
        """Un corazón y cuatro deditos. Ni cuatro ni seis."""
        import numpy as np
        from PIL import Image

        valores = set(np.unique(np.asarray(Image.open(MASCARAS).convert("L"))))
        assert valores == {0, 1, 2, 3, 4, 5}

    def test_todos_los_colores_del_muestrario_se_pueden_dibujar(self):
        """Si a un color le falta el hex, ese anillo no se puede previsualizar."""
        faltan = [c.value for c in ColorCircon if c not in HEX_COLOR]
        assert not faltan, f"colores sin color: {faltan}"

    def test_dibuja_y_devuelve_un_nombre_logico(self, render, tmp_path):
        nombre = render.previsualizar(
            [Huellita(corazon=ColorCircon.ROJO, dedos=ColorCircon.AZUL_REY)]
        )
        assert nombre and nombre.startswith("vista_")
        assert (tmp_path / f"{nombre}.jpg").is_file()

    def test_la_misma_combinacion_no_se_dibuja_dos_veces(self, render, tmp_path):
        h = [Huellita(corazon=ColorCircon.LILA, dedos=ColorCircon.MORADO)]
        primero = render.previsualizar(h)
        antes = (tmp_path / f"{primero}.jpg").stat().st_mtime_ns
        assert render.previsualizar(h) == primero
        assert (tmp_path / f"{primero}.jpg").stat().st_mtime_ns == antes

    def test_combinaciones_distintas_dan_archivos_distintos(self, render):
        rojo = render.previsualizar(
            [Huellita(corazon=ColorCircon.ROJO, dedos=ColorCircon.BLANCO)]
        )
        verde = render.previsualizar(
            [Huellita(corazon=ColorCircon.VERDE_ESMERALDA, dedos=ColorCircon.BLANCO)]
        )
        assert rojo != verde

    def test_el_color_pedido_es_el_que_domina_la_piedra(self, render, tmp_path):
        """Que el dibujo salga NO basta: tiene que salir del color que pidió."""
        import numpy as np
        from PIL import Image

        nombre = render.previsualizar(
            [Huellita(corazon=ColorCircon.ROJO, dedos=ColorCircon.BLANCO)]
        )
        a = np.asarray(Image.open(tmp_path / f"{nombre}.jpg").convert("RGB")).astype(int)
        # El corazón ocupa la mitad de abajo. Ahí el rojo tiene que ganar.
        abajo = a[a.shape[0] // 2 :]
        coloreado = abajo[abajo.max(axis=2) - abajo.min(axis=2) > 40]
        assert len(coloreado) > 1000, "no tiñó nada"
        assert coloreado[:, 0].mean() > coloreado[:, 1].mean() + 30, "no salió rojo"

    def test_tres_huellitas_caben_en_una_sola_foto(self, render, tmp_path):
        from PIL import Image

        una = render.previsualizar(
            [Huellita(corazon=ColorCircon.ROJO, dedos=ColorCircon.BLANCO)]
        )
        tres = render.previsualizar(
            [
                Huellita(corazon=ColorCircon.ROJO, dedos=ColorCircon.BLANCO),
                Huellita(corazon=ColorCircon.LILA, dedos=ColorCircon.MORADO),
                Huellita(corazon=ColorCircon.NEGRO, dedos=ColorCircon.AMARILLO),
            ]
        )
        assert (
            Image.open(tmp_path / f"{tres}.jpg").width
            > Image.open(tmp_path / f"{una}.jpg").width * 2
        )

    def test_sin_foto_base_no_se_rompe_nada(self, tmp_path):
        roto = RenderDeHuellitas(
            tmp_path / "no-existe.jpg", MASCARAS, tmp_path / "salida"
        )
        assert (
            roto.previsualizar(
                [Huellita(corazon=ColorCircon.ROJO, dedos=ColorCircon.BLANCO)]
            )
            is None
        )


# ═══════════════════════════════════════════════════════════════════════════
# EN LA CONVERSACIÓN
# ═══════════════════════════════════════════════════════════════════════════


class TestSeLaEnsena:
    def test_al_escoger_los_colores_le_manda_su_anillo(self, bot):
        hablar(bot, "quiero un anillo de 1 huellita")
        turno = hablar(bot, "corazón rojo y dedos blancos")[0]
        vistas = [n for t, n in turno.respuesta.adjuntos() if n.startswith("vista_")]
        assert vistas, "escogió colores y no le enseñó cómo queda"

    def test_NO_se_la_manda_otra_vez_al_anotar_la_talla(self, bot):
        """La foto de su anillo en cada mensaje deja de ser un regalo y pasa
        a ser ruido."""
        hablar(bot, "quiero un anillo de 2 huellitas", "corazón rojo y dedos blancos")
        turno = hablar(bot, "se llama Poncho")[0]
        assert not [n for _, n in turno.respuesta.adjuntos() if n.startswith("vista_")]

    def test_el_resumen_final_SI_la_lleva(self, bot):
        hablar(
            bot,
            "quiero un anillo de 1 huellita",
            "corazón rojo y dedos blancos",
            "se llama Poncho",
            "talla 8",
            "Carlos Pérez",
            "Bucaramanga",
        )
        turno = hablar(bot, "Calle 45 #12-30")[0]
        assert [n for _, n in turno.respuesta.adjuntos() if n.startswith("vista_")]

    def test_si_cambia_un_color_la_foto_es_otra(self, bot):
        hablar(bot, "quiero un anillo de 1 huellita")
        primera = hablar(bot, "corazón rojo y dedos blancos")[0]
        segunda = hablar(bot, "no mejor corazón lila y dedos morados")[0]
        assert primera.respuesta.imagenes() != segunda.respuesta.imagenes()

    def test_sin_dibujante_la_conversacion_es_la_misma(self):
        customers = InMemoryCustomerRepository()
        customers.upsert(
            Customer(id="c1", channel=Channel.WHATSAPP, channel_user_id="573001112233")
        )
        mundo = Mundo(
            InMemoryOrderRepository(), customers, _productos(), ContextoEnMemoria()
        )
        pelado = Pipeline(
            Interprete(ModeloDeMadera(), "", ""), mundo, Ejecutor(mundo), Redactor()
        )
        hablar(pelado, "quiero un anillo de 1 huellita")
        turno = hablar(pelado, "corazón rojo y dedos blancos")[0]
        assert "grabamos" in turno.respuesta.texto_plano.lower()


# ═══════════════════════════════════════════════════════════════════════════
# AYUDARLA A ESCOGER
# ═══════════════════════════════════════════════════════════════════════════


class TestLasSugerencias:
    @pytest.mark.parametrize(
        "pregunta",
        [
            "¿cuál me recomiendas?",
            "no sé cuál escoger",
            "ayúdame a elegir",
            "qué me sugieres",
            "el que tú digas",
            "no tengo idea",
            "cuál se ve mejor",
        ],
    )
    def test_pedir_ayuda_saca_las_tres(self, bot, pregunta):
        hablar(bot, "quiero un anillo de 1 huellita")
        turno = hablar(bot, pregunta)[0]
        assert turno.decision.accion is Accion.SUGERIR_COMBINACION
        for s in COMBINACIONES:
            assert s.nombre in turno.respuesta.texto_plano

    def test_van_con_su_foto_cada_una(self, bot):
        hablar(bot, "quiero un anillo de 1 huellita")
        turno = hablar(bot, "¿cuál me recomiendas?")[0]
        vistas = [n for _, n in turno.respuesta.adjuntos() if n.startswith("vista_")]
        assert len(vistas) == len(COMBINACIONES)
        assert len(set(vistas)) == len(COMBINACIONES), "mandó la misma foto tres veces"

    def test_la_ultima_palabra_es_SIEMPRE_de_la_clienta(self, bot):
        """Una sugerencia que suena a decisión tomada se lleva puesto lo que
        la clienta quería, y encima la deja sin ganas de corregir."""
        hablar(bot, "quiero un anillo de 1 huellita")
        texto = hablar(bot, "¿cuál me recomiendas?")[0].respuesta.texto_plano.lower()
        assert "dime cuál te gusta" in texto
        assert "otra combinación" in texto

    @pytest.mark.parametrize(
        "eleccion, corazon",
        [
            ("la elegante", ColorCircon.VERDE_ESMERALDA),
            ("la segunda", ColorCircon.ROJO),
            ("la 3", ColorCircon.LILA),
            ("me gusta la clásica", ColorCircon.ROJO),
            ("la dulce", ColorCircon.LILA),
        ],
    )
    def test_escoger_una_la_deja_anotada(self, bot, eleccion, corazon):
        hablar(bot, "quiero un anillo de 1 huellita", "¿cuál me recomiendas?")
        turno = hablar(bot, eleccion)[0]
        proceso = turno.contexto.abiertos()[0]
        assert proceso.datos["colores"][0]["corazon"] == corazon.value

    def test_puede_pedir_una_combinacion_que_no_estaba(self, bot):
        """Sugerir no es decidir: si escribe otra cosa, manda ella."""
        hablar(bot, "quiero un anillo de 1 huellita", "¿cuál me recomiendas?")
        turno = hablar(bot, "mejor corazón negro y dedos amarillos")[0]
        assert turno.contexto.abiertos()[0].datos["colores"] == [
            {"corazon": "NEGRO", "dedos": "AMARILLO"}
        ]

    def test_fuera_de_ese_momento_la_segunda_no_es_una_combinacion(self, bot):
        """«La segunda» habla de un pedido, salvo justo después de las tres."""
        hablar(bot, "quiero un anillo de 1 huellita")
        turno = hablar(bot, "la segunda")[0]
        assert not turno.contexto.abiertos()[0].datos.get("colores")
