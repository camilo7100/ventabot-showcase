# VentaBot — manual vivo

> **Qué es este archivo.** El retrato de VentaBot **tal como está hoy**: qué busca,
> qué logra, cómo está armado, qué protege cada pieza, qué NO hace y qué falta.
> No es una bitácora: aquí no va el historial de cambios (para eso están los ADR).
> **Si algo deja de ser verdad, se corrige aquí mismo, no se agrega debajo.**
>
> **Regla:** cualquier cambio en el modelo, en el prompt, en los precios o en las
> reglas que protegen la plata **se escribe aquí en el mismo momento**. Un dato
> viejo en este archivo hace más daño que no tenerlo. Al final está la lista de
> qué revisar cuando se cambia de modelo.
>
> Última revisión: **17/09/2026**.

---

## 1. Para qué existe

Lía vende por WhatsApp un solo producto: un **anillo de plata Ley 925 con las
huellitas de las mascotas de la clienta**, con circones de colores y los nombres
grabados por dentro. Antes contestaba ella, mensaje por mensaje, y las ventas se
caían cuando no alcanzaba a responder.

Desde el 03/10 hay un segundo producto, la **cadena con huellita y nombre**
($250.000, abono $65.000), que el bot **nunca ofrece**: solo la muestra si la
clienta pregunta por cadenas o por más productos ([R2p](sistema/03-reglas-de-negocio.md)).

VentaBot atiende esa conversación completa: cotiza, toma la talla, ayuda a
escoger colores, **dibuja cómo va a quedar el anillo**, arma el pedido, pide el
abono de $60.000 y recibe el comprobante.

**De esto dependen los ingresos de una persona.** Por eso el criterio no es
"que responda bonito" sino, en orden:

1. **No hacer daño**: no inventar precios, no dar un pedido por tomado sin abono,
   no confirmar un pago, no cambiar un anillo que ya se está fabricando.
2. **Cerrar la venta**: llegar al abono con el pedido bien tomado.
3. **Que se sienta una persona**: cálida, corta, que responda lo que le
   preguntaron y recuerde lo que ya dijo la clienta.

Lo que **no** es: no es un catálogo, no es un chatbot de preguntas frecuentes y
no es un agente libre. El modelo **propone**; Python **decide y escribe**.

---

## 2. Qué se obtiene hoy (medido, no estimado)

| Qué | Cuánto | Con qué se mide |
|---|---|---|
| Conversaciones completas correctas | **251/256 comprobaciones · 16/21 perfectas** (21/09, última corrida; las cuatro anteriores daban 247–248). Lo que falla es crónico y no toca la plata: la ciudad, en tres —el modelo la reconoce («Girón») pero no llena el campo; se le vuelve a pedir con los datos de envío. Arreglarlo es tocar el esquema de `Jugada`, que está al límite de lo que Claude acepta ([ADR 0026](adr/0026-lo-verde-tiene-que-estar-verde.md)): no vale el riesgo por esto—. El insulto de entrada, que fallaba desde el 17/09, ya pasa a Lía | `vb repasar` |
| Frases repetidas o casi repetidas | **0 repetidas · 7 casi repetidas** en 21 conversaciones (preguntas de cantidad, talla o nombre) | `vb repasar` (señales `repetidas` y `casi_repetidas`) |
| Traspaso a una persona | **probado**: contesta, calla mientras hay alguien, y vuelve | `tests/unit/test_traspaso_humano.py` |
| Costo por conversación completa | **~USD 0,04** (unos 160 pesos): USD 0,85 las 21 | el mismo repaso |
| Tiempo por respuesta | **~2,7 s** | el mismo repaso |
| Pruebas automáticas | **1565 en ~27 s** | `vb test` |
| Contratos de arquitectura | **4 intactos** | `vb arch` (import-linter) |
| Aciertos **sin** modelo (solo reglas) | **67,3 %** | `vb golden --solo-python` |
| Revisión de todo antes de arrancar | **29 OK**, 1 FALTA (el commit), 2 manuales | `vb preflight` |
| Diagnóstico de punta a punta (bot, túnel, CRM, claves, base, ERP, código, limpieza) | **39 revisiones en verde** | `vb diagnostico` |

**El punto de comparación:** con el gestor por etiquetas (el motor anterior, hoy
respaldo) esas mismas 7 conversaciones reales de Lía cerraban **0 ventas**.

**Cuidado con el puntaje.** El 17/09 el repaso daba 186/186 y aun así el bot
repetía "Quedo atenta al comprobante" cuatro turnos seguidos. **Hay que leer las
transcripciones** (`Documents\GitHub\material\repasos\<fecha>`), no solo el número.

---

## 2b. Qué está probado y qué NO

**Probado y en verde:**

