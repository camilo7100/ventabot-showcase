"""Avisarle a Camilo al celular cuando algo se rompe.

════════════════════════════════════════════════════════════════════════════
POR QUÉ
════════════════════════════════════════════════════════════════════════════
Lo que más duele no es que el bot falle: es que falle **y nadie se entere**.
Un token vencido, la API caída o la cola de salida atascada se ven igual desde
afuera que un día tranquilo — hasta que aparecen tres clientas sin respuesta.

Dos formas de avisar, las dos gratis y sin cuenta que pagar:

- **ntfy**: se instala la app (Android o iPhone), se suscribe a un tema y
  llega la notificación. El servidor público `ntfy.sh` no pide registro.
- **Telegram**: si ya se usa, un bot propio y listo.

════════════════════════════════════════════════════════════════════════════
REGLAS
════════════════════════════════════════════════════════════════════════════
1. **Nunca tumba nada.** Si el aviso falla, se registra y se sigue: avisar es
   lo menos importante que pasa en un turno.
2. **Nunca repite.** El mismo problema no avisa dos veces en una hora; si no,
   una API caída manda cien notificaciones y se silencia la app.
3. **Nunca lleva datos de clientas.** El aviso dice QUÉ se rompió, no a quién:
   viaja por un servicio de terceros.
"""

from __future__ import annotations

import logging
import time

log = logging.getLogger("ventabot.avisos")

#: Cuánto se espera al servicio de avisos. Corto: esto no puede demorar nada.
ESPERA_S = 6

#: El mismo problema no vuelve a avisar hasta pasado esto.
SILENCIO_S = 3600


class SinAvisos:
    """Lo de siempre: el problema queda en el log y ya."""

    def avisar(self, titulo: str, detalle: str = "", clave: str = "") -> bool:
        return False


class _ConSilencio:
    """Lo común a los dos: no repetir el mismo aviso una y otra vez."""

    def __init__(self, silencio_s: int = SILENCIO_S) -> None:
        self._silencio = silencio_s
        self._ultimos: dict[str, float] = {}

    def _muy_seguido(self, clave: str) -> bool:
        ahora = time.monotonic()
        anterior = self._ultimos.get(clave)
        if anterior is not None and ahora - anterior < self._silencio:
            return True
        self._ultimos[clave] = ahora
        return False


class AvisosPorNtfy(_ConSilencio):
    """Notificación al celular por ntfy. Sin cuenta, sin costo."""

    def __init__(
        self,
        tema: str,
        servidor: str = "https://ntfy.sh",
        silencio_s: int = SILENCIO_S,
    ) -> None:
        super().__init__(silencio_s)
        self._tema = tema.strip("/")
        self._servidor = servidor.rstrip("/")

    def avisar(self, titulo: str, detalle: str = "", clave: str = "") -> bool:
        if self._muy_seguido(clave or titulo):
            return False
        import httpx

        try:
            httpx.post(
                f"{self._servidor}/{self._tema}",
                content=(detalle or titulo).encode("utf-8"),
                headers={
                    "Title": titulo.encode("utf-8"),
                    "Priority": "high",
                    "Tags": "warning",
                },
                timeout=ESPERA_S,
            ).raise_for_status()
            return True
        except Exception as exc:
            log.warning("no se pudo avisar por ntfy (%s)", exc)
            return False


class AvisosPorTelegram(_ConSilencio):
    """Notificación por un bot de Telegram propio."""

    def __init__(self, token: str, chat_id: str, silencio_s: int = SILENCIO_S) -> None:
        super().__init__(silencio_s)
        self._token = token
        self._chat = chat_id

    def avisar(self, titulo: str, detalle: str = "", clave: str = "") -> bool:
        if self._muy_seguido(clave or titulo):
            return False
        import httpx

        try:
            httpx.post(
                f"https://api.telegram.org/bot{self._token}/sendMessage",
                json={
                    "chat_id": self._chat,
                    "text": f"⚠️ {titulo}\n{detalle}".strip(),
                    "disable_web_page_preview": True,
                },
                timeout=ESPERA_S,
            ).raise_for_status()
            return True
        except Exception as exc:
            log.warning("no se pudo avisar por Telegram (%s)", exc)
            return False


class AvisarLosErrores(logging.Handler):
    """Todo ERROR del registro, venga de donde venga, llega al celular (16/10).

    El 14/10 el webhook se cayó dos días con un error en el registro que nadie
    vio. Los avisos con nombre (webhook roto, mensaje que no salió…) cubren lo
    que ya pasó; esto cubre lo que todavía no se nos ha ocurrido. Va el texto
    del error SIN sus valores (`record.msg`, no `getMessage()`): los valores
    traen números de clientas, y el aviso viaja por un servicio de terceros
    (regla 3). Se manda en otro hilo: un aviso lento no frena el turno.
    """

    def __init__(self, avisos) -> None:
        super().__init__(level=logging.ERROR)
        self._avisos = avisos

    def emit(self, record: logging.LogRecord) -> None:
        if record.name.startswith("ventabot.avisos"):
            return
        try:
            error = record.exc_info[1] if record.exc_info else None
            tipo = type(error).__name__ if error else ""
            donde = record.name.removeprefix("ventabot.")
            que = str(record.msg).replace("%s", "…").replace("%r", "…")[:160]
            detalle = f"{donde}: {que}" + (f" ({tipo})" if tipo else "")
            import threading

            threading.Thread(
                target=self._avisos.avisar,
                args=("⚠️ Error en VentaBot", detalle + "\nMira el registro del bot."),
                kwargs={"clave": f"error:{record.name}:{tipo}"},
                daemon=True,
            ).start()
        except Exception:  # pragma: no cover - avisar nunca tumba nada
            # En debug y no en error: un error aquí volvería a entrar a este aviso.
            log.debug("no se pudo armar el aviso del error", exc_info=True)
