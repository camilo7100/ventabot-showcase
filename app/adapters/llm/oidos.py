"""Oír las notas de voz: convertirlas en texto para que la venta siga.

════════════════════════════════════════════════════════════════════════════
POR QUÉ
════════════════════════════════════════════════════════════════════════════
Muchas clientas hablan en vez de escribir. Hasta hoy el bot contestaba «¿me lo
escribes porfa?», y ahí se pierde gente: la que mandó un audio de veinte
segundos explicando lo que quiere no lo vuelve a teclear.

Transcribir es barato (centavos por hora de audio) y no cambia nada más: el
texto transcrito entra al turno como si la clienta lo hubiera escrito, con una
marca para que la asesora sepa que vino de un audio y pueda confirmar lo que
entendió.

════════════════════════════════════════════════════════════════════════════
QUÉ NO HACE
════════════════════════════════════════════════════════════════════════════
- **No decide nada.** Devuelve texto o no devuelve nada; si falla, el turno
  sigue con el mensaje de siempre («¿me lo escribes?»). Nunca tumba una venta.
- **No corre en esta máquina.** Igual que el resto del bot, trabaja con un
  servicio en línea (`app.domain.ports.OidosPort`).
"""

from __future__ import annotations

import logging

log = logging.getLogger("ventabot.oidos")

#: Más largo que esto no es una nota de voz de WhatsApp: es otra cosa, y
#: transcribirla cuesta y tarda. Se deja pasar sin oírla.
MAXIMO_BYTES = 16 * 1024 * 1024

#: Si tarda más que esto, la clienta ya se cansó de esperar.
ESPERA_S = 25

#: El vocabulario del negocio. Whisper acierta mucho más con palabras que ya
#: «espera» oír: sin esto «Daviplata» sale «David plata» y «fucsia», «fusia».
VOCABULARIO = (
    "Luna Joyas. Anillo de huellitas en plata, con circones. Una huellita, dos "
    "huellitas. Corazón y deditos. Colores: blanco, negro, lila, morado, celeste, "
    "azul rey, rosado, fucsia, rojo, naranja, durazno, amarillo, verde oliva, verde "
    "esmeralda. Grabado, talla, abono, saldo, comprobante. Nequi, Daviplata, "
    "Bancolombia. Envío por Coordinadora a Bucaramanga, Bogotá, Medellín, Cali."
)


class OidosSordos:
    """El de siempre: no oye nada. Es lo que hay sin servicio configurado."""

    def transcribir(self, datos: bytes, mime: str = "") -> str | None:
        return None


class OidosDeGroq:
    """Whisper en Groq: lo más barato y rápido que se midió (US$0,04/hora).

    Usa la API compatible con OpenAI, así que cambiar de proveedor es cambiar
    la URL y el modelo.
    """

    def __init__(
        self,
        api_key: str,
        modelo: str = "whisper-large-v3-turbo",
        base_url: str = "https://api.groq.com/openai/v1",
        espera_s: int = ESPERA_S,
    ) -> None:
        self._key = api_key
        self._modelo = modelo
        self._base = base_url.rstrip("/")
        self._espera = espera_s

    def transcribir(self, datos: bytes, mime: str = "") -> str | None:
        if not datos or len(datos) > MAXIMO_BYTES:
            log.info("audio ignorado (%s bytes)", len(datos or b""))
            return None
        import httpx

        extension = {"audio/ogg": "ogg", "audio/mpeg": "mp3", "audio/mp4": "m4a"}.get(
            mime.split(";")[0].strip(), "ogg"
        )
        try:
            r = httpx.post(
                f"{self._base}/audio/transcriptions",
                headers={"Authorization": f"Bearer {self._key}"},
                files={"file": (f"nota.{extension}", datos, mime or "audio/ogg")},
                data={
                    "model": self._modelo,
                    # El idioma se fija: adivinarlo con audio corto y ruidoso es
                    # la forma más común de que salga en portugués.
                    "language": "es",
                    "prompt": VOCABULARIO,
                    "response_format": "text",
                    "temperature": 0,
                },
                timeout=self._espera,
            )
            r.raise_for_status()
        except Exception as exc:
            log.warning("no se pudo transcribir la nota de voz (%s)", exc)
            return None
        texto = (r.text or "").strip()
        if not texto:
            return None
        log.info("nota de voz transcrita (%s caracteres)", len(texto))
        return texto[:1500]
