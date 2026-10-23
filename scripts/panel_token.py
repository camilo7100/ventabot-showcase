#!/usr/bin/env python3
"""Genera el token del panel y dice exactamente qué hacer con él.

    vb panel

El panel del taller viene APAGADO. Este comando lo enciende: genera una clave
aleatoria, la escribe en el .env y te arma el enlace con la URL de ngrok que
tengas corriendo en ese momento.

Existe para que nadie se invente su propia clave. Una contraseña pensada por
una persona ("lia2026") se adivina; esta son 24 bytes de aleatoriedad real.
"""

from __future__ import annotations

import argparse
import re
import secrets
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

import httpx

from app.infra.consola import preparar_salida
from app.infra.settings import get_settings

_C = preparar_salida()
V, R, A, G, C, RST = (_C.ok, _C.error, _C.aviso, _C.tenue, _C.titulo, _C.fin)
OK, NO = f"{V}✔{RST}", f"{R}✘{RST}"

NGROK_API = "http://127.0.0.1:4040/api/tunnels"

#: Se prueba contra 127.0.0.1 y NO contra "localhost" a propósito.
#:
#: En Windows, "localhost" resuelve primero a ::1 (IPv6), y uvicorn arranca
#: escuchando en 127.0.0.1 (IPv4). Si algo se conecta por nombre, puede
#: fallar con «target machine actively refused it» aunque el servidor esté
#: perfectamente vivo. Es la misma trampa que hace fallar a ngrok cuando se
#: lanza con `ngrok http 8000` en vez de `ngrok http 127.0.0.1:8000`.
LOCAL = "http://127.0.0.1:8000"


def url_publica() -> str | None:
    try:
        datos = httpx.get(NGROK_API, timeout=3).json()
    except Exception:
        return None
    for tunel in datos.get("tunnels", []):
        if tunel.get("public_url", "").startswith("https://"):
            return tunel["public_url"].rstrip("/")
    return None


def servidor_vivo() -> bool:
    try:
        return httpx.get(f"{LOCAL}/health", timeout=3).status_code == 200
    except Exception:
        return False


def panel_responde(token: str) -> int | None:
    """Prueba el enlace de verdad, en vez de solo imprimirlo.

    Un comando que te da una URL y no la comprueba te está pasando el trabajo
    de depurar a ti. Aquí se abre el panel antes de dártelo.
    """
    try:
        return httpx.get(f"{LOCAL}/panel", params={"token": token}, timeout=5).status_code
    except Exception:
        return None


def fijar_en_env(clave: str, valor: str) -> Path:
    """Reemplaza una clave del .env, o la agrega si no estaba.

    Se edita LÍNEA A LÍNEA y no se reescribe el archivo entero: el .env tiene
    comentarios y el token de Meta, y regenerarlo perdería ambos.
    """
    ruta = RAIZ / ".env"
    if not ruta.exists():
        raise FileNotFoundError(ruta)
    lineas = ruta.read_text(encoding="utf-8").splitlines()
    patron = re.compile(rf"^\s*{re.escape(clave)}\s*=")
    for i, linea in enumerate(lineas):
        if patron.match(linea):
            lineas[i] = f"{clave}={valor}"
            break
    else:
        lineas += ["", "# Generado por: vb panel", f"{clave}={valor}"]
    ruta.write_text("\n".join(lineas) + "\n", encoding="utf-8")
    return ruta