| Prueba | Qué cubre | Resultado |
|---|---|---|
| 1565 pruebas automáticas | Reglas de negocio, precios, estados del pedido, contexto, guardias de la asesora, webhook y firma, panel, métricas, fletes, ventas/Excel, plantillas, fotos, Chatwoot (eco, firma, estados) | **Todas pasan** (~27 s), sin tocar ningún servicio real (ni Chatwoot ni el ERP: ADR 0026) |
| `vb repasar` (21 conversaciones) | 7 conversaciones **reales** de Lía + 14 casos difíciles inventados (desconfianza, duelo, queja, insulto, color inexistente, pago temprano, ráfaga de fragmentos, nota de voz, PDF, envío por adelantado, pide la cuenta sin pagar) | **251/256** el 21/09, sin respaldos ni errores |
| `vb verdad` (27 clientas, IA real) | Todas las etapas: talla dicha, regla, medida, cantidad, colores, grabado (con fecha, sin grabado), nombre, resumen, cambio después del resumen, cuentas, comprobante (foto, PDF, «ya transferí», $59.700, antes de tiempo), lo de Lía (talla, abono, listo, saldo, despacho), datos de envío, dos anillos, la cadena, la vitrina, objeciones, queja; ortografía mala, voz, mayúsculas, ráfagas | **122/122 y 120/120** el 04/10, las dos últimas corridas seguidas (tras arreglar los más de 10 errores reales que encontró), ~5 min, ~USD 0,04 |
| Punta a punta con el servidor real | Webhook firmado → asesora → pedido creado → envío con nombre y ciudad → Excel actualizado solo | **Pasa** |
| Arquitectura (import-linter) | Que el dominio no dependa de nada externo | **4 contratos intactos** |
| `vb preflight` | 32 revisiones antes de arrancar | **29 OK**, 1 falta (el commit), 2 manuales |
| `vb diagnostico` (21/09) | El sistema de verdad: servidor, túnel, Chatwoot, credenciales (que la API acepte el esquema de la asesora y que Meta deje escribir desde el número), base, ERP (y su pestaña CENTRO DE MANDO), código y limpieza. Corre solo al encender el bot | **39/39**, y deja línea en `logs/diagnostico.log` |
| Traspaso, avisos y notas de voz | Que el bot calle con una persona, que avise si se rompe, que oiga un audio | **Probados** (`test_traspaso_humano`, `test_chatwoot_vuelta`, `test_avisos`, `test_oidos`) |
| **WhatsApp de verdad** (19/09) | El número real +57 300 1110009 con mensajes desde un celular: entra, contesta, queda en Chatwoot | **Pasa** (y destapó el eco, ya corregido) |
| `vb ensayo` (19/09) | WhatsApp → bot → Chatwoot real → bot: firma «VentaBot», sin repetir, estados, asignar calla, resolver devuelve, «necesita-persona» | **29/29**, gratis (modelo simulado, sin Meta) |
| El PC como servidor (19/09) | Encender al iniciar sesión, levantarse solo si se cae, apagar de verdad, registro en archivo | **Pasa** (probado matando el servidor) |
| **Docker, como en la nube** (19/09) | Venta completa dentro del contenedor, reinicio sin perder datos, respaldo adentro, mudanza de la base real | **Pasa** |

**Probado y con resultado a medias (sirve como línea base, no como nota):**

- `vb golden --solo-python` = **67,3 %** (56,2 % en lo que cuesta dinero). Mide el **intérprete
  del motor viejo** sin modelo, no la asesora, y está afinado contra sus propios ejemplos: el
  número está inflado hasta que entren 30–40 mensajes nuevos de Lía.

**NO probado todavía (y hay que hacerlo antes de confiarle clientas de verdad):**

| Falta probar | Por qué importa |
|---|---|
| Varias clientas a la vez | Todo lo medido es una conversación por vez |
| Un día entero encendido | El PC ya quedó de servidor; falta verlo aguantar días con tráfico real |
| Fotos reales (no descritas) | En los repasos la foto se describe en texto; el modelo de visión no se ha medido con fotos de verdad |
| Reinicio a mitad de venta **con la asesora** | Está probado con el motor viejo, no con este |
| El Excel con cientos de ventas | Hoy se probó con pocas filas |

---

## 3. Cómo funciona un turno

```
WhatsApp → webhook (firma HMAC + dedup)
  → agrupador (un turno a la vez por conversación, fuera del hilo del servidor;
     junta la ráfaga con AGRUPAR_SEGUNDOS de calma; el primer mensaje no espera)
  → ASESORA:
      1. contexto     qué pedidos activos tiene, borrador, charla reciente
      2. Claude       lee y devuelve una JUGADA cerrada (Pydantic):
                      cambios · acciones · mensaje · confianza
      3. guardias     Python valida ANTES de aplicar (§5)
      4. aplicar      se escribe el borrador; lo rechazado vuelve como aviso
      5. acciones     precios, muestrario, guía de talla, ejemplos, "cómo queda",
                      resumen, cuentas, comprobante, pasar a Lía
      6. vigilar      se revisa el texto YA con el estado nuevo (§5)
      7. armar        resumen + mensaje + fichas + cierre
  → outbox → WhatsApp   ·   registro de decisión   ·   espejo en el CRM
```

Si GPT no contesta, contesta Claude; si ninguno contesta en ~35 s, la clienta
recibe una vez «Dame un momentico», el turno queda **pendiente** y el bot le
contesta solo cuando alguno vuelva (ADR 0027). **Nunca se cae a un modelo
local** (decisión de Camilo, §7).

---

## 4. Las piezas y para qué sirve cada una

### El corazón de la conversación

