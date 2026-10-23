#!/usr/bin/env python3
"""Mide si el modelo entiende. Con un número, no con una impresión.

    vb golden                 <- con el modelo de tu .env
    vb golden --solo-python   <- SIN modelo: la línea base honesta
    vb golden --fallos        <- solo lo que falló, para leerlo entero

════════════════════════════════════════════════════════════════════════════
QUÉ MIDE, Y POR QUÉ ESO Y NO OTRA COSA
════════════════════════════════════════════════════════════════════════════
La métrica que manda NO es «acertó la etiqueta». Es «¿el sistema habría hecho
lo correcto?».

Dos interpretaciones distintas pueden llevar a la misma acción: si el modelo
dice CONSULTAR·PRODUCTO·PRECIO y la etiqueta decía CONSULTAR·PRODUCTO·NINGUNO,
las dos terminan en MOSTRAR_PRODUCTO y la clienta recibe exactamente lo mismo.
Contar eso como fallo castigaría al modelo por algo que no le importa a nadie.

Por eso el titular es ACCIÓN. Las etiquetas sueltas también se miden, pero
como diagnóstico: dicen DÓNDE falla, no si sirve.

════════════════════════════════════════════════════════════════════════════
LA LÍNEA BASE
════════════════════════════════════════════════════════════════════════════
`--solo-python` corre el dataset con los atajos y los parsers deterministas, y
el modelo apagado. Ese número es el suelo. Si el modelo no le gana claramente,
no está aportando nada y lo estás pagando en latencia — o en dinero, cuando
sea hospedado.

Es la comparación que casi nadie hace y la única que responde «¿me sirve este
modelo?» sin discutir.
"""

from __future__ import annotations

import argparse
import csv
import logging
import statistics
import sys
import time
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

from app.domain.acciones import CRITICAS, planificar
from app.domain.contexto import ContextoConversacional
from app.domain.interpretacion import (
    Acto,
    Atributo,
    Entidad,
    Interpretacion,
    TipoReferencia,
)
from app.infra.consola import preparar_salida
from app.infra.settings import get_settings

_C = preparar_salida()
V, R, A, G, C, RST = (_C.ok, _C.error, _C.aviso, _C.tenue, _C.titulo, _C.fin)
OK, NO = f"{V}✔{RST}", f"{R}✘{RST}"

DATASET = RAIZ / "tests" / "golden" / "interpretacion.csv"

#: Por debajo de esto el modelo no sirve para producción: uno de cada diez
#: mensajes acaba en la acción equivocada.
MINIMO_ACCION = 0.90
#: En lo que cuesta dinero el listón es más alto. Confundir «ya pagué» con
#: «confírmalo» no es un fallo del 5%: es un pedido cobrado mal.
MINIMO_CRITICO = 0.95


@dataclass
class Caso:
    mensaje: str
    acto: str
    entidad: str
    atributo: str
    ref_tipo: str
    ref_pos: str
    huellitas: str
    talla: str
    nota: str = ""

    def esperado(self) -> Interpretacion:
        from app.domain.interpretacion import DatosSueltos, Referencia

        return Interpretacion(
            acto=Acto(self.acto),
            entidad=Entidad(self.entidad),
            atributo=Atributo(self.atributo),
            referencia=Referencia(
                tipo=TipoReferencia(self.ref_tipo or "NINGUNA"),
                posicion=int(self.ref_pos) if self.ref_pos else None,
            ),
            datos=DatosSueltos(
                huellitas=int(self.huellitas) if self.huellitas else None,
                talla=float(self.talla) if self.talla else None,
            ),
        )


@dataclass
class Marcador:
    total: int = 0
    aciertos: Counter = field(default_factory=Counter)
    fallos: list = field(default_factory=list)
    tiempos: list[float] = field(default_factory=list)
    criticos: int = 0
    criticos_ok: int = 0

    def pct(self, campo: str) -> float:
        return self.aciertos[campo] / self.total if self.total else 0.0


def cargar() -> list[Caso]:
    with DATASET.open(encoding="utf-8") as fh:
        return [Caso(**fila) for fila in csv.DictReader(fh)]


def accion_de(i: Interpretacion):
    return planificar(i.acto, i.entidad, i.atributo, trae_datos=i.datos.hay_algo())


