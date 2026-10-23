# 06 · Los datos y la privacidad

Por aquí pasan nombres, teléfonos, direcciones, fotos de mascotas y
comprobantes de pago de personas reales. Esto dice **qué se guarda, dónde y qué
no sale nunca del PC**.

## Dónde vive cada cosa

| Qué | Dónde | Sale del PC |
|---|---|---|
| Conversaciones, mensajes, pedidos, outbox | `data/ventabot.db` (SQLite) | No |
| Conversaciones (copia para trabajar) | Chatwoot → postgres en Docker | No |
| Fotos que manda la clienta | `data/fotos/` | No |
| Prototipos que genera el bot | `data/renders/` | Se sirven por el túnel mientras se mandan |
| Excel de ventas | `Documents\Luna Joyas\` | No |
| El ERP | Google Sheets (`HUELLAS_ERP_v1`) | **Sí**, es de Lía |
| Trazas de cada turno | LangSmith | **Sí**, proyecto `ventabot` |
| Credenciales | `.env` y `Documents\Luna Joyas\credenciales\` | No |
| Respaldos | `Documents\Respaldos\VentaBot\` | No |

## Lo que se manda afuera, y a quién

| Servicio | Qué recibe |
|---|---|
| Meta / WhatsApp | Los mensajes que se le contestan a la clienta |
| Anthropic (Claude) | El texto de la conversación para entender el turno |
| Groq | El audio de las notas de voz, para transcribirlo |
| Google Sheets | Los datos de la venta: pedido, montos, estado, ciudad |
| LangSmith | El turno completo: lo que entró, lo que decidió y lo que respondió |

**A nadie más.** No hay analítica, ni terceros, ni correo.

## De qué anuncio llegó la clienta

Cuando una clienta toca un anuncio «Click to WhatsApp» de Instagram o Facebook,
el **primer** mensaje que escribe trae el objeto `referral` de Meta. Los
siguientes ya no lo traen: si no se lee ahí, se pierde (ADR 0028). Lo lee
`referido_de()` en `app/adapters/channels/whatsapp.py` y lo convierte en un
`Referido` (`app/domain/anuncios.py`):

| Campo | De Meta | Qué es |
|---|---|---|
| `anuncio_id` | `source_id` | El id del anuncio. La llave para cruzar con el costo en el Administrador de anuncios |
| `tipo` | `source_type` | `ad` (pagado) o `post` (publicación) |
| `url` | `source_url` | El enlace al anuncio |
| `titulo` · `texto` | `headline` · `body` | El titular y el texto del anuncio |
| `medio` | `media_type` | `image` o `video` |
| `ctwa_clid` | `ctwa_clid` | El id del clic, para devolverle a Meta la compra algún día (ver el plan). En anuncios de Estados de WhatsApp Meta no lo manda |
| `cuando` | `timestamp` del mensaje | Cuándo tocó el anuncio |

Las URL de la imagen y del video del anuncio **no se guardan**: caducan.

Dónde queda:

- **En la clienta** (`customers`): `primer_anuncio` (el que la trajo; no cambia
  nunca) y `ultimo_anuncio` (el último que tocó). Guardar la clienta por otro
  motivo no los borra (`anuncios.toques_que_se_conservan`).
- **En el pedido** (`orders`), cuando nace (`Mundo.crear_pedido`): `anuncio` =
  el último anuncio de la clienta, si lo tocó hace menos de
  `VENTANA_DE_ATRIBUCION_DIAS` (28). Se copia y no se recalcula: si después
  toca otro anuncio, ese pedido no se mueve.
- **En el Excel de ventas** (hoja Ventas, columnas grises del sistema):
  **Anuncio** (el id), **Anuncio (titular)**, **Días desde el anuncio** (para
  filtrar a 7 y comparar con la ventana por defecto de Meta) y
  **Primer anuncio**. El `ctwa_clid` no va al Excel.

Con eso marketing saca el **costo por venta de cada anuncio**: el gasto del
anuncio en Meta dividido entre las filas con ese **Anuncio** y «¿Venta?» = SÍ.
Ningún dato del anuncio sale del PC: Meta ya lo tiene.

## Las credenciales

- Viven en `.env` (que está en `.gitignore`) y en
  `Documents\Luna Joyas\credenciales\`.
- **Nunca en el código** y nunca en un commit: una clave que entra al historial
  de Git se queda ahí para siempre, aunque se borre después.
- Las herramientas del proyecto **no las imprimen**. El diagnóstico dice «token
  puesto», y si tiene que mostrar una URL con token, lo tapa (`token=•••`).
- Hay una prueba que falla si `.env` aparece dentro de Git, y el diagnóstico lo
  vuelve a revisar en cada corrida.

## El panel del taller

Muestra nombres, teléfonos y montos, y el servidor se publica por un túnel al
internet abierto. Por eso:

- Sin `?token=` correcto responde 404: no dice ni que existe.
- El token vive en `.env` (`PANEL_TOKEN`) y se genera aleatorio.
- El diagnóstico comprueba en cada corrida que sin token no se entra.

## Lo que NUNCA se sube a ningún lado

- `Documents\GitHub\material\` (escenarios y repasos) tiene **conversaciones reales de
  clientas**. No se versiona ni se sube. Nunca.
- Las fotos de clientas (`data/fotos/`) están fuera de Git.
- El Excel de ventas y los respaldos están fuera del repositorio.

## Respaldos

`vb respaldo` copia la base y el Excel a `Documents\Respaldos\VentaBot\` y deja
las 14 últimas. `vb reiniciar` hace un respaldo **antes** de borrar nada.

El diagnóstico avisa si el último respaldo tiene más de dos días.

## Borrar las charlas de prueba

```bash
vb reiniciar
```

Dice qué va a borrar, pregunta, respalda y borra: los contactos de Chatwoot con
sus conversaciones y, en la base del bot, conversaciones, mensajes, memoria,
outbox, eventos procesados y decisiones. **No toca** el catálogo, los fletes,
las reglas, el Excel, el ERP ni la configuración de Chatwoot. Con `--pedidos`
borra también los pedidos, que hay que pedirlo a propósito porque un pedido es
plata.

## Las pruebas no tocan nada real

`tests/conftest.py` deja cada prueba encerrada: base de datos temporal, Excel
temporal, carpeta de fotos temporal, canal de consola, modelo simulado,
LangSmith apagado y avisos apagados.

Esto no es cosmético: hubo pruebas que escribieron en el Chatwoot de verdad y
que podían disparar avisos al celular. Hoy no pueden.