| Archivo | Qué hace | Por qué existe |
|---|---|---|
| `app/domain/asesora.py` | El **Borrador** del pedido, la **Jugada** que devuelve el modelo, `aplicar()` y `vigilar()`, y todas las guardias | Es dominio puro: no sabe de WhatsApp ni de Claude, y por eso se puede probar sin red |
| `app/conversacion/asesora.py` | El **turno**: ordena contexto → modelo → guardias → acciones → vigilancia → mensaje | Un solo sitio donde se decide el orden de las cosas |
| `app/prompts/asesora_v1.txt` | Cómo escribe Lía, el flujo de la venta, cómo llenar el borrador | El tono vive en un archivo de texto, no en el código |
| `app/conversacion/pipeline.py` | El gestor por etiquetas (respaldo) | Si la API se cae, la venta no se queda muda |
| `app/domain/cambios.py` | Qué se puede cambiar **según el estado del pedido** | Una clienta pidió cambiar colores de un pedido despachado; ninguna regla de lenguaje puede ser la única defensa |
| `app/domain/contexto.py` | Qué pedido está mirando la clienta, qué charla se le pasa al modelo | Sin esto el bot contesta del pedido equivocado |
| `app/domain/atencion.py` | **Si una persona escribe, el bot calla 12 h en esa conversación** ([ADR 0016](adr/0016-cuando-contesta-una-persona-el-bot-calla.md)) | Dos voces en el mismo chat rompen la venta |

### El negocio

| Archivo | Qué hace |
|---|---|
| `data/catalogo.csv` | Los 3 precios: 1 huellita **$200.000**, 2 **$250.000**, 3 **$300.000**; abono **$60.000**; 10–15 días |
| `data/fletes.csv` | **El único sitio** donde vive el precio del envío. Se edita con Excel, sin tocar código |
| `app/domain/faq.py` | Las cuentas para transferir y las respuestas fijas |
| `app/domain/personalizacion.py` | Colores válidos (los 14 del muestrario, con nombre, tinte y acabado —facetas, reflejos, fuego— editables en el panel → Colores con vista en vivo, tabla `colores_circon`; los tintes de fábrica, **medidos en la foto** con `vb muestrario`; el bot entiende el nombre nuevo sin tocar código: `colores_texto.sinonimos_vigentes`), grabado (hasta 5 nombres, admite `♡ ∞ & / ( )`, 30 caracteres) |
| `app/domain/tallas.py` | Talla a partir de milímetros medidos en la foto de la regla |
| `app/domain/pricing.py` | Precio, abono y saldo. **Ningún número sale del modelo** |

### Pedidos, ventas y operación

