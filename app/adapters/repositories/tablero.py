"""El tablero: cómo va el negocio y cómo va el bot, desde la base local.

Todo sale de tablas que ya existen (`messages`, `orders`, `conv_contexto`,
`decisiones`): no hay un segundo registro que se pueda desincronizar, ni se
manda nada a un servicio de fuera. Son números agregados: sin textos ni
teléfonos, se pueden mirar en cualquier parte.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta, timezone

from app.adapters.repositories.sqlite_store import SqliteDB, SqliteDecisiones
from app.domain.numeros_propios import solo_respuesta_inmediata

#: Estados en los que la clienta YA pagó al menos el anticipo: es una venta.
PAGADOS = (
    "ANTICIPO_PAGADO",
    "EN_PRODUCCION",
    "PRODUCCION_LISTA",
    "ESPERANDO_SALDO",
    "SALDO_PAGADO",
    "DESPACHADO",
    "ENTREGADO",
)

#: Una respuesta que tarda más que esto no es «el bot contestó», es otra charla
#: (la clienta volvió al día siguiente): no entra en el tiempo de respuesta.
RESPUESTA_MAXIMA_S = 600


def tablero(db: SqliteDB, desde: str) -> dict:
    """Los números desde `desde` (ISO en UTC)."""
    mensajes = db.consultar(
        "SELECT conversation_id, direccion, created_at FROM messages "
        "WHERE created_at >= ? ORDER BY conversation_id, id",
        (desde,),
    )
    recibidos = [m for m in mensajes if m["direccion"] == "IN"]
    con_clientas = {m["conversation_id"] for m in recibidos}
    primeras = db.consultar(
        "SELECT conversation_id, MIN(created_at) AS primera FROM messages "
        "WHERE direccion = 'IN' GROUP BY conversation_id"
    )
    nuevas = sum(1 for f in primeras if f["primera"] >= desde)

    pedidos = db.consultar(
        "SELECT estado, payload FROM orders WHERE created_at >= ?", (desde,)
    )
    pagados = [p for p in pedidos if p["estado"] in PAGADOS]
    ventas = sum(int(json.loads(p["payload"]).get("total_cop") or 0) for p in pagados)

    a_mano = 0
    ahora = datetime.now().astimezone()
    for (payload,) in db.consultar("SELECT payload FROM conv_contexto"):
        hasta = (json.loads(payload) or {}).get("humano_hasta")
        if hasta and datetime.fromisoformat(hasta) > ahora:
            a_mano += 1

    bot = SqliteDecisiones(db).metricas(desde)
    return {
        "conversaciones": len(con_clientas),
        "nuevas": nuevas,
        "recibidos": len(recibidos),
        "enviados": len(mensajes) - len(recibidos),
        "respuesta_p50_s": _respuesta_p50(mensajes),
        "pedidos": len(pedidos),
        "pagados": len(pagados),
        "ventas_cop": ventas,
        "conversion_pct": round(100 * len(pagados) / nuevas, 1) if nuevas else 0.0,
        "a_mano_ahora": a_mano,
        "bot": bot,
    }


def _respuesta_p50(mensajes) -> float | None:
    """Mediana de segundos entre lo que escribe la clienta y lo siguiente que sale.

    Varias piezas seguidas de la clienta cuentan desde la primera: es lo que
    ella siente que esperó.
    """
    esperas: list[float] = []
    esperando_desde: datetime | None = None
    conversacion = None
    for m in mensajes:
        if m["conversation_id"] != conversacion:
            conversacion, esperando_desde = m["conversation_id"], None
        cuando = datetime.fromisoformat(m["created_at"])
        if m["direccion"] == "IN":
            esperando_desde = esperando_desde or cuando
        elif esperando_desde is not None:
            segundos = (cuando - esperando_desde).total_seconds()
            if 0 <= segundos <= RESPUESTA_MAXIMA_S:
                esperas.append(segundos)
            esperando_desde = None
    if not esperas:
        return None
    esperas.sort()
    return round(esperas[len(esperas) // 2], 1)


#: Los números inventados de las pruebas (5700000000xx): nunca son clientas.
PREFIJO_DE_PRUEBA = "5700000000"
#: Colombia no cambia de hora: UTC−5 fijo (sin `ZoneInfo`, que en Windows falla).
_COLOMBIA = timezone(timedelta(hours=-5))


def embudo_por_dia(db: SqliteDB, desde: str) -> list[dict]:
    """El embudo del chat, día por día, para la pestaña «Piloto» (03/10).

    Cada conversación cuenta en el día (de Colombia) en que la clienta escribió
    por PRIMERA vez —la regla de conteo del piloto: la venta es del día en que
    empezó la charla, no del día del pago— y llega hasta donde llegó:

    - **enganchada**: ya escogió algo (huellitas, colores o grabado);
    - **lista para pagar**: hay pedido (se le pidió el abono);
    - **venta**: el abono está confirmado (`PAGADOS`).

    Solo totales: ni textos ni teléfonos salen de aquí. `desde` es una fecha
    AAAA-MM-DD (de Colombia).
    """
    pedidos = {
        f["id"]: (f["estado"], f["payload"])
        for f in db.consultar("SELECT id, estado, payload FROM orders")
    }
    contextos = {
        f["conversation_id"]: f["payload"]
        for f in db.consultar("SELECT conversation_id, payload FROM conv_contexto")
    }
    dias: dict[str, dict] = {}
    for f in db.consultar(
        "SELECT conversation_id, MIN(created_at) AS primera FROM messages "
        "WHERE direccion = 'IN' GROUP BY conversation_id"
    ):
        conv = f["conversation_id"]
        if solo_respuesta_inmediata(conv):
            continue
        primera = datetime.fromisoformat(f["primera"])
        if primera.tzinfo is None:
            primera = primera.replace(tzinfo=UTC)
        dia = primera.astimezone(_COLOMBIA).date().isoformat()
        if dia < desde:
            continue
        b = _borrador(contextos.get(conv))
        estado, payload = pedidos.get(b.get("pedido_id") or "", ("", "{}"))
        fila = dias.setdefault(
            dia,
            {
                "fecha": dia,
                "conversaciones": 0,
                "enganchadas": 0,
                "listas": 0,
                "ventas": 0,
                "ventas_cop": 0,
            },
        )
        fila["conversaciones"] += 1
        if estado or any(
            b.get(k) for k in ("cantidad", "huellitas", "grabado", "anillos")
        ):
            fila["enganchadas"] += 1
        if estado:
            fila["listas"] += 1
        if estado in PAGADOS:
            fila["ventas"] += 1
            fila["ventas_cop"] += int(json.loads(payload).get("total_cop") or 0)
    return [dias[d] for d in sorted(dias)]


def _borrador(payload: str | None) -> dict:
    try:
        b = (json.loads(payload or "{}") or {}).get("borrador") or {}
    except ValueError:
        return {}
    return b if isinstance(b, dict) else {}
