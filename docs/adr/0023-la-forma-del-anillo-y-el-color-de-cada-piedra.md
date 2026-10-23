# 0023 — La forma del anillo no se escoge; el color de cada piedra, sí

**Estado:** Aceptada · 20/09/2026 · Camilo, con fotos del anillo real.

## Contexto

Probando desde el celular salieron cuatro problemas del mismo lado —el del
diseño que la clienta ve y que el taller fabrica—:

- **Las huellitas del dibujo miraban todas igual.** En el anillo de verdad no:
  en el de dos, una mira hacia arriba y la otra hacia abajo; en el de tres, la
  del centro va al revés.
- **Los deditos de colores se perdían.** La conversación ya entendía
  «negro-blanco-negro-blanco» (`dedos_alternos`), pero al pasar al pedido se
  guardaba solo el primer color y los otros tres iban a una nota suelta. El
  dibujo enseñaba los cuatro iguales y el taller habría recibido un anillo
  unicolor.
- **Al comparar colores se veía una patita suelta**, aunque ella estuviera
  comprando el de tres.
- **«No ya no me gustó» no borraba nada.** El borrador siguió en fucsia y la
  conversación pasó al grabado: un anillo del color que ella rechazó. No había
  forma de desescoger: en los cambios, un vacío significa «esto no cambia».

## Decisión

- **La forma es fija, por diseño**: la segunda huellita va al revés (`VUELTAS`
  en `app/adapters/render/huellita.py`). Si piden otra dirección, el bot dice
  con cariño que no es posible.
- **Cada piedra lleva su color**: el corazón y cada uno de los cuatro deditos.
  `Huellita.dedos_alternos` llega al pedido, al dibujo y al resumen.
- **La foto trae el anillo entero** (`_el_anillo_entero`): si está mirando el
  color de una huellita, las demás se completan con lo que ya escogió.
- **Desescoger es una acción, `QUITAR_COLORES`**, no un campo nuevo: un campo
  más en el esquema del modelo lo rompe (ADR 0021). Con los colores borrados,
  `falta_del_anillo()` los vuelve a pedir y la conversación no puede seguir sin
  ellos.
- **El resumen, con el formato que escribió Camilo**: renglón en blanco bajo el
  título y el punto de color delante del corazón (`EMOJI_COLOR`). Solo en el
  corazón: con cuatro emojis más, los deditos alternos no se leerían.

## Consecuencias

- Pruebas: `tests/unit/test_huellitas_del_anillo.py` y
  `TestCuandoDiceQueYaNoLeGusta` en `test_conversaciones_reales.py`.
- Reglas R2e, R2i y R2j de `docs/sistema/03-reglas-de-negocio.md`.
