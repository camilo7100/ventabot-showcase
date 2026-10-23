"""De lo que el bot QUIERE decir a lo que sale por WhatsApp.

El dominio produce `Respuesta`: una lista de piezas de texto e imágenes,
nombradas por su nombre lógico ("muestrario_circones"). Aquí se convierten en
`OutboundMessage`, que ya sabe de canales, plantillas de Meta y claves de
idempotencia.

DOS COSAS QUE SE RESUELVEN AQUÍ Y NO ANTES
==========================================
1. LA URL DE LAS IMÁGENES. Meta las baja con un GET anónimo desde internet, y
   la dirección pública cambia cada vez que se reinicia el túnel. Guardarla en
   el dominio haría que las respuestas de ayer apuntaran a una dirección
   muerta.

2. LA CLAVE DE IDEMPOTENCIA. Cada pieza necesita la suya, derivada del mensaje
   entrante y de su posición. Si Meta reenvía el webhook —y lo hace— la outbox
   descarta las cuatro piezas, no solo la primera. Sin el índice en la clave,
   un turno de cuatro mensajes se habría deduplicado a uno.
"""

from __future__ import annotations

import logging
from pathlib import Path

from app.domain.models import Channel, OutboundMessage
from app.domain.respuesta import Respuesta, Tipo

log = logging.getLogger("ventabot.salida")

#: Extensiones que se prueban para un nombre lógico, en orden. Los videos
#: van en la misma lista porque viven en la misma carpeta y se sirven por la
#: misma ruta: para el dominio, «anillo_video_1» es un nombre y ya.
EXTENSIONES = (".jpg", ".jpeg", ".png", ".webp", ".mp4")


def ruta_de_media(carpetas, nombre: str) -> Path | None:
    """El archivo de un nombre lógico, buscando en varias carpetas en orden.

    Son dos: el catálogo (versionado) y las previsualizaciones (generadas).
    El orden importa — un nombre del catálogo no lo puede pisar un archivo
    que el bot dibujó.
    """
    for carpeta in carpetas:
        if (ruta := ruta_de_imagen(carpeta, nombre)) is not None:
            return ruta
    return None


def ruta_de_imagen(carpeta: Path, nombre: str) -> Path | None:
    """El archivo de un nombre lógico, o None si no está.

    `Path.name` recorta cualquier `../`: el nombre viene de una tabla nuestra,
    pero esta función también la puede llamar código futuro con un nombre que
    venga de fuera, y entonces sería una puerta abierta al disco entero.
    """
    seguro = Path(nombre).name
    if not seguro or seguro != nombre:
        return None
    for ext in EXTENSIONES:
        candidato = carpeta / f"{seguro}{ext}"
        if candidato.is_file():
            return candidato
    return None


def a_mensajes(
    respuesta: Respuesta,
    *,
    channel: Channel,
    to: str,
    conversation_id: str,
    clave_base: str,
    url_publica: str,
    carpetas_de_media,
) -> list[OutboundMessage]:
    """Convierte la respuesta del dominio en mensajes listos para la outbox.

    Una imagen que no existe en disco NO se manda y NO tumba el turno: se
    registra y se sigue con el resto. Que falte una foto no puede dejar a la
    clienta sin la respuesta que la acompañaba.
    """
    raiz = (url_publica or "").rstrip("/")
    mensajes: list[OutboundMessage] = []
    sin_url = False

    for i, pieza in enumerate(respuesta.piezas):
        clave = f"{clave_base}:{i}"

        if pieza.tipo in (Tipo.IMAGEN, Tipo.VIDEO) and pieza.imagen:
            if not raiz:
                # Un aviso por foto llena el log de líneas iguales y esconde
                # lo único que importa, que es qué hacer. Uno por turno, con
                # el comando.
                if not sin_url:
                    log.warning(
                        "NO SE MANDAN FOTOS NI VIDEOS: falta la URL pública. "
                        "Arréglalo con  vb panel  (o pon PUBLIC_URL en el .env)"
                    )
                    sin_url = True
                continue
            if ruta_de_media(carpetas_de_media, pieza.imagen) is None:
                log.warning(
                    "falta el archivo «%s» en %s",
                    pieza.imagen,
                    carpetas_de_media,
                )
                continue
            mensajes.append(
                OutboundMessage(
                    channel=channel,
                    to=to,
                    kind="image" if pieza.tipo is Tipo.IMAGEN else "video",
                    text=pieza.texto[:1024],
                    media_url=f"{raiz}/media/{pieza.imagen}",
                    conversation_id=conversation_id,
                    idempotency_key=clave,
                )
            )
            continue

        if not pieza.texto.strip():
            continue

        mensajes.append(
            OutboundMessage(
                channel=channel,
                to=to,
                kind="options" if pieza.opciones else "text",
                text=pieza.texto,
                options=[dict(o) for o in pieza.opciones],  # type: ignore[arg-type]
                conversation_id=conversation_id,
                idempotency_key=clave,
            )
        )

    return mensajes
