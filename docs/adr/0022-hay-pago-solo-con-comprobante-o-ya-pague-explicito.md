# 0022 — Hay pago solo con comprobante o con un «ya pagué» explícito

**Estado:** Aceptada · 21/09/2026 · Camilo, tras probar el bot desde su celular.

## Contexto

Con las cuentas del abono ya mandadas, la clienta escribió «Cuenta». Le
llegaron las cuentas y, debajo, «Recibido!». Ella: «Cuál recibido si no he
hecho el pago».

Al repasar, apareció lo mismo por otro lado: «Yo los pago cuando esté listo el
anillo» hizo que el modelo pidiera RECIBIR_COMPROBANTE, y bastaba con que el
texto dijera «pago» para dejarlo pasar: el pedido quedó en revisión de pago sin
que nadie hubiera transferido nada.

## Decisión

- **Un pago existe** cuando llega el comprobante (foto o PDF) o cuando ella dice,
  **explícito y en pasado**, que ya pagó: «ya transferí», «ya pagué, revisa la
  cuenta», «te mandé el comprobante». No se interpreta un «de pronto ya pagó».
  «Cuenta», «voy a transferir», «te pago más tarde», «los pago cuando esté
  listo», «no he hecho el pago» no son pagos (`habla_de_pago`).
- **«Recibido» solo con pago.** El vigilante (`_ACUSA_RECIBO`) quita cualquier
  «recibido» sin comprobante ni «ya pagué». Cuando sí llegó, se dice corto:
  «¡Recibido! 🙌».
- **Mientras no paga, no se le insiste.** Debajo de las cuentas, UNA vez: «Quedo
  atenta a tu comprobante 💓 Cualquier duda, me cuentas 🫶» (`QUEDO_ATENTA`, sin
  signos de pregunta). Después, mientras va a pagar —«gracias», «mañana le
  consigno»—, solo se le agradece (Camilo, 07/10, con la charla de Mónica: antes
  cerraba cada mensaje con una «pregunta suave» y salieron cinco seguidas).
- **Si pide las cuentas, se le mandan**, aunque se hayan mandado el turno
  anterior (`pide_las_cuentas`). La regla de no repetirlas era contra el spam,
  no contra quien las pide. Solo se REENVÍAN: si nunca se mandaron, es porque
  algo las frena (resumen sin confirmar, dato que falta) y eso manda.

- **Un comprobante que llegó no se pierde.** Si llega una foto o un PDF y lo
  que el modelo mismo leyó lo llama comprobante, se registra aunque el modelo
  olvide pedirlo (`llego_un_comprobante`). Pasó en un repaso: el modelo escribió
  «Envió el comprobante de pago del abono» y no lo registró.

## Consecuencias

- Pruebas: `tests/unit/test_envio_con_saldo.py` (secciones 5 a 7) y el escenario
  `sint-14-pide-la-cuenta-sin-pagar` en `vb repasar`.
- Un comprobante escrito como texto («[comprobante]») ya no cuenta: tiene que
  llegar como foto o PDF, o con un «ya pagué» claro.
