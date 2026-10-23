"""Las promociones activas (Camilo, 17/10).

Martha preguntó por «dos anillos por el precio de uno» que vio publicado. No
había ninguna promoción y el bot no tenía dónde mirarlo. Ahora está la lista
(`data/promociones.csv`): vacía, el bot dice que no hay; nunca inventa una.
"""

from datetime import date
from pathlib import Path

import pytest

from app.adapters.repositories.csv_files import cargar_promociones_csv
from app.domain.asesora import vigilar
from app.domain.promociones import (
    Promocion,
    linea_del_estado,
    pregunta_por_promociones,
    promete_una_promocion,
    vigentes,
)

RAIZ = Path(__file__).resolve().parents[2]
HOY = date(2026, 10, 17)


def test_hoy_no_hay_ninguna():
    promos = cargar_promociones_csv(RAIZ / "data" / "promociones.csv")
    assert vigentes(promos, HOY) == []
    assert "NINGUNA" in linea_del_estado([])


def test_la_vigencia_va_sola_por_las_fechas(tmp_path):
    ruta = tmp_path / "p.csv"
    ruta.write_text(
        "nombre,detalle,desde,hasta,activa\n"
        "Amor y amistad,10% en el anillo de corazón,2026-09-01,2026-09-30,TRUE\n"
        "Navidad,envío gratis,2026-12-01,2026-12-24,TRUE\n"
        "Apagada,lo que sea,,,FALSE\n"
        "Rota,fecha mala,2026-13-01,,TRUE\n",
        encoding="utf-8",
    )
    promos = cargar_promociones_csv(ruta)
    assert [p.nombre for p in promos] == ["Amor y amistad", "Navidad", "Apagada"]
    assert vigentes(promos, HOY) == []
    assert [p.nombre for p in vigentes(promos, date(2026, 12, 24))] == ["Navidad"]
    assert "Navidad: envío gratis" in linea_del_estado(
        vigentes(promos, date(2026, 12, 1))
    )


def test_sin_archivo_no_hay_promociones(tmp_path):
    assert cargar_promociones_csv(tmp_path / "no.csv") == []


@pytest.mark.parametrize(
    "texto",
    [
        "vi una promo de dos por el precio de uno",
        "tienen 2x1?",
        "¿hay algún descuento?",
        "la oferta que publicaron",
    ],
)
def test_reconoce_cuando_pregunta(texto):
    assert pregunta_por_promociones(texto)


class TestLaRedDeSeguridad:
    @pytest.mark.parametrize(
        "frase",
        [
            "¡Sí! Tenemos 2x1 en anillos 💗",
            "Hoy te damos un 20% de descuento.",
            "Hay una promoción de dos por el precio de uno.",
            "El segundo anillo gratis 🎁",
        ],
    )
    def test_quita_la_promocion_inventada(self, frase):
        assert promete_una_promocion(frase)
        limpio, problemas = vigilar(f"¡Hola! {frase}", set())
        assert "Hola" in limpio and frase not in limpio
        assert any("promoción" in p for p in problemas)

    @pytest.mark.parametrize(
        "frase",
        [
            "En este momento no tenemos ninguna promoción activa 🤍",
            "No manejamos 2x1, pero lo separas con $60.000.",
            "Hoy no hay descuentos ni promociones.",
        ],
    )
    def test_decir_que_no_hay_si_se_puede(self, frase):
        assert not promete_una_promocion(frase)

    def test_una_promocion_cargada_si_se_puede_nombrar(self):
        activa = Promocion("Amor y amistad", "10% de descuento en el anillo de corazón")
        frase = "Tenemos la promoción de Amor y amistad: 10% de descuento 💗"
        assert promete_una_promocion(frase)
        assert not promete_una_promocion(frase, [activa])
