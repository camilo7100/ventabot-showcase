#!/usr/bin/env python3
"""Borra las conversaciones de PRUEBA y deja el sistema como recién instalado.

    vb reiniciar            # dice qué se va a borrar y pregunta
    vb reiniciar --si       # lo hace sin preguntar
    vb reiniciar --pedidos  # además borra los pedidos (y sus eventos)
    vb reiniciar --numeros 3001110002,3001110001
                            # SOLO esos números: su charla, su ficha, sus
                            # pedidos y su contacto en Chatwoot. Lo demás no
                            # se toca. Es lo que usa REINICIAR-PRUEBAS.cmd.

Mientras probamos, en el CRM y en la base se acumulan charlas que no son de
nadie: clientas inventadas, ensayos, mensajes repetidos. Dejarlas ahí es peor
que sucio — falsea las métricas, ensucia el ERP y hace dudar de lo que se ve.

QUÉ BORRA
  · Chatwoot: los contactos de la cuenta y, con ellos, sus conversaciones.
  · La base del bot: conversaciones, mensajes, memoria de cada charla, la
    bandeja de salida, los eventos ya procesados y las decisiones grabadas.
  · Con `--pedidos`: también los pedidos, sus eventos, las claves de
    idempotencia y las notas del Excel de ventas. Las fotos de las pruebas se
    APARTAN a la carpeta de respaldos (no se borran) y las previsualizaciones,
    que el bot redibuja, se borran. Es lo que se corre justo antes de pasar a
    clientas de verdad (docs/MANUAL-VIVO.md).
  · Siempre: el análisis de pedidos (`pedidos_analitica`) se rehace con lo que
    queda.

QUÉ NO TOCA
  El catálogo, los fletes, las reglas, el ERP de Google Sheets ni la
  configuración de Chatwoot (etiquetas, macros, carpetas). El Excel de ventas
  se vuelve a escribir solo, desde los pedidos que quedan (con `--pedidos` se
  crea nuevo, después de copiarlo al respaldo).

SIEMPRE hace un respaldo antes. Si algo se borró de más, está en
Documents\\Respaldos\\VentaBot.
"""

from __future__ import annotations

import argparse
import re
import sqlite3
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

from app.infra.consola import preparar_salida

# UTF-8 pase lo que pase: sin esto, redirigir la salida a un archivo (o
# leerla desde otro proceso) revienta en Windows al imprimir un ✔.
_C = preparar_salida()
V, R, A, G, C, RST = (_C.ok, _C.error, _C.aviso, _C.tenue, _C.titulo, _C.fin)
OK, MAL = f"{V}✔{RST}", f"{R}✘{RST}"

from app.infra.settings import get_settings

#: Lo que guarda una conversación. El orden importa poco (no hay claves
#: foráneas duras), pero se listan de lo más grande a lo más pequeño.
TABLAS_DE_CHARLA = (
    "messages",
    "conv_contexto",
    "conversations",
    "outbox",
    "processed_events",
    "checkpoints",
    "decisiones",
    "writes",
    "recordatorios_24h",
    "customers",
)

#: Solo con --pedidos. Un pedido es plata: no se borra sin decirlo. Van también
#: las notas del Excel de ventas y su historial: sin pedidos no son de nadie.
#: (`pedidos_analitica` no está aquí: se rehace al final desde lo que queda.)
TABLAS_DE_PEDIDO = (
    "order_events",
    "order_idem",
    "orders",
    "ventas_anotaciones",
    "ventas_anotaciones_log",
    "ventas_sincronizaciones",
)


def rehacer_analitica(ruta_base: Path) -> int:
    """La tabla de análisis (`pedidos_analitica`) se aplana desde los pedidos
    que QUEDAN: sin esto, los pedidos de prueba seguían en el análisis y en el
    CSV del panel después de borrarlos (visto el 29/09)."""
    from app.adapters.repositories.analitica_sqlite import SqliteAnalitica
    from app.adapters.repositories.sqlite_store import SqliteDB

    return SqliteAnalitica(SqliteDB(ruta_base)).reconstruir()


