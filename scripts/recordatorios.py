#!/usr/bin/env python3
"""Los recordatorios: a quién le toca qué y a qué hora. NO manda nada.

    vb recordatorios               <- los próximos y los últimos mandados
    vb recordatorios --plantilla   <- crea en Meta la plantilla del tercero
                                      (`retomar_diseno`) o dice cómo va
    vb recordatorios --plantillas  <- las 4 de los recordatorios POR DÍAS:
                                      dice cómo va cada una (no crea nada)
    vb recordatorios --plantillas --crear   <- las crea en Meta (con foto)
    vb recordatorios --medir       <- enviados, respondidos y ventas por
                                      segmento y por número de recordatorio

`vb recordatorios` lo corre en el servidor, donde está la base de verdad
(`docker compose exec -T ventabot python scripts/recordatorios.py`).

Las reglas están en `app/domain/recordatorios.py`. Los números salen
enmascarados (solo los 4 últimos dígitos): esto se mira en una terminal.
"""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

from app.domain import plantilla_de_emergencia as emergencia
from app.domain import recordatorios as r
from app.domain import recordatorios_por_dias as d
from app.infra.consola import preparar_salida
from app.infra.settings import get_settings

_C = preparar_salida()
V, R, A, G, C, RST = (_C.ok, _C.error, _C.aviso, _C.tenue, _C.titulo, _C.fin)

API = "https://graph.facebook.com/v21.0"


def _numero(conv: str) -> str:
    return f"…{conv[-4:]}"


def _hora(cuando: datetime) -> str:
    return cuando.astimezone(r.COLOMBIA).strftime("%a %d/%m %I:%M %p")


def ensayo() -> int:
    """Lo que haría el worker ahora mismo, sin mandar nada."""
    from app.adapters.repositories.recordatorios import (
        CharlasParaRecordar,
        RegistroDeRecordatorios,
    )
    from app.adapters.repositories.sqlite_store import SqliteDB
    from app.domain.models import Channel
    from app.infra.container import build_container
    from app.workers.recordatorios import planes

    s = get_settings()
    if s.repository_backend != "sqlite":
        print(f"  {R}Los recordatorios necesitan la base SQLite.{RST}")
        return 1
    # Un contenedor de solo lectura: sin canal de verdad, sin Chatwoot, sin el
    # worker. Solo para leer la base con las mismas reglas.
    c = build_container(
        s.model_copy(
            update={
                "channel_backend": "console",
                "chatwoot_url": "",
                "recordatorios": False,
                "ventas_cada_s": 0,
            }
        )
    )
    db = SqliteDB(s.sqlite_path)
    charlas, registro = CharlasParaRecordar(db), RegistroDeRecordatorios(db)

    def nombre_de(conv: str) -> str:
        clienta = c.customers.get_by_channel_user(
            Channel.WHATSAPP.value, conv.rsplit(":", 1)[-1]
        )
        return (clienta.nombre or "") if clienta is not None else ""

    ahora = datetime.now(UTC)
    print(f"\n{C}{'=' * 72}\n  RECORDATORIOS · {_hora(ahora)} (Colombia){RST}")
    estado = f"{V}ENCENDIDOS{RST}" if s.recordatorios else f"{A}apagados{RST}"
    plantilla = (
        f"{V}sí{RST}" if s.recordatorio_con_plantilla else f"{A}no (falta aprobarla){RST}"
    )
    print(f"  En el servidor: {estado} · plantilla a los 3 días: {plantilla}")
    print(f"{C}{'=' * 72}{RST}")

    recientes = charlas.recientes()
    por_dias = None
    if s.recordatorios_modo == "dias":
        from app.infra.container import _por_dias

        por_dias = _por_dias(s, c.products)
        print(f"  Modo: {V}por días{RST} (10 a. m. – 7 p. m., segmentos S1–S4)")
    proximos = planes(
        c.bot._mundo,
        charlas,
        registro,
        nombre_de,
        ahora,
        s.recordatorio_con_plantilla,
        por_dias,
    )
    print(f"\n{G}[1]{RST} Los próximos ({len(recientes)} charlas de los últimos días)")
    if not proximos:
        print(f"  {G}A nadie le toca uno.{RST}")
    for e in proximos:
        ya = f"{V}YA{RST}" if e.cuando <= ahora else _hora(e.cuando)
        tipo = f"plantilla {e.plantilla_nombre}" if e.plantilla else "texto"
        print(f"  {_numero(e.conversation_id)}  #{e.numero} ({tipo}) · {e.etapa} · {ya}")
        print(f"      {G}{e.texto[:110]}{RST}")

    print(f"\n{G}[2]{RST} Los últimos mandados")
    ultimos = registro.ultimos(15)
    if not ultimos:
        print(f"  {G}Ninguno todavía.{RST}")
    for f in ultimos:
        cuando = _hora(datetime.fromisoformat(f["enviado_en"]))
        print(
            f"  {_numero(f['conversation_id'])}  #{f['numero']} · {f['etapa']} · {cuando}"
        )
    print()
    return 0


