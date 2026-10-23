# 0007 — Un modelo aparte para mirar las fotos

**Estado:** Aceptada · 2026-09
**Contexto previo:** [0005](0005-llm-local-detras-de-un-puerto.md), [0006](0006-la-expectativa-entra-en-la-interpretacion.md)

## Contexto

Media conversación de Lía pasa por una foto: el comprobante de la
transferencia, el anillo apoyado en una regla para sacar la talla, el
muestrario de circones con un color rodeado con el dedo.

Hasta ahora el sistema no miraba ninguna. Adivinaba por contexto —«si la
compra espera la talla, la foto es la talla»— y no sacaba ningún dato de la
imagen. Eso significaba que el momento en que entra el dinero y el momento en
que se decide la medida del anillo eran los dos únicos de toda la venta que el
bot no podía atender.

## Opciones

1. **Usar el mismo modelo para todo.** `qwen2.5vl` lee texto y mira imágenes,
   así que técnicamente sobra un puerto. Pero entonces mejorar la lectura de
   fotos obliga a cambiar el modelo que interpreta la conversación, y al revés.
2. **Un puerto propio con su propio modelo.** Dos configuraciones, dos
   evoluciones independientes, y la posibilidad de apagar uno.
3. **No leer imágenes; que las mire Lía.** Es lo que hay hoy, y funciona —
   pero la clienta se queda esperando y en ese hueco se enfrían las ventas.

## Decisión

La segunda. `VisionPort` es un puerto propio (`app/domain/ports.py`) con su
propio modelo (`OLLAMA_VISION_MODEL`) y su propio esquema cerrado
(`LecturaDeImagen`).

Y la división de siempre, aquí más marcada que en ningún otro sitio:

- **El modelo LEE**: qué tipo de foto es, qué número aparece en la regla, qué
  monto pone el comprobante, si la foto está clara.
- **Python DECIDE**: de milímetros a talla lo hace `tallas.medir()`, que es
  una tabla; qué se guarda y qué se manda a revisar lo hace
  `vision.entender()`, que es una función pura de cincuenta líneas.

Esa frontera es la que hace que el error sea *medible*: si el modelo dice 17.3
mm cuando eran 16.5, la talla sale mal en 1 y eso se ve. Si dijera «talla 7»
directamente no se vería nada.

La política, escrita una sola vez:

> Si se entiende con seguridad, se guarda. Si no, se guarda **lo que se vio**,
> se marca para que lo confirme una persona, y la conversación **sigue**.

Nunca se bloquea y nunca se inventa. Es viable porque este negocio revisa a
mano todas las conversaciones que llegan a transacción: 50 ventas al mes, no
50.000. Con otro volumen la decisión sería distinta, y ese es el motivo por el
que está escrita aquí y no dada por hecha.

## Consecuencias

- **Un comprobante sigue sin confirmar nada.** Lo más lejos que llega es
  `EN_REVISION_PAGO`, desde donde la tabla de transiciones no deja producir ni
  despachar. Una captura de pantalla se edita en treinta segundos.
- **Lo que se ve tiene que llegar a alguien.** Por eso las notas cuelgan del
  id de la conversación y salen en la tarjeta del pedido, en el panel. Un
  aviso que nadie mira es lo mismo que no avisar.
- **El bot puede funcionar ciego.** Sin `OLLAMA_VISION_MODEL` reconoce que
  llegó una foto, la marca y sigue. Es el arranque por defecto correcto:
  mejor avisar que adivinar.
- **El esquema del modelo de texto se encogió.** `PropuestaDelModelo` ya no
  incluye los campos que solo puede rellenar el lector de imágenes, así que el
  modelo de texto no puede inventarlos —marcaba `comprobante=True` leyendo
  «te mando el comprobante»— y el prompt de cada turno es más corto.
- **Falta medir con fotos reales.** `vb ojos` existe para eso: enseña la
  lectura en crudo y la decisión que se toma con ella, para poder separar «el
  modelo lee mal» de «nosotros decidimos mal».
