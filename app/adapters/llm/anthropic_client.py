"""Claude como modelo de RESCATE. Implementa el mismo `LLMPort` que Ollama.

════════════════════════════════════════════════════════════════════════════
QUÉ HACE AQUÍ UN MODELO DE PAGO EN UN PROYECTO QUE CORRE LOCAL
════════════════════════════════════════════════════════════════════════════
El modelo de siempre es el de 4 GB de VRAM que vive en el PC (`OLLAMA_MODEL`),
y contesta todos los turnos. Este solo se usa cuando aquel NO entendió nada y
Python tampoco le sacó ningún dato de la frase — los turnos que acababan en «no
te entendí» y son los que pierden la venta. Ver `Interprete._rescatar`.

Por eso la factura es pequeña: se paga por turno RESCATADO, no por turno. En la
medición, de tres mensajes se gastó en uno.

Y por eso el modelo es Haiku (5.5 desde el 12/10), el más barato: la tarea es
describir una frase corta con campos cerrados, no razonar. Para eso, el modelo
más caro no acierta más y sí cuesta más y tarda más — y del otro lado hay una
clienta esperando.

════════════════════════════════════════════════════════════════════════════
DEVUELVE EL MISMO OBJETO CERRADO, Y ESO NO ES NEGOCIABLE
════════════════════════════════════════════════════════════════════════════
`extract` devuelve el mismo Pydantic con `Enum` cerrados que devuelve Ollama, y
lo valida la API contra el esquema (`output_format`). Un modelo mejor describe
mejor; no decide más. Su respuesta sigue pasando por `_corregir`, así que
tampoco puede llamar a una persona por su cuenta ni inventarse un color.

Esa es la razón de que cambiar de modelo cueste una línea en el contenedor: el
sistema no conoce modelos, conoce un puerto.
"""

from __future__ import annotations

import base64
import logging
import time
from typing import Any

from pydantic import BaseModel

from app.domain import consumo
from app.infra.trazas import traza, uso_del_modelo

log = logging.getLogger("ventabot.claude")

#: Cuánto se le deja escribir. Es una clasificación —un objeto pequeño con
#: campos cerrados—, pero el razonamiento también cuenta contra este tope, y
#: quedarse corto trunca la respuesta a mitad y obliga a repetir la llamada.
MAX_TOKENS = 4096

#: Cuánto se espera antes de rendirse, en segundos.
#:
#: El SDK espera DIEZ MINUTOS por defecto, y aquí eso no vale: del otro lado hay
#: una clienta mirando WhatsApp. Una llamada normal tarda ~2,5 s medidos
#: (sept. 2026), así que 10 es de sobra; si no contesta en 10, se sigue con lo
#: que ya teníamos, que es
#: exactamente lo que hace el rescate cuando falla.
#:
#: La PRIMERA llamada con un esquema nuevo tardó más de 8 s (compila la
#: gramática y escribe la caché): por eso el servidor calienta al arrancar.
#:
#: Con un reintento, el peor caso son ~20 s. El reintento se deja porque un
#: parpadeo de red no debería costar el rescate del turno.
ESPERA_MAXIMA_S = 10.0

#: Cuánto se le deja al CALENTAMIENTO del arranque. Nadie espera ahí.
#:
#: La primera llamada con un esquema nuevo compila la gramática en el
#: proveedor. Medido el 20/09 al cambiar un campo de `Jugada`: 62 s la primera
#: y 2 s todas las demás. Con el tope de las clientas (10 s) el calentamiento
#: se rendía antes de que compilara, la gramática no se guardaba nunca y TODAS
#: las llamadas siguientes fallaban igual: el bot entero inservible por un
#: campo. Cambiar el esquema tiene que costar un arranque lento, no el bot.
ESPERA_AL_CALENTAR_S = 150.0

#: SE CACHEA EL PROMPT, y ahí está casi todo el ahorro.
#:
#: Medido: 4.757 tokens de entrada por rescate y 50 de salida. O sea que el 95%
#: de lo que cuesta esto es el prompt, que es SIEMPRE EL MISMO. Una lectura de
#: caché cuesta la décima parte, así que el rescate baja de USD 0,0050 a unos
#: USD 0,0009 en cuanto hay dos seguidos.
#:
#: Lo que se cachea son 4.738 tokens medidos, y la mayor parte NO es el prompt
#: (que son unas 1.200): es el ESQUEMA de `PropuestaDelModelo`, con sus enums
#: enteros. Por eso la cifra es mucho mayor que el archivo del prompt.
#:
#: ⚠️ Haiku 4.5 exige 4.096 tokens como MÍNIMO para cachear, y por debajo no
#: cachea SIN AVISAR: `cache_creation_input_tokens` sale 0 y todo parece normal.
#: Hoy hay margen, pero es poco: recortar el esquema o el prompt puede dejar
#: esto por debajo del mínimo y el ahorro desaparece en silencio.
#:
#: El marcador va en el BLOQUE DEL SISTEMA y no arriba con
#: `cache_control=`: eso último cachea «el último bloque cacheable», que aquí
#: sería el mensaje de la clienta — distinto en cada turno, así que no acertaría
#: nunca. Lo estable es el prompt, y es lo único que se cachea.
CACHEAR = {"type": "ephemeral"}

