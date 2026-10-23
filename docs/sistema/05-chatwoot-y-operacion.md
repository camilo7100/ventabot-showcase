# 05 · Chatwoot y la operación diaria

Chatwoot es el sitio donde Lía trabaja: ve todas las conversaciones, contesta
cuando quiere y mueve pedidos sin tocar el PC. El bot sigue siendo el dueño del
WhatsApp; Chatwoot es el tablero.

## La jornada, en cuatro gestos

1. **Abrir una carpeta** de la barra lateral (ver abajo) y trabajar lo que hay.
2. **Tomar una charla** si hace falta: *Asignar a mí*. El bot se calla ahí.
3. **Devolvérsela al bot**: marcarla **Resuelta**.
4. **Mover un pedido**: ponerle una etiqueta `hacer-…`.

## Las carpetas (lo que Lía abre para trabajar)

| Carpeta | Qué junta |
|---|---|
| 🙋 Me necesitan | `necesita-persona`, `datos-incompletos` |
| 💰 Pagos por verificar | `pago-por-verificar` |
| 📍 Falta la dirección | `falta-direccion` |
| 🔨 En el taller | `05-en-taller` |
| 💍 Listos: cobrar saldo | `06-listo-cobrar-saldo` |
| 📦 Por despachar | `08-por-despachar` |
| ⏳ Esperando abono | `03-esperando-abono` |

## Las etiquetas

Son de tres clases y se distinguen a simple vista. Las pone y las quita el bot
solo, salvo las de acción, que son las órdenes de Lía.

### Etapas — dónde va la venta (siempre una)

`01-consulta` · `02-disenando` · `03-esperando-abono` · `04-abono-por-verificar`
· `05-en-taller` · `06-listo-cobrar-saldo` · `07-saldo-por-verificar` ·
`08-por-despachar` · `09-despachado` · `10-entregado` · `99-cancelado`

### Alertas — algo que mirar (puede haber varias)

| Etiqueta | Qué quiere decir |
|---|---|
| `necesita-persona` | Pidió una persona, hay una queja o un caso raro |
| `pago-por-verificar` | Hay un comprobante esperando en la cuenta |
| `datos-incompletos` | Pagó pero al pedido le faltan datos: no entra al taller |
| `confirmar-antes-de-fabricar` | Algo que mirar antes de fundir (talla dudosa, grabado raro) |
| `tiene-fecha-limite` | Necesita el anillo para una fecha |
| `falta-direccion` | Pagó el abono y falta la dirección (o si lo recoge) |

Cuatro de ellas (`necesita-persona`, `pago-por-verificar`, `datos-incompletos`,
`falta-direccion`) **abren** la conversación aunque estuviera resuelta: son
cosas que no se pueden quedar quietas.

### Acciones — lo que Lía le ordena al bot

| Etiqueta | Qué hace |
|---|---|
| `hacer-abono-ok` | Abono verificado → al taller, y le avisa a la clienta |
| `hacer-anillo-listo` | Manda las fotos del anillo y cobra el saldo |
| `hacer-saldo-ok` | Saldo verificado → queda por despachar |
| `hacer-despachado` | Ya lo llevé a Coordinadora (o ya está listo para recoger) |
| `hacer-entregado` | Ya le llegó |
| `hacer-preguntar-lo-que-falta` | **No mueve el pedido.** El bot le vuelve a pedir a la clienta lo que falta, con la lista exacta, y te deja una nota con TODO lo que tiene guardado. Para cuando se traba en un paso y no se entiende por qué |

Se ponen desde el celular igual que desde el PC. **El bot la quita sola** en
cuanto la cumple y deja una nota privada diciendo qué pasó. Si la acción no se
puede hacer (falta algo, o ese paso no existe desde donde está), lo dice en la
nota y no mueve nada. Ponerla dos veces no hace nada dos veces.

## La ficha de la derecha

13 campos que se llenan solos: pedido, huellitas, colores, grabado, talla,
envío, **cómo se entrega**, total, abonado, saldo por pagar, qué falta, por
confirmar y fecha límite. Para ver de un vistazo en qué va sin leer la charla.

## Las respuestas rápidas

Escribiendo `/` en Chatwoot salen las respuestas de siempre (las cuentas, el
abono, los tiempos…). **Salen de las mismas verdades que usa el bot**, así que
nunca dicen una cosa distinta.

