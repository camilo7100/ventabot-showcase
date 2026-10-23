"""Por qué el bot hizo lo que hizo en un turno. Una fila, sin datos personales.

════════════════════════════════════════════════════════════════════════════
QUÉ RESPONDE
════════════════════════════════════════════════════════════════════════════
Cuando alguien pregunta «¿por qué le contestó eso?», el registro de un turno
dice, sin tener que reconstruirlo:

  · qué capa respondió      reglas | basico | fuerte
  · por qué                 la regla o el motivo de la escalada
  · con qué contexto        compra en curso | pedido activo | historial | nada
  · si buscó en el historial, y entre cuántos pedidos
  · con qué confianza, y si Python corrigió al modelo
  · si terminó en una persona
  · cuánto tardó y cuánto costó (tokens y USD estimados)

Y NO guarda: el texto de la clienta, su número, nombres, direcciones ni montos.
La conversación se identifica con una huella corta, suficiente para agrupar
turnos de la misma persona sin poder leer quién es.

Con estas filas salen las métricas (`scripts/metricas.py`): % sin IA, % con el
modelo básico, % con el potente, escaladas, consultas históricas, errores,
latencia, costo y acciones corregidas.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime

from app.domain import consumo


def huella_conversacion(conversation_id: str) -> str:
    return hashlib.sha256((conversation_id or "").encode("utf-8")).hexdigest()[:12]


@dataclass
class RegistroDeDecision:
    ts: str
    conversacion: str
    routing_layer: str
    motivo: str
    escalated: bool
    escalation_reason: str
    intent: str
    action: str
    verdict: str
    confidence: str
    context_source: str
    active_orders: int
    closed_orders: int
    historical_lookup: bool
    candidate_orders: int
    human_review: bool
    image: str
    corrected: bool
    model_said: str
    context_archived: list[str] = field(default_factory=list)
    llm_calls: list[dict] = field(default_factory=list)
    cost_usd: float = 0.0
    latency_ms: int = 0
    error: str = ""

    def a_dict(self) -> dict:
        return asdict(self)

    def linea(self) -> str:
        return json.dumps(self.a_dict(), ensure_ascii=False, separators=(",", ":"))


def registro_del_turno(turno, ficha=None, *, ms: int = 0) -> RegistroDeDecision:
    """El registro de un `Turno` ya terminado. Nunca falla."""
    i = turno.interpretacion
    d = turno.decision
    ctx = turno.contexto
    operativo = getattr(ctx, "operativo", None)
    gasto = consumo.actual()
    ruta = i.ruta if i is not None else None
    accion = d.accion.value if d is not None else ""
    historial = accion == "CONSULTAR_HISTORIAL"

    return RegistroDeDecision(
        ts=datetime.now(UTC).isoformat(timespec="seconds"),
        conversacion=huella_conversacion(turno.conversation_id),
        routing_layer=ruta.capa if ruta else "sistema",
        motivo=ruta.motivo if ruta else "",
        escalated=bool(ruta and ruta.escalado),
        escalation_reason=ruta.motivo_escalada if ruta else "",
        intent=(
            f"{i.acto.value}·{i.entidad.value}·{i.atributo.value}"
            if i is not None
            else ""
        ),
        action=accion,
        verdict=d.veredicto.value if d is not None else "",
        confidence=i.confianza if i is not None else "",
        context_source=(
            "historial"
            if historial
            else (operativo.fuente() if operativo is not None else "sin_resolver")
        ),
        active_orders=len(operativo.activos) if operativo is not None else 0,
        closed_orders=operativo.cerrados if operativo is not None else 0,
        historical_lookup=historial,
        candidate_orders=(
            int((ficha.datos if ficha is not None else {}).get("candidatos") or 0)
            if historial
            else len(d.candidatos)
            if d is not None
            else 0
        ),
        human_review=bool(turno.respuesta is not None and turno.respuesta.escalar),
        image=i.foto if i is not None else "",
        corrected=bool(ruta and ruta.corregido),
        model_said=ruta.dijo_el_modelo if ruta else "",
        context_archived=list(operativo.archivados) if operativo is not None else [],
        llm_calls=[x.a_dict() for x in gasto.llamadas] if gasto else [],
        cost_usd=round(gasto.usd, 6) if gasto else 0.0,
        latency_ms=ms,
    )
