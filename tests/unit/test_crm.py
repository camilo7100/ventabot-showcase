"""El espejo en Chatwoot. Lo que se prueba es que NUNCA estorbe.

Copiar la conversación a un CRM es lo menos importante que pasa en un turno.
Si Chatwoot está caído, lento o mal configurado, la clienta no se puede
quedar esperando por eso — y eso es exactamente lo que se prueba aquí.
"""

from __future__ import annotations

import time

import pytest

from app.adapters.crm.chatwoot import COLA_MAXIMA, ChatwootCRM, CrmDeMentira
from app.domain.ports import CrmPort


class TestElPuerto:
    def test_los_dos_lo_cumplen(self):
        assert isinstance(CrmDeMentira(), CrmPort)

    def test_sin_crm_configurado_no_pasa_nada(self):
        falso = CrmDeMentira()
        falso.registrar("wa:573001112233", "hola", entrante=True)
        assert falso.copias


class TestNuncaEstorba:
    @pytest.fixture
    def caido(self):
        """Un Chatwoot que no existe. Es el peor caso realista."""
        crm = ChatwootCRM(
            base_url="http://127.0.0.1:9",  # puerto que no escucha nadie
            token="x",
            account_id=1,
            inbox_id=1,
            espera_s=1,
        )
        yield crm
        # Sin esto, el hilo sigue intentándolo cuando la prueba ya terminó y
        # suelta «no se pudo copiar a Chatwoot» al final de TODA la suite,
        # donde parece que se tocó el Chatwoot de verdad.
        crm.cerrar()

    def test_registrar_vuelve_al_instante_aunque_este_caido(self, caido):
        arranque = time.perf_counter()
        for _ in range(20):
            caido.registrar("wa:573001112233", "hola", entrante=True)
        assert time.perf_counter() - arranque < 0.3, "bloqueó el turno"

    def test_un_crm_caido_no_lanza_nada(self, caido):
        caido.registrar("wa:573001112233", "hola", entrante=True)
        time.sleep(0.2)  # deja trabajar al hilo
        # Si hubiera propagado, el hilo estaría muerto.
        assert caido._hilo.is_alive()

    def test_la_cola_tiene_techo(self, caido):
        """Sin techo, un Chatwoot lento se come la memoria del proceso que
        atiende a las clientas."""
        for i in range(COLA_MAXIMA + 50):
            caido.registrar("wa:573001112233", f"mensaje {i}", entrante=True)
        assert caido.pendientes() <= COLA_MAXIMA

    def test_un_mensaje_vacio_no_se_copia(self, caido):
        caido.registrar("wa:573001112233", "", entrante=True)
        assert caido.pendientes() == 0


class TestReconoceSuEco:
    """Lo que el bot copia vuelve por webhook como si lo hubiera escrito Lía.

    El 19/09, con clientas de verdad, eso hizo que cada mensaje saliera DOS
    veces y que el bot se callara creyendo que lo atendía una persona.
    """

    @pytest.fixture
    def espejo(self):
        crm = ChatwootCRM(
            base_url="http://127.0.0.1:9",
            token="x",
            account_id=1,
            inbox_id=1,
            espera_s=1,
        )
        yield crm
        crm.cerrar()

    def test_lo_que_copio_el_bot_es_eco(self, espejo):
        espejo.registrar("wa:1", "¿De cuántas huellitas? ", entrante=False)
        assert espejo.es_eco("wa:1", "¿De cuántas huellitas?")

    def test_cada_copia_es_un_solo_eco(self, espejo):
        """Si Lía escribe después lo mismo que dijo el bot, eso SÍ sale."""
        espejo.registrar("wa:1", "Listo 💜", entrante=False)
        assert espejo.es_eco("wa:1", "Listo 💜")
        assert not espejo.es_eco("wa:1", "Listo 💜")

    def test_lo_de_la_clienta_no_se_recuerda(self, espejo):
        espejo.registrar("wa:1", "hola", entrante=True)
        assert not espejo.es_eco("wa:1", "hola")

    def test_no_se_cruza_entre_conversaciones(self, espejo):
        espejo.registrar("wa:1", "hola", entrante=False)
        assert not espejo.es_eco("wa:2", "hola")

    def test_lo_nuevo_de_lia_no_es_eco(self, espejo):
        espejo.registrar("wa:1", "hola", entrante=False)
        assert not espejo.es_eco("wa:1", "Hola, soy Lía")

    def test_el_estado_se_encola_sin_bloquear(self, espejo):
        arranque = time.perf_counter()
        espejo.marcar_estado("wa:1", "open")
        assert time.perf_counter() - arranque < 0.1


