# 04 · Los estados del pedido

Un pedido siempre está en **uno** de estos 14 estados. La tabla de transiciones
(`app/domain/order_state.py`) dice a cuáles puede pasar, y es la única verdad:
el panel construye sus botones desde ahí, y Chatwoot mueve por el mismo camino.

## Los 14 estados

| Estado | Qué significa | Puede pasar a |
|---|---|---|
| `BORRADOR` | Se está armando | `COTIZADO`, `CANCELADO` |
| `COTIZADO` | Ya tiene precio | `CONFIRMADO`, `CANCELADO` |
| `CONFIRMADO` | Ella dijo que sí | `ESPERANDO_ANTICIPO`, `CANCELADO` |
| `ESPERANDO_ANTICIPO` | Cuentas enviadas, falta el abono | `EN_REVISION_PAGO`, `ANTICIPO_PAGADO`, `CANCELADO` |
| `EN_REVISION_PAGO` | Hay un comprobante por verificar | `ANTICIPO_PAGADO`, `SALDO_PAGADO`, `ESPERANDO_ANTICIPO`, `ESPERANDO_SALDO`, `CANCELADO` |
| `ANTICIPO_PAGADO` | Abono verificado | `EN_PRODUCCION`, `REEMBOLSO` |
| `EN_PRODUCCION` | En el taller | `PRODUCCION_LISTA`, `REEMBOLSO` |
| `PRODUCCION_LISTA` | El anillo quedó | `ESPERANDO_SALDO` |
| `ESPERANDO_SALDO` | Fotos enviadas, falta el saldo | `EN_REVISION_PAGO`, `SALDO_PAGADO` |
| `SALDO_PAGADO` | Saldo verificado: por despachar | `DESPACHADO`, `REEMBOLSO` |
| `DESPACHADO` | Va en camino (o listo para recoger) | `ENTREGADO` |
| `ENTREGADO` | Le llegó | — |
| `CANCELADO` | Se cayó | — |
| `REEMBOLSO` | Se devolvió la plata | — |

**`EN_REVISION_PAGO` es un solo estado para los dos pagos.** El panel muestra
solo los botones del pago que se está revisando: si el abono ya está pagado, el
que se revisa es el saldo. Nunca salen los dos.

## Los dos guardias

Antes de mover, `container.mover_pedido` comprueba dos cosas — y en este orden:

1. **¿La transición existe?** Si no, es ilegal y se dice así. Un salto que la
   tabla no permite no se queja de la dirección: se queja de que ese salto no
   existe.
2. **¿Está completo para ese paso?**
   - Hacia `EN_PRODUCCION`: `falta_para_taller()` — el anillo entero, con talla.
   - Hacia `DESPACHADO`: `falta_para_despachar()` — nombre y dirección, o que
     dijo que lo recoge.

Si falta algo, el movimiento se rechaza con un **409** que dice exactamente qué
falta. No se pierde nada y nadie tiene que adivinar.

## Qué le llega a la clienta en cada movimiento

Los mensajes viven en `app/domain/guion.py` (`AVISOS`, y `AVISOS_RECOGE` para
quien lo recoge). Los estados que no están aquí se mueven en silencio.

| Al llegar a | Le llega |
|---|---|
| `ESPERANDO_ANTICIPO` | El resumen del pedido y las cuentas |
| `EN_PRODUCCION` | «Tu pedido entró al taller» |
| `ESPERANDO_SALDO` | Las fotos del anillo terminado y el cobro del saldo |
| `DESPACHADO` | El número de guía… o dónde recogerlo y que la esperan |

Ese aviso **también entra en la memoria del bot**. Sin eso, después de mandar
«tu anillo ya está listo», el bot seguía diciendo «está en el taller».

## Lo que pasa además, en el mismo movimiento

Mover un pedido nunca es solo cambiar una palabra. En una sola operación:

1. se valida (los dos guardias de arriba);
2. se hace la transición y queda el evento con **quién** lo movió;
3. se registran los montos (confirmar el abono deja el abono pagado);
4. sale el aviso a la clienta, con las fotos primero, por la outbox;
5. ese aviso entra en la memoria de la conversación;
6. Chatwoot se entera: nota privada, etapa nueva, alertas al día;
7. el ERP de Google Sheets se actualiza.

Los pasos 6 y 7 **nunca bloquean**: si Chatwoot o Google están caídos, el pedido
se mueve igual y se reconcilia después.

## Quién puede mover un pedido

| Quién | Cómo |
|---|---|
| Lía, en el PC | El panel del taller (`/panel`, con token) |
| Lía, en el celular | Una etiqueta `hacer-…` en Chatwoot |
| El bot | Solo hasta `EN_REVISION_PAGO`. De ahí en adelante, jamás solo |

Los dos caminos de Lía pasan por la misma función. No hay una regla en el panel
y otra en Chatwoot: hay una sola, y las dos la obedecen.
