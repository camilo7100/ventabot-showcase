"""Guarda las fotos del anillo terminado y las publica para que Meta las baje.

POR QUÉ ESTO EXISTE
===================
El mensaje que le pide $140.000 a una clienta funciona por una sola razón:
porque va con la foto de SU anillo terminado. Sin la foto, es un cobro; con
la foto, es la entrega de algo que ya existe y que ella reconoce.

Hoy Lía manda esas fotos a mano, una por una, desde la galería del celular.

CÓMO SE PUBLICAN, Y POR QUÉ ASÍ
===============================
Meta no baja la imagen con nuestras credenciales: sus servidores hacen un GET
anónimo a una URL pública. Eso significa que la foto TIENE que ser accesible
sin token, y ahí está todo el riesgo.

La defensa es que la URL sea imposible de adivinar: cada archivo se guarda con
un nombre de 32 caracteres aleatorios criptográficos. No se puede listar el
directorio, no se puede iterar, y un identificador correlativo (`/fotos/1`,
`/fotos/2`) habría dejado ver las fotos de todas las clientas a cualquiera que
contara hasta cien.

Es el mismo mecanismo que usan los enlaces "no listados" de cualquier servicio
de fotos, y tiene sus mismos límites: quien tenga el enlace, ve la foto.
Para fotos de un anillo es el equilibrio correcto. Para un documento de
identidad no lo sería.

[POR DEFINIR] Las fotos se borran a los 90 días. Cuando esto pase a la nube
(S3, R2), el adaptador cambia y el resto del sistema no se entera: solo se
usa a través de `guardar()` y `ruta_de()`.
"""

from __future__ import annotations

import mimetypes
import secrets
from dataclasses import dataclass
from pathlib import Path

#: Lo que WhatsApp acepta como imagen. Nada más entra: un archivo que Meta no
#: sepa mostrar se convierte en un mensaje roto que la clienta no entiende.
TIPOS: dict[str, str] = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
}

#: Tope de Meta para imágenes: 5 MB. Una foto de celular moderna los pasa sin
#: esfuerzo, así que se comprueba ANTES de guardar y se le dice a Lía, en vez
#: de dejar que Meta rechace el envío media hora después.
MAX_BYTES = 5 * 1024 * 1024

#: Bytes con los que empieza cada formato. Se comprueba el CONTENIDO y no la
#: extensión: el navegador manda el `content-type` que le da la gana, y un
#: `.jpg` que en realidad es otra cosa es una forma clásica de colar un
#: archivo donde no debe.
FIRMAS: tuple[tuple[bytes, str], ...] = (
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"RIFF", "image/webp"),  # RIFF....WEBP
)


class FotoInvalida(ValueError):
    """El archivo no sirve. El mensaje explica por qué, en castellano."""


@dataclass(frozen=True)
class Foto:
    """Una foto guardada. `nombre` es lo único que se guarda en el pedido."""

    nombre: str
    bytes_totales: int
    tipo: str


def detectar_tipo(datos: bytes) -> str | None:
    """El formato real, mirando los primeros bytes. None si no es una imagen."""
    for firma, tipo in FIRMAS:
        if datos.startswith(firma):
            if tipo == "image/webp" and datos[8:12] != b"WEBP":
                continue
            return tipo
    return None


class AlmacenDeFotos:
    def __init__(self, carpeta: Path) -> None:
        self.carpeta = carpeta
        self.carpeta.mkdir(parents=True, exist_ok=True)

    def guardar(self, datos: bytes) -> Foto:
        """Valida y guarda. Lanza `FotoInvalida` con un motivo legible."""
        if not datos:
            raise FotoInvalida("el archivo llegó vacío")
        if len(datos) > MAX_BYTES:
            mb = len(datos) / 1024 / 1024
            raise FotoInvalida(
                f"la foto pesa {mb:.1f} MB y WhatsApp solo acepta hasta 5 MB. "
                f"Mándala desde la galería en tamaño mediano."
            )
        tipo = detectar_tipo(datos)
        if tipo is None:
            raise FotoInvalida(
                "eso no parece una foto (solo JPG, PNG o WEBP). "
                "Si es un video, todavía no se pueden mandar por aquí."
            )

        # 32 caracteres aleatorios: la URL no se puede adivinar ni recorrer.
        nombre = secrets.token_urlsafe(24) + TIPOS[tipo]
        (self.carpeta / nombre).write_bytes(datos)
        return Foto(nombre=nombre, bytes_totales=len(datos), tipo=tipo)

    def ruta_de(self, nombre: str) -> Path | None:
        """La ruta en disco, o None si el nombre no es válido o no existe.

        `Path.name` recorta cualquier `../`: sin eso, un nombre como
        `../../.env` serviría el archivo de secretos por una URL pública. Es
        la vulnerabilidad más antigua que existe y sigue apareciendo.
        """
        seguro = Path(nombre).name
        if not seguro or seguro != nombre:
            return None
        destino = self.carpeta / seguro
        # Segunda cerradura: se comprueba que el archivo resuelto siga dentro
        # de la carpeta, por si un enlace simbólico apuntara afuera.
        try:
            destino.resolve().relative_to(self.carpeta.resolve())
        except (ValueError, OSError):
            return None
        return destino if destino.is_file() else None

    def tipo_de(self, nombre: str) -> str:
        return mimetypes.guess_type(nombre)[0] or "application/octet-stream"

    def borrar(self, nombre: str) -> bool:
        ruta = self.ruta_de(nombre)
        if ruta is None:
            return False
        ruta.unlink()
        return True
