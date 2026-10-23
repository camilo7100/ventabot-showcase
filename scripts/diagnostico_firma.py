#!/usr/bin/env python3
"""Diagnostica por qué la firma de un webhook de Meta no cuadra.

    vb server          <- deja que Meta mande un POST y falle
    vb firma           <- esto analiza el fallo

QUÉ HACE
========
Coge el webhook que el servidor guardó al rechazarlo (`data/webhook_fallido.json`)
y prueba, una por una, TODAS las hipótesis razonables de por qué el HMAC no
coincide. Al final te dice cuál encajó — o que ninguna, que también es una
respuesta útil porque descarta el código y señala al secreto.

Depurar una firma a ojo es imposible: o coincide o no, y el error es el mismo
sea cual sea la causa. Esta herramienta convierte «adivina» en «mide».

SEGURIDAD
=========
Nunca imprime el secreto. Muestra una HUELLA (los primeros 12 caracteres del
SHA-256 del secreto), que sirve para comparar dos secretos sin revelar ninguno.
Puedes pegarme la huella sin riesgo; el secreto NO.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import json
import sys
import unicodedata
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

from datetime import UTC

from app.infra.consola import preparar_salida
from app.infra.settings import get_settings

_C = preparar_salida()
V, R, A, G, C, RST = (_C.ok, _C.error, _C.aviso, _C.tenue, _C.titulo, _C.fin)
OK, NO = f"{V}✔{RST}", f"{R}✘{RST}"


def huella(secreto: str) -> str:
    """Identifica un secreto sin revelarlo. Dos huellas iguales = mismo secreto."""
    return hashlib.sha256(secreto.encode()).hexdigest()[:12]


def describir(secreto: str) -> list[str]:
    """Todo lo que se puede decir de un secreto sin enseñarlo."""
    notas = [
        f"longitud: {len(secreto)} caracteres",
        f"huella:   {huella(secreto)}",
    ]
    if len(secreto) != 32:
        notas.append(f"{A}⚠ un App Secret de Meta tiene EXACTAMENTE 32 caracteres{RST}")
    if secreto != secreto.strip():
        notas.append(
            f"{A}⚠ tiene espacios o saltos de línea al principio o al final{RST}"
        )
    if not all(ch in "0123456789abcdefABCDEF" for ch in secreto.strip()):
        raros = {ch for ch in secreto.strip() if ch not in "0123456789abcdefABCDEF"}
        notas.append(
            f"{A}⚠ contiene caracteres que no son hexadecimales: {sorted(raros)}{RST}"
        )
    invisibles = [
        f"U+{ord(ch):04X} ({unicodedata.name(ch, '?')})"
        for ch in secreto
        if unicodedata.category(ch) in {"Cf", "Zs"} or ord(ch) in {0xFEFF}
    ]
    if invisibles:
        notas.append(f"{R}⚠ CARACTERES INVISIBLES: {invisibles}{RST}")
    return notas


# ---------------------------------------------------------------------------
# Hipótesis. Cada una es una forma en que la firma PODRÍA calcularse.
# ---------------------------------------------------------------------------


def hipotesis(secreto: str, cuerpo: bytes) -> list[tuple[str, str, str]]:
    """(nombre, firma calculada, qué significaría si esta es la que encaja)"""
    limpio = secreto.strip()
    sin_bom = limpio.lstrip("﻿")
    out = [
        (
            "secreto tal cual + SHA-256 (lo que Meta especifica)",
            "sha256=" + hmac.new(secreto.encode(), cuerpo, hashlib.sha256).hexdigest(),
            "todo correcto",
        ),
        (
            "secreto sin espacios alrededor",
            "sha256=" + hmac.new(limpio.encode(), cuerpo, hashlib.sha256).hexdigest(),
            "tu .env tiene un espacio o salto de línea de más",
        ),
        (
            "secreto sin marca BOM",
            "sha256=" + hmac.new(sin_bom.encode(), cuerpo, hashlib.sha256).hexdigest(),
            "el .env se guardó en UTF-8 con BOM (Bloc de notas lo hace)",
        ),
        (
            "secreto interpretado como bytes hex",
            "sha256="
            + hmac.new(
                bytes.fromhex(limpio) if _es_hex(limpio) else b"", cuerpo, hashlib.sha256
            ).hexdigest(),
            "habría que decodificar el secreto antes de firmar (no es el caso de Meta)",
        ),
        (
            "SHA-1 en vez de SHA-256",
            "sha1=" + hmac.new(limpio.encode(), cuerpo, hashlib.sha1).hexdigest(),
            "estás comparando contra la cabecera antigua X-Hub-Signature",
        ),
    ]
    # Hipótesis sobre el CUERPO. Si alguna de estas encaja, el secreto era
    # correcto todo el tiempo y lo que pasa es que algo en el camino
    # (un proxy, un túnel, el servidor) alteró los bytes antes de que
    # llegaran al verificador.
    variantes = [
        (b"\n" + cuerpo, "algo AÑADIÓ un salto de línea al principio"),
        (cuerpo + b"\n", "algo AÑADIÓ un salto de línea al final"),
        (cuerpo.rstrip(b"\n\r"), "algo QUITÓ el salto de línea del final"),
        (
            cuerpo.replace(b", ", b",").replace(b": ", b":"),
            "algo re-serializó el JSON quitando espacios",
        ),
    ]
    for variante, significado in variantes:
        if variante == cuerpo:
            continue
        out.append(
            (
                f"cuerpo distinto: {significado}",
                "sha256="
                + hmac.new(limpio.encode(), variante, hashlib.sha256).hexdigest(),
                significado,
            )
        )
    return out


#: Marcas del payload de EJEMPLO que manda el botón «Probar» del panel de Meta.
#: Son valores fijos de su documentación, idénticos para todo el mundo.
MARCAS_DE_EJEMPLO = (
    b'"id":"0"',
    b'"display_phone_number":"16505551111"',
    b'"wa_id":"16315551181"',
    b'"body":"this is a text message"',
    b'"timestamp":"1504902988"',
)


def es_payload_de_ejemplo(cuerpo: bytes) -> list[str]:
    """Devuelve las marcas encontradas. Si hay dos o más, es el botón «Probar».

    Distinguirlo importa muchísimo: ese payload NO es un mensaje real y su
    firma no prueba nada de tu integración. Sin este aviso, uno se pasa horas
    persiguiendo un problema de criptografía que no existe.
    """
    return [m.decode() for m in MARCAS_DE_EJEMPLO if m in cuerpo]


def _es_hex(s: str) -> bool:
    try:
        bytes.fromhex(s)
        return len(s) % 2 == 0
    except ValueError:
        return False


# ---------------------------------------------------------------------------


def main() -> int:
    ap = argparse.ArgumentParser(description="Diagnostica firmas de webhook de Meta")
    ap.add_argument(
        "--captura",
        default=None,
        help="ruta del webhook capturado (por defecto data/webhook_fallido.json)",
    )
    ap.add_argument(
        "--huella-de",
        metavar="SECRETO",
        default=None,
        help="calcula la huella de un secreto que pegues, para compararlo "
        "con el del .env sin revelar ninguno de los dos",
    )
    args = ap.parse_args()

    s = get_settings()

    if args.huella_de:
        print(f"\n  huella del secreto que pegaste : {huella(args.huella_de)}")
        print(f"  huella del secreto de tu .env  : {huella(s.app_secret_efectivo)}")
        iguales = huella(args.huella_de) == huella(s.app_secret_efectivo)
        print(
            f"\n  {OK if iguales else NO} "
            f"{'Son el MISMO secreto' if iguales else 'Son secretos DISTINTOS'}\n"
        )
        return 0 if iguales else 1

    captura = (
        Path(args.captura)
        if args.captura
        else s.sqlite_path.parent / "webhook_fallido.json"
    )

    print(f"\n{C}{'=' * 72}\n  DIAGNÓSTICO DE FIRMA DEL WEBHOOK\n{'=' * 72}{RST}")

    # ---- 1. el secreto ----
    print(f"\n{G}[1]{RST} El secreto que está usando el servidor")
    secreto = s.app_secret_efectivo
    if s.usando_secreto_de_desarrollo:
        print(f"  {NO} META_APP_SECRET está VACÍO: se está usando el de desarrollo.")
        print(
            f"      {A}→{RST} Meta nunca va a coincidir con ese. Rellena META_APP_SECRET."
        )
        return 1
    for nota in describir(secreto):
        print(f"      {nota}")

    # ---- 2. la captura ----
    print(f"\n{G}[2]{RST} El webhook que Meta mandó")
    if not captura.exists():
        print(f"  {NO} No encuentro {captura}")
        print(f"\n  {A}Para capturarlo:{RST}")
        print("      1. Deja el servidor corriendo (vb server)")
        print("      2. Haz que Meta mande un POST (escríbele al número, o usa")
        print("         el botón «Probar» del webhook en el panel de Meta)")
        print("      3. Vuelve a correr este comando")
        return 1

    datos = json.loads(captura.read_text(encoding="utf-8"))
    cuerpo = base64.b64decode(datos["cuerpo_base64"])
    cabeceras = {k.lower(): v for k, v in datos["cabeceras"].items()}
    recibida = cabeceras.get("x-hub-signature-256", "")

    # Analizar una captura VIEJA lleva a conclusiones falsas: te dice que
    # nada encaja cuando en realidad estás mirando el intento de hace una hora,
    # con un secreto que ya cambiaste. Pasó durante las pruebas de esta misma
    # herramienta.
    from datetime import datetime

    momento = datetime.fromisoformat(datos["capturado_en"])
    minutos = (datetime.now(UTC) - momento).total_seconds() / 60
    edad = f"hace {minutos:.0f} min" if minutos >= 1 else "hace segundos"
    print(f"      capturado: {datos['capturado_en']}  ({edad})")
    if minutos > 10:
        print(f"  {A}⚠ ESTA CAPTURA ES VIEJA.{RST} Si cambiaste el secreto desde")
        print("      entonces, el diagnóstico te va a mentir. Borra el archivo,")
        print("      reinicia el servidor y provoca un POST nuevo de Meta:")
        print(f"      {G}del data\\webhook_fallido.json{RST}")
    print(f"      cuerpo:    {len(cuerpo)} bytes")

    # El servidor lee el .env UNA vez, al arrancar. Si lo editaste después y no
    # reiniciaste, el .env está bien y el servidor sigue firmando con el valor
    # viejo. Por fuera se ve idéntico a "el secreto está mal", y se persigue el
    # problema equivocado durante horas.
    huella_servidor = datos.get("huella_secreto_servidor")
    if huella_servidor and huella_servidor != huella(secreto):
        print(f"\n  {R}⚠ EL SERVIDOR ESTÁ USANDO OTRO SECRETO.{RST}")
        print(f"      el que tiene tu .env AHORA  : {huella(secreto)}")
        print(f"      el que usó el servidor      : {huella_servidor}")
        print(f"      {A}→{RST} Cambiaste el .env y no reiniciaste el servidor.")
        print("          Ciérralo con Ctrl+C, vuelve a abrirlo con  vb server,")
        print("          y manda otro «Hola». No toques nada más.\n")
        return 1
    if huella_servidor:
        print("      el servidor usó el MISMO secreto que tiene tu .env ahora")
    print(
        f"      firma que mandó Meta: {recibida[:24]}…"
        if recibida
        else f"  {NO} Meta NO mandó la cabecera X-Hub-Signature-256"
    )
    if not recibida:
        print(f"      cabeceras recibidas: {list(cabeceras)}")
        print(f"\n  {A}→{RST} Si no hay firma, no es Meta quien llama, o hay un")
        print("      proxy en medio quitando cabeceras.")
        return 1

    marcas = es_payload_de_ejemplo(cuerpo)
    if len(marcas) >= 2:
        print(f"\n  {A}{'─' * 68}{RST}")
        print(f"  {A}ESTO NO ES UN MENSAJE REAL.{RST}")
        print(f"  {A}{'─' * 68}{RST}")
        print("  Es el payload de EJEMPLO del botón «Probar» del panel de Meta.")
        print("  Lo delatan valores fijos de su documentación:")
        for m in marcas:
            print(f"      {G}{m}{RST}")
        print()
        print("  Ese ejemplo no sale de tu cuenta ni de tu número, así que su")
        print("  firma no dice nada sobre si tu integración funciona.")
        print()
        print(f"  {V}LA PRUEBA DE VERDAD:{RST} coge tu celular y escríbele por")
        print("  WhatsApp al número de prueba de Meta. Un mensaje real sí viene")
        print("  firmado con el secreto de tu app.")
        print(f"  {A}{'─' * 68}{RST}")

    # Pista sobre de qué cuenta viene, útil para comparar en el panel de Meta.
    try:
        payload = json.loads(cuerpo)
        waba = payload.get("entry", [{}])[0].get("id", "?")
        print(f"      viene de la cuenta de WhatsApp (WABA id): {waba}")
    except Exception:
        pass

    # ---- 3. las hipótesis ----
    print(f"\n{G}[3]{RST} Probando cómo se pudo calcular esa firma")
    ganadora = None
    for nombre, calculada, significado in hipotesis(secreto, cuerpo):
        coincide = hmac.compare_digest(calculada, recibida)
        print(f"  {OK if coincide else NO} {nombre}")
        # Se queda con la PRIMERA que encaje, no con la última. Cuando el
        # secreto está limpio, varias hipótesis son equivalentes y todas dan
        # ✔; la primera de la lista es la canónica (lo que Meta especifica) y
        # es la que hay que reportar. Quedarse con la última hacía que la
        # herramienta dijera "tienes un BOM" cuando en realidad todo estaba
        # bien — un diagnóstico que inventa un problema inexistente.
        if coincide and ganadora is None:
            ganadora = (nombre, significado)

    # ---- 4. veredicto ----
    print(f"\n{C}{'=' * 72}\n  VEREDICTO\n{'=' * 72}{RST}")
    if ganadora and ganadora[1] == "todo correcto":
        print(f"  {V}La firma SÍ cuadra con este secreto y este cuerpo.{RST}")
        print("  Si el servidor la rechazó igual, el secreto cambió entre medias:")
        print("  reinicia el servidor para que recargue el .env.\n")
        return 0
    if ganadora:
        print(f"  {A}Encaja con: {ganadora[0]}{RST}")
        print(f"  Significa que: {ganadora[1]}\n")
        return 1

    if len(es_payload_de_ejemplo(cuerpo)) >= 2:
        print(f"  {A}Ninguna hipótesis encaja — pero estabas analizando el payload{RST}")
        print(f"  {A}de EJEMPLO del botón «Probar», no un mensaje real.{RST}")
        print("""
  No saques conclusiones de esto. Antes de tocar nada:

    1. Comprueba que en Meta, en la sección Webhooks, el campo `messages`
       tenga la casilla MARCADA (botón «Administrar»). Si no lo está, Meta
       acepta tu URL y no te manda nada nunca.

    2. Comprueba que tu celular esté en la lista de destinatarios de prueba
       (WhatsApp -> Configuración de la API), verificado con su código.

    3. Escríbele por WhatsApp al número de prueba desde tu celular.

    4. Vuelve a correr este diagnóstico. Si el mensaje real SÍ pasa, no hay
       nada que arreglar: el botón «Probar» simplemente no es una prueba.
