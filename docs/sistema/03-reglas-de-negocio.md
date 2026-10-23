# 03 · Las reglas del negocio

Una regla aquí no es un consejo: es algo que **el código impide**. Cada una dice
dónde vive y qué pasó el día que no existía.

## Cuando dos reglas chocan: qué manda

Este documento es **la fuente única** de cómo se comporta el bot. El prompt
(`app/prompts/asesora_v1.txt`), los manuales y el panel (`/panel/flujo`,
`/panel/instructivo`) dicen lo mismo con otras palabras; si alguno dice otra
cosa, **manda este documento y el código**, y el otro se corrige.

Si llega una instrucción nueva que contradice una regla de aquí, se resuelve
así, en este orden, sin interpretar ni flexibilizar:

1. **Lo que protege a una persona o al negocio** va primero y no tiene
   excepciones por conveniencia: no dar la dirección de la casa de Lía (R17), no
   decir que un pago está confirmado (R5), no escribirle a una clienta real desde
   una prueba (R16), nunca ofrecer la cadena por cuenta propia (R2p).
2. **La instrucción más reciente de Camilo reemplaza a la anterior sobre LO
   MISMO.** Se reescribe la regla vieja (no se apilan las dos) y se anota abajo,
   en «Reemplazadas», qué cambió y cuándo.
3. **Una excepción vale solo si está escrita aquí** como excepción de una regla
   concreta («Excepción: …»). Lo que no está escrito como excepción, no lo es.
4. **Lo puntual no cambia la regla.** «Solo por esta vez» con una clienta se hace
   a mano (sin tocar el flujo) y no se escribe aquí.
5. Si de verdad no se puede saber qué quiso decir Camilo, **se le pregunta**
   antes de cambiar nada.

### Reemplazadas (lo que ya NO vale)

| Antes | Ahora | Desde |
|---|---|---|
| Debajo de las cuentas, hasta 3 cosas en una pregunta | Una sola cosa, la primera útil (R4) | 09/10 |
| Resolver en Chatwoot devolvía la charla al bot | Resolver solo cierra; devolver es otra acción (R9) | 09/10 |
| Toda charla viva «Abierta», sin asignar | Asignada a VentaBot («Pendiente») o a una persona (R11) | 09/10 |
| Se decía la dirección completa para recoger | Solo el conjunto, sin torre ni apartamento (R17) | 09/10 |
| Mientras va a pagar: «¿te ayudo con algo más?» | Sin preguntas mientras va a pagar (R3b) | 07/10 |
| Copias a Chatwoot en memoria, 2 reintentos | En la base, reintento sin límite (05-chatwoot) | 09/10 |
| «Lo pienso» llevaba UN recordatorio | Si la IA lo lee como desinterés, ninguno (R3b) | 10/10 |
| Saludo «¡Buenos días! ¿Cómo amaneciste?» | «¡Buen día! ¿Cómo estás?» (ADR 0017) | 10/10 |
| Recordatorios encendidos | **Pausados**: no sale ninguno (`RECORDATORIOS: "false"`) | 13/10 |
| Apertura «¡Hola! Buen día 🌞» a cualquier hora | Buen día / Buenas tardes / Buenas noches según la hora (R2f) | 13/10 |
| A un «gracias» o a un ❤️ se le pegaba «¿De cuántas huellitas lo quieres?» | «¡Con gusto!» y ya; a una reacción sola, nada (R3b) | 13/10 |
| Pospone → se cierra sin ninguna pregunta | Si falta diseñar, UNA vez: «¿dejamos tu anillo listo?» (R3b) | 13/10 |

---

## R1 · El pedido se toma al 100 %

**Antes del abono** tienen que estar, EN ESTE ORDEN: cuántas huellitas, la
**talla**, el color de cada una, el grabado (o «sin grabado») y su nombre.

La talla va de segundas a propósito: es lo único que exige que la clienta haga
algo (medir y mandar una foto), y al final se volvía un tapón (ADR 0020).

- Vive en: `Borrador.falta_para_abono()` (`app/domain/asesora.py`).
- Por qué: el 19/09 se pidió el abono con «Talla: por confirmar». Un pedido que
  se paga a medias se queda «en abono»: no nace, no entra al taller y hay que
  perseguir a la clienta días después.

## R2 · Los datos de envío van AL FINAL, con las fotos

Ciudad, nombre completo, cédula, celular y dirección **no se preguntan antes de
pagar**. Los pide el sistema en el mensaje del anillo terminado, junto con las
fotos y el cobro del saldo. Sin ellos (o sin que diga que lo recoge) el pedido
no se despacha.

- Vive en: `Borrador.falta_de_la_guia()` y `operacion.falta_para_despachar()`,
  que `container.mover_pedido` exige antes de `DESPACHADO`.
- Por qué: pedirlos antes es un formulario a alguien que todavía no ha
  comprado, y para cuando hay que despachar esa dirección tiene dos semanas.
  Al final llegan frescos y en un solo mensaje, mientras ella está
  transfiriendo (ADR 0020).

## R2b · Sin fotos no se puede decir que está listo

`mover_pedido` se niega a pasar a `ESPERANDO_SALDO` si el pedido no tiene
fotos, y le dice a Lía que las suba.

- Vive en: `operacion.SinFotosDelAnillo`.
- Por qué: el 19/09 salió «Te comparto las fotos de cómo quedó» y no salió
  ninguna imagen, seguido de un cobro de $140.000. Ese mensaje **es** las
  fotos.

## R2c · El negocio se llama Luna Joyas

Ni «Anillo Vial», ni el nombre de la calle, ni nada que el modelo se invente.

- Vive en: `asesora.NOMBRE_DEL_NEGOCIO`, que entra en los hechos del prompt, y
  la guardia `_OTRO_NOMBRE` del vigilante, que borra la frase.
- Por qué: el 20/09 abrió con «Bienvenida a Anillo Vial» —la calle del punto de
  recogida—. En el primer mensaje, y es de las cosas que más rápido delatan que
  del otro lado hay una máquina.

## R2d · Si se calcula la talla, se la decimos

Cuando la talla sale de una medida o de la foto de la regla, el **sistema** la
anuncia con el número que quedó guardado: «¡Es una talla 7! 💍».

- Vive en: la cabecera del turno en `app/conversacion/asesora.py`.
- Por qué: el 20/09 el sistema calculó 6.5, el modelo escribió «talla 7», el
  vigilante le borró la frase por no cuadrar y a la clienta le llegó un
  «¡Perfecto!» a secas. Tuvo que escribir «?» para saber su talla.

## R2e · «Muéstrame cómo queda» es mirar, no escoger

Los diseños que pide ver van en `Jugada.vistas_previas` y se dibujan **sin
guardarse**. Máximo 3 por mensaje, cada uno con su nombre de pie.

La foto trae **el anillo entero**: si compra el de tres y está mirando el
color de una, se completa con lo que ya escogió para las otras (y si no hay, con
la que está mirando).

