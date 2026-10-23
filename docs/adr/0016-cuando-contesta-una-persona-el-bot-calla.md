# 0016 — Cuando contesta una persona, el bot calla

**Estado:** Aceptada · 17/09/2026

## Contexto

El bot ya vende solo, pero hay conversaciones que tiene que atender una persona:
una queja, una negociación, un caso raro. Hasta ahora eso significaba que Camilo
o Lía escribieran desde fuera del sistema… y el bot seguía contestando encima.
La clienta recibe entonces dos voces distintas en el mismo chat, con dos
versiones del pedido. Es la forma más rápida de perder una venta hecha.

Quien ya montó agentes de venta en WhatsApp coincide en lo mismo: **el traspaso
a una persona es la parte difícil**, más que la conversación.

Además hacía falta un sitio para escribir a mano **desde el celular**, que es
donde se atiende de verdad.

## Opciones

1. **Un interruptor por conversación en el panel**: hay que acordarse de
   encenderlo y, sobre todo, de apagarlo. El que se olvida deja una clienta sin
   bot para siempre.
2. **Que el bot detecte por el texto que alguien más está contestando**: adivinar
   con lenguaje algo que es un hecho del sistema. No.
3. **Que escribir SEA el interruptor** (elegida): quien escribe a mano ya dijo
   todo lo que hacía falta saber.

## Decisión

**Si una persona escribe en una conversación, el bot se calla ahí durante 12
horas.** No para siempre —eso mataría el bot en esa clienta sin que nadie se
acuerde de reactivarlo— y no por un turno —eso no alcanza para una charla real—.
Vuelve solo, o antes con el botón «que siga el bot».

- La regla vive en `app/domain/atencion.py`, sin dependencias.
- La marca se guarda en el contexto de la conversación (`humano_hasta`), que ya
  se persistía entero: no hizo falta tabla nueva.
- El chequeo está en el borde, antes de llamar al bot
  (`Container.procesar_mensaje`): si hay alguien atendiendo, el mensaje entrante
  se registra y se copia al CRM, y no se contesta.
- **Lo que escribe la persona entra en la charla que lee la asesora.** Sin eso,
  al volver el bot no sabría qué se le prometió a la clienta y podría
  contradecirlo.
- Dos entradas para escribir a mano, las dos con token:
  - **El panel** (`/panel/chats`), que se abre en el celular sin instalar nada.
  - **Chatwoot** (`/webhook/chatwoot`), que tiene apps de iPhone y Android.

## Consecuencias

- Chatwoot deja de ser solo un espejo: ahora se puede **atender** desde él. Lo
  que el bot copia va marcado (`content_attributes.origen = "ventabot"`) para que
  el webhook no le devuelva a la clienta su propio mensaje en bucle.
- El bot puede quedarse callado sin que nadie se dé cuenta. Por eso el chat
  muestra cuánto falta para que vuelva, y el panel marca «a mano».
- Una persona puede prometer algo que el bot no sabe cumplir (un descuento, una
  fecha). El bot lo lee al volver, pero **no lo valida**: eso sigue siendo
  responsabilidad de quien lo escribió.
- Probado en `tests/unit/test_traspaso_humano.py` y
  `tests/unit/test_chatwoot_vuelta.py`: el bot contesta, deja de contestar
  mientras hay alguien, y vuelve cuando se le devuelve la conversación.

## Adenda · 19/09/2026 — Chatwoot como WhatsApp Business

Camilo eligió Chatwoot como CRM principal para tomar el control desde el celular. El
puente se amplió con la misma regla de fondo:

- **Asignarse la conversación** (`conversation_updated` con cambio de
  `assignee_id` hacia una persona) **ya calla al bot**, antes de escribir. La
  idea original era «empezar a escribir» (`conversation_typing_on`), pero esta
  versión de Chatwoot rechaza ese evento en los webhooks (422) y no lo emite.
  Por eso la **auto-asignación del buzón está apagada**: asignar tiene que ser
  un gesto de Lía, no algo que Chatwoot haga solo con cada clienta nueva. Si
  una versión futura emite «escribiendo…», el bot ya lo entiende.
- **Resolver** la conversación (`conversation_status_changed` → `resolved`) **se la
  devuelve al bot**. Es el botón que Lía ya conoce, no uno inventado.
- **Fotos en los dos sentidos**: las de la clienta se suben a Chatwoot como
  archivos (no "[adjunto]"); las que Lía manda desde Chatwoot salen por WhatsApp,
  guardadas en el mismo almacén de fotos del anillo terminado (solo imágenes,
  nombres aleatorios, máximo 5 MB). Audio o PDF desde Chatwoot **todavía no** se
  reenvían: se ignoran con motivo, en vez de mandarse rotos.
- Probado en `tests/unit/test_chatwoot_vuelta.py`.

## Adenda 2 · 19/09/2026 — El eco, la firma y los estados

Con clientas de verdad apareció el fallo más caro: **el bot se oía a sí mismo.**
Todo lo que copia a Chatwoot vuelve por webhook, y la marca
`content_attributes.origen` que debía reconocerlo **Chatwoot la descarta** al crear
el mensaje por API. Resultado: cada pieza salía dos veces por WhatsApp y el bot se
callaba creyendo que lo atendía una persona.

- **Firma:** lo que copia el bot se publica con el token de un **agente bot
  «VentaBot»** (`CHATWOOT_BOT_TOKEN`). El webhook lo reconoce por
  `sender.type = agent_bot`; Lía ve en Chatwoot quién escribió cada cosa.
  El agente bot tiene que estar conectado al buzón (si no, Chatwoot da 401), sin
  URL de salida: Chatwoot no le manda nada.
- **Respaldo:** si faltara la firma, el adaptador recuerda lo que copió en los
  últimos 5 minutos y cada copia se reconoce una sola vez (`es_eco`).
- **Estados, como las pestañas de WhatsApp Business:** «Pendiente» = la lleva el
  bot; «Abierta» = la clienta pidió una persona o Lía la tomó (asignarse o
  contestar); «Resuelta» = vuelve el bot.
  > **Reemplazado el 09/10:** quien está ASIGNADO es quien atiende (VentaBot o una
  > persona); devolver al bot es quitarse la asignación («Ninguna») o la macro;
  > resolver solo cierra. Ver R9 y R11 en `docs/sistema/03-reglas-de-negocio.md`.
- **Las pruebas no tocan servicios reales:** `tests/conftest.py` vacía Chatwoot,
  avisos, WhatsApp y Claude, y usa base, Excel y fotos temporales. Antes, la suite
  copió conversaciones inventadas al Chatwoot real.
- **Ensayo de punta a punta:** `vb ensayo` (`scripts/ensayo_chatwoot.py`) levanta un
  segundo bot en :8001 con modelo simulado, canal de consola y base temporal,
  apunta el webhook ahí mientras dura y lo devuelve al terminar.
