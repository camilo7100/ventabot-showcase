# 0027 — GPT primero, Claude de respaldo, y ninguno deja a la clienta sin respuesta

**Estado:** Aceptada · 29/09/2026. Cierra la D13 del plan («no depender de un
solo proveedor»).

## Contexto

- **El 29/09 a las 9:16 Anthropic devolvió 503.** El bot se rindió en un
  segundo y el «Sí» de una clienta se quedó sin respuesta. Era la tercera vez
  que un problema de un solo proveedor dejaba al bot sin pensar (21/09 sin
  saldo; 20/09 un esquema rechazado, [ADR 0026](0026-lo-verde-tiene-que-estar-verde.md)).
- **VentaBot es micro** (~40 anillos al mes): cada peso de la IA cuenta, pero
  una clienta mal atendida cuesta más que un año de tokens.

## Qué se midió (29/09, base desechable, nada salió a WhatsApp)

La misma conversación de 10 mensajes (precio → talla 1,8 → dos huellitas →
colores → grabado → nombre → Lía confirma la talla → «cuánto se demora a
Medellín»):

| Modelo | Resultado | Tiempo total | Costo |
|---|---|---|---|
| `gpt-6-luna`, esfuerzo `none` (dos veces) | Flujo limpio | ~22 s | US$0,0078 (≈0,002 con la caché bien contada, ver abajo) |
| `gpt-6-luna`, esfuerzo `low` | Dudó con 1,8 y volvió a preguntar | 29 s | US$0,0083 |
| `claude-haiku-4-5` | Siguió pidiendo la talla e inventó «3 a 5 días» | 28,5 s | US$0,0517 |

Para «cuando duda» (una entrada difícil, a propósito): luna `low` 6,9 s y
razonable; `medium` 14,8 s, demasiado lento para una clienta esperando.

Fotos (imágenes públicas del negocio + un comprobante inventado): luna leyó
bien el comprobante de **$60.000**; Haiku lo leyó como **$60.000.000**. En la
regla de la talla y el muestrario, empate.

Respaldo, con una clave mala a propósito: GPT caído → contestó Claude en 7,0 s;
Claude caído → contestó GPT en 5,1 s.

## Decisión

- **GPT primero**: `gpt-6-luna` sin razonar (`none`) para casi todo; cuando
  duda, **la misma luna razonando un poco** (`low`). Un modelo más grande
  (`gpt-6-sol`, 20 veces más caro) no hizo falta en ninguna medición.
- **Claude de respaldo**: Haiku 4.5 y Sonnet 5.5, en el mismo orden de capas.
- **Las fotos siguen el mismo orden** (la misma `CadenaDeModelos`).
- **Si ninguno contesta**, se insiste ~35 s en vueltas (GPT, Claude, GPT…);
  después el turno queda **pendiente** y un reintento cada 30 s lo contesta
  cuando alguno vuelve. No pasa a una persona salvo que Lía la tome.
- **La caché del prompt** (~9.200 tokens fijos: prompt + esquema) dura 24 h
  (`RETENCION_DE_CACHE`, sin costo extra). Medido en producción: 9.180 de 9.214
  tokens salen de caché, a US$0,01 el millón en vez de 0,10. Una llamada de luna
  cuesta ~US$0,0002. El ensayo cobraba lo de caché a precio entero (OpenAI lo
  cuenta dentro de `prompt_tokens`); ya se separa. `prompt_cache_key` no se usa:
  con GPT-6 el enrutamiento es automático.
- **El contexto no se recorta**: lo variable de cada turno (~1.600 tokens: estado
  del pedido y conversación reciente) cuesta ~US$0,00016; quitarle contexto
  ahorraría centavos al mes y costaría ventas.
- **Dónde vive cada cosa**: los modelos y el orden en `docker-compose.yml`
  (son una decisión); las dos claves en el `.env` del servidor y del PC (plan
  B), nunca en GitHub.

## Consecuencias

- Costo de la IA: ~US$0,002 por conversación, unas 25 veces menos que con Haiku de
  principal.
- El diagnóstico muestra «Quién contesta» y prueba el esquema `Jugada` en
  **los dos** proveedores con una llamada de verdad, y «la caché de la IA»
  con los turnos reales de las últimas 24 h (cuánto sale de caché y cuánto costó).
- Cada llamada queda apuntada con su capa (`basico`, `fuerte`, `reescribir`…):
  antes decía «?» y `vb metricas` no distinguía el básico del potente.
- Pruebas: `TestLaConfiguracion`, `TestGPT` y `TestLasCapasQuedanApuntadas` en
  `tests/unit/test_ia_caida.py`; `TestLaCache` en `tests/unit/test_diagnostico.py`.
