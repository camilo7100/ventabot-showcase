"""La documentación de `docs/sistema/` tiene que describir el sistema de HOY.

════════════════════════════════════════════════════════════════════════════
POR QUÉ ESTO ES UNA PRUEBA Y NO UNA BUENA INTENCIÓN
════════════════════════════════════════════════════════════════════════════
Documentación que envejece en silencio es peor que no tener ninguna: hace tomar
decisiones sobre un sistema que ya no existe, y nadie se entera hasta que algo
sale mal. «Acordarse de actualizarla» no es un mecanismo.

Así que se comprueba: si aparece un estado del pedido, una etiqueta de Chatwoot
o un comando de `vb` que la carpeta no menciona, esta prueba falla y dice cuál.
No revisa la redacción —eso no se puede automatizar—, revisa que no falte nada
y que no sobre nada inventado.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[2]
SISTEMA = RAIZ / "docs" / "sistema"


@pytest.fixture(scope="module")
def todo() -> str:
    """Toda la carpeta, en un solo texto."""
    return "\n".join(f.read_text(encoding="utf-8") for f in sorted(SISTEMA.glob("*.md")))


class TestLaCarpetaEstaCompleta:
    def test_estan_los_nueve_documentos_y_el_indice(self):
        esperados = {
            "README.md",
            "01-flujo-de-venta.md",
            "02-arquitectura.md",
            "03-reglas-de-negocio.md",
            "04-estados-del-pedido.md",
            "05-chatwoot-y-operacion.md",
            "06-datos-y-privacidad.md",
            "07-observabilidad.md",
            "08-erp.md",
            "09-glosario.md",
        }
        assert {f.name for f in SISTEMA.glob("*.md")} == esperados

    def test_el_indice_enlaza_a_todos(self):
        indice = (SISTEMA / "README.md").read_text(encoding="utf-8")
        for f in sorted(SISTEMA.glob("*.md")):
            if f.name != "README.md":
                assert f.name in indice, f"{f.name} no está en el índice"

    def test_ningun_enlace_apunta_a_un_archivo_que_no_existe(self, todo):
        for destino in re.findall(r"\]\((?!https?:)([^)#]+)\)", todo):
            ruta = (SISTEMA / destino).resolve()
            assert ruta.exists(), f"enlace roto: {destino}"


class TestDiceLoQueElCodigoHace:
    def test_estan_todos_los_estados_del_pedido(self):
        from app.domain.order_state import OrderState

        texto = (SISTEMA / "04-estados-del-pedido.md").read_text(encoding="utf-8")
        faltan = [e.value for e in OrderState if e.value not in texto]
        assert not faltan, f"estados sin documentar: {faltan}"

    def test_estan_todas_las_etiquetas_de_chatwoot(self):
        from app.domain.seguimiento import ACCIONES, ALERTAS, ETAPAS

        texto = (SISTEMA / "05-chatwoot-y-operacion.md").read_text(encoding="utf-8")
        etiquetas = [e[0] for e in (*ETAPAS, *ALERTAS, *ACCIONES)]
        faltan = [e for e in etiquetas if e not in texto]
        assert not faltan, f"etiquetas sin documentar: {faltan}"

    def test_las_carpetas_de_chatwoot_son_las_que_crea_el_script(self):
        import sys

        sys.path.insert(0, str(RAIZ))
        from scripts.chatwoot import CARPETAS

        texto = (SISTEMA / "05-chatwoot-y-operacion.md").read_text(encoding="utf-8")
        faltan = [nombre for nombre, _ in CARPETAS if nombre not in texto]
        assert not faltan, f"carpetas sin documentar: {faltan}"

    def test_esta_lo_que_se_guarda_de_un_anuncio(self):
        """Lo que se guarda de un anuncio y sus columnas del Excel (ADR 0028).

        Si `Referido` crece un campo o el Excel una columna del anuncio, marketing
        tiene que poder leer aquí qué es sin abrir el código."""
        from app.domain.anuncios import Referido
        from app.domain.ventas import COLUMNAS_VENTAS

        texto = (SISTEMA / "06-datos-y-privacidad.md").read_text(encoding="utf-8")
        campos = [f"`{c}`" for c in Referido.model_fields]
        columnas = [f"**{c.titulo}**" for c in COLUMNAS_VENTAS if "anuncio" in c.clave]
        faltan = [x for x in (*campos, *columnas) if x not in texto]
        assert not faltan, f"del anuncio, sin documentar: {faltan}"

    def test_los_comandos_que_se_nombran_existen(self, todo):
        """Un documento que manda correr algo que no existe hace perder media
        hora. Se comprueban los `vb <algo>` que aparecen escritos."""
        vb = (RAIZ / "vb.bat").read_text(encoding="cp1252")
        reales = set(re.findall(r'if /I "%~1"=="([\w-]+)"', vb))
        nombrados = set(re.findall(r"\bvb ([a-z][\w-]*)", todo))
        inventados = sorted(nombrados - reales)
        assert not inventados, f"comandos que no existen: {inventados}"

    def test_el_punto_de_recogida_no_se_copia_a_mano(self, todo):
        """Los datos del negocio viven en el código; aquí se dice DÓNDE están.
        Copiarlos es garantizar que un día digan cosas distintas."""
        from app.domain.faq import PUNTO_DE_RECOGIDA

        assert PUNTO_DE_RECOGIDA not in todo, (
            "el punto de recogida está copiado en la documentación: "
            "nombra `faq.PUNTO_DE_RECOGIDA` en vez de la dirección"
        )


class TestSeSabeCuandoSeVerifico:
    def test_el_indice_dice_la_fecha_de_la_ultima_revision(self):
        indice = (SISTEMA / "README.md").read_text(encoding="utf-8")
        assert re.search(r"Última verificación: \d{1,2} de \w+ de \d{4}", indice), (
            "sin fecha de verificación no se sabe si esto sigue siendo cierto"
        )