#: NO se manda `output_config.effort`, y es a propósito: Haiku 4.5 lo RECHAZA
#: con un 400. El modelo por defecto aquí es Haiku porque esto es clasificar
#: una frase corta —no hay nada que razonar largo— y aun así está muy por
#: encima del modelo de 3B que acaba de fallar. Si algún día se pone un modelo
#: de la familia Opus, su esfuerzo por defecto ya es el correcto.


def _encoger(datos: bytes) -> bytes:
    """Una foto de móvil son miles de tokens de imagen. Se reduce antes.

    Mismo helper que usa Ollama. Si Pillow no puede abrirla, va tal cual.
    """
    try:
        from app.adapters.llm.imagenes import encoger

        return encoger(datos)
    except Exception:  # pragma: no cover - una foto rara no tumba el turno
        return datos


def _tipo_de_imagen(datos: bytes) -> str:
    """El media type REAL de la foto. La API rechaza uno que no coincida.

    WhatsApp manda JPEG casi siempre, pero una captura de pantalla puede ser
    PNG y un sticker WEBP. Decir «jpeg» a todo hacía fallar justo el
    comprobante, que suele ser una captura.
    """
    if datos.startswith(b"\x89PNG"):
        return "image/png"
    if datos[:4] == b"RIFF" and datos[8:12] == b"WEBP":
        return "image/webp"
    if datos.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    return "image/jpeg"


def _sin_pensar(modelo: str) -> dict:
    """Cómo se le dice «no pienses» a cada modelo.

    Sonnet 5.5 y Opus 5.5 RECHAZAN `{"type": "disabled"}` con un 400 (29/09):
    Sonnet 5.5 lo apaga con `between_tools` (con el esfuerzo por defecto, que
    es el que se usa aquí); Opus 5.5 no deja apagarlo, así que se le deja
    pensar (adaptativo). Los anteriores (Sonnet 5, Opus 5) aceptan `disabled`,
    y también Haiku 5.5 (que rechaza `between_tools`, 12/10).
    """
    if modelo.startswith("claude-sonnet-5-5"):
        return {"type": "between_tools"}
    if modelo.startswith("claude-opus-5-5"):
        return {"type": "adaptive"}
    return {"type": "disabled"}