- Vive en: `Asesora._como_queda` y `_el_anillo_entero()`.
- Por qué: el 20/09 pidió ver colores tres veces y el bot contestó «¡Claro! Te
  muestro cómo se ve rosado con rojo» sin mandar ni una imagen — `_como_queda`
  solo dibujaba lo ya escogido, y ella estaba mirando para decidir.

## R2f · La presentación va una vez

`SOLO_UNA_VEZ_EN_LA_CHARLA`. Si después pregunta un precio, se contesta en una
frase. Lía nunca reenvía la ficha.

- **Aunque la presentación acabe de salir** (13/10): si pregunta el precio, se le
  dan los tres en una frase. Nunca «ya te compartí los precios» ni solo el saludo
  (12/10: «Hola me interesa su precios», «Precio y tallas»). Si pregunta es porque
  no lo leyó. Clienta `precio_otra_vez`.
- **Lo que va en ella**, revisado a ojo el 13/10 (`PIEZA_DE_CADA_ANILLO`): la ficha;
  el PRIMER video, anillos de **2 huellitas**; el SEGUNDO, de **1 huellita** (uno con
  el nombre grabado por dentro); y la FOTO del final, con «¿Sabes tu talla…?», UN
  anillo de **3 huellitas** en tres ángulos. «¿Me los puede mostrar por separado?» se
  contesta describiendo cada uno, sin «¿te refieres a…?» (regla «PIENSA QUÉ QUIERE
  DE VERDAD» del prompt). Clienta `por_separado`.
- **Si pide ver UNO** («muéstrame el de 2», «¿cómo es el de una huellita?»,
  `pide_ver_el_de`): le llega solo esa pieza, no la presentación entera. Clienta
  `ver_el_de_dos`.
- **Si el primer mensaje ya trae su pedido** («quiero uno de una huellita talla 6, todo
  rosado, que diga Lola», `trae_datos_del_pedido`), ese turno lo lee la IA: la
  bienvenida y la presentación van igual, pero lo que dijo queda anotado (antes se
  perdía y le volvían a preguntar la talla y las huellitas). Una pregunta de precio
  («¿cuánto vale el de dos huellitas?») sigue con la apertura fija, sin modelo.
- **El saludo, según la hora de Colombia** (`saludo_de_apertura`): «¡Hola! Buen día
  🌞» hasta las 12, «Buenas tardes 🌷» hasta las 7 p. m., «Buenas noches 🌙» después
  (12/10: a las 9:37 p. m. le llegaba «Buen día»).

## R2g · Hay pago solo con comprobante o con un «ya pagué» explícito

Un pago se registra cuando llega el comprobante (foto o PDF) o cuando ella dice,
explícito y en pasado, que ya pagó («ya transferí», «ya pagué, revisa la
cuenta»). No se interpreta un «de pronto ya pagó». Hasta entonces el bot no dice
«recibido»: cierra con «Quedo atenta a tu comprobante 💓 ¿Te puedo ayudar con
algo más?», sin presionarla. Si pide las cuentas otra vez, se le mandan.

- Vive en: `habla_de_pago()`, `_ACUSA_RECIBO` en `vigilar()`,
  `pide_las_cuentas()` y `QUEDO_ATENTA`.
- Por qué: el 21/09 escribió «Cuenta», le llegaron las cuentas y debajo
  «¡Recibido!». Ella: «Cuál recibido si no he hecho el pago». Y «Yo los pago
  cuando esté listo el anillo» dejó un pedido en revisión de pago sin un peso.
- La frase no se dice dos veces en el mismo mensaje: si el modelo ya escribió
  «quedo atenta» y las preguntas suaves ya salieron, el mensaje queda como está.
  En los repasos del 21/09 salía «¡Dale! Quedo atenta a tu comprobante 🙌 Quedo
  atenta a tu comprobante 💓 ¿…?» tras varios «ok» seguidos
  (`TestQuedoAtentaNoSaleDosVeces`).

## R2h · El envío se paga al recibir, o con el SALDO; nunca con el abono

Lo normal —y lo único que se dice si ella no pregunta— es pagar el envío al
recibir. Si **ella** pide pagarlo antes (no está en casa, que se lo dejen en
portería), sí se puede: va **junto con el saldo**, cuando el anillo esté listo.
El abono es solo el del anillo, y **sin abono el anillo no entra al taller**:
el bot no puede decir lo contrario.

- Vive en: las acciones `ENVIO_CON_SALDO` / `ENVIO_AL_RECIBIR` que pide el
  modelo y resuelve `acordar_envio()`; `Borrador.envio_con_saldo` y
  `DatosDeEnvio.envio_con_saldo` (se guarda en el pedido); el vigilante (`vigilar()`) quita «el abono + el envío»
  y «tu pedido entra al taller» mientras no haya abono; las cuentas, el cobro
  del saldo (`aviso_de_cierre`) y el aviso de despacho cambian solos.
- Por qué: el 21/09 una clienta preguntó si podía pagar el envío porque no
  estaba en casa. El bot le pegó «¡Recibido! 🙌» sin que hubiera pagado nada, le
  ofreció sumarlo al abono, le dijo que su pedido «entra al taller ahora mismo»
  sin abono, y al final le volvió a decir que el envío se pagaba al recibir.
  Pruebas: `tests/unit/test_envio_con_saldo.py`.

## R2i · La forma del anillo no se escoge; el color de cada piedra, sí

La segunda huellita va siempre al revés: en el de una, mirando hacia arriba
(corazón abajo, deditos arriba); en el de dos, la derecha al revés; en el de
tres, la del centro. Si piden otra dirección, no es posible por diseño. Lo que sí
escogen es el color del corazón de cada huellita y **el de cada dedito**: los
cuatro pueden ser distintos («negro-blanco-negro-blanco»), y así llegan al
dibujo, al resumen y al pedido.

- Vive en: `VUELTAS` en `app/adapters/render/huellita.py`;
  `Huellita.dedos_alternos` y `colores_de_los_dedos` en
  `app/domain/personalizacion.py`.
- Por qué: el 20/09 Camilo mostró con fotos del anillo real cómo van las
  huellitas, y el dibujo las ponía todas mirando igual. Y «negro-blanco-negro-
  blanco» se guardaba como un solo color: el taller habría recibido un anillo
  unicolor con una nota al margen.

## R2j · «Ya no me gustó» borra el color

Si dice que ya no le gusta el color y todavía no dice cuál quiere, los colores
se borran y se le vuelven a preguntar. No se sigue con el grabado hasta que
escoja.

- Vive en: la acción `QUITAR_COLORES` y `sin_colores()`
  (`app/domain/asesora.py`). Es una acción y no un campo: un campo más rompe el
  esquema del modelo (ADR 0021).
