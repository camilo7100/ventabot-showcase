"""El diagnóstico no grita antes de que las cosas terminen de arrancar.

20/09. Corrido justo después de ENCENDER-BOT, daba dos rojos:

    ✘ el dominio de .env es el que está publicado
    ✘ el bot se ve desde internet — HTTP 404

Diez segundos después, los dos en verde: ngrok todavía estaba levantando la
entrada del dominio y contestaba su propia página de «aquí no hay nada».

Una falsa alarma es peor que no tener diagnóstico. Manda a Camilo a arreglar
algo que no está roto y, la vez que de verdad se rompa, no le va a creer.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RAIZ))

from scripts.diagnostico import _insistiendo  # noqa: E402


@pytest.fixture(autouse=True)
def sin_esperas(monkeypatch):
    """Los tests no duermen: solo importa CUÁNTAS veces se mira."""
    import scripts.diagnostico as d

    monkeypatch.setattr(d.time, "sleep", lambda _s: None)


class TestInsistir:
    def test_lo_que_ya_está_bien_se_mira_una_sola_vez(self):
        mirados = []

        def mirar():
            mirados.append(1)
            return 200

        assert _insistiendo(mirar, lambda c: c == 200) == 200
        assert len(mirados) == 1, "insistió sobre algo que ya estaba bien"

    def test_lo_que_tarda_en_arrancar_se_espera(self):
        """ngrok contesta 404 mientras publica y 200 en cuanto termina."""
        respuestas = iter([404, 404, 200])
        assert _insistiendo(lambda: next(respuestas), lambda c: c == 200) == 200

    def test_ngrok_que_ni_abre_su_4040_tampoco_es_un_fallo_de_una(self):
        """Recién arrancado, la API del 4040 no existe todavía: eso no es
        «ngrok no está corriendo», es que no ha terminado."""
        intentos = []

        def mirar():
            intentos.append(1)
            if len(intentos) < 3:
                raise ConnectionError("no hay nadie en el 4040")
            return {"https://x.ngrok-free.dev"}

        assert _insistiendo(mirar, lambda v: v) == {"https://x.ngrok-free.dev"}

    def test_lo_que_está_roto_de_verdad_se_reporta_igual(self):
        """No es disimular un fallo: si se acaba el tiempo, se dice."""
        assert _insistiendo(lambda: 404, lambda c: c == 200, segundos=0) == 404

    def test_si_nunca_responde_el_error_sale_a_la_luz(self):
        def mirar():
            raise ConnectionError("no responde")

        with pytest.raises(ConnectionError):
            _insistiendo(mirar, lambda v: v, segundos=0)


class TestLaCache:
    """El diagnóstico mide la caché con los turnos reales (29/09)."""

    def _diag(self):
        from scripts.diagnostico import Diagnostico

        d = Diagnostico.__new__(Diagnostico)
        d.r = []
        return d

    def test_con_la_cache_funcionando_esta_en_verde(self):
        d = self._diag()
        llamada = {"in": 40, "cache_read": 9180, "usd": 0.0002, "ok": True}
        d._la_cache([llamada] * 6)
        assert d.r[-1].estado == "ok"
        assert "100%" in d.r[-1].detalle

    def test_si_el_prompt_no_sale_de_cache_avisa(self):
        d = self._diag()
        d._la_cache([{"in": 9200, "cache_read": 0, "usd": 0.001, "ok": True}] * 6)
        assert d.r[-1].estado == "ojo"
        assert d.r[-1].arreglo

    def test_sin_turnos_no_hay_alarma(self):
        d = self._diag()
        d._la_cache([])
        assert d.r[-1].estado == "ok"