def apartar_medios(s, carpeta_respaldos: Path) -> tuple[int, int]:
    """Las fotos de las pruebas (reglas, mascotas, comprobantes) se APARTAN a la
    carpeta de respaldos, no se borran; las previsualizaciones se borran porque
    el bot las vuelve a dibujar. Devuelve (fotos apartadas, previas borradas)."""
    import shutil
    from datetime import datetime

    from scripts.respaldo import COLOMBIA

    def archivos(carpeta: Path) -> list[Path]:
        return [f for f in carpeta.glob("*") if f.is_file()] if carpeta.exists() else []

    fotos = archivos(s.fotos_dir)
    if fotos:
        hora = datetime.now(COLOMBIA)
        destino = carpeta_respaldos / f"fotos-de-prueba-{hora:%Y%m%d-%H%M}"
        destino.mkdir(parents=True, exist_ok=True)
        for f in fotos:
            shutil.move(str(f), str(destino / f.name))
    previas = archivos(s.renders_dir)
    for f in previas:
        f.unlink()
    # El Excel de ventas (ya copiado en el respaldo): la próxima vuelta lo crea
    # nuevo. Si se quedara, sus notas de pedidos de prueba volverían a la base.
    Path(s.ventas_excel).unlink(missing_ok=True)
    return len(fotos), len(previas)


def _contar(cx: sqlite3.Connection, tablas: tuple[str, ...]) -> dict[str, int]:
    existentes = {
        r[0] for r in cx.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    return {
        t: cx.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        for t in tablas
        if t in existentes
    }


def _borrar(cx: sqlite3.Connection, tablas: dict[str, int]) -> None:
    for t in tablas:
        cx.execute(f"DELETE FROM {t}")
    cx.commit()


# ── Solo algunos números (--numeros) ───────────────────────────────────────


def normalizar(numero: str) -> str:
    """«300 111 0002» o «+57 3001110002» -> «573001110002», como lo guarda Meta."""
    digitos = re.sub(r"\D", "", numero)
    if len(digitos) == 10 and digitos.startswith("3"):
        digitos = "57" + digitos
    return digitos


def _existe(cx: sqlite3.Connection, tabla: str) -> bool:
    return bool(
        cx.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (tabla,)
        ).fetchone()
    )


def _que_borrar(
    cx: sqlite3.Connection, numeros: list[str]
) -> list[tuple[str, str, list]]:
    """(tabla, columna, valores): todo lo que es de esos números y de nadie más."""
    from app.domain.decisiones import huella_conversacion

    convs = [f"wa:{n}" for n in numeros]
    marcas = ",".join("?" * len(numeros))
    clientas = [
        r[0]
        for r in cx.execute(
            f"SELECT id FROM customers WHERE channel_user_id IN ({marcas})", numeros
        )
    ]
    pedidos: list[str] = []
    if clientas:
        marcas_c = ",".join("?" * len(clientas))
        pedidos = [
            r[0]
            for r in cx.execute(
                f"SELECT id FROM orders WHERE customer_id IN ({marcas_c})", clientas
            )
        ]
    return [
        ("messages", "conversation_id", convs),
        ("conv_contexto", "conversation_id", convs),
        ("conversations", "conversation_id", convs),
        ("checkpoints", "thread_id", convs),
        ("writes", "thread_id", convs),
        ("decisiones", "conversacion", [huella_conversacion(c) for c in convs]),
        ("outbox", "destinatario", numeros),
        ("recordatorios_24h", "conversation_id", convs),
        ("order_events", "order_id", pedidos),
        ("order_idem", "order_id", pedidos),
        ("ventas_anotaciones", "order_id", pedidos),
        ("ventas_anotaciones_log", "order_id", pedidos),
        ("orders", "id", pedidos),
        ("customers", "id", clientas),
    ]


def _contar_numeros(cx, plan) -> dict[str, int]:
    cuenta: dict[str, int] = {}
    for tabla, columna, valores in plan:
        if not valores or not _existe(cx, tabla):
            continue
        marcas = ",".join("?" * len(valores))
        n = cx.execute(
            f"SELECT COUNT(*) FROM {tabla} WHERE {columna} IN ({marcas})", valores
        ).fetchone()[0]
        if n:
            cuenta[tabla] = n
    return cuenta


def _borrar_numeros(cx, plan) -> None:
    for tabla, columna, valores in plan:
        if not valores or not _existe(cx, tabla):
            continue
        marcas = ",".join("?" * len(valores))
        cx.execute(f"DELETE FROM {tabla} WHERE {columna} IN ({marcas})", valores)
    cx.commit()