## Las fotos y los audios se ven

Todo lo que viaja por la conversación se ve **dentro de Chatwoot**, no como un
«[📷 muestrario]» que hay que imaginarse:

- lo que manda la clienta (fotos de su mascota, la regla de la talla, el
  comprobante, **las notas de voz**, que se pueden reproducir ahí mismo);
- lo que manda el bot (el muestrario, el prototipo de su anillo, los videos de
  la presentación, las fotos del anillo terminado).

Los archivos del bot se leen del disco y no se vuelven a bajar por el túnel:
son los mismos megas que ya salieron hacia WhatsApp.

En el **panel del taller** (`/panel/chats`) también se ven las fotos y los
videos que mandó el bot, dentro de cada burbuja. Lo que manda la clienta se ve
en Chatwoot: en el panel sale como «[adjunto]», porque ese archivo vive en los
servidores de Meta y no en el PC.

## Quién atiende: VentaBot o una persona (09/10)

**Una sola regla, igual en el computador y en el celular: quien está asignado
es quien atiende.**

| Asignada a | Estado en Chatwoot | Qué pasa |
|---|---|---|
| **VentaBot** (lo normal) | Pendiente | Contesta el bot. |
| **Una persona** (Lía, Camilo) | Abierta | Contesta esa persona; el bot se calla. |

Deja el filtro de la lista en **«Todos»**: en «Abiertas» solo salen las que
atiende una persona; las del bot están en «Pendientes».

**Para tomarla (que el bot se calle):**
- En el computador: abre la conversación → a la derecha, en «Acciones de
  conversación» → «Agente asignado» → toca **«Asignar a mi»**.
- En el celular: abre la conversación → menú de la conversación → asignar
  agente → **tu nombre**.
- O simplemente **escríbele**: queda asignada a ti sola.

**Para devolverla al bot:**
- En el computador o el celular: en «Agente asignado» elige **«Ninguna»**
  (quítatela). El bot la toma solo y vuelve a aparecer VentaBot.
- También sirven: elegir **VentaBot**, la macro **«🤖 Devolver al bot»**, la
  etiqueta `hacer-devolver-al-bot` o el botón «Que siga el bot» del panel.

**Resolver ≠ devolver.** «Resolver» solo cierra la conversación (y quita la
alerta de «necesita persona»); no cambia quién la atiende.

Si una persona la tiene y pasan 12 h desde lo último que escribió, cuando la
clienta vuelva a escribir el bot la retoma y deja una nota privada «⏰».
Lo que necesita a una persona queda **Urgente** (y en la carpeta «🙋 Me
necesitan»); el bot la sigue atendiendo mientras tanto.

## Nada se queda por fuera de Chatwoot

Chatwoot es la única forma de ver la charla, así que todo lo que sale hacia la
clienta pasa por una sola puerta (`Container.enviar_a_la_clienta`) que lo
manda por WhatsApp **y** lo copia aquí: las respuestas del bot, los
recordatorios, lo que Lía escribe en el panel, los envíos a mano desde el
servidor.

La copia va por detrás para no demorar a la clienta, en una **cola guardada en
la base de datos** (tabla `chatwoot_pendientes`, `app/adapters/crm/cola.py`):

- **Si Chatwoot se cae, aunque sea por horas**, cada copia espera ahí y se
  reintenta sin límite (a los 2 s, 5 s, 15 s, 30 s y luego cada minuto). Cuando
  Chatwoot vuelve, llegan todas **en orden**. La que llega con más de 10 min de
  retraso dice a qué hora pasó de verdad: «🕓 07/10 2:32 p. m. · …».
- **Si el bot se reinicia o se actualiza, no se pierde nada**: la cola está en
  disco. Antes de cerrarse espera hasta 20 s a que termine (3 s si Chatwoot está
  caído); lo que falte lo copia al volver a arrancar. El servidor le da 30 s
  para cerrar (`stop_grace_period`).
- **Lo que manda un script de una sola vez** queda en la misma cola; si el
  script termina antes, lo copia el servidor. Nunca salen repetidas: cada copia
  la toma un solo proceso a la vez.
