"""Las trazas de LangSmith: auditables cuando están encendidas, invisibles
cuando no (app/infra/trazas.py)."""


class TestAuditableEnLangSmith:
    """Con las trazas encendidas, cada llamada al modelo lleva sus tokens y cada
    turno sus etiquetas. Se prueba contra un nodo falso: sin red ni cuenta."""

    def test_tokens_y_etiquetas_llegan_al_nodo(self, monkeypatch):
        from app.infra import trazas

        class Nodo:
            def __init__(self):
                self.meta, self.uso, self.tags = {}, None, []

            def add_metadata(self, d):
                self.meta.update(d)

            def set(self, *, usage_metadata):
                self.uso = usage_metadata

            def add_tags(self, t):
                self.tags += t

        nodo = Nodo()
        monkeypatch.setattr(trazas, "_arbol", lambda: nodo)
        trazas.uso_del_modelo(
            "claude-haiku-4-5", entrada=100, salida=50, cache_leida=4000
        )
        trazas.etiquetar("capa:basico", "", "escalado")
        assert nodo.meta["ls_model_name"] == "claude-haiku-4-5"
        assert nodo.uso["input_tokens"] == 4100 and nodo.uso["output_tokens"] == 50
        assert nodo.uso["input_token_details"]["cache_read"] == 4000
        assert nodo.tags == ["capa:basico", "escalado"], "las vacías no se mandan"

    def test_cada_llamada_dice_su_proveedor_y_su_capa(self, monkeypatch):
        """29/09: en LangSmith todas las llamadas se llamaban «modelo» y decían
        «anthropic», también las de GPT. Ahora cada una lleva lo suyo."""
        from app.domain import consumo
        from app.infra import trazas

        class Nodo:
            def __init__(self):
                self.meta, self.tags = {}, []

            def add_metadata(self, d):
                self.meta.update(d)

            def set(self, **kw):
                pass

            def add_tags(self, t):
                self.tags += t

        nodo = Nodo()
        monkeypatch.setattr(trazas, "_arbol", lambda: nodo)
        with consumo.capa("fuerte"):
            trazas.uso_del_modelo(
                "gpt-6-luna", entrada=34, salida=160, cache_leida=9180, proveedor="openai"
            )
        assert nodo.meta["ls_provider"] == "openai"
        assert nodo.meta["capa"] == "fuerte"
        assert nodo.tags == ["llamada:fuerte"]

    def test_apagadas_no_hacen_nada(self):
        from app.infra import trazas

        trazas._ACTIVO = False
        trazas.uso_del_modelo("x", entrada=1, salida=1)
        trazas.etiquetar("y")