- Por qué: el 20/09 una clienta dijo «No ya no me gusto» del fucsia; el borrador
  siguió en fucsia y la conversación pasó al grabado. Ese anillo se habría
  fabricado del color que ella rechazó.

## R2k · Siempre se pregunta algo, y una cosa a la vez

Mientras le falte algo a ella, cada mensaje termina con una pregunta: que sepa
que le toca y qué (cuándo NO se pregunta: R3b). **Una sola, una cosa útil a la
vez** (Camilo, 09/10), también debajo de las cuentas (R4): dos preguntas
seguidas sobre cosas distintas la confunden. Si contesta una parte, se sigue con
lo que quedó faltando. Si el modelo no preguntó
nada, Python pone la de lo siguiente que falta (no si ella solo agradeció: R3b) —o «¿Así está bien?» tras el
resumen—. Si esa frase fija ya se dijo igualita en la charla, va con otras
palabras («Para pasar tu pedido al taller, ¿…?» si ya pagó; «Y cuéntame, ¿…?»);
solo si eso también ya se dijo, se calla (12/10). Solo se calla cuando lo siguiente lo hace Lía (verificar un pago, sacar
el anillo del taller). Esperando el comprobante se cierra con `QUEDO_ATENTA`
(R2g).

- Vive en: `_le_falta_la_pregunta()`, `_lo_que_falta()` y `COMO_SE_PREGUNTA`
  (`app/conversacion/asesora.py`); la regla «TERMINA SIEMPRE CON UNA PREGUNTA»
  del prompt.
- Por qué: el 20/09 le llegó el resumen del pedido y debajo «¡Perfecto Camilo!
  🫶», y ahí se quedó. Otra clienta recibió «¿Cooper es uno solo…?» y «¿Lo dejo a
  nombre de Jose Pérez?» a la vez, y no volvió a escribir.

## R2l · El nombre se propone, no se pide dos veces

Se pregunta una vez. Si contesta otra cosa, se le propone el que tiene en
WhatsApp («¿Lo dejo a nombre de Laura Gómez? 🥰»): entra al resumen, y su «sí» al
resumen lo confirma. Si ya pagó y sigue sin nombre —también si pagó con el pedido
a medias (`pagado_sin_pedido`), que es como pasa de verdad: sin nombre el pedido
no nace—, pasa a Lía una sola vez, con una nota que dice cómo aparece en
WhatsApp. Después de ese aviso ya no se le propone: sería una segunda pregunta.

Si el modelo se lo vuelve a preguntar en otro turno, con las palabras que sean,
esa frase se quita y en su lugar va la propuesta. Solo cuando es la única
pregunta del mensaje; sin nombre de WhatsApp se deja como venía.

- Vive en: `_lo_del_nombre()` y `_cambiar_por_la_propuesta()`
  (`app/conversacion/asesora.py`), con el `sender_name` que llega de Meta.
- Por qué: en una conversación real la clienta transfirió los $60.000 y el
  pedido no nació: le pidieron el nombre cuatro veces y nunca lo escribió. Lía lo
  tiene delante en el contacto y no lo habría preguntado ni una.

## R2m · La cantidad no se adivina, pero lo que ella escribió cuenta

La cantidad cambia el precio: un «sí» a «¿de 1 o de 2?» no elige. Pero si ella
ya escribió cuántas huellitas —aunque haya sido en el primer mensaje—, eso
cuenta, siempre que sea un número DE HUELLITAS y el mismo que se propone («una
foto» no es una huellita). A la tercera vez preguntando sin respuesta, pasa a
Lía.

- Vive en: `cantidad_respaldada()` y `cuantas_huellitas_escribio()`
  (`app/domain/asesora.py`); `VECES_ANTES_DE_LIA`.
- Por qué: abrió con «quiero el de 3 huellitas» y al turno siguiente le
  preguntaron de cuántas lo quería. En un repaso, la descripción de una foto
  («una foto…») validó 2 huellitas que nadie pidió. Y otra dio vueltas cuatro
  veces con «listo, así» hasta decir que ya había pagado.

## R2n · Varios anillos: de a uno, y un solo cobro

Si compra más de un anillo, se PREGUNTAN de a uno y en orden: cantidad de
huellitas, talla, colores y grabado del primero; hasta que no está completo no
se pregunta por el siguiente. Pero lo que ella adelanta de otro anillo diciendo
cuál («talla 6 el de una», «para el de tres: …», «el segundo») se guarda en ESE
anillo, y la foto de la regla sin decir de cuál va al que todavía no tiene
talla. «Y otro de 1» ya deja anotado que el nuevo es de 1 huellita. La talla se
pregunta una vez («¿son de la misma talla?»); vale para todos solo si ELLA lo
dice (un «sí» a otra pregunta no cuenta); si no, se pide la de cada uno.
Es UN pedido con una línea por anillo: un abono ($60.000 × anillos) y un saldo,
de todos juntos, en una transferencia cada uno. En el ERP cada anillo es una
venta (`PED-…-A1`, `-A2`); en el panel cada anillo tiene su talla y sus datos.
Con el pedido ya creado, agregar o quitar un anillo lo hace Lía.

- Vive en: las acciones `OTRO_ANILLO`, `UN_ANILLO_MENOS`, `MISMA_TALLA` y
  `contar_anillos()`, `anillo_del_mensaje()`; `Borrador.anillos` y
  `por_empezar`, `enfocar()`, `pasar_al_siguiente()`,
  `anillos_del_pedido()` (`app/domain/asesora.py`);
  `Mundo.crear_pedido_de_anillos()`; `erp.por_anillo()`.
- Por qué (02/10, prueba de Lía: uno de 3 huellitas y otro de 1): mezcló los
  colores de los dos, perdió la talla 6, le pisó una huellita al primero, dijo
  que Lía confirmaba una talla que nunca le mandaron y cobró el abono de un
  solo anillo. El primer arreglo, que solo dejaba anotar en el anillo que iba,
  falló en el ensayo con la IA real: la foto de la regla del de 3 le pisó la
  talla al de 1 y los nombres del de 3 quedaron en el de 1.

## R2o · El grabado lleva corazones ENTRE los nombres

Un nombre por renglón y el sistema pone ♡ entre cada uno, nunca al final
(«Lulú ♡ Pepito ♡ Nala»). Si ella pide otra cosa (sin corazones, otro símbolo),
va en un solo renglón tal cual lo quiere.

- Vive en: `unir_grabados()` (`app/domain/personalizacion.py`): lo usan el
  resumen, el taller, el panel, el Excel y el ERP (ahí sin espacios:
  «Lulú♡Pepito»).
- Por qué (Lía, 02/10): salió «Lulú ♡ Pepito ♡ Nala ♡».

## R2p · La cadena: solo si ella pregunta

