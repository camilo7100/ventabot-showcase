#!/usr/bin/env python3
"""Levanta Chatwoot en el PC y comprueba que el bot le puede escribir.

    vb chatwoot            <- dice en qué punto estás y qué falta
    vb chatwoot --arrancar <- lo levanta (la primera vez tarda: ~2 GB)
    vb chatwoot --conectar <- después de crear tu usuario: conecta todo solo

════════════════════════════════════════════════════════════════════════════
QUÉ ES CHATWOOT AQUÍ
════════════════════════════════════════════════════════════════════════════
La bandeja para ATENDER, desde el PC o la app del celular, como WhatsApp
Business: ves todas las conversaciones con quién es cada clienta, qué pidió y
qué falta. El bot atiende solo, y en cuanto Lía empieza a escribir en una
conversación el bot se calla ahí; al marcarla «Resuelta», vuelve el bot.
Las fotos pasan en los dos sentidos.

Si Chatwoot no está, el bot funciona exactamente igual.
"""

from __future__ import annotations

import argparse
import secrets
import shutil
import subprocess
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

from app.infra.consola import preparar_salida

# UTF-8 pase lo que pase: sin esto, redirigir la salida a un archivo (o
# leerla desde otro proceso) revienta en Windows al imprimir un ✔.
preparar_salida()


from app.infra.settings import get_settings

CARPETA = RAIZ / "docker" / "chatwoot"
C, V, R, A, B, RST = (
    "\033[36m",
    "\033[32m",
    "\033[31m",
    "\033[33m",
    "\033[1m",
    "\033[0m",
)
OK, MAL, PASO = f"{V}✔{RST}", f"{R}✘{RST}", f"{A}○{RST}"


def _docker() -> str | None:
    return shutil.which("docker")


def _docker_vivo() -> bool:
    try:
        return (
            subprocess.run(["docker", "info"], capture_output=True, timeout=25).returncode
            == 0
        )
    except Exception:
        return False


def _preparar_env() -> Path:
    """Crea el .env de Chatwoot con una clave nueva si no existe."""
    destino = CARPETA / ".env"
    if destino.is_file():
        return destino
    plantilla = (CARPETA / ".env.example").read_text(encoding="utf-8")
    plantilla = plantilla.replace("CAMBIAME_POR_UNA_CLAVE_LARGA", secrets.token_hex(64))
    destino.write_text(plantilla, encoding="utf-8")
    return destino


def _levantar() -> int:
    print(f"\n{B}Preparando la base de datos (la primera vez tarda){RST}")
    subprocess.run(
        [
            "docker",
            "compose",
            "run",
            "--rm",
            "rails",
            "bundle",
            "exec",
            "rails",
            "db:chatwoot_prepare",
        ],
        cwd=CARPETA,
        check=False,
    )
    print(f"\n{B}Levantando Chatwoot{RST}")
    return subprocess.run(
        ["docker", "compose", "up", "-d"], cwd=CARPETA, check=False
    ).returncode


def _probar_api(s) -> bool:
    import httpx

    try:
        r = httpx.get(
            f"{s.chatwoot_url.rstrip('/')}/api/v1/accounts/"
            f"{s.chatwoot_account_id}/inboxes",
            headers={"api_access_token": s.chatwoot_token},
            timeout=10,
        )
    except Exception as exc:
        print(f"  {MAL} no responde ({type(exc).__name__})")
        return False
    if r.status_code != 200:
        print(f"  {MAL} contestó {r.status_code}: revisa CHATWOOT_TOKEN")
        return False
    buzones = r.json().get("payload", [])
    print(f"  {OK} el token sirve · {len(buzones)} buzón(es)")
    for b in buzones:
        marca = "  ← el configurado" if str(b["id"]) == str(s.chatwoot_inbox_id) else ""
        print(f"      #{b['id']}  {b['name']}  ({b.get('channel_type', '')}){marca}")
    if not any(str(b["id"]) == str(s.chatwoot_inbox_id) for b in buzones):
        print(f"\n  {MAL} CHATWOOT_INBOX_ID={s.chatwoot_inbox_id} no existe.")
        print("      Pon arriba el número del buzón de tipo API.")
        return False
    return True


