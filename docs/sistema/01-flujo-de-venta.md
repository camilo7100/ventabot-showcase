# 01 · El flujo de venta, paso a paso

Así ocurre una venta hoy. Cada paso dice **quién actúa** (la clienta, el bot,
Lía) y **qué queda guardado**.

---

## 0. Llega un mensaje

La clienta escribe al WhatsApp del negocio. Meta manda un webhook firmado a
`POST /webhook/whatsapp`, que pasa por el túnel de ngrok hasta el PC.

El bot **no contesta de inmediato**: espera unos segundos por si ella sigue
escribiendo, y contesta todo junto (ADR 0012). Una clienta que manda cinco
mensajes seguidos recibe una respuesta, no cinco.

Si llegó **tocando un anuncio** de Instagram o Facebook, ese primer mensaje
dice de qué anuncio venía: se le anota a la clienta (primer y último anuncio) y
el pedido que nazca se le cuenta a ese anuncio. Así el Excel de ventas dice qué
anuncio vendió (ver [06 · De qué anuncio llegó](06-datos-y-privacidad.md)).

Si el mensaje es una **nota de voz**, se transcribe con Groq Whisper antes de
entenderla. Si es una **foto**, la mira un modelo aparte (ADR 0007): sirve para
la huella de la mascota y para la foto de la regla con la que se saca la talla.

## 1. Entender y decidir

El turno pasa por la asesora (ADR 0014):

1. **GPT-6 luna** (sin razonar) lee la conversación y propone una *jugada*: qué
   entendió, qué cambia en el pedido y qué acción tomar.
2. Si la confianza es baja, se repite con **la misma luna razonando un poco**.
   Si GPT no contesta, cada paso lo hace Claude (Haiku 5.5 / Sonnet 5.5)
   (ADR 0027).
3. **Python valida** la jugada antes de ejecutarla: una talla que no existe en el
   mandril se rechaza; una dirección sin número no se guarda; un color que no
   está en el catálogo no entra. El modelo propone, el código manda.
4. Si ninguna IA contesta en ~35 s, la clienta recibe una vez «Dame un
   momentico», el turno queda pendiente y el bot le contesta solo cuando alguna
   vuelva.

Cada turno queda grabado en LangSmith y en la tabla `decisiones`.

## 2. La apertura: la presentación entera, y gratis

**Los dos primeros turnos no pasan por Claude.** Ni cuestan, ni hacen esperar:

| Turno | Qué llega | Coste |
|---|---|---|
| 1. Cualquier primer mensaje | La presentación entera | **0 tokens**, instantáneo |
| 2. «No sé mi talla / mándame la guía» | La guía y su foto | **0 tokens**, instantáneo |

En las siete conversaciones reales de Lía esas dos respuestas son siempre las
mismas, palabra por palabra. Preguntarle a un modelo que cuesta dinero cuál de
las respuestas fijas toca, cuando solo hay una, es pagar por una decisión que
ya está tomada — y son 2-4 segundos justo al principio, que es donde la clienta
decide si esto va en serio.

La segunda tiene una condición estrecha a propósito (`pide_la_guia_de_la_talla`):
solo si lo último que dijimos fue la pregunta de la talla y su mensaje no trae
ningún número. Ante cualquier duda, al modelo. Adivinar intenciones en general
ya se intentó con el gestor por etiquetas y por eso existe la asesora (ADR 0014).

La primera tiene dos excepciones, que van al modelo: **una foto de entrada**
(puede ser la huella de su mascota) y **una queja de entrada** —reclamo,
devolución, «estafadores», un insulto, «no me llegó», «me llegó el anillo y se
le cayó una piedrita», «¿tiene garantía?»— (`_QUEJA_DE_ENTRADA`).
A una queja la ficha con precios es lo peor que se le puede mandar, y suele ser
alguien que ya compró escribiendo desde otro número: el modelo la lee y se la
pasa a Lía. Pasó en el repaso del 21/09 con «ustedes son unos estafadores de
mierda, devuélvanme la plata»: le llegó la bienvenida con el catálogo, y a Lía no
le avisó nadie; y lo mismo a la de la piedrita caída. Ahora contesta «Uy,
lamento mucho que sientas eso. Ya le aviso a Lía…» y queda marcada para ella.

