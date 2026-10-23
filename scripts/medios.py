#!/usr/bin/env python3
"""¿Por qué no salen las fotos y los videos? Con una respuesta, no con una teoría.

    vb medios

════════════════════════════════════════════════════════════════════════════
QUÉ COMPRUEBA, Y POR QUÉ EN ESE ORDEN
════════════════════════════════════════════════════════════════════════════
Mandar una foto por WhatsApp tiene tres puntos donde se rompe, y desde el
log del servidor los tres se parecen a «no pasó nada»:

    1. EL ARCHIVO      ¿existe en disco con ese nombre lógico?
    2. LA DIRECCIÓN    ¿hay una URL pública, y es https?
    3. LA DESCARGA     ¿responde esa URL con el archivo y el tipo correcto?

El tercero es el que nadie prueba, y es el que importa: los servidores de
Meta hacen un GET ANÓNIMO desde internet. Si el túnel está caído, si la URL
es la de ayer, o si el video sale como `application/octet-stream`, Meta
descarta el mensaje y devuelve un 400 sin explicar cuál de las tres cosas
falló.

Esto hace ese mismo GET. Si aquí sale verde, a Meta le va a funcionar.
"""

from __future__ import annotations

import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

from app.infra.consola import preparar_salida

# UTF-8 pase lo que pase: sin esto, redirigir la salida a un archivo (o
# leerla desde otro proceso) revienta en Windows al imprimir un ✔.
preparar_salida()


from app.conversacion.redactor import (
    ADJUNTOS,
    ADJUNTOS_DEL_HUECO,
)
from app.conversacion.salida import ruta_de_media
from app.domain.respuesta import Tipo
from app.infra.settings import get_settings

C, V, R, A, B, RST = (
    "\033[36m",
    "\033[32m",
    "\033[31m",
    "\033[33m",
    "\033[1m",
    "\033[0m",
)
OK, MAL, DUDA = f"{V}✔{RST}", f"{R}✘{RST}", f"{A}○{RST}"

#: Lo que Meta acepta. El límite de video es suyo, no nuestro.
TOPE_IMAGEN_MB = 5
TOPE_VIDEO_MB = 16
TIPOS = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
    ".mp4": "video/mp4",
}


def _todos_los_nombres() -> list[tuple[str, str]]:
    """(nombre lógico, dónde se usa), sin repetir."""
    vistos: dict[str, str] = {}
    for accion, grupo in ADJUNTOS.items():
        for tipo, nombre, _ in grupo:
            vistos.setdefault(nombre, f"{tipo.value.lower()} · {accion.value}")
    for hueco, grupo in ADJUNTOS_DEL_HUECO.items():
        for tipo, nombre, _ in grupo:
            vistos.setdefault(nombre, f"{tipo.value.lower()} · pregunta {hueco}")
    return sorted(vistos.items())


def main() -> int:
    s = get_settings()
    nombres = _todos_los_nombres()
    videos = {n for grupo in ADJUNTOS.values() for t, n, _ in grupo if t is Tipo.VIDEO}

    print(f"\n{C}{'=' * 74}")
    print("  MEDIOS · lo que el bot puede mandar")
    print(f"{'=' * 74}{RST}")

    # -- 1. los archivos ---------------------------------------------------
    print(f"\n{B}[1] Los archivos{RST}")
    faltan = []
    pesados = []
    for nombre, donde in nombres:
        ruta = ruta_de_media(s.carpetas_de_media, nombre)
        if ruta is None:
            faltan.append(nombre)
            print(f"  {MAL} {nombre:26} NO ESTÁ EN DISCO  ({donde})")
            continue
        mb = ruta.stat().st_size / 1024 / 1024
        tope = TOPE_VIDEO_MB if nombre in videos else TOPE_IMAGEN_MB
        aviso = ""
        if mb > tope:
            pesados.append(nombre)
            aviso = f"  {R}pesa más de {tope} MB: Meta lo rechaza{RST}"
        print(f"  {OK} {nombre:26} {mb:5.2f} MB  {ruta.suffix:5} ({donde}){aviso}")

    # -- 2. la dirección ---------------------------------------------------
    print(f"\n{B}[2] La dirección pública{RST}")
    if not s.url_publica:
        print(f"  {MAL} No hay URL pública: el bot NO manda fotos ni videos.")
        print(f"      {A}→{RST} ngrok http 127.0.0.1:8000")
        print(f"      {A}→{RST} y después:  vb panel   (la escribe sola en el .env)")
        print(f"      {A}→{RST} reinicia el servidor\n")
        return 1
    if not s.url_publica.startswith("https://"):
        print(f"  {MAL} {s.url_publica} no es https. Meta solo baja de https.\n")
        return 1
    print(f"  {OK} {s.url_publica}")

    # -- 3. la descarga, igual que la hace Meta ----------------------------
    print(f"\n{B}[3] La descarga (el mismo GET que hace Meta){RST}")
    try:
        import httpx
    except ImportError:  # pragma: no cover
        print(f"  {DUDA} sin httpx no se puede probar")
        return 1

    malas = 0
    for nombre, _ in nombres:
        url = f"{s.url_publica}/media/{nombre}"
        try:
            r = httpx.get(url, timeout=20, follow_redirects=True)
        except Exception as exc:
            malas += 1
            print(f"  {MAL} {nombre:26} no responde ({type(exc).__name__})")
            continue
        tipo = r.headers.get("content-type", "").split(";")[0]
        ruta = ruta_de_media(s.carpetas_de_media, nombre)
        esperado = TIPOS.get(ruta.suffix.lower() if ruta else "", "")
        if r.status_code != 200:
            malas += 1
            print(f"  {MAL} {nombre:26} HTTP {r.status_code}")
        elif esperado and tipo != esperado:
            malas += 1
            print(f"  {MAL} {nombre:26} sale como {tipo}, debería ser {esperado}")
        else:
            print(f"  {OK} {nombre:26} {len(r.content) / 1024:6.0f} KB  {tipo}")

    # -- veredicto ---------------------------------------------------------
    print(f"\n{C}{'=' * 74}")
    print("  VEREDICTO")
    print(f"{'=' * 74}{RST}")
    if faltan:
        print(f"  {R}Faltan {len(faltan)} archivo(s):{RST} {', '.join(faltan)}")
        print("  Ponlos en data/imagenes/ con ese nombre exacto.")
    if pesados:
        print(f"  {R}Demasiado pesados:{RST} {', '.join(pesados)}")
    if malas:
        print(f"  {R}{malas} no se pueden descargar desde internet.{RST}")
        print("  Si el túnel se reinició, la URL cambió:  vb panel  y reinicia.")
    if not (faltan or pesados or malas):
        print(f"  {V}Todo se puede mandar.{RST} Si aun así no llegan, mira el log")
        print("  del servidor: el problema ya no es el archivo ni la dirección.")
    print()
    return 1 if (faltan or pesados or malas) else 0


if __name__ == "__main__":
    raise SystemExit(main())