#: Lo que Chatwoot le avisa al bot: un mensaje de Lía (sale a la clienta), que
#: se asignó la conversación (el bot se calla) y que la resolvió (vuelve el
#: bot). «escribiendo…» NO se puede suscribir en esta versión: Chatwoot la
#: rechaza con 422. Ver `/webhook/chatwoot` en app/api/main.py.
EVENTOS_DEL_WEBHOOK = [
    "message_created",
    "conversation_updated",
    "conversation_status_changed",
]
NOMBRE_DEL_BUZON = "WhatsApp Lía"

#: Quién firma lo que escribe el bot. Sin él, todo sale a nombre de Lía y ni
#: ella ni el webhook saben qué escribió cada quien.
NOMBRE_DEL_BOT = "VentaBot"

#: Lo que el bot anota en la ficha de cada conversación (ver
#: `Container._ficha`). Definirlo le da nombre bonito en la barra derecha.
ATRIBUTOS = {
    "pedido": "Pedido",
    "huellitas": "Huellitas",
    "colores": "Colores",
    "grabado": "Grabado",
    "talla": "Talla",
    "envio": "Envío",
    "entrega": "Cómo se entrega",
    "total": "Total",
    "abonado": "Abonado",
    "saldo_pendiente": "Saldo por pagar",
    "falta": "Qué falta",
    "por_confirmar": "Por confirmar",
    "fecha_limite": "Fecha límite",
    # Los datos de la guía, uno por uno: Lía los puede corregir aquí y se
    # copian solos al pedido y al panel (29/09).
    "destinatario": "A nombre de (guía)",
    "ciudad": "Ciudad",
    "direccion": "Dirección",
    "barrio": "Barrio",
    "cedula": "Cédula",
    "celular": "Celular (guía)",
    "transportadora": "Transportadora",
    "guia": "Número de guía",
}

#: Carpetas de la barra lateral: lo que Lía abre para trabajar.
CARPETAS = (
    ("🙋 Me necesitan", ["necesita-persona", "datos-incompletos"]),
    ("💰 Pagos por verificar", ["pago-por-verificar"]),
    ("📍 Falta la dirección", ["falta-direccion"]),
    ("🔨 En el taller", ["05-en-taller"]),
    ("💍 Listos: cobrar saldo", ["06-listo-cobrar-saldo"]),
    ("📦 Por despachar", ["08-por-despachar"]),
    ("⏳ Esperando abono", ["03-esperando-abono"]),
)


def _respuestas_rapidas() -> list[tuple[str, str]]:
    """Las que Lía escribe con «/» en Chatwoot. Salen de las mismas verdades
    que usa el bot (cuentas, tiempos), para que nunca digan otra cosa."""
    from app.domain.faq import UBICACION, datos_para_transferir

    return [
        ("cuentas", "Puedes transferir a:\n\n" + datos_para_transferir()),
        (
            "abono",
            "Para iniciar la fabricación abonas $60.000 y el saldo lo pagas cuando "
            "veas las fotos de tu anillo terminado 💓",
        ),
        (
            "tiempos",
            "Tu anillo se fabrica en 10 a 15 días calendario 💍 Apenas esté listo te "
            "mando las fotos de cómo quedó ✨",
        ),
        (
            "envio",
            "Enviamos por Coordinadora a todo el país 🚚 El envío se paga al recibir. "
            "Si te queda cerca, lo puedes recoger sin costo en el conjunto Caminos de "
            "Ejemplo (Floridablanca) 🥰 En Bucaramanga hay domicilio; el valor "
            "depende del domicilio de ese día.",
        ),
        # La misma que dice el bot (09/10): sin dirección, torre ni apartamento.
        ("ubicacion", UBICACION),
        (
            "talla",
            "Con un anillo que conserve su forma redonda y una regla, lo mides en toda "
            "la mitad del anillo 📏 Me regalas una foto y te confirmo la talla :)",
        ),
        (
            "garantia",
            "Es plata Ley 925 contramarcada ✨ no se pela ni se oxida, y tiene 6 meses "
            "de garantía por defectos de fabricación 💍",
        ),
        (
            # Los mismos campos, en el mismo orden, que pide el bot con las
            # fotos del anillo terminado. Si dicen cosas distintas, la clienta
            # manda unos datos y falta otro.
            "datos",
            "Para poder hacer el envío, por favor regálanos los siguientes "
            "datos:\n\n"
            "📍 Ciudad:\n"
            "🙋‍♀️ Nombre completo:\n"
            "🪪 Cédula:\n"
            "📱 Celular:\n"
            "🏡 Dirección completa con barrio y nomenclatura:",
        ),
        ("gracias", "¡Mil gracias por tu confianza! ❣️ Te va a encantar ✨"),
    ]


