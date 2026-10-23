# Golden dataset

**Este directorio contiene tu activo más valioso del proyecto.**

Un CSV con `mensaje,intencion_esperada,sku_esperado,cantidad_esperada`, hecho
con **mensajes reales de tus clientes**, etiquetados a mano por ti.

## Por qué importa tanto

Sin esto no puedes responder ninguna de estas preguntas:

- ¿Este modelo local es lo bastante bueno para producción?
- ¿Cambiar el prompt mejoró o empeoró las cosas?
- ¿Vale la pena pagar por un modelo hosted, o el gratis me alcanza?
- ¿El modelo se degradó desde la semana pasada?

Con esto, las cuatro se responden en 30 segundos.

## Cómo construirlo (Fase 2)

1. Exporta tus últimas ~200 conversaciones de WhatsApp.
2. Toma los primeros mensajes de cada cliente (los que abren la conversación).
3. Etiqueta 100 a mano con la intención correcta. Es tedioso. Hazlo igual.
4. Incluye deliberadamente los casos difíciles:
   - ambiguos: "cuánto vale eso"
   - con errores de tipeo: "kiero 2 camicetas"
   - regionalismos: "me regala una camiseta", "hágame el favor"
   - mezclados: "hola, cuánto vale la roja y me la mandan a Cali?"
   - trampas: "quiero hablar con una persona" NO es COTIZAR aunque diga "quiero"

## Formato

```csv
mensaje,intencion,sku,cantidad
"hola buenas",SALUDO,,
"que tienen?",CATALOGO,,
"quiero 2 camisetas premium",COTIZAR,CAM-001,2
"cuanto vale eso",COTIZAR,,
"listo confirmo",CONFIRMAR,,
"ya me llego?",ESTADO,,
"quiero hablar con una persona",HUMANO,,
```

## Test

```python
def test_accuracy_minima(golden_rows, llm):
    aciertos = sum(
        1 for r in golden_rows
        if llm.extract(PROMPT, r["mensaje"], Intencion).tipo.value == r["intencion"]
    )
    accuracy = aciertos / len(golden_rows)
    assert accuracy >= 0.90, f"accuracy cayó a {accuracy:.1%}"
```

Ponlo en CI. Cada cambio de prompt o de modelo pasa por aquí.

## Baseline honesto

Corre el mismo test contra `FakeLLM` (clasificación por reglas, en
`app/adapters/llm/ollama_client.py`). Si tu LLM no le gana claramente,
no estás ganando nada usándolo — y las reglas son gratis e instantáneas.
Mídelo antes de asumirlo.
