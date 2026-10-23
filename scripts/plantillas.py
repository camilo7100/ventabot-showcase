#!/usr/bin/env python3
"""Las plantillas de WhatsApp: qué pegar en Meta y si ya las aprobaron.

    vb plantillas            <- te dice cómo va cada una
    vb plantillas --crear    <- imprime el texto exacto para pegar en el panel

POR QUÉ HACEN FALTA
===================
WhatsApp solo deja escribir texto libre dentro de las 24 h siguientes al
último mensaje de la clienta. Después exige una PLANTILLA que Meta haya
revisado a mano.

La fabricación son 10 a 15 días. Cuando el anillo queda listo, esa ventana
lleva días cerrada — justo cuando hay que mandar el mensaje que más importa:
el cobro del saldo. Sin plantilla, ese cobro espera a que la clienta escriba
primero, y puede no escribir nunca.

Con plantilla, sale en el segundo en que Lía toca el botón.

MIENTRAS TANTO NO SE ROMPE NADA
===============================
Si la plantilla no existe o Meta no la ha aprobado, el mensaje se queda en la
outbox y sale solo en cuanto la clienta escriba. No se pierde.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

import httpx

from app.domain.guion import (
    CATEGORIA_META,
    CUERPOS_META,
    IDIOMA_META,
    PLANTILLAS_META,
)
from app.infra.consola import preparar_salida
from app.infra.settings import get_settings

_C = preparar_salida()
V, R, A, G, C, RST = (_C.ok, _C.error, _C.aviso, _C.tenue, _C.titulo, _C.fin)
OK, NO, ESPERA = f"{V}✔{RST}", f"{R}✘{RST}", f"{A}○{RST}"

API = "https://graph.facebook.com/v21.0"

#: Cómo traduce Meta sus propios estados. El crudo ("APPROVED") no dice qué
#: hacer con él.
ESTADOS = {
    "APPROVED": (OK, "aprobada · ya se usa sola"),
    "PENDING": (ESPERA, "en revisión · Meta suele tardar de 1 h a 2 días"),
    "IN_APPEAL": (ESPERA, "apelada · esperando respuesta de Meta"),
    "REJECTED": (NO, "RECHAZADA · mira el motivo en el panel y vuelve a enviarla"),
    "PAUSED": (NO, "pausada por baja calidad · las clientas la reportaron"),
    "DISABLED": (NO, "desactivada por Meta"),
}


def como_pegarla(nombre: str) -> str:
    cuerpo = CUERPOS_META[nombre]
    huecos = sum(1 for i in (1, 2, 3, 4) if f"{{{{{i}}}}}" in cuerpo)
    ejemplos = {"1": "PED-2026-0417", "2": "$140.000"}
    lineas = [
        f"{C}{'─' * 72}{RST}",
        f"  {V}{nombre}{RST}",
        f"{C}{'─' * 72}{RST}",
        f"  Categoria : {CATEGORIA_META}",
        f"  Idioma    : {IDIOMA_META} (Español)",
        "  Encabezado: ninguno",
        "  Pie       : ninguno",
        "  Botones   : ninguno",
        "",
        f"  {A}Cuerpo — copia esto TAL CUAL:{RST}",
        "",
    ]
    lineas += [f"      {linea}" for linea in cuerpo.split("\n")]
    if huecos:
        lineas += ["", f"  {A}Ejemplos que te va a pedir Meta:{RST}"]
        lineas += [
            f"      {{{{{i}}}}}  ->  {ejemplos[str(i)]}" for i in range(1, huecos + 1)
        ]
    return "\n".join(lineas)


def estado_en_meta(token: str, waba: str) -> dict[str, dict] | None:
    """Lo que Meta dice de cada plantilla. None si no se pudo preguntar."""
    try:
        r = httpx.get(
            f"{API}/{waba}/message_templates",
            headers={"Authorization": f"Bearer {token}"},
            params={
                "limit": 100,
                "fields": "name,status,language,category,rejected_reason",
            },
            timeout=30,
        )
        if r.status_code != 200:
            return None
        return {p["name"]: p for p in r.json().get("data", [])}
    except Exception:
        return None


def bloqueo_de_meta(token: str, telefono: str) -> list[str] | None:
    """Lo que impide que salgan, aunque estén aprobadas (None: no se pudo saber)."""
    from app.domain.salud_meta import leer_salud

    try:
        r = httpx.get(
            f"{API}/{telefono}",
            params={"fields": "health_status"},
            headers={"Authorization": f"Bearer {token}"},
            timeout=15,
        )
        r.raise_for_status()
    except httpx.HTTPError:
        return None
    salud = leer_salud(r.json().get("health_status"))
    return salud.problemas if salud.estado == "BLOCKED" else []


def main() -> int:
    ap = argparse.ArgumentParser(description="Plantillas de WhatsApp")
    ap.add_argument(
        "--crear",
        action="store_true",
        help="imprime el texto exacto para pegar en el panel de Meta",
    )
    args = ap.parse_args()
    s = get_settings()

    print(f"\n{C}{'=' * 72}\n  PLANTILLAS DE WHATSAPP\n{'=' * 72}{RST}")

    if args.crear:
        print(f"""
  Meta exige plantillas aprobadas para escribirle a alguien que lleva más
  de 24 h sin escribirte. Tú las creas UNA vez y ellos las revisan.

  {G}DÓNDE:{RST}  https://business.facebook.com/wa/manage/message-templates/
          (o: panel de Meta -> WhatsApp -> Administrador -> Plantillas)

  {G}CÓMO:{RST}   Botón «Crear plantilla». Por cada una de abajo:
            1. Categoría: {CATEGORIA_META}   {A}(NO Marketing: se aprueba peor
               y cuesta más){RST}
            2. Nombre: cópialo EXACTO. Meta solo acepta minúsculas,
               números y guion bajo.
            3. Idioma: Español
            4. Pega el cuerpo tal cual, con las llaves {{{{1}}}} incluidas
            5. Rellena los ejemplos que te pide
            6. Enviar

  {A}Meta tarda entre una hora y dos días.{RST} Mientras tanto no se rompe
  nada: los avisos se quedan encolados y salen cuando la clienta escriba.
