"""El vigía: que una caída del túnel no se lleve los mensajes en silencio.

════════════════════════════════════════════════════════════════════════════
LAS DOS COSAS QUE TIENE QUE HACER BIEN
════════════════════════════════════════════════════════════════════════════
1. AVISAR cuando de verdad no entra nada. El 20/09 una clienta escribió y su
   mensaje nunca llegó; tuvo que repetirlo tres minutos después.

2. CALLARSE el resto del tiempo. La primera versión de este vigía pedía
   `/health` a la URL pública y gritó «el túnel no responde» mientras los
   mensajes entraban con toda normalidad — esa prueba salía del PC, daba la
   vuelta por ngrok y volvía, y medía la salida de esta máquina, no la entrada
   de Meta. Una alarma que se equivoca enseña a ignorarla.

La segunda es tan importante como la primera, y por eso hay más tests de
silencio que de alarma.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.workers.vigia_del_tunel import (
    FALLOS_PARA_AVISAR,
    MARGEN,
    VENTANA_DE_ACTIVIDAD,
    VigiaDelTunel,
)

AHORA = datetime.now(UTC)


class _Avisos:
    def __init__(self):
        self.avisos = []

    def avisar(self, titulo, detalle="", clave=""):
        self.avisos.append((titulo, detalle))


def _vigia(enviado, webhook, avisos=None):
    """Un vigía con el reloj puesto donde haga falta."""
    return VigiaDelTunel(lambda: enviado, lambda: webhook, avisos=avisos)


# ══════════════════════════════════════════════════════════════════════════
#  1. Cuando de verdad no entra nada
# ══════════════════════════════════════════════════════════════════════════


class TestCuandoNoEntraNada:
    def test_respondimos_y_meta_no_acusa_recibo(self):
        """Meta acusa cada envío en segundos. Diez minutos de silencio
        después de haber respondido solo pueden significar una cosa."""
        v = _vigia(
            enviado=AHORA - timedelta(minutes=10),
            webhook=AHORA - timedelta(minutes=30),
        )
        assert v.mirar_una_vez() is False

    def test_avisa_al_celular_tras_dos_comprobaciones(self):
        avisos = _Avisos()
        v = _vigia(
            enviado=AHORA - timedelta(minutes=10),
            webhook=AHORA - timedelta(minutes=30),
            avisos=avisos,
        )
        for _ in range(FALLOS_PARA_AVISAR):
            v.mirar_una_vez()
        assert avisos.avisos
        assert "mensajes" in avisos.avisos[0][0].lower()

    def test_no_repite_la_alarma_cada_dos_minutos(self):
        avisos = _Avisos()
        v = _vigia(
            enviado=AHORA - timedelta(minutes=10),
            webhook=AHORA - timedelta(minutes=30),
            avisos=avisos,
        )
        for _ in range(8):
            v.mirar_una_vez()
        assert len(avisos.avisos) == 1

    def test_cuando_vuelve_a_entrar_lo_dice(self):
        avisos = _Avisos()
        v = VigiaDelTunel(
            lambda: AHORA - timedelta(minutes=10),
            lambda: self_webhook[0],
            avisos=avisos,
        )
        self_webhook = [AHORA - timedelta(minutes=30)]
        for _ in range(FALLOS_PARA_AVISAR):
            v.mirar_una_vez()
        self_webhook[0] = AHORA  # volvió a entrar
        assert v.mirar_una_vez() is True
        assert v.fallos == 0
        assert len(avisos.avisos) == 2 and "ya entran" in avisos.avisos[1][0].lower()


# ══════════════════════════════════════════════════════════════════════════
#  2. Cuando NO hay nada que concluir: callarse
# ══════════════════════════════════════════════════════════════════════════


class TestCuandoNoHayNadaQueConcluir:
    def test_de_madrugada_sin_haber_mandado_nada_se_calla(self):
        """Sin clientas no hay acuses que esperar. Avisar aquí sería gritar
        todas las noches."""
        avisos = _Avisos()
        v = _vigia(
            enviado=AHORA - VENTANA_DE_ACTIVIDAD - timedelta(minutes=5),
            webhook=AHORA - timedelta(hours=3),
            avisos=avisos,
        )
        assert v.mirar_una_vez() is None
        assert not avisos.avisos

    def test_bot_recien_encendido_sin_historial(self):
        avisos = _Avisos()
        v = _vigia(enviado=None, webhook=None, avisos=avisos)
        assert v.mirar_una_vez() is None
        assert not avisos.avisos

    def test_acabamos_de_mandar_y_el_acuse_todavia_no_llega(self):
        """El acuse tarda segundos, pero la comprobación puede caer justo en
        ese hueco. Ahí no se concluye nada."""
        v = _vigia(
            enviado=AHORA - timedelta(seconds=20),
            webhook=AHORA - timedelta(minutes=2),
        )
        assert v.mirar_una_vez() is None

    def test_si_entra_todo_no_dice_nada(self):
        avisos = _Avisos()
        v = _vigia(
            enviado=AHORA - timedelta(minutes=5),
            webhook=AHORA - timedelta(minutes=4),
            avisos=avisos,
        )
        assert v.mirar_una_vez() is True
        assert not avisos.avisos

    def test_una_fuente_rota_no_da_la_alarma(self):
        """Si no se puede leer la base o el registro, se calla: no saber no
        es lo mismo que estar roto."""

        def _revienta():
            raise RuntimeError("la base está ocupada")

        avisos = _Avisos()
        v = VigiaDelTunel(_revienta, _revienta, avisos=avisos)
        assert v.mirar_una_vez() is None
        assert not avisos.avisos

    @pytest.mark.parametrize("desfase", [0, 30, 120])
    def test_el_acuse_del_mismo_envio_cuenta(self, desfase):
        """El acuse llega justo después del envío, a veces con el reloj
        apenas movido. No puede contar como «no entró nada»."""
        enviado = AHORA - timedelta(minutes=6)
        v = _vigia(enviado=enviado, webhook=enviado + timedelta(seconds=desfase))
        assert v.mirar_una_vez() is True


class TestElMargen:
    def test_el_margen_es_holgado_pero_no_eterno(self):
        """Tres minutos: de sobra para un acuse que llega en segundos, y poco
        para enterarse antes de perder una conversación entera."""
        assert timedelta(minutes=1) <= MARGEN <= timedelta(minutes=5)

    def test_la_ventana_de_actividad_cubre_una_conversacion(self):
        assert timedelta(minutes=10) <= VENTANA_DE_ACTIVIDAD
