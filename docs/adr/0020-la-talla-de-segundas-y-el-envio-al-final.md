# 0020 — La talla de segundas y los datos de envío al final

**Estado:** Aceptada · 20/09/2026 · Camilo, tras probar el bot toda la noche
desde dos celulares. Reemplaza el orden de preguntas de los ADR 0018 y 0019.

## Contexto

Dos conversaciones reales, de punta a punta. Lo que se vio:

**La talla llegaba tarde y se atravesaba.** El bot preguntaba cantidad →
colores → grabado → talla. Es el peor orden posible, porque la talla es lo
único que exige que la clienta **haga algo**: buscar un anillo, una regla,
medir y mandar una foto. Al pedirla al final, la venta se paraba justo cuando
ya estaba decidida. En la primera prueba pasaron 32 minutos entre «mándame la
guía» y la foto, con la conversación congelada.

**Los datos de envío llegaban demasiado pronto.** Se pedían ciudad y nombre
antes de cobrar y la dirección justo después del abono (ADR 0019). Pero entre
el abono y el despacho pasan 10 a 15 días: cuando por fin hay que mandar el
anillo, esa dirección tiene dos semanas. Y pedirla antes es un formulario a
alguien que todavía no ha comprado.

Lo que Lía hace de verdad es otra cosa, y funciona: cuando el anillo está
terminado, manda las fotos **y en el mismo mensaje** pide ciudad, nombre
completo, cédula, celular y dirección. La clienta los manda junto con la
transferencia del saldo. Un solo mensaje, un solo momento, datos frescos.

**Y un fallo grave:** el bot mandó «Te comparto las fotos de cómo quedó» **sin
una sola foto**, y a continuación pidió $140.000. Se le estaba cobrando a
alguien por algo que no había visto.

**Además:** cotizó $8.000 de envío a Bogotá y $14.000 a otra clienta el mismo
día (filas viejas del CSV), cuando Lía cobra una tarifa nacional única.

## Decisión

### 1. La talla va de segundas

Orden nuevo: **cantidad → TALLA → colores → grabado → nombre**.

Se le pide apenas dice de cuántas huellitas lo quiere, con la guía a mano.
Mientras ella mide, la conversación sigue avanzando con los colores y el
grabado, que es la parte divertida. `Borrador.falta_del_anillo()` devuelve los
huecos **en ese orden**, y el modelo pregunta el primero que quede.

### 2. Los datos de envío se piden AL FINAL

Antes del abono no se pregunta nada personal salvo **su nombre** (para poder
tratarla por él al confirmar el pedido).

Ciudad, nombre completo, cédula, celular y dirección los pide **el sistema**,
no el modelo, en el mensaje del anillo terminado. Nuevos campos `cedula` y
`celular` en `Borrador` y `DatosDeEnvio`; `falta_de_la_guia()` los lista en el
mismo orden del mensaje de Lía.

### 3. El aviso del anillo listo va partido, con las fotos dentro

Tres piezas, en este orden:

1. «Hola 🌷 ¡Tu anillo ya está listo!» + los cinco datos que hacen falta para
   la guía + el valor del envío;
2. **las fotos del anillo**;
3. el cobro: cuánto con envío incluido, cuánto sin él, y las cuentas.

Así ve su anillo **entre** el «ya está listo» y el número. Al revés, el número
llega antes que el motivo.

### 4. Sin fotos no se puede decir que está listo

`SinFotosDelAnillo`: `mover_pedido` se niega a pasar a `ESPERANDO_SALDO` si el
pedido no tiene fotos, y le dice a Lía que las suba. Ese mensaje **es** las
fotos; sin ellas es un cobro a ciegas.

### 5. Una etiqueta para cuando el bot se traba

`hacer-preguntar-lo-que-falta`. No mueve el pedido: le manda a la clienta la
lista exacta de lo que falta y le deja a Lía una nota con **todo lo que el
pedido tiene guardado**. Si lo que la clienta ya dijo no aparece en esa nota,
es que no se guardó — y eso, que antes era invisible, se ve en un toque.

### 6. Una sola tarifa nacional: $18.000

Todas las filas de `data/fletes.csv` dicen 18000, y `ENVIO_NACIONAL_COP`
también. El mecanismo por ciudad se queda para cuando se diferencie; sus
pruebas usan ahora un CSV de mentira, para no atarlas a los precios de Lía.

> ⚠️ **Dos cifras conviven a propósito.** El mensaje del anillo terminado sigue
> diciendo **$16.500** (`ENVIO_EN_EL_MENSAJE_COP`), porque es el texto que Lía
> manda hoy y Camilo decidió no tocarlo (20/09). Las cotizaciones del bot usan
> $18.000. Cuando se unifiquen, la constante del mensaje desaparece.

### 7. Dos frases que el vigilante ya no deja pasar

- «Apenas Lía lo verifique **te lo despachamos**» dicho con el **abono** en
  revisión: entre eso y el despacho hay taller y un saldo. Con el **saldo** en
  revisión la misma frase es verdad y sigue permitida.
- «Perfecto, **ya lo vimos**» sobre un comprobante: suena a confirmado y no lo
  está. Un pago lo confirma una persona mirando el banco (ADR 0011).

## Consecuencias

- La talla deja de ser un tapón y pasa a resolverse en paralelo.
- Los datos de la guía llegan frescos, en un solo mensaje, cuando la clienta
  ya está mandando plata: es el momento de máxima disposición.
- Un anillo terminado ya no se puede cobrar sin enseñarlo.
- `falta-direccion` sigue existiendo pero ahora se enciende al final, que es
  cuando de verdad falta algo.
- Quedan dos cifras distintas de envío conviviendo. Está documentado y el
  código lo dice en voz alta, pero es deuda: la decisión es de Camilo.

---

## Apéndice (20/09, más tarde): la apertura

Al probarlo otra vez, el primer mensaje era un «¡Hola! ¿Cómo estás? Bienvenida
a **Anillo Vial**». El modelo había leído la calle del punto de recogida y la
tomó por el nombre del negocio, en el primer mensaje de la conversación.

Se corrigió en dos sitios, como siempre que algo cuesta confianza: el nombre
entra como un **hecho** del prompt (`NOMBRE_DEL_NEGOCIO`) y hay una **guardia**
en el vigilante (`_OTRO_NOMBRE`) que borra la frase si vuelve a pasar.

Y la apertura pasó a ser la de Lía, entera y automática:

1. la ficha del producto, palabra por palabra;
2. la foto del anillo y dos videos (`data/imagenes/presentacion_*`);
3. «¿Sabes tu talla de anillo o te comparto la guía? 💍💜».

Es decir: **la talla se pregunta en la apertura**, antes incluso que la
cantidad de huellitas. Es lo que hace Lía y tiene el mismo motivo que el resto
de este ADR — es lo único que exige que la clienta haga algo, así que se
arranca lo primero.
