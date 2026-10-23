# 08 · El ERP (HUELLAS_ERP_v1)

El ERP de Lía es una hoja de Google Sheets con 23 pestañas: la primera la
escribe el bot para decir dónde está (ver abajo), y las demás son tres capas:

- **CAPTURA** — lo que alguien escribe: `Ventas`, `Pagos`, `Produccion`…
- **CATÁLOGOS** — productos, insumos, recetas (BOM).
- **PROCESAMIENTO** — `Inventario`, `Mensual`, `Dashboard`: todo con fórmulas.

**El bot escribe solo en la capa de captura.** No toca una fórmula, un catálogo
ni el tablero, y usa los mismos nombres de las listas desplegables del ERP para
que las validaciones no marquen «REVISAR».

## Qué se llena solo, y cuándo

| Hoja | Cuándo | Qué queda |
|---|---|---|
| `Ventas` | Cuando el **abono queda verificado** | Una fila por pedido: producto, celular, canal, ciudad, talla, colores, grabado, cantidad, precio, abono, medio de pago y estado |
| `Pagos` | Cuando el **saldo queda verificado** | El saldo (el abono ya va en Ventas) |
| `Produccion` | Cuando el **anillo queda listo** | Un lote de 1, para que el inventario descuente plata e insumos según la receta |
| `Publicidad` | Cuando se **sube la carpeta de marketing** (o «Actualizar del ERP» en el panel) | Una fila por campaña y mes: fechas, canal Instagram, campaña, inversión y conversaciones (reales, de Ads Manager) |
| `Rank_Ciudades` | Igual que Publicidad (la hoja es del bot) | Fórmulas sobre Ventas: unidades e ingresos por ciudad, y Bogotá·Medellín·Cali contra el resto |

**Antes del abono no hay venta**: es un prospecto. El ERP no se ensucia con
conversaciones que no llegaron a nada.

El **estado** de la fila de Ventas se mueve con el pedido: si el pedido avanza,
la fila se actualiza; no se escribe una fila nueva.

## La pestaña CENTRO DE MANDO: dónde está el bot

La dirección del bot cambia con el túnel, con la máquina y el día que viva en un
servidor. El ERP no: es la misma hoja siempre y se abre desde cualquier
teléfono. Por eso el bot escribe ahí, **en la primera pestaña**, dónde está y
cómo abrir cada cosa: al arrancar y **cada 10 minutos**, con la misma vuelta del
reconciliador.

- **«Visto vivo»**: la hora de la última vuelta. Si tiene más de 15 minutos, el
  bot está apagado. En un servidor sin pantalla es la forma de saberlo.
- Dónde corre (la máquina y la carpeta), la dirección pública y los enlaces al
  centro de mando, el taller, las conversaciones, Chatwoot, las métricas y el
  registro.
- **La llave del panel sí va** (es la que abre esos enlaces, y quien ve el ERP
  ya ve los mismos datos). **Las claves de Meta, Claude, Chatwoot y Google no**:
  con ellas se gasta plata y se escribe por WhatsApp a nombre del negocio, y
  Google guarda el historial de cada celda para siempre. La hoja dice en qué
  archivo están. Una prueba falla si alguna se cuela.
- Se crea sola si no existe (y solo entonces la pone la primera: si alguien la
  movió, se respeta). Se escribe siempre del mismo tamaño, para que no queden
  filas viejas que parezcan actuales. Si falla, las ventas siguen: va aparte y
  después.

Vive en `app/infra/centro_de_mando.py` (las filas) y
`ErpEnSheets.publicar_accesos()` (escribirlas).

## Cómo se puede auditar

Cada fila lleva una columna extra, **`Pedido_Ref`**, con el código del pedido
(`PED-2026-…`). Con ese código se llega desde el ERP a la conversación en
Chatwoot, al panel y a las trazas de LangSmith — y al revés.

## Cuándo se escribe

Dos momentos, para que nada se pierda:

1. **Al mover un pedido**, en el acto.
2. **Cada 10 minutos**, un reconciliador compara los pedidos con la hoja y
   arregla lo que falte. Si Google estaba caído cuando se movió el pedido, se
   repara solo.

Escribir en el ERP **nunca bloquea una venta**: si falla, el pedido se mueve
igual y el reconciliador lo alcanza después.

## La credencial

Hace falta una **cuenta de servicio** de Google (un JSON que no caduca), no una
credencial OAuth de «app de escritorio» (esas caducan cada 7 días en modo
prueba). El bot rechaza la equivocada y lo dice en claro.

- El archivo vive en `Documents\Luna Joyas\credenciales\erp-google.json`.
- Su correo (`…iam.gserviceaccount.com`) tiene que estar compartido como
  **Editor** en el ERP.