def comparar(esperado: Interpretacion, obtenido: Interpretacion) -> dict[str, bool]:
    ref_e, ref_o = esperado.referencia, obtenido.referencia
    return {
        "accion": accion_de(esperado) is accion_de(obtenido),
        "acto": esperado.acto is obtenido.acto,
        "entidad": esperado.entidad is obtenido.entidad,
        "atributo": esperado.atributo is obtenido.atributo,
        "referencia": ref_e.tipo is ref_o.tipo and ref_e.posicion == ref_o.posicion,
        "datos": (
            esperado.datos.huellitas == obtenido.datos.huellitas
            and esperado.datos.talla == obtenido.datos.talla
        ),
    }


def construir_interprete(solo_python: bool):
    from app.adapters.repositories.csv_files import cargar_catalogo_csv
    from app.conversacion.interprete import Interprete

    s = get_settings()
    catalogo = "\n".join(
        f"- {p.sku}: {p.nombre} ({p.precio_cop} COP, {p.huellitas} huellitas)"
        for p in cargar_catalogo_csv(s.catalogo_csv)
    )
    prompt = (RAIZ / "app" / "prompts" / "interpretacion_v1.txt").read_text(
        encoding="utf-8"
    )

    if solo_python:

        class SinModelo:
            """Siempre falla. Así solo puntúan los atajos y los parsers."""

            def extract(self, *a, **k):
                raise RuntimeError("modelo apagado a propósito")

        return Interprete(SinModelo(), prompt, catalogo), "solo-python"

    from app.adapters.llm.ollama_client import FakeLLM, OllamaLLM

    if s.llm_backend == "claude" and s.anthropic_api_key:
        from app.adapters.llm.anthropic_client import ClaudeLLM

        # Cuesta dinero: ~107 llamadas, unos USD 0,08 con Haiku y la caché.
        return (
            Interprete(
                ClaudeLLM(s.llm_basico_model, s.anthropic_api_key), prompt, catalogo
            ),
            f"claude:{s.llm_basico_model}",
        )
    if s.llm_backend == "ollama":
        return (
            Interprete(
                OllamaLLM(model=s.ollama_model, host=s.ollama_host), prompt, catalogo
            ),
            f"ollama:{s.ollama_model}",
        )
    return Interprete(FakeLLM(), prompt, catalogo), "fake"


