# Cómo trabajar en este repo

**Lee primero [`docs/MANUAL-VIVO.md`](docs/MANUAL-VIVO.md).** Es el retrato del proyecto tal como está
hoy: qué busca, qué logra (medido), cómo está armado, qué protege cada guardia, qué NO hace y qué falta.

**Déjalo actualizado.** Si cambias el modelo, el prompt, los precios o una regla que protege la plata,
corrige el manual en el mismo momento, en su sitio. El historial va en `docs/adr/` (el porqué de cada
decisión, un archivo por decisión, sin editar los viejos) y **cómo funciona hoy**, pieza por pieza, en
`docs/sistema/`, que tiene una prueba que falla si se queda atrás.

## Reglas que no se negocian

- Nunca escribirle a una clienta real desde una prueba.
- No mostrar claves en pantalla ni subirlas: viven en `.env` (fuera de git).
- Un pago **nunca** lo confirma el bot: lo confirma una persona.
- Los precios salen de un CSV, nunca del modelo.
- Esta es la **versión pública**: no incluye datos reales del negocio ni fotos de producto.

## Antes de dar algo por bueno

1. `vb check` (lint + tipos + arquitectura + todas las pruebas).
2. Si lo que falló cuesta dinero o confianza, la corrección va **en Python con su prueba**; el prompt no
   es una defensa. Si fue tono, va en `app/prompts/asesora_v1.txt`.
3. Una conversación que salió mal se vuelve un escenario de prueba, no una regla nueva.