- **Aviso por ntfy** si Chatwoot lleva 15 min sin recibir, y otro cuando vuelve.
- **Lo único que se aparta** es lo que Chatwoot *rechaza* por sí mismo (HTTP 400,
  413, 415 o 422, tres veces; o un error raro de la copia, diez veces): si se
  reintentara para siempre taparía todo lo que viene detrás. Queda guardado con
  `apartada = 1` y su error, se avisa, y `vb diagnostico` lo muestra en «copias
  pendientes».

Antes del 07/10 la cola vivía en la memoria del proceso y una copia que no
entraba se perdía: así le pasó a la información de la cadena de una clienta.

El eco de una copia tardía no es problema: lo que copia el bot va firmado por el
agente bot «VentaBot», y además se recuerda otra vez justo al copiarlo, así que
nunca se confunde con algo que escribió Lía.

## Las notas privadas

Lo que el bot le cuenta a Lía y la clienta no ve: por qué escaló, qué
transcribió de una nota de voz, qué comprobante llegó, qué movió y con qué
resultado. Van marcadas con 🙋 🎤 🧾 💰.

## La app del celular

App **Chatwoot** → «usar tu propia instalación» → la dirección **https** del
túnel (la misma del bot). Funciona en la casa y en la calle.

- La app **rechaza direcciones `http`**: por eso el túnel reparte un solo
  dominio https entre el bot y el CRM.
- En el PC se puede seguir entrando por `http://localhost:3000`.
- El registro de cuentas nuevas está **apagado**: nadie de afuera se puede
  crear un usuario.

## El centro de mando: todo en una página

`/panel/todo` junta el estado de cada pieza —el bot, la cola de envío, la base,
el ERP, la última copia y lo que falta por revisar— y los enlaces a todo lo
demás: el taller, las conversaciones, Chatwoot, las métricas, el ERP y el
registro del servidor (`/panel/registro`, sin abrir ninguna ventana).

- Se abre con `VER-TODO.cmd` o `vb ver-todo`, que leen la llave del `.env` al
  vuelo: el acceso directo no la lleva escrita.
- Para el celular trae un **QR** (se dibuja en el propio servidor: el enlace no
  sale hacia ningún servicio de internet) y un botón de copiar.
- Está dentro del panel a propósito: hereda su llave, el `noindex` y el
  `no-referrer`, y el túnel ya manda `/panel…` al bot, así que el mismo enlace
  sirve en el PC y en el celular. Sin llave —o con una llave rara, como un «…»
  copiado a medias— responde 404, como el resto del panel.

Si nadie tiene el enlace a mano, está en la primera pestaña del ERP
(ver 08 · El ERP).

## Lo que hay que saber para no romperlo

- **Auto-asignación apagada.** Si se enciende, Chatwoot le asigna cada charla
  nueva a Lía y el bot se calla en todas.
- **El agente bot tiene que estar conectado al buzón.** Si no, Chatwoot le
  responde 401 y el bot no puede copiar nada.
- **`SAFE_FETCH_ALLOW_PRIVATE_NETWORK=true`.** Chatwoot 4.x no entrega webhooks
  a direcciones privadas, y el bot es una. Sin esto el CRM se ve bien pero nada
  de lo que hace Lía vuelve al bot.

Las tres las revisa `vb diagnostico` en cada corrida.

## Comandos

```bash
vb chatwoot --conectar
```

Deja el CRM configurado: buzón, agente bot, webhook, etiquetas, ficha,
respuestas rápidas, carpetas y macros. Es idempotente: se puede correr las veces
que haga falta.

```bash
vb ensayo
```

Ensaya la cadena completa WhatsApp → bot → Chatwoot → bot con una clienta
inventada, un segundo bot en el puerto 8001 y el modelo simulado: **no gasta ni
un peso y no toca a nadie**. 29 comprobaciones. El bot real sigue atendiendo
mientras tanto.

```bash
vb prueba-chatwoot
```

Lo que el ensayo no puede probar: que lo que Lía escribe en Chatwoot **llegue
al teléfono**. Usa el bot real y Meta de verdad, con el número de prueba
5700000000 77, y solo da por bueno el mensaje si Meta devuelve su `wamid`.
Borra su contacto al terminar.

```bash
vb ver-todo            # abre el centro de mando en este PC
vb ver-todo --enlace   # escribe el enlace para el celular
```
