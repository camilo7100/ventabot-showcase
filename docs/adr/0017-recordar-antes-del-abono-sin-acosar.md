# 0017 — Recordar antes del abono, sin acosar

**Estado:** Aceptada · rehecha el 04/10/2026; el CUÁNDO y el QUÉ, reemplazados por la [0029](0029-recordatorios-por-dias-separar-sin-talla-y-la-venta-a-meta.md) el 13/10 (la primera versión, del 17/09, solo
recordaba el abono a las 24 h y 72 h y nunca se encendió)

## Contexto

La venta más barata de recuperar es la que ya empezó: escribió, escogió colores,
se fue a medir el anillo… y se quedó callada. Camilo, 04/10: «medir un anillo es
un esfuerzo grande y es normal que se le olvide; pero si me escribe a las 2 de la
tarde no le voy a escribir a las 2 a. m., y me da miedo que la gente sienta que
la acosan. Haz lo que más me venda».

Del otro lado, en WhatsApp insistir se paga con bloqueos, y los bloqueos con el
número frenado por Meta. Un recordatorio de más no cuesta una venta: cuesta el
canal.

Lo que dice la práctica de recuperar carritos: el primer mensaje rinde más
pronto (la primera hora para un carrito; aquí más tarde, porque cada paso le
pide algo a ella), y rara vez vale la pena pasar de tres. Dentro de las 24 h
desde el último mensaje de ella se le puede escribir texto libre casi gratis
(1.000 mensajes de servicio al mes gratis; después ~US$0,0008 cada uno). Fuera de
la ventana, solo con una plantilla aprobada (~US$0,0125 una de marketing en
Colombia): con que 1 de cada ~400 cierre un anillo de $200.000, se paga sola.

## Decisión

**A quién:** solo **antes del abono**, solo si lo que falta es de ELLA (la talla,
la cantidad, los colores, el grabado, su nombre, el «sí» al resumen o el abono) y
solo si escribió **al menos dos mensajes** (o uno que ya es una compra: «quiero
hacer un pedido»). Nunca si la atiende una persona, si la charla está escalada a
Lía, si el bot le está contestando en ese momento o si es un número de prueba.

**Solo en DOS horarios: 9 a. m. y 5 p. m., hora de Colombia** (Camilo, 05/10: un
recordatorio salió a las 9:35 y «no está mal, lo que no me gusta es el horario»).
Así se deja un tiempo parejo para que ella haga lo que le tocaba.

**Cuántos y cuándo, por cada vez que se queda callada:**

1. **Uno según dónde se quedó**, en el primer horario que quede al menos 8 h
   después de su último mensaje: si escribió antes de las 9 a. m., a las 5 p. m.
   de ese día; si escribió después, a las 9 a. m. del día siguiente. Siempre
   dentro de sus 24 h (texto libre, casi gratis): quien escribió entre las 9:00 y
   las 9:30 recibe el de las 5 p. m., porque a las 9 a. m. siguientes ya se le
   habría cerrado la ventana.
2. **Otro, solo si cabe un segundo horario antes de que se cierre su ventana**
   (al menos 5 h después del primero; en la práctica, quien escribió de noche
   recibe uno a las 9 a. m. y otro a las 5 p. m.), con una razón para hacerlo hoy:
   la fecha en que tendría su anillo. Sin descuentos.
3. **Uno a los 3 días, con plantilla** (`retomar_diseno`, con los botones «Sí,
   sigamos» y «Más adelante»), solo si ya había invertido en su diseño (no a quien
   solo vio precios) y como mucho **una vez por semana** a la misma persona. Sale
   en el horario más cercano a la hora en que ella suele escribir (antes de la
   1 p. m., a las 9; si no, a las 5).

Si el servidor estuvo caído y se pasó un horario por más de una hora, ese no sale
(no se manda a deshoras): sigue el que toque.

**Si dijo que no** («no gracias», «no me interesa») o lo deja para otro mes («lo dejo pasar, quizás el próximo mes»), nada más hasta que vuelva a escribir. **Si pidió tiempo**
(«lo pienso», «te aviso», «más adelante»), uno solo: el de los 3 días si aplica;
si no, el último de la ventana. Si contesta, la cuenta vuelve a empezar con su
próximo silencio.

