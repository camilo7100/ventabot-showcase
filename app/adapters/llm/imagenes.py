"""Encoger una foto antes de dársela al modelo de visión.

════════════════════════════════════════════════════════════════════════════
POR QUÉ ESTO NO ES UNA OPTIMIZACIÓN PREMATURA
════════════════════════════════════════════════════════════════════════════
Se midió. `vb ojos` sobre las fotos reales del proyecto, con qwen2.5vl:3b en
una GPU de 4 GB, daba **47 segundos de mediana y 82 en el peor caso**. Una
clienta no espera 47 segundos por una respuesta; se va, o manda la foto otra
vez y se duplica el trabajo.

La causa no es el modelo: es el tamaño. Una foto de móvil son 4000×3000
píxeles y un modelo de visión la trocea en cuadraditos — cuatro veces más
lado son dieciséis veces más trozos que procesar. Bajarla al lado que de
verdad necesita no le quita información útil: la regla y el anillo se ven
igual de bien a 1024 px, porque lo que hay que leer son marcas de un
milímetro sobre un objeto que ocupa media foto.

════════════════════════════════════════════════════════════════════════════
DOS DETALLES QUE PARECEN TONTERÍA Y NO LO SON
════════════════════════════════════════════════════════════════════════════
1. LA ORIENTACIÓN. Las fotos de móvil vienen giradas con una etiqueta EXIF,
   no con los píxeles. Si se ignora, el modelo mira una regla tumbada. Se
   aplica antes de nada.
2. FALLO SEGURO. Si Pillow no está o el archivo no es una imagen válida, se
   devuelve el original tal cual. Encoger es una mejora, no un requisito: no
   puede ser el motivo de que una foto no se lea.
"""

from __future__ import annotations

import io
import logging

log = logging.getLogger("ventabot.imagenes")

#: Lado máximo, en píxeles. 1024 es el punto en el que las marcas de una
#: regla siguen siendo legibles y el modelo deja de ahogarse. Si algún día
#: hay que leer algo más fino, se sube ESTE número y se vuelve a medir con
#: `vb ojos` — que para eso existe.
LADO_MAXIMO = 1024

#: Calidad del JPEG resultante. 85 es indistinguible a ojo y pesa la mitad.
CALIDAD = 85


def encoger(datos: bytes, lado_maximo: int = LADO_MAXIMO) -> bytes:
    """La misma foto, más pequeña. O la misma foto, si algo falla."""
    if not datos:
        return datos
    try:
        from PIL import Image, ImageOps
    except ImportError:  # pragma: no cover - depende del entorno
        log.warning("sin Pillow: las fotos van a tamaño completo (más lentas)")
        return datos

    try:
        with Image.open(io.BytesIO(datos)) as imagen:
            # EXIF primero: si no, la regla se mira de lado.
            imagen = ImageOps.exif_transpose(imagen)
            if max(imagen.size) <= lado_maximo and imagen.format == "JPEG":
                return datos
            imagen.thumbnail((lado_maximo, lado_maximo), Image.LANCZOS)
            if imagen.mode not in ("RGB", "L"):
                imagen = imagen.convert("RGB")
            salida = io.BytesIO()
            imagen.save(salida, format="JPEG", quality=CALIDAD, optimize=True)
            return salida.getvalue()
    except Exception as exc:
        # Un archivo que no es una imagen, o un formato raro. No se rompe
        # nada: que lo intente el modelo con el original.
        log.warning("no se pudo encoger la foto (%s); va entera", exc)
        return datos