Al primer «hola» sale, de un tirón, lo mismo que manda Lía:

1. la **ficha del producto** (los tres precios, el material, el abono, los
   tiempos) — palabra por palabra la suya;
2. **dos videos y una foto** del anillo, seguidos y sin texto en medio, para
   que WhatsApp los junte en un álbum;
3. la pregunta **«¿Sabes tu talla de anillo o te comparto la guía? 💍💜»**, que
   va de **pie del último medio**: así queda debajo del álbum y no despegada en
   un mensaje aparte. La manda el sistema, no el modelo, y si el modelo la
   repite abajo se le quita.

> **Por qué son cuatro mensajes y no uno.** La API de WhatsApp Business manda
> **un archivo por mensaje**: no existe el álbum que sí puede la app del
> celular. Lo que se ve agrupado lo agrupa WhatsApp solo, porque llegan
> seguidos y del mismo remitente.
>
> Y por eso el despachador **espera unos segundos tras cada archivo**
> (`ESPERA_TRAS_ARCHIVO_S`): Meta no recibe el video, recibe una URL y lo baja
> de nuestro servidor. Los videos pesan 3,5 MB y la foto 136 KB, así que sin
> esa pausa la foto —con la pregunta de pie— adelantaba a los videos y la
> pregunta llegaba **en medio del álbum**. Mandar en orden no es llegar en
> orden.

El negocio se llama **Luna Joyas**, y eso es un hecho del prompt con su
propia guardia: el 20/09 el bot saludó con «Bienvenida a Anillo Vial» —había
leído la calle del punto de recogida y la tomó por la marca.

## 3. La talla, de primeras

Se le pregunta en la apertura, antes que nada. A propósito: es lo único que
exige que ella haga algo —buscar un anillo, una regla, medir y mandar la
foto—, así que se arranca temprano.

Si se demora midiendo, la conversación no se para: sigue con la cantidad y los
colores.

## 4. Armar el anillo

El bot va llenando un *borrador* con lo que ella dice, en el orden en que salga:

| Dato | Cómo se consigue |
|---|---|
| Cuántas huellitas | 1, 2 o 3 (son tres productos distintos) |
| La talla | Ella la sabe, o se saca de la foto de la regla |
| El color de cada huellita | El corazón y los deditos, de la lista de circones. Cada dedito puede ir de su color («negro-blanco-negro-blanco») |
| El grabado | Hasta 5 nombres, o «sin grabado» |

**Cuando los colores quedan completos, el bot manda el prototipo sin que se lo
pidan**: un render de cómo le va a quedar (ADR 0008), con **todas** las
huellitas del anillo en la misma imagen y en su forma fija (la segunda al
revés, R2i). Si ella pide consejo, le ofrece cuatro combinaciones: todo rosa,
todo azul zafiro, todo blanco y todo amarillo (los nombres los pone el panel → Colores).

Si dice que ya no le gusta el color, se borra y se le vuelve a preguntar antes
de seguir (R2j). La cantidad no se adivina: tiene que haberla escrito ella
(R2m).

## 5. A nombre de quién

Lo único personal que se pregunta antes de hablar de plata: **su nombre**. Se
pregunta una vez; si contesta otra cosa, se le propone el que tiene en WhatsApp
(«¿Lo dejo a nombre de Laura Gómez? 🥰»), y si ya pagó sin darlo, pasa a Lía
(R2l).

Ni ciudad, ni cédula, ni celular, ni dirección. Todo eso va al final (paso 9).
El **teléfono no se pregunta**: está escribiendo por WhatsApp, ya lo tenemos.

## 6. El abono

Con el pedido al 100 % (huellitas, talla, colores, grabado y nombre), el bot
manda el resumen con el formato de Lía y pregunta si así está bien:

```
•Anillo 1 huellita•

Talla: 7
Color: 🖤 Negro / Dedos: Negro-Blanco-Negro-Blanco
Grabado: Akira ♡ 08/02/2021

•Entrega•
A nombre de: Camilo
```

