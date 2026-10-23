"""VentaBot trabaja solo con modelos en línea: nunca cae a Ollama por su cuenta."""

import pytest

from app.adapters.llm.ollama_client import FakeLLM
from app.infra import container as contenedor
from app.infra.settings import Settings


@pytest.fixture
def sin_ollama(monkeypatch):
    def prohibido(*_a, **_k):
        raise AssertionError("VentaBot no debe crear un modelo de Ollama")

    monkeypatch.setattr(contenedor, "OllamaLLM", prohibido)


def test_claude_sin_clave_no_cae_a_un_modelo_local(tmp_path, sin_ollama):
    s = Settings(
        sqlite_path=tmp_path / "t.db",
        repository_backend="memory",
        llm_backend="claude",
        anthropic_api_key="",
        llm_fuerte_model="claude-sonnet-5",
        llm_vision_model="claude-haiku-4-5",
        payment_backend="fake",
        channel_backend="console",
        ventas_excel=tmp_path / "v.xlsx",
    )
    c = contenedor.build_container(s)
    assert isinstance(c.llm, FakeLLM)


def test_un_modelo_fuerte_que_no_es_en_linea_no_se_usa(tmp_path, sin_ollama):
    s = Settings(
        sqlite_path=tmp_path / "t.db",
        repository_backend="memory",
        llm_backend="fake",
        llm_fuerte_model="gemma4:12b",
        payment_backend="fake",
        channel_backend="console",
        ventas_excel=tmp_path / "v.xlsx",
    )
    contenedor.build_container(s)
