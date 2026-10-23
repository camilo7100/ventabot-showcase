# 0024 — Siempre una pregunta, una a la vez; el nombre se propone; primero el resumen

**Estado:** Aceptada · 20/09/2026 · Camilo, tras probar el bot desde su celular.
Lo de esperar el comprobante lo precisa el ADR 0022 (21/09).

## Contexto

Conversaciones que se paraban solas, o que se iban:

- Le llegó el resumen del pedido y debajo «¡Perfecto Camilo! 🫶», y ahí se
  quedó: sin pregunta, ella no sabe si le toca ni qué.
- A otra le llegó «¿Cooper es uno solo, o tienes dos peluditos?» y justo debajo
  «¿Lo dejo a nombre de Jose Pérez?». No volvió a escribir.
- En una conversación real, la clienta transfirió los $60.000 y el pedido no
  nació: le pidieron el nombre completo cuatro veces y nunca lo escribió. Lía lo
  tiene delante, en el contacto de WhatsApp, y no se lo habría preguntado.
- Otra dio vueltas cuatro veces con «listo, así» a «¿de 1 o de 2 huellitas?»
  hasta decir que ya había pagado. Y a una que abrió con «quiero el de 3
  huellitas» le volvieron a preguntar de cuántas lo quería.
- En el mismo mensaje se le preguntaba «¿está todo bien así?» y debajo se le
  pedía el abono; y a quien acababa de decir «ya transferí» se le volvían a
  mandar las cuentas.

## Decisión

- **Siempre termina con una pregunta, y una sola.** Si el modelo no preguntó,
  Python pone la de lo siguiente que falta (`_lo_que_falta`, `COMO_SE_PREGUNTA`)
  o «¿Así está bien?» tras el resumen; nunca la misma frase fija dos veces
  seguidas. Solo se calla cuando lo siguiente lo hace Lía.
- **El nombre se pregunta una vez y después se propone** el de WhatsApp
  (`_lo_del_nombre`, con el `sender_name` de Meta). Entra al resumen y su «sí» lo
  confirma. Si ya pagó y sigue sin nombre, pasa a Lía **una** vez, con una nota
  que dice cómo aparece en WhatsApp. «Ya pagó» incluye pagar con el pedido a
  medias (`pagado_sin_pedido`): es el caso real, porque sin nombre el pedido no
  nace y el abono no llega a contar como reportado. La primera versión miraba
  solo `abono_reportado` y no se encendía nunca (repaso del 21/09).
  Y si el modelo se lo vuelve a preguntar en un turno posterior, su frase se
  cambia por la propuesta (`_cambiar_por_la_propuesta`): en una prueba en vivo
  del 21/09 lo pidió con tres frases distintas antes de proponerlo, porque su
  pregunta tapaba la propuesta.
- **La cantidad no se adivina** (cambia el precio), pero lo que ella escribió
  cuenta aunque haya sido antes, si es un número DE HUELLITAS y el mismo que se
  propone (`cuantas_huellitas_escribio`). A la tercera vez sin respuesta, pasa a
  Lía (`VECES_ANTES_DE_LIA`).
- **Primero el resumen, el abono cuando dice que sí.** Con el resumen recién
  mandado no sale ningún dato de pago, venga como venga el orden de las acciones
  (`resumen_sin_confirmar`). Y con un pago en el mismo turno, ni PEDIR_ABONO ni
  MANDAR_CUENTAS (`ya_pago`).
- **El primer mensaje se recuerda**: la apertura no le contesta —es fija y
  gratis—, pero guarda lo que escribió en vez de un relleno.

## Consecuencias

- Pruebas: en `tests/unit/test_conversaciones_reales.py`, las clases
  `TestNingunMensajeSeQuedaSinPreguntar`, `TestUnaPreguntaPorMensaje`,
  `TestSuNombreNoSePideACiegas`, `TestPagoConElPedidoAMediasYSinNombre`,
  `TestALaTerceraSeLlamaALia`,
  `TestMirarAtrasSeHaceConLupa`, `TestLasCuentasNoSalenAntesDeQueConfirme` y
  `TestNoSePideLaPlataQueAcabaDeLlegar`.
- Reglas R2k, R2l y R2m de `docs/sistema/03-reglas-de-negocio.md`.
- El 21/09 el ADR 0022 cambió el cierre mientras se espera el comprobante:
  antes se callaba; ahora dice «Quedo atenta a tu comprobante 💓 ¿Te puedo
  ayudar con algo más?».
