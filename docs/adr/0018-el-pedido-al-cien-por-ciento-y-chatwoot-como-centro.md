# 0018 — El pedido al 100 % antes del abono, y Chatwoot como centro de control

**Estado:** Aceptada · 19/09/2026 · decisiones de Camilo tras probar el bot con su
propio celular.

## Contexto

La prueba real del 19/09 destapó dos tipos de problema.

**En la venta:**
- El bot pidió el abono con «Talla: por confirmar» y sin dirección.
- Le mandó el prototipo del anillo a la clienta solo cuando ella lo pidió, y en vez de
  los consejos útiles le ofreció tres combinaciones «bonitas» sin criterio.
- Dijo «quedo atenta al comprobante» sin haber mandado las cuentas.
- Después del comprobante volvió a mandar las cuentas del abono.
- El comprobante del **saldo** no se registró en ninguna parte.
- Con el anillo listo, contestó «ya está en el taller». Los avisos que manda el panel no
  entraban en la memoria del bot.

**En la operación:** Chatwoot servía para ver, pero no decía en qué iba cada
venta ni qué necesitaba a Lía, y no se podía hacer nada desde él.

## Decisión

### El pedido se toma al 100 %

- `Borrador.falta_para_abono()` ahora exige, además del anillo, **talla, nombre,
  ciudad y dirección** (la dirección tiene que traer número).
- El pedido **nace** solo completo. Si la clienta paga antes, el pago queda por
  verificar (`pagado_sin_pedido`, alerta `datos-incompletos`) y no entra al taller.
- `Container.mover_pedido` **niega** la entrada al taller (`PedidoIncompleto`) a
  cualquier pedido incompleto, venga del panel o de Chatwoot.

### El resto del flujo de venta

- **Prototipo automático:** apenas quedan los colores, Python agrega
  `MOSTRAR_COMO_QUEDA`.
- **Consejo:** solo si lo pide, `MOSTRAR_SUGERENCIAS` manda 4 diseños: todo rosado,
  todo azul oscuro, todo blanco y todo amarillo.
- **Hablar de plata es mandar las cuentas:** `MANDAR_CUENTAS` manda las cuentas sin
  crear el pedido. El vigilante borra «quedo atenta al comprobante» si las cuentas no
  se han enviado.
- **El abono se pide una vez.** Con el abono reportado, `PEDIR_ABONO` se descarta.
- **El saldo se registra.** Un comprobante con el anillo listo pasa a revisión, marca
  `saldo_reportado` y deja la nota «Verificar SALDO».
- **El bot sabe dónde va el pedido:**
  - lee el estado en palabras (`ESTADO_EN_PALABRAS`) con los montos reales;
  - los avisos del panel entran en su charla (`anotar_aviso_del_sistema`);
  - el vigilante borra «en el taller» si el anillo ya está listo, y «ya se despachó»
    si no se ha despachado.

### Chatwoot como centro de control (`app/domain/seguimiento.py`)

- **Etapa:** una etiqueta por conversación, que se mueve sola (`01-consulta` …
  `10-entregado`).
- **Alertas:** `necesita-persona`, `pago-por-verificar`, `datos-incompletos`,
  `confirmar-antes-de-fabricar` y `tiene-fecha-limite`. Las tres primeras dejan la
  conversación «Abierta»; sin alertas queda «Pendiente», que significa que la lleva
  el bot.
- **Acciones:** Lía pone una etiqueta `hacer-…` (o toca su macro en el PC). El
  sistema la ejecuta con `mover_pedido`, la quita y deja una nota con el resultado.
  Es idempotente: cada cambio de etiquetas vuelve por webhook, y lo que ya se hizo
  solo se limpia.
- **Notas privadas del bot:** pedido tomado con su resumen, verificar pago, 🙋 por
  qué la necesitan, 🎤 lo que entendió de una nota de voz, cada cambio de etapa. Se
  anotan una vez (`crm_hecho`).
- **La ficha:** 12 campos del pedido.
- **Configuración:** 8 respuestas rápidas, 6 carpetas y 7 macros. Todo lo crea
  `vb chatwoot --conectar`, que se puede repetir sin duplicar.
- Las etiquetas que Lía ponga a mano **no se tocan nunca**.

### Un solo camino para mover un pedido

`Container.mover_pedido` hace todo en orden:
1. la regla del 100 %;
2. la transición;
3. los montos pagados;
4. el aviso a la clienta con sus fotos;
5. la memoria del bot;
6. Chatwoot y el ERP.

El panel y Chatwoot lo usan igual.

## Consecuencias

- Una clienta que no quiere dar la dirección antes de pagar no llega al abono. Es la
  regla que pidió Camilo: prefiere un pedido completo a un pedido rápido.
- Chatwoot se vuelve imprescindible: si se cae, el bot sigue vendiendo (el espejo
  nunca bloquea), pero Lía pierde la vista de las etapas hasta que vuelva.
- Probado sin red: 1262 pruebas. Contra el Chatwoot real con `vb ensayo`: 29
  comprobaciones, sin gastar API. Contra el modelo real, repitiendo la conversación
  de Camilo: USD 0,06 por corrida.
