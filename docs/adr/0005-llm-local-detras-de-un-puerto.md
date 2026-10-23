# 0005 — Ollama local detrás de `LLMPort`, con salida estructurada real

**Fecha:** 2026-08-20 · **Estado:** Aceptada

## Contexto

Se quiere empezar con un modelo local gratuito y poder cambiar a uno hospedado
más adelante, sin reescribir nada. Y se quiere el máximo determinismo posible.

## Opciones

1. `ChatOllama` de `langchain-ollama` con `with_structured_output()`.
2. Cliente `ollama` nativo con `format=<json_schema>`, detrás de un puerto propio.
3. LiteLLM como proxy delante de todo.

## Decisión

**Opción 2**, con la opción 3 como camino de crecimiento.

`LLMPort` expone **un solo método**: `extract(prompt, texto, schema) -> BaseModel`.
No hay un `chat()` que devuelva texto libre. Esa ausencia es deliberada: obliga
estructuralmente a que **todo** uso del LLM pase por un schema cerrado.

## Consecuencias

Razones concretas para no pasar por `ChatOllama`:

- `format=<dict schema>` es **constrained decoding real**: restringe los logits
  para que sea *imposible* emitir un token que rompa el schema. `format="json"`
  a secas es mucho más débil.
- La documentación de LangChain **no aclara** si
  `ChatOllama.with_structured_output()` mapea a `format=<schema>` o hace parsing
  best-effort. Cuando el determinismo del schema es crítico, no se confía en una
  abstracción cuyo comportamiento no está documentado.
- El endpoint OpenAI-compatible de Ollama **no soporta `tool_choice`**: no se
  puede forzar la llamada a una herramienta concreta. La API nativa `/api/chat`
  con `format` sí garantiza la forma.

**Verificado**, no supuesto: `scripts/f0_determinismo.py` corrido contra un
servidor stub confirma que la petición lleva el JSON Schema completo (con el
`enum` de las 10 intenciones) y `temperature=0, seed=42, top_k=1, top_p=1.0`.

**Límite conocido:** `temperature=0` + `seed` **no** garantizan reproducibilidad
bit a bit. Los kernels de atención en GPU no son invariantes al tamaño del batch
y el último bit del logit puede cambiar el `argmax`. Mitigación:
`OLLAMA_NUM_PARALLEL=1`. El determinismo real no viene de ahí: viene del schema
cerrado, la validación contra el catálogo y el router en Python.
