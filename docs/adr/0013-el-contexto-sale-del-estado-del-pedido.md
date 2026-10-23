# 0013 — El contexto sale del estado del pedido, y el modelo entra por motivo

**Estado:** Aceptada · 2026-09-14
**Relacionada con:** [0006](0006-la-expectativa-entra-en-la-interpretacion.md), [0011](0011-el-pago-lo-confirma-una-persona.md)

## Contexto

Probando con el número de Meta, el pedido `PED-2026-4826` se despachó y cinco
minutos después «¿me puedes montar cómo quedaría uno azul?» le **cambió los
colores al pedido despachado**; «comencemos de 0» le volvió a mostrar ese
pedido; «¿cuántos pedidos he hecho?» dijo «te queda por pagar $200.000» de un
anillo pagado. En la base de datos de pruebas había procesos de compra y pagos
reportados apuntando a pedidos que ya no existían o ya estaban cerrados.

La causa no era el modelo: el contexto de un turno salía de la memoria de la
conversación (procesos que viven 12 días, foco, listas), no del estado real de
los pedidos. Lo cerrado seguía «abierto» para el chat, y lo activo se olvidaba
si la clienta tardaba más de 12 días en volver.

Además, el modelo básico se llamaba en casi todos los turnos aunque una regla
fuera a pisar su respuesta después, y el potente solo entraba cuando no se
entendía nada.

## Opciones

1. **Meter el historial y los pedidos en el prompt.** Ya descartada en 0006:
   cara, crece, y convierte un dato exacto en algo que el modelo deduce.
2. **Embeddings / vector DB para la memoria.** Una clienta tiene 1-5 pedidos:
   se filtran por mes, color, grabado o código con un `for`. Un índice vectorial
   acertaría menos en fechas y agrega un servicio.
3. **Reconciliar el contexto con la base de datos en cada turno** y separar las
   memorias; buscar el historial solo cuando se pide; elegir la capa de modelo
   por un motivo auditable.

## Decisión

La 3.

- **Context Resolver** (`Mundo.resolver_contexto` + `domain/operativo.py`): lee
  los pedidos ACTIVOS, archiva del contexto todo lo que apunte a un pedido
  CERRADO y no deja caducar lo de un pedido activo. El resultado viaja como
  `contexto.operativo` (no se persiste).
- **Historial selectivo** (`domain/historial.py`, acción `CONSULTAR_HISTORIAL`):
  solo lee, por SQL + filtros estructurados. El modelo potente solo desempata
  cuando hay varios candidatos Y una descripción que no está en los campos.
- **Cambios validados por estado** (`domain/cambios.py`): el chat solo escribe
  en un pedido existente si su estado lo permite; si no, anota y pasa a una
  persona. No es política comercial nueva: es impedir que el bot la salte.
- **Routing por motivo** (`Interprete`): reglas decisivas antes del modelo;
  Haiku con una línea de estado sin datos personales; Sonnet 5 solo por
  `sin_entender`, `confianza_baja`, `accion_sensible` o `foto_ambigua`.
- **Registro de decisiones** (`domain/decisiones.py`, tabla `decisiones`,
  `vb metricas`): capa, motivo, contexto, historial, confianza, costo, latencia.
  Sin textos ni teléfonos.

## Consecuencias

- Un pedido cerrado no puede recibir datos, pagos ni cambios desde el chat, y
  «ya te mandé la foto» se interpreta contra el pedido vivo.
- El pedido es la verdad: si el proceso guardado tiene menos datos, se rellena
  desde el pedido.
- Medido en la prueba E2E local (17 turnos): 64,7 % sin IA, 23,5 % Haiku,
  11,8 % Sonnet 5, USD 0,0032 en total.
- La primera llamada tras cambiar el esquema tarda >8 s: el servidor calienta
  los modelos al arrancar.
- Riesgo aceptado: con varios pedidos activos, un cambio sin referencia no se
  aplica solo; va a una persona.
