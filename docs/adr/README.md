# ADR — Architecture Decision Records

Un archivo por decisión: **contexto, opciones, decisión, consecuencias**.
Tres párrafos cada uno, no más.

Dentro de seis meses no vas a recordar por qué elegiste `arq` sobre Celery, y
ese "por qué" es lo que te permite **revisar la decisión con criterio** en vez
de por moda. Es el hábito de ingeniería con mejor relación esfuerzo/beneficio
que existe.

Cuando cambies una decisión, **no edites el ADR viejo**: escribe uno nuevo que
lo reemplace y marca el anterior como `Reemplazado por 000N`. El historial es
el valor.

| # | Decisión | Estado |
|---|---|---|
| [0001](0001-langgraph-fsm-no-agente-libre.md) | LangGraph como FSM explícita, no agente libre | Aceptada |
| [0002](0002-postgres-fuente-de-verdad.md) | Postgres es la fuente de verdad; Sheets es una vista | Aceptada |
| [0003](0003-cobro-por-link-no-por-comprobante.md) | El cobro se confirma por webhook, nunca por imagen | Reemplazada por 0011 |
| [0004](0004-cola-de-tareas-arq.md) | arq como cola de tareas | Aceptada |
| [0005](0005-llm-local-detras-de-un-puerto.md) | Ollama local detrás de `LLMPort` | Aceptada |
| [0006](0006-la-expectativa-entra-en-la-interpretacion.md) | La expectativa entra en la interpretación | Aceptada |
| [0007](0007-un-modelo-aparte-para-mirar-fotos.md) | Un modelo aparte para mirar las fotos | Aceptada |
| [0008](0008-ensenarle-como-le-va-a-quedar.md) | Enseñarle cómo le va a quedar (previsualización y sugerencias) | Aceptada |
| [0009](0009-chatwoot-como-espejo.md) | Chatwoot como espejo, no como canal | Aceptada |
| [0010](0010-el-flete-vive-en-un-csv.md) | El flete vive en un CSV, no en el código | Aceptada |
| [0011](0011-el-pago-lo-confirma-una-persona.md) | El pago lo confirma una persona, no un webhook | Aceptada |
| [0012](0012-una-respuesta-por-rafaga.md) | Una respuesta por ráfaga, no una por mensaje | Aceptada (apagada por defecto) |
| [0013](0013-el-contexto-sale-del-estado-del-pedido.md) | El contexto sale del estado del pedido, y el modelo entra por motivo | Aceptada |
| [0014](0014-la-asesora-lee-la-conversacion.md) | La asesora lee la conversación; Python decide qué pasa | Aceptada |
| [0015](0015-la-base-de-ventas-y-su-excel.md) | La base de ventas es SQLite; el Excel es una vista con columnas de Camilo | Aceptada |
| [0016](0016-cuando-contesta-una-persona-el-bot-calla.md) | Cuando contesta una persona, el bot calla 12 h en esa conversación | Aceptada |
| [0017](0017-recordar-antes-del-abono-sin-acosar.md) | Recordar antes del abono, sin acosar (2 en la ventana + 1 con plantilla a los 3 días) | Aceptada (rehecha el 04/10) |
| [0018](0018-el-pedido-al-cien-por-ciento-y-chatwoot-como-centro.md) | El pedido al 100 % antes del abono; Chatwoot como centro de control (etapas, alertas, acciones) | Aceptada |
| [0019](0019-la-direccion-despues-del-abono-y-el-crm-que-si-contesta.md) | La dirección va después del abono, se puede recoger, y Chatwoot vuelve a contestarle al bot | Orden de preguntas reemplazado por 0020 |
| [0020](0020-la-talla-de-segundas-y-el-envio-al-final.md) | La talla de segundas; los datos de envío con las fotos del anillo terminado; sin fotos no se cobra | Aceptada |
| [0021](0021-el-envio-por-adelantado-va-con-el-saldo.md) | El envío por adelantado va con el saldo (nunca con el abono), pedido como acción: un campo más rompe el esquema | Aceptada |
| [0022](0022-hay-pago-solo-con-comprobante-o-ya-pague-explicito.md) | Hay pago solo con comprobante o «ya pagué» explícito; «recibido» solo con pago; si pide la cuenta, se le manda | Aceptada |
| [0023](0023-la-forma-del-anillo-y-el-color-de-cada-piedra.md) | La forma del anillo no se escoge; el color de cada piedra, sí (y «ya no me gustó» borra el color) | Aceptada |
| [0024](0024-siempre-una-pregunta-y-el-nombre-se-propone.md) | Siempre una pregunta, una a la vez; el nombre se propone; primero el resumen y después el abono | Aceptada (cierre del comprobante precisado por 0022) |
| [0025](0025-el-centro-de-mando-y-la-pestana-del-erp.md) | El centro de mando en una página, y la primera pestaña del ERP dice dónde está el bot | Aceptada |
| [0026](0026-lo-verde-tiene-que-estar-verde.md) | Lo que se ve verde tiene que estar verde: el diagnóstico prueba el esquema, y ni pruebas ni repasos tocan servicios reales | Aceptada |
| [0027](0027-gpt-primero-claude-de-respaldo.md) | GPT primero (luna), Claude de respaldo, las fotos igual; si ninguno contesta, el turno queda pendiente y se reintenta solo | Aceptada |
| [0028](0028-de-que-anuncio-llego-y-a-cual-se-le-cuenta-la-venta.md) | De qué anuncio llegó la clienta (primer y último toque) y a cuál se le cuenta la venta: el último, si fue hace menos de 28 días | Aceptada |
| [0029](0029-recordatorios-por-dias-separar-sin-talla-y-la-venta-a-meta.md) | Recordatorios por días con foto y botones; separar sin talla; la venta a Meta; la apertura del peludito; sin anillos, el dedo con papel | Aceptada (reemplaza el cuándo de 0017) |
| [0031](0031-banco-de-plantillas-por-situacion.md) | El banco de plantillas por situación: el selector «primera aprobada» (apagado hasta que Camilo prenda un grupo), los límites de Meta (250 sin verificar, 100 por hora) y la limpieza de sobrantes | Aceptada |
