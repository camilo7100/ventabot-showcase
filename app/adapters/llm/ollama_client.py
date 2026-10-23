"""Adaptador de Ollama con SALIDA ESTRUCTURADA REAL.

Por qué se llama al cliente `ollama` directamente y no a `ChatOllama` de
LangChain:

  1. `format=<json_schema>` es CONSTRAINED DECODING de verdad: restringe los
     logits para que sea IMPOSIBLE emitir un token que rompa el schema.
     `format="json"` (a secas) es solo "modo JSON" y es mucho más débil.

  2. La documentación de LangChain no aclara si `ChatOllama.with_structured_output()`
     mapea a `format=<schema>` o hace parsing best-effort. Y `langchain-ollama`
     (1.1.0, abril 2026) va rezagado frente a `langchain-core` (1.6.0).
     Cuando el determinismo del schema es crítico — y aquí lo es — no se
     confía en una abstracción cuyo comportamiento no está documentado.

  3. El endpoint OpenAI-compatible de Ollama NO SOPORTA `tool_choice`: no
     puedes forzar la llamada a una herramienta concreta. La API nativa
     `/api/chat` con `format=<schema>` sí garantiza la forma.

Todo esto queda encapsulado detrás de `LLMPort`. El día que cambies a un modelo
hosted, escribes otro adaptador de 40 líneas y el dominio no se entera.

TRAMPA #1 DE OLLAMA (la causa nº1 de fallos misteriosos):
    En GPUs con menos de 24 GB de VRAM, Ollama asigna 4K de contexto POR DEFECTO
    aunque el modelo declare 128K. Tu historial + el schema desbordan en silencio
    y el modelo "olvida" las instrucciones. Arranca siempre así:

        OLLAMA_CONTEXT_LENGTH=32000 OLLAMA_FLASH_ATTENTION=1 ollama serve

    y verifica con `ollama ps`.
"""

from __future__ import annotations

import base64
import json
import re
import time
from typing import Any

from pydantic import BaseModel

from app.domain import consumo
from app.infra.trazas import traza

#: Opciones de mínima varianza. NO garantizan reproducibilidad bit a bit
#: (los kernels de GPU no son invariantes al tamaño del batch), pero es lo
#: máximo alcanzable del lado del modelo. El determinismo REAL viene del
#: schema cerrado + el router de Python, no de estos parámetros.
OPCIONES_DETERMINISTAS: dict[str, Any] = {
    "temperature": 0,
    "seed": 42,
    "top_k": 1,
    "top_p": 1.0,
    "num_ctx": 16000,
    # TECHO DE GENERACIÓN. La respuesta es un JSON de unos 120 tokens; 256 le
    # sobra con holgura.
    #
    # Sin este tope, medir el golden dataset dio 4 s de mediana y 37 s en el
    # peor caso: un puñado de mensajes hacían al modelo escribir y escribir
    # hasta agotarse. Una clienta no espera 37 segundos; se va. Y la cola
    # larga es la que decide si el bot se siente vivo, no la mediana.
    "num_predict": 256,
}

#: Opciones para MIRAR una foto. Distintas, y por razones medidas.
#:
#: ════════════════════════════════════════════════════════════════════════
#: LO QUE ENSEÑÓ `vb ojos` CON FOTOS REALES
#: ════════════════════════════════════════════════════════════════════════
#: 47 s de mediana, 82 s en el peor caso. Pero la MISMA foto, dos veces
#: seguidas, tardó 82 s y luego 13 s. Eso no es el modelo pensando: es Ollama
#: cargándolo. Con 4 GB de VRAM no caben a la vez el modelo de texto y el de
#: visión, así que cada foto expulsa uno y carga el otro.
#:
#: De ahí estas dos opciones: un contexto mucho más corto (el prompt de
#: visión son cuatro párrafos, no dieciséis mil tokens) hace que quepa más
#: fácil y que la caché de atención ocupe una fracción. Y el techo de
#: generación baja, porque la respuesta es un JSON de cien tokens.
#:
#: El resto es hardware: con 8 GB los dos modelos se quedan cargados y esto
#: baja a segundos. Está escrito aquí para que la próxima persona no repita
#: la medición.
OPCIONES_DE_VISION: dict[str, Any] = {
    **OPCIONES_DETERMINISTAS,
    "num_ctx": 4096,
    "num_predict": 192,
}