def _token_del_administrador() -> tuple[str, int, int] | None:
    """El token, el usuario y la cuenta del primer administrador de ESTE Chatwoot.

    Solo sirve para la instalación local en Docker: se lee de su propia base
    para que Camilo no tenga que copiar el token a mano. Nunca se imprime.
    """
    consulta = (
        "select t.token, u.id, au.account_id from access_tokens t "
        "join users u on t.owner_type = 'User' and t.owner_id = u.id "
        "join account_users au on au.user_id = u.id and au.role = 1 "
        "order by u.id limit 1"
    )
    try:
        r = subprocess.run(
            [
                "docker",
                "compose",
                "exec",
                "-T",
                "postgres",
                "psql",
                "-U",
                "chatwoot",
                "-d",
                "chatwoot",
                "-tAF",
                "|",
                "-c",
                consulta,
            ],
            cwd=CARPETA,
            capture_output=True,
            text=True,
            timeout=60,
        )
    except Exception:
        return None
    linea = (r.stdout or "").strip().splitlines()
    if r.returncode != 0 or not linea or "|" not in linea[0]:
        return None
    token, usuario, cuenta = linea[0].split("|")
    return token.strip(), int(usuario), int(cuenta)


def _escribir_en_env(valores: dict[str, str]) -> None:
    import re

    ruta = RAIZ / ".env"
    texto = ruta.read_text(encoding="utf-8")
    for clave, valor in valores.items():
        if re.search(rf"^{clave}=", texto, re.M):
            texto = re.sub(rf"^{clave}=.*$", f"{clave}={valor}", texto, flags=re.M)
        else:
            texto = texto.rstrip("\n") + f"\n{clave}={valor}\n"
    ruta.write_text(texto, encoding="utf-8", newline="")


def _conectar(s) -> int:
    """Deja Chatwoot conectado al bot. Lo único previo: haber creado el usuario."""
    import httpx

    print(f"\n{B}[3] Conectando Chatwoot con el bot{RST}")
    admin = _token_del_administrador()
    if admin is None:
        print(f"  {MAL} todavía no hay un usuario administrador en Chatwoot.")
        print(f"      {A}→{RST} abre http://localhost:3000, crea tu usuario y vuelve a")
        print(f"        correr  {B}vb chatwoot --conectar{RST}\n")
        return 1
    token, usuario, cuenta = admin
    base = "http://localhost:3000"
    api = f"{base}/api/v1/accounts/{cuenta}"
    h = {"api_access_token": token}
    print(f"  {OK} usuario administrador encontrado (cuenta #{cuenta})")

    buzones = httpx.get(f"{api}/inboxes", headers=h, timeout=20).json().get("payload", [])
    buzon = next((b for b in buzones if b.get("name") == NOMBRE_DEL_BUZON), None)
    if buzon is None:
        buzon = httpx.post(
            f"{api}/inboxes",
            headers=h,
            json={
                "name": NOMBRE_DEL_BUZON,
                "channel": {"type": "api", "webhook_url": ""},
            },
            timeout=20,
        ).json()
        print(f"  {OK} buzón «{NOMBRE_DEL_BUZON}» creado (#{buzon['id']})")
    else:
        print(f"  {OK} buzón «{NOMBRE_DEL_BUZON}» ya existía (#{buzon['id']})")
    # Sin auto-asignación: asignar ES tomar la conversación (calla al bot), así
    # que Chatwoot no debe asignar solo cada clienta nueva.
    r = httpx.patch(
        f"{api}/inboxes/{buzon['id']}",
        headers=h,
        json={"enable_auto_assignment": False},
        timeout=20,
    )
    if r.status_code >= 300:
        print(f"  {MAL} no se pudo apagar la auto-asignación: {r.status_code}")
        print(f"      {r.text[:200]}")
        return 1
    print(f"  {OK} auto-asignación apagada (asignarte una charla = tomarla)")
    # Que las conversaciones le lleguen (y le notifiquen) a Lía.
    httpx.post(
        f"{api}/inbox_members",
        headers=h,
        json={"inbox_id": buzon["id"], "user_ids": [usuario]},
        timeout=20,
    )

    secreto = s.chatwoot_webhook_token
    if not secreto:
        secreto = secrets.token_urlsafe(24)
    url = f"http://host.docker.internal:8000/webhook/chatwoot?token={secreto}"
    avisos = httpx.get(f"{api}/webhooks", headers=h, timeout=20).json()
    existentes = (
        (avisos.get("payload") or {}).get("webhooks", [])
        if isinstance(avisos.get("payload"), dict)
        else avisos.get("payload", [])
    )
    nuestro = next(
        (w for w in existentes if "/webhook/chatwoot" in (w.get("url") or "")), None
    )
    cuerpo = {"url": url, "subscriptions": EVENTOS_DEL_WEBHOOK}
    if nuestro:
        r = httpx.patch(
            f"{api}/webhooks/{nuestro['id']}", headers=h, json=cuerpo, timeout=20
        )
        hecho = "actualizado"
    else:
        r = httpx.post(f"{api}/webhooks", headers=h, json=cuerpo, timeout=20)
        hecho = "creado"
    if r.status_code >= 300:
        print(f"  {MAL} Chatwoot no aceptó el webhook: {r.status_code} {r.text[:200]}")
        return 1
    print(f"  {OK} webhook {hecho} (mensajes, «asignada» y «resuelta»)")

    token_bot = _agente_bot(api, h, buzon["id"])
    if token_bot is None:
        return 1
    _organizar(api, h, usuario)

    _escribir_en_env(
        {
            "CHATWOOT_URL": base,
            "CHATWOOT_TOKEN": token,
            "CHATWOOT_BOT_TOKEN": token_bot,
            "CHATWOOT_ACCOUNT_ID": str(cuenta),
            "CHATWOOT_INBOX_ID": str(buzon["id"]),
            "CHATWOOT_WEBHOOK_TOKEN": secreto,
        }
    )
    print(f"  {OK} .env de VentaBot actualizado (el token no se muestra)")
    print(f"\n{C}{'=' * 74}{RST}")
    print(f"  {V}Chatwoot conectado.{RST} Falta un paso: {B}reinicia el bot{RST}")
    print("  (APAGAR-BOT.cmd y luego ENCENDER-BOT.cmd) para que lo tome.\n")
    return 0


