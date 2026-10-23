"""Tests del `.env.example`.

Parecen triviales. No lo son: el bug que atrapa el primero se manifiesta en la
Fase 1 como "Meta rechaza mi firma" con un token que *parece* configurado, y se
tarda una hora en encontrar.

    WA_ACCESS_TOKEN=            # usa un System User token

python-dotenv parsea eso como el valor literal `"# usa un System User token"`.
La variable NO queda vacía, así que ninguna validación de "campo obligatorio"
salta, y te vas a producción con un token que es un comentario.

Regla: en los `.env`, los comentarios van SIEMPRE en su propia línea.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from dotenv import dotenv_values

RAIZ = Path(__file__).resolve().parents[2]
EJEMPLO = RAIZ / ".env.example"


@pytest.fixture(scope="module")
def valores() -> dict[str, str | None]:
    return dotenv_values(EJEMPLO)


def test_el_ejemplo_existe():
    assert EJEMPLO.exists(), "sin .env.example nadie sabe qué variables hacen falta"


def test_ningun_valor_es_en_realidad_un_comentario(valores):
    culpables = {k: v for k, v in valores.items() if v and v.lstrip().startswith("#")}
    assert not culpables, (
        "Estas claves tienen un comentario como valor. Mueve el comentario a su "
        f"propia línea: {list(culpables)}"
    )


def test_no_hay_comentarios_en_la_misma_linea(valores):
    """Defensa estructural: prohibimos la forma peligrosa, no solo su síntoma."""
    ofensores = []
    for n, linea in enumerate(EJEMPLO.read_text(encoding="utf-8").splitlines(), 1):
        limpia = linea.strip()
        if not limpia or limpia.startswith("#") or "=" not in limpia:
            continue
        if "#" in limpia.split("=", 1)[1]:
            ofensores.append(f"línea {n}: {limpia}")
    assert not ofensores, "comentarios en la misma línea que un valor:\n" + "\n".join(
        ofensores
    )


def test_estan_todas_las_claves_que_el_codigo_espera(valores):
    """Si añades un campo a Settings y olvidas documentarlo aquí, esto falla."""
    from app.infra.settings import Settings

    # Campos que tienen un default sensato y no necesitan estar en el ejemplo.
    opcionales = {
        "log_level",
        "log_archivo",
        "reglas_path",
        "catalogo_csv",
        "promociones_csv",
        "banco_plantillas_json",
        "banco_plantillas_activos",
        "fletes_csv",
        "ollama_vision_model",
        # rutas y afinados internos: default sensato, casi nadie los toca
        "sqlite_path",
        "dispatcher_interval_s",
    }
    # El alias manda sobre el nombre del campo: es el que se escribe en el
    # .env. `url_publica_override` se pone como URL_PUBLICA, no como
    # URL_PUBLICA_OVERRIDE.
    esperadas = {
        (campo.alias or nombre).upper()
        for nombre, campo in Settings.model_fields.items()
        if nombre not in opcionales
    }
    faltan = esperadas - set(valores)
    assert not faltan, f"claves de Settings sin documentar en .env.example: {faltan}"


def test_no_hay_secretos_reales_en_el_ejemplo(valores):
    """El .env.example SÍ se sube a Git. No puede traer credenciales."""
    sensibles = [
        k for k in valores if any(t in k for t in ("TOKEN", "SECRET", "KEY", "PASSWORD"))
    ]
    assert sensibles, "el test no está mirando ninguna clave sensible"
    con_valor = {
        k: valores[k]
        for k in sensibles
        if valores[k] and not valores[k].startswith(("postgresql://", "redis://", "http"))
    }
    assert not con_valor, f"¡hay secretos en .env.example!: {list(con_valor)}"


def test_el_gitignore_protege_el_env():
    gi = (RAIZ / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert ".env" in [ln.strip() for ln in gi]
