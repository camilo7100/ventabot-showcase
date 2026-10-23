# 0029 — Recordatorios por días, separar sin talla y la venta a Meta

**Estado:** Aceptada (13/10/2026). Reemplaza el CUÁNDO y el QUÉ de la 0017 (los
dos horarios de 9 a. m. y 5 p. m.); lo de no acosar de la 0017 sigue igual.

## Contexto

Camilo, 13/10, con los datos que trajo marketing de la base en vivo:

- 48 recordatorios enviados y 5 respuestas (~10 %). Eran preguntas de trámite
  («¿Ya sabes de cuántas huellitas?», «¿Pudiste medir tu anillo?»), sin foto ni
  una razón para volver.
- 47 de 70 que llegaron por anuncio mandaron un solo mensaje y recibieron cero.
- El freno real es el precio y la TALLA: de 70 personas, 3 escogieron colores,
  2 dieron la talla y ninguna pidió.

Lo que pidió (y aprobó punto por punto el 13/10): recordatorios personalizados
por días para quien pasó de cierto punto; separar el anillo con el abono y
mandar la talla después; avisarle a Meta cada venta; y probar otra primera
respuesta. El mismo día, que sin anillos se mida el dedo con papel o hilo (la
joyería era un cuello de botella).

## Decisión

1. **Recordatorios por días** (`app/domain/recordatorios_por_dias.py`,
   `RECORDATORIOS_MODO: dias`). Segmentos: S1 vio la presentación y no volvió
   (días 1 y 4); S2 se frenó en la talla o la cantidad (1, 3 y 7); S3 ya escogió
   algo (1, 3 y 6); S4 pedido sin abono (1, 3 y 7). El día 1 dentro de sus 24 h,
   en texto libre; los otros, con plantilla. Siempre de 10 a. m. a 7 p. m., con
   su nombre y el de su peludito, una FOTO (su anillo dibujado o uno real con el
   nombre grabado) y tres botones: «💍 Quiero separarlo» · «Tengo una duda» ·
   «Más adelante». Máximo 3 por silencio; si pidió tiempo, el primero y el último.
   Lo de no acosar de la 0017 se mantiene: nunca si dijo que no o mostró cualquier
   desinterés (y la IA lee la charla antes de cada uno), nunca si la atiende una
   persona, nunca a un número de prueba, solo antes del abono.
2. **Cuatro plantillas** (Camilo aprobó consolidar las siete del diseño):
   `anillo_con_abono`, `asi_quedaria`, `cupo_en_el_taller`, `ultimo_recordatorio`
   («Guardé el diseño… cuando quieras retomarlo, aquí estoy»). Y una quinta guardada
   para su temporada, `ultimo_navidad` («el último día para pedirlo para Navidad es
   el 8 de diciembre»): Camilo, 14/10, «no desde ya, es muy específico; por ahí en
   noviembre». Va sola del 1 de noviembre al 8 de diciembre (`TEMPORADA_DE_NAVIDAD`). Se crean con
   `vb recordatorios --plantillas --crear` (cabecera con foto). Hasta que estén
   aprobadas, `RECORDATORIO_CON_PLANTILLA: "false"`: solo sale el del día 1.
3. **Separar sin talla** (`Borrador.talla_despues`): si toca «💍 Quiero separarlo»,
   lo dice, o acepta el ofrecimiento (que sale UNA vez cuando solo falta la talla y
   no la tiene a mano), el abono no espera la talla. El resumen dice «Talla: me la
   mandas después 📏». El pedido nace sin talla y Lía no lo funde hasta tenerla (R7:
   el panel no lo deja pasar al taller).
4. **La venta a Meta** (`app/adapters/conversiones_meta.py`): al confirmar un abono,
   un `Purchase` al dataset de mensajes del bot (`META_DATASET_MENSAJES`), unido al
   clic del anuncio (`ctwa_clid` del primer mensaje). `event_id` = código del pedido
   (no se duplica la de PED-2026-3277, que marketing mandó a mano). Sin clic de
   anuncio o con número de prueba, nada. Nunca frena el movimiento del pedido.
5. **La prueba de la primera respuesta** (`APERTURA_PELUDITO`): a «Quiero más
   información» se le abre con la foto del anillo grabado y «¿Cómo se llama tu
   peludito? 🐾»; la presentación con precios va en su segundo mensaje. A quien
   pregunta el precio, la de siempre. Se mide con `vb recordatorios --medir`
   (cuántas escriben un segundo mensaje, con una apertura y con la otra).
6. **Sin anillos, el dedo con papel o hilo** y el video `medir_talla_dedo` (antes,
   la joyería; Lía, 05/10). Lía confirma la talla con los centímetros.

## Consecuencias

- Cuesta: cada plantilla es un mensaje de marketing de Meta (tarifa de Colombia).
  Se mide por segmento y por número de recordatorio para quitar lo que no venda.
- El modo de los dos horarios sigue en el código (`RECORDATORIOS_MODO: horarios`)
  por si hay que volver.
- Un pedido puede pagarse sin talla: Lía tiene que pedírsela antes de fundir; el
  resumen y el panel lo dicen.
- Frases que solo pueden ser verdad si Camilo las sostiene: «cupo en el taller esta
  semana», «muchas clientas nos escriben…», «hasta el 8 de diciembre para Navidad»
  (Camilo las confirmó el 13/10; la de Navidad, solo en su temporada).