def _agente_bot(api: str, h: dict, buzon: int) -> str | None:
    """Crea (o reutiliza) el agente bot «VentaBot», lo conecta al buzón y
    devuelve su token.

    Conectarlo es obligatorio: Chatwoot rechaza (401) al bot en cualquier buzón
    al que no esté conectado. Como NO tiene URL de salida, Chatwoot no le manda
    nada (el bot ya se entera por su propio webhook) y su token FIRMA lo que el
    bot copia, que es como se distingue del eco.

    Chatwoot hace nacer en «Pendiente» las charlas de un buzón con agente bot;
    el bot las pasa a «Abierta» enseguida, porque las «Pendiente» no salen en
    la bandeja ni en la app y parecía que no llegaban los mensajes (19/09).
    """
    import httpx

    r = httpx.get(f"{api}/agent_bots", headers=h, timeout=20)
    if r.status_code >= 300:
        print(f"  {MAL} no se pudo leer los agentes bot: {r.status_code}")
        return None
    bot = next((b for b in r.json() if b.get("name") == NOMBRE_DEL_BOT), None)
    if bot is None:
        r = httpx.post(
            f"{api}/agent_bots",
            headers=h,
            json={"name": NOMBRE_DEL_BOT, "description": "El bot de ventas de Lía"},
            timeout=20,
        )
        if r.status_code >= 300:
            print(f"  {MAL} no se pudo crear el agente bot: {r.status_code}")
            return None
        bot = r.json()
        print(f"  {OK} agente bot «{NOMBRE_DEL_BOT}» creado: firma lo que escribe el bot")
    else:
        print(f"  {OK} agente bot «{NOMBRE_DEL_BOT}» ya existía")
    if not bot.get("access_token"):
        bot = httpx.get(f"{api}/agent_bots/{bot['id']}", headers=h, timeout=20).json()
    if not bot.get("access_token"):
        print(f"  {MAL} Chatwoot no devolvió el token del agente bot")
        return None
    r = httpx.post(
        f"{api}/inboxes/{buzon}/set_agent_bot",
        headers=h,
        json={"agent_bot": bot["id"]},
        timeout=20,
    )
    if r.status_code >= 300:
        print(f"  {MAL} no se pudo conectar el agente bot al buzón: {r.status_code}")
        return None
    print(f"  {OK} agente bot conectado al buzón (contesta y firma «VentaBot»)")
    return bot["access_token"]


