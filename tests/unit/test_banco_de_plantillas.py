"""El banco de plantillas por situación (22/10): el selector «primera aprobada».

Solo escoge; no manda nada. Un grupo no se usa hasta que Camilo lo prende, y
por defecto no hay ninguno prendido.
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.domain.banco_de_plantillas import (
    Banco,
    Grupo,
    Plantilla,
    armar,
    grupos_activos,
    roles_basicos,
)

RAIZ = Path(__file__).resolve().parents[2]
BANCO_REAL = RAIZ / "data" / "plantillas" / "banco.json"


def _banco() -> Banco:
    plantillas = {
        "datos_a": Plantilla(
            "datos_a",
            "UTILITY",
            "Hola {{1}}, tu abono es {{2}} del anillo {{3}} 💳 listo.",
            ("nombre", "monto", "codigo"),
            ("Enviar datos", "Ya pagué"),
        ),
        "datos_b": Plantilla(
            "datos_b",
            "UTILITY",
            "Hola {{1}} 💳 Los datos del abono de {{2}} aquí.",
            ("nombre", "monto"),
            ("Enviar datos",),
        ),
        "datos_c": Plantilla(
            "datos_c", "MARKETING", "Hola 💳 ¿Te paso los datos del abono?"
        ),
        "foto_a": Plantilla(
            "foto_a",
            "UTILITY",
            "Mira {{1}} 😍 tu anillo quedó listo.",
            ("nombre",),
            (),
            "IMAGE",
        ),
    }
    grupos = {
        "4.3": Grupo(
            "4.3", "Reenviar datos", "ambas", False, ("datos_a", "datos_b", "datos_c")
        ),
        "7.6": Grupo("7.6", "Foto del anillo", "fuera", False, ("foto_a",)),
        "9.9": Grupo("9.9", "Bloqueada", "fuera", True, ("datos_c",)),
    }
    return Banco(plantillas, grupos)


APROBADAS = {
    "datos_a": "APPROVED",
    "datos_b": "APPROVED",
    "datos_c": "APPROVED",
    "foto_a": "APPROVED",
}
TODO = {"nombre": "Laura", "monto": "$60.000", "codigo": "PED-2026-0364"}


class TestEscoger:
    def test_la_primera_aprobada_del_orden(self):
        e = _banco().escoger("4.3", APROBADAS, TODO)
        assert e.plantilla.nombre == "datos_a"
        assert (
            e.texto
            == "Hola Laura, tu abono es $60.000 del anillo PED-2026-0364 💳 listo."
        )
        assert e.parametros == {"1": "Laura", "2": "$60.000", "3": "PED-2026-0364"}

    def test_si_la_primera_sigue_en_revision_va_la_siguiente(self):
        estados = {**APROBADAS, "datos_a": "PENDING"}
        assert _banco().escoger("4.3", estados, TODO).plantilla.nombre == "datos_b"

    def test_si_a_la_primera_le_falta_un_dato_va_la_siguiente(self):
        sin_codigo = {"nombre": "Laura", "monto": "$60.000"}
        assert (
            _banco().escoger("4.3", APROBADAS, sin_codigo).plantilla.nombre == "datos_b"
        )

    def test_nunca_manda_con_un_hueco_ni_con_un_valor_vacio(self):
        assert (
            _banco().escoger(
                "4.3",
                {"datos_a": "APPROVED"},
                {"nombre": " ", "monto": "", "codigo": "x"},
            )
            is None
        )

    def test_la_sin_variables_siempre_sirve_si_esta_aprobada(self):
        estados = {"datos_a": "REJECTED", "datos_b": "PENDING", "datos_c": "APPROVED"}
        e = _banco().escoger("4.3", estados, {})
        assert e.plantilla.nombre == "datos_c" and e.parametros == {}

    def test_ninguna_aprobada_no_escoge(self):
        b = _banco()
        assert b.escoger("4.3", {"datos_a": "PENDING"}, TODO) is None
        assert "datos_a: PENDING" in b.por_que_no("4.3", {"datos_a": "PENDING"}, TODO)
        assert "falta codigo" in b.por_que_no(
            "4.3", {"datos_a": "APPROVED"}, {"nombre": "L", "monto": "1"}
        )

    def test_un_grupo_bloqueado_o_que_no_existe_no_escoge(self):
        b = _banco()
        assert b.escoger("9.9", APROBADAS, TODO) is None
        assert b.escoger("0.0", APROBADAS, TODO) is None

    def test_la_foto_va_aparte_y_es_obligatoria(self):
        b = _banco()
        assert b.escoger("7.6", APROBADAS, {"nombre": "Laura"}) is None
        e = b.escoger("7.6", APROBADAS, {"nombre": "Laura", "imagen": "https://x/y.jpg"})
        assert e.parametros == {"1": "Laura", "imagen": "https://x/y.jpg"}

    def test_se_arma_con_los_parametros_en_orden(self):
        e = armar("4.3", _banco().plantillas["datos_b"], TODO)
        assert list(e.parametros) == ["1", "2"]


def test_los_valores_de_siempre():
    assert roles_basicos("laura garcía", "Luna", "anillo") == {
        "nombre": "Laura",
        "mascota": "Luna",
        "pieza": "anillo",
    }
    assert roles_basicos(None, None, "cadena") == {
        "nombre": "de nuevo",
        "mascota": "tu peludito",
        "pieza": "cadena",
    }
    assert roles_basicos("+573001112233", "", "corazon")["nombre"] == "de nuevo"
    assert roles_basicos()["pieza"] == "anillo"


class TestActivacion:
    def test_hoy_no_hay_ningun_grupo_prendido(self):
        assert (
            grupos_activos(RAIZ / "data" / "plantillas" / "activos.json") == frozenset()
        )

    def test_sin_archivo_o_roto_tampoco(self, tmp_path):
        assert grupos_activos(tmp_path / "no.json") == frozenset()
        (tmp_path / "roto.json").write_text("{no", encoding="utf-8")
        assert grupos_activos(tmp_path / "roto.json") == frozenset()

    def test_el_contenedor_no_da_nada_si_el_grupo_no_esta_prendido(self, tmp_path):
        c = _contenedor(tmp_path, activos=[])
        try:
            assert (
                c.plantilla_del_grupo(
                    "4.3", TODO, conv="wa:573001112233", to="573001112233", clave="k"
                )
                is None
            )
        finally:
            c.cerrar()

    def test_prendido_da_el_mensaje_listo_pero_no_lo_manda(self, tmp_path):
        c = _contenedor(tmp_path, activos=["4.3"])
        c._estados_banco = (
            datetime.now(UTC),
            {"datos_a": "PENDING", "datos_b": "APPROVED"},
        )
        try:
            m = c.plantilla_del_grupo(
                "4.3", TODO, conv="wa:573001112233", to="573001112233", clave="k1"
            )
            assert m.kind == "template" and m.template_name == "datos_b"
            assert m.template_params == {"1": "Laura", "2": "$60.000"}
            assert m.text.startswith("Hola Laura 💳")
            assert c.outbox.pending(10) == [], "escoger no manda nada"
        finally:
            c.cerrar()


def _contenedor(tmp_path, activos):
    from app.infra import container as contenedor
    from app.infra.settings import Settings

    banco = tmp_path / "banco.json"
    banco.write_text(
        json.dumps(
            {
                "plantillas": [
                    {
                        "nombre": "datos_a",
                        "categoria": "UTILITY",
                        "cuerpo": "Hola {{1}}, {{2}} y {{3}} ok",
                        "variables": ["nombre", "monto", "codigo"],
                        "botones": [],
                        "encabezado": None,
                    },
                    {
                        "nombre": "datos_b",
                        "categoria": "UTILITY",
                        "cuerpo": "Hola {{1}} 💳 abono de {{2}} aquí",
                        "variables": ["nombre", "monto"],
                        "botones": [],
                        "encabezado": None,
                    },
                ],
                "grupos": [
                    {
                        "grupo": "4.3",
                        "situacion": "x",
                        "ventana": "ambas",
                        "bloqueada": False,
                        "orden": [
                            {"nombre": "datos_a", "existente": False},
                            {"nombre": "datos_b", "existente": False},
                        ],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    prendidos = tmp_path / "activos.json"
    prendidos.write_text(json.dumps(activos), encoding="utf-8")
    s = Settings(
        sqlite_path=tmp_path / "b.db",
        repository_backend="memory",
        llm_backend="fake",
        payment_backend="fake",
        channel_backend="console",
        meta_app_secret="s",
        meta_verify_token="v",
        chatwoot_webhook_token="",
        ventas_excel=tmp_path / "v.xlsx",
        banco_plantillas_json=banco,
        banco_plantillas_activos=prendidos,
    )
    return contenedor.build_container(s)


class TestElBancoReal:
    """El archivo que viaja con el código (copia de marketing-lia): bien formado."""

    @pytest.fixture(scope="class")
    def datos(self):
        return json.loads(BANCO_REAL.read_text(encoding="utf-8"))

    def test_carga_y_tiene_todo(self, datos):
        b = Banco.desde_json(BANCO_REAL)
        assert len(b.plantillas) == len(datos["plantillas"]) >= 344
        assert len(b.grupos) >= 100

    def test_cada_nombre_de_cada_grupo_existe_o_ya_estaba_en_uso(self):
        b = Banco.desde_json(BANCO_REAL)
        for g in b.grupos.values():
            for n in g.orden:
                assert n in b.plantillas or n in g.existentes, (g.id, n)

    def test_cumple_lo_que_meta_exige(self, datos):
        for t in datos["plantillas"]:
            c = t["cuerpo"]
            assert not re.match(r"\s*[^\w\s]*\{\{", c), (
                f"{t['nombre']}: empieza en variable"
            )
            assert not re.search(r"\{\{\d+\}\}[^\w]*$", c), (
                f"{t['nombre']}: termina en variable"
            )
            n = len(set(re.findall(r"\{\{(\d+)\}\}", c)))
            assert len(t["variables"]) == n, f"{t['nombre']}: variables ≠ huecos"
            assert len(t["ejemplos"]) == n, f"{t['nombre']}: faltan ejemplos"
            assert len(c) <= 1024
            for boton in t["botones"]:
                assert len(boton) <= 25 and re.fullmatch(r"[\w¿?¡!,.:'· ]+", boton), (
                    f"{t['nombre']}: botón «{boton}» con símbolos"
                )

    def test_sin_numeros_de_cuenta_ni_direccion(self, datos):
        for t in datos["plantillas"]:
            assert not re.search(r"\d{9,}", t["cuerpo"]), t["nombre"]
            assert "torre" not in t["cuerpo"].lower(), t["nombre"]

    def test_ningun_grupo_viene_prendido(self):
        assert json.loads((BANCO_REAL.parent / "activos.json").read_text()) == []


class TestLaLimpieza:
    def _plan(self, estados, banco=None):
        from scripts.banco_de_plantillas import plan_de_limpieza

        return plan_de_limpieza(banco or _banco(), estados)

    def test_se_queda_la_primera_aprobada_y_se_borran_las_otras(self):
        plan = self._plan(
            {"datos_a": "PENDING", "datos_b": "APPROVED", "datos_c": "PENDING"}
        )
        assert plan["quedan"] == {"datos_b": "4.3"}
        assert [b["nombre"] for b in plan["borrar"]] == ["datos_a"]
        assert "datos_c" in plan["se_salvaron"], "la espera el grupo bloqueado"

    def test_un_grupo_sin_aprobada_no_se_toca(self):
        plan = self._plan({"datos_a": "PENDING", "datos_b": "PENDING"})
        assert plan["quedan"] == {} and plan["borrar"] == []

    def test_lo_que_esta_en_uso_nunca_se_borra(self):
        plantillas = {
            n: Plantilla(n, "UTILITY", "Hola")
            for n in ("asesora_te_atiende_2", "pedido_despachado", "nueva", "primera")
        }
        banco = Banco(
            plantillas,
            {
                "1.1": Grupo(
                    "1.1",
                    "x",
                    "ambas",
                    False,
                    ("primera", "asesora_te_atiende_2", "pedido_despachado", "nueva"),
                )
            },
        )
        estados = {n: "APPROVED" for n in plantillas}
        plan = self._plan(estados, banco)
        assert [b["nombre"] for b in plan["borrar"]] == ["nueva"]
        assert plan["se_salvaron"]["asesora_te_atiende_2"] == "en uso: protegida"
        assert plan["se_salvaron"]["pedido_despachado"] == "en uso: protegida"

    def test_lo_que_usa_otro_grupo_se_queda(self):
        plantillas = {n: Plantilla(n, "UTILITY", "Hola") for n in ("a", "b", "c")}
        banco = Banco(
            plantillas,
            {
                "1.1": Grupo("1.1", "x", "ambas", False, ("a", "b")),
                "1.2": Grupo("1.2", "y", "ambas", False, ("b", "c")),
            },
        )
        plan = self._plan({"a": "APPROVED", "b": "APPROVED", "c": "PENDING"}, banco)
        assert plan["quedan"] == {"a": "1.1", "b": "1.2"}
        assert [b["nombre"] for b in plan["borrar"]] == ["c"]

    def test_lo_que_espera_otro_grupo_sin_aprobada_se_salva(self):
        plantillas = {n: Plantilla(n, "UTILITY", "Hola") for n in ("a", "b")}
        banco = Banco(
            plantillas,
            {
                "1.1": Grupo("1.1", "x", "ambas", False, ("a", "b")),
                "1.2": Grupo("1.2", "y", "ambas", False, ("x_no", "b")),
            },
        )
        plan = self._plan({"a": "APPROVED", "b": "PENDING"}, banco)
        assert plan["borrar"] == [] and plan["se_salvaron"]["b"].startswith(
            "la espera otro grupo"
        )

    def test_lo_que_no_es_del_banco_no_se_toca(self):
        plan = self._plan({"datos_a": "APPROVED", "ajena_de_otro": "APPROVED"})
        assert all(b["nombre"] != "ajena_de_otro" for b in plan["borrar"])