def plantilla() -> int:
    """Crea la plantilla del tercero en Meta (si no existe) y dice cómo va."""
    import httpx

    s = get_settings()
    if not s.wa_access_token or not s.wa_business_account_id:
        print(f"  {R}Faltan WA_ACCESS_TOKEN o WA_BUSINESS_ACCOUNT_ID.{RST}")
        return 1
    h = {"Authorization": f"Bearer {s.wa_access_token}"}
    url = f"{API}/{s.wa_business_account_id}/message_templates"
    existentes = httpx.get(
        url,
        headers=h,
        params={"name": r.PLANTILLA, "fields": "name,status,category,rejected_reason"},
        timeout=30,
    )
    existentes.raise_for_status()
    datos = [p for p in existentes.json().get("data", []) if p["name"] == r.PLANTILLA]
    if not datos:
        cuerpo = {
            "name": r.PLANTILLA,
            "language": "es",
            "category": "MARKETING",
            "components": [
                {
                    "type": "BODY",
                    "text": r.CUERPO_DE_LA_PLANTILLA,
                    "example": {"body_text": [["Laura", "anillo"]]},
                },
                {
                    "type": "BUTTONS",
                    "buttons": [
                        {"type": "QUICK_REPLY", "text": b}
                        for b in r.BOTONES_DE_LA_PLANTILLA
                    ],
                },
            ],
        }
        creada = httpx.post(url, headers=h, json=cuerpo, timeout=30)
        if creada.status_code >= 400:
            error = creada.json().get("error", {})
            motivo = error.get("error_user_msg") or error.get("message")
            print(f"  {R}Meta no la aceptó: {motivo}{RST}")
            return 1
        info = creada.json()
        print(f"  {V}Creada{RST} «{r.PLANTILLA}» · estado: {info.get('status', '?')}")
    else:
        info = datos[0]
        print(
            f"  «{r.PLANTILLA}» · {info.get('category')} · estado: {info.get('status')}"
        )
        motivo = info.get("rejected_reason")
        if motivo and motivo != "NONE":
            print(f"  {R}motivo del rechazo: {motivo}{RST}")
    if info.get("status") == "APPROVED":
        print(
            f"  {V}Aprobada:{RST} ya se puede encender RECORDATORIO_CON_PLANTILLA=true "
            "en docker-compose.yml."
        )
    else:
        print(f"  {A}Mientras no esté APPROVED, el tercero no se manda.{RST}")
    return 0


def _id_de_la_app(httpx, token: str) -> str:
    """La app de Meta del token (hace falta para subir la foto de ejemplo)."""
    r_app = httpx.get(f"{API}/app", params={"access_token": token}, timeout=30)
    if r_app.is_success and r_app.json().get("id"):
        return r_app.json()["id"]
    dbg = httpx.get(
        f"{API}/debug_token",
        params={"input_token": token, "access_token": token},
        timeout=30,
    )
    dbg.raise_for_status()
    return dbg.json()["data"]["app_id"]


def _subir_foto_de_ejemplo(httpx, token: str, app_id: str, foto: Path) -> str:
    """Sube la foto de ejemplo de la cabecera (Meta la pide para revisar la
    plantilla) y devuelve su `header_handle`."""
    datos = foto.read_bytes()
    sesion = httpx.post(
        f"{API}/{app_id}/uploads",
        params={
            "file_name": foto.name,
            "file_length": len(datos),
            "file_type": "image/jpeg",
            "access_token": token,
        },
        timeout=30,
    )
    sesion.raise_for_status()
    subida = httpx.post(
        f"{API}/{sesion.json()['id']}",
        headers={"Authorization": f"OAuth {token}", "file_offset": "0"},
        content=datos,
        timeout=60,
    )
    subida.raise_for_status()
    return subida.json()["h"]


