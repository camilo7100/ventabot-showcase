"""Registro de TODOS los webhooks que entran, válidos o no.

POR QUÉ HIZO FALTA
==================
Guardar solo el último webhook rechazado no alcanza. Cuando llegan mensajes
reales mezclados con clics al botón «Probar» del panel, cada uno sobrescribe al
anterior y acabas analizando el que no era. Se pierde una tarde así.

Este registro es un `.jsonl` (una línea de JSON por webhook) con lo justo para
responder de un vistazo las preguntas que importan:

    ¿llegó algo?  ¿de qué cuenta?  ¿la firma cuadró?  ¿era el ejemplo de Meta?
    ¿qué decía?   ¿se encoló una respuesta?

NO guarda la firma ni el secreto. Del cuerpo guarda solo el texto del mensaje,
que es lo que hace falta para reconocerlo.
"""

from __future__ import annotations

import contextlib
import json
from datetime import UTC, datetime
from pathlib import Path

MAX_LINEAS = 500


def _resumir(cuerpo: bytes) -> dict:
    """Saca lo identificable del payload sin guardarlo entero."""
    try:
        d = json.loads(cuerpo)
    except Exception:
        return {"tipo": "ilegible"}

    entry = (d.get("entry") or [{}])[0]
    value = ((entry.get("changes") or [{}])[0]).get("value", {})
    mensajes = value.get("messages") or []
    estados = value.get("statuses") or []

    resumen = {
        "waba_id": entry.get("id"),
        "phone_number_id": (value.get("metadata") or {}).get("phone_number_id"),
        "n_mensajes": len(mensajes),
        "n_estados": len(estados),
    }
    if mensajes:
        m = mensajes[0]
        resumen |= {
            "de": m.get("from"),
            "tipo_mensaje": m.get("type"),
            "texto": ((m.get("text") or {}).get("body") or "")[:120],
            "message_id": (m.get("id") or "")[:40],
        }
    elif estados:
        # Meta también manda acuses de entrega. Son webhooks legítimos que NO
        # son mensajes: si solo llegan estos, es que nadie te ha escrito.
        resumen |= {"estado": estados[0].get("status")}
    return resumen


def registrar(
    ruta: Path,
    *,
    cuerpo: bytes,
    firma_valida: bool,
    es_ejemplo: bool,
    encolados: int | None = None,
    nota: str = "",
) -> None:
    fila = {
        "cuando": datetime.now(UTC).isoformat(timespec="seconds"),
        "bytes": len(cuerpo),
        "firma_valida": firma_valida,
        "es_ejemplo_de_meta": es_ejemplo,
        "encolados": encolados,
        "nota": nota,
        **_resumir(cuerpo),
    }
    # Registrar NUNCA puede tumbar la API: un fallo al escribir el log no
    # justifica perder el mensaje de un cliente.
    with contextlib.suppress(Exception):
        ruta.parent.mkdir(parents=True, exist_ok=True)
        with ruta.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(fila, ensure_ascii=False) + "\n")
        _recortar(ruta)


def _recortar(ruta: Path) -> None:
    lineas = ruta.read_text(encoding="utf-8").splitlines()
    if len(lineas) > MAX_LINEAS:
        ruta.write_text("\n".join(lineas[-MAX_LINEAS:]) + "\n", encoding="utf-8")


def ultimo(ruta: Path):
    """Cuándo entró el último webhook, o None si no hay ninguno.

    Cuenta CUALQUIERA, no solo los mensajes: Meta acusa recibo de todo lo que
    se manda en segundos, así que su ausencia es la señal de que no entra nada.
    """
    from datetime import UTC, datetime

    for registro in reversed(leer(ruta, ultimos=5)):
        cuando = registro.get("cuando")
        if not cuando:
            continue
        with contextlib.suppress(TypeError, ValueError):
            momento = datetime.fromisoformat(cuando)
            return momento if momento.tzinfo else momento.replace(tzinfo=UTC)
    return None


def leer(ruta: Path, ultimos: int = 30) -> list[dict]:
    if not ruta.exists():
        return []
    out = []
    for ln in ruta.read_text(encoding="utf-8").splitlines()[-ultimos:]:
        # Una línea corrupta (si el proceso murió a mitad de escribirla) no
        # debe impedir leer las demás.
        with contextlib.suppress(Exception):
            out.append(json.loads(ln))
    return out