| Archivo | Qué hace |
|---|---|
| `app/domain/order_state.py` | Los 14 estados del pedido (de `BORRADOR` a `ENTREGADO`) |
| `app/domain/ventas.py` · `app/adapters/repositories/ventas.py` | La base de ventas: anotaciones, bitácora append-only, sincronizaciones |
| `app/adapters/excel/libro_ventas.py` | El Excel de Camilo (hojas Ventas, Clientas, Diccionario, Registro) |
| `app/domain/anuncios.py` | **De qué anuncio llegó** la clienta (el `referral` de Meta en su primer mensaje): primer y último anuncio en la clienta; el pedido nace con el último si fue hace menos de 28 días; columnas «Anuncio» en el Excel para el costo por venta de cada anuncio ([ADR 0028](adr/0028-de-que-anuncio-llego-y-a-cual-se-le-cuenta-la-venta.md)) |
| `app/workers/ventas.py` | Regenera el Excel cada `VENTAS_CADA_S` (120 s) **solo si algo cambió** |
| `app/api/panel.py` | El panel: el taller, las conversaciones (`/panel/chats`), las **métricas** (`/panel/metricas`: negocio y bot, hoy / 7 / 30 días), el **centro de mando** (`/panel/todo`: el estado de cada pieza y todo a un clic, con QR para el celular) y el **registro** del servidor (`/panel/registro`) |
| `app/infra/centro_de_mando.py` | Lo que el bot escribe de sí mismo en la primera pestaña del ERP (CENTRO DE MANDO): dónde corre, su dirección, los enlaces y «visto vivo». Sin claves de afuera (ADR 0025) |
| `app/domain/seguimiento.py` | La etapa y las alertas de cada conversación (Chatwoot), y las acciones `hacer-…` |
| `Container.mover_pedido` | EL camino para mover un pedido: regla del 100 %, transición, montos, aviso, memoria del bot, Chatwoot, ERP |
| `app/domain/erp.py` · `app/adapters/erp/sheets.py` | El ERP en Google Sheets: Ventas, Pagos y Producción se llenan solos (`vb erp`) |
| `app/adapters/repositories/tablero.py` | Los números del tablero, sacados de la base local: sin textos ni teléfonos |
| `app/api/main.py` → `/webhook/chatwoot` · `app/infra/quien_atiende.py` | Quien está asignado es quien atiende (09/10): lo que se escribe desde Chatwoot sale a la clienta, se asigna a quien escribió y calla al bot; asignarla a una persona la calla antes; «Ninguna», VentaBot o `hacer-devolver-al-bot` la devuelven; «Resolver» solo cierra; ignora lo firmado por el agente bot «VentaBot» |
| `app/adapters/crm/chatwoot.py` · `cola.py` | Copia cada mensaje a Chatwoot (el del bot, firmado «VentaBot») desde una cola en la base que no se rinde nunca; pone etiquetas, ficha del pedido y asignación: VentaBot («Pendiente») o una persona («Abierta»); lo que necesita a alguien, Urgente |
| `scripts/ensayo_chatwoot.py` → `vb ensayo` | Ensayo de punta a punta contra el Chatwoot real con un bot de ensayo en :8001 (modelo simulado, sin Meta, base temporal) |
| `scripts/prueba_de_verdad.py` → `vb verdad` (04/10) | LA prueba de verdad: 27 clientas inventadas (`scripts/verdad/escenarios.py`) conversan con la IA REAL en el servidor, aisladas (base temporal, consola, sin Chatwoot/ERP/avisos). Las compradoras contestan a lo que el bot pregunta (`compradora.py`); hace de Lía (talla, abono, listo, saldo, despacho); califica cada mensaje con las reglas de siempre y cada etapa (`revisiones.py`). Las fotos (comprobantes, regla) en `fotos.py`. Sale con error si algo falla: ningún cambio del flujo se despliega sin que pase |
| `scripts/prueba_desde_chatwoot.py` → `vb prueba-chatwoot` | Lo mismo pero contra el bot REAL y contra Meta: Lía escribe desde Chatwoot y se comprueba que Meta devuelve un `wamid`, que es lo único que demuestra que llegó al teléfono. Usa el número de prueba 5700000000 77 y borra su contacto al terminar |
| `scripts/respaldo.py` | Copia la base y el Excel (`vb respaldo`); corre solo cada noche |
| `scripts/reiniciar_chats.py` → `vb reiniciar` | Borra las charlas de prueba (CRM y base) después de respaldar. No toca catálogo, fletes, ERP ni la configuración de Chatwoot. El Excel no lo toca él, pero lo regenera el bot desde la base: con `--pedidos`, los pedidos borrados desaparecen también de ahí (el respaldo guarda el Excel de antes) |
| `scripts/diagnostico.py` → `vb diagnostico` | EL diagnóstico: 8 áreas, 39 revisiones, y una ventanita con el resultado |
| `app/domain/catalogo_meta.py` → `/catalogo/whatsapp.csv` | El catálogo del perfil de WhatsApp (catálogo «Luna Joyas», 1234567890123456, conectado el 03/10, sin carrito): Commerce Manager lo lee cada día de `data/catalogo.csv` (mismos precios que cobra el bot; la foto la dice `imagen_url`). Si la clienta escribe desde un producto, `con_el_producto` le dice al bot cuál (R2p) |
| `app/domain/salud_meta.py` | Si Meta deja escribir desde el número (método de pago, verificación): lo usan `vb diagnostico` y `vb plantillas` |
| `scripts/ver_todo.py` → `vb ver-todo` · `VER-TODO.cmd` | Abre el centro de mando con la llave del `.env` (el acceso directo no la lleva escrita); `--enlace` da el del celular |
| `ngrok.yml` · `scripts/tunel.cmd` | El túnel: UN dominio https para el bot (`/webhook`, `/panel`, `/media`, `/health`) y para Chatwoot (lo demás; la app del celular exige https). En bucle: si se cae, se reabre |
| `scripts/servidor-en-bucle.cmd` | El servidor de producción: si se cae, se vuelve a encender a los 10 s. Lo abre `ENCENDER-BOT.cmd`, que corre solo al iniciar sesión (tarea *VentaBot-encender-al-iniciar*) |
| `logs/servidor.log` | El registro auditable del servidor (rota a 5 MB × 5) |
| `Dockerfile` · `.dockerignore` · `docker-compose.yml` | El bot listo para un servidor: sin privilegios, sin secretos ni datos en la imagen, datos en un volumen, túnel ngrok o Cloudflare ([guía](DESPLIEGUE-EN-LA-NUBE.md)) |
| `app/adapters/llm/oidos.py` | Pasa una nota de voz a texto (Whisper en Groq). Si falla, se le pide por escrito: nunca tumba el turno |
| `app/adapters/avisos.py` | Avisa al celular si el token caducó o un mensaje no salió (ntfy o Telegram). Nunca repite el mismo aviso ni lleva datos de clientas |
| `app/domain/recordatorios.py` · `app/workers/recordatorios.py` | Le escribe a quien se quedó a medias ANTES del abono: uno útil, uno antes de que se cierre su ventana y uno con plantilla a los 3 días; de día, nunca si dijo que no ([ADR 0017](adr/0017-recordar-antes-del-abono-sin-acosar.md)). `vb recordatorios` dice a quién le toca |
| `app/workers/outbox_dispatcher.py` | Nada se manda "en el momento": todo pasa por la outbox, con reintentos |

### Entrada y salida

`app/api/main.py` (webhooks firmados), `app/adapters/channels/whatsapp.py`,
`app/adapters/llm/anthropic_client.py` (Claude), `app/adapters/render/huellita.py`
(el dibujo de cómo va a quedar: el cuerpo de cada piedra da exacto el color
del panel), `app/adapters/crm/chatwoot.py` (espejo, nunca canal),
`app/infra/container.py` (arma todo y decide qué implementación entra).

---

## 5. Lo que protege la plata (cada regla, y por qué existe)

Todas están en Python, con prueba propia en `tests/unit/test_asesora.py`.
**Cada una nació de una conversación real que salió mal.**