class TestLoQueVeLia:
    """El seguimiento en Chatwoot (app.domain.seguimiento): etapa y alertas."""

    def test_toda_etiqueta_se_puede_filtrar(self):
        import re

        from app.domain.seguimiento import ETIQUETAS_DEL_SISTEMA

        for etiqueta in ETIQUETAS_DEL_SISTEMA:
            assert re.fullmatch(r"[a-z0-9-]+", etiqueta), etiqueta

    def test_cada_estado_del_pedido_tiene_su_etapa(self):
        from app.domain.order_state import OrderState
        from app.domain.seguimiento import ETIQUETAS_DE_ETAPA, seguimiento

        for estado in OrderState:
            assert seguimiento(estado_pedido=estado.value).etapa in ETIQUETAS_DE_ETAPA

    def test_el_pago_en_revision_dice_cual_es(self):
        from app.domain.seguimiento import seguimiento

        abono = seguimiento(estado_pedido="EN_REVISION_PAGO")
        saldo = seguimiento(estado_pedido="EN_REVISION_PAGO", anticipo_pagado=True)
        assert abono.etapa == "04-abono-por-verificar"
        assert saldo.etapa == "07-saldo-por-verificar"
        assert "pago-por-verificar" in abono.alertas and abono.abierta

    def test_sin_nada_pendiente_la_lleva_el_bot(self):
        from app.domain.seguimiento import seguimiento

        s = seguimiento(estado_pedido="EN_PRODUCCION")
        assert s.etapa == "05-en-taller" and not s.alertas and not s.abierta

    def test_pago_sin_pedido_completo_es_datos_incompletos(self):
        from app.domain.seguimiento import seguimiento

        s = seguimiento(diseno_empezado=True, pagado_sin_pedido=True)
        assert {"datos-incompletos", "pago-por-verificar"} <= s.alertas

    def test_las_etiquetas_de_lia_no_se_tocan(self):
        from app.domain.seguimiento import nuevas_etiquetas, seguimiento

        actuales = ["vip", "02-disenando", "necesita-persona", "hacer-abono-ok"]
        nuevas = nuevas_etiquetas(
            actuales, seguimiento(estado_pedido="ESPERANDO_ANTICIPO")
        )
        assert "vip" in nuevas and "hacer-abono-ok" in nuevas
        assert "03-esperando-abono" in nuevas
        assert "02-disenando" not in nuevas and "necesita-persona" not in nuevas


class TestLoQueMandaElBotSeVe:
    """En Chatwoot salía «[📷 muestrario circones]» y había que imaginárselo.

    Lía no veía el prototipo que el bot acababa de mandarle a la clienta, ni
    las fotos del anillo terminado, ni en el PC ni en el celular (Camilo,
    20/09). Ahora el archivo viaja con el mensaje.
    """

    def test_un_archivo_nuestro_se_lee_del_disco_y_no_de_la_red(self, tmp_path):
        from app.adapters.crm.chatwoot import ChatwootCRM

        foto = tmp_path / "muestrario.jpg"
        foto.write_bytes(b"\xff\xd8\xff" + b"contenido")

        def _no_se_llama(ref):
            raise AssertionError("no tiene que salir a la red: el archivo es nuestro")

        crm = ChatwootCRM(
            base_url="http://127.0.0.1:9",
            token="x",
            account_id=1,
            inbox_id=1,
            descargar=_no_se_llama,
        )
        try:
            archivos = crm._bajar(({"ruta": str(foto), "mime_type": "image/jpeg"},))
            assert len(archivos) == 1
            nombre, datos, mime = archivos[0]
            assert datos == foto.read_bytes()
            assert mime == "image/jpeg" and nombre.endswith(".jpg")
        finally:
            crm.cerrar()

    def test_el_contenedor_encuentra_el_archivo_del_muestrario(self, tmp_path):
        """De la URL pública se vuelve al archivo en disco."""
        from app.domain.models import Channel, OutboundMessage
        from app.infra.container import Container

        salida = OutboundMessage(
            channel=Channel.WHATSAPP,
            to="573001112233",
            kind="image",
            media_url="https://x.ngrok-free.dev/media/muestrario_circones",
            text="",
            conversation_id="wa:573001112233",
            idempotency_key="k",
        )
        adjuntos = Container._adjunto_de(_ContenedorDeMentira(), salida)
        assert len(adjuntos) == 1
        assert adjuntos[0]["ruta"].endswith(("jpg", "jpeg", "png", "webp"))
        assert adjuntos[0]["mime_type"].startswith("image/")

    def test_un_mensaje_de_solo_texto_no_lleva_adjuntos(self):
        from app.domain.models import Channel, OutboundMessage
        from app.infra.container import Container

        salida = OutboundMessage(
            channel=Channel.WHATSAPP,
            to="573001112233",
            text="¡Hola!",
            conversation_id="wa:573001112233",
            idempotency_key="k",
        )
        assert Container._adjunto_de(_ContenedorDeMentira(), salida) == ()


