"""Cuánto costó un turno: qué modelos se llamaron, con cuántos tokens y cuánto tardaron.

Es un contador por TURNO, no global. Vive en un `ContextVar` porque los turnos
corren en hilos distintos (`BackgroundTasks` de FastAPI): dos clientas
escribiendo a la vez no pueden sumarse las llamadas la una a la otra.

Los adaptadores de modelos apuntan aquí cada llamada; el pipeline lo abre al
empezar el turno y lo lee al final para el registro de decisiones. Si nadie lo
abrió (un script, un test), apuntar no hace nada y no falla.

Los precios son USD por MILLÓN de tokens, de las tablas oficiales de Anthropic
y OpenAI (septiembre de 2026). Un modelo local cuesta 0: se paga en luz y en espera, no
en factura. Si un precio cambia, se cambia aquí y en ningún otro sitio.
"""

from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass, field

#: modelo (prefijo) -> (entrada, salida) en USD por millón de tokens.
PRECIOS_USD_MTOK: dict[str, tuple[float, float]] = {
    # Precios de lista de Anthropic al 25/09/2026. Los más específicos primero:
    # se busca por prefijo y «claude-sonnet-5» también es el comienzo de 5.5.
    # Haiku 5.5 (12/10, tabla oficial): para mensajes de hasta 100.000 tokens;
    # más largos cuestan 5 veces más, pero los del bot rondan 13.000-22.000.
    "claude-haiku-5-5": (0.10, 0.50),
    "claude-haiku-4-5": (1.00, 5.00),
    "claude-sonnet-5-5": (2.00, 10.00),
    "claude-sonnet-5": (2.00, 10.00),
    "claude-opus-5-5": (4.00, 20.00),
    # GPT-6, precios de lista de OpenAI al 29/09/2026 (developers.openai.com).
    "gpt-6-luna": (0.10, 0.50),
    "gpt-6.1-sol": (2.00, 10.00),
    "gpt-6-sol": (2.00, 10.00),
    "gpt-6-astra": (10.00, 50.00),
    "claude-sonnet-4-6": (3.00, 15.00),
    "claude-opus-5": (5.00, 25.00),
    "claude-opus-4-8": (5.00, 25.00),
}
#: Leer de caché cuesta la décima parte (Anthropic y también GPT-6 luna: US$0,01
#: contra 0,10); escribirla, un 25 % más en Anthropic y nada extra en OpenAI
#: (que por eso la apunta siempre como lectura o entrada normal).
FACTOR_CACHE_LECTURA = 0.10
FACTOR_CACHE_ESCRITURA = 1.25


def precio_de(modelo: str) -> tuple[float, float]:
    for prefijo, precio in PRECIOS_USD_MTOK.items():
        if (modelo or "").startswith(prefijo):
            return precio
    return (0.0, 0.0)


@dataclass
class Llamada:
    modelo: str
    #: «basico», «fuerte», «reescribir», «vision», «vision_fuerte», «historial».
    capa: str
    entrada: int = 0
    salida: int = 0
    cache_leida: int = 0
    cache_escrita: int = 0
    ms: int = 0
    ok: bool = True

    @property
    def usd(self) -> float:
        p_in, p_out = precio_de(self.modelo)
        return (
            self.entrada * p_in
            + self.cache_leida * p_in * FACTOR_CACHE_LECTURA
            + self.cache_escrita * p_in * FACTOR_CACHE_ESCRITURA
            + self.salida * p_out
        ) / 1_000_000

    def a_dict(self) -> dict:
        return {
            "modelo": self.modelo,
            "capa": self.capa,
            "in": self.entrada,
            "out": self.salida,
            "cache_read": self.cache_leida,
            "cache_write": self.cache_escrita,
            "ms": self.ms,
            "ok": self.ok,
            "usd": round(self.usd, 6),
        }


@dataclass
class Consumo:
    llamadas: list[Llamada] = field(default_factory=list)

    @property
    def usd(self) -> float:
        return sum(x.usd for x in self.llamadas)


_TURNO: ContextVar[Consumo | None] = ContextVar("ventabot_consumo", default=None)
#: Qué capa está llamando ahora. La pone el intérprete antes de cada llamada,
#: para que el adaptador —que no sabe para qué lo llaman— lo apunte bien.
_CAPA: ContextVar[str] = ContextVar("ventabot_capa", default="")


def abrir_turno() -> Consumo:
    consumo = Consumo()
    _TURNO.set(consumo)
    return consumo


def actual() -> Consumo | None:
    return _TURNO.get()


def capa_actual() -> str:
    """La capa que está llamando ahora («basico», «fuerte»…), o "" si nadie la
    puso. La lee también la traza de LangSmith de cada llamada al modelo."""
    return _CAPA.get()


def capa(nombre: str):
    """`with consumo.capa("fuerte"): llm.extract(...)`."""
    return _Capa(nombre)


class _Capa:
    def __init__(self, nombre: str) -> None:
        self._nombre = nombre
        self._token = None

    def __enter__(self):
        self._token = _CAPA.set(self._nombre)
        return self

    def __exit__(self, *exc):
        _CAPA.reset(self._token)
        return False


def registrar(modelo: str, **kw) -> None:
    """Lo llaman los adaptadores después de cada llamada. Nunca falla."""
    consumo = _TURNO.get()
    if consumo is None:
        return
    consumo.llamadas.append(Llamada(modelo=modelo, capa=_CAPA.get() or "?", **kw))
