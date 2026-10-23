# 0010 — El flete vive en un CSV, no en el código

**Estado:** Aceptada · 2026-09
**Contexto previo:** [0002](0002-postgres-fuente-de-verdad.md)

## Contexto

`data/fletes.csv` estaba en el repositorio desde la Fase 0, con 29 ciudades y
sus tarifas. **Nadie lo leía.** El adaptador `CsvFletes` existía, funcionaba y
no lo construía ningún módulo; el número que de verdad se cobraba —$16.500—
estaba escrito a mano en tres sitios del código.

Eso costaba plata en las dos direcciones. A una clienta de Bogotá se le
cobraban $16.500 por un envío de $8.000. A una de Leticia se le cobraban
$16.500 por uno de $45.000, y la diferencia la ponía Lía de su bolsillo.

Y había un defecto de conversación encima: «¿cuánto vale el envío?» disparaba
la regla de «pregunta el precio» y el bot contestaba con la lista de precios
del anillo. La palabra «envío» estaba en la frase y nadie la miraba.

## Opciones

1. **Cambiar la constante.** Ajustar $16.500 y seguir. Vuelve a estar mal el
   día que Coordinadora suba tarifas, y sigue cobrándole igual a Bogotá que a
   Leticia.
2. **Una tabla en la base de datos,** con pantalla en el panel para editarla.
   Es lo correcto a los dos años; hoy son tres pantallas y una migración para
   un archivo que se cambia cuatro veces al año.
3. **Leer el CSV que ya existe** y meterlo detrás de un puerto.

## Decisión

La tercera. `data/fletes.csv` es **la única fuente** del precio del envío, y
se edita con Excel o con el Bloc de notas.

Tres precisiones que son el diseño:

**El valor por defecto también vive en el archivo,** en una fila `(DEFECTO)`.
Es el caso más común de todos —la clienta pregunta el envío antes de decir de
dónde es— y dejarlo en una constante habría significado que justo el número
que más se dice sí hay que programarlo para cambiarlo. Son $15.000.

**El flete se congela en el pedido.** `Order.envio_contraentrega_cop` guarda
lo que se le cotizó el día que compró. Un pedido de marzo tiene que seguir
diciendo lo de marzo aunque la tabla ya diga otra cosa: recalcularlo al
mostrarlo es cambiarle el precio a alguien que ya abonó.

**La ciudad la lee Python, no el modelo.** `leer_ciudad` saca el nombre de
«soy de Bogotá» con una expresión regular y sin lista de ciudades —Colombia
tiene 1.100 municipios y cualquier lista nace incompleta—. Quien decide si esa
ciudad existe es el CSV. Un modelo de 3B que *deduce* de dónde es alguien
cotiza mal un envío real, así que si la frase no nombra una ciudad, no hay
ciudad.

## Consecuencias

Cambiar un flete pasó de ser un cambio de código con tests y despliegue a ser
`abrir el archivo, cambiar el número, guardar, reiniciar`. `vb fletes --revisar`
avisa de los errores de dedo (un cero de más o de menos) antes de que cobren
mal.

Que falte el archivo **no frena una venta**: `Mundo.envio_a` cae al valor
nacional de último recurso y la conversación es idéntica salvo por la cifra.

Lo que queda pendiente: la tabla es de Coordinadora y está puesta a ojo. Los
valores reales los tiene Camilo en su cuenta de la transportadora, y son los
que hay que poner antes de vender de verdad.
