"""Bajar los archivos que manda la clienta. Implementa `MediaPort`.

WhatsApp no manda la foto: manda un `media_id`, y bajarlo son DOS llamadas
con token, de las cuales la primera devuelve una URL que caduca en cinco
minutos. Por eso esto existe como adaptador y no como una línea suelta: el
día que haya Instagram, la diferencia se resuelve aquí y en ningún otro sitio.

DE MOMENTO NO GUARDA NADA
=========================
`store()` devuelve una ruta local. Guardar las fotos de las clientas en un
almacén externo es una decisión con consecuencias legales (son datos suyos) y
de coste, y todavía no hace falta: la foto se mira, se saca el dato, y lo que
se conserva es el dato — no la imagen. Cuando haga falta conservarlas, se
cambia esta clase entera y nada más.
"""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path

log = logging.getLogger("ventabot.media")

#: Tope de lo que se baja. Una foto de móvil pesa 2-5 MB; más que esto es un
#: vídeo o un error, y bajarlo bloquearía el turno varios segundos.
MAXIMO_BYTES = 12 * 1024 * 1024


class MediaDeWhatsApp:
    """Baja adjuntos usando el canal, que es quien tiene el token."""

    def __init__(self, canal, carpeta: Path | None = None) -> None:
        self._canal = canal
        self._carpeta = carpeta

    def download(self, media_id_or_url: str) -> bytes:
        datos = self._canal.download_media(media_id_or_url)
        if len(datos) > MAXIMO_BYTES:
            log.warning(
                "adjunto de %s MB: se descarta (tope %s MB)",
                len(datos) // 1024 // 1024,
                MAXIMO_BYTES // 1024 // 1024,
            )
            return b""
        return datos

    def store(self, data: bytes, *, filename: str) -> str:
        if self._carpeta is None:
            return ""
        self._carpeta.mkdir(parents=True, exist_ok=True)
        # El nombre lleva el hash: dos veces el mismo archivo es un archivo.
        huella = hashlib.sha256(data).hexdigest()[:16]
        destino = self._carpeta / f"{huella}-{Path(filename).name}"
        destino.write_bytes(data)
        return str(destino)
