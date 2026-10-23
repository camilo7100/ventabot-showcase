# 09 · Glosario

Las palabras que se usan en el código y en estos documentos, en español claro.

## Del negocio

| Palabra | Qué es |
|---|---|
| **Huellita** | La huella de una mascota en el anillo. Hay anillos de 1, 2 y 3, y son tres productos distintos |
| **Circón** | La piedra. Cada huellita lleva color de corazón y color de dedos |
| **Grabado** | Los nombres por dentro del aro. Hasta 5 |
| **Talla** | La del mandril. Si no la sabe, se saca de una foto suya con una regla |
| **Abono** | Lo que se paga para empezar a fabricar ($60.000) |
| **Saldo** | Lo que falta, y se paga cuando ve las fotos del anillo terminado |
| **Flete** | El costo del envío, según la ciudad (`data/fletes.csv`) |
| **Punto de recogida** | Donde se puede recoger en vez de enviar, en Floridablanca |
| **Prototipo** | El render de cómo le va a quedar, que el bot manda solo |
| **Anuncio CTWA** | «Click to WhatsApp»: el anuncio de Instagram o Facebook con el botón que abre el chat |
| **Primer / último anuncio** | El anuncio que trajo a la clienta la primera vez (no cambia) y el último que tocó. La venta se le cuenta al último, si fue hace menos de 28 días |
| **Costo por venta** | Lo que se gastó en un anuncio dividido entre las ventas que trajo. Meta da el gasto; el Excel de ventas, las ventas |

## Del sistema

| Palabra | Qué es |
|---|---|
| **Borrador** | El pedido a medio armar mientras se habla. Vive en la conversación, no en la tabla de pedidos |
| **Jugada** | Lo que el modelo propone en un turno: qué entendió, qué cambia y qué hacer. Python la valida antes de ejecutarla |
| **Turno** | Un intercambio: lo que ella escribió y lo que se le contestó |
| **Ráfaga** | Varios mensajes seguidos de la clienta que se contestan de una sola vez |
| **Outbox** | La cola de salida. Nada se manda directo: se encola y un trabajador lo saca |
| **Transición** | Pasar un pedido de un estado a otro. Solo las de la tabla existen |
| **Etapa** | La etiqueta de Chatwoot que dice dónde va la venta (`05-en-taller`…) |
| **Alerta** | La etiqueta que dice que algo hay que mirar (`pago-por-verificar`…) |
| **Acción** | La etiqueta `hacer-…` con la que Lía le ordena algo al bot |
| **Eco** | El mensaje del bot que Chatwoot le devuelve por webhook. Se reconoce por la firma y se ignora |
| **Escalar** | Pasar el turno del modelo básico al potente, o llamar a una persona |
| **Puerto** | La interfaz que el dominio conoce; el adaptador es quien habla con el mundo |
| **Reconciliador** | Lo que compara los pedidos con el ERP y arregla lo que falte |
| **Traza** | El registro de un turno en LangSmith |
| **Idempotente** | Que hacerlo dos veces es igual que hacerlo una. Las acciones desde Chatwoot lo son |
| **Referral / Referido** | Lo que Meta manda en el primer mensaje de quien llegó por un anuncio. En el código, `Referido` (`app/domain/anuncios.py`) |
| **ctwa_clid** | El id del clic en el anuncio. Sirve para devolverle a Meta qué clic terminó en compra |

## De las herramientas

| Palabra | Qué es |
|---|---|
| **ngrok** | El túnel: le da al PC una dirección https pública |
| **Chatwoot** | El CRM donde trabaja Lía |
| **Sidekiq** | La parte de Chatwoot que manda los webhooks |
| **SSRF** | El ataque del que Chatwoot 4.x se protege no llamando a direcciones privadas. Aquí hay que permitirlo a propósito |
| **Agente bot** | El usuario de Chatwoot con el que firma VentaBot |
| **LangSmith** | Donde queda grabado cada turno para poder auditarlo |
| **Groq / Whisper** | Quien transcribe las notas de voz |
| **ruff / mypy / import-linter** | Estilo, tipos y arquitectura |
| **ADR** | «Registro de decisión»: por qué se decidió algo, con lo que se descartó (`docs/adr/`) |
| **vb** | Los atajos de Windows (`vb diagnostico`, `vb ensayo`…). En Linux, el `Makefile` |