Segundo producto (Camilo, 03/10): **cadena personalizada con huellita y nombre**,
$250.000, abono $65.000 (`CAD-HUE-1` en `data/catalogo.csv`, categoría
`cadenas`). El bot **nunca la ofrece** (ni recomendación, ni venta cruzada, ni al
despedirse). Solo si la clienta pregunta por cadenas (collar, dije, colgante) o
por más productos («¿qué más tienen?», «¿solo anillos?») le llega el mensaje de
Camilo con las 3 fotos (`cadena_1..3`), una vez por conversación.

- **UNA huellita, siempre** (`personalizacion.HUELLITAS_DE_LA_CADENA = 1`; no
  existe cadena de 2 ni de 3). Si la piden con más, el sistema mismo lo dice
  (`CADENA_CON_UNA`: «La cadenita se hace con una sola huellita 🐾 Si quieres más
  de una, el anillo sí puede llevar hasta 3 💍») y `aplicar` no anota otra
  cantidad. Clientas `erika_cadena` y `dani_cadena_dos` en la prueba de verdad.
- La huellita (corazón + 4 deditos, del color o los colores que quiera), **sin
  talla**, y el **nombre grabado es obligatorio**: un renglón por lado, hasta 2
  nombres por lado, 2 lados (los nombres sueltos se acomodan de a dos y se le
  confirma). Se le muestra la foto de su huellita y confirma el resumen antes
  del abono, igual que el anillo.
- Puede ir sola o con anillos en la misma compra (un abono y un saldo de todo;
  la cadena tiene su propio abono). Los avisos dicen «tu cadena» o «tu pedido».
- **El catálogo del perfil de WhatsApp** (conectado el 03/10) sí la muestra: ahí
  es ella la que busca. Si escribe desde un producto del catálogo, el webhook le
  antepone al texto «[Escribe desde la vitrina de WhatsApp, mirando: …]»
  (`catalogo_meta.con_el_producto`): desde la cadena eso cuenta como preguntar por
  ella; desde un anillo, no (por eso la nota no dice «catálogo», que sí abriría la
  puerta). Si su PRIMER mensaje ya pregunta por la cadena, no recibe la ficha del
  anillo: lo lee el modelo (`_apertura`).
- En el ERP es una venta de «Cadena» (Cat_Productos ya la tiene, con su receta);
  en el panel, sin talla y con el grabado «lado 1 / lado 2».
- Vive en: las acciones `MOSTRAR_CADENA` y `ES_CADENA`; `pregunta_por_cadenas`,
  `quitar_cadena_no_pedida` (si el modelo la nombra por su cuenta, la frase se
  quita), `Borrador.pieza` (`app/domain/asesora.py`); `Personalizacion.pieza`,
  `lados_de_la_cadena` (`app/domain/personalizacion.py`); `Product.categoria`.
  Los precios de los anillos se leen solo de la categoría `anillos`.

## R2r · El anillo de corazón: sí se ofrece (17/10)

El otro diseño de anillo (Camilo, 17/10): **un corazón de circón** del color que
ella escoja, en vez de huellitas; plata Ley 925, en su talla, hasta 5 nombres
grabados por dentro, abono $60.000, 10 a 15 días, fotos antes del saldo.
**$200.000** (`ANI-COR-1` en `data/catalogo.csv`, categoría `corazones`; fotos
`anillo_corazon_1` y `_2`). Se presenta como anillo de promesa sin limitarse a eso.

- **A diferencia de la cadena, sí se ofrece**, desde el primer mensaje, cuando
  viene al caso: no le convence la huellita («uno que no es de huellita,
  solamente con la piedrita», Martha 17/10), es para la pareja o una promesa,
  pregunta por otros diseños. `MOSTRAR_CORAZON` manda su presentación
  (`HechosDelNegocio.ficha_del_corazon`, la misma estructura que la ficha de la
  huellita) con la foto, una vez por conversación; si pregunta por él, va sola
  (sin además la de la huellita, salvo que pida los dos de entrada).
- `ES_CORAZON` marca la pieza (`Borrador.pieza = "corazon"`): un solo corazón
  (`PIEDRAS_DEL_CORAZON`), su color en la huellita 1 (corazón = dedos), talla y
  grabado como cualquier anillo. Si vio solo su presentación, lo que dice
  después es de ese anillo aunque la IA no lo marque (`viene_por_el_corazon`).
  Las preguntas fijas hablan del corazón. «Así se te va a ver» (Camilo, 17/10):
  como en la huellita, pero SOLO el corazón, al derecho, de su color
  (`RenderDeHuellitas.previsualizar_corazon`: la máscara 1 de la foto base,
  completada por simetría donde la tapa el dedito, volteada, borde suavizado y
  agrandada a 1080 px, JPG 95 sin submuestreo de color).
- **No confundir**: «el corazón rosado» de una huellita es la piedra de la
  patita (`habla_del_corazon` exige «anillo de corazón», «el de corazón», «sin
  huella», «solo con la piedrita», «de promesa»…).
- ERP: «Anillos 1 huella» (mismo precio; falta cargarlo en Cat_Productos con
  sus gramos) y «Anillo de corazón · ♡ color» en el detalle.

## R2s · Promociones: solo las que están cargadas (17/10)

`data/promociones.csv` (nombre, detalle, desde, hasta, activa). Cada turno el
estado del pedido trae `PROMOCIONES ACTIVAS HOY` (vigentes por fecha de
Colombia). Hoy está vacío: el bot dice con transparencia que no hay ninguna
promoción activa y nunca inventa ni promete una. Red de seguridad: `vigilar`
quita la frase que ofrece una promoción que no está en la lista («tenemos 2x1»,
«20 % de descuento»); decir que no hay sí se puede.

## R2q · Lo que encontró la prueba de verdad (04/10)

Camilo, 04/10, con dos errores vistos en una charla real: «las pruebas fueron
deficientes; crea una prueba de verdad». `scripts/prueba_de_verdad.py` (`vb verdad`):
27 clientas con la IA real, aisladas; ver el instructivo, paso 6. Lo que quedó:

- **La talla que ella DICE queda lista** («si dan la talla no hay nada que
  verificar; eso es solo si mandan la foto del anillo con una regla»). Solo la foto
  de la regla y la medida escrita esperan a Lía (`aplicar`: `talla_confirmada`; una
  foto en revisión no se la salta un número que repita el modelo). **Dictada por voz
  también** (05/10: «talla seis» llegó como «Gamma seis»): `talla_dictada` la lee sin
  IA —«talla» o como la escriba el dictado, con un número; o un número suelto justo
  después de preguntarla—. Con la talla dicha **no se duda de ella**: la guía solo
  si la pide (`pide_la_guia`), y el vigilante quita «te confirmo la talla» y «¿es la
  definitiva?» cuando no hay ninguna por confirmar.
