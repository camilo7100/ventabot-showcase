# 0011 — El pago lo confirma una persona

**Estado:** Aceptada · 2026-09
**Reemplaza a:** [0003](0003-cobro-por-link-no-por-comprobante.md)

## Contexto

La ADR 0003 decidió que un pago solo se da por bueno cuando lo confirma el
webhook de una pasarela, y que **una foto de un comprobante no confirma
nada**. El razonamiento sigue siendo correcto: una captura de pantalla se
edita en treinta segundos, y un modelo de visión que lee «$60.000» en una
imagen no ha visto entrar un peso a ninguna cuenta.

Lo que ha cambiado es quién cierra ese hueco. Camilo lo dijo así:

> «No voy a tocar nada de confirmación de pagos automáticos, para esos
> siempre va un humano a confirmar al corto plazo.»

Y tiene razón de negocio. Lía cobra hoy por Bancolombia, Nequi y Daviplata:
transferencias a cuentas personales, no una pasarela. Enchufar Bold o Wompi
para confirmar automáticamente significa cambiar **cómo cobra el negocio**, no
solo cómo lo confirma el software. Eso es una decisión comercial —comisión por
transacción, tiempos de dispersión, facturación— y no se toma para desbloquear
un módulo.

## Opciones

1. **Integrar Bold/Wompi ya.** Cambia el medio de cobro del negocio para
   resolver un problema que hoy resuelve una persona en diez segundos.
2. **Dar por bueno el comprobante que lee el modelo de visión.** Es
   exactamente lo que 0003 prohibió, y con razón.
3. **Dejar el pago en un estado que NO produce, y que una persona lo
   confirme.**

## Decisión

La tercera. El flujo del dinero queda así, y no hay ninguna otra puerta:

1. La clienta manda la foto del comprobante.
2. El lector de imágenes **lee** lo que ve —monto, referencia— y lo guarda
   como *lo que dice la foto*, nunca como *lo que pasó*.
3. El pedido entra en `EN_REVISION_PAGO`. Ese estado **no puede producir ni
   despachar**: está en la máquina de estados, no en un `if`.
4. A la clienta se le contesta que se está verificando. No se le dice
   «recibido» —sería mentira— ni se le vuelve a pedir el abono —sería
   desconfiado—.
5. Una persona mira la cuenta, ve el movimiento y confirma en el panel. Ahí,
   y solo ahí, el pedido pasa a producción.

La pieza de software que esto necesita **no es una integración: es una cola de
revisión visible**. Que Lía abra el panel y vea «3 pagos por confirmar» con la
foto al lado y un botón.

## Consecuencias

El bot nunca miente sobre dinero, que era todo el objetivo de 0003, y el
negocio no cambia de forma de cobrar para conseguirlo.

El costo es humano y hay que medirlo: cada abono son unos segundos de alguien
mirando la app del banco. Con el volumen de hoy es despreciable. El día que
sean cincuenta pagos diarios, esto se revisa —y entonces la conversación sobre
la pasarela será una conversación de negocio con números, que es como debe
ser.

`app/adapters/payments/bold.py` se queda en el repositorio, sin enchufar. No
es código muerto: es la implementación del puerto que se activará el día que
haya pasarela, y borrarla obligaría a escribirla otra vez.