def _chatwoot_de_numeros(s, numeros: list[str]) -> list[dict]:
    """Los contactos de Chatwoot cuyo teléfono es uno de esos números."""
    import httpx

    api = f"{s.chatwoot_url}/api/v1/accounts/{s.chatwoot_account_id}"
    h = {"api_access_token": s.chatwoot_token}
    encontrados: dict[int, dict] = {}
    for n in numeros:
        r = httpx.get(f"{api}/contacts/search", headers=h, params={"q": n}, timeout=30)
        r.raise_for_status()
        for c in r.json().get("payload") or []:
            if re.sub(r"\D", "", c.get("phone_number") or "").endswith(n[-10:]):
                encontrados[c["id"]] = c
    return list(encontrados.values())


def _chatwoot_contactos(s) -> list[dict]:
    import httpx

    api = f"{s.chatwoot_url}/api/v1/accounts/{s.chatwoot_account_id}"
    h = {"api_access_token": s.chatwoot_token}
    contactos, pagina = [], 1
    while True:
        r = httpx.get(f"{api}/contacts", headers=h, params={"page": pagina}, timeout=30)
        r.raise_for_status()
        lote = r.json().get("payload") or []
        if not lote:
            return contactos
        contactos += lote
        pagina += 1


def _chatwoot_borrar(s, contactos: list[dict]) -> tuple[int, int]:
    import httpx

    api = f"{s.chatwoot_url}/api/v1/accounts/{s.chatwoot_account_id}"
    h = {"api_access_token": s.chatwoot_token}
    borrados = fallos = 0
    for c in contactos:
        r = httpx.delete(f"{api}/contacts/{c['id']}", headers=h, timeout=30)
        if r.status_code < 300:
            borrados += 1
        else:
            fallos += 1
    return borrados, fallos


def main() -> int:
    ap = argparse.ArgumentParser(description="Borra las charlas de prueba")
    ap.add_argument("--si", action="store_true", help="no preguntar")
    ap.add_argument("--pedidos", action="store_true", help="borrar también los pedidos")
    ap.add_argument(
        "--numeros",
        default="",
        help="solo estos números, separados por coma (con o sin el 57)",
    )
    args = ap.parse_args()

    s = get_settings()
    if args.numeros:
        return _solo_numeros(s, args)
    print(f"\n{C}{'=' * 74}")
    print("  REINICIAR LOS CHATS · deja el sistema como recién instalado")
    print(f"{'=' * 74}{RST}\n")

    cx = sqlite3.connect(str(s.sqlite_path))
    charla = _contar(cx, TABLAS_DE_CHARLA)
    pedidos = _contar(cx, TABLAS_DE_PEDIDO) if args.pedidos else {}

    hay_crm = bool(s.chatwoot_url and s.chatwoot_token and s.chatwoot_account_id)
    contactos: list[dict] = []
    if hay_crm:
        try:
            contactos = _chatwoot_contactos(s)
        except Exception as e:
            print(f"  {MAL} no se pudo hablar con Chatwoot: {e}")
            hay_crm = False

    print(f"  Base del bot   {G}{s.sqlite_path}{RST}")
    for t, n in {**charla, **pedidos}.items():
        print(f"    {t:22} {n}")
    if hay_crm:
        print(f"  Chatwoot       {G}{s.chatwoot_url}{RST}")
        print(f"    {'contactos (con sus charlas)':22} {len(contactos)}")

    total = sum(charla.values()) + sum(pedidos.values()) + len(contactos)
    if total == 0:
        print(f"\n  {OK} Ya está limpio: no hay nada que borrar.\n")
        return 0

    if not args.si:
        print(f"\n  {A}Esto NO se puede deshacer (pero se hace un respaldo antes).{RST}")
        if input("  Escribe «si» para continuar: ").strip().lower() not in ("si", "sí"):
            print("\n  Cancelado. No se tocó nada.\n")
            return 1

    print(f"\n{C}[1] Respaldo{RST}")
    import scripts.respaldo as respaldo

    # `respaldo.main()` lee sys.argv: sin esconderle los nuestros, se queja de
    # «--si» y sale antes de copiar nada.
    argv = sys.argv
    try:
        sys.argv = [argv[0]]
        respaldo.main()
    finally:
        sys.argv = argv

    print(f"\n{C}[2] La base del bot{RST}")
    _borrar(cx, charla)
    print(f"  {OK} {sum(charla.values())} fila(s) de conversación borradas")
    if pedidos:
        _borrar(cx, pedidos)
        print(f"  {OK} {sum(pedidos.values())} fila(s) de pedidos borradas")
    cx.execute("VACUUM")
    cx.close()
    print(f"  {OK} base compactada")
    print(f"  {OK} análisis rehecho: {rehacer_analitica(s.sqlite_path)} pedido(s)")
    if pedidos:
        apartadas, previas = apartar_medios(s, respaldo.carpeta_de_respaldos())
        print(
            f"  {OK} {apartadas} foto(s) de prueba apartadas a los respaldos y "
            f"{previas} previsualización(es) borradas; el Excel de ventas se "
            "crea nuevo en la próxima vuelta"
        )

    if hay_crm and contactos:
        print(f"\n{C}[3] Chatwoot{RST}")
        borrados, fallos = _chatwoot_borrar(s, contactos)
        print(f"  {OK} {borrados} contacto(s) borrados con sus conversaciones")
        if fallos:
            print(f"  {MAL} {fallos} no se pudieron borrar (míralos en Chatwoot)")

    print(f"\n  {V}Listo.{RST} La próxima clienta que escriba empieza de cero.\n")
    return 0