- **Sin anillos para medir: el contorno del dedo con papel o hilo, con video**
  (Camilo, 13/10: «ir a la joyería para gente que no tenga anillo puede ser un cuello
  de botella importante»; es lo que se le dijo a Laura el 05/10 y con eso abonó).
  «No tengo anillos» -> mensaje fijo `TALLA_SIN_ANILLOS` + el video
  `medir_talla_dedo` con «Cuando lo midas, me cuentas cuántos centímetros te da 💍»
  (sin IA: `no_tiene_anillos`; «no tengo» a secas, solo justo después de la guía) y,
  si falta algo del anillo, se sigue armando. No se le manda la guía de la regla (es
  para medir un anillo). Si la IA también lo explicó, se quita lo suyo (va una vez).
  Los centímetros que escriba van a Lía (`tallas.CONTORNO_CM` da las posibles) y Lía
  confirma la talla. Antes (Lía, 05/10) se mandaba a la joyería «porque medir el dedo
  es inexacto». Clienta `laura_sin_anillos` en la prueba de verdad.
- **Solo en plata** (Camilo, 05/10; real: «¿Solo en plata? ¿No hay dorado?»). No se
  hacen baños de oro ni de otros colores porque con el tiempo se pelan, y la joya tiene
  que durar toda la vida. Lo dice el sistema, siempre igual (`faq.SOLO_EN_PLATA`, el
  mismo texto de la pregunta frecuente `COLOR_DORADO`). Si es lo único que pregunta,
  sin IA, y vuelve a la pregunta que estaba abierta con otras palabras («Y cuéntame,
  ¿sabes…»); si viene con otra cosa, la regla va arriba y el modelo contesta lo demás
  (lo que el modelo dijo del metal se quita: `sin_lo_del_metal`). Nunca se ofrece otro
  metal ni un baño. **«El corazón dorado» es una piedra** (el circón amarillo): no
  dispara la regla (`pregunta_por_otro_metal`). Clienta `vale_dorado` en la prueba de
  verdad; en el flujo, el **A5**.
- **Un comprobante no se juzga.** Si el valor no es exacto (el costo de la
  transferencia), el nombre sale tapado o es otra cuenta: «¡Recibido! 🙌 Lía revisa tu
  comprobante…», nota para Lía con lo que se leyó y la charla marcada para una
  persona (`duda_del_comprobante`, `COMPROBANTE_RECIBIDO`). Con el pago pendiente, una
  foto con plata ES el comprobante (`parece_un_pago`), y «ya te transferí» lo registra.
  Si mandó el comprobante y el bot no lo dijo, se antepone «¡Recibido! 🙌». Si pagó
  antes de terminar, al completar no se le vuelven a mandar las cuentas.
- **Varios anillos:** «el mío talla 6 y el de ella talla 8» -> cada una a su anillo
  (`tallas_para_varios`, también si lo dijo antes de que existiera el segundo);
  «los dos de una huellita» -> la cantidad a todos (`cantidad_de_todos`); «el de
  ella / el de mi hermana / el otro» es el segundo y «el mío» el primero (con dos).
- **Cambiar algo después del resumen** manda el resumen nuevo en ese turno: su «sí»
  siguiente ya trae las cuentas (no confirma dos veces).
- **Un «sí / así está bien / perfecto» con el resumen completo ya mostrado y sin
  cambios ES la confirmación**: van las cuentas, aunque el modelo haya preguntado
  otra cosa del resumen («¿Simba va en el lado 1?») (`solo_afirma`).
- **Desde la cadena de la vitrina**, si nunca la vio, se le muestra (precio, fotos).
- **Los datos de envío no se preguntan antes de tiempo** (regla del 20/09, ahora con
  guardia en Python): antes de que el anillo esté listo se quita cualquier pregunta
  por ciudad, dirección, cédula o celular (`quitar_pedida_de_envio`). Pasó: «¡Recibido!
  🙌 Ya tomé tu pedido 🫶 ¿A qué ciudad te lo enviamos cuando esté listo?».
- **Una sola pregunta también en lo reescrito** (la segunda pasada del modelo).
- **El grabado con fecha** va pegado: «Morita 21/09/23», sin ♡ antes de la fecha.

## R3 · También se puede recoger

Punto de recogida: `faq.PUNTO_DE_RECOGIDA` = «el conjunto Caminos de
Ejemplo, en Floridablanca» (nunca más que eso: R17). No se cobra envío. Si la
clienta es del área metropolitana (`faq.CIUDADES_CERCA`), el bot se lo ofrece
cuando manda las cuentas. Si recoge, no hace falta dirección ni ciudad, y los
avisos cambian: nada de «va en camino»; «te lo dejo listo en la portería del
conjunto» (`guion.AVISOS_RECOGE`).

## R3b · Se pregunta solo lo que hace falta (06/10 · 07/10)

Termina con una pregunta **mientras le falte algo a ella** (o haya una duda real). Si
le preguntó algo y ella contestó OTRA cosa o solo una parte, **se le sigue preguntando
lo que falta** (Mónica, 07/10: «No así toda» quedó sin que se le volviera a pedir el
grabado). Si no contesta nada, no se insiste: el recordatorio lo hace al día
siguiente. (**Los recordatorios están pausados desde el 13/10**: donde aquí dice «lo
retoma el recordatorio», hoy nadie lo retoma; Lía lo ve en Chatwoot.) No se pregunta
(`asesora`, al armar el mensaje):

- **Cuando no le falta nada** (`nada_que_preguntarle`): lo que sigue es de Lía —la talla
  por confirmar, el pago por verificar, el taller, el despacho—, ya pagó, o **ya tiene
  las cuentas y solo falta que pague**. Ni la coletilla («¿te parece?»)
  (`sin_preguntas_de_mas`); si no queda nada, «¡Con gusto! 🥰». Debajo de las cuentas
  va UNA vez «Quedo atenta a tu comprobante 💓 Cualquier duda, me cuentas 🫶», sin
  pregunta. Lo que pregunta el sistema («¿Me compartes el comprobante?») se queda.