def _plantilla_de_emergencia(
    httpx,
    url: str,
    h: dict,
    nombre: str,
    info: dict | None,
    crear: bool,
    *,
    cuerpo: str | None = None,
    botones: tuple[str, ...] = emergencia.BOTONES,
    ejemplo: tuple[str, ...] = (),
):
    """Las de `#retomar` (16/10) y `#asesora` (19/10): solo texto y dos
    botones. La principal y la de respaldo: va la que Meta apruebe primero."""
    if info is not None:
        estado = info.get("status")
        color = V if estado == "APPROVED" else R if estado == "REJECTED" else A
        print(f"  «{nombre}» (emergencia) · {color}{estado}{RST}")
        return
    if not crear:
        print(f"  «{nombre}» (emergencia) · {A}no existe todavía{RST}")
        return
    creada = httpx.post(
        url,
        headers=h,
        json={
            "name": nombre,
            "language": "es",
            "category": "MARKETING",
            "components": [
                {
                    "type": "BODY",
                    "text": cuerpo or emergencia.PLANTILLAS[nombre],
                    **({"example": {"body_text": [list(ejemplo)]}} if ejemplo else {}),
                },
                *(
                    [
                        {
                            "type": "BUTTONS",
                            "buttons": [
                                {"type": "QUICK_REPLY", "text": b} for b in botones
                            ],
                        }
                    ]
                    if botones
                    else []
                ),
            ],
        },
        timeout=30,
    )
    if creada.is_success:
        print(f"  {V}Creada{RST} «{nombre}» · {creada.json().get('status')}")
    else:
        error = creada.json().get("error", {})
        motivo = error.get("error_user_msg") or error.get("message")
        print(f"  {R}Meta no aceptó «{nombre}»: {motivo}{RST}")


def plantillas_por_dias(crear: bool) -> int:
    """Las 4 plantillas de los recordatorios por días: cómo va cada una y, con
    `--crear`, las que falten (cabecera con foto, cuerpo y los tres botones)."""
    import httpx

    s = get_settings()
    if not s.wa_access_token or not s.wa_business_account_id:
        print(f"  {R}Faltan WA_ACCESS_TOKEN o WA_BUSINESS_ACCOUNT_ID.{RST}")
        return 1
    token = s.wa_access_token
    h = {"Authorization": f"Bearer {token}"}
    url = f"{API}/{s.wa_business_account_id}/message_templates"
    existentes = httpx.get(
        url,
        headers=h,
        params={"fields": "name,status,category,rejected_reason", "limit": 200},
        timeout=30,
    )
    existentes.raise_for_status()
    por_nombre = {p["name"]: p for p in existentes.json().get("data", [])}
    handle = None
    malas = 0
    for p in d.PLANTILLAS.values():
        if p.nombre in por_nombre:
            info = por_nombre[p.nombre]
            estado = info.get("status")
            color = V if estado == "APPROVED" else R if estado == "REJECTED" else A
            print(f"  «{p.nombre}» · {info.get('category')} · {color}{estado}{RST}")
            motivo = info.get("rejected_reason")
            if motivo and motivo != "NONE":
                print(f"     {R}motivo del rechazo: {motivo}{RST}")
            malas += estado != "APPROVED"
            continue
        if not crear:
            print(f"  «{p.nombre}» · {A}no existe todavía{RST} (--crear la manda a Meta)")
            malas += 1
            continue
        if handle is None:
            app_id = _id_de_la_app(httpx, token)
            foto = RAIZ / "data" / "imagenes" / f"{d.FOTO_DE_UN_ANILLO_GRABADO}.jpg"
            handle = _subir_foto_de_ejemplo(httpx, token, app_id, foto)
        for botones in (d.BOTONES, tuple(b.lstrip("💍 ") for b in d.BOTONES)):
            cuerpo = {
                "name": p.nombre,
                "language": "es",
                "category": "MARKETING",
                "components": [
                    {
                        "type": "HEADER",
                        "format": "IMAGE",
                        "example": {"header_handle": [handle]},
                    },
                    {
                        "type": "BODY",
                        "text": p.cuerpo,
                        "example": {"body_text": [list(p.ejemplo)]},
                    },
                    {
                        "type": "BUTTONS",
                        "buttons": [{"type": "QUICK_REPLY", "text": b} for b in botones],
                    },
                ],
            }
            creada = httpx.post(url, headers=h, json=cuerpo, timeout=30)
            if creada.is_success:
                print(
                    f"  {V}Creada{RST} «{p.nombre}» · estado: "
                    f"{creada.json().get('status', '?')}"
                )
                break
            error = creada.json().get("error", {})
            motivo = error.get("error_user_msg") or error.get("message")
            # Si Meta no acepta el emoji del botón, se intenta sin él.
            if botones == d.BOTONES:
                print(f"  {A}«{p.nombre}»: {motivo} · se intenta sin emoji{RST}")
                continue
            print(f"  {R}Meta no aceptó «{p.nombre}»: {motivo}{RST}")
            malas += 1
        else:
            malas += 1
    for nombre in emergencia.PLANTILLAS:
        _plantilla_de_emergencia(httpx, url, h, nombre, por_nombre.get(nombre), crear)
    for nombre, cuerpo in emergencia.PLANTILLAS_ASESORA.items():
        _plantilla_de_emergencia(
            httpx,
            url,
            h,
            nombre,
            por_nombre.get(nombre),
            crear,
            cuerpo=cuerpo,
            botones=()
            if nombre in emergencia.SIN_BOTONES
            else emergencia.BOTONES_ASESORA,
            ejemplo=emergencia.EJEMPLO_ASESORA if "{{1}}" in cuerpo else (),
        )
    if malas:
        print(
            f"\n  {A}Mientras no estén todas APPROVED, deja "
            f'RECORDATORIO_CON_PLANTILLA en "false": salen solo los del día 1.{RST}'
        )
    else:
        print(f'\n  {V}Todas aprobadas:{RST} RECORDATORIO_CON_PLANTILLA: "true".')
    return 0


