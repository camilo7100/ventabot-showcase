"""Tests del activador del número.

El valor de este script no está en llamar a dos endpoints —eso es trivial—
sino en TRADUCIR los errores de Meta a algo accionable. El mensaje crudo de
Graph casi nunca dice qué hacer, y ahí es donde la gente se atasca.
"""

from __future__ import annotations

from scripts.registrar_numero import EXPLICACIONES, es_numero_de_prueba, explicar


def test_un_token_caducado_dice_como_regenerarlo(self=None):
    lineas = explicar({"error": {"code": 190, "message": "Session has expired"}})
    texto = " ".join(lineas)
    assert "Session has expired" in texto  # se conserva el original
    assert "Generar" in texto  # y se añade el arreglo


def test_un_identificador_malo_apunta_al_env():
    lineas = explicar({"error": {"code": 100, "message": "Unsupported get request"}})
    assert any("WA_PHONE_NUMBER_ID" in ln for ln in lineas)


def test_un_pin_equivocado_explica_la_opcion_pin():
    lineas = explicar({"error": {"code": 133005, "message": "Two-step PIN mismatch"}})
    assert any("--pin" in ln for ln in lineas)


def test_un_error_desconocido_no_revienta_y_conserva_el_mensaje():
    lineas = explicar({"error": {"code": 999999, "message": "algo raro"}})
    assert lineas == ["algo raro"]


def test_un_cuerpo_sin_error_no_revienta():
    assert explicar({}) == ["sin mensaje"]


def test_todas_las_explicaciones_dicen_que_hacer():
    """Una explicación que solo describe el problema no sirve de nada."""
    verbos = ("genera", "revisa", "cópialos", "espera", "pásalo", "genéralo")
    for codigo, lineas in EXPLICACIONES.items():
        texto = " ".join(lineas).lower()
        assert any(v in texto for v in verbos), f"el código {codigo} no dice qué hacer"


class TestNumeroDePrueba:
    """Los números que regala Meta ya vienen registrados.

    Llamar a /register sobre uno da «Two step verification PIN Mismatch», un
    error que asusta y que no hay que arreglar. Detectarlo evita que alguien
    persiga un PIN que nunca existió.
    """

    def test_reconoce_el_numero_de_prueba_por_el_nombre(self):
        assert es_numero_de_prueba(
            {"verified_name": "Test Number", "display_phone_number": "+1 555-200-2511"}
        )

    def test_lo_reconoce_tambien_solo_por_el_numero(self):
        assert es_numero_de_prueba({"display_phone_number": "+1 555-123-4567"})

    def test_un_numero_real_colombiano_no_se_confunde(self):
        assert not es_numero_de_prueba(
            {"verified_name": "Mi Negocio", "display_phone_number": "+57 300 111 2233"}
        )

    def test_sin_datos_no_revienta(self):
        assert not es_numero_de_prueba({})