```bash
vb erp                              # revisa la conexión y la estructura
vb erp --sincronizar                # fuerza la reconciliación ahora
vb erp --importar-sabana ARCHIVO    # la sábana real de ventas (no duplica)
vb erp --montar                     # catálogos, Costeo, plata, gastos, Gráficas, Balance, LEEME
vb erp --cuestionario ARCHIVO.xlsx  # el Excel para Lía (preguntas + lo del mes)
vb erp --importar-lia ARCHIVO.xlsx  # lo que Lía llenó → ERP (no duplica) y recalcula
vb erp --vaciar                     # respaldo + borra la captura (para empezar limpio)
```

En el servidor (el PC no corre Python), con el archivo por la entrada:
`ssh servidor-demo 'cd ~/ventabot && sudo docker compose exec -T ventabot python
scripts/erp.py --importar-lia -' < archivo.xlsx`. Cada importación guarda antes un
respaldo completo del ERP en `estado/respaldos/`.

## El marketing en el ERP (01/10)

El ERP ya sabía qué hacer con la publicidad: `Publicidad` alimenta `Mensual`
(utilidad después de pauta, CAC) y el `Dashboard` (ROAS, conversión). Estaba
vacía. Ahora la llena el bot con `datos/meta_campanas_mensual.csv` de la carpeta
de marketing, **cada vez que se sube** (`SUBIR-MARKETING.cmd`) o con el botón
**Actualizar del ERP** del panel de marketing (pestaña Números).

- Las filas del bot llevan **`Origen_Ref`** («MKT 2026-09 · campaña»), una
  columna que agrega al final. Se actualizan y se quitan solas; una fila que
  Camilo escriba a mano (sin esa marca) no se toca nunca.
- **La pauta es REAL** (sale de Ads Manager) aunque las ventas del ERP sigan
  siendo de prueba: por eso `vb erp --vaciar` no la borra, y al «Pasar a real»
  queda bien puesta.
- **Entra desde el primer mes con ventas del ERP** (`Config`, «Primer mes con
  ventas»). Con toda la historia contra un solo mes de ventas de prueba, el
  Dashboard de 2026 salía en −$16,5 millones (01/10). El día que se cargue el
  historial real, los meses anteriores entran solos en la siguiente subida. La
  historia completa sigue en el panel de marketing.
- `Rank_Ciudades` es del bot: se reescribe entera. Usa `UNIQUE` + `SUMIF`, ni
  `QUERY` (con 2.000 filas de fórmulas vacías decide mal el tipo) ni `SUMIFS`
  (dentro de `ARRAYFORMULA` repite el primer valor en todas las ciudades).
  Separa también las ventas **sin ciudad** (recoge o falta el dato).
- Al subir se guarda una **foto del ERP** (`estado/marketing/erp.json`): el costo
  de cada producto, el estado de resultados de los últimos meses, las ciudades y
  lo que Validaciones marca para revisar. El panel de marketing la muestra.
- Nada de esto bloquea nada: si Google falla, la carpeta de marketing sube igual
  y el mensaje lo dice.

Vive en `app/domain/erp_marketing.py` (qué filas) y `app/adapters/erp/marketing.py`
(escribir, la hoja de ciudades y la foto).

## Las ventas reales: la sábana (01/10)

`vb erp --importar-sabana` (`app/domain/sabana.py`, `app/adapters/erp/historial.py`)
pasa «HUELLAS 2026.xlsx» de Camilo a Ventas: **421 ventas de enero a septiembre de
2026 por $90.355.000**, una fila por venta (un anillo de 3 huellitas es UNA fila con
sus 3 colores), referencia `SABANA 2026-01 F14` en `Pedido_Ref`. Los saldos se
asumen cobrados 10 días después (Pagos). Las pruebas del bot quedan fuera: desde
`VENTAS_REALES_DESDE=2026-10-01` el bot suma solo los pedidos de verdad
(`erp.solo_reales`). No cuadra con el resumen que Camilo lleva a mano: septiembre
(48 ventas en el detalle contra 52, −$755.000), en enero falta una cadena de
$200.000 y hay diferencias pequeñas en marzo, mayo, julio y agosto; V0337 tiene un
abono mayor que el total (error de digitación en la sábana).

Un pedido del bot con VARIOS anillos (02/10) es una venta por anillo
(`PED-…-A1`, `-A2`, `erp.por_anillo`), con su parte de la plata. Una cadena
(03/10, R2p) entra como «Cadena», sin talla y con el grabado por lado.


## El costo de una pieza: la hoja Costeo (01–02/10)

`vb erp --montar` arma Costeo (`app/adapters/erp/montaje/costeo.py`): la receta
(BOM) más lo que la receta no ve, capa por capa, para cada pieza, con la plata de
hoy y **mes a mes** (la plata pasó de $13.500/g en enero a $6.500/g en septiembre;
hoja `Precio_Plata`, la anota Camilo o Lía). Cada venta se costea con la plata de
SU mes (`Ventas!T`, con la merma).

