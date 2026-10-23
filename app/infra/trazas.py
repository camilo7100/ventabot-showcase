"""Ver qué hizo el bot en cada conversación. LangSmith, y sin depender de él.

════════════════════════════════════════════════════════════════════════════
QUÉ PROBLEMA RESUELVE
════════════════════════════════════════════════════════════════════════════
El log de un turno cabe en cinco líneas y se pierde entre otros mil. Cuando
una clienta dice «el bot me contestó cualquier cosa» hay que reconstruir a
mano qué entendió, qué decidió y cuánto tardó — con suerte, si el servidor
lleva poco corriendo.

Una traza guarda eso ordenado: por conversación, con lo que entró, lo que el
modelo devolvió, la acción que se eligió y el tiempo de cada tramo. Es la
diferencia entre «no sé qué pasó» y «mira, aquí interpretó CONSULTAR y
debería haber sido COMPRAR».

════════════════════════════════════════════════════════════════════════════
POR QUÉ UN DECORADOR PROPIO Y NO `@traceable` DIRECTO
════════════════════════════════════════════════════════════════════════════
Tres razones, y las tres son la misma:

  1. APAGADO POR DEFECTO. Sin `LANGSMITH_TRACING=true` esto no hace
     literalmente nada: devuelve la función tal cual. Cero latencia, cero
     red, cero dependencia en caliente.
  2. SIN LIBRERÍA TAMBIÉN FUNCIONA. Si `langsmith` no está instalado, el
     decorador se convierte en un adorno. El bot no puede caerse por una
     herramienta de observabilidad.
  3. UN SOLO SITIO. El día que se cambie LangSmith por otra cosa —o por un
     visor propio— se cambia aquí, y no en los seis módulos decorados.

════════════════════════════════════════════════════════════════════════════
LOCAL
════════════════════════════════════════════════════════════════════════════
`LANGSMITH_ENDPOINT` apunta a donde se manden las trazas. Con la nube de
LangSmith se deja vacío; con un LangSmith propio corriendo en el PC se pone
su dirección. El código es el mismo.
"""

from __future__ import annotations

import functools
import logging
import os
from collections.abc import Callable

log = logging.getLogger("ventabot.trazas")

#: Se decide UNA vez al arrancar. Cambiarlo en caliente no tendría sentido y
#: sí tendría coste: preguntar por la variable en cada mensaje.
_ACTIVO: bool | None = None


def activar_desde_settings(s) -> bool:
    """Enciende (o no) las trazas y deja el entorno listo para la librería.

    La librería de LangSmith se configura por variables de entorno. En vez de
    pedirle a nadie que las exporte a mano —y que un día no coincidan con el
    `.env`—, se derivan aquí de los ajustes del proyecto.
    """
    global _ACTIVO
    _ACTIVO = bool(s.langsmith_tracing and s.langsmith_api_key)
    if not _ACTIVO:
        # Explícito: la librería también mira esta variable por su cuenta, y
        # dejarla a medias sería trazar sin querer.
        os.environ["LANGSMITH_TRACING"] = "false"
        return False

    os.environ["LANGSMITH_TRACING"] = "true"
    os.environ["LANGSMITH_API_KEY"] = s.langsmith_api_key
    os.environ["LANGSMITH_PROJECT"] = s.langsmith_project
    if s.langsmith_endpoint:
        os.environ["LANGSMITH_ENDPOINT"] = s.langsmith_endpoint
    log.info(
        "trazas ENCENDIDAS · proyecto=%s · %s",
        s.langsmith_project,
        s.langsmith_endpoint or "nube de LangSmith",
    )
    return True


