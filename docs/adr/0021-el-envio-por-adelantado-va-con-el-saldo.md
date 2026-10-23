# 0021 — El envío por adelantado va con el saldo, y como acción

**Estado:** Aceptada · 21/09/2026 · Camilo, tras probar el bot desde su celular.

## Contexto

Con las cuentas del abono ya mandadas, la clienta preguntó «¿Puedo pagar el
envío? Es que a veces no estoy en casa». Lo que hizo el bot:

1. Contestó «lo coordinas con el transportista» y debajo pegó «¡Recibido! 🙌»,
   sin que ella hubiera pagado nada: era la frase de relleno de
   `_mensaje_seguro`, que salía con cualquier pedido creado.
2. Cuando ella insistió («que me lo dejen en portería»), le ofreció «¿Transfieres
   los $60.000 del abono + los $18.000 del envío en una sola transferencia?».
3. Dos turnos después: «Tu pedido entra al taller ahora mismo. En 10 a 15 días
   te comparto las fotos», **sin abono**. El vigilante solo buscaba «EN el
   taller» y no lo vio.
4. Y al volver a mandar las cuentas: «ese valor lo puedes cancelar al recibir
   tu anillo», lo contrario de lo acordado.

## Decisión

**La regla de negocio.** El envío se paga al recibir; es lo normal y lo único
que se dice si ella no pregunta. Si **ella** pide pagarlo antes, se puede, pero
**junto con el saldo**, cuando el anillo está listo. Nunca con el abono: el
abono es solo el del anillo y es lo que lo hace entrar al taller.

**Cómo se guarda.** `Borrador.envio_con_saldo` y `DatosDeEnvio.envio_con_saldo`
(va dentro del pedido, que se guarda como JSON: no hace falta migración). Con
la marca, las cuentas dicen «lo pagas junto con el saldo», el cobro del saldo
trae una sola cifra con el envío incluido y el aviso de despacho no le vuelve a
cobrar el envío.

**El modelo lo pide como ACCIÓN (`ENVIO_CON_SALDO` / `ENVIO_AL_RECIBIR`), no
como un campo de `CambiosDelBorrador`.** El primer intento fue un campo
opcional más. Claude rechazó el esquema entero de `Jugada`: *«Schema is too
complex»*. Las pruebas locales no lo ven —usan un modelo simulado— y en
producción el bot habría quedado sin modelo en todos los turnos (todo por el
respaldo de reglas). **Antes de agregar un campo a `Jugada` o a
`CambiosDelBorrador`, hay que compilar el esquema contra Claude** (con
`calentando=True`: la primera compilación tarda 50-90 s).

**Lo que Python garantiza:**
- `vigilar()` quita «el abono + el envío» (`_ENVIO_CON_EL_ABONO`) y «entra al
  taller / en 10 a 15 días te comparto las fotos» sin abono
  (`_ARRANCA_EL_TALLER`); dicho como condición («apenas hagas el abono…») sí pasa.
- Si el modelo no lo dice bien, la frase de lo acordado la escribe Python, con
  el recordatorio de que el abono va primero.
- «¡Recibido!» solo sale cuando ella mandó algo que se está revisando; y la
  pregunta de relleno solo se agrega si de verdad es una pregunta.
- `habla_de_pago` ya no confunde pagar DESPUÉS con haber pagado. Al repasar
  esta misma conversación, «Yo los pago cuando esté listo el anillo» hizo que el
  modelo pidiera RECIBIR_COMPROBANTE, la palabra «pago» bastó para dejarlo
  pasar, y el pedido quedó en revisión de pago sin un peso transferido.
- Si el vigilante quita un «entra al taller» sin abono y no hay reescritura, lo
  que sale es «Apenas hagas el abono de $60.000, tu anillo entra al taller»
  (Python), no un «quedo atenta al comprobante» que no le aclara nada.

## Consecuencias

- Pruebas: `tests/unit/test_envio_con_saldo.py` (la conversación del 21/09 turno
  por turno) y el escenario `sint-13-envio-por-adelantado` en `vb repasar`.
- La plantilla de Meta `pedido_despachado` (la que sale con la ventana de 24 h
  cerrada) todavía dice «el envío se cancela al recibir». Para las clientas que
  lo pagaron con el saldo hace falta una plantilla aparte, aprobada por Meta.
- El cobro del saldo usa la cifra del mensaje de Lía (`ENVIO_EN_EL_MENSAJE_COP`,
  $16.500) y las cuentas del abono la de la tabla de fletes ($18.000 nacional).
  Es así desde antes; con el envío por adelantado se nota más.