def _organizar(api: str, h: dict, usuario: int) -> None:
    """Deja Chatwoot organizado para el seguimiento. Se puede repetir sin miedo:
    lo que existe se actualiza y lo que falta se crea (nada se duplica)."""
    import httpx

    from app.domain.seguimiento import ACCIONES, ALERTAS, ETAPAS

    def pedir(metodo, ruta, **kw):
        r = httpx.request(metodo, f"{api}{ruta}", headers=h, timeout=20, **kw)
        r.raise_for_status()
        return r.json() if r.content else None

    # 1. Etiquetas: etapas, alertas y acciones, con su color y su «para qué».
    hay = {x["title"]: x for x in pedir("GET", "/labels").get("payload", [])}
    todas = [(e, d, c) for e, d, c in ETAPAS + ALERTAS] + [
        (e, d, c) for e, d, c, _ in ACCIONES
    ]
    for titulo, descripcion, color in todas:
        cuerpo = {
            "title": titulo,
            "description": descripcion,
            "color": color,
            "show_on_sidebar": not titulo.startswith("hacer-"),
        }
        if titulo in hay:
            if (hay[titulo].get("color"), hay[titulo].get("description")) != (
                color,
                descripcion,
            ):
                pedir("PATCH", f"/labels/{hay[titulo]['id']}", json=cuerpo)
        else:
            pedir("POST", "/labels", json=cuerpo)
    print(
        f"  {OK} etiquetas: {len(ETAPAS)} etapas, {len(ALERTAS)} alertas, "
        f"{len(ACCIONES)} acciones"
    )

    # 2. La ficha de la derecha.
    hay = {
        x.get("attribute_key")
        for x in pedir(
            "GET",
            "/custom_attribute_definitions",
            params={"attribute_model": "conversation_attribute"},
        )
    }
    for clave, nombre in ATRIBUTOS.items():
        if clave not in hay:
            pedir(
                "POST",
                "/custom_attribute_definitions",
                json={
                    "attribute_display_name": nombre,
                    "attribute_key": clave,
                    "attribute_display_type": "text",
                    "attribute_model": "conversation_attribute",
                },
            )
    print(f"  {OK} ficha del pedido ({len(ATRIBUTOS)} campos)")

    # 3. Respuestas rápidas («/cuentas», «/tiempos»…).
    hay = {x["short_code"]: x for x in pedir("GET", "/canned_responses")}
    for codigo, texto in _respuestas_rapidas():
        cuerpo = {"short_code": codigo, "content": texto}
        if codigo in hay:
            if hay[codigo].get("content") != texto:
                pedir("PATCH", f"/canned_responses/{hay[codigo]['id']}", json=cuerpo)
        else:
            pedir("POST", "/canned_responses", json=cuerpo)
    print(f"  {OK} respuestas rápidas: escribe «/» en Chatwoot")

    # 4. Carpetas de la barra lateral.
    hay = {x["name"] for x in pedir("GET", "/custom_filters")}
    for nombre, etiquetas in CARPETAS:
        if nombre in hay:
            continue
        condiciones = [
            {
                "attribute_key": "labels",
                "filter_operator": "equal_to",
                "values": [e],
                "query_operator": "or" if i < len(etiquetas) - 1 else None,
            }
            for i, e in enumerate(etiquetas)
        ]
        pedir(
            "POST",
            "/custom_filters",
            json={
                "name": nombre,
                "type": "conversation",
                "query": {"payload": condiciones},
            },
        )
    print(f"  {OK} carpetas ({len(CARPETAS)})")

    # 5. Macros: un toque = la acción (en el PC; en el celular, la etiqueta).
    nombres = {
        "hacer-abono-ok": "✅ Abono verificado",
        "hacer-anillo-listo": "✅ Anillo listo (cobrar saldo)",
        "hacer-saldo-ok": "✅ Saldo verificado",
        "hacer-despachado": "✅ Despachado",
        "hacer-entregado": "✅ Entregado",
        "hacer-preguntar-lo-que-falta": "🔁 Se trabó: ¿qué falta?",
        # Devolver NO es resolver (09/10): pone la etiqueta y el bot hace el
        # resto (se la asigna a VentaBot y sigue atendiendo).
        "hacer-devolver-al-bot": "🤖 Devolver al bot",
    }
    macros = [
        (nombres[e], [{"action_name": "add_label", "action_params": [e]}])
        for e, _, _, _ in ACCIONES
    ] + [
        # Una por persona: las macros de Chatwoot no saben «quién la usa», y una
        # sola «Tomar» se la asignaba siempre a quien corrió este script.
        (
            f"🙋 La toma {agente.get('available_name') or agente.get('name')}",
            [{"action_name": "assign_agent", "action_params": [agente["id"]]}],
        )
        for agente in pedir("GET", "/agents")
    ]
    hay = {x["name"]: x for x in pedir("GET", "/macros").get("payload", [])}
    vigentes = {nombre for nombre, _ in macros}
    for nombre, macro in hay.items():
        # Las del sistema empiezan con ✅/🙋/🤖: una con otro nombre es de una
        # versión vieja de este script y se borra. Las de Lía no se tocan.
        if nombre[:1] in "✅🙋🤖" and nombre not in vigentes:
            pedir("DELETE", f"/macros/{macro['id']}")
    for nombre, acciones in macros:
        cuerpo = {"name": nombre, "visibility": "global", "actions": acciones}
        if nombre in hay:
            pedir("PATCH", f"/macros/{hay[nombre]['id']}", json=cuerpo)
        else:
            pedir("POST", "/macros", json=cuerpo)
    print(f"  {OK} macros ({len(macros)})")


