# 0006 — La expectativa entra en la interpretación

**Estado:** Aceptada · 2026-09
**Contexto previo:** [0005](0005-llm-local-detras-de-un-puerto.md)

## Contexto

Hablando con el bot en producción aparecieron seis fallos seguidos que la
medición no había visto: el golden dataset puntuaba 98.1% de acción correcta
y la conversación real se rompía igual.

La razón es que el golden mide **mensajes aislados** y todos esos fallos eran
**de conversación**: una palabra suelta contestando a una pregunta, media
respuesta de colores, la misma pregunta repetida cuatro veces, «ya pagué» sin
un pedido al que referirse.

La hipótesis inicial fue que faltaba «inteligencia»: un modelo más grande, o
una distancia coseno que clasificara el mensaje en una categoría. Ninguna de
las dos habría arreglado nada. «Carmen» no es difícil de clasificar; es
imposible de clasificar **sin saber que acabábamos de preguntar un nombre**.

## Opciones

1. **Modelo más grande / embeddings.** Caro, lento, y no ataca la causa: el
   problema no es qué tan bien se entiende el mensaje, es que el mensaje se
   miraba solo.
2. **Meter el historial en el prompt.** Rechazado ya en el rediseño: cuesta
   tokens en cada turno, se degrada según crece y convierte un dato exacto en
   algo que hay que deducir.
3. **Pasar la pregunta pendiente a la interpretación.** El `Proceso` abierto
   ya sabe qué falta. Leerlo antes de interpretar es un `if`.

## Decisión

Se elige la tercera. `leer_respuesta_esperada(texto, contexto)` corre **antes
del modelo**: si hay una compra esperando el grabado y llega una palabra que
solo puede ser un nombre, es el nombre. Si espera colores y llega un color
—aunque sea medio—, es un color. Si espera la talla y llega una talla, es la
talla.

Tres consecuencias que no son casualidad:

- **Ahorra llamadas al modelo** en los turnos más frecuentes de todos, que son
  justo las respuestas cortas.
- **No delega la parte cara.** El dato que se graba en plata lo saca un parser
  que se lee entero y no alucina.
- **Media respuesta se guarda.** Un color sin parte queda pendiente y la
  siguiente pregunta se afina en vez de repetirse.

Va acompañada de un guardián de repeticiones (`ContextoConversacional.
registrar_salida`): el mismo mensaje no sale dos veces seguidas nunca, y a la
tercera insistencia aparece una persona.

## Consecuencias

- El golden dataset **ya no basta como medida**. Mide interpretación de
  mensajes sueltos; hace falta medir conversaciones. Mientras tanto, el
  archivo `tests/unit/test_inteligencia_conversacional.py` cumple ese papel:
  cada fallo de la conversación real es un test, y el modelo que usa acierta
  el verbo y nada más, para probar que la inteligencia está en Python.
- La interpretación **deja de ser una función pura del texto**. Es el precio,
  y es el correcto: una conversación tampoco es una función pura de su último
  mensaje. El contexto que entra está tipado y es pequeño (qué falta en el
  proceso abierto), no un historial.
- El día que se cambie a un modelo de pago, esta capa **sigue delante**. Un
  modelo mejor no debería tener que adivinar lo que nosotros ya sabemos.
