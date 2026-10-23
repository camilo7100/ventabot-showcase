# 0014 — La asesora lee la conversación; Python decide qué pasa

**Estado:** Aceptada · 2026-09-17
**Relacionada con:** [0001](0001-langgraph-fsm-no-agente-libre.md), [0006](0006-la-expectativa-entra-en-la-interpretacion.md), [0011](0011-el-pago-lo-confirma-una-persona.md), [0013](0013-el-contexto-sale-del-estado-del-pedido.md)

## Contexto

Se reprodujeron, mensaje por mensaje, las **siete conversaciones reales** de Lía
(`material\Ejemplo conversaciones`) contra el gestor por etiquetas, con reglas
solas y con Claude. **Ninguna llegó al abono.** Y no por detalles:

- grabó el **nombre de la clienta** («María José Orozco», «John Alexander
  Hernández Torres») y hasta «gato pantera, gata calico» como grabado del aro;
- «morado + lila / negro + plateado» quedó «corazón blanco / dedos lila»;
- bucles: «¿Cuántas huellitas?» ocho veces, la misma pregunta seis veces;
- «No» se leyó como cancelar; «me regalas la guía» como consultar pedido;
  «Hola, ¿cómo vas?» a mitad de venta recibió «¡Con mucho gusto!» o la
  bienvenida entera.

Además el dominio no podía guardar pedidos que Lía sí fabrica: el grabado
prohibía «/», «♡» y símbolos (Lía graba fechas, corazones, alitas, infinitos,
carita de gato) y no existían deditos intercalados.

La causa es de diseño: una clienta real no contesta la pregunta que se le hizo.
Clasificar cada mensaje suelto en (acto, entidad, atributo) y decidir con una
tabla pierde justo eso, y ya eran 13.000 líneas de reglas.

## Opciones

1. **Más reglas.** Cada conversación real destapa varias nuevas; es una carrera
   sin fin y ya no convergía.
2. **Agente libre** con herramientas. Rechazado en 0001 y sigue rechazado: el
   dinero y los estados no pueden depender de lo que el modelo decida llamar.
3. **Jugada estructurada validada.** El modelo lee la conversación reciente y el
   borrador del pedido y devuelve un esquema cerrado: cambios al borrador
   (colores en el `Enum` de 14), acciones de una lista cerrada, mensaje y
   confianza. Python valida y ejecuta todo lo que importa.

## Decisión

La 3 (`app/domain/asesora.py`, `app/conversacion/asesora.py`,
`app/prompts/asesora_v1.txt`), detrás de `CONVERSACION_MOTOR=asesora`.

Lo que sigue siendo de Python, sin excepción:

- **Validar**: cantidad 1-3, colores del muestrario, talla que exista (una
  medida escrita se marca para revisar), grabado sin el nombre de la clienta y
  con máximo 5 nombres.
- **Escribir los números**: ficha de precios, cuentas, resumen y envío los pone
  Python; el mensaje del modelo solo puede nombrar cifras del estado.
- **Vigilar el mensaje** (`vigilar`): fuera montos inventados, cuentas,
  teléfonos, «pago confirmado», redes/enlaces/trayectoria inventados, una talla
  distinta a la guardada. Si afirma algo que el estado desmiente («ya tomé tu
  pedido» sin abono, «ya te pasé las cuentas» sin haberlas mandado), se
  descarta el mensaje entero.
- **Reescribir antes que frase fija** (17/09): si el mensaje miente, queda
  vacío tras vigilarlo, repite casi igual uno de los 3 anteriores
  (`repite_lo_dicho`) o habla de una cantidad que no quedó, se le pide al modelo
  SOLO otro texto (`MensajeReescrito`) con el motivo, lo que dijo la clienta y
  el estado real. La reescritura se vigila igual; si falla, queda la frase fija
  de siempre. Las frases fijas eran lo que más sonaba a bot («Quedo atenta al
  comprobante» cuatro veces seguidas).
- **Pedidos y pagos**: el pedido se crea con `mundo.crear_pedido`; el
  comprobante lo deja en `EN_REVISION_PAGO` (0011); los cambios a un pedido
  existente pasan por `domain.cambios.permiso` (0013).
- **Respaldo**: si la API falla, contesta el gestor por etiquetas.

Modelo: Haiku 4.5 principal; Sonnet 5 solo con confianza BAJA. Solo modelos en
línea: sin clave de Anthropic no se cae a un modelo local (decisión de Camilo,
17/09; `tests/unit/test_sin_ollama.py`).

## Consecuencias

- Medido con `vb repasar` (escenarios en `material\escenarios`, fuera del repo
  por datos personales): **7/7 conversaciones reales** llegan al abono con
  pedido correcto (79/79 comprobaciones) y **10 escenarios sintéticos no vistos**
  (desconfianza, descuento, duelo, queja, insulto, color inexistente, cambio
  de nombre tras pagar) generalizan. ~USD 0,003 por turno, ~3,5 s.
- La conversación deja de ser determinista: la red son los tests sin red de lo
  que Python valida (`tests/unit/test_asesora.py`) y el repaso con modelo real,
  que hay que correr antes de cada cambio de prompt.
- El gestor por etiquetas no se borra: es el respaldo y sus 1.000 tests siguen.
- Cada conversación que salga mal se agrega como escenario, no como regla.