def _solo_numeros(s, args) -> int:
    """Borra SOLO lo de esos números: los de prueba de Camilo (27/09).

    Todo lo demás —las clientas de verdad, sus pedidos, sus conversaciones—
    queda exactamente igual. El ERP de Google Sheets no se toca.
    """
    numeros = sorted({normalizar(n) for n in args.numeros.split(",") if normalizar(n)})
    print(f"\n{C}{'=' * 74}")
    print("  REINICIAR NÚMEROS DE PRUEBA · solo estos, lo demás no se toca")
    print(f"{'=' * 74}{RST}\n")
    for n in numeros:
        print(f"    {n}")

    cx = sqlite3.connect(str(s.sqlite_path))
    plan = _que_borrar(cx, numeros)
    cuenta = _contar_numeros(cx, plan)

    hay_crm = bool(s.chatwoot_url and s.chatwoot_token and s.chatwoot_account_id)
    contactos: list[dict] = []
    if hay_crm:
        try:
            contactos = _chatwoot_de_numeros(s, numeros)
        except Exception as e:
            print(f"  {MAL} no se pudo hablar con Chatwoot: {e}")
            hay_crm = False

    print(f"\n  Base del bot   {G}{s.sqlite_path}{RST}")
    for tabla, n in cuenta.items():
        print(f"    {tabla:22} {n}")
    if hay_crm:
        print("  Chatwoot")
        print(f"    {'contactos (con sus charlas)':22} {len(contactos)}")

    if not cuenta and not contactos:
        print(f"\n  {OK} Esos números ya están en cero: no hay nada que borrar.\n")
        return 0

    if not args.si:
        print(f"\n  {A}Esto NO se puede deshacer (pero se hace un respaldo antes).{RST}")
        if input("  Escribe «si» para continuar: ").strip().lower() not in ("si", "sí"):
            print("\n  Cancelado. No se tocó nada.\n")
            return 1

    print(f"\n{C}[1] Respaldo{RST}")
    import scripts.respaldo as respaldo

    argv = sys.argv
    try:
        sys.argv = [argv[0]]
        respaldo.main()
    finally:
        sys.argv = argv

    print(f"\n{C}[2] La base del bot{RST}")
    _borrar_numeros(cx, plan)
    cx.close()
    print(f"  {OK} {sum(cuenta.values())} fila(s) borradas (charla, ficha y pedidos)")
    print(f"  {OK} análisis rehecho: {rehacer_analitica(s.sqlite_path)} pedido(s)")

    if hay_crm and contactos:
        print(f"\n{C}[3] Chatwoot{RST}")
        borrados, fallos = _chatwoot_borrar(s, contactos)
        print(f"  {OK} {borrados} contacto(s) borrados con sus conversaciones")
        if fallos:
            print(f"  {MAL} {fallos} no se pudieron borrar (míralos en Chatwoot)")

    print(
        f"\n  {V}Listo.{RST} Esos números empiezan de cero la próxima vez que escriban.\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
