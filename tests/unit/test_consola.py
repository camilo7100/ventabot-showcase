"""Tests de la salida por terminal.

El bug que protegen es real y costó una ronda entera de ida y vuelta:

    UnicodeEncodeError: 'charmap' codec can't encode character '\\u2714'

En Windows, cuando la salida va a una tubería o a un archivo, Python usa
cp1252, donde el carácter ✔ no existe. El script MORÍA — aunque su trabajo ya
estuviera hecho: `init_env.py` creaba el `.env` correctamente y luego terminaba
con código 1 al intentar imprimir el mensaje de éxito.

Es el peor tipo de error: el programa hace bien su trabajo y aun así reporta
fallo. Y solo aparece al redirigir, que es justo lo que uno hace para pedir
ayuda con un problema.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from app.infra.consola import (
    CON_COLOR,
    SIN_COLOR,
    Colores,
    preparar_salida,
    soporta_color,
)

RAIZ = Path(__file__).resolve().parents[2]


class TestColores:
    def test_sin_terminal_no_hay_codigos_de_color(self):
        """Redirigido a un archivo, los códigos ANSI son basura ilegible."""
        assert SIN_COLOR.hay_color is False
        assert SIN_COLOR.ok == ""
        assert SIN_COLOR.fin == ""

    def test_con_terminal_si_hay_color(self):
        assert CON_COLOR.hay_color is True
        assert CON_COLOR.ok.startswith("\033[")

    def test_las_dos_paletas_tienen_los_mismos_campos(self):
        """Si alguien añade un color a una y olvida la otra, revienta al usarlo."""
        assert set(vars(CON_COLOR)) == set(vars(SIN_COLOR))

    def test_no_color_desactiva_el_color(self, monkeypatch):
        monkeypatch.setenv("NO_COLOR", "1")
        assert soporta_color() is False

    def test_force_color_lo_fuerza(self, monkeypatch):
        monkeypatch.delenv("NO_COLOR", raising=False)
        monkeypatch.setenv("FORCE_COLOR", "1")
        assert soporta_color() is True

    def test_un_stream_raro_no_tumba_nada(self, monkeypatch):
        monkeypatch.delenv("NO_COLOR", raising=False)
        monkeypatch.delenv("FORCE_COLOR", raising=False)

        class Raro:
            def isatty(self):
                raise OSError("stream cerrado")

        assert soporta_color(Raro()) is False

    def test_preparar_salida_devuelve_una_paleta(self):
        assert isinstance(preparar_salida(), Colores)


# ---------------------------------------------------------------------------
# El test que reproduce el bug original
# ---------------------------------------------------------------------------

#: Scripts que imprimen ✔ / ✘ / ○ y que el usuario redirige a un archivo.
SCRIPTS = [
    "init_env.py",
    "preflight.py",
    "f0_determinismo.py",
    "f1_check.py",
    "simular_whatsapp.py",
    "demo.py",
]


@pytest.mark.parametrize("script", SCRIPTS)
def test_ningun_script_revienta_con_la_codificacion_de_windows(script, tmp_path):
    """Cada script debe poder importarse y arrancar con stdout en cp1252.

    Se ejecuta con `--help` (o equivalente) para no hacer trabajo real: lo que
    se comprueba es que la CONFIGURACIÓN de la salida no explote.
    """
    # HERMÉTICO. La primera versión heredaba el entorno tal cual, así que en la
    # máquina del usuario `demo.py` leía su .env con LLM_BACKEND=ollama,
    # golpeaba el modelo de verdad y agotaba el tiempo límite. Un test que
    # depende de la configuración de quien lo corre no prueba lo que dice.
    entorno = {
        **os.environ,
        "PYTHONIOENCODING": "cp1252",
        "LLM_BACKEND": "fake",
        "CHANNEL_BACKEND": "console",
        "PAYMENT_BACKEND": "fake",
        "REPOSITORY_BACKEND": "memory",
    }
    r = subprocess.run(
        [sys.executable, f"scripts/{script}", "--help"],
        cwd=RAIZ,
        env=entorno,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert r.returncode == 0, (
        f"scripts/{script} --help debería imprimir la ayuda y salir, "
        f"no ejecutar trabajo real:\n{(r.stdout + r.stderr)[-600:]}"
    )
    salida = r.stdout + r.stderr
    assert "UnicodeEncodeError" not in salida, (
        f"scripts/{script} muere al redirigir la salida en Windows:\n{salida[-800:]}"
    )


def test_init_env_termina_bien_aunque_la_consola_sea_cp1252(tmp_path):
    """La reproducción exacta del fallo: creaba el .env y salía con código 1."""
    (tmp_path / "scripts").mkdir()
    (tmp_path / ".env.example").write_text(
        (RAIZ / ".env.example").read_text(encoding="utf-8"), encoding="utf-8"
    )
    (tmp_path / "scripts" / "init_env.py").write_text(
        (RAIZ / "scripts" / "init_env.py").read_text(encoding="utf-8"), encoding="utf-8"
    )
    # init_env importa app.infra.consola desde la raíz del proyecto.
    entorno = {
        **os.environ,
        "PYTHONIOENCODING": "cp1252",
        "PYTHONPATH": str(RAIZ),
    }
    r = subprocess.run(
        [sys.executable, "scripts/init_env.py"],
        cwd=tmp_path,
        env=entorno,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert r.returncode == 0, r.stdout + r.stderr
    assert (tmp_path / ".env").exists()
    assert "UnicodeEncodeError" not in (r.stdout + r.stderr)


def test_la_salida_redirigida_no_lleva_codigos_de_color(tmp_path):
    """Un archivo de diagnóstico lleno de ESC[92m no se puede leer.

    Nota: aquí NO se invoca `preflight.py`, aunque sería el candidato obvio.
    El preflight ejecuta pytest como parte de sus comprobaciones, así que
    llamarlo desde un test crea una recursión infinita: pytest -> preflight ->
    pytest -> ... Se descubrió colgando la suite durante dos minutos.
    """
    (tmp_path / "scripts").mkdir()
    (tmp_path / ".env.example").write_text("ENTORNO=dev\n", encoding="utf-8")
    (tmp_path / ".env").write_text("ENTORNO=dev\n", encoding="utf-8")  # ya existe
    (tmp_path / "scripts" / "init_env.py").write_text(
        (RAIZ / "scripts" / "init_env.py").read_text(encoding="utf-8"), encoding="utf-8"
    )
    entorno = {**os.environ, "PYTHONPATH": str(RAIZ)}
    entorno.pop("FORCE_COLOR", None)
    r = subprocess.run(
        [sys.executable, "scripts/init_env.py"],
        cwd=tmp_path,
        env=entorno,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert r.returncode == 0
    assert r.stdout.strip(), "el script no imprimió nada; el test no prueba nada"
    assert "\033[" not in r.stdout, "hay códigos ANSI en una salida redirigida"
