# 0003 — El pago se confirma por webhook firmado, nunca por una imagen

**Fecha:** 2026-08-20 · **Estado:** Aceptada

## Contexto

En Colombia es costumbre mandar un pantallazo de la transferencia como "prueba"
de pago. Y existen **aplicaciones falsas que suplantan a Nequi** y generan
comprobantes visualmente casi idénticos a los reales. El fraude se concentra de
jueves a domingo, cuando la verificación bancaria es más lenta, y ataca
específicamente ventas por redes sociales.

## Opciones

1. Aceptar el comprobante y verificarlo con OCR o un LLM de visión.
2. Cobrar siempre por link de pasarela y confirmar con webhook firmado.
3. Híbrido: link por defecto, comprobante como caso de revisión.

## Decisión

**Opción 3**, con una regla dura codificada en la máquina de estados:

> **La imagen nunca autoriza nada. La imagen solo abre un caso.**

Un comprobante crea un `Payment` en `EN_REVISION` y mueve el pedido a
`EN_REVISION_PAGO`. **Jamás** a `ANTICIPO_PAGADO`. Hay un test que lo verifica.

El anticipo va siempre por link (`permitir_transferencia_para_anticipo: false`).

## Consecuencias

El OCR y el LLM de visión **sí se usan**, pero solo para pre-llenar el caso y
ahorrarle tipeo al operador. No prueban nada: un comprobante editado se lee
perfecto. El análisis forense (ELA, EXIF) tampoco sirve — WhatsApp recomprime y
borra los metadatos, así que da falsos positivos a montones.

Lo que sí prueba es el cruce contra el movimiento bancario real. Para hacerlo
determinístico se usa **monto con dígitos únicos**: $150.000 se cobra como
$150.037, donde `037` se deriva del ID del pedido. Con 1.000 slots y una ventana
temporal, el match es exacto.

Ventaja estructural del negocio: el producto es **hecho a la medida**, no
revendible. El estafador tiene poco incentivo, y el anticipo por link le cierra
la puerta.
