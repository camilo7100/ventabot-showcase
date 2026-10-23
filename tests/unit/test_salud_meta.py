"""Lo que Meta dice del número se traduce a qué hacer (03/10)."""

from __future__ import annotations

from app.domain.salud_meta import leer_salud

#: Lo que devolvió Meta el 03/10/2026 (ids cambiados).
DEL_03_10 = {
    "can_send_message": "BLOCKED",
    "entities": [
        {
            "entity_type": "PHONE_NUMBER",
            "can_send_message": "LIMITED",
            "errors": [{"error_code": 138024, "error_description": "SIP"}],
        },
        {
            "entity_type": "WABA",
            "can_send_message": "BLOCKED",
            "errors": [{"error_code": 141006, "error_description": "payment"}],
        },
        {
            "entity_type": "BUSINESS",
            "can_send_message": "LIMITED",
            "errors": [{"error_code": 141010, "error_description": "verification"}],
        },
        {
            "entity_type": "APP",
            "can_send_message": "AVAILABLE",
            "errors": [{"error_code": 138025, "error_description": "SIP"}],
        },
    ],
}


def test_el_pago_bloquea_y_dice_que_hacer():
    s = leer_salud(DEL_03_10)
    assert s.estado == "BLOCKED"
    assert len(s.problemas) == 2
    assert "método de pago" in s.problemas[0]
    assert "verificada" in s.problemas[1]


def test_las_llamadas_por_sip_no_cuentan():
    solo_sip = {"entities": [DEL_03_10["entities"][0], DEL_03_10["entities"][3]]}
    s = leer_salud(solo_sip)
    assert s.estado == "AVAILABLE"
    assert s.problemas == []


def test_un_codigo_desconocido_usa_el_texto_de_meta():
    s = leer_salud(
        {
            "entities": [
                {
                    "can_send_message": "LIMITED",
                    "errors": [{"error_code": 1, "error_description": "algo nuevo"}],
                }
            ]
        }
    )
    assert (s.estado, s.problemas) == ("LIMITED", ["algo nuevo"])


def test_sin_datos_esta_bien():
    assert leer_salud(None).estado == "AVAILABLE"
