"""Configuración común de los tests.

LOS TESTS NO PUEDEN DEPENDER DEL .env DE QUIEN LOS CORRE
========================================================

Esta lección salió cara: dos fallos distintos en la máquina del usuario
tuvieron el mismo origen. Su `.env` tiene `LLM_BACKEND=ollama`, así que los
tests que arrancaban un script como subproceso acababan golpeando el modelo de
verdad — lentos, dependientes de que Ollama estuviera arriba, y con resultados
distintos a los de la máquina de desarrollo.

Un test que se comporta distinto según la configuración local de cada uno no
prueba lo que dice probar.

`pydantic-settings` da prioridad a las variables de entorno REALES por encima
del archivo `.env`, así que fijarlas aquí neutraliza el `.env` del usuario sin
tocarlo ni borrarlo.
"""

from __future__ import annotations

import os
import shutil
import tempfile

import pytest

#: Donde van la base, el Excel y las fotos de la suite (nunca los de verdad).
_TEMPORAL = tempfile.mkdtemp(prefix="ventabot-tests-")

#: Configuración con la que corre TODA la suite, pase lo que pase en el .env.
ENTORNO_DE_PRUEBAS = {
    "ENTORNO": "dev",
    "LLM_BACKEND": "fake",
    "CHANNEL_BACKEND": "console",
    "PAYMENT_BACKEND": "fake",
    "REPOSITORY_BACKEND": "memory",
    # Que ningún test intente hablar con un Ollama real por descuido.
    "OLLAMA_HOST": "http://127.0.0.1:1",
    # El túnel de ngrok NO puede venir del .env de quien corre los tests.
    # `url_publica` cae de URL_PUBLICA sobre PUBLIC_URL, así que un test que
    # quiere probar «sin túnel» vaciaba solo la primera y seguía viendo la
    # segunda: pasaba en una máquina y fallaba en la otra. Las dos vacías; el
    # test que necesita un túnel pone URL_PUBLICA él mismo.
    "URL_PUBLICA": "",
    "PUBLIC_URL": "",
    # Nada de servicios reales. Con el Chatwoot del .env, la suite copió sus
    # conversaciones de mentira al Chatwoot de verdad, que se las devolvió al
    # bot encendido como si Lía las hubiera escrito: mensajes en cola para un
    # número inventado. Un test que necesita uno de estos lo pone él mismo.
    "CHATWOOT_URL": "",
    "CHATWOOT_TOKEN": "",
    "CHATWOOT_BOT_TOKEN": "",
    "CHATWOOT_WEBHOOK_TOKEN": "",
    # Ni el ERP. Una prueba con REPOSITORY_BACKEND=sqlite construía el
    # contenedor con el ID y la credencial del .env y arrancaba un ERP DE
    # VERDAD, con su hilo escribiendo en HUELLAS_ERP_v1. Se vio el 20/09: la
    # suite y el bot crearon a la vez la hoja CENTRO DE MANDO y Google dejó
    # una segunda con «_conflict» en el nombre. Con pedidos pagados, esas
    # pruebas habrían metido ventas de mentira en el ERP del negocio.
    "SHEETS_SPREADSHEET_ID": "",
    "GOOGLE_SERVICE_ACCOUNT_JSON": "",
    "AVISOS_BACKEND": "ninguno",
    "NTFY_TEMA": "",
    "TELEGRAM_BOT_TOKEN": "",
    "TELEGRAM_CHAT_ID": "",
    "TRANSCRIPCION_BACKEND": "ninguno",
    "GROQ_API_KEY": "",
    "RECORDATORIOS": "false",
    # Sin ventana de ráfaga: cada prueba ve su respuesta al instante.
    "AGRUPAR_SEGUNDOS": "0",
    # El flujo de siempre; la regla de Lía tiene sus propias pruebas.
    "TALLA_LA_CONFIRMA_LIA": "false",
    "WA_ACCESS_TOKEN": "",
    "ANTHROPIC_API_KEY": "",
    # Nada de trazas de la suite en el proyecto de LangSmith de verdad.
    "LANGSMITH_TRACING": "false",
    "LANGSMITH_API_KEY": "",
    # Ni la base ni el Excel de ventas de verdad: los de la suite viven en una
    # carpeta temporal que se tira al terminar.
    "SQLITE_PATH": os.path.join(_TEMPORAL, "ventabot-tests.db"),
    "VENTAS_EXCEL": os.path.join(_TEMPORAL, "ventas-tests.xlsx"),
    "FOTOS_DIR": os.path.join(_TEMPORAL, "fotos"),
    # El registro del servidor de verdad no se mezcla con el de la suite.
    "LOG_ARCHIVO": "",
}


