# 0012 — Una respuesta por ráfaga, no una por mensaje

**Estado:** Aceptada · encendida en producción desde el 27/09/2026 (5 s de calma, tope 15 s); desde el 12/10/2026, **20 s de calma y tope de 1 minuto** (Camilo: que la clienta alcance a escribir todo antes de que le contesten)
**Fecha:** septiembre de 2026

## Contexto

Nadie escribe por WhatsApp como se escribe un correo. Esto es textual de una
clienta de Lía, cuatro mensajes seguidos en menos de un minuto:

> «Son dos huellitas»
> «Una huellita negra por mi panterita»
> «Y la otra huellita no se jajaja»
> «Tienes referencias de negro con otra huella»

Eso es **una** pregunta. Lía leyó las cuatro líneas y contestó una vez, con las
fotos de anillos negros combinados. El bot contestaba cuatro veces, y la tercera
respuesta estaba mal escrita antes de salir, porque se redactó sin haber leído
la cuarta línea. En la reproducción de esa conversación el bot acabó repitiendo
la misma pregunta y escalando a una persona por una respuesta que estaba
perfectamente clara.

De todas las cosas que delatan que del otro lado hay una máquina, esta es la
primera: antes que el tono, antes que los emojis y antes que el modelo. La idea
viene de [basdonax-ai-agentkity](https://github.com/fcori47/basdonax-ai-agentkity),
donde se llama «método brasilero» y se nombra como una de las dos cosas que más
cambian el resultado.

## Opciones

1. **Nada.** Contestar cada mensaje al llegar. Es lo que había, y es lo que
   produjo el fallo de arriba.
2. **Que lo resuelva el contexto.** Ya lo hace a medias: los datos de los cuatro
   mensajes se acumulan en la misma compra. Pero eso arregla los datos, no la
   conversación: siguen saliendo cuatro respuestas.
3. **Esperar unos segundos por conversación y juntar** lo que llegue. Un
   diccionario y una tarea de `asyncio` por conversación, en el mismo proceso.
   Es la misma decisión que ya está tomada en el despachador de la outbox.
4. **Una cola de verdad con ventanas** (arq/Redis). Es la Fase 6. Hoy no hay más
   que un proceso y un número.

## Decisión

La 3, en `app/workers/agrupador.py`, entre el webhook y `procesar_mensaje`.
Cada mensaje reinicia el contador de **su** conversación; cuando pasan
`AGRUPAR_SEGUNDOS` sin que llegue otro, se atienden todos juntos fundidos en uno,
con los textos separados por saltos de línea y todas las fotos sumadas.

Se conserva el `external_message_id` del **último**: es el que la deduplicación
acaba de marcar como visto y el que va en la clave de idempotencia de la
respuesta.

**Rehecho el 27/09 con la conversación de prueba del 26/09**, donde 8 mensajes
reenviados en el mismo segundo produjeron 8 respuestas. La causa real no era la
falta de espera: el turno corría **dentro del hilo que recibe los webhooks**, así
que el servidor quedaba sordo mientras la IA pensaba (Meta hasta reenvió un
audio) y cada mensaje entraba solo cuando el anterior ya estaba contestado.
Ahora:

1. Un turno a la vez por conversación, en **un hilo aparte** (uno solo: nunca dos
   turnos a la vez, como antes). El servidor sigue recibiendo.
2. Lo que llega mientras se atiende se junta en el turno siguiente: foto, audio
   (que se transcribe dentro del turno) y texto van juntos.
3. La ventana es de **calma** (cada mensaje la reinicia) con **tope** desde el
   primero. No es un `sleep` fijo.
4. El **primer mensaje no espera**: la apertura es fija y no se toca.
5. Cada mensaje de la ráfaga se guarda y se copia a Chatwoot **por separado**
   (`InboundMessage.partes`); el turno los lee juntos.

En el código viene en `0` (cuánto tarda el bot es una decisión del negocio); en
producción lo fija `docker-compose.yml`.

## Consecuencias

- Cuatro mensajes producen una respuesta, escrita con las cuatro líneas leídas.
- `detener()` **no** tira lo que esté esperando: lo atiende. Un Ctrl+C no puede
  comerse el mensaje de una clienta.
- Lo que esté en el buffer se pierde si el proceso muere de golpe. Es la misma
  exposición que ya tiene `BackgroundTasks`, y dura segundos. Cuando llegue la
  cola de la Fase 6, esto se cae solo y lo hace la cola.
- `vb f1-check` no se ve afectado: su primer mensaje no espera.
- El contador es por conversación y vive en memoria: con dos procesos, dos
  ráfagas de la misma clienta podrían atenderse por separado. Es el mismo caso
  que ya pide un lock por conversación en la Fase 6.