class OllamaLLM:
    """Implementa `app.domain.ports.LLMPort`."""

    def __init__(
        self,
        model: str = "gemma4:12b",
        host: str = "http://localhost:11434",
        vision_model: str | None = None,
    ) -> None:
        self.model = model
        self.vision_model = vision_model or model
        self._host = host
        self._client = None  # perezoso: no importar ollama hasta que se use

    def _get_client(self):
        if self._client is None:
            from ollama import Client  # import perezoso

            self._client = Client(host=self._host)
        return self._client

    @traza("modelo", tipo="llm")
    def extract(
        self,
        system_prompt: str,
        user_text: str,
        schema: type[BaseModel],
        *,
        calentando: bool = False,  # aquí no hay gramática que compilar: se ignora
        images: list[bytes] | None = None,
    ) -> BaseModel:
        client = self._get_client()

        mensaje: dict[str, Any] = {"role": "user", "content": user_text or "."}
        if images:
            # ENCOGER PRIMERO. Un modelo de visión trocea la imagen en
            # cuadraditos: cuatro veces más lado son dieciséis veces más
            # trabajo, y una foto de móvil no aporta nada por encima de mil
            # píxeles para leer una regla. Ver `imagenes.encoger`.
            from app.adapters.llm.imagenes import encoger

            # Ollama acepta imágenes en base64 (no acepta URLs por el endpoint
            # OpenAI-compatible; por la API nativa sí acepta bytes/base64).
            mensaje["images"] = [base64.b64encode(encoger(i)).decode() for i in images]

        json_schema = schema.model_json_schema()

        # El schema también va EN EL PROMPT: la doc de Ollama lo recomienda
        # explícitamente. El `format` constriñe la SINTAXIS; el prompt
        # constriñe la SEMÁNTICA. Los dos juntos rinden mucho más.
        system = (
            f"{system_prompt}\n\n"
            f"Responde ÚNICAMENTE un JSON que cumpla este schema:\n"
            f"{json.dumps(json_schema, ensure_ascii=False)}"
        )

        modelo = self.vision_model if images else self.model
        inicio = time.perf_counter()
        try:
            respuesta = client.chat(
                model=modelo,
                messages=[{"role": "system", "content": system}, mensaje],
                format=json_schema,  # ← constrained decoding real
                options=OPCIONES_DE_VISION if images else OPCIONES_DETERMINISTAS,
            )
        except Exception:
            consumo.registrar(
                modelo, ms=int((time.perf_counter() - inicio) * 1000), ok=False
            )
            raise
        # Local: cuesta 0 USD, pero los tokens y la espera sí se apuntan.
        consumo.registrar(
            modelo,
            entrada=int(respuesta.get("prompt_eval_count") or 0),
            salida=int(respuesta.get("eval_count") or 0),
            ms=int((time.perf_counter() - inicio) * 1000),
        )
        # Pydantic valida. Si falla, el nodo NLU reintenta una vez y luego
        # cae al fallback determinista. Nunca bucles infinitos.
        return schema.model_validate_json(respuesta["message"]["content"])


