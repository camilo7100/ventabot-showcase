# 0008 — Enseñarle cómo le va a quedar

**Estado:** Aceptada · 2026-09
**Contexto previo:** [0007](0007-un-modelo-aparte-para-mirar-fotos.md)

## Contexto

Catorce colores para el corazón por catorce para los deditos son **196 anillos
posibles**. La clienta los escoge mirando una foto de bolsitas de piedras sobre
una mesa.

Delante de eso mucha gente no elige. No es que no quiera el anillo: es que no
quiere equivocarse en algo que cuesta $200.000, se funde a mano y no se puede
devolver. Dice «déjame pensarlo» y no vuelve.

## Opciones

1. **Nada.** Que se lo imagine. Es lo que había.
2. **Fotografiar las combinaciones.** Lía tendría que hacer 196 fotos y
   rehacerlas cada vez que entre un color nuevo.
3. **Dibujarlo.** Tomar UNA foto de la huellita en circón transparente y
   teñirla con los colores que ella pida.

## Decisión

La tercera, con dos precisiones que son el diseño entero.

**Se tiñe, no se pinta.** Un circón no es un círculo de color: es un montón de
facetas con reflejos blancos y sombras. Lo que se cambia es el **tono** y la
**saturación**; el brillo se respeta tal cual estaba. Y la saturación baja
donde la foto es casi blanca —los destellos— porque un destello es luz, no
color. Sin esa curva, la piedra pierde el chispazo y queda un sticker.

**Las máscaras se calculan una vez.** Las cinco piedras están siempre en el
mismo sitio de la misma foto, así que dónde está cada una vive en un PNG de
5,6 KB generado offline. En caliente solo queda teñir: cuatro operaciones de
numpy. Detectar los contornos en cada mensaje habría sido resolver otra vez un
problema ya resuelto, mientras la clienta espera, y con cuarenta megas de
dependencia.

El nombre del archivo sale de los colores (`vista_<hash>`), así que la misma
combinación no se dibuja dos veces nunca.

Encima va la otra mitad: **el bot propone**. Tres combinaciones con nombre —la
elegante, la clásica, la dulce— cada una con su foto, y se puede contestar «la
segunda» o «la elegante». Cada propuesta termina devolviéndole la decisión:

> Proponer sí. Decidir por ella, nunca.

Una sugerencia que suena a decisión tomada se lleva puesto lo que la clienta
quería y encima la deja sin ganas de corregir. Si la propuesta se equivoca
cuesta un mensaje; si se le impone, cuesta la clienta.

## Consecuencias

- **Hay un color hexadecimal por circón** (`HEX_COLOR`), en un solo sitio y
  editable. Si un color no se parece al de verdad, se cambia el número y
  cambian todas las previsualizaciones a la vez.
- **La foto base es parte del producto.** Si un día cambian las piedras, hay
  que rehacerla y regenerar las máscaras. Está anotado en el módulo.
- **Puede no existir.** Sin foto base el bot no dibuja y la conversación es
  idéntica, solo que sin fotos. Es un regalo, no un requisito.
- **La previsualización solo sale cuando cambia un color** o en el resumen
  final. Mandarla en cada mensaje la convierte en ruido.
- Falta medir si convierte. La forma honesta es contar cuántas conversaciones
  que ven una previsualización llegan al abono, contra las que no.