| Anillo de 1 huellita (plata de sep.) | $ | Qué es |
|---|---:|---|
| Plata (2,7 g × $6.500) | 17.550 | DATO |
| Piedras: 1 corazón + 4 deditos | 2.700 | estimado / SUPUESTO ($300 c/u) |
| Insumos del taller + empaque | 15.140 | guía vieja (por confirmar) |
| Ayudante | 14.000 | DATO |
| **= costo de receta** (el que usan las fórmulas del ERP) | **49.390** | |
| Merma de plata (8 % se pierde al fundir) | 1.404 | SUPUESTO |
| Equipo del taller ($17,4 M en 10 años ÷ 561 piezas) | 3.102 | DATO (los años: supuesto) |
| Arriendo y servicios del taller | 0 | FALTA (cuestionario T1–T4) |
| Salario de Lía ($2 M/mes, el mínimo) | 42.781 | decisión de Camilo |
| Mamá + tío ($1 M/mes) | 21.390 | SUPUESTO |
| Diligencias | 4.278 | SUPUESTO |
| Colchón 10 % | 12.234 | SUPUESTO |
| **= costo completo** | **134.579** | |

El promedio de lo que se vende hoy es **$137.406** (Config fila 15: lo usa el
marketing) y, con la plata de cada mes, **$147.020** en lo vendido de enero a
septiembre. Enero–septiembre da una **utilidad contable de +$10,68 M** (~$1,19 M al
mes) **pagándole a Lía el mínimo**. Los «~$23 M de taller en 2025» eran el EQUIPO
(Camilo, 02/10: $17,4 M real, en `Activos`, se deprecia en 10 años), no un gasto de
cada año; el arriendo y los servicios del taller todavía no están (cuestionario).
La explicación larga va en el informe de costos (Descargas).

Lo que manda sobre lo de antes: el «costo real $86.000» del 01/10 y
`vb erp --costo-real` ya no existen; el costo sale de Costeo.

## Lo que Lía llena: el cuestionario y lo del mes (02/10)

`vb erp --cuestionario ARCHIVO.xlsx` (`app/domain/cuestionario.py`,
`app/adapters/erp/cuestionario.py`) crea un Excel con:

- **Preguntas** (28): el taller por partes (arriendo, servicios, mantenimiento,
  otros), el salario de Lía, la mamá, el tío,
  el ayudante, la merma, el precio de cada piedra, el empaque, lo que se paga sin
  pensar (taxis, comisiones, contador, celular), los equipos y las ventas. Donde
  no sabe: **NO SÉ** (no cambia nada).
- **Las hojas del mes** (lo que el bot no ve): Compras, Gastos, Plata, Equipos,
  Ventas fuera del bot, Inventario hoy, con listas desplegables.

`vb erp --importar-lia` hace un respaldo, guarda las respuestas en
`Respuestas_Lía`, y lo que trae número reemplaza el supuesto (queda **REAL** y
`--montar` ya no lo pisa): el taller solo si contestó sus cuatro partes; el
salario de Lía nunca baja del mínimo. Lo del mes va a su hoja marcado `LIA …`
(importar dos veces no duplica). Un gasto real de un mes **reemplaza su
estimado de ese mes** (si anota el arriendo de octubre, octubre deja de usar
«taller ÷ 12»: hay que anotar todo lo del taller ese mes). Los equipos reales
apagan el bloque estimado de $30 M. Al final recalcula todo (`--montar`).

## Revisión completa del ERP (02/10)

| Hoja | Estado |
|---|---|
| Ventas, Pagos | La sábana real (ene–sep) + lo que vende el bot desde el 01/10 |
| Produccion | La llena el bot cuando un anillo queda listo |
| Publicidad | La llena el marketing (real) desde el primer mes con ventas |
| Compras, Ajustes | Vacías hasta que Lía llene su Excel (el Balance usa el costo de receta mientras tanto) |
| Gastos | Estimados de Costeo mes a mes; los reales de Lía los reemplazan |
| Precio_Plata | Real (ene–sep 2026, de Camilo) |
| Costeo, Cat_Materiales, BOM | Gramos y plata reales; piedras, empaque e insumos por confirmar (cuestionario) |
| Activos | El equipo real ($17,4 M, 10 máquinas, Camilo 02/10); el bloque estimado de $30 M quedó en NO |
| Mensual, Balance, Gráficas, Dashboard, Validaciones | Fórmulas: se corrigen solas con los datos |
| Respuestas_Lía | Lo que contestó Lía (se crea con la primera importación) |

## Lo que falta (es de Lía y de Camilo, no del código)

- Que **Lía llene el Excel** (`Descargas\Paoaccesorios\Para Lía - datos del
  negocio.xlsx`) y Camilo lo importe. Es lo que convierte los supuestos en datos.
- Cuadrar la sábana con el resumen a mano (septiembre, la cadena de enero, V0337).
- Cada mes: la hoja del mes del Excel (compras, gastos, plata).