""")
        return 1

    print(f"  {R}Ninguna hipótesis encaja.{RST}")
    print("""
  Eso DESCARTA el código: el cálculo es el correcto y el cuerpo llegó intacto.
  Lo que queda es que el secreto no es el de la aplicación que está mandando
  el webhook. Las tres causas, por frecuencia:

    1. El secreto es de OTRA app de Meta. Si creaste más de una, es casi
       seguro esto. Comprueba el identificador de la app en la URL del panel
       cuando copiaste el secreto, y compáralo con el de la app donde
       configuraste el webhook: tienen que ser el MISMO número.

    2. Copiaste el App ID en vez del App Secret. El ID son ~16 dígitos; el
       secreto son 32 caracteres hexadecimales.

    3. Regeneraste el secreto en el panel después de pegarlo en el .env.

  NO LO ADIVINES: MÍDELO.

    vb app

  Le pregunta a Meta de qué aplicación es tu token, si tu secreto pertenece a
  esa misma aplicación, y qué aplicación está suscrita a tu cuenta de WhatsApp
  (que es la que firma). Si algo no cuadra, te da la URL exacta de la página
  donde está el secreto que sí sirve.

  Y si quieres probar un secreto ANTES de tocar el .env:

    vb app --secreto PEGA_AQUI_EL_SECRETO
""")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