@pytest.fixture(autouse=True, scope="session")
def _entorno_hermetico():
    """Fija la configuración de pruebas durante toda la sesión."""
    anterior = {k: os.environ.get(k) for k in ENTORNO_DE_PRUEBAS}
    os.environ.update(ENTORNO_DE_PRUEBAS)
    yield
    for k, v in anterior.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v
    shutil.rmtree(_TEMPORAL, ignore_errors=True)


@pytest.fixture(autouse=True)
def _sin_contenedor_compartido():
    """Cada test arranca sin el contenedor global de otro test.

    `get_container()` guarda una instancia única. Sin esto, un test que lo
    construya deja su base de datos y sus repositorios en memoria para el
    siguiente, y los fallos aparecen o no según el ORDEN de ejecución — que es
    el tipo de bug más difícil de encontrar que existe.
    """
    import app.infra.container as contenedor

    contenedor._singleton = None
    yield
    contenedor._singleton = None


@pytest.fixture(autouse=True)
def _paleta_de_fabrica():
    """Cada test arranca con los nombres, tintes y acabados de fábrica.

    La paleta vive en diccionarios del módulo (`NOMBRE_COLOR`, `HEX_COLOR`,
    `ACABADO_COLOR`) que el panel cambia en su sitio (`aplicar_paleta`, 30/09).
    Un test que renombra una bolsita la dejaría renombrada para todos los que
    siguen.
    """
    from app.domain import personalizacion as p

    nombres, tintes = dict(p.NOMBRE_COLOR), dict(p.HEX_COLOR)
    acabados = dict(p.ACABADO_COLOR)
    yield
    p.NOMBRE_COLOR.clear()
    p.NOMBRE_COLOR.update(nombres)
    p.HEX_COLOR.clear()
    p.HEX_COLOR.update(tintes)
    p.ACABADO_COLOR.clear()
    p.ACABADO_COLOR.update(acabados)
    p.VERSION_PALETA += 1


# ---------------------------------------------------------------------------
# Versión pública: las fotos reales del negocio (muestrario de circones, máscaras de
# huellitas, fotos del anillo) NO se publican; en `data/imagenes` hay imágenes de relleno
# con los mismos nombres. Las pruebas que miden píxeles de esas fotos se saltan aquí y
# corren completas en el repositorio privado.
_HUELLITAS = "tests/unit/test_huellitas_del_anillo.py::TestLaFormaDelAnillo"
_PRUEBAS_QUE_NECESITAN_LAS_FOTOS_REALES = (
    "tests/unit/test_colores_del_muestrario.py",
    "tests/unit/test_previsualizacion.py",
    "tests/unit/test_panel_colores.py::TestElBlancoEsLaFotoDelDiamante",
    _HUELLITAS + "::test_en_el_de_tres_la_del_centro_mira_al_otro_lado",
    "tests/unit/test_anillo_corazon.py::TestComoQueda",
)
_MOTIVO = "usa las fotos reales del negocio (no incluidas en la versión pública)"


def pytest_collection_modifyitems(config, items):
    marca = pytest.mark.skip(reason=_MOTIVO)
    for item in items:
        nodo = item.nodeid.replace("\\", "/")
        if nodo.startswith(_PRUEBAS_QUE_NECESITAN_LAS_FOTOS_REALES):
            item.add_marker(marca)
