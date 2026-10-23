"""Si Meta deja escribir desde el número: el `health_status` del número (03/10).

Las plantillas pueden estar aprobadas y aun así no salir: si Meta no puede
cobrar, bloquea TODO lo que inicia el negocio (el cobro del saldo, «tu pedido
salió»). Las respuestas a la clienta dentro de las 24 h siguen saliendo, así
que el bot parece sano mientras los avisos se quedan en la cola. Pasó el
03/10/2026: plantillas aprobadas, método de pago con error, nada lo decía.

Meta lo cuenta por capas (número, cuenta de WhatsApp, empresa, app). Aquí se
traduce a qué hacer; lo de las llamadas por SIP no se usa y no cuenta.
"""

from __future__ import annotations

from dataclasses import dataclass, field

#: Códigos de Meta que no son problema para VentaBot: llamadas por SIP.
IGNORADOS = frozenset({138024, 138025})

#: Lo que significa cada código y quién lo arregla.
QUE_HACER = {
    141006: "Meta no puede cobrar: arregla el método de pago en WhatsApp Manager"
    " → Facturación (bloquea el cobro del saldo y los avisos)",
    141010: "La empresa no está verificada: Configuración del negocio → Centro de"
    " seguridad → Verificación (limita cuántas clientas nuevas al día)",
}

ORDEN = {"AVAILABLE": 0, "LIMITED": 1, "BLOCKED": 2}


@dataclass
class Salud:
    #: «AVAILABLE», «LIMITED» o «BLOCKED»: lo peor de las capas que cuentan.
    estado: str = "AVAILABLE"
    problemas: list[str] = field(default_factory=list)


def leer_salud(health_status: dict | None) -> Salud:
    salud = Salud()
    for capa in (health_status or {}).get("entities", []):
        errores = [
            e for e in capa.get("errors", []) if e.get("error_code") not in IGNORADOS
        ]
        if not errores:
            continue
        estado = capa.get("can_send_message", "AVAILABLE")
        if ORDEN.get(estado, 0) > ORDEN[salud.estado]:
            salud.estado = estado
        for e in errores:
            texto = QUE_HACER.get(e.get("error_code")) or e.get("error_description", "")
            if texto and texto not in salud.problemas:
                salud.problemas.append(texto)
    return salud
