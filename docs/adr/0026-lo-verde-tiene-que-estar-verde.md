# 0026 — Lo que se ve verde tiene que estar verde

**Estado:** Aceptada · 20–21/09/2026.

## Contexto

Tres veces en dos días, todo se veía bien por dentro y no lo estaba:

- **Un campo de más en `Jugada` apagó al bot.** La API contestó «Schema is too
  complex» a todas las llamadas. El bot arrancaba, el diagnóstico daba verde y
  las pruebas pasaban —ninguna llama a la API—; cada clienta recibía «Dame un
  momentico». Debajo había otro fallo: un esquema nuevo tarda ~60 s en
  compilarse la primera vez (2 s después), y el calentamiento del arranque usaba
  el tope de las clientas (10 s): se rendía antes y la gramática no se guardaba
  nunca.
- **Las pruebas podían escribir en el ERP de verdad.** Con `sqlite`, el
  contenedor arrancaba el ERP con el ID y la credencial del `.env`. La suite y
  el bot crearon a la vez la pestaña CENTRO DE MANDO y quedó una duplicada.
- **Los repasos también.** El 21/09 corrieron 33, y cada uno escribió en la
  pestaña CENTRO DE MANDO enlaces a `https://ejemplo.local` con la llave real
  del panel, hasta que el bot los corregía a los 10 minutos. Las ventas no se
  tocaron.

## Decisión

- **El diagnóstico prueba el esquema contra la API** con una llamada de verdad
  («el esquema de la asesora lo acepta la API»). Cuesta centavos y deja la
  gramática compilada.
- **El calentamiento no tiene el tope de las clientas**
  (`ESPERA_AL_CALENTAR_S`): nadie está esperando ahí.
- **Ni pruebas ni repasos alcanzan un servicio real**: sin Chatwoot, sin ERP y
  sin avisos (`ENTORNO_DE_PRUEBAS` en `tests/conftest.py`,
  `ENTORNO_DEL_REPASO` en `scripts/repasar.py`). Los repasos usan el modelo real
  y nada más.
- **Las capacidades nuevas del modelo van como acciones**, no como campos
  (ADR 0021): un valor más en un enum casi no pesa en el esquema.

## Consecuencias

- Pruebas: `TestLasPruebasNoTocanElErpDeVerdad` en
  `tests/unit/test_centro_de_mando.py` (una para la suite y otra para los
  repasos, que monta el contenedor con un Google de mentira que siempre abre:
  con una credencial inválida no probaría nada) y `tests/unit/test_diagnostico.py`.
- Regla R16 de `docs/sistema/03-reglas-de-negocio.md`.
- El diagnóstico pasó de 36 a 38 revisiones.