- **Cuando ella pospone** (`recordatorios.pospone`: «mañana le consigno», «ahora no me
  queda fácil», «lo pienso», «el otro mes», «pal otro mez», «a fin de mes», «para
  diciembre»): solo se le agradece y se cierra, **sin preguntas y sin prometer
  escribirle ni «programar un recordatorio»** (`sin_promesas_de_escribir`). Si es
  para otro mes (`_PARA_OTRO_MES`) no sale ningún recordatorio; si es «mañana», el
  recordatorio sale al primer horario (si escribió a las 9 p. m., a las 9 a. m.).
  Excepción: si ELLA pide que le escriban («escríbeme el otro mes»,
  `pide_que_le_escriban`), se le dice que sí, sin fecha, y a Lía le llega una nota
  privada «📅» para que le escriba ella. Clienta `nati_ubicacion`.
  También cuenta como posponer que diga que escribe cuando tenga algo (13/10): «cuando
  tenga una talla los contactaré de nuevo», «apenas lo haga le escribo».
  **Dejarlo listo** (Camilo, 13/10: «que se sienta cordial, que escucha, no un robot
  hostil»): si todavía falta diseñar su anillo (cantidad, colores o grabado) y no es
  un «no» (`recordatorios.rechaza`), se le ofrece **una sola vez**
  (`ofrecer_dejarlo_listo`): «¡Claro, sin afán! 🫶 ¿Te gustaría que mientras tanto
  dejemos tu anillo personalizado listo? Así solo quedarían pendientes la talla y el
  abono. Y si no, igual quedo muy atenta a cuando tengas la foto de la medida 📏💍».
  Si dice que sí, se sigue diseñando sin pedirle lo que dejó para después; si no, se
  cierra cálido. Si **ya está diseñando** y lo que deja para después es medirse, no
  se le pide permiso: «¡Claro, sin afán! 🫶 Mientras tanto vamos dejando listo tu
  anillo, y así solo quedarían pendientes la talla y el abono. ¿…lo siguiente?»
  (`SEGUIMOS_DISENANDO`). «Le pido la foto a ella y ya te la mando» es la foto de la
  medida, no lo último que se le preguntó (`lo_deja_para_despues`). «El otro mes» también lo lleva (sigue sin recordatorios). Clientas
  `los_contacto` y `nati_ubicacion`. Reemplaza «pospone → cerrar sin preguntas» cuando
  falta diseñar; con el diseño completo («mañana le consigno») sigue igual.
- **Cuando solo agradece** (`recordatorios.solo_agradece`, 13/10: «Gracias por la
  información», «Vale gracias»): el sistema no le pega su pregunta de relleno; va
  «¡Con gusto! 🥰». Si está a mitad de su diseño y le falta algo, la pregunta que haga
  la IA se queda. Clienta `solo_gracias`.
- **Cuando le da miedo abonar o desconfía** (Camilo, 13/10; real, Nora: «no me gusta
  que tiene que dar vueltas plata adelantada»). Es lógico: no nos conoce. Se le
  contesta desde el sentir, no desde los números (prompt, «CUANDO LE DA MIEDO
  ABONAR»), corto y en renglones: 1) validar lo que siente («Te entiendo muchísimo
  🫶 es normal sentir eso cuando todavía no nos conoces»); 2) el porqué: su anillo
  se hace solo para ella, el abono es lo que permite empezarlo en el taller y el
  resto lo paga cuando vea las fotos terminado; 3) cómo conocernos, solo lo
  verdadero: lunajoyas.example («creando piezas especiales desde 2019») e Instagram
  @lunajoyas, plata 925 con garantía, anillos hechos (MOSTRAR_EJEMPLOS); si
  teme que no le llegue, Coordinadora con número de guía; 4) sin afán: a lo sumo
  «¿Te gustaría que sigamos armando tu anillo?», nunca «¿De cuántas huellitas?»
  pegado (`teme_abonar`). «Plata adelantada» es dinero, no el metal: no cuenta como
  desinterés. El vigilante deja pasar SOLO esa página y ese Instagram
  (`REDES_DE_VERDAD`) y deja explicar que el abono lleva el anillo al taller
  (`explica_el_abono`); decir que YA está en el taller sigue prohibido. Clienta
  `nora_miedo_al_abono`. «Más de 8 años» NO se dice: la página dice desde 2019.
- **«Caro» con una pregunta es una objeción, no un no** (13/10): «muy caro, ¿no tienen
  descuento?» se contesta con calma (no hay descuentos; empieza con $60.000 de abono;
  plata Ley 925) y se sigue. «Uy no, muy caro», sin pregunta, sí es un no. Clienta
  `curiosa`.
- **Cuando la IA ya se despidió** («Si algún día te animas, aquí estoy», `se_despide`):
  debajo no va la pregunta de relleno (13/10: a «uff está como caro» le llegaba la
  despedida y debajo «¿De cuántas huellitas lo quieres?»).
- **Con la guía ya en sus manos** y hablando de otra cosa, no se le vuelve a preguntar
  por la talla: está midiendo; se sigue con el diseño (13/10).
- **Cuando es un regalo** («es para regalarle a mi hija pero no vive conmigo»,
  `es_para_otra_persona`): la guía va con «¡Qué lindo regalo! 🥰 Te comparto la guía
  para que se la pases: ella puede medir un anillo suyo con una regla y mandarte la
  foto, o el contorno de su dedo con una tira de papel y decirte los centímetros 📏».
- **Cuando solo reacciona** con un emoji a un mensaje (13/10): no se le contesta; se ve
  en Chatwoot (`asesora.solo_reacciona`). Excepción: un 👍 a «¿Así está bien?» o a
  «¿Lo dejo a nombre de…?», que es un «sí». Antes recibía «¡Anotado! 🫶» y «¿De cuántas
  huellitas lo quieres?».

- **Para confirmar lo que ella dijo claro y quedó anotado** (`cambio_anotado`,
  `sin_confirmar_lo_dicho`): «Adela» -> nada de «¿así quedan los dos nombres?». Si la
  IA no lo anotó porque dudó, su pregunta se queda. Si solo confirmaba, «¡Anotado! 🫶».

**Las situaciones** (Camilo, 09/10), y qué hace el bot en cada una:

| Ella… | Ejemplo | El bot |
|---|---|---|
| No ha respondido | (silencio) | Nada; el recordatorio sale en su horario (ADR 0017). |
| Respondió a medias | «No así toda» (sin el grabado) | Anota y pregunta lo siguiente que falta, una cosa. Lo que no contestó se le pide **una vez más**; después, el recordatorio. |
| Dice que lo manda después | «la medida te la confirmo en la tarde» | Lo anota y **no se lo vuelve a pedir en la charla** (ni con «¿?» ni con «mándame…»). Le llega **un** recordatorio sobre eso y ya. |
| Rechaza una pregunta | «no quiero grabado» | Lo acepta: si es opcional, no la vuelve a preguntar; si es indispensable (talla, colores, cantidad), explica en una frase por qué hace falta y sigue. Clienta `lina_sin_grabado`. |
| Pospone la compra | «el otro mes», «mañana», «apenas mida le escribo» | Lo acepta con cariño; si falta diseñar, le ofrece UNA vez dejar el anillo listo (arriba). |
| Solo agradece | «Gracias por la información» | «¡Con gusto! 🥰», sin la pregunta de relleno (arriba). |
| Solo reacciona | ❤️ a un mensaje | Nada (salvo el 👍 al resumen o a su nombre). |
| No le interesa, por poco que sea | «no me gusta la plata», «no los voy a pedir», «muy caro», «solo miraba», «estaba averiguando solamente» | Agradece y cierra en una frase («¡Gracias por contarme! 🫶 Si algún día te animas, aquí estoy 💓»), sin ofrecer nada (ni la cadena), sin preguntar y sin prometer nada. **Ningún recordatorio más** en esa charla (`Borrador.sin_recordatorios`) hasta que ella retome el pedido. Clienta `no_le_gusta_la_plata`. |