| Regla | Qué impide | Dónde |
|---|---|---|
| `cantidad_respaldada` | Que un "sí" a "¿1 o 2 huellitas?" fije una cantidad. **La cantidad cambia el precio: nunca se supone** | `domain/asesora.py` |
| `cambia_la_cantidad` | Que un pedacito de una ráfaga ("una huella negra") baje a 1 un anillo de 2 | ídem |
| `habla_de_una_sola_huellita` | Lo contrario: "toda la huellita en el mismo tono" **sí** es un anillo de 1 (así lo lee Lía) | ídem |
| Resumen antes de cobrar | Que se cree el pedido y se manden las cuentas con un diseño que la clienta **no ha visto** | `conversacion/asesora.py` |
| `_PEDIDO_TOMADO` | "Ya tomé tu pedido", "ya queda lista tu orden", "listo para el taller" **sin abono reportado** | `domain/asesora.py` |
| `_CUENTAS_YA_DADAS` | "Ya te pasé los datos" cuando nunca se mandaron | ídem |
| `_PROMESAS_PROHIBIDAS` | Confirmar o verificar un pago. **Eso lo hace una persona** ([ADR 0011](adr/0011-el-pago-lo-confirma-una-persona.md)) | ídem |
| Montos permitidos | Cualquier cifra que no salga del estado del pedido (precio, abono, saldo, envío) | `vigilar()` |
| `_CUENTA` | Que el modelo escriba un número de cuenta o un teléfono. **Los escribe Python** | ídem |
| `_INVENTOS` | Instagram, enlaces, "llevamos X años", "cientos de clientas" | ídem |
| `parece_descripcion` | Grabar "gato pantera" o "una gata calico": son descripciones, no nombres. Pregunta cómo se llama | ídem |
| Nombre de la clienta | Que su nombre termine grabado dentro del anillo | `_validar_grabado` |
| Colores del muestrario | Un color que no existe (dorado, café, gris): ofrece el parecido | `aplicar()` |
| `_COLOR_FUERA_DEL_MUESTRARIO` | Que el bot le confirme como piedra un nombre que no es de ninguna bolsita («verde menta», «turquesa», «dorado»). Pasa si es la guía («no tenemos…», «el más parecido es…», «se llama…») | `vigilar()` |
| `_cantidad_que_no_es` | Que al CONFIRMAR el pedido diga otra cantidad de huellitas que la del pedido («déjame confirmar: 1 huellita» con 2 en el resumen). Ofrecer opciones sí puede | `vigilar()` |
| Cuentas antes de la talla de Lía | Mandar los datos del abono con el pedido incompleto (la talla por confirmar, el resumen) si ella no las pidió | `_mandar_cuentas` |
| Nombres al pie de la vista | Cada «así se te va a ver» lleva el nombre de la bolsita de cada piedra (`nombres_de_los_colores`), no el que inventó el modelo | `conversacion/asesora.py` |
| `pasar_a_lia_sin_motivo` | Llamar a Lía solo porque la clienta dio su nombre | `domain/asesora.py` |
| `falta_para_abono` al 100 % | Pedir el abono sin **talla, nombre, ciudad y dirección** ([ADR 0018](adr/0018-el-pedido-al-cien-por-ciento-y-chatwoot-como-centro.md)) | `domain/asesora.py` |
| `pagado_sin_pedido` | Que un pago con el pedido incompleto se pierda: queda **por revisar**, con alerta `datos-incompletos`, y el pedido nace apenas se completa | `conversacion/asesora.py` |
| `PedidoIncompleto` | Que un pedido sin todos sus datos entre al taller (desde el panel o Chatwoot) | `domain/operacion.py` · `Container.mover_pedido` |
| Abono una sola vez | Volver a mandar las cuentas del abono después del comprobante | `conversacion/asesora.py` |
| `_ESPERA_PAGO` | «Quedo atenta al comprobante» sin haber mandado las cuentas | `domain/asesora.py` |
| `_EN_TALLER` · `_DESPACHADO` | «Está en el taller» con el anillo listo; «ya se despachó» sin despachar | ídem |
| `_ARRANCA_EL_TALLER` | «Tu pedido entra al taller ahora mismo», «en 10 a 15 días te comparto las fotos» **sin abono**. Como condición («apenas hagas el abono…») sí pasa | ídem |
| `habla_de_pago` | Registrar un pago sin comprobante ni un «ya pagué» **explícito y en pasado**. «Cuenta», «voy a transferir», «los pago cuando esté listo», «no he hecho el pago» **no** son un pago | ídem |
| `_ACUSA_RECIBO` | «¡Recibido!» sin que haya llegado un comprobante ni diga que ya pagó. Sin pago, el cierre es «Quedo atenta a tu comprobante 💓 Cualquier duda, me cuentas 🫶» (`QUEDO_ATENTA`), una vez | `domain/asesora.py` · `conversacion/asesora.py` |
| `pide_las_cuentas` | Negarle las cuentas porque «se mandaron hace un turno» cuando ella las pide con todas las letras («Cuenta», «¿a qué Nequi?») | ídem |
| `_ENVIO_CON_EL_ABONO` | Sumar el envío al abono. Si ella pide pagarlo antes, va **con el saldo** (`envio_con_saldo`), y eso lo escribe Python | ídem · `conversacion/asesora.py` |
| Saldo registrado | Que el comprobante del saldo se ignore: pasa a revisión y queda la nota «Verificar SALDO» | `_recibir_comprobante` |
| Botones del pago en revisión | Dar por pagado el saldo de un anillo que ni se empezó: solo salen los del pago que se revisa | `acciones_de` |
| Política por estado | Cambiar colores de algo que ya está en producción | `domain/cambios.py` |
| `contar_anillos` · `pasar_al_siguiente` | Con varios anillos: mezclar los datos de uno con otro, pasar al siguiente con uno a medias, o cobrar anillo por anillo. Se describen de a uno; es UN pedido con un abono y un saldo de todos ([R2n](sistema/03-reglas-de-negocio.md)) | `domain/asesora.py` |
| `unir_grabados` | Un ♡ colgando al final del grabado: van siempre ENTRE los nombres ([R2o](sistema/03-reglas-de-negocio.md)) | `domain/personalizacion.py` |
| `pregunta_por_cadenas` · `quitar_cadena_no_pedida` | Ofrecer la cadena sin que ella pregunte: la acción se rechaza y la frase se quita del mensaje ([R2p](sistema/03-reglas-de-negocio.md)) | `domain/asesora.py` |

