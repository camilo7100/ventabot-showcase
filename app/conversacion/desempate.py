"""Cuando la búsqueda histórica deja VARIOS pedidos y la frase describe algo
que no está en los campos, se le pregunta al modelo potente cuál es.

════════════════════════════════════════════════════════════════════════════
CUÁNDO, Y CUÁNDO NO
════════════════════════════════════════════════════════════════════════════
«El otro pedido» con tres candidatos NO llega aquí: ningún modelo sabe cuál
de los tres quiere decir, y adivinarlo con más parámetros sigue siendo
adivinar. Eso se le pregunta a la clienta, que es la única que lo sabe.

Llega aquí solo lo que tiene PALABRAS que no coincidieron con ningún campo
(«el que le regalé a mi hermana», «el de la navidad») y varios candidatos.
Ahí un modelo capaz sí puede aportar, y aun así:

  · recibe solo lo mínimo de cada pedido (fecha, estado, colores), numerado
  · devuelve un NÚMERO de la lista o nada, con su confianza
  · si no está seguro, no se elige: se le pregunta a la clienta
  · y es una CONSULTA: aunque se equivocara, no se paga ni se cambia nada
"""

from __future__ import annotations

import logging

from pydantic import BaseModel, Field

from app.domain import consumo
from app.domain.historial import FiltroHistorico, ResultadoHistorico, fecha_corta

log = logging.getLogger("ventabot.desempate")

PROMPT = """Eres el archivo de pedidos de una joyeria que hace anillos con las
huellitas de las mascotas. Una clienta pregunta por UNO de sus pedidos
anteriores y te doy la lista numerada de los que pueden ser.

Tu unico trabajo: decir el NUMERO del pedido del que habla, o null si no se
puede saber con lo que dijo. No inventes: si dos encajan igual, es null.
confianza: ALTA solo si la frase apunta claramente a uno."""


class EleccionHistorica(BaseModel):
    numero: int | None = Field(default=None, ge=1, le=10)
    confianza: str = Field(default="BAJA", pattern="^(ALTA|MEDIA|BAJA)$")


class DesempateHistorico:
    def __init__(self, llm) -> None:
        self._llm = llm

    def __call__(
        self, texto: str, resultado: ResultadoHistorico, filtro: FiltroHistorico
    ):
        if self._llm is None or not resultado.palabras_sin_coincidencia:
            return None
        candidatos = resultado.candidatos[:10]
        lineas = []
        for n, pedido in enumerate(candidatos, start=1):
            detalle = ""
            if pedido.items:
                detalle = " | ".join(
                    i.personalizacion.describir().replace("\n", " · ")
                    for i in pedido.items
                )
            lineas.append(
                f"{n}. {fecha_corta(pedido.created_at)} · estado {pedido.estado}"
                f" · {detalle}"
            )
        mensaje = (
            "PEDIDOS:\n"
            + "\n".join(lineas)
            + "\n\nLA CLIENTA LO DESCRIBE CON ESTAS PALABRAS: "
            + ", ".join(resultado.palabras_sin_coincidencia)
        )
        try:
            with consumo.capa("historial"):
                eleccion = self._llm.extract(PROMPT, mensaje, EleccionHistorica)
        except Exception as exc:
            log.warning("sin desempate histórico (%s)", type(exc).__name__)
            return None
        if (
            isinstance(eleccion, EleccionHistorica)
            and eleccion.numero
            and eleccion.confianza == "ALTA"
            and eleccion.numero <= len(candidatos)
        ):
            return candidatos[eleccion.numero - 1]
        return None
