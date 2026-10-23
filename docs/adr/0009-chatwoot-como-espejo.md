# 0009 — Chatwoot como espejo, no como canal

**Estado:** Aceptada · 2026-09

## Contexto

Lía necesita ver las conversaciones: quién escribió, qué pidió, qué falta, y
poder meterse cuando haga falta. El panel del taller enseña **pedidos**, no
conversaciones — y hay conversaciones que no llegan a pedido y son justo las
que hay que mirar.

Chatwoot es un CRM de conversaciones, gratuito y auto-hospedable.

## Opciones

1. **Chatwoot dueño del canal.** Chatwoot se conecta a la API de Meta y el bot
   pasa a ser un webhook suyo. Es lo que recomienda su documentación y es la
   arquitectura más limpia a largo plazo.
2. **Chatwoot como espejo.** El bot sigue siendo el dueño del canal y copia
   cada mensaje a Chatwoot, en los dos sentidos.
3. **Construir la vista de conversaciones en el panel.** Otra pantalla más que
   mantener, peor que un CRM hecho.

## Decisión

La segunda, y por una razón que no es técnica: **el canal funciona**.

La conexión con Meta costó una fase entera —firmas HMAC, la app equivocada
suscrita al WABA, el token de 24 horas, la ventana de las 24 h, las
plantillas—. Cambiar quién habla con Meta es volver a pelear todo eso a cambio
de nada que la clienta note.

Lo que hace falta hoy es que Lía pueda **mirar**, y para eso basta un espejo:
el bot copia cada mensaje con etiquetas (`necesita-persona`,
`confirmar-antes-de-fabricar`, `pago-por-verificar`) y con los datos del
pedido colgados de la conversación.

## Consecuencias

- **Hay un puerto** (`CrmPort`). El día que convenga invertirlo —Chatwoot
  dueño del canal, el bot detrás— se tira este adaptador y se escribe el otro.
  Nada más del sistema se entera.
- **La copia nunca bloquea.** Va en un hilo aparte con tope de tiempo corto por
  llamada; la clienta no espera por Chatwoot. Hay tests contra un Chatwoot caído.
- **Pero toda copia llega** (cambiado el 07/10). Chatwoot resultó ser la única
  forma en que Camilo y Lía ven la charla y contestan, así que «perder una copia
  es molesto» dejó de ser cierto. La cola pasó de la memoria a la base
  (`chatwoot_pendientes`): sobrevive caídas de Chatwoot de horas, reinicios del
  bot y scripts que terminan, y se reintenta sin límite, en orden. Solo se
  aparta (guardado, con aviso) lo que Chatwoot rechaza por sí mismo, para que
  no tape la fila. Detalle en `docs/sistema/05-chatwoot-y-operacion.md`.
- **Si Lía contesta desde Chatwoot, esa respuesta no sale por WhatsApp.** Es
  la limitación real del espejo, y es la razón por la que existe la opción 1.
  Mientras el volumen sea de 50 ventas al mes, contestar desde el celular es
  más rápido que montar el otro camino.
- **Tres etiquetas, no treinta.** Una por acción llenaría el CRM de ruido y no
  se usaría ninguna.