**Cuando el mensaje no se puede mandar** (miente, se queda vacío tras vigilarlo,
repite casi igual algo de los 3 mensajes anteriores, o habla de una cantidad que
no quedó), **no se suelta una frase fija**: se le pide al modelo otro texto
(`MensajeReescrito`) con el motivo y el estado real, y esa reescritura pasa por
la misma vigilancia. Las frases fijas eran lo que más sonaba a robot.

---

## 6. Límites (lo que hoy NO hace, y si es por decisión o por falta)

**Por decisión, y conviene que siga así:**

- **No confirma pagos.** Marca el comprobante como `EN_REVISION_PAGO` y Lía mira el banco.
- **No promete fechas exactas** ni descuentos.
- **No cambia la cantidad de huellitas de un pedido ya creado**: eso lo decide Lía (cambia el precio). Tampoco agrega ni quita anillos a un pedido creado.
- **Con varios anillos, desde el chat solo se corrige el último**; los anteriores (o la talla y el grabado desde Chatwoot) se corrigen en el panel, anillo por anillo.
- **Los recordatorios solo van ANTES del abono** y solo a quien escribió al menos dos mensajes:
  máximo tres por silencio, solo a las 9 a. m. o a las 5 p. m., nunca si dijo que no ni si la atiende una persona ([ADR 0017](adr/0017-recordar-antes-del-abono-sin-acosar.md)).
- **No contesta encima de una persona.** Quien escribe a mano —desde el panel o desde Chatwoot— queda asignado en Chatwoot y lo calla en esa conversación (también al asignársela); vuelve cuando se la quitan («Ninguna»), con «que siga el bot», la macro «🤖 Devolver al bot», o solo si pasan 12 horas sin que la persona escriba. **Resolver no lo devuelve** (09/10).
- **No dice la dirección de la casa de Lía**: solo Floridablanca y el nombre del conjunto para recoger ([R17](sistema/03-reglas-de-negocio.md)).
- **No inventa nada del negocio**: si no está en los hechos, no lo sabe.
- **El modelo no escribe números.** Precios, cuentas y resumen los pone Python, verbatim.

**Limitaciones de verdad (se pueden levantar, hoy no están):**

- **Las notas de voz ya se pueden transcribir**, pero está **apagado** hasta que haya clave:
  con `TRANSCRIPCION_BACKEND=groq` + `GROQ_API_KEY` la clienta puede hablar y la venta sigue
  (~US$0,04 por hora de audio). Sin clave, contesta "¿me lo escribes?" como antes.
- **No lee PDF**: lo trata como comprobante para que no tumbe el turno.
- **Los adornos del grabado se usan y se tiran.** Lía graba "Paz ♡ 05/01/2025"; hoy los símbolos
  sirven para separar nombres pero no se guardan como campo propio. Pide un campo nuevo en
  `Personalizacion`, no un parche en el intérprete.
- **Una sola clienta a la vez por conversación**: no hay pedidos múltiples simultáneos en la misma charla más allá de lo que resuelve el contexto.
- **El repaso es estocástico.** El mismo escenario puede variar entre corridas; por eso se exige
  **dos corridas completas limpias** antes de dar algo por bueno.
- **El golden está afinado contra sí mismo**: el 67,3 % está inflado hasta que entren 30–40 mensajes nuevos de Lía.

---

## 7. Modelos: qué se usa hoy y por qué

Dos proveedores en cadena (29/09, [ADR 0027](adr/0027-gpt-primero-claude-de-respaldo.md)):
si el primero no contesta, el otro, en vueltas de ~35 s; después el turno
queda pendiente y se reintenta solo.

| Capa | Primero (GPT) | Respaldo (Claude) | Para qué |
|---|---|---|---|
| Básico | `gpt-6-luna`, esfuerzo `none` | `claude-haiku-5-5` (desde el 12/10; antes Haiku 4.5) | Todos los turnos |
| Fuerte | `gpt-6-luna`, esfuerzo `low` | `claude-sonnet-5-5` | Solo cuando la jugada viene con confianza **BAJA** |
| Fotos | igual que el básico / el fuerte | `claude-haiku-5-5` / `claude-sonnet-5-5` | Comprobantes, la regla de la talla, fotos de mascotas |