**Sin recordatorios para quien no le interesa** (Camilo, 10/10). Real: «Es que no me
gusta la plata» y al otro día le llegó un recordatorio; «No no los voy a pedir porque
te dije que no me gusta la plata» y le llegó la información de la cadena (el filtro
leyó «te dije» como «un dije») y otro recordatorio. Desde el 10/10:

- El desinterés, por pequeño que sea, apaga los recordatorios de la charla para
  siempre (`sin_recordatorios`), no solo por un silencio. Vuelven si ella retoma el
  pedido (escoge algo, dice que lo quiere).
- Se detecta de tres formas, para no depender de la ortografía: lo que ella
  escribe (`recordatorios.no_quiere`, ampliado), lo que contesta la IA cuando lo
  entendió así («disculpa por insistir», «gracias por decírmelo»:
  `el_bot_entendio_que_no`) y, **antes de mandar CADA recordatorio, la IA lee la
  charla** (`workers/recordatorios.JUEZ`): si hay cualquier señal de desinterés
  («nah muy karo pa mi», «no me convense», «pense q era mas barato»), no sale. Si
  la IA no contesta, mandan las palabras. Quedarse callada NO es desinterés.
- En la charla: se agradece y se cierra, sin mostrarle nada que no pidió.

**No acosar** (Camilo, 09/10, la charla de Yulieth). Ella escribió «No la medida te
las confirmo en la tarde pero sería uno más grande que el otro» y el bot le pidió la
talla cuatro veces más, a veces sin signo de pregunta («Me falta la medida…; cuando
puedas, mándame la foto con la regla»). Lo que dijo para los dos anillos («cada
anillo con una sola huella», «una lila y la otra fucsia», «Khalifa en los dos») se lo
volvió a preguntar en el segundo. Desde el 09/10:

- **Lo que dice que manda después** (`lo_deja_para_despues`, `Borrador.lo_manda_despues`)
  no se le pide más: `sin_pedir` quita cualquier frase que lo pida, con o sin «¿?», y
  el estado le dice a la IA «NO LE PIDAS AHORA». Le llega UN recordatorio sobre eso
  («Quedé pendiente de la talla que me ibas a confirmar 📏…», etapa `despues_talla`)
  y ninguno más (ni el segundo ni la plantilla). Si ella vuelve a hablar de eso, se
  suelta.
  Irse a medir el dedo (no tiene anillos) cuenta igual: la talla la trae ella.
- **Después de pagar** (12/10), lo que falta se le pide aunque ya se le haya
  pedido: es para pasar su pedido al taller, no para venderle. Lo que dijo que
  manda después se sigue respetando.
- **Si DICE que compra varios** («quiero dos anillos», «serían dos anillos»), se
  crean en ese momento aunque la IA no marque «otro anillo» (`anillos_que_pide`), una
  sola vez. Antes, a veces lo del segundo quedaba en el primero o se perdía.
- **Varios anillos** (12/10): si ella no habla de talla en ese mensaje, la IA no
  puede copiarle a un anillo la talla de OTRO (a «el de ella todo celeste» le ponía
  al de la hermana la talla del primero).
- **Lo que no contesta** se le pide una vez más (`VECES_QUE_SE_PIDE = 2`,
  `Borrador.veces_pedido`); después ya no se le pide en la charla: lo retoma el
  recordatorio de su horario. El recordatorio cuenta como una vez.
- **Lo que ya está anotado** no se le pide ni se le confirma (cualquier cosa: cantidad,
  talla, colores, grabado, su nombre).
- **Lo dicho para todos los anillos** queda en cada uno (`cantidad_de_todos`,
  `colores_por_anillo`, `grabado_para_todos`). «La otra» en «una lila y la otra fucsia»
  no es «habla del otro anillo»: es un color para cada uno, en orden.
- Si a otro anillo solo le falta lo bloqueado, no se le dice «vamos con el siguiente
  anillo»: se sigue con lo que sí falta (su nombre).
- Clienta `yulieth_dos_anillos` en la prueba de verdad (revisión `no_pide`).

Y se entiende lo que escribe corto o mal (regla «INTERPRETA CON EL CONTEXTO» del
prompt, más lecturas sin IA): «De una» a «¿de cuántas huellitas?» es 1
(`cantidad_contestada`); «La verdad creo que soy 7» es talla 7 (`talla_dictada`); un
color es toda la huellita, sin preguntar si combina corazón y deditos, salvo que ella
lo insinúe.

Lo que va grabado, entre comillas latinas cuando el bot lo nombra (`con_comillas`),
sin anidarlas: «Campanita ♡ Dulce ♡ Eva». Pasó con Laura (06/10) y Mónica (07/10).
Clientas `sara_espera_a_lia` y `monica_escribe_corto` en la prueba de verdad.

**La cadena, de una** (07/10): si pregunta por la cadena y no se le ha mostrado, la
información va en ese mismo turno (`MOSTRAR_CADENA`), sin «¿quieres que te cuente cómo
es?» (Erika). Clienta `erika_cadena`.

## R4 · Si se habla de plata, van las cuentas

Cualquier mensaje que mencione el abono o el saldo lleva las cuentas en el
mismo mensaje.

- Vive en: la acción `MANDAR_CUENTAS` y `faq.datos_para_transferir()`.
- Por qué: el 19/09 el bot dijo «quedo atenta al comprobante» sin decir a dónde
  transferir. La clienta tuvo que preguntar.
- **Si ELLA quiere pagar, aunque falten datos, se le manda la cuenta** (Camilo,
  05/10). El bot no persigue el pago con el pedido a medias, pero si ella la pide o
  lo insinúa («regálame por fis la cuenta», «sí lo quiero, ¿cómo te pago?», «quiero
  ir abonando»: `quiere_la_cuenta`; o la IA pide `MANDAR_CUENTAS` y ella habla de
  pagar), sale la cuenta y DEBAJO, con cariño, **una sola cosa** de lo que falta
  (09/10; antes hasta tres): «Cuando puedas, ¿me compartes tu nombre completo para
  dejar tu pedido completo? 🫶». La talla no se le pide mientras la está midiendo
  (guía o joyería). Lo demás, en los turnos siguientes. Nunca «para poder iniciar me faltan…»
  encima de los datos. «Después te pago», «todavía no» o «la quincena»
  (`paga_despues`): no. El pedido nace cuando esté completo (`pagado_sin_pedido`).
  Pasó con Yesi (05/10): «Regálame por fis la cuenta para realizar el abono» no
  salió y tuvo que mandarla una persona. Clienta `yesi_insinua` en la prueba de
  verdad.

## R5 · Un pago lo confirma una persona

El bot **nunca** dice que un pago está confirmado. Recibe el comprobante, lo
registra y lo deja en `EN_REVISION_PAGO` con la alerta `pago-por-verificar`.