class ClaudeLLM:
    """Implementa `app.domain.ports.LLMPort` contra la API de Anthropic."""

    #: Aprovecha una línea de estado operativo junto al mensaje (ver
    #: `Interprete._para_el_modelo`). Es un modelo que la usa bien; el local de
    #: 3B no la recibe.
    acepta_contexto = True

    def __init__(self, model: str, api_key: str) -> None:
        self.model = model
        self._api_key = api_key
        self._client: Any = None  # perezoso: no se conecta hasta que se use
        #: Los fallos de cuenta —sin saldo, clave revocada— no se arreglan
        #: solos y se repiten en CADA turno. Avisar una vez y callar: un aviso
        #: que sale cien veces iguales esconde lo único que importaba.
        self._ya_avise = False

    def _get_client(self) -> Any:
        if self._client is None:
            import anthropic  # import perezoso, como en el cliente de Ollama

            # La clave se pasa explícita y NO por el entorno: en este proyecto
            # vive en el `.env`, que lo lee pydantic-settings y no llega a
            # `os.environ`. El SDK no la encontraría sola.
            self._client = anthropic.Anthropic(
                api_key=self._api_key,
                max_retries=1,
                timeout=ESPERA_MAXIMA_S,
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
        """Describe el mensaje, devolviendo el esquema ya validado.

        Levanta la excepción si algo falla. Quien llama —`_rescatar`— la
        recoge y se queda con lo que ya tenía: un rescate que no rescata no
        puede costar un turno.
        """
        contenido: list[dict] = []
        for imagen in images or []:
            imagen = _encoger(imagen)
            contenido.append(
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": _tipo_de_imagen(imagen),
                        "data": base64.standard_b64encode(imagen).decode(),
                    },
                }
            )
        contenido.append({"type": "text", "text": user_text})

        opciones: dict[str, Any] = {}
        if not self.model.startswith("claude-haiku-4"):
            # Los modelos 5 piensan por defecto. Para describir una frase con
            # campos cerrados no hace falta, y cada segundo pensando es un
            # segundo de la clienta mirando el chat. (Haiku 4.5 no piensa por
            # defecto y RECHAZA `effort`, por eso a él no se le manda nada.
            # Haiku 5.5 sí piensa a veces —con una foto, medido el 12/10: 2,0 s
            # pensando contra 1,3 s sin— y acepta `disabled`.)
            opciones["thinking"] = _sin_pensar(self.model)

        inicio = time.perf_counter()
        try:
            cliente = self._get_client()
            if calentando:
                # Sin prisa: es el arranque y no hay nadie esperando.
                cliente = cliente.with_options(timeout=ESPERA_AL_CALENTAR_S)
            respuesta = cliente.messages.parse(
                model=self.model,
                max_tokens=MAX_TOKENS,
                system=[
                    {"type": "text", "text": system_prompt, "cache_control": CACHEAR}
                ],
                messages=[{"role": "user", "content": contenido}],
                output_format=schema,
                **opciones,
            )
        except Exception as exc:
            consumo.registrar(
                self.model, ms=int((time.perf_counter() - inicio) * 1000), ok=False
            )
            # Se explica en claro antes de dejarla subir: el log es lo único
            # que va a leer alguien a las 11 de la noche.
            self._explicar(exc)
            raise

        self._apuntar_uso(respuesta, inicio)
        if respuesta.parsed_output is None:
            raise ValueError(f"la respuesta no encajó en {schema.__name__}")
        return respuesta.parsed_output

    def _apuntar_uso(self, respuesta, inicio: float) -> None:
        """Tokens y tiempo de esta llamada, para el registro de decisiones."""
        uso = getattr(respuesta, "usage", None)

        def n(campo: str) -> int:
            valor = getattr(uso, campo, 0) if uso is not None else 0
            return valor if isinstance(valor, int) else 0

        consumo.registrar(
            self.model,
            entrada=n("input_tokens"),
            salida=n("output_tokens"),
            cache_leida=n("cache_read_input_tokens"),
            cache_escrita=n("cache_creation_input_tokens"),
            ms=int((time.perf_counter() - inicio) * 1000),
        )
        uso_del_modelo(
            self.model,
            entrada=n("input_tokens"),
            salida=n("output_tokens"),
            cache_leida=n("cache_read_input_tokens"),
            cache_escrita=n("cache_creation_input_tokens"),
        )

    def _explicar(self, exc: Exception) -> None:
        """Un aviso que diga qué hacer, no solo qué pasó.

        Los dos primeros son problemas de CUENTA: no se arreglan solos, se
        repiten en cada turno y no los ve nadie si van enterrados en un volcado
        de JSON. Se avisan una vez, en claro, y luego se callan.
        """
        import anthropic

        texto = str(exc)

        # El fallo nº1 de una cuenta nueva, y no es un error de clave: la clave
        # es válida y la API contesta 400. Sin este caso, el log soltaba el
        # JSON entero de Anthropic en cada mensaje de cada clienta.
        if "credit balance is too low" in texto:
            if not self._ya_avise:
                log.error("=" * 62)
                log.error("LA CUENTA DE CLAUDE NO TIENE SALDO. No hay rescate.")
                log.error("Ponle saldo en console.anthropic.com -> Plans & Billing,")
                log.error("o deja LLM_FUERTE_MODEL vacío en el .env para apagarlo.")
                log.error(
                    "El bot sigue funcionando con el modelo local, igual que antes."
                )
                log.error("=" * 62)
                self._ya_avise = True
            return

        if isinstance(
            exc, anthropic.AuthenticationError | anthropic.PermissionDeniedError
        ):
            if not self._ya_avise:
                log.error(
                    "la clave de Claude no sirve (caducó o se revocó): pon una "
                    "nueva en ANTHROPIC_API_KEY, en el .env"
                )
                self._ya_avise = True
            return

        if isinstance(exc, anthropic.RateLimitError):
            log.warning("Claude está limitando el ritmo; este turno va sin rescate")
        elif isinstance(exc, anthropic.APIConnectionError):
            log.warning("sin internet para llegar a Claude; este turno va sin rescate")
        else:
            log.warning("Claude no pudo interpretar (%s)", exc)
