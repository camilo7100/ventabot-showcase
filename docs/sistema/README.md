# El sistema, como funciona HOY

Esta carpeta describe VentaBot **tal como está corriendo ahora mismo**, no como
se pensó ni como quedará. Si algo aquí no coincide con lo que hace el programa,
el error está en esta carpeta y se corrige aquí, no al revés.

> **Última verificación: 21 de septiembre de 2026.**
> Chatwoot v4.17.0 · Python 3.11 · 2.050 pruebas en verde · 39 revisiones del
> diagnóstico en verde.

## Para qué sirve cada documento

| Documento | Responde a |
|---|---|
| [01 · El flujo de venta](01-flujo-de-venta.md) | Qué pasa, paso a paso, desde «hola» hasta «le llegó» |
| [02 · La arquitectura real](02-arquitectura.md) | Qué piezas hay, dónde vive cada una y quién puede llamar a quién |
| [03 · Las reglas del negocio](03-reglas-de-negocio.md) | Qué NO se puede hacer, y por qué cada regla existe |
| [04 · Los estados del pedido](04-estados-del-pedido.md) | Los 14 estados, quién los mueve y qué le llega a la clienta |
| [05 · Chatwoot y la operación diaria](05-chatwoot-y-operacion.md) | Cómo trabaja Lía: bandejas, etiquetas, tomar una charla, la app del celular |
| [06 · Los datos y la privacidad](06-datos-y-privacidad.md) | Qué se guarda, dónde, cuánto dura y qué no sale nunca del PC |
| [07 · Cómo se vigila](07-observabilidad.md) | El diagnóstico, LangSmith, las métricas y los registros |
| [08 · El ERP](08-erp.md) | Cómo se llena solo el HUELLAS_ERP_v1 de Google Sheets, y la pestaña que dice dónde está el bot |
| [09 · Glosario](09-glosario.md) | Qué quiere decir cada palabra rara |

## Cómo se mantiene viva

Documentación que envejece en silencio es peor que no tener ninguna: hace tomar
decisiones sobre un sistema que ya no existe. Aquí hay tres defensas:

1. **Pruebas que la vigilan.** `tests/unit/test_documentacion.py` falla si un
   estado del pedido, una etiqueta de Chatwoot o un comando de `vb` existen en
   el código pero no están escritos aquí (o al revés). No puede quedarse atrás
   sin que alguien se entere.
2. **Una sola fuente por dato.** Los precios salen de `data/catalogo.csv`, los
   fletes de `data/fletes.csv`, las cuentas de `app/domain/faq.py`, el punto de
   recogida de `faq.PUNTO_DE_RECOGIDA`. Aquí se explica **dónde vive** cada
   dato; los valores no se copian.
3. **El diagnóstico.** `vb diagnostico` revisa el sistema de verdad (ocho áreas,
   39 revisiones) y corre solo cada vez que se enciende el bot.

## Qué NO está aquí

- **Cómo se atiende** (para quien usa Chatwoot: etiquetas, escenarios, qué decir)
  → `MANUAL-DE-ATENCION.md`.
- **Lo que le toca a Camilo** (instalar, conectar, credenciales) →
  `INSTRUCTIVO-PARA-CAMILO.md`.
- **Qué comando hace qué** → `docs/MANUAL-VIVO.md`.
- **Por qué se decidió cada cosa**, con la discusión → `docs/adr/`.

Esta carpeta es el **cómo funciona**. Las otras son el cómo se usa, el por qué y
el qué sigue.
