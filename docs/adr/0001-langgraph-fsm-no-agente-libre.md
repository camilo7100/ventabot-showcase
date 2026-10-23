# 0001 — LangGraph como máquina de estados, no como agente libre

**Fecha:** 2026-08-20 · **Estado:** Aceptada

## Contexto

El sistema conversa con clientes reales y mueve dinero real: cotiza, cobra un
anticipo y dispara producción. Un error no es un mensaje raro, es plata.

## Opciones

1. **Agente ReAct** (`create_agent` de LangChain v1): el LLM decide qué
   herramienta llamar en un bucle hasta considerar que terminó.
2. **StateGraph explícito**: nosotros definimos nodos y transiciones; el LLM
   solo clasifica intención dentro de un nodo.
3. Cadena LCEL sin estado: no sirve, no tiene ciclos ni persistencia.

## Decisión

**Opción 2.** `StateGraph` directo. Nada de `create_agent` ni
`create_react_agent` (este último, además, está deprecado).

El LLM aparece en 2 de 12 nodos y siempre devuelve un Pydantic con campos
`Literal`/`Enum` cerrados. El router es un `dict.get` con default en Python.

## Consecuencias

**A favor:** el espacio de decisión pasa de combinatorio a 7 destinos
enumerables. Se testea sin LLM, sin red, en microsegundos. Los modelos locales
pequeños degradan con más de 5-6 herramientas expuestas; con una FSM se exponen
1-2 por nodo.

**En contra:** cada nueva capacidad exige un nodo y una arista — no "emerge"
sola. Es exactamente el intercambio que queremos cuando el error cuesta dinero.

**Corolario:** `langgraph` es MIT y corre dentro de nuestro FastAPI. **No** se
usa LangGraph Platform / Agent Server, que no es MIT, exige
`LANGGRAPH_CLOUD_LICENSE_KEY`, hace egress a `beacon.langchain.com` y limita
nodos ejecutados. No necesitamos nada de él: checkpoints, interrupts y
durabilidad están en la librería libre.
