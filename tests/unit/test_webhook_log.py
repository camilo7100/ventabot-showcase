"""Tests del registro de webhooks.

Guardar solo el ÚLTIMO webhook rechazado no alcanzaba: cuando se mezclan
mensajes reales con clics al botón «Probar», cada uno sobrescribe al anterior y
se acaba analizando el que no era. Este registro los guarda todos.
"""

from __future__ import annotations

import json

from app.adapters.repositories.webhook_log import leer, registrar

MENSAJE_REAL = json.dumps(
    {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": "1234567890123456",
                "changes": [
                    {
                        "field": "messages",
                        "value": {
                            "metadata": {"phone_number_id": "1234567890123456"},
                            "messages": [
                                {
                                    "from": "573001112233",
                                    "id": "wamid.ABC",
                                    "type": "text",
                                    "text": {"body": "hola"},
                                }
                            ],
                        },
                    }
                ],
            }
        ],
    }
).encode()

ACUSE_DE_ENTREGA = json.dumps(
    {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": "1234567890123456",
                "changes": [
                    {
                        "field": "messages",
                        "value": {
                            "statuses": [{"id": "wamid.X", "status": "delivered"}],
                        },
                    }
                ],
            }
        ],
    }
).encode()


def test_registra_lo_identificable_de_un_mensaje(tmp_path):
    ruta = tmp_path / "log.jsonl"
    registrar(ruta, cuerpo=MENSAJE_REAL, firma_valida=True, es_ejemplo=False, encolados=1)
    (f,) = leer(ruta)
    assert f["waba_id"] == "1234567890123456"
    assert f["de"] == "573001112233"
    assert f["texto"] == "hola"
    assert f["firma_valida"] is True
    assert f["encolados"] == 1


def test_distingue_un_acuse_de_entrega_de_un_mensaje(tmp_path):
    """Meta manda acuses además de mensajes. Si SOLO llegan acuses, es que
    nadie te ha escrito — y eso parece 'sí llegan webhooks' si no se separan."""
    ruta = tmp_path / "log.jsonl"
    registrar(ruta, cuerpo=ACUSE_DE_ENTREGA, firma_valida=True, es_ejemplo=False)
    (f,) = leer(ruta)
    assert f["n_mensajes"] == 0
    assert f["n_estados"] == 1
    assert f["estado"] == "delivered"


def test_acumula_en_vez_de_sobrescribir(tmp_path):
    """El defecto que motivó este registro."""
    ruta = tmp_path / "log.jsonl"
    for _ in range(5):
        registrar(ruta, cuerpo=MENSAJE_REAL, firma_valida=True, es_ejemplo=False)
    assert len(leer(ruta, 50)) == 5


def test_no_guarda_la_firma_ni_el_cuerpo_entero(tmp_path):
    ruta = tmp_path / "log.jsonl"
    registrar(ruta, cuerpo=MENSAJE_REAL, firma_valida=False, es_ejemplo=False)
    texto = ruta.read_text(encoding="utf-8")
    assert "sha256" not in texto
    assert "object" not in texto  # no está el payload crudo


def test_un_cuerpo_ilegible_no_rompe_nada(tmp_path):
    ruta = tmp_path / "log.jsonl"
    registrar(ruta, cuerpo=b"esto no es json", firma_valida=False, es_ejemplo=False)
    assert leer(ruta)[0]["tipo"] == "ilegible"


def test_una_linea_corrupta_no_impide_leer_las_demas(tmp_path):
    """Si el proceso muere a mitad de escribir, el resto debe seguir sirviendo."""
    ruta = tmp_path / "log.jsonl"
    registrar(ruta, cuerpo=MENSAJE_REAL, firma_valida=True, es_ejemplo=False)
    with ruta.open("a", encoding="utf-8") as fh:
        fh.write('{"cuando": "roto\n')
    registrar(ruta, cuerpo=MENSAJE_REAL, firma_valida=True, es_ejemplo=False)
    assert len(leer(ruta, 50)) == 2


def test_leer_un_registro_que_no_existe_devuelve_vacio(tmp_path):
    assert leer(tmp_path / "no_existe.jsonl") == []
