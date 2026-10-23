#!/usr/bin/env python3
"""CRITERIO DE ACEPTACIÓN DE LA FASE 0.

    "Le mandas 'quiero 3 camisetas rojas' a un script y te devuelve
     Intencion(tipo='COTIZAR', cantidad=3) validado, diez veces seguidas
     con el mismo resultado."

Uso:
    python scripts/f0_determinismo.py                 # contra Ollama (por defecto)
    LLM_BACKEND=fake python scripts/f0_determinismo.py  # smoke test del arnés
    python scripts/f0_determinismo.py --n 20 --verbose

Qué comprueba, en orden, deteniéndose en el primer fallo con un diagnóstico útil:

  1. El servidor de Ollama responde.
  2. El modelo configurado está descargado.
  3. EL CONTEXTO EFECTIVO ES SUFICIENTE.  ← la trampa nº1
     Con menos de 24 GB de VRAM, Ollama asigna 4K por defecto aunque el modelo
     declare 128K. El prompt + el schema desbordan EN SILENCIO y el modelo
     "olvida" las instrucciones. No da error: simplemente responde mal.
  4. La salida cumple el JSON Schema (constrained decoding real).
  5. La intención y la cantidad son las correctas.
  6. N ejecuciones seguidas devuelven EXACTAMENTE lo mismo.

Sale con código 0 si todo pasa, 1 si algo falla.
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.domain.models import Intencion, Intent
from app.graph.nodes.nlu import cargar_prompt
from app.infra.consola import preparar_salida
from app.infra.settings import get_settings

# UTF-8 y color solo si hay terminal: sin esto, redirigir la salida a un
# archivo revienta en Windows al imprimir un ✔ (cp1252 no lo soporta).
_C = preparar_salida()
V, R, A, G, C, RST = (_C.ok, _C.error, _C.aviso, _C.tenue, _C.titulo, _C.fin)
OK, FAIL, WARN = f"{V}✔{RST}", f"{R}✘{RST}", f"{A}!{RST}"

FRASE = "quiero 3 camisetas rojas"
ESPERADO_TIPO = Intent.COTIZAR
ESPERADO_CANTIDAD = 3

#: Contexto mínimo aceptable. Por debajo de esto el prompt + el schema no caben
#: con holgura y empiezan los fallos silenciosos.
#: 8192 es el piso: el prompt del NLU con el catálogo ronda los 1.500 tokens,
#: el JSON Schema otros 700, y hace falta margen para el historial.
#: El default recomendado sigue siendo 16000 (ver .env.example).
NUM_CTX_MINIMO = 8192


def titulo(t: str) -> None:
    print(f"\n{C}{'=' * 72}\n  {t}\n{'=' * 72}{RST}")


def paso(n: int, texto: str) -> None:
    print(f"\n{G}[{n}]{RST} {texto}")


# ---------------------------------------------------------------------------


def comprobar_servidor(host: str) -> dict | None:
    import httpx

    try:
        r = httpx.get(f"{host}/api/tags", timeout=5)
        r.raise_for_status()
        return r.json()
    except Exception as exc:
        print(f"  {FAIL} No responde en {host}")
        print(f"      {exc}")
        print(f"\n  {A}Windows:{RST} ¿está el icono de Ollama en la bandeja del sistema")
        print("      (abajo a la derecha, junto al reloj)? Si no, abre Ollama")
        print("      desde el menú Inicio.")
        print(f"  {A}macOS / Linux:{RST} déjalo corriendo en otra terminal con")
        print("      OLLAMA_CONTEXT_LENGTH=16000 OLLAMA_FLASH_ATTENTION=1 ollama serve")
        return None


def comprobar_modelo(tags: dict, modelo: str) -> bool:
    disponibles = [m["name"] for m in tags.get("models", [])]
    # Ollama reporta "granite4.1:8b"; aceptamos también el nombre sin tag.
    if modelo in disponibles or any(
        d.split(":")[0] == modelo.split(":")[0] for d in disponibles
    ):
        print(f"  {OK} Modelo disponible: {modelo}")
        return True
    print(f"  {FAIL} El modelo {modelo!r} no está descargado.")
    print(f"      Descargados: {', '.join(disponibles) or '(ninguno)'}")
    print(f"\n  {A}Descárgalo con:{RST}")
    print(f"      ollama pull {modelo}")
    return False


def comprobar_contexto(host: str, modelo: str, num_ctx: int) -> bool:
    """Hace una llamada mínima y luego lee /api/ps para ver el contexto REAL."""
    import httpx

    try:
        httpx.post(
            f"{host}/api/chat",
            json={
                "model": modelo,
                "messages": [{"role": "user", "content": "ok"}],
                "stream": False,
                "options": {"num_ctx": num_ctx},
            },
            timeout=180,
        ).raise_for_status()
        ps = httpx.get(f"{host}/api/ps", timeout=10).json()
    except Exception as exc:
        print(f"  {WARN} No pude leer el contexto efectivo: {exc}")
        return True  # no bloqueamos por esto

    cargados = ps.get("models", [])
    if not cargados:
        print(f"  {WARN} El modelo no aparece cargado en /api/ps")
        return True

    efectivo = cargados[0].get("context_length") or cargados[0].get("num_ctx")
    if efectivo is None:
        print(f"  {WARN} Ollama no reportó context_length (versión antigua)")
        return True

    if efectivo < NUM_CTX_MINIMO:
        print(f"  {FAIL} Contexto efectivo: {efectivo} tokens (mínimo {NUM_CTX_MINIMO})")
        print(f"\n  {A}Esta es LA trampa nº1 de Ollama.{RST} Con <24 GB de VRAM asigna")
        print("      4K por defecto aunque el modelo declare 128K. El prompt")
        print("      desborda EN SILENCIO y el modelo ignora las instrucciones.")
        print(f"\n  {A}Windows:{RST} abre Anaconda Prompt y corre")
        print("      setx OLLAMA_CONTEXT_LENGTH 16000")
        print("      luego cierra Ollama desde la bandeja del sistema")
        print("      y vuelve a abrirlo.")
        print(f"  {A}macOS / Linux:{RST}")
        print("      OLLAMA_CONTEXT_LENGTH=16000 OLLAMA_FLASH_ATTENTION=1 ollama serve")
        return False

    print(f"  {OK} Contexto efectivo: {efectivo} tokens")
    return True


# ---------------------------------------------------------------------------


def construir_llm():
    s = get_settings()
    if s.llm_backend == "fake":
        from app.adapters.llm.ollama_client import FakeLLM

        print(f"  {WARN} LLM_BACKEND=fake — esto valida el ARNÉS, no el modelo.")
        print("      Para validar de verdad la Fase 0: LLM_BACKEND=ollama")
        return FakeLLM(), True
    from app.adapters.llm.ollama_client import OllamaLLM

    return OllamaLLM(model=s.ollama_model, host=s.ollama_host), False


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=10, help="repeticiones (default 10)")
    ap.add_argument("--frase", default=FRASE)
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    s = get_settings()
    titulo("FASE 0 — criterio de aceptación: determinismo del NLU")
    print(f"  backend : {s.llm_backend}")
    print(f"  modelo  : {s.ollama_model}")
    print(f"  host    : {s.ollama_host}")
    print(f"  frase   : {args.frase!r}")
    print(f"  esperado: tipo={ESPERADO_TIPO.value}  cantidad={ESPERADO_CANTIDAD}")

    llm, es_fake = construir_llm()

    if not es_fake:
        paso(1, "Servidor de Ollama")
        tags = comprobar_servidor(s.ollama_host)
        if tags is None:
            return 1
        print(f"  {OK} Responde en {s.ollama_host}")

        paso(2, "Modelo descargado")
        if not comprobar_modelo(tags, s.ollama_model):
            return 1

        paso(3, "Contexto efectivo (la trampa nº1)")
        if not comprobar_contexto(s.ollama_host, s.ollama_model, s.ollama_num_ctx):
            return 1

    # --- prompt del sistema, igual que en el nodo NLU real ---
    from app.infra.container import cargar_catalogo

    catalogo = cargar_catalogo()
    prompt = cargar_prompt().replace(
        "{{CATALOGO}}",
        "\n".join(f"- {p.sku}: {p.nombre} ({p.precio_cop} COP)" for p in catalogo),
    )

    paso(4, f"{args.n} ejecuciones idénticas")
    resultados: list[str] = []
    latencias: list[float] = []
    fallos: list[str] = []

    for i in range(1, args.n + 1):
        t0 = time.perf_counter()
        try:
            r = llm.extract(prompt, args.frase, Intencion)
            dt = time.perf_counter() - t0
            latencias.append(dt)
            firma = json.dumps(
                r.model_dump(mode="json"), sort_keys=True, ensure_ascii=False
            )
            resultados.append(firma)
            marca = OK if firma == resultados[0] else FAIL
            extra = f"  {G}{firma}{RST}" if args.verbose else ""
            print(
                f"   {marca} {i:2}/{args.n}  {dt * 1000:7.0f} ms  "
                f"tipo={r.tipo.value:<10} cantidad={r.cantidad}{extra}"
            )
        except Exception as exc:
            latencias.append(time.perf_counter() - t0)
            fallos.append(f"iteración {i}: {type(exc).__name__}: {exc}")
            print(f"   {FAIL} {i:2}/{args.n}  EXCEPCIÓN: {type(exc).__name__}: {exc}")

    # --- veredicto ---
    titulo("VEREDICTO")

    if fallos:
        print(f"  {FAIL} {len(fallos)} ejecución(es) lanzaron excepción:")
        for f in fallos[:3]:
            print(f"      {f}")
        return 1

    unicos = Counter(resultados)
    estable = len(unicos) == 1
    primero = json.loads(resultados[0])
    tipo_ok = primero["tipo"] == ESPERADO_TIPO.value
    cant_ok = primero.get("cantidad") == ESPERADO_CANTIDAD

    print(
        f"  {OK if estable else FAIL} Estabilidad: {len(unicos)} resultado(s) "
        f"distinto(s) en {args.n} ejecuciones"
    )
    if not estable:
        for firma, veces in unicos.most_common():
            print(f"      {veces:2}x  {firma}")
    print(
        f"  {OK if tipo_ok else FAIL} Intención: {primero['tipo']} "
        f"(esperado {ESPERADO_TIPO.value})"
    )
    print(
        f"  {OK if cant_ok else FAIL} Cantidad: {primero.get('cantidad')} "
        f"(esperado {ESPERADO_CANTIDAD})"
    )
    print(f"  {OK} Schema Pydantic: validado en las {args.n} ejecuciones")

    if latencias:
        print(
            f"\n  latencia: mediana {statistics.median(latencias) * 1000:.0f} ms · "
            f"p95 {sorted(latencias)[int(len(latencias) * 0.95) - 1] * 1000:.0f} ms · "
            f"máx {max(latencias) * 1000:.0f} ms"
        )

    todo_ok = estable and tipo_ok and cant_ok
    print()
    if todo_ok and es_fake:
        print(f"  {A}ARNÉS OK, pero corriste con FakeLLM.{RST}")
        print("  La Fase 0 NO está cerrada hasta que esto pase con LLM_BACKEND=ollama.")
        return 0
    if todo_ok:
        print(f"  {V}✔ FASE 0 SUPERADA — el NLU es determinista con este modelo.{RST}")
        return 0
    print(f"  {R}✘ FASE 0 NO SUPERADA.{RST}")
    if not estable:
        print("    · Revisa temperature=0, seed y top_k=1 en OPCIONES_DETERMINISTAS")
        print("    · Baja OLLAMA_NUM_PARALLEL a 1")
    if not tipo_ok or not cant_ok:
        print(
            "    · Ajusta app/prompts/nlu_v1.txt (añade el caso que falló a los ejemplos)"
        )
        print(
            f"    · O prueba otro modelo: OLLAMA_MODEL=qwen3:8b "
            f"(actual: {s.ollama_model})"
        )
    return 1


if __name__ == "__main__":
    os.environ.setdefault("LLM_BACKEND", "ollama")
    raise SystemExit(main())
