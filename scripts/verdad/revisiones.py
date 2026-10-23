"""Cómo se califica cada respuesta del bot en la prueba de verdad (04/10).

Dos clases de revisión:

- **Las reglas de siempre** (`REGLAS`): se miran en TODOS los pasos de todas
  las clientas. Son las que, si fallan una sola vez en producción, cuestan una
  venta o la confianza: contestar siempre, no inventar precios, no pedir el
  abono antes del resumen, no decir «recibido» sin pago, no cuestionar un
  comprobante, no poner a esperar a Lía por una talla que ella dijo, no ofrecer
  la cadena, una sola pregunta por mensaje, no repetirse, tardar poco.
- **Lo que se espera de cada paso** (`dice`, `manda`, `pedido_en`…): lo
  escribe cada escenario según la etapa (talla, colores, resumen, abono…).

Todo se compara sin tildes ni mayúsculas. Una revisión devuelve la lista de
problemas (vacía = pasó).
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass, field


def plano(texto: str) -> str:
    t = unicodedata.normalize("NFKD", str(texto or "")).lower()
    return "".join(c for c in t if not unicodedata.combining(c))


@dataclass
class Salida:
    """Lo que salió hacia la clienta en un paso (en orden)."""

    textos: list[str] = field(default_factory=list)
    medios: list[str] = field(default_factory=list)
    plantillas: list[str] = field(default_factory=list)
    segundos: float = 0.0

    @property
    def todo(self) -> str:
        return plano(" \n ".join(self.textos))

    @property
    def vacia(self) -> bool:
        return not (self.textos or self.medios or self.plantillas)


@dataclass
class Estado:
    """Lo que se sabe de la clienta hasta este paso (lo pone el que corre)."""

    pidio_cadena: bool = False
    pidio_cuentas: bool = False
    mando_regla_o_medida: bool = False
    pago_reportado: bool = False
    lia_verifico_pago: bool = False
    anillo_listo: bool = False
    resumen_visto: bool = False
    #: Lo de la base después del paso.
    pedido: dict | None = None
    borrador: dict = field(default_factory=dict)
    anteriores: list[str] = field(default_factory=list)


Revision = Callable[[Salida, Estado], list[str]]

# ---------------------------------------------------------------------------
# Las reglas de siempre
# ---------------------------------------------------------------------------

#: Lo que vale cualquier precio que diga el bot (catálogo, abonos, saldos,
#: envío, sumas de hasta tres piezas). Un número fuera de aquí es inventado.
_PIEZAS = (200_000, 250_000, 300_000)
_ABONOS = (60_000, 65_000)
ENVIO = 17_500


def precios_validos() -> set[int]:
    validos = {ENVIO, *_PIEZAS, *_ABONOS}
    piezas = (*_PIEZAS, 250_000)  # la cadena vale 250.000
    for a in piezas:
        for b in (0, *piezas):
            for c in (0, *piezas):
                total = a + b + c
                n = 1 + (b > 0) + (c > 0)
                for abono in (60_000 * n, 60_000 * (n - 1) + 65_000, 65_000 * n):
                    validos |= {total, abono, total - abono, total + ENVIO}
                    validos |= {total - abono + ENVIO}
    return validos


VALIDOS = precios_validos()
_PRECIO = re.compile(r"\$\s?(\d{1,3}(?:[.,]\d{3})+|\d{4,})")
_PLANTILLA = ("•", "*a esta cuenta", "envios nacionales", "🎀", "estos son los colores")


def _es_plantilla(texto: str) -> bool:
    t = plano(texto)
    return any(m in t for m in _PLANTILLA)


def responde(s: Salida, e: Estado) -> list[str]:
    return ["no contestó nada"] if s.vacia else []


def sin_restos(s: Salida, e: Estado) -> list[str]:
    malos = [t for t in s.textos if re.search(r"[{}]|\bNone\b|\bnull\b|\[\w+\]", t)]
    return [f"texto con restos de código: «{malos[0][:80]}»"] if malos else []


def no_inventa_precios(s: Salida, e: Estado) -> list[str]:
    raros = set()
    for t in s.textos:
        for m in _PRECIO.finditer(t):
            valor = int(re.sub(r"[.,]", "", m.group(1)))
            if valor not in VALIDOS:
                raros.add(m.group(0))
    return [f"precio que no existe: {', '.join(sorted(raros))}"] if raros else []


_DUDA = re.compile(r"otro comprobante|no coincide|no cuadra|otra persona|no corresponde")


def no_cuestiona_el_pago(s: Salida, e: Estado) -> list[str]:
    m = _DUDA.search(s.todo)
    return [f"cuestionó el comprobante («{m.group(0)}»)"] if m else []


_ESPERA_LA_TALLA = re.compile(
    r"confirm(o|arte|amos) (tu |la )?talla|revise tu medida|confirmo tu talla"
    r"|te confirmo la talla|confirmarte la talla"
)


def talla_sin_esperar_a_lia(s: Salida, e: Estado) -> list[str]:
    if e.mando_regla_o_medida:
        return []
    m = _ESPERA_LA_TALLA.search(s.todo)
    return [f"puso a esperar a Lía una talla que ella DIJO («{m.group(0)}»)"] if m else []


def no_ofrece_la_cadena(s: Salida, e: Estado) -> list[str]:
    if e.pidio_cadena:
        return []
    return ["nombró la cadena sin que ella preguntara"] if "cadena" in s.todo else []


def recibido_solo_con_pago(s: Salida, e: Estado) -> list[str]:
    if e.pago_reportado:
        return []
    return ["dijo «recibido» sin que ella pagara"] if "recibido" in s.todo else []


def cuentas_despues_del_resumen(s: Salida, e: Estado) -> list[str]:
    """Las cuentas, solo con el resumen ya visto (o en esta misma tanda, antes),
    o si ella las pidió (regla 8 del prompt: hablar de plata = cuentas)."""
    if e.resumen_visto or e.pidio_cuentas:
        return []
    for t in s.textos:
        p = plano(t)
        if any(m in p for m in ("•anillo", "•cadena", "•pedido")):
            return []
        if "paula mantilla" in p:
            return ["mandó las cuentas antes del resumen"]
    return []


_PIDE_DATOS_DE_ENVIO = re.compile(
    r"cedula|direccion completa|tu direccion|barrio|envio.{0,40}ciudad|ciudad.{0,40}envi"
)


def envio_solo_al_final(s: Salida, e: Estado) -> list[str]:
    if e.anillo_listo:
        return []
    m = _PIDE_DATOS_DE_ENVIO.search(s.todo)
    return [f"pidió datos de envío antes de tiempo («{m.group(0)}»)"] if m else []


def una_pregunta_por_mensaje(s: Salida, e: Estado) -> list[str]:
    dobles = [t for t in s.textos if t.count("?") > 1 and not _es_plantilla(t)]
    return [f"dos preguntas en un mensaje: «{dobles[0][:90]}»"] if dobles else []


def no_se_repite(s: Salida, e: Estado) -> list[str]:
    antes = {plano(t) for t in e.anteriores[-8:] if len(t) > 25 and not _es_plantilla(t)}
    repetidos = [t for t in s.textos if plano(t) in antes]
    return [f"repitió un mensaje: «{repetidos[0][:80]}»"] if repetidos else []


_CONFIRMA_EL_PAGO = re.compile(
    r"pago (esta |quedo )?confirmado|confirmamos tu pago|ya verifique tu pago"
    r"|abono (esta |quedo )?confirmado"
)


def no_confirma_pagos(s: Salida, e: Estado) -> list[str]:
    if e.lia_verifico_pago:
        return []
    m = _CONFIRMA_EL_PAGO.search(s.todo)
    return [f"dio el pago por confirmado sin Lía («{m.group(0)}»)"] if m else []


def rapido(s: Salida, e: Estado) -> list[str]:
    return [f"tardó {s.segundos:.0f} s"] if s.segundos > 40 else []


REGLAS: dict[str, Revision] = {
    "contesta siempre": responde,
    "sin restos de código": sin_restos,
    "no inventa precios": no_inventa_precios,
    "no cuestiona comprobantes": no_cuestiona_el_pago,
    "la talla que dice no espera a Lía": talla_sin_esperar_a_lia,
    "no ofrece la cadena": no_ofrece_la_cadena,
    "«recibido» solo con pago": recibido_solo_con_pago,
    "cuentas después del resumen": cuentas_despues_del_resumen,
    "envío solo al final": envio_solo_al_final,
    "una pregunta por mensaje": una_pregunta_por_mensaje,
    "no se repite": no_se_repite,
    "no confirma pagos": no_confirma_pagos,
    "contesta en menos de 40 s": rapido,
}

# ---------------------------------------------------------------------------
# Lo que se espera de un paso (los escenarios los combinan)
# ---------------------------------------------------------------------------


def dice(*frases: str, alguna: bool = False) -> Revision:
    """Que diga TODAS las frases (o alguna, con `alguna=True`)."""

    def revisar(s: Salida, e: Estado) -> list[str]:
        faltan = [f for f in frases if plano(f) not in s.todo]
        if alguna:
            return [] if len(faltan) < len(frases) else [f"no dijo nada de {frases}"]
        return [f"no dijo «{f}»" for f in faltan]

    return revisar


def no_dice(*frases: str) -> Revision:
    def revisar(s: Salida, e: Estado) -> list[str]:
        return [f"dijo «{f}»" for f in frases if plano(f) in s.todo]

    return revisar


def manda(medio: str) -> Revision:
    def revisar(s: Salida, e: Estado) -> list[str]:
        if any(medio in m for m in s.medios):
            return []
        return [f"no mandó la imagen «{medio}»"]

    return revisar


def no_manda(medio: str) -> Revision:
    def revisar(s: Salida, e: Estado) -> list[str]:
        return [f"mandó «{medio}»"] if any(medio in m for m in s.medios) else []

    return revisar


def pregunta() -> Revision:
    def revisar(s: Salida, e: Estado) -> list[str]:
        return [] if "?" in s.todo else ["no terminó con una pregunta"]

    return revisar


def entre_comillas_si_lo_nombra(grabado: str) -> Revision:
    """Si el bot nombra lo que va grabado, va entre comillas: «Bombom» (06/10)."""
    g = plano(grabado)

    def revisar(s: Salida, e: Estado) -> list[str]:
        sueltas = s.todo.replace(f"«{g}»", "")
        return [f"nombró «{grabado}» sin comillas"] if g in sueltas else []

    return revisar


def no_pide(que: str) -> Revision:
    """Que NO le pida `que` («talla», «colores»…), ni con «¿?» ni con «mándame»:
    lo dejó para después o ya se lo pidieron de más (Yulieth, 09/10)."""
    from app.domain.asesora import pide

    def revisar(s: Salida, e: Estado) -> list[str]:
        texto = "\n".join(s.textos)
        return [f"le volvió a pedir {que}: «{texto[-160:]}»"] if pide(texto, que) else []

    return revisar


def no_pregunta() -> Revision:
    """Ya no le falta nada a ella (espera a Lía): no se le pregunta (06/10)."""

    def revisar(s: Salida, e: Estado) -> list[str]:
        return [f"preguntó sin necesidad: «{s.todo[-120:]}»"] if "?" in s.todo else []

    return revisar


def pedido_en(*estados: str) -> Revision:
    def revisar(s: Salida, e: Estado) -> list[str]:
        actual = (e.pedido or {}).get("estado")
        return [] if actual in estados else [f"pedido en {actual}, se esperaba {estados}"]

    return revisar


def sin_pedido() -> Revision:
    def revisar(s: Salida, e: Estado) -> list[str]:
        return [f"ya hay pedido ({e.pedido['estado']})"] if e.pedido else []

    return revisar


def borrador(**esperado) -> Revision:
    """Campos del borrador: `talla=6`, `cantidad=2`, `grabado_tiene="Luna"`…"""

    def revisar(s: Salida, e: Estado) -> list[str]:
        b = e.borrador or {}
        problemas = []
        for clave, valor in esperado.items():
            if clave == "grabado_tiene":
                if plano(valor) not in plano(" ".join(b.get("grabado") or [])):
                    problemas.append(f"el grabado no tiene «{valor}»: {b.get('grabado')}")
            elif clave == "talla_lista":
                pendiente = bool(b.get("talla_revisar")) or not b.get("talla_confirmada")
                if valor and (b.get("talla") is None or pendiente):
                    problemas.append(
                        f"la talla no quedó lista: talla={b.get('talla')} "
                        f"revisar={b.get('talla_revisar')} "
                        f"confirmada={b.get('talla_confirmada')}"
                    )
            elif clave == "talla_en_revision":
                if bool(b.get("talla_revisar")) != valor:
                    problemas.append(f"talla_revisar={b.get('talla_revisar')}")
            elif b.get(clave) != valor:
                problemas.append(f"{clave}={b.get(clave)!r}, se esperaba {valor!r}")
        return problemas

    return revisar


def total_del_pedido(pesos: int) -> Revision:
    def revisar(s: Salida, e: Estado) -> list[str]:
        total = ((e.pedido or {}).get("payload") or {}).get("total_cop")
        return (
            [] if total == pesos else [f"total del pedido {total}, se esperaba {pesos}"]
        )

    return revisar