class _ContenedorDeMentira:
    """Lo mínimo que `_adjunto_de` necesita: la configuración de verdad."""

    def __init__(self):
        from app.infra.settings import get_settings

        self.settings = get_settings()


class TestNoSePierdenCopiasAlCerrar:
    """07/10: se le mandó a una clienta la información de la cadena desde un
    script; el script terminó y la cola de Chatwoot (un hilo que muere con el
    proceso) no alcanzó a copiarla. Chatwoot es la ÚNICA forma en que Camilo y
    Lía ven la charla: nada puede quedarse por fuera."""

    def _crm_lento(self, hechas: list):
        crm = ChatwootCRM(
            base_url="http://127.0.0.1:9", token="x", account_id=1, inbox_id=1
        )

        def hacer(tarea, creada=None):
            time.sleep(0.1)
            hechas.append(tarea)

        crm._hacer = hacer  # type: ignore[method-assign]
        return crm

    def test_vaciar_espera_a_que_todo_llegue(self):
        hechas: list = []
        crm = self._crm_lento(hechas)
        try:
            for i in range(3):
                crm.registrar("wa:573001112233", f"mensaje {i}", entrante=False)
            assert crm.vaciar(tope_s=5)
            assert len(hechas) == 3
        finally:
            crm.cerrar()

    def test_si_no_alcanza_avisa_y_no_se_queda_colgado(self):
        hechas: list = []
        crm = self._crm_lento(hechas)
        try:
            for i in range(20):
                crm.registrar("wa:573001112233", f"mensaje {i}", entrante=False)
            arranque = time.perf_counter()
            assert not crm.vaciar(tope_s=0.2)
            assert time.perf_counter() - arranque < 1
        finally:
            crm.cerrar()

    def test_un_proceso_que_termina_igual_deja_todo_copiado(self, tmp_path):
        """Lo de verdad: un proceso aparte encola y termina enseguida."""
        import subprocess
        import sys
        from pathlib import Path

        hechas = tmp_path / "hechas.txt"
        codigo = f"""
import time
from app.adapters.crm.chatwoot import ChatwootCRM
crm = ChatwootCRM(base_url="http://127.0.0.1:9", token="x", account_id=1, inbox_id=1)
def hacer(tarea, creada=None):
    time.sleep(0.1)
    with open({str(hechas)!r}, "a", encoding="utf-8") as f:
        f.write("ok ")
crm._hacer = hacer
for i in range(5):
    crm.registrar("wa:573001112233", f"m{{i}}", entrante=False)
"""
        raiz = Path(__file__).resolve().parents[2]
        subprocess.run([sys.executable, "-c", codigo], cwd=raiz, check=True, timeout=60)
        assert hechas.read_text(encoding="utf-8").count("ok") == 5

    def test_un_tropiezo_de_chatwoot_se_reintenta(self, monkeypatch):
        import app.adapters.crm.chatwoot as cw

        monkeypatch.setattr(cw, "REINTENTOS_S", (0.01, 0.01))
        crm = ChatwootCRM(
            base_url="http://127.0.0.1:9", token="x", account_id=1, inbox_id=1
        )
        intentos: list = []

        def hacer(tarea, creada=None):
            intentos.append(tarea)
            if len(intentos) < 3:
                raise RuntimeError("Chatwoot reiniciando")

        crm._hacer = hacer  # type: ignore[method-assign]
        try:
            crm.registrar("wa:573001112233", "la cadena", entrante=False)
            assert crm.vaciar(tope_s=5)
            assert len(intentos) == 3
        finally:
            crm.cerrar()