def medir() -> int:
    """Enviados, respondidos (escribió en los 7 días siguientes) y ventas (abonó
    después), por segmento y por número de recordatorio. Y la apertura."""
    from app.adapters.repositories.sqlite_store import SqliteDB

    s = get_settings()
    db = SqliteDB(s.sqlite_path)
    filas = db.consultar(
        "SELECT conversation_id, numero, etapa, enviado_en FROM recordatorios_24h"
    )
    pagados = {
        f["conv"]: f["cuando"]
        for f in db.consultar(
            "SELECT 'wa:' || cu.channel_user_id AS conv, MIN(e.created_at) AS cuando "
            "FROM order_events e JOIN orders o ON o.id = e.order_id "
            "JOIN customers cu ON cu.id = o.customer_id "
            "WHERE e.estado_nuevo = 'ANTICIPO_PAGADO' GROUP BY conv"
        )
    }
    cuentas: dict[tuple[str, int], list[int]] = {}
    for f in filas:
        seg = f["etapa"].split(":")[0] if ":" in f["etapa"] else "antes (9/5)"
        enviado = f["enviado_en"]
        respondio = db.consultar(
            "SELECT 1 FROM messages WHERE conversation_id = ? AND direccion = 'IN' "
            "AND created_at > ? AND created_at < datetime(?, '+7 days') LIMIT 1",
            (f["conversation_id"], enviado, enviado),
        )
        vendio = (pagados.get(f["conversation_id"]) or "") > enviado
        c = cuentas.setdefault((seg, int(f["numero"])), [0, 0, 0])
        c[0] += 1
        c[1] += bool(respondio)
        c[2] += bool(vendio)
    print(f"\n{C}  RECORDATORIOS: lo que pasó después de cada uno{RST}")
    print(
        f"  {'segmento':28} {'#':>2} {'enviados':>9} {'respondieron':>13} {'ventas':>7}"
    )
    for (seg, n), (env, resp, ven) in sorted(cuentas.items()):
        nombre = f"{seg} {d.NOMBRES_DE_LOS_SEGMENTOS.get(seg, '')}".strip()[:28]
        pct = f"{100 * resp / env:.0f} %" if env else "-"
        print(f"  {nombre:28} {n:>2} {env:>9} {resp:>6} ({pct:>4}) {ven:>7}")
    # La prueba de la apertura: ¿cuántas escriben un segundo mensaje?
    aperturas = db.consultar("SELECT conversation_id, payload FROM conv_contexto")
    import json

    grupos = {"con el peludito": [0, 0], "con los precios": [0, 0]}
    for a in aperturas:
        b = (json.loads(a["payload"] or "{}") or {}).get("borrador") or {}
        mostrado = b.get("mostrado_en") or {}
        if "APERTURA_PELUDITO" in mostrado:
            g = "con el peludito"
        elif "MOSTRAR_PRECIOS" in mostrado:
            g = "con los precios"
        else:
            continue
        suyos = db.consultar(
            "SELECT COUNT(*) AS n FROM messages WHERE conversation_id = ? "
            "AND direccion = 'IN'",
            (a["conversation_id"],),
        )[0]["n"]
        grupos[g][0] += 1
        grupos[g][1] += suyos >= 2
    print(f"\n{C}  LA APERTURA: ¿escriben un segundo mensaje?{RST}")
    for g, (n, dos) in grupos.items():
        pct = f"{100 * dos / n:.0f} %" if n else "-"
        print(f"  {g:18} {n:>5} charlas · {dos:>4} escribieron otra vez ({pct})")
    print()
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Recordatorios (no manda nada)")
    ap.add_argument(
        "--plantilla",
        action="store_true",
        help="crea en Meta la plantilla del tercero, o dice cómo va",
    )
    ap.add_argument(
        "--plantillas",
        action="store_true",
        help="las 4 plantillas de los recordatorios por días: cómo va cada una",
    )
    ap.add_argument("--crear", action="store_true", help="con --plantillas: las crea")
    ap.add_argument("--medir", action="store_true", help="qué pasó después de cada uno")
    args = ap.parse_args()
    if args.plantillas:
        return plantillas_por_dias(args.crear)
    if args.medir:
        return medir()
    return plantilla() if args.plantilla else ensayo()


if __name__ == "__main__":
    raise SystemExit(main())