- Vive en: ADR 0011 y `operacion.montos_al_llegar`.
- El cobro automático está parado a propósito.

## R6 · Después de pagar no se vuelve a pedir el abono

- Vive en: la guarda de `PEDIR_ABONO` en `app/conversacion/asesora.py`.
- Por qué: pasó. Es la forma más rápida de que una clienta crea que le van a
  cobrar dos veces.

## R7 · Sin talla no se funde nada

`falta_para_taller()` exige el anillo completo antes de `EN_PRODUCCION`. El
panel ni siquiera muestra el botón: los botones salen de la tabla de
transiciones, no de un `if` en el HTML.

## R8 · Una transición que no existe, no pasa

`TRANSICIONES` (`app/domain/order_state.py`) es la única verdad. Da igual que
alguien arme el formulario a mano: la validación está en el dominio.
`PRODUCCION_LISTA → DESPACHADO` no existe — primero se cobra el saldo.

## R9 · Quien está asignado es quien atiende (09/10)

Un solo criterio en Chatwoot del PC, del celular y en el panel
(`app/infra/quien_atiende.py`):

- **VentaBot** (por defecto): contesta el bot.
- **Una persona**: cuando escribe (desde Chatwoot o el panel), cuando empieza a
  escribir o cuando se la asigna, queda asignada a ELLA y el bot se calla 12 h
  desde lo último que escribió (`atencion.HORAS_DE_PAUSA`).
- **Devolver al bot** es una acción propia: dejar «Agente asignado» en
  **«Ninguna»**, asignarla a VentaBot, la macro «🤖 Devolver al bot», la etiqueta
  `hacer-devolver-al-bot` o «Que siga el bot» en el panel. Sin asignar no se deja
  nunca: vuelve a VentaBot.
- **Resolver solo cierra** y quita la alerta de «necesita persona»; no cambia
  quién la atiende (antes la devolvía al bot).
- Si pasan las 12 h sin que nadie la devuelva y la clienta escribe, el bot la
  retoma y deja una nota privada «⏰» para que se entienda el cambio.

Cómo se hace paso a paso: `docs/sistema/05-chatwoot-y-operacion.md`.

## R10 · El bot no se oye a sí mismo

Lo que el bot copia a Chatwoot va firmado por el agente bot «VentaBot». Cuando
Chatwoot se lo devuelve por webhook, lo reconoce y lo ignora.

- Por qué: sin esto el bot se contestaba a sí mismo, duplicaba mensajes y
  acababa callándose solo por creer que había una persona escribiendo.

## R11 · El estado en Chatwoot dice quién la atiende (09/10)

- **«Pendiente»** = la atiende VentaBot. Chatwoot 4.17 no deja tener una charla
  asignada a un bot y «Abierta» a la vez.
- **«Abierta»** = la atiende una persona.
- **«Resuelta»** = cerrada. No se reabre sola, salvo que haya una alerta que
  necesite a una persona; si la clienta escribe, Chatwoot la reabre.
- Lo que necesita a una persona (necesita-persona, pago por verificar, datos
  incompletos, falta la dirección) queda con prioridad **Urgente** y en sus
  carpetas; el bot la sigue atendiendo mientras tanto.
- Por eso el filtro de la lista va en **«Todos»**: el 19/09 las «Pendiente» no se
  veían con el filtro por defecto y parecía que no llegaban mensajes.

## R17 · La casa de Lía no se dice (09/10)

No hay punto físico: es un taller de joyería en casa. A «¿dónde están?» se
contesta `faq.UBICACION`: Floridablanca, Santander; sin punto físico; se puede
recoger sin costo en el conjunto Conjunto Ejemplo; en Bucaramanga hay
domicilio y **su valor depende del domicilio** (nunca una cifra); al resto del
país, Coordinadora.

- **Nunca** la dirección, la torre ni el apartamento. `vigilar` borra cualquier
  frase del bot que los tenga (`faq.DIRECCION_DE_CASA`), y la pregunta se contesta
  sin llamar a la IA (`pregunta_por_la_ubicacion`, también mal escrita: «dnd
  qdan», «ubicasion», «tienen local?»). En Chatwoot, la respuesta rápida
  «/ubicacion» dice lo mismo.
- Por qué: hasta el 09/10 `PUNTO_DE_RECOGIDA` tenía la dirección completa con
  torre y apartamento, y el bot se la daba a cualquiera que preguntara.
- Clienta `nati_ubicacion` en la prueba de verdad.

## R12 · Una respuesta por ráfaga

Cinco mensajes seguidos de la clienta son un turno, no cinco (ADR 0012).

## R13 · El teléfono no se pregunta

Está escribiendo por WhatsApp. Ya lo tenemos.

## R14 · «1,8» no es una talla

Si el modelo pone un número entre 1,2 y 2,6 en el campo de la talla, no es una
talla: es la medida en centímetros de la foto de la regla. Se convierte a talla
y se marca «confirmar con foto».

- Vive en: la guarda de `aplicar()` en `app/domain/asesora.py`.
- Por qué: pasó con una clienta real y la talla se perdió — Python rechazaba
  «la talla 1.8 no existe en el mandril» y nadie se enteraba.

## R15 · Una dirección sin número no se guarda

«El barrio San Luis» no sirve para una guía de Coordinadora. Se pide completa.

## R16 · Nada se manda a una clienta desde una prueba

Las pruebas corren con la base en un temporal, el canal en consola, el modelo
simulado y los avisos apagados. El ensayo de Chatwoot levanta un **segundo**
bot en el puerto 8001 con su propia base, usa una clienta inventada y la borra
al terminar.

**Y tampoco se escribe en nada de verdad**: ni pruebas ni repasos pueden
alcanzar el Chatwoot ni el ERP del `.env`. Los repasos usan el modelo real —es
lo que miden— y nada más.

- Vive en: `ENTORNO_DE_PRUEBAS` (`tests/conftest.py`) y `ENTORNO_DEL_REPASO`
  (`scripts/repasar.py`), cada uno con su prueba.
- Por qué: una vez la suite copió conversaciones de mentira al Chatwoot de
  verdad. Y el 21/09, 33 repasos escribieron en la hoja CENTRO DE MANDO del ERP
  enlaces a `https://ejemplo.local` hasta que el bot los corregía a los 10
  minutos: el ERP arranca su hilo con `sqlite`, que es justo lo que usa un
  repaso.

---

## Los números del negocio

No se copian aquí a propósito — se leerían mal el día que cambien.

| Dato | Dónde vive |
|---|---|
| Precios y días de producción | `data/catalogo.csv` |
| Fletes (hoy: $17.500 a todo el país) | `data/fletes.csv` |
| Abono, cuentas, punto de recogida, tiempos | `app/domain/faq.py` |
| Los mensajes que se le mandan a la clienta | `app/domain/guion.py` |
| Tallas y diámetros | `app/domain/tallas.py` |
| Colores de circón | `app/domain/personalizacion.py` |
