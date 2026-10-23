"""GPT (OpenAI): en producción, el PRIMERO en contestar; Claude es su respaldo
(ADR 0027, 29/09).

Implementa el mismo `LLMPort` que `ClaudeLLM`: recibe el prompt, el mensaje y
el esquema Pydantic, y devuelve el objeto ya validado. El orden lo arma
`_modelos_con_respaldo` en el contenedor (`IA_PRINCIPAL`, `OPENAI_MODELO`,
`OPENAI_ESFUERZO`…); la clave va solo en el `.env`.

Usa las salidas estructuradas de OpenAI (`chat.completions.parse` con
`response_format`): la respuesta llega validada contra el mismo esquema que
usa Claude. Se comprobó sin gastar nada que la `Jugada` entera convierte al
esquema estricto de OpenAI (29/09, openai 3.20.0).
"""

from __future__ import annotations

import base64
import logging
import time
from typing import Any

from pydantic import BaseModel

from app.domain import consumo
from app.infra.trazas import traza, uso_del_modelo

log = logging.getLogger("ventabot.gpt")

#: Lo más que se espera una respuesta. Igual que con Claude.
ESPERA_MAXIMA_S = 60
MAX_TOKENS = 4096

#: La CACHÉ del prompt. OpenAI la hace sola cuando el comienzo de la llamada se
#: repite (≥1.024 tokens): aquí el prompt de la asesora (~9.200 tokens, fijo
#: mientras el bot vive) y el esquema. Medido en producción el 29/09: 9.180 de
#: 9.214 tokens salen de caché, a US$0,01 el millón en vez de 0,10 (luna).
#:
#: Sin retención larga, la caché se borra tras 5–10 min sin uso, y un negocio
#: micro pasa más tiempo quieto que ocupado: casi todas las clientas pagarían
#: el prompt entero. Con `24h` sobrevive entre clientas y no cuesta nada extra
#: (developers.openai.com, 29/09). `prompt_cache_key` NO se usa: con GPT-6 el
#: enrutamiento es automático y en la medición solo agregó un primer fallo.
RETENCION_DE_CACHE = "24h"


def _tipo_de_imagen(datos: bytes) -> str:
    if datos.startswith(b"\x89PNG"):
        return "image/png"
    if datos[:4] == b"RIFF" and datos[8:12] == b"WEBP":
        return "image/webp"
    return "image/jpeg"


class OpenAILLM:
    """Implementa `app.domain.ports.LLMPort` contra la API de OpenAI."""

    acepta_contexto = True

    def __init__(
        self, model: str, api_key: str, *, esfuerzo: str = "", cliente: Any = None
    ) -> None:
        self.model = model
        self._api_key = api_key
        #: Cuánto razona (`none`, `low`…). Vacío = el de fábrica del modelo.
        self._esfuerzo = esfuerzo
        self._client: Any = cliente  # perezoso; las pruebas pasan uno falso

    def _get_client(self) -> Any:
        if self._client is None:
            import openai  # import perezoso: solo si el respaldo está encendido

            self._client = openai.OpenAI(
                api_key=self._api_key, max_retries=1, timeout=ESPERA_MAXIMA_S
            )
        return self._client

    @traza("modelo", tipo="llm")
    def extract(
        self,
        system_prompt: str,
        user_text: str,
        schema: type[BaseModel],
        *,
        calentando: bool = False,
        images: list[bytes] | None = None,
    ) -> BaseModel:
        contenido: list[dict] = [{"type": "text", "text": user_text}]
        for imagen in images or []:
            try:
                from app.adapters.llm.imagenes import encoger

                imagen = encoger(imagen)
            except Exception as exc:  # pragma: no cover - una foto rara va tal cual
                log.debug("no se pudo encoger la foto (%s)", exc)
            datos = base64.standard_b64encode(imagen).decode()
            contenido.append(
                {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:{_tipo_de_imagen(imagen)};base64,{datos}"
                    },
                }
            )
        extra: dict[str, Any] = {}
        if self._esfuerzo:
            extra["reasoning_effort"] = self._esfuerzo
        inicio = time.perf_counter()
        try:
            respuesta = self._get_client().chat.completions.parse(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": contenido},
                ],
                response_format=schema,
                max_completion_tokens=MAX_TOKENS,
                prompt_cache_retention=RETENCION_DE_CACHE,
                **extra,
            )
        except Exception as exc:
            consumo.registrar(
                self.model, ms=int((time.perf_counter() - inicio) * 1000), ok=False
            )
            log.warning("GPT no pudo interpretar (%s)", exc)
            raise
        uso = getattr(respuesta, "usage", None)
        # OpenAI cuenta lo de caché DENTRO de `prompt_tokens`; Anthropic, aparte.
        # Se separa para que el costo sea el real y se vea si la caché funciona.
        entrada = int(getattr(uso, "prompt_tokens", 0) or 0)
        detalle = getattr(uso, "prompt_tokens_details", None)
        de_cache = min(entrada, int(getattr(detalle, "cached_tokens", 0) or 0))
        salida = int(getattr(uso, "completion_tokens", 0) or 0)
        consumo.registrar(
            self.model,
            entrada=entrada - de_cache,
            cache_leida=de_cache,
            salida=salida,
            ms=int((time.perf_counter() - inicio) * 1000),
        )
        uso_del_modelo(
            self.model,
            entrada=entrada - de_cache,
            salida=salida,
            cache_leida=de_cache,
            proveedor="openai",
        )
        mensaje = respuesta.choices[0].message
        if getattr(mensaje, "refusal", None):
            raise ValueError(f"GPT no quiso contestar: {mensaje.refusal}")
        if mensaje.parsed is None:
            raise ValueError(f"la respuesta de GPT no encajó en {schema.__name__}")
        return mensaje.parsed
