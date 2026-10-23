"""Logging estructurado con el `conversation_id` SIEMPRE presente.

Por qué importa desde el día 1: cuando un cliente diga "el bot me respondió
cualquier cosa", lo único que te salva es poder filtrar por su número y ver
la secuencia completa de lo que pasó. Si el `conversation_id` no está en cada
línea, esa investigación es imposible.

    2026-09-02 14:22:01  INFO   wa:573001112233  api      entra mensaje wamid.HBg…
    2026-09-02 14:22:01  INFO   wa:573001112233  worker   nlu -> COTIZAR
    2026-09-02 14:22:02  INFO   wa:573001112233  outbox   enviado a WhatsApp

Se usa con `log_conversacion("wa:573...")` como context manager, o pasando
`extra={"conv": "..."}`. Si nadie lo pone, sale un guion y no falla.
"""

from __future__ import annotations

import contextvars
import logging
import sys

#: Variable de contexto: sobrevive a los `await` y no se mezcla entre tareas.
_conv: contextvars.ContextVar[str] = contextvars.ContextVar("conv", default="-")

VERDE, GRIS, AMARILLO, ROJO, CYAN, RST = (
    "\033[92m",
    "\033[90m",
    "\033[93m",
    "\033[91m",
    "\033[96m",
    "\033[0m",
)
COLOR_NIVEL = {
    "DEBUG": GRIS,
    "INFO": VERDE,
    "WARNING": AMARILLO,
    "ERROR": ROJO,
    "CRITICAL": ROJO,
}


class ConvFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if not hasattr(record, "conv"):
            record.conv = _conv.get()
        return True


class Formato(logging.Formatter):
    """La misma línea, con fecha o sin ella según dónde se lea.

    En la ventana del servidor la fecha sobra: se está mirando lo que pasa
    ahora. En el archivo hace falta — sin ella, leer el registro de una noche
    es adivinar si una línea es de hoy o de ayer, y cuando dos procesos
    escriben a la vez (el que se cierra y el que arranca) las líneas quedan
    desordenadas sin que se pueda notar.
    """

    def __init__(self, color: bool = True, fecha: bool = False) -> None:
        super().__init__(datefmt="%Y-%m-%d %H:%M:%S" if fecha else "%H:%M:%S")
        self.color = color

    def format(self, record: logging.LogRecord) -> str:
        hora = self.formatTime(record, self.datefmt)
        nivel = record.levelname
        conv = getattr(record, "conv", "-")
        nombre = record.name.replace("ventabot.", "")
        msg = record.getMessage()
        if record.exc_info:
            msg += "\n" + self.formatException(record.exc_info)
        if self.color:
            c = COLOR_NIVEL.get(nivel, "")
            return (
                f"{GRIS}{hora}{RST} {c}{nivel:<7}{RST} "
                f"{CYAN}{conv:<18}{RST} {GRIS}{nombre:<10}{RST} {msg}"
            )
        return f"{hora} {nivel:<7} {conv:<18} {nombre:<10} {msg}"


def configurar(nivel: str = "INFO", color: bool | None = None, archivo: str = "") -> None:
    """Consola siempre; y si hay `archivo`, además un registro que rota.

    El archivo es lo que queda para auditar después (qué entró, qué contestó,
    qué falló) aunque la ventana se haya cerrado. Rota a los 5 MB y guarda 5:
    como mucho 30 MB, nunca llena el disco del PC que hace de servidor.
    """
    if color is None:
        color = sys.stderr.isatty()
    h = logging.StreamHandler(sys.stderr)
    h.setFormatter(Formato(color=color))
    h.addFilter(ConvFilter())
    manejadores: list[logging.Handler] = [h]
    if archivo:
        from logging.handlers import RotatingFileHandler
        from pathlib import Path

        Path(archivo).parent.mkdir(parents=True, exist_ok=True)
        f = RotatingFileHandler(
            archivo, maxBytes=5_000_000, backupCount=5, encoding="utf-8"
        )
        f.setFormatter(Formato(color=False, fecha=True))
        f.addFilter(ConvFilter())
        manejadores.append(f)
    root = logging.getLogger()
    root.handlers[:] = manejadores
    root.setLevel(nivel.upper())
    # uvicorn duplica los accesos; los silenciamos y dejamos los nuestros.
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)


class log_conversacion:
    """Marca todas las líneas de este bloque con un `conversation_id`.

    with log_conversacion("wa:573001112233"):
        log.info("procesando")     # sale con el conv ya puesto
    """

    def __init__(self, conversation_id: str) -> None:
        self._id = conversation_id
        self._token = None

    def __enter__(self) -> str:
        self._token = _conv.set(self._id)
        return self._id

    def __exit__(self, *exc) -> None:
        if self._token is not None:
            _conv.reset(self._token)


def conversacion_actual() -> str:
    return _conv.get()
