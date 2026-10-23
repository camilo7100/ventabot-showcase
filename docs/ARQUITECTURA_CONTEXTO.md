# Arquitectura de contexto y routing de modelos

> **Desde el 17/09/2026** la conversación la lleva la asesora
> ([ADR 0014](adr/0014-la-asesora-lee-la-conversacion.md)). Lo de este documento
> sigue vigente como **respaldo** (si la API falla) y para lo que la asesora
> reutiliza: el Context Resolver, la política de cambios por estado
> (`domain/cambios.py`) y el registro de decisiones.

Por qué: [ADR 0013](adr/0013-el-contexto-sale-del-estado-del-pedido.md).
Pruebas: `tests/unit/test_contexto_operativo.py` (los 10 casos + la
conversación real con el número de Meta).

## El turno

```
webhook (firma HMAC, dedup)
  -> 1. CONTEXT RESOLVER   Mundo.resolver_contexto
        pedidos ACTIVOS de la BD · archiva lo que apunta a pedidos CERRADOS
  -> 2. INTERPRETAR        Interprete.interpretar
        reglas (sin IA) -> modelo básico -> modelo potente (solo por motivo)
  -> 3. RESOLVER           referencias contra el catálogo OPERATIVO
  -> 4. PLANIFICAR         tabla de acciones (Python)
  -> 5. VALIDAR            ambigüedad, requisitos, confianza en acciones críticas
  -> 6. EJECUTAR           Ejecutor (+ política de cambios por estado)
  -> 7. REDACTAR           plantillas
  -> registro de decisión (tabla `decisiones`) · outbox · WhatsApp
```

## Las cuatro memorias

| Memoria | Qué es | De dónde sale | ¿Va al modelo? |
|---|---|---|---|
| Reciente | últimos mensajes | tabla `messages`, ventana `VENTANA_RECIENTE_HORAS` | solo al potente, al escalar |
| Operativa | pedidos activos, compra en curso, qué falta, qué pago espera | BD en cada turno (`contexto.operativo`) | una línea, sin nombres ni teléfonos |
| Cliente | ciudad | `ContextoConversacional.ciudad` | no |
| Historial | pedidos cerrados | BD, **solo** con `CONSULTAR_HISTORIAL` | nunca por defecto |

Un pedido está **cerrado** si su estado es `ENTREGADO`, `CANCELADO` o
`REEMBOLSO`. `DESPACHADO` sigue activo (falta la entrega), pero la política
de cambios no deja modificar su diseño ni su dirección desde el chat.

## Capas de interpretación

1. **Reglas** (sin costo): quejas y petición de persona · «ya pagué» ·
   referencias al pasado · «ya te mandé la foto» · la respuesta a lo que se
   acaba de preguntar · atajos · «comencemos de 0» · reglas decisivas (precio,
   estado del pedido, objeciones, qué sigue, pedir sugerencia) · «cambiar la talla».
2. **Básico** (GPT-6 luna sin razonar; Haiku 5.5 si GPT no contesta, ADR 0027):
   el texto + una línea de estado.
   Devuelve `PropuestaDelModelo` (enums cerrados) y Python la corrige.
3. **Potente** (luna razonando un poco; Sonnet 5.5 de respaldo), solo con uno de
   estos motivos:
   - `sin_entender`: ni el modelo ni Python sacaron nada
   - `confianza_baja`: el básico dijo BAJA y ninguna regla lo corrigió
   - `accion_sensible`: cancelar / quitar / modificar sin confianza ALTA
   - `foto_ambigua`: una foto que importa y el lector básico no entendió
   - desempate histórico: varios candidatos y una descripción fuera de los campos

   Nunca por número de mensajes. Si el potente también duda, se queda la
   primera lectura. Si Python ya corrigió al modelo, no se escala.

## Fotos

`imagen + estado + pendientes`:

1. pista = lo pendiente (pago de un pedido activo > hueco de la compra > talla
   faltante de un pedido activo)
2. lector básico -> si no entendió y la foto importa -> lector potente
3. sigue sin entenderse: si solo cabe «comprobante» se recibe como tal (queda
   `EN_REVISION_PAGO`, nunca pagado) con nota para Lía; si caben varias cosas
   se pregunta y la referencia de la foto se guarda en `foto_pendiente`.

## Cambios a pedidos existentes (`domain/cambios.py`)

| Estado | talla que faltaba | talla existente | colores/grabado | dirección |
|---|---|---|---|---|
| hasta `EN_REVISION_PAGO` | aplica | aplica | aplica | aplica |
| `ANTICIPO_PAGADO` | aplica + nota | aplica + nota | aplica + nota | aplica + nota |
| `EN_PRODUCCION` | aplica + nota | persona | persona | aplica + nota |
| `PRODUCCION_LISTA`, `ESPERANDO_SALDO`, `SALDO_PAGADO` | persona | persona | persona | aplica + nota |
| `DESPACHADO` | persona | persona | persona | persona |
| cerrado | nunca | nunca | nunca | nunca |

## Observabilidad

Cada turno deja en el log una línea `decision {...}` y una fila en `decisiones`:

```json
{"routing_layer":"basico","motivo":"modelo","escalated":false,
 "intent":"INFORMAR·GRABADO·NINGUNO","action":"ANOTAR_DATOS","confidence":"MEDIA",
 "context_source":"compra_en_curso","active_orders":1,"closed_orders":0,
 "historical_lookup":false,"candidate_orders":0,"human_review":false,
 "llm_calls":[{"modelo":"claude-haiku-4-5","capa":"basico","in":85,"out":50,
 "cache_read":5015,"ms":1212,"usd":0.000837}],"cost_usd":0.000837,"latency_ms":1218}
```

`vb metricas` (o `vb metricas --horas 24 --ultimas 20`) resume: % sin IA,
% básico, % potente, escaladas, consultas históricas, pasados a persona,
acciones corregidas, errores, latencia p50/p95 y costo.