def main() -> int:
    ap = argparse.ArgumentParser(description="Chatwoot en el PC")
    ap.add_argument("--arrancar", action="store_true", help="levantarlo")
    ap.add_argument(
        "--conectar",
        action="store_true",
        help="después de crear tu usuario: conecta Chatwoot con el bot, solo",
    )
    args = ap.parse_args()

    s = get_settings()
    print(f"\n{C}{'=' * 74}")
    print("  CHATWOOT · el CRM de Lía, en tu PC")
    print(f"{'=' * 74}{RST}")

    print(f"\n{B}[1] Docker{RST}")
    if _docker() is None:
        print(f"  {MAL} no está instalado.")
        print(f"      {A}→{RST} instala Docker Desktop y vuelve\n")
        return 1
    if not _docker_vivo():
        print(f"  {MAL} está instalado pero el demonio no responde.")
        print(f"      {A}→{RST} abre Docker Desktop y espera a que arranque\n")
        return 1
    print(f"  {OK} Docker responde")

    print(f"\n{B}[2] Configuración{RST}")
    env = _preparar_env()
    print(f"  {OK} {env.relative_to(RAIZ)}")

    if args.arrancar:
        if _levantar() != 0:
            print(f"\n  {MAL} algo falló al levantarlo. Mira lo de arriba.\n")
            return 1
        print(f"\n  {OK} Chatwoot levantado.")
        print(f"\n  Abre {B}http://localhost:3000{RST} y crea la cuenta de Lía.")
        print("  Tarda un par de minutos en responder la primera vez.\n")

    if args.conectar:
        return _conectar(s)

    print(f"\n{B}[3] El bot le puede escribir{RST}")
    if not (s.chatwoot_url and s.chatwoot_token and s.chatwoot_inbox_id):
        print(f"  {PASO} todavía sin configurar en tu .env. Los pasos:")
        print()
        print(f"   1. {B}vb chatwoot --arrancar{RST}  (si no está corriendo)")
        print("   2. Abre http://localhost:3000 y crea tu usuario (una pantalla).")
        print(f"   3. {B}vb chatwoot --conectar{RST}  hace todo lo demás solo:")
        print("      el buzón, el webhook y el .env del bot.")
        print("   4. Reinicia el bot (APAGAR-BOT.cmd y ENCENDER-BOT.cmd).\n")
        return 1

    if not _probar_api(s):
        print()
        return 1

    print(f"\n{C}{'=' * 74}{RST}")
    print(f"  {V}Todo listo.{RST} Cada conversación se copia a Chatwoot con")
    print("  etiquetas: necesita-persona, confirmar-antes-de-fabricar,")
    print("  pago-por-verificar. Lía puede filtrar por ellas.\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