**Primero el resumen; el abono, cuando ella dice que sí.** En el turno en que el
resumen es nuevo no sale ningún dato de pago, aunque el modelo lo pida: el
mismo mensaje no puede preguntarle si está bien y pedirle la plata. Cuando
confirma, **van las cuentas en el mismo mensaje**: nadie tiene que pedirlas.

- El anillo se fabrica con un abono de **$60.000**.
- El saldo se paga cuando ella ve las fotos del anillo terminado.

## 7. El comprobante

Ella manda la foto o el PDF del comprobante, o dice, explícito y en pasado,
que ya pagó («ya transferí»). «Voy a transferir» o pedir la cuenta **no** es un
pago: el bot no dice «recibido» y cierra, una vez, con «Quedo atenta a tu comprobante 💓
Cualquier duda, me cuentas 🫶», sin insistir después (R2g, R3b). Un comprobante que llegó se registra
aunque el modelo se olvide de pedirlo.

Con el pago de verdad, el bot responde «¡Recibido!» y **nunca** dice que el
pago está confirmado: eso lo verifica una
persona mirando la cuenta (ADR 0011). El pedido queda en `EN_REVISION_PAGO`, la
conversación se marca `pago-por-verificar` y aparece en la bandeja «💰 Pagos por
verificar».

Después de esto el bot **no vuelve a pedir el abono**.

## 8. Lía verifica el abono

Desde el panel del taller o desde Chatwoot (etiqueta `hacer-abono-ok`, que
funciona en el celular), Lía confirma el abono. Entonces, en un solo movimiento:

- el pedido pasa a `EN_PRODUCCION`;
- se registra el abono pagado;
- a la clienta le llega el aviso de que entró al taller;
- la etapa cambia a `05-en-taller` en Chatwoot;
- la venta se escribe en el ERP de Google Sheets.

**No entra al taller si le falta algo del anillo** (talla incluida). El sistema
lo impide, no se le olvida.

## 9. El taller, las fotos y los datos de envío

Lía fabrica. Cuando queda, **sube las fotos al panel** y marca
`hacer-anillo-listo`. A la clienta le llegan tres mensajes seguidos:

1. «Hola 🌷 ¡Tu anillo ya está listo!» y, en el mismo mensaje, **los datos que
   hacen falta para la guía**: ciudad, nombre completo, cédula, celular y
   dirección completa, más el valor del envío;
2. **las fotos del anillo terminado**;
3. el cobro: cuánto con envío incluido, cuánto sin él, y las cuentas.

Si ella había pedido **pagar el envío por adelantado** (R2h), el cobro trae una
sola cifra, con el envío incluido, y el aviso de despacho ya no le dice que
pague al recibir.

**Aquí es donde se piden los datos de envío**, y no antes. Es cuando ella los
manda junto con la transferencia: un solo mensaje, un solo momento, y la
dirección es la de hoy y no la de hace dos semanas.

**Sin fotos el sistema no deja mandar ese mensaje.** «Te comparto las fotos de
cómo quedó» sin una sola foto es pedirle $140.000 a alguien por algo que no ha
visto — pasó el 19/09, y ahora es imposible.

Si ella lo va a recoger, los tres mensajes cambian solos: ni guía, ni cédula,
ni «lo llevo a Coordinadora».

## 10. El saldo

Igual que el abono: ella paga, el bot recibe el comprobante y lo registra, y
Lía lo verifica (`hacer-saldo-ok`). El pedido queda **por despachar**.

## 11. Entrega

- **Envío**: Lía lo lleva a Coordinadora y marca `hacer-despachado`. A la
  clienta le llega el aviso de que va en camino.
- **Recoge**: el mismo botón, pero el mensaje dice dónde y que la esperan.

Cuando le llega, `hacer-entregado`. Fin.

---

## Lo que el bot nunca hace solo

- Confirmar un pago.
- Pasar un pedido al taller.
- Decir que algo está despachado antes de que Lía lo diga.
- Contestar encima de Lía cuando ella tomó la conversación.
- Pedir el abono dos veces después de que ella pagó.
