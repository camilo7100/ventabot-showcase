#!/usr/bin/env python3
"""El banco de plantillas por situación: estado, limpieza y sincronización (22/10).

    python scripts/banco_de_plantillas.py estado
    python scripts/banco_de_plantillas.py limpiar            # solo muestra el plan
    python scripts/banco_de_plantillas.py limpiar --borrar   # guarda la lista y borra
    python scripts/banco_de_plantillas.py sincronizar RUTA   # copia el banco de marketing

En el servidor: `sudo docker compose exec -T ventabot python
scripts/banco_de_plantillas.py estado`.

`estado`: por grupo, cuál se usaría hoy (la primera aprobada del orden) y cómo va
cada una. No toca nada.

`limpiar`: cuando un grupo ya tiene una plantilla APROBADA, las demás de ese grupo
sobran y ocupan cupo (el tope de Meta es 250 con el negocio sin verificar). Se queda
la primera aprobada del orden; se borran las otras, SALVO:
  · las que ya existían y están en uso (`PROTEGIDAS`, y las marcadas «existente»),
  · las que otro grupo todavía necesita (está en el orden de un grupo sin aprobada),
  · las de grupos bloqueados por una decisión pendiente,
  · cualquiera que no sea del banco (nunca se toca lo que no es suyo).
Antes de borrar se guarda la lista COMPLETA (con el texto, para poder volver a
crearlas) en `estado/banco/borradas-AAAAMMDD-HHMM.json`.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

from app.domain.banco_de_plantillas import Banco
from app.infra.settings import get_settings

#: Lo que está en uso o es de otra cosa: NUNCA se borra desde aquí.
PROTEGIDAS = frozenset(
    {
        "anillo_con_abono",
        "asi_quedaria",
        "cupo_en_el_taller",
        "ultimo_recordatorio",
        "ultimo_navidad",
        "retomar_diseno",
        "hello_world",
    }
)
PREFIJOS_PROTEGIDOS = ("pedido_", "retomar_conversacion", "asesora_te_atiende")


def protegida(nombre: str) -> bool:
    return nombre in PROTEGIDAS or nombre.startswith(PREFIJOS_PROTEGIDOS)


def plan_de_limpieza(banco: Banco, estados: dict[str, str]) -> dict:
    """Qué se queda y qué se borra. Puro: se prueba sin Meta."""
    quedan: dict[str, str] = {}  # nombre -> grupo que lo usa
    candidatas: dict[str, str] = {}  # nombre -> grupo del que sobra
    sin_resolver: set[str] = set()
    for g in banco.grupos.values():
        if g.bloqueada:
            sin_resolver |= set(g.orden)  # no se toca nada de lo que espera una decisión
            continue
        primera = next((n for n in g.orden if estados.get(n) == "APPROVED"), None)
        if primera is None:
            sin_resolver |= set(g.orden)
            continue
        quedan[primera] = g.id
        for n in g.orden:
            if n != primera:
                candidatas.setdefault(n, g.id)
    existentes = {n for g in banco.grupos.values() for n in g.existentes}
    borrar, motivos = [], {}
    for nombre, grupo in sorted(candidatas.items()):
        if nombre not in banco.plantillas or nombre not in estados:
            continue  # no es del banco, o ni existe en Meta: no hay nada que borrar
        if nombre in quedan:
            motivos[nombre] = f"la usa el grupo {quedan[nombre]}"
        elif protegida(nombre) or nombre in existentes:
            motivos[nombre] = "en uso: protegida"
        elif nombre in sin_resolver:
            motivos[nombre] = "la espera otro grupo todavía sin aprobada"
        else:
            borrar.append({"nombre": nombre, "grupo": grupo, "estado": estados[nombre]})
    return {"quedan": quedan, "borrar": borrar, "se_salvaron": motivos}


def _contenedor():
    from app.infra.container import build_container

    return build_container()


def estado() -> int:
    c = _contenedor()
    banco = c.banco_de_plantillas()
    if banco is None:
        print("No pude leer el banco (data/plantillas/banco.json).")
        return 1
    estados = c.estados_de_las_plantillas()
    resueltos = 0
    for g in banco.grupos.values():
        primera = next((n for n in g.orden if estados.get(n) == "APPROVED"), None)
        resueltos += primera is not None
        marca = "🔒" if g.bloqueada else ("✔" if primera else "·")
        detalle = ", ".join(f"{n}={estados.get(n, '—')}" for n in g.orden)
        quien = primera or "ninguna aún"
        print(f"{marca} {g.id:6} {g.situacion[:46]:46} → {quien}  [{detalle}]")
    print(
        f"\n{resueltos} de {len(banco.grupos)} grupos con alguna aprobada · "
        f"{len(estados)} plantillas en Meta (tope 250)"
    )
    return 0


def limpiar(borrar: bool) -> int:
    c = _contenedor()
    banco = c.banco_de_plantillas()
    if banco is None:
        print("No pude leer el banco.")
        return 1
    estados = c.estados_de_las_plantillas()
    plan = plan_de_limpieza(banco, estados)
    print(f"Quedan {len(plan['quedan'])} (la primera aprobada de cada grupo resuelto).")
    print(f"Se salvan {len(plan['se_salvaron'])} que sobrarían pero se necesitan.")
    print(f"Se borrarían {len(plan['borrar'])}:")
    for b in plan["borrar"]:
        print(f"  - {b['nombre']}  ({b['estado']}, grupo {b['grupo']})")
    if not borrar:
        print("\n(Solo el plan. Con --borrar se guarda la lista y se borra.)")
        return 0
    if not plan["borrar"]:
        return 0
    destino = Path(c.settings.sqlite_path).parent / "banco"
    destino.mkdir(parents=True, exist_ok=True)
    archivo = destino / f"borradas-{datetime.now(UTC):%Y%m%d-%H%M}.json"
    archivo.write_text(
        json.dumps(
            [
                {
                    **b,
                    "categoria": banco.plantillas[b["nombre"]].categoria,
                    "cuerpo": banco.plantillas[b["nombre"]].cuerpo,
                    "botones": list(banco.plantillas[b["nombre"]].botones),
                    "encabezado": banco.plantillas[b["nombre"]].encabezado,
                    "variables": list(banco.plantillas[b["nombre"]].variables),
                }
                for b in plan["borrar"]
            ],
            ensure_ascii=False,
            indent=1,
        ),
        encoding="utf-8",
    )
    print(f"\nLista guardada ANTES de borrar: {archivo}")
    waba = c.settings.wa_business_account_id
    mal = 0
    for b in plan["borrar"]:
        try:
            c.whatsapp.borrar_plantilla(waba, b["nombre"])
            print(f"  borrada {b['nombre']}")
        except Exception as exc:
            mal += 1
            print(f"  NO se pudo borrar {b['nombre']}: {exc}")
        time.sleep(0.5)
    print(f"\n{len(plan['borrar']) - mal} borradas, {mal} con error.")
    return 1 if mal else 0


def sincronizar(ruta: str) -> int:
    """Copia el banco de marketing-lia a `data/plantillas/banco.json` (solo los
    campos que usa el selector). No toca `activos.json`."""
    d = json.loads(Path(ruta).read_text(encoding="utf-8"))
    campos = (
        "nombre",
        "categoria",
        "cuerpo",
        "variables",
        "ejemplos",
        "botones",
        "encabezado",
        "grupo",
        "ola",
    )
    salida = {
        "fuente": "marketing-lia/guias/plantillas-para-meta.json",
        "generado": d.get("generado"),
        "plantillas": [{k: t.get(k) for k in campos} for t in d["plantillas"]],
        "grupos": [
            {k: g.get(k) for k in ("grupo", "situacion", "ventana", "bloqueada", "orden")}
            for g in d["grupos"]
        ],
    }
    destino = get_settings().banco_plantillas_json
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text(
        json.dumps(salida, ensure_ascii=False, indent=1) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    cuantas, cuantos = len(salida["plantillas"]), len(salida["grupos"])
    print(f"{cuantas} plantillas, {cuantos} grupos → {destino}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("estado")
    lim = sub.add_parser("limpiar")
    lim.add_argument("--borrar", action="store_true")
    sin = sub.add_parser("sincronizar")
    sin.add_argument("ruta")
    args = ap.parse_args()
    if args.cmd == "estado":
        return estado()
    if args.cmd == "limpiar":
        return limpiar(args.borrar)
    return sincronizar(args.ruta)


if __name__ == "__main__":
    raise SystemExit(main())