class FakeLLM:
    """Doble de prueba: clasificación por reglas, sin red ni modelo.

    Sirve para dos cosas:
      1. Tests del grafo completo en milisegundos.
      2. Baseline honesto: si tu LLM no le gana claramente a esto en el golden
         dataset, no estás ganando nada usándolo. Mídelo antes de asumirlo.
    """

    def __init__(self, respuestas: dict[str, BaseModel] | None = None) -> None:
        self.respuestas = respuestas or {}
        self.llamadas: list[tuple[str, str]] = []

    def extract(
        self,
        system_prompt: str,
        user_text: str,
        schema: type[BaseModel],
        *,
        calentando: bool = False,
        images: list[bytes] | None = None,
    ) -> BaseModel:
        self.llamadas.append((schema.__name__, user_text))

        if user_text in self.respuestas:
            return self.respuestas[user_text]

        from app.domain.interpretacion import Interpretacion, PropuestaDelModelo
        from app.domain.models import DatosComprobante, Intencion, Intent

        if schema in (Interpretacion, PropuestaDelModelo):
            leido = _interpretar_por_reglas(user_text or "")
            if schema is PropuestaDelModelo:
                # El modelo de texto solo devuelve su parte. Se recorta igual
                # que lo haría uno de verdad con este esquema.
                return PropuestaDelModelo.model_validate(
                    leido.model_dump(include=set(PropuestaDelModelo.model_fields))
                )
            return leido

        if schema is DatosComprobante:
            return DatosComprobante(monto_cop=None, legible=True)

        t = (user_text or "").lower()
        # El ORDEN importa: las reglas más específicas van primero.
        # ("quiero hablar con una persona" no puede clasificarse como COTIZAR
        #  solo porque contiene "quiero"). Es la misma trampa que tendrás con
        #  un LLM real: por eso existe el golden dataset.
        if any(k in t for k in ("humano", "asesor", "persona", "alguien")):
            tipo = Intent.HUMANO
        elif any(k in t for k in ("confirmo", "confirmar", "lo quiero", "dale")):
            tipo = Intent.CONFIRMAR
        elif any(
            k in t
            for k in ("cómo va", "como va", "mi pedido", "estado", "ya llegó", "ya llego")
        ):
            tipo = Intent.ESTADO
        elif any(
            k in t
            for k in (
                "catálogo",
                "catalogo",
                "qué tienen",
                "que tienen",
                "productos",
                "portafolio",
            )
        ):
            tipo = Intent.CATALOGO
        elif any(k in t for k in ("quiero", "cuánto", "cuanto", "precio", "vale")):
            tipo = Intent.COTIZAR
        elif any(k in t for k in ("hola", "buenas", "buenos días", "buen día")):
            tipo = Intent.SALUDO
        else:
            tipo = Intent.OTRO

        # Detección de SKU por patrón, no por lista fija: así el doble sigue
        # funcionando cuando cambies el catálogo (data/catalogo.csv).
        m = re.search(r"\b[A-Z]{2,4}(?:-[A-Z0-9]{2,4}){1,2}\b", user_text or "")
        sku = m.group(0) if m else None
        cantidad = next(
            (
                int(w)
                for w in t.replace(",", " ").split()
                if w.isdigit() and 0 < int(w) <= 500
            ),
            None,
        )
        return Intencion(tipo=tipo, sku=sku, cantidad=cantidad, confianza="ALTA")


# ---------------------------------------------------------------------------
# Doble de prueba para el contrato NUEVO (`Interpretacion`).
#
# OJO CON QUÉ ES Y QUÉ NO ES: son reglas de palabras clave, no un modelo.
# Sirven para que los tests corran sin Ollama y en microsegundos, y para tener
# un punto de comparación. NO sirven como medición: la única medición honesta
# es `vb golden` contra el modelo de verdad, y la línea base honesta es
# `vb golden --solo-python`, que apaga esto también.
# ---------------------------------------------------------------------------


