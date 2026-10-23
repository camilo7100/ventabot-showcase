# 07 · Cómo se vigila

Un bot que atiende solo tiene un modo de fallar peor que caerse: **funcionar a
medias sin que nadie se entere**. Pasó el 19/09 — Chatwoot dejó de entregar sus
webhooks y por fuera todo se veía bien. Esto es lo que hay para que no se
repita.

---

## 1. El diagnóstico — `vb diagnostico`

Revisa el sistema **de verdad**: no lee la configuración, la usa. 38
comprobaciones en ocho áreas:

| Área | Qué comprueba |
|---|---|
| 1 · El bot | Que responda, que la bandeja esté al día, **que el servidor vivo sea el del código de ahora**, **que no haya dos servidores**, y que el panel pida contraseña |
| 2 · El túnel | Que ngrok corra, que el dominio publicado sea el del `.env`, y que el bot y Chatwoot se vean desde internet |
| 3 · Chatwoot | Los 4 contenedores, el token, el webhook, el buzón, la auto-asignación, la red privada permitida, los webhooks entregados, la firma del bot y las 23 etiquetas |
| 4 · Credenciales | Meta, GPT, Claude, LangSmith, Groq y Google — puestas, y ninguna dentro de Git. **Quién contesta** (GPT → Claude), **que GPT y Claude acepten el esquema** con el que piensa la asesora (una llamada de verdad a cada uno) y **que la caché funcione** (con los turnos reales de 24 h) |
| 5 · Los datos | Que la base esté sana, qué hay dentro, que haya respaldo reciente, catálogo y fletes |
| 6 · El ERP | Que la hoja abra, que tenga Ventas, Pagos y Produccion, y que esté la pestaña CENTRO DE MANDO |
| 7 · El código | Tests, estilo y arquitectura |
| 8 · Limpieza | Que los registros no se desborden y que no haya errores recientes |

**Corre solo cada vez que se enciende el bot** (`ENCENDER-BOT.cmd`, en modo
`--rapido`, que salta los tests) y saca una ventanita diciendo cómo quedó. Cada
corrida deja una línea en `logs/diagnostico.log`, así se puede ver qué cambió
entre una jornada y la anterior.

```bash
vb diagnostico            # todo (unos 40 s)
vb diagnostico --rapido   # sin tests ni lint (unos 10 s)
vb diagnostico --ventana  # además, la ventanita
```

Devuelve 0 solo si no hay nada roto. **Si algo sale en rojo, el bot no está
listo para atender.**

**Por qué prueba el esquema contra la API.** El 20/09 un campo de más en
`Jugada` hizo que la API contestara «Schema is too complex» a **todas** las
llamadas. El bot arrancaba, el diagnóstico daba verde y las pruebas pasaban
—ninguna llama a la API—; lo único que se veía era que cada clienta recibía
«Dame un momentico». Además, la primera llamada con un esquema nuevo tarda
~60 s en compilarse (2 s las demás): el calentamiento del arranque tiene
`ESPERA_AL_CALENTAR_S` para pagar esa primera vez, porque con el tope de las
clientas (10 s) se rendía antes y la gramática no se guardaba nunca.

## 2. El ensayo de punta a punta — `vb ensayo`

El diagnóstico dice que las piezas están. El ensayo dice que la **cadena
completa** funciona: WhatsApp → bot → Chatwoot → bot, con el Chatwoot de verdad
y sus webhooks, su agente bot y sus estados.

29 comprobaciones, entre ellas: que lo de la clienta aparezca una sola vez, que
el bot no se calle por su propio eco, que «Asignar a mí» lo calle, que lo que
Lía escribe salga hacia la clienta, que «Resolver» se la devuelva y que una
etiqueta `hacer-abono-ok` mueva un pedido de verdad.

**Gratis y sin tocar a nadie**: levanta un segundo bot en el puerto 8001, con
el modelo simulado, el canal de consola y una base temporal; usa una clienta
inventada y la borra al terminar. Devuelve el webhook al bot real pase lo que
pase.

## 3. LangSmith — cada turno, auditable

Encendido en producción (proyecto **`ventabot`**, `LANGSMITH_*` en el `.env`
del servidor). **`vb diagnostico` comprueba que de verdad llegan** (12/10): le
pregunta a LangSmith cuántas trazas «turno» recibió en las últimas 24 h y las
compara con los turnos de la base; si hubo turnos y no llegó ninguna, «ojo»
(«LangSmith recibe los turnos»). `vb trazas` manda una de prueba. En las pruebas y los ensayos está apagado a propósito: ahí solo
llegan conversaciones de verdad. El código vive en `app/infra/trazas.py`.

Cada turno queda grabado con lo que entró, cada llamada al modelo, lo que
decidió y lo que respondió. **Threads** agrupa los turnos por clienta
(`thread_id` = la conversación), con tokens y costo.

**Qué traza es cada cosa**