Los textos son **fijos** (cero IA) y cada recordatorio entra en la memoria del bot
como algo que dijo Lía: si ella contesta «sí», el bot sabe a qué. Lo enviado se
anota en la tabla `recordatorios_24h`: un reinicio nunca le vuelve a escribir.

**Esto es SOLO de los recordatorios: no cambia nada del flujo de la charla.**

## Dónde

- Reglas (funciones puras): `app/domain/recordatorios.py`.
- La vuelta cada 5 min: `app/workers/recordatorios.py`.
- Lo que lee y anota en la base: `app/adapters/repositories/recordatorios.py`.
- `RECORDATORIOS=true` lo enciende; `RECORDATORIO_CON_PLANTILLA=true` suma el de
  los 3 días (solo con la plantilla APROBADA en Meta).
- `vb recordatorios` dice a quién le toca qué y a qué hora, sin mandar nada;
  `vb recordatorios --plantilla` crea la plantilla en Meta o dice cómo va.

## Consecuencias

- La primera semana encendido, mirar la **calificación de calidad** del número en
  Meta. Si baja, lo primero que se apaga es el de los 3 días; después, todo.
- Probado en `tests/unit/test_recordatorios.py`: el horario (ninguno sale de
  noche, a ninguna hora en que ella escriba), cada etapa, a quién no, la
  plantilla y el worker contra la base de verdad (manda una vez, nunca repite).

## 09/10: más dulces

Camilo: «más dulces al responder, saludar, preguntar cómo está, cómo le fue en el
día o cómo amaneció». Cada recordatorio abre con un saludo según la hora en que sale
(`recordatorios.saludo`; 10/10, más sencillo: 9 a. m. «¡Buen día, …! 🌷 ¿Cómo estás?»;
5 p. m. «¡Buenas tardes, …! 🌷 ¿Cómo estás?»), que es su ÚNICA pregunta; debajo, lo
de su etapa dicho como invitación («cuando puedas…»), con huellitas y sin presión. El
que le llegó a Mónica («Te escribo por si te quedó alguna duda antes del abono») no le
gustó: el del abono ahora es «Tu anillo con la huellita de tu peludito sigue
guardadito tal como lo dejamos 🐾…».

«El otro mes» (y «pal otro mez», «a fin de mes», «para diciembre»): ningún
recordatorio (`_PARA_OTRO_MES`).

## 09/10: lo que dijo que manda después, un solo recordatorio

Yulieth: «la medida te las confirmo en la tarde». El bot se la pidió cuatro veces más
en la charla. Ahora (`asesora.lo_deja_para_despues`, `Borrador.lo_manda_despues`) no se
le pide más en la charla y la etapa del recordatorio es `despues_<qué>` («Quedé
pendiente de la talla que me ibas a confirmar 📏…»): UNO solo, sin el segundo ni la
plantilla. Ya enviado, ninguno más hasta que ella vuelva a hablar de eso
(`recordado_despues`). En la charla, lo que no contesta se pide una vez más y después
lo retoma el recordatorio (`VECES_QUE_SE_PIDE`). Ver R3b en `docs/sistema/03`.

## 10/10: el saludo sencillo y nada para quien no le interesa

- Saludo: «¡Buen día, …! 🌷 ¿Cómo estás?» (5 p. m.: «¡Buenas tardes, …!»). «¿Cómo
  amaneciste?» no le gustó a Camilo.
- Antes de mandar cada recordatorio, la IA lee la charla (`JUEZ` en
  `app/workers/recordatorios.py`, con el mismo modelo de la asesora, una llamada
  corta por recordatorio): si hay cualquier señal de desinterés, no sale y la charla
  queda sin recordatorios (`Borrador.sin_recordatorios`). Si la IA falla, mandan las
  palabras (`no_quiere`). Lo mismo si la asesora entendió en la charla que no le
  interesa. Real: a quien dijo «no me gusta la plata» le llegaron dos.