def _interpretar_por_reglas(texto: str):
    import unicodedata

    from app.domain.interpretacion import (
        Acto,
        Atributo,
        Entidad,
        Interpretacion,
    )

    t = "".join(
        c
        for c in unicodedata.normalize("NFD", texto.lower())
        if unicodedata.category(c) != "Mn"
    )

    def hay(*palabras: str) -> bool:
        return any(p in t for p in palabras)

    # El ORDEN importa: lo más específico primero. Es la misma trampa que
    # tendrá el modelo de verdad, y por eso existe el golden dataset.
    if hay("humano", "asesor", "persona", "alguien", "llamen", "llamar"):
        return Interpretacion(acto=Acto.HUMANO, confianza="ALTA")
    if hay("partido", "roto", "se cayo", "devolver", "reclamo", "no me ha llegado"):
        return Interpretacion(acto=Acto.HUMANO, entidad=Entidad.PEDIDO)
    if hay("cancelar", "ya no lo quiero", "cancelalo"):
        return Interpretacion(acto=Acto.CANCELAR, entidad=Entidad.PEDIDO)
    if hay("ya pague", "ya abone", "transferencia", "consign", "comprobante"):
        return Interpretacion(acto=Acto.INFORMAR, entidad=Entidad.PAGO)
    if hay("garantia", "se le cae una piedra"):
        return Interpretacion(acto=Acto.PREGUNTAR, atributo=Atributo.GARANTIA)
    if hay("material", "plata de verdad", "de que material"):
        return Interpretacion(acto=Acto.PREGUNTAR, atributo=Atributo.MATERIAL)
    if hay("contraentrega", "contra entrega", "cuando lo reciba"):
        return Interpretacion(
            acto=Acto.PREGUNTAR, entidad=Entidad.PAGO, atributo=Atributo.CONTRAENTREGA
        )
    if hay("medios de pago", "como puedo pagar", "tarjeta", "nequi"):
        return Interpretacion(
            acto=Acto.PREGUNTAR, entidad=Entidad.PAGO, atributo=Atributo.MEDIOS_DE_PAGO
        )
    if hay("dorado", "oro", "enchapad"):
        return Interpretacion(
            acto=Acto.PREGUNTAR,
            entidad=Entidad.COLOR,
            atributo=Atributo.COLOR_DISPONIBLE,
        )
    # CON ARTÍCULO DELANTE, y no la palabra suelta: «envío» es un sustantivo y
    # un verbo. «A qué número te envío los 60?» —una clienta de verdad, a punto
    # de pagar— se leía como una pregunta por el costo del flete. Esto es el
    # doble de prueba, así que el fallo no le costaba una venta a nadie, pero
    # sí falseaba la línea base del golden: medía mal justo el mensaje que más
    # importa de toda la conversación.
    if hay("el envio", "los envios", "envio nacional", "de donde son", "el flete"):
        return Interpretacion(
            acto=Acto.PREGUNTAR, entidad=Entidad.ENVIO, atributo=Atributo.COSTO_ENVIO
        )
    if hay("se demora", "cuantos dias", "tarda"):
        return Interpretacion(acto=Acto.PREGUNTAR, atributo=Atributo.TIEMPO)
    if hay("como mido", "no se mi talla", "guia", "no tengo regla"):
        return Interpretacion(
            acto=Acto.PREGUNTAR, entidad=Entidad.TALLA, atributo=Atributo.COMO_MEDIR
        )
    if hay("ejemplos", "fotos", "muestras", "como queda"):
        return Interpretacion(acto=Acto.CONSULTAR, entidad=Entidad.IMAGEN)
    if hay("sigamos", "continuemos", "volvamos"):
        return Interpretacion(acto=Acto.RETOMAR)
    if hay("tambien quiero", "uno mas", "agregame", "agregale"):
        return Interpretacion(acto=Acto.AGREGAR, entidad=Entidad.PRODUCTO)
    if hay("mejor no quiero", "quitame"):
        return Interpretacion(acto=Acto.ELIMINAR, entidad=Entidad.PRODUCTO)
    if hay("mejor que sea"):
        return Interpretacion(acto=Acto.MODIFICAR, entidad=Entidad.COLOR)
    if hay("cambiame la talla"):
        return Interpretacion(acto=Acto.MODIFICAR, entidad=Entidad.TALLA)
    if hay("cuanto debo", "cuanto me falta", "saldo"):
        return Interpretacion(
            acto=Acto.CONSULTAR, entidad=Entidad.PEDIDO, atributo=Atributo.SALDO
        )
    if hay("mi pedido", "mis pedidos", "ya lo enviaron", "mi anillo", "novedad"):
        return Interpretacion(
            acto=Acto.CONSULTAR, entidad=Entidad.PEDIDO, atributo=Atributo.ESTADO
        )
    if hay("talla"):
        return Interpretacion(acto=Acto.INFORMAR, entidad=Entidad.TALLA)
    if hay("corazon", "dedos", "deditos", "toda negra"):
        return Interpretacion(acto=Acto.INFORMAR, entidad=Entidad.COLOR)
    if hay("nombre", "que diga", "grabado"):
        return Interpretacion(acto=Acto.INFORMAR, entidad=Entidad.GRABADO)
    if hay("quiero", "pedir el mio", "me gustaria"):
        return Interpretacion(acto=Acto.COMPRAR, entidad=Entidad.PRODUCTO)
    if hay("precio", "cuanto vale", "cuanto cuesta"):
        return Interpretacion(
            acto=Acto.CONSULTAR, entidad=Entidad.PRODUCTO, atributo=Atributo.PRECIO
        )
    if hay("informacion", "info", "me interesa", "anillo"):
        return Interpretacion(acto=Acto.CONSULTAR, entidad=Entidad.PRODUCTO)
    if hay("hola", "buenas", "buenos dias"):
        return Interpretacion(acto=Acto.SALUDAR, confianza="ALTA")
    if hay("gracias", "ok", "bendiciones", "lindos"):
        return Interpretacion(acto=Acto.CONVERSAR)
    if hay("confirmo", "lo quiero", "dale", "si porfa", "listo"):
        return Interpretacion(acto=Acto.CONFIRMAR)
    return Interpretacion(acto=Acto.OTRO, confianza="BAJA")
