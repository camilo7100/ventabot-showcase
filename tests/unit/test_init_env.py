"""Tests del creador de `.env`.

El escenario que protegen: alguien corre `vb init-env` dos veces y se le borran
las credenciales que ya había puesto. Eso no puede pasar nunca.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
from dotenv import dotenv_values

RAIZ = Path(__file__).resolve().parents[2]


@pytest.fixture
def proyecto(tmp_path):
    """Una copia mínima del proyecto: el ejemplo y el script."""
    (tmp_path / "scripts").mkdir()
    (tmp_path / ".env.example").write_text(
        (RAIZ / ".env.example").read_text(encoding="utf-8"), encoding="utf-8"
    )
    (tmp_path / "scripts" / "init_env.py").write_text(
        (RAIZ / "scripts" / "init_env.py").read_text(encoding="utf-8"), encoding="utf-8"
    )
    return tmp_path


def correr(proyecto: Path, *args: str) -> subprocess.CompletedProcess:
    # PYTHONPATH apunta al proyecto real porque init_env.py importa
    # app.infra.consola (el helper que evita que el script muera al redirigir la
    # salida en Windows). La carpeta temporal solo tiene el script y el ejemplo.
    entorno = {**os.environ, "PYTHONPATH": str(RAIZ)}
    return subprocess.run(
        [sys.executable, "scripts/init_env.py", *args],
        cwd=proyecto,
        capture_output=True,
        text=True,
        timeout=30,
        env=entorno,
    )


def test_crea_el_env_desde_el_ejemplo(proyecto):
    assert correr(proyecto).returncode == 0
    assert (proyecto / ".env").exists()


def test_genera_un_verify_token(proyecto):
    """Es un valor que inventa el usuario, no Meta. Mejor generado que tecleado."""
    correr(proyecto)
    token = dotenv_values(proyecto / ".env")["META_VERIFY_TOKEN"]
    assert token and len(token) >= 20


def test_dos_ejecuciones_dan_tokens_distintos(proyecto, tmp_path_factory):
    otro = tmp_path_factory.mktemp("otro")
    (otro / "scripts").mkdir()
    for f in (".env.example",):
        (otro / f).write_text(
            (proyecto / f).read_text(encoding="utf-8"), encoding="utf-8"
        )
    (otro / "scripts" / "init_env.py").write_text(
        (proyecto / "scripts" / "init_env.py").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    correr(proyecto)
    correr(otro)
    a = dotenv_values(proyecto / ".env")["META_VERIFY_TOKEN"]
    b = dotenv_values(otro / ".env")["META_VERIFY_TOKEN"]
    assert a != b


def test_no_pisa_un_env_existente(proyecto):
    """EL test importante: no puede borrar credenciales ya puestas."""
    correr(proyecto)
    (proyecto / ".env").write_text(
        "WA_ACCESS_TOKEN=EAAmiTokenReal\nMETA_VERIFY_TOKEN=elmio\n", encoding="utf-8"
    )
    r = correr(proyecto)
    assert r.returncode == 0
    v = dotenv_values(proyecto / ".env")
    assert v["WA_ACCESS_TOKEN"] == "EAAmiTokenReal"


def test_con_force_hace_copia_de_seguridad(proyecto):
    correr(proyecto)
    (proyecto / ".env").write_text("WA_ACCESS_TOKEN=EAAviejo\n", encoding="utf-8")
    correr(proyecto, "--force")
    assert (proyecto / ".env.anterior").exists()
    assert "EAAviejo" in (proyecto / ".env.anterior").read_text(encoding="utf-8")


def test_el_env_creado_no_tiene_valores_que_son_comentarios(proyecto):
    correr(proyecto)
    v = dotenv_values(proyecto / ".env")
    malos = {k: x for k, x in v.items() if x and x.lstrip().startswith("#")}
    assert not malos, malos
