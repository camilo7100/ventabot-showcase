"""Que ntfy avise de cualquier error del registro (16/10).

El 14/10 el webhook se cayó dos días y el celular no sonó: el error estaba en
el registro y Meta seguía mandando los acuses de entrega, así que ningún
aviso con nombre lo vio.
"""

from __future__ import annotations

import logging
import time

from app.adapters.avisos import AvisarLosErrores


class _Avisos:
    def __init__(self) -> None:
        self.dados: list[tuple] = []

    def avisar(self, titulo, detalle="", clave=""):
        self.dados.append((titulo, detalle, clave))
        return True


def _esperar(avisos: _Avisos, n: int) -> None:
    for _ in range(50):
        if len(avisos.dados) >= n:
            return
        time.sleep(0.02)


class TestCualquierError:
    def test_un_error_del_registro_llega_sin_datos_de_la_clienta(self):
        avisos = _Avisos()
        registro = logging.getLogger("ventabot.prueba_de_avisos")
        manejador = AvisarLosErrores(avisos)
        registro.addHandler(manejador)
        try:
            try:
                raise KeyError("wa_id")
            except KeyError:
                registro.exception("falló con %s", "wa:573001112233")
            _esperar(avisos, 1)
        finally:
            registro.removeHandler(manejador)
        [(titulo, detalle, _clave)] = avisos.dados
        assert "Error" in titulo and "KeyError" in detalle
        assert "573001112233" not in detalle  # el número no viaja a ntfy

    def test_lo_que_no_es_error_no_avisa(self):
        avisos = _Avisos()
        registro = logging.getLogger("ventabot.prueba_de_avisos")
        manejador = AvisarLosErrores(avisos)
        registro.addHandler(manejador)
        try:
            registro.warning("algo raro pero no grave")
            time.sleep(0.1)
        finally:
            registro.removeHandler(manejador)
        assert not avisos.dados