Precio de lista por millón de tokens (entrada/salida): luna USD 0,10 / 0,50;
Haiku 5.5 0,10 / 0,50 (desde el 12/10; Haiku 4.5 era 1 / 5); Sonnet 5.5 2 / 10. Medido
con la misma conversación de 10 mensajes (29/09, con Haiku 4.5): luna sin razonar
~US$0,002 (con la caché de 24 h) y flujo limpio; Haiku 4.5 US$0,052, repitió preguntas e
inventó un plazo de entrega. En fotos, luna leyó bien un comprobante de $60.000
que Haiku leyó como $60.000.000.

**La caché:** el prompt de la asesora (~9.200 tokens, fijo mientras el bot vive)
va primero y lo variable del turno después, así que ~99 % de lo que lee la IA
sale de caché, a la décima parte del precio. En GPT dura 24 h
(`RETENCION_DE_CACHE` en `app/adapters/llm/openai_client.py`, sin costo
extra). **Nada que cambie en cada turno puede ir en el prompt del sistema**: rompe
la caché sin avisar. El diagnóstico lo vigila («la caché de la IA», con los
turnos reales de las últimas 24 h).

**VentaBot trabaja SOLO con modelos en línea de pago.** Sin claves no se cae a
ningún modelo local: contestan las reglas y se registra el error
(`tests/unit/test_sin_ollama.py` lo mantiene así).

**En las pruebas lo que importa no es la marca del modelo**, sino que razone bien
con el contexto y el flujo programados. Cambiar a otro proveedor en línea (por
ejemplo DeepSeek) es cambiar el adaptador y volver a medir: la lógica de negocio
no se toca.

---

## 8. Configuración que de verdad importa

En `.env` (nunca se sube a ningún lado, nunca se muestra en pantalla):

| Variable | Hoy | Qué cambia |
|---|---|---|
| `CONVERSACION_MOTOR` | `asesora` | `pipeline` vuelve al gestor por etiquetas |
| `LLM_BACKEND` | `claude` | `fake` = sin modelo (pruebas) |
| `IA_PRINCIPAL` / `LLM_RESPALDO_BACKEND` | `openai` / `openai` | Quién va primero; vacío el segundo = un solo proveedor (en producción, en `docker-compose.yml`) |
| `OPENAI_MODELO` / `OPENAI_ESFUERZO` (y `_FUERTE`) | `gpt-6-luna` `none` / `gpt-6-luna` `low` | GPT y cuánto razona |
| `LLM_BASICO_MODEL` / `LLM_FUERTE_MODEL` | Haiku 5.5 / Sonnet 5.5 | Claude, el respaldo |
| `LLM_VISION_MODEL` | `claude-haiku-5-5` | El Claude de las fotos (con GPT delante) |
| `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` | en el `.env` | Solo en el `.env` del servidor y del PC; nunca en GitHub |
| `TRANSCRIPCION_BACKEND` | `ninguno` | `groq` + `GROQ_API_KEY` = se oyen las notas de voz |
| `AVISOS_BACKEND` | `ninguno` | `ntfy` = avisa al celular cuando algo se rompe (el tema ya está en el `.env`) |
| `RECORDATORIOS` | `true` (04/10) | Le escribe a quien se quedó a medias antes del abono (ADR 0017) |
| `RECORDATORIO_CON_PLANTILLA` | `false` hasta que Meta apruebe `retomar_diseno` | `true` = suma el de los 3 días |
| `CHATWOOT_URL` / `CHATWOOT_WEBHOOK_TOKEN` | listos | La bandeja para atender a mano desde el celular |
| `VENTAS_EXCEL` | `Documents\Luna Joyas\Ventas_LunaJoyas.xlsx` | Dónde se escribe el Excel |
| `VENTAS_CADA_S` | `120` | Cada cuánto se regenera |
| `AGRUPAR_SEGUNDOS` | `0` (producción `20`, desde el 12/10) | Calma que se espera para juntar la ráfaga |
| `AGRUPAR_TOPE_SEGUNDOS` | `15` (producción `60`) | Lo más que se espera desde el primer mensaje |
| `VENTANA_RECIENTE_HORAS` | `12` | Qué se considera "la charla reciente" |

---

## 9. Los datos: dónde viven y qué no sale del PC

- **SQLite** (`data/ventabot.db`) es la fuente de verdad: pedidos, clientas, contexto, decisiones, ventas.
- **El Excel es una vista.** Las columnas grises las llena el sistema (bloqueadas); las **verdes son de Camilo**
  (costo material, costo envío real, fuente, etiqueta, notas) y vuelven a la base con bitácora.
  Si el archivo está abierto, se reintenta; nunca se pisa a medias (escritura atómica).