def main() -> int:
    ap = argparse.ArgumentParser(description="Enciende el panel del taller")
    ap.add_argument(
        "--nuevo",
        action="store_true",
        help="genera un token NUEVO aunque ya haya uno (invalida el enlace viejo)",
    )
    args = ap.parse_args()

    print(f"\n{C}{'=' * 72}\n  PANEL DEL TALLER\n{'=' * 72}{RST}")

    s = get_settings()
    actual = s.panel_token

    if actual and not args.nuevo:
        token = actual
        print(f"\n  {OK} Ya estaba encendido. Uso el token que tienes.")
        print(f"      {G}(para cambiarlo: vb panel --nuevo){RST}")
    else:
        token = secrets.token_urlsafe(24)
        try:
            ruta = fijar_en_env("PANEL_TOKEN", token)
        except FileNotFoundError:
            print(f"\n  {NO} No encuentro tu archivo .env")
            print(f"      {A}→{RST} Créalo con:  vb init-env\n")
            return 1
        print(f"\n  {OK} Token nuevo escrito en {ruta.name}")
        if actual:
            print(f"  {A}⚠ El enlace anterior dejó de funcionar.{RST}")

    # ---- ¿está el servidor arriba? ----
    print(f"\n{G}[1]{RST} El servidor")
    if not servidor_vivo():
        print(f"  {NO} No hay nada escuchando en {LOCAL}")
        print(f"\n      {A}→{RST} Abre OTRA ventana de la terminal y corre:")
        print(f"            {G}conda activate ventabot{RST}")
        print(f"            {G}cd {RAIZ}{RST}")
        print(f"            {G}vb server{RST}")
        print("\n      Déjala abierta. Si la cierras, el bot se apaga y ngrok")
        print("      responde «502 Bad Gateway» a todo.")
        print(f"\n      Cuando esté arriba, vuelve a correr:  {G}vb panel{RST}\n")
        return 1
    print(f"  {OK} responde en {LOCAL}")

    # ---- ¿el panel abre CON ESTE token? ----
    print(f"\n{G}[2]{RST} El panel con tu token")
    codigo = panel_responde(token)
    if codigo == 200:
        print(f"  {OK} abre correctamente")
    elif codigo == 404:
        print(f"  {NO} el servidor todavía tiene el token VIEJO (o ninguno).")
        print(f"      {A}→{RST} El .env solo se lee al arrancar. Cierra el")
        print("          servidor con Ctrl+C, ábrelo otra vez con «vb server»,")
        print("          y vuelve a correr «vb panel».\n")
        return 1
    else:
        print(f"  {A}○{RST} respondió {codigo}: algo raro, míralo en la ventana")
        print("      del servidor.")

    print(f"\n{G}[3]{RST} Tu enlace")
    publica = url_publica()

    # URL_PUBLICA es de donde Meta baja las fotos del anillo. Cambia cada vez
    # que se reinicia ngrok gratuito, así que se reescribe aquí en vez de
    # esperar a que alguien se acuerde: una URL vieja significa que el cobro
    # sale sin fotos, en silencio.
    if publica and publica != s.url_publica:
        # Se escriben LAS DOS. `PUBLIC_URL` es la que usa todo lo demás y
        # `URL_PUBLICA` la que miraban las fotos: tener dos nombres para lo
        # mismo costó una conversación entera de pruebas sin una sola foto.
        fijar_en_env("PUBLIC_URL", publica)
        fijar_en_env("URL_PUBLICA", publica)
        print(f"  {OK} URL pública actualizada en el .env (fotos y videos)")
        print(f"      {A}→{RST} reinicia el servidor para que la lea")
    if publica:
        print(f"\n      {V}{publica}/panel?token={token}{RST}\n")
        print("      Ese enlace es el que le mandas a Lía. En el celular,")
        print("      «Añadir a pantalla de inicio» y le queda como una app.")
    else:
        print(f"\n      {V}{LOCAL}/panel?token={token}{RST}\n")
        print(f"      {A}(ngrok no está corriendo: por ahora solo desde este PC.{RST}")
        print(f"      {A} Levántalo y vuelve a correr «vb panel» para el enlace){RST}")
        print()
        print(f"      {G}Consejo: arráncalo como  ngrok http 127.0.0.1:8000{RST}")
        print("      y no como «ngrok http 8000». En Windows, «localhost»")
        print("      resuelve primero a IPv6 (::1) y uvicorn escucha en IPv4,")
        print("      así que a veces falla con «connection refused» aunque el")
        print("      servidor esté vivo.")

    print(f"\n{A}  OJO:{RST} ese enlace es una contraseña. Quien lo tenga ve todos")
    print("  los pedidos, con nombres y teléfonos. No lo publiques.\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
