"""Los ojos: un modelo de visión, aparte del que lee texto.

Implementa `app.domain.ports.VisionPort`. Reutiliza el cliente de Ollama que
ya existe, pero con SU PROPIO modelo, elegido en `OLLAMA_VISION_MODEL`. Esa
separación es el punto entero: el día que la lectura de fotos se quede corta
se cambia esa variable y la conversación no se entera.

FALLO SEGURO, OTRA VEZ
======================
Si el modelo no está, no responde, o devuelve algo inválido, se devuelve una
`LecturaDeImagen` de tipo OTRA con `seguro=False`. Eso NO rompe el turno:
`vision.entender()` la convierte en «esto lo mira una persona» y la
conversación continúa. Una foto que no se pudo leer no puede dejar a la
clienta sin respuesta.
"""

from __future__ import annotations

import logging

from app.domain.vision import LecturaDeImagen, TipoDeImagen
from app.infra.trazas import traza

log = logging.getLogger("ventabot.ojos")

#: Qué buscar según lo que estábamos esperando. No obliga —una clienta manda
#: el comprobante cuando le pedías la talla— pero mirar buscando algo concreto
#: le sube mucho el acierto a un modelo pequeño.
PISTAS: dict[str, str] = {
    "talla": (
        "Lo más probable es que sea un ANILLO apoyado sobre una REGLA para "
        "medir la talla."
    ),
    "colores": (
        "Lo más probable es que sea una foto del MUESTRARIO de circones con "
        "algún color señalado, marcado o rodeado."
    ),
    "comprobante": ("Lo más probable es que sea el COMPROBANTE de una transferencia."),
}


class OjosDeOllama:
    """Un modelo de visión detrás del puerto. Nada más."""

    def __init__(self, llm, prompt: str) -> None:
        #: Un `LLMPort` cualquiera cuyo `extract` acepte imágenes. Se recibe ya
        #: construido (con el modelo de visión dentro) para que este objeto no
        #: tenga que saber de hosts ni de puertos TCP.
        self._llm = llm
        self._prompt = prompt

    @traza("mirar_foto", tipo="llm")
    def leer(self, imagen: bytes, *, pista: str = "") -> LecturaDeImagen:
        instruccion = self._prompt
        if ayuda := PISTAS.get(pista):
            instruccion = f"{instruccion}\n\nCONTEXTO: {ayuda}"
        try:
            lectura = self._llm.extract(
                instruccion, "Describe esta imagen.", LecturaDeImagen, images=[imagen]
            )
        except Exception as exc:
            # Sin traza: puede pasar en cada foto si el modelo no está bajado,
            # y cuarenta líneas repetidas entierran lo único útil.
            log.warning("los ojos no pudieron leer la imagen (%s)", exc)
            return LecturaDeImagen(tipo=TipoDeImagen.OTRA, seguro=False)
        if not isinstance(lectura, LecturaDeImagen):  # pragma: no cover - defensa
            return LecturaDeImagen(tipo=TipoDeImagen.OTRA, seguro=False)
        return lectura


class OjosCiegos:
    """No mira nada. Es lo que hay cuando no se configura un modelo de visión.

    Devuelve OTRA sin seguridad, que el dominio traduce a «que lo mire una
    persona». Es el comportamiento correcto por defecto: sin ojos el bot no
    adivina, avisa.
    """

    def leer(self, imagen: bytes, *, pista: str = "") -> LecturaDeImagen:
        return LecturaDeImagen(
            tipo=TipoDeImagen.OTRA,
            seguro=False,
            descripcion="no hay lector de imágenes configurado",
        )