| Traza | Qué es |
|---|---|
| `turno` | Un mensaje (o ráfaga) de una clienta, de punta a punta |
| `turno_pendiente` | Un turno que ninguna IA pudo contestar, reintentado cuando volvió |
| `calentar_ia` | El calentamiento al arrancar el bot (una por arranque) |
| `modelo` (dentro) | Cada llamada a GPT o Claude: proveedor, modelo, tokens sin caché / de caché / salida, y su capa |
| `mirar_foto` (dentro) | Cuando la IA mira una foto (comprobante, regla, mascota) |

**Filtros útiles (etiquetas)**

| Etiqueta | Para encontrar… |
|---|---|
| `respaldo` | Turnos que contestó **Claude** porque GPT no respondió |
| `reintento` | Turnos en que la IA tuvo que insistir antes de contestar |
| `pendiente` | Turnos retomados después de una caída |
| `escalado` | Turnos que pasaron a Lía |
| `corregido` | Turnos en que Python corrigió lo que propuso el modelo |
| `capa:basico`, `capa:potente`, `capa:apertura`… | Quién decidió el turno (el modelo básico, el potente o las reglas) |
| `llamada:basico`, `llamada:fuerte`, `llamada:reescribir`, `llamada:vision`… | Una llamada al modelo en particular, dentro del turno |
| `pedido:ESPERANDO_ANTICIPO`… | El estado del pedido en ese turno |
| `nota-de-voz` | Turnos con audio transcrito |

Los metadatos del turno (acción, lectura del modelo, confianza, pedido, lo que
Python corrigió, costo) sirven para buscar, por ejemplo, «las conversaciones
que acabaron en LLAMAR_HUMANO».

```bash
vb trazas     # comprueba que está grabando
```

Sirve para responder «¿por qué contestó eso?» meses después, que es la única
forma de mejorar un bot sin adivinar.

## 4. Las métricas — `vb metricas`

Qué capa de modelo atendió cada turno, cuántos se escalaron al potente y por
qué, cuánto costó (con lo de caché a su precio) y cuánto tardó. Sale de la tabla `decisiones`, que se escribe en
cada turno, y también se ve en el panel.

## 4b. El vigía: «¿están entrando los mensajes?»

Cada dos minutos el bot se hace una sola pregunta, y la contesta con evidencia
que no se puede falsear:

> ¿acabamos de responderle a alguien y no ha vuelto **nada**?

Meta acusa recibo de todo lo que se manda —«sent», «delivered», «read»— en
segundos, y esos acuses entran por el mismo webhook que los mensajes. Si el bot
respondió hace minutos y desde entonces no ha entrado ni un acuse, el camino de
entrada está roto. Si no se ha mandado nada —de madrugada, sin clientas— no hay
nada que concluir y **se calla**.

No repara nada solo, a propósito: matar ngrok desde dentro puede dejar dos
procesos peleándose el puerto 8000, que es otro fallo del mismo día.

- Por qué: el 20/09 una clienta escribió y **su mensaje nunca llegó**. Tuvo que
  repetirlo tres minutos después. Desde el PC todo se veía bien —ngrok
  corriendo, servidor perfecto—; lo único roto era el camino de fuera. Un
  mensaje perdido es una venta perdida, y no deja ni un error.

> **La primera versión de este vigía estaba mal y dio falsas alarmas.** Pedía
> `/health` a la URL pública: una petición que sale del PC, da la vuelta por el
> borde de ngrok y vuelve a entrar. Que ese viaje falle dice algo de la salida
> de esta máquina, no de si Meta puede entregar — y gritó «el túnel no
> responde» mientras los mensajes entraban con toda normalidad. Una alarma que
> se equivoca es peor que no tener alarma: enseña a ignorarla.

## 5. Los registros

| Archivo | Qué tiene |
|---|---|
| `logs/servidor.log` | Cada mensaje que entra y lo que respondió |
| `logs/tunel.log` | El túnel |
| `logs/ensayo-chatwoot.log` | El detalle del último ensayo |
| `logs/diagnostico.log` | Una línea por corrida del diagnóstico |

## 6. Las pruebas — `vb check`

1.290 pruebas en 27 segundos, más estilo (ruff), tipos (mypy) y arquitectura
(import-linter, 4 contratos). Corren sin internet y sin tocar nada real.

No son pruebas de adorno: casi todas nacieron de algo que pasó con una clienta
de verdad y llevan escrito qué fue.

---

## Qué mirar cuando algo va mal

| Síntoma | Mira esto |
|---|---|
| «No contesta» | `vb diagnostico` — casi siempre es el túnel o el servidor |
| «No llegan al CRM» | Área 3 del diagnóstico: webhook, red privada, webhooks entregados |
| «Contesta raro» | LangSmith: el turno completo, con lo que el modelo propuso |
| «Contestó dos veces» | `vb ensayo` — el eco tiene su propia comprobación |
| «El ERP no se llenó» | `vb erp`; se reconcilia solo cada 10 minutos |
| «Se cayó una ventana» | Se levanta sola a los 10 s; mira `logs/servidor.log` |
| «Cambié algo y el bot sigue igual» | Área 1: quedó un servidor viejo con el puerto 8000. `ENCENDER-BOT.cmd` ya apaga antes de arrancar |