""")
        for nombre in CUERPOS_META:
            print(como_pegarla(nombre))
            print()
        print(f"  {G}Cuando las envíes, comprueba cómo van con:  vb plantillas{RST}\n")
        return 0

    # ---- estado real ----
    if not s.wa_access_token or not s.wa_business_account_id:
        print(f"\n  {NO} Faltan WA_ACCESS_TOKEN o WA_BUSINESS_ACCOUNT_ID en tu .env")
        print(f"      {A}→{RST} Para ver qué hay que crear:  vb plantillas --crear\n")
        return 1

    print(f"\n{G}[1]{RST} Las que el bot necesita")
    en_meta = estado_en_meta(s.wa_access_token, s.wa_business_account_id)
    if en_meta is None:
        print(f"  {NO} No pude preguntarle a Meta (¿token caducado? prueba: vb token)\n")
        return 1

    faltan, aprobadas = [], 0
    for estado, (nombre, campos) in PLANTILLAS_META.items():
        info = en_meta.get(nombre)
        if info is None:
            print(f"  {NO} {nombre}")
            print(f"      no existe en Meta · se usa al mover a {estado}")
            faltan.append(nombre)
            continue
        marca, explicacion = ESTADOS.get(info["status"], (ESPERA, info["status"].lower()))
        print(f"  {marca} {nombre}")
        print(f"      {explicacion} · {len(campos)} dato(s): {', '.join(campos)}")
        motivo = info.get("rejected_reason")
        if motivo and motivo != "NONE":
            print(f"      {R}motivo del rechazo: {motivo}{RST}")
        if info["status"] == "APPROVED":
            aprobadas += 1

    otras = set(en_meta) - {n for n, _ in PLANTILLAS_META.values()}
    if otras:
        print(f"\n{G}[2]{RST} Otras plantillas que tienes en Meta (el bot no las usa)")
        for nombre in sorted(otras):
            print(f"  {G}·{RST} {nombre}")

    print(f"\n{C}{'=' * 72}\n  VEREDICTO\n{'=' * 72}{RST}")
    total = len(PLANTILLAS_META)
    bloqueo = bloqueo_de_meta(s.wa_access_token, s.wa_phone_number_id)
    if aprobadas == total and bloqueo:
        print(f"  {R}Las {total} están aprobadas, pero Meta NO las deja salir:{RST}")
        for problema in bloqueo:
            print(f"      {A}→{RST} {problema}")
        print("  Mientras tanto esperan en la cola y salen cuando la clienta escriba.\n")
        return 1
    if aprobadas == total:
        print(f"  {V}Las {total} están aprobadas.{RST}")
        print("  El bot puede escribirle a una clienta aunque lleve semanas")
        print("  sin hablar. El cobro del saldo sale en cuanto Lía toque el botón.\n")
        return 0

    print(f"  {A}{aprobadas} de {total} aprobadas.{RST}")
    if faltan:
        print(f"\n  Sin crear todavía: {', '.join(faltan)}")
        print(f"      {G}vb plantillas --crear{RST}  te da el texto exacto")
    print("\n  Mientras tanto NO se pierde nada: los avisos se quedan en la")
    print("  cola y salen en cuanto la clienta escriba. Lo que se pierde es la")
    print("  inmediatez, que en el cobro del saldo es justo lo que vale.\n")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