- Cambiar el orden es una línea (`IA_PRINCIPAL: anthropic`), pero se vuelve a
  medir antes: el prompt es el mismo para los dos y lo que importa es cómo
  razona con él, no la marca.

## 12/10: el respaldo básico de Claude pasa a Haiku 5.5

Camilo pidió el Haiku más nuevo. Comprobado en la lista de modelos de la API de
Anthropic: `claude-haiku-5-5` (Claude Haiku 5.5, del 07/10/2026). Precio oficial:
US$0,10 / 0,50 por millón de tokens (mensajes de hasta 100.000 tokens; los del bot
rondan 13.000-22.000), **10 veces menos que Haiku 4.5** (US$1 / 5) y lo mismo que
GPT-6 luna. GPT sigue primero; Claude, detrás.

Medido con el prompt y el esquema reales de la asesora:

| | Haiku 4.5 | Haiku 5.5 |
|---|---|---|
| Entiende «creo que soy talla 7, lo quiero de 2 huellitas» | sí | sí |
| Con caché (en caliente) | 3,0 s | 2,7 s |
| Una foto (la guía de la talla) | — | 1,3 s sin pensar · 2,0 s pensando |
| `thinking: disabled` | lo rechaza (no se le manda) | lo acepta (se le manda) |
| `thinking: between_tools` | — | lo rechaza |

La primera llamada con el esquema tarda ~60 s en los dos (Anthropic compila la
gramática una vez); el calentamiento del arranque la cubre. También mira las fotos
cuando GPT no puede (`LLM_VISION_MODEL`). Fijado en `docker-compose.yml`, que manda
sobre el `.env`.

## 12/10: ¿Haiku 5.5 de principal? Probado y descartado: sigue luna

Camilo pidió probar Haiku 5.5 de principal y luna de respaldo. Para que la
diferencia sea **del modelo y no de la medición**, se corrió la prueba de verdad
completa con **el mismo código, la misma configuración (ráfaga de 20 s / 1 min) y
las mismas 29 clientas**, cambiando solo `IA_PRINCIPAL`, dos vueltas cada uno, en
el servidor y sin tocar producción (`docker compose run -e IA_PRINCIPAL=…`):

| `IA_PRINCIPAL` | Vuelta | Pasos bien | Fallas | Turnos | Costo | Tiempo |
|---|---|---|---|---|---|---|
| `anthropic` (Haiku 5.5 → luna) | 1 | 195 de 201 | 6 | 154 | US$0,739 | 11,3 min |
| `anthropic` (Haiku 5.5 → luna) | 2 | 188 de 194 | 6 | 145 | US$0,671 | 10,6 min |
| `openai` (luna → Haiku 5.5) | 1 | 193 de 193 | 0 | 144 | US$0,061 | 8,9 min |
| `openai` (luna → Haiku 5.5) | 2 | 191 de 192 | 1 | 143 | US$0,052 | 8,4 min |

**Las fallas de Haiku de principal** (todas de criterio, ninguna de la medición):
pidió datos de envío antes de tiempo; repitió «¿De cuántas huellitas lo quieres?»;
puso a esperar a Lía una talla que la clienta DIJO; en una compra de dos anillos
perdió el segundo (cobró $200.000 en vez de $400.000 y el resumen no lo nombraba);
dejó de decir el precio y una fecha grabada; un pedido no nació. Costó **unas 12
veces más** que luna (US$0,67-0,74 contra 0,05-0,06), porque su tokenizador cuenta
~22.000 tokens donde luna cuenta ~13.000 y porque, de principal, cuando duda va a
Sonnet 5.5.

**La única falla de luna** (`paga_antes`) se repitió aparte: 3 de 3 bien. Venía de
algo que se arregló y vale para cualquier modelo: después de pagar, el tope de
«pedirlo dos veces» callaba la pregunta de lo que falta. Con el pago hecho, lo que
falta se pide siempre. En las vueltas finales apareció otra, también de criterio y
ya cerrada: con dos anillos, la IA a veces le copiaba al segundo la talla del
primero (ahora no se anota si ella no habló de talla).

**Con los arreglos, las dos vueltas finales de luna** (lo que se desplegó): **193 de
193 y 193 de 193**, US$0,046 y 0,045, 8,6 y 8,5 min. En el camino aparecieron y se
cerraron, para cualquier modelo: el segundo anillo que a veces se creaba tarde
(ahora, si ella dice «quiero dos anillos», se crean de una) y la pregunta que,
repetida igualita, se callaba (ahora va con otras palabras).

**Decisión:** queda `IA_PRINCIPAL: openai` (luna primero, Haiku 5.5 de respaldo).
Haiku 5.5 se queda como respaldo porque, para eso, es 10 veces más barato que
Haiku 4.5 y responde igual de rápido. Para repetir la prueba: el procedimiento
«Cambiar qué IA va primero» del instructivo.