def traza(nombre: str, tipo: str = "chain") -> Callable:
    """Marca una función para que aparezca en la traza. Barato o gratis.

    `tipo` es el que entiende LangSmith: "llm" para las llamadas al modelo,
    "chain" para todo lo demás. Sirve para que la vista de costes y latencia
    separe lo que se paga de lo que no.
    """

    def envolver(funcion: Callable) -> Callable:
        @functools.wraps(funcion)
        def envuelta(*args, **kwargs):
            if not _ACTIVO:
                return funcion(*args, **kwargs)
            try:
                from langsmith import traceable
            except ImportError:  # pragma: no cover - depende del entorno
                return funcion(*args, **kwargs)
            # Se envuelve AQUÍ y no al importar el módulo: si se hiciera
            # arriba, el decorador de LangSmith se instalaría aunque las
            # trazas estuvieran apagadas.
            return traceable(name=nombre, run_type=tipo)(funcion)(*args, **kwargs)

        return envuelta

    return envolver


def _arbol():
    """El nodo de la traza en curso, o None (apagado, sin librería, sin traza)."""
    if not _ACTIVO:
        return None
    try:
        from langsmith.run_helpers import get_current_run_tree

        return get_current_run_tree()
    except Exception:  # pragma: no cover - la observabilidad no rompe nada
        return None


def etiquetar(*etiquetas: str) -> None:
    """Etiquetas de la traza: filtrar en LangSmith por «escalado», «potente»…"""
    arbol = _arbol()
    if arbol is not None:
        try:
            arbol.add_tags([e for e in etiquetas if e])
        except Exception as exc:  # pragma: no cover
            log.debug("no se pudo etiquetar la traza (%s)", exc)


def uso_del_modelo(
    modelo: str,
    *,
    entrada: int,
    salida: int,
    cache_leida: int = 0,
    cache_escrita: int = 0,
    proveedor: str = "anthropic",
) -> None:
    """Los tokens de la llamada al modelo en curso: con esto LangSmith calcula
    el costo de cada turno por su cuenta (y se puede cruzar con `vb metricas`).

    `entrada` es lo que NO salió de caché, en los dos proveedores (el adaptador
    de GPT ya lo separa): así la suma de aquí es igual para Anthropic y OpenAI.
    """
    arbol = _arbol()
    if arbol is None:
        return
    try:
        from app.domain.consumo import capa_actual

        # Dentro de un turno, todas las llamadas se llaman «modelo»: la capa
        # (básico, fuerte, reescribir, visión…) dice cuál es cuál y se filtra
        # con «llamada:…» (el turno entero lleva «capa:…», que es otra cosa:
        # quién decidió el turno).
        capa = capa_actual()
        arbol.add_metadata(
            {"ls_provider": proveedor, "ls_model_name": modelo, "capa": capa or "?"}
        )
        if capa:
            arbol.add_tags([f"llamada:{capa}"])
        arbol.set(
            usage_metadata={
                "input_tokens": entrada + cache_leida + cache_escrita,
                "output_tokens": salida,
                "total_tokens": entrada + cache_leida + cache_escrita + salida,
                "input_token_details": {
                    "cache_read": cache_leida,
                    "cache_creation": cache_escrita,
                },
            }
        )
    except Exception as exc:  # pragma: no cover
        log.debug("no se pudo anotar el uso del modelo (%s)", exc)


def anotar(**metadatos) -> None:
    """Cuelga datos del turno actual: la acción, el pedido, si escaló.

    Es lo que convierte una lista de trazas en algo buscable («enséñame las
    conversaciones que acabaron en LLAMAR_HUMANO»). Si no hay traza activa,
    no hace nada y no se queja.
    """
    if not _ACTIVO:
        return
    try:
        from langsmith.run_helpers import get_current_run_tree

        if (arbol := get_current_run_tree()) is not None:
            arbol.extra.setdefault("metadata", {}).update(metadatos)
    except Exception as exc:  # pragma: no cover - la observabilidad no rompe nada
        # A nivel debug: que una traza no se pueda anotar no le importa a
        # nadie mientras el bot conteste, y llenar el log de esto taparía lo
        # que sí importa.
        log.debug("no se pudo anotar la traza (%s)", exc)