- **`Documents\GitHub\material\`** (escenarios y repasos) tiene **nombres y mensajes de clientas reales**:
  vive **fuera del repo** y no se sube a ningún lado.
- **Nada de esto sale del computador.** No hay despliegue, no hay remoto de git, y los mensajes de
  prueba nunca van a clientas reales.

---

## 10. Cómo se opera (los comandos que se usan)

```bat
ENCENDER-BOT.cmd REM el bot de producción (servidor que se levanta solo + túnel); también al iniciar sesión
APAGAR-BOT.cmd   REM lo apaga de verdad
vb ensayo        REM ensayo WhatsApp → bot → Chatwoot de punta a punta, gratis
vb prueba-chatwoot  REM Lía contesta desde Chatwoot y sale a WhatsApp de verdad
vb ver-todo      REM el CENTRO DE MANDO: todo en una página (--enlace para el celular)
vb erp           REM el ERP en Google Sheets (--sincronizar, --montar, --importar-sabana X.xlsx)
vb trazas        REM ¿llegan las trazas a LangSmith?
vb server        REM el servidor solo, para desarrollar
vb respaldo      REM copia la base y el Excel (--listar para ver las copias)
vb reiniciar     REM borra las charlas de prueba (respalda antes)
vb diagnostico   REM REVISA TODO y dice como quedo (--rapido sin tests)
make up          REM el bot en Docker, igual que en el servidor (make down / make logs)
vb test          REM todas las pruebas
vb check         REM lint + tipos + arquitectura + pruebas, todo junto
vb preflight     REM ¿está todo listo para trabajar? (dice qué falta y con qué comando)
vb repasar       REM repasa las conversaciones de verdad contra el bot y las puntúa
vb ventas        REM regenera el Excel de ventas a mano
vb metricas      REM qué decidió el bot y con qué capa de modelo (en el celular: panel → métricas)
vb panel         REM abre el panel de Lía
SUBIR-MARKETING.cmd REM sube la carpeta de marketing al panel (/panel/marketing, 8 pestañas)
```

---

## 11. Cómo se cambia algo sin romper la venta

1. **Si lo que falló cuesta dinero o confianza** (una cifra, un pago, un dato del pedido):
   la corrección va **en Python con su prueba**. El prompt no es una defensa.
2. **Si fue tono o manera de preguntar**: va en `app/prompts/asesora_v1.txt`.
3. **Una conversación que salió mal se vuelve un escenario**, no una regla nueva:
   se copia un JSON de `material\escenarios\`, se pegan los mensajes y se escribe lo esperado.
4. **Nunca se toca el prompt sin volver a correr `vb repasar` completo**: un arreglo para una
   conversación rompe otra.
5. **Se leen las transcripciones**, no solo el puntaje.
6. Una decisión de arquitectura nueva se escribe como **ADR** en `docs/adr/` (uno por decisión,
   y el viejo no se edita: se reemplaza).

### Checklist cuando se cambia de modelo (o de proveedor)

- [ ] Cambiar `LLM_BASICO_MODEL` / `LLM_FUERTE_MODEL` / `LLM_VISION_MODEL` en `.env`.
- [ ] `vb test` (las pruebas no usan red: si fallan, el problema es de código, no del modelo).
- [ ] `vb repasar` **dos veces seguidas**, ambas limpias, y **leer** al menos dos transcripciones.
- [ ] Mirar costo y latencia en el resumen del repaso.
- [ ] Prueba de punta a punta con el servidor real (webhook → pedido → Excel).
- [ ] **Actualizar en este archivo**: la tabla del §2 (lo medido), la del §7 (modelos y precios) y,
      si cambió alguna regla, la del §5.

---

## 12. El camino hasta que venda solo

**Hoja de ruta (resumen).** El mapa de fases:

| Fase | Qué falta | Estado |
|---|---|---|
| F2 | Datos del negocio: cuentas, **fletes reales**, política de talla, quién mira el banco | ⬜ **bloquea todo** |
| F3 | Bandeja para atender a mano desde el PC y el celular (Chatwoot autohospedado, gratis) | 🟨 conectada en el PC; falta la app del celular |
| F4 | Conectar WhatsApp de verdad (token, webhook, plantillas) | ✅ número real atendiendo; plantillas en revisión |
| F5 | Piloto vigilado, 2–3 semanas con clientas reales | 🟨 empieza ya |
| F6 | Recordatorios, notas de voz, aviso de "está listo" | ⬜ |
| F7 | Servidor siempre encendido, alarmas y respaldos | 🟨 el PC es el servidor (se enciende y se levanta solo); la nube cuando Camilo decida |
| F8 | Mejora continua midiendo | 🔁 |
| — | Pago automático | ⏸️ **aparcado**: el flujo es pequeño y se verifica a mano |

**Siempre va a necesitar una persona:** fabricar el anillo, mandar las fotos de cómo quedó,
despachar y resolver un reclamo.

---

## 13. Dónde está lo demás

| Archivo | Para qué |
|---|---|
| `README.md` | La entrada rápida al repo |
| `INSTRUCTIVO-PARA-CAMILO.md` | Lo que falta hacer **a mano**, paso a paso |
| `docs/adr/` | **Por qué** se decidió cada cosa. Lo más valioso del repo |
| `MANUAL-DE-ATENCION.md` | **El manual de quien atiende** (Lía): entrar desde el celular, las 22 etiquetas una por una, las carpetas, tomar y devolver una charla, los 5 botones, qué hacer en cada escenario y qué mensajes recibe la clienta |
| `docs/sistema/` | **Cómo funciona HOY**: flujo, arquitectura real, reglas, estados, Chatwoot, datos, observabilidad, ERP y glosario. Lo vigila `tests/unit/test_documentacion.py` |
| `docs/ARQUITECTURA_CONTEXTO.md` | El detalle del motor de respaldo y del contexto |
| `docs/REGLAS_NEGOCIO.md` | Las reglas del negocio en un solo sitio |
