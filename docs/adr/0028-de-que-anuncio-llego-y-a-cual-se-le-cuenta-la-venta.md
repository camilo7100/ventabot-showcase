# 0028 — De qué anuncio llegó la clienta, y a cuál se le cuenta la venta

**Estado:** Aceptada · 30/09/2026
**Relacionada con:** [0015](0015-la-base-de-ventas-y-su-excel.md) (el Excel de ventas)

## Contexto

Marketing (`Proyectos\marketing-lia`) paga anuncios «Click to WhatsApp» en
Instagram y Facebook para los anillos de huellitas. Meta le dice cuánto costó
cada **conversación**, pero no cuál terminó en un anillo vendido: eso solo lo
sabe VentaBot. Sin ese cruce, el anuncio que trae muchas charlas y ninguna
venta parece el mejor, y se le sigue metiendo plata.

Meta ya manda el dato: el primer mensaje después de tocar el anuncio trae
`messages[].referral` (`source_id` = id del anuncio, `source_url`,
`source_type`, `headline`, `body`, `media_type`, `ctwa_clid`). Los mensajes
siguientes no lo traen. Hasta hoy `app/` no lo leía: el dato llegaba, quedaba
crudo en `messages.payload` y no se usaba.

## Opciones

1. **Que Lía o Camilo llenen la columna «Fuente»** del Excel a mano. Ya
   existe y casi nunca se llena; y a mano no se puede saber el id del anuncio.
2. **Sacarlo después del `payload` crudo** guardado en `messages`. Funciona
   hoy, pero ata el reporte al formato de Meta y a una tabla que se borra con
   `vb reiniciar`; y el pedido no sabría de dónde vino.
3. **Leerlo en el adaptador, guardarlo en la clienta y copiarlo al pedido
   cuando nace.**

## Decisión

La 3.

- **Entrada**: `referido_de()` (adaptador de WhatsApp) traduce `referral` a
  `Referido` (`app/domain/anuncios.py`, dominio puro, nombres nuestros). Sin
  `source_id` no cuenta: no habría con qué cruzarlo. Las URL de la imagen o el
  video no se guardan: caducan.
- **Clienta**: `primer_anuncio` (el que la trajo; no cambia nunca) y
  `ultimo_anuncio` (cada anuncio nuevo lo reemplaza). Se anota en
  `Container._atender`, antes de mirar si la atiende una persona: la venta se
  le cuenta al anuncio la cierre quien la cierre. En una ráfaga se miran las
  partes, porque se funde sobre el último mensaje y el anuncio viene en el
  primero. Un fallo aquí se registra y el turno sigue.
- **Pedido**: al nacer (`Mundo.crear_pedido`, el único sitio donde nace) se
  copia el **último** anuncio si fue hace menos de **28 días**
  (`VENTANA_DE_ATRIBUCION_DIAS`). Último y no primero porque es el criterio de
  Meta (último clic) y así los números se pueden comparar. 28 días porque es
  la ventana de clic más larga que ofrece Meta: ninguna venta que Meta
  atribuiría queda por fuera, y una clienta que vuelve en julio por un anuncio
  de enero no infla ese anuncio. Se copia y no se recalcula: tocar otro
  anuncio después no mueve un pedido que ya existía.
- **Excel de ventas** (columnas del sistema, ADR 0015): Anuncio (id), Anuncio
  (titular), Días desde el anuncio (para filtrar a 7, la ventana por defecto de
  Meta) y Primer anuncio. El `ctwa_clid` no va al Excel: no se lee, se le
  devuelve a Meta.
- **Sin migración**: clienta y pedido viven como JSON (`payload`); los campos
  nuevos son opcionales y lo viejo se lee igual.
- **Guardar la clienta por otro motivo no borra los toques**
  (`toques_que_se_conservan`, en los repositorios SQLite y en memoria): el
  motor viejo la guarda armada de cero.

## Lo que queda por fuera, a propósito

- **Devolverle la compra a Meta** (Conversions API for Business Messaging con
  el `ctwa_clid`) para que optimice por compradoras y no por charlas: es otra
  decisión, con credenciales y un dataset nuevos. Está en el plan
  . Lo de hoy deja el
  `ctwa_clid` guardado en el pedido para cuando se haga.
- **El ERP de Google Sheets** y las métricas del panel no muestran el anuncio
  todavía: la pregunta de marketing se contesta con el Excel.
- **Instagram Direct** tiene su propio `referral`; ese canal aún no está
  (Fase 5).

## Consecuencias

- Marketing saca el costo por venta de cada anuncio: gasto en Meta ÷ filas del
  Excel con ese Anuncio y «¿Venta?» = SÍ.
- Los pedidos de antes de hoy no tienen anuncio (no se reconstruye del
  `payload` viejo).
- Si Meta cambia el formato de `referral`, se toca un solo archivo (el
  adaptador); las pruebas usan el ejemplo de su documentación.
