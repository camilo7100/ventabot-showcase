# 0004 — arq como cola de tareas

**Fecha:** 2026-08-20 · **Estado:** Aceptada

## Contexto

El webhook debe responder 200 en menos de ~200 ms (Bold exige 2 s) y no puede
hacer inferencia LLM dentro del handler. Hace falta una cola. `BackgroundTasks`
de FastAPI no sirve: corre en el mismo proceso y **pierde mensajes al
reiniciar**.

## Opciones

1. **arq** — asyncio nativo sobre Redis, ligero.
2. **Celery** — el más maduro (beat, chains, Flower), pero su soporte async
   sigue siendo incómodo.
3. **Redis Streams** crudo con consumer groups — orden estricto por partición.

## Decisión

**arq.** El stack ya es async de punta a punta (FastAPI + LangGraph +
`AsyncPostgresSaver`), y arq encaja sin ceremonia.

## Consecuencias

⚠️ **Restricción descubierta al verificar la resolución de dependencias:**
`arq==0.28.0` declara `redis[hiredis]<6`. No se puede usar `redis` 6.x ni 8.x
en el mismo entorno. El proyecto queda pineado en `redis[hiredis]==5.3.1`.

Si algún día se necesita redis 6+ (por una función nueva del cliente), toca
cambiar de cola: **taskiq** o **dramatiq** son los reemplazos naturales. Queda
anotado aquí para no redescubrirlo bajo presión.

⚠️ **Requisito no negociable, independiente de la cola:** dos workers
procesando mensajes del mismo `thread_id` en paralelo **corrompen el checkpoint
de LangGraph**. Hace falta un lock por conversación (`SET NX PX` en Redis) antes
de `graph.invoke()`, o partición por `thread_id`. La opción del lock es más
simple y basta; la partición con Redis Streams es lo correcto a escala.