def main() -> int:
    ap = argparse.ArgumentParser(description="Mide la interpretación del modelo")
    ap.add_argument(
        "--solo-python",
        action="store_true",
        help="sin modelo: la línea base contra la que compararlo",
    )
    ap.add_argument("--fallos", action="store_true", help="lista todos los fallos")
    ap.add_argument("--limite", type=int, default=0, help="solo los primeros N")
    args = ap.parse_args()

    if args.solo_python:
        # El modelo está apagado a propósito: avisar de ello 107 veces no es
        # información, es ruido que tapa el resultado.
        logging.getLogger("ventabot.interprete").setLevel(logging.CRITICAL)

    casos = cargar()
    if args.limite:
        casos = casos[: args.limite]
    interprete, quien = construir_interprete(args.solo_python)
    vacio = ContextoConversacional(conversation_id="golden")

    print(f"\n{C}{'=' * 74}\n  GOLDEN DATASET · {quien}\n{'=' * 74}{RST}")
    print(f"  {len(casos)} mensajes reales, etiquetados a mano\n")

    m = Marcador(total=len(casos))
    for n, caso in enumerate(casos, start=1):
        esperado = caso.esperado()
        arranque = time.perf_counter()
        try:
            obtenido = interprete.interpretar(caso.mensaje, None, vacio)
        except Exception as exc:
            obtenido = Interpretacion(acto=Acto.OTRO)
            caso.nota = f"{caso.nota} [error: {exc}]".strip()
        m.tiempos.append((time.perf_counter() - arranque) * 1000)

        resultado = comparar(esperado, obtenido)
        for campo, bien in resultado.items():
            if bien:
                m.aciertos[campo] += 1

        if accion_de(esperado) in CRITICAS:
            m.criticos += 1
            if resultado["accion"]:
                m.criticos_ok += 1

        if not resultado["accion"]:
            m.fallos.append((caso, esperado, obtenido))

        # El contador solo se pinta en una terminal de verdad. Redirigido a
        # un archivo, `\r` no borra nada y deja una línea ilegible con los
        # once avances pegados.
        if sys.stdout.isatty() and (n % 5 == 0 or n == len(casos)):
            print(f"\r  {n}/{len(casos)}…", end="", flush=True)
    if sys.stdout.isatty():
        print("\r" + " " * 30 + "\r", end="")

    # ---- resultados ----
    print(f"{G}[1]{RST} Lo que importa: ¿hizo lo correcto?")
    pct = m.pct("accion")
    marca = OK if pct >= MINIMO_ACCION else NO
    print(f"  {marca} acción correcta: {pct:.1%}  ({m.aciertos['accion']}/{m.total})")
    if m.criticos:
        pctc = m.criticos_ok / m.criticos
        marca = OK if pctc >= MINIMO_CRITICO else NO
        print(
            f"  {marca} en lo que cuesta dinero: {pctc:.1%}  "
            f"({m.criticos_ok}/{m.criticos})"
        )

    print(f"\n{G}[2]{RST} Dónde falla (diagnóstico, no nota)")
    for campo in ("acto", "entidad", "atributo", "referencia", "datos"):
        p = m.pct(campo)
        barra = "█" * int(p * 24) + "·" * (24 - int(p * 24))
        color = V if p >= 0.9 else (A if p >= 0.75 else R)
        print(f"  {campo:11} {color}{barra}{RST} {p:.0%}")

    print(f"\n{G}[3]{RST} Cuánto tarda")
    if m.tiempos:
        print(
            f"  mediana {statistics.median(m.tiempos):.0f} ms · "
            f"peor {max(m.tiempos):.0f} ms"
        )

    if args.fallos and m.fallos:
        print(f"\n{G}[4]{RST} Los {len(m.fallos)} fallos, uno por uno")
        for caso, esp, obt in m.fallos:
            print(f"\n  {R}«{caso.mensaje}»{RST}")
            print(f"      esperaba: {esp.resumen()}  ->  {accion_de(esp).value}")
            print(f"      dijo:     {obt.resumen()}  ->  {accion_de(obt).value}")
            if caso.nota:
                print(f"      {G}nota: {caso.nota}{RST}")
    elif m.fallos:
        print(f"\n{G}[4]{RST} Ejemplos de fallo (con --fallos salen todos)")
        for caso, esp, obt in m.fallos[:5]:
            print(f"  {R}«{caso.mensaje[:44]}»{RST}")
            print(f"      {accion_de(esp).value} → dijo {accion_de(obt).value}")

    # ---- veredicto ----
    print(f"\n{C}{'=' * 74}\n  VEREDICTO\n{'=' * 74}{RST}")
    if args.solo_python:
        print(f"  Esta es tu LÍNEA BASE: {pct:.1%} sin usar el modelo.")
        print("  Corre ahora  vb golden  y compara. Si el modelo no le gana")
        print("  con holgura, no está aportando nada y lo pagas en latencia.\n")
        return 0

    if pct >= MINIMO_ACCION and (
        not m.criticos or m.criticos_ok / m.criticos >= MINIMO_CRITICO
    ):
        print(f"  {V}El modelo alcanza.{RST} No hay razón para cambiarlo.")
        print("  Guarda este número: es contra el que se compara el siguiente")
        print("  cambio de prompt o de modelo.\n")
        return 0

    print(f"  {A}Se queda corto de momento.{RST}")
    print(f"  Falla {m.total - m.aciertos['accion']} de {m.total} mensajes.\n")
    print("  ANTES de cambiar de modelo, en este orden:")
    print("    1. Mira los fallos:  vb golden --fallos")
    print("       Si se repiten en un solo campo, es el prompt, no el modelo.")
    print("    2. Compara con la línea base:  vb golden --solo-python")
    print("       Si el modelo no le gana, el problema no es su tamaño.")
    print("    3. Agrega al prompt un ejemplo de cada fallo que se repita.")
    print("    4. Vuelve a medir. Solo si sigue corto, cambia de modelo.\n")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
