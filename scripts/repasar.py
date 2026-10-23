#!/usr/bin/env python3
"""Repasa conversaciones REALES contra el bot y las puntúa.

    vb repasar                      <- todos los escenarios, con la asesora
    vb repasar --motor pipeline     <- el gestor por etiquetas, para comparar
    vb repasar --solo septima       <- los escenarios cuyo nombre contenga eso

Cada escenario es un JSON en `..\\material\\escenarios` (fuera del repo: lleva
nombres de clientas reales) con lo que escribió la clienta, las fotos descritas
y lo que Lía anotó al final. El bot conversa con una base TEMPORAL y el canal de
consola: no toca pedidos reales ni manda nada a nadie. Sí llama a la API de
Claude (unos centavos de dólar por repaso completo).

Qué se mide:
  · resultado: cantidad, talla, colores de cada huellita, grabado, nombre, ciudad,
    pedido creado y abono reportado — contra el resumen final de Lía;
  · señales de bot: respuestas idénticas seguidas, «no te entendí», bienvenida a
    mitad de venta, escalados, frases que el vigilante tuvo que quitar;
  · calidez: una frase casi igual a otra de los 3 mensajes anteriores cuenta
    como «casi repetida»; más de una en la conversación no pasa;
  · costo y latencia.

Deja la transcripción de cada conversación en `..\\material\\repasos\\<fecha>`.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import time
import unicodedata
from datetime import datetime
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

MATERIAL = RAIZ.parent / "material"


def _plano(texto: str) -> str:
    t = unicodedata.normalize("NFKD", str(texto or "")).lower()
    return "".join(c for c in t if not unicodedata.combining(c))


#: Renglones que pone el SISTEMA (resumen, cuentas, fichas): repetirlos es correcto.
_PLANTILLA = (
    "•",
    "talla:",
    "huellita ",
    "color:",
    "grabado:",
    "*a esta cuenta",
    "✨",
    "envios nacionales",
    "el envio nacional (",
    "estos son los colores",
    "con un anillo que conserve",
    "🎀",
    "🪄",
    "💰",
    "⏳",
    "📏 se fabrica",
    "🎨 escoge",
    "🖊️",
    "cuando este listo",
)


def _solo_lo_escrito(texto: str) -> str:
    """El mensaje sin los renglones de plantilla: lo que de verdad «dijo» Lía."""
    return "\n".join(
        r
        for r in (texto or "").split("\n")
        if not _plano(r.strip()).startswith(_PLANTILLA)
    )


def _color_ok(esperado, real) -> bool:
    if isinstance(esperado, list):
        return real in esperado
    return real == esperado


def evaluar(
    esperado: dict,
    borrador: dict | None,
    pedido,
    textos=(),
    escalados=0,
    casi_repetidas=0,
) -> list[tuple[str, bool, str]]:
    b = borrador or {}
    checks: list[tuple[str, bool, str]] = []

    def check(nombre, ok, detalle=""):
        checks.append((nombre, bool(ok), detalle))

    if "cantidad" in esperado:
        opciones = esperado["cantidad"]
        opciones = opciones if isinstance(opciones, list) else [opciones]
        check("cantidad", b.get("cantidad") in opciones, f"{b.get('cantidad')}")
    if "talla" in esperado:
        check("talla", b.get("talla") == esperado["talla"], f"{b.get('talla')}")
    for i, (corazon, dedos) in enumerate(esperado.get("huellitas", []), 1):
        h = (
            (b.get("huellitas") or [])[i - 1]
            if len(b.get("huellitas") or []) >= i
            else {}
        )
        check(
            f"h{i} corazón", _color_ok(corazon, h.get("corazon")), f"{h.get('corazon')}"
        )
        if isinstance(dedos, list) and len(dedos) == 4:
            ok = h.get("dedos_alternos") == dedos
            real = h.get("dedos_alternos")
        else:
            ok = _color_ok(dedos, h.get("dedos"))
            real = h.get("dedos")
        check(f"h{i} dedos", ok, f"{real}")
    grabado = " | ".join(b.get("grabado") or [])
    for palabra in esperado.get("grabado_contiene", []):
        check(f"grabado «{palabra}»", _plano(palabra) in _plano(grabado), grabado)
    for palabra in esperado.get("grabado_no_contiene", []):
        check(f"grabado SIN «{palabra}»", _plano(palabra) not in _plano(grabado), grabado)
    if "nombre_clienta" in esperado:
        check(
            "nombre clienta",
            _plano(esperado["nombre_clienta"]) in _plano(b.get("nombre_clienta")),
            b.get("nombre_clienta", ""),
        )
    if "ciudad" in esperado:
        check(
            "ciudad",
            _plano(esperado["ciudad"]) == _plano(b.get("ciudad")),
            b.get("ciudad", ""),
        )
    if "sin_grabado" in esperado:
        check("sin grabado", b.get("sin_grabado") == esperado["sin_grabado"], "")
    if esperado.get("pedido") is True:
        check("pedido creado", pedido is not None, getattr(pedido, "codigo", ""))
    if esperado.get("pedido") is False:
        check("NO se crea pedido", pedido is None, getattr(pedido, "codigo", ""))
    if esperado.get("abono") is True:
        check("abono reportado", b.get("abono_reportado"), "")
    if esperado.get("abono") is False:
        check("sin abono reportado", not b.get("abono_reportado"), "")
    if "envio_con_saldo" in esperado:
        check(
            "envío con el saldo" if esperado["envio_con_saldo"] else "envío al recibir",
            bool(b.get("envio_con_saldo")) == esperado["envio_con_saldo"],
            "",
        )
    if "escalado" in esperado:
        check(
            "pasa a Lía" if esperado["escalado"] else "no pasa a Lía",
            bool(escalados) == esperado["escalado"],
            f"{escalados} turnos",
        )
    check("no repite frases (≤1)", casi_repetidas <= 1, f"{casi_repetidas}")
    todo = _plano(" ".join(textos))
    for frase in esperado.get("nunca_dice", []):
        check(f"nunca dice «{frase}»", _plano(frase) not in todo, "")
    return checks


#: Todo lo que un repaso NO puede tocar de verdad. El modelo sí es el real
#: —es lo que se mide—; lo demás va apagado o a una carpeta temporal.
#:
#: El ERP estaba fuera de esta lista y un repaso monta el contenedor con
#: `sqlite`, que es justo cuando el ERP arranca su hilo. El 21/09 corrieron 33
#: repasos y cada uno escribió en la hoja CENTRO DE MANDO del ERP de verdad
#: enlaces a `https://ejemplo.local` (con la llave real del panel), hasta que el
#: bot los corregía a los 10 minutos. Mismo agujero que tuvieron las pruebas
#: con Chatwoot y con el ERP: ver `tests/conftest.py`.
ENTORNO_DEL_REPASO = {
    "REPOSITORY_BACKEND": "sqlite",
    "CHANNEL_BACKEND": "console",  # nada sale por WhatsApp
    "URL_PUBLICA": "https://ejemplo.local",
    "LLM_BACKEND": "claude",
    "CHATWOOT_URL": "",  # nada se copia al Chatwoot de verdad
    "SHEETS_SPREADSHEET_ID": "",  # ni al ERP
    "GOOGLE_SERVICE_ACCOUNT_JSON": "",
    "AVISOS_BACKEND": "ninguno",  # ni se le avisa nada a nadie
}


def repasar(escenario: dict, motor: str, carpeta: Path) -> dict:
    temporal = Path(tempfile.mkdtemp())
    db = temporal / "repaso.db"
    os.environ.update(
        ENTORNO_DEL_REPASO,
        SQLITE_PATH=str(db),
        # El Excel de ventas solo se escribe con el servidor encendido, pero
        # que apunte a la carpeta temporal por si eso cambia algún día.
        VENTAS_EXCEL=str(temporal / "ventas.xlsx"),
        CONVERSACION_MOTOR=motor,
    )
    from app.domain.asesora import repite_lo_dicho
    from app.infra.container import build_container
    from app.infra.settings import Settings

    c = build_container(Settings())
    conv = "wa:573000000000"
    mundo = c.bot._mundo
    mundo.asegurar_cliente(conv)

    lineas = [f"# {escenario['nombre']}  ·  motor={motor}", ""]
    anteriores: list[str] = []
    senales = {
        "repetidas": 0,
        "casi_repetidas": 0,
        "no_entendi": 0,
        "bienvenida_tarde": 0,
        "escalados": 0,
        "vigilante": 0,
        "errores": 0,
        "respaldo": 0,
    }
    costo, ms = 0.0, []
    for n, t in enumerate(escenario["turnos"], 1):
        media = []
        if t.get("foto"):
            media.append({"kind": "image", "descripcion": t["foto"]})
        if t.get("audio"):
            media.append({"kind": "audio", "media_id": "simulado"})
        if t.get("pdf"):
            media.append({"kind": "document", "media_id": "simulado"})
        media = media or None
        inicio = time.perf_counter()
        try:
            # Cómo se llama en WhatsApp. En un chat de verdad SIEMPRE está
            # —Lía lo tiene delante— y el bot lo usa para proponerle el
            # nombre del pedido en vez de pedírselo a ciegas.
            turno = c.bot.ejecutar(
                conv, t.get("texto"), media, escenario.get("nombre_whatsapp", "")
            )
            texto = turno.respuesta.texto_plano.strip()
            traza = turno.respuesta.traza
            resumen = turno.resumen()
            escalar = turno.respuesta.escalar
            costo += float(getattr(turno.registro, "cost_usd", 0) or 0)
        except Exception as exc:  # se cuenta, no se esconde
            texto, traza, resumen, escalar = (
                f"!!! {type(exc).__name__}: {exc}",
                [],
                "",
                False,
            )
            senales["errores"] += 1
        ms.append(int((time.perf_counter() - inicio) * 1000))
        if texto and anteriores and texto == anteriores[-1]:
            senales["repetidas"] += 1
        elif texto and repite_lo_dicho(
            _solo_lo_escrito(texto), [_solo_lo_escrito(a) for a in anteriores[-3:]]
        ):
            senales["casi_repetidas"] += 1
        if "no te entend" in _plano(texto) or "no alcance a entender" in _plano(texto):
            senales["no_entendi"] += 1
        if n > 1 and "bienvenida a lia" in _plano(texto):
            senales["bienvenida_tarde"] += 1
        senales["escalados"] += int(bool(escalar))
        senales["vigilante"] += sum(
            1
            for x in traza
            if "no pasó" in x
            and any(
                s in x
                for s in (
                    "monto no autorizado",
                    "pago confirmado",
                    "cuenta o tel",
                    "dice talla",
                    "por tomado",
                    "mandó las cuentas",
                )
            )
        )
        if not resumen.startswith("asesora") and motor == "asesora":
            senales["respaldo"] += 1
        anteriores.append(texto)
        quien = t.get("texto") or ""
        if t.get("foto"):
            quien += f"  📷 [{t['foto']}]"
        if t.get("audio"):
            quien += "  🎤 [nota de voz]"
        if t.get("pdf"):
            quien += "  📄 [PDF]"
        lineas.append(f"**[{n}] 👤 Clienta:** {quien}")
        lineas.append(f"`{resumen}`")
        lineas.extend(f"> {x}" if x else ">" for x in texto.splitlines())
        for x in traza:
            if "no pasó" in x:
                lineas.append(f"- ⚠️ {x.strip()}")
        lineas.append("")

    ctx = mundo.contexto(conv)
    borrador = ctx.borrador
    pedido_id = (borrador or {}).get("pedido_id")
    pedido = mundo.pedido(pedido_id) if pedido_id else None
    checks = evaluar(
        escenario["esperado"],
        borrador,
        pedido,
        anteriores,
        senales["escalados"],
        senales["casi_repetidas"],
    )
    aciertos = sum(ok for _, ok, _ in checks)
    lineas += ["---", f"## Resultado: {aciertos}/{len(checks)}", ""]
    lineas += [f"- {'✅' if ok else '❌'} {nombre}: {det}" for nombre, ok, det in checks]
    lineas += [
        "",
        f"Señales: {json.dumps(senales, ensure_ascii=False)}",
        f"Costo: USD {costo:.4f} · latencia media {sum(ms) // max(len(ms), 1)} ms",
        f"Notas para Lía: {ctx.revisar}",
    ]
    nombre = "".join(ch if ch.isalnum() else "-" for ch in _plano(escenario["nombre"]))[
        :50
    ]
    (carpeta / f"{nombre}.md").write_text("\n".join(lineas), encoding="utf-8")
    return {
        "nombre": escenario["nombre"],
        "aciertos": aciertos,
        "total": len(checks),
        "cerrada": all(ok for _, ok, _ in checks),
        "senales": senales,
        "costo": round(costo, 4),
        "latencia_ms": sum(ms) // max(len(ms), 1),
        "fallidos": [n for n, ok, _ in checks if not ok],
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Repasa conversaciones reales")
    ap.add_argument("--motor", choices=("asesora", "pipeline"), default="asesora")
    ap.add_argument(
        "--solo", default="", help="solo escenarios cuyo nombre contenga esto"
    )
    ap.add_argument("--escenarios", default=str(MATERIAL / "escenarios"))
    args = ap.parse_args()

    import logging

    from app.infra.consola import preparar_salida

    logging.disable(logging.WARNING)
    preparar_salida()
    archivos = sorted(Path(args.escenarios).glob("*.json"))
    archivos = [a for a in archivos if _plano(args.solo) in _plano(a.stem)]
    if not archivos:
        print("No hay escenarios en", args.escenarios)
        return 1
    carpeta = (
        MATERIAL / "repasos" / f"{datetime.now().astimezone():%Y-%m-%d_%H%M}-{args.motor}"
    )
    carpeta.mkdir(parents=True, exist_ok=True)

    resultados = []
    for archivo in archivos:
        esc = json.loads(archivo.read_text(encoding="utf-8"))
        r = repasar(esc, args.motor, carpeta)
        resultados.append(r)
        marca = "✅" if r["cerrada"] else "❌"
        print(
            f"{marca} {r['aciertos']:>2}/{r['total']:<2} {r['nombre'][:55]:<55} "
            f"USD {r['costo']:.3f}  {r['latencia_ms']} ms  {r['senales']}"
        )
        if r["fallidos"]:
            print("      falló:", ", ".join(r["fallidos"]))

    aciertos = sum(r["aciertos"] for r in resultados)
    total = sum(r["total"] for r in resultados)
    cerradas = sum(r["cerrada"] for r in resultados)
    print(
        f"\nTOTAL {aciertos}/{total} comprobaciones · {cerradas}/{len(resultados)} "
        f"conversaciones perfectas · USD {sum(r['costo'] for r in resultados):.3f}"
    )
    print("Transcripciones:", carpeta)
    (carpeta / "resultados.json").write_text(
        json.dumps(resultados, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
