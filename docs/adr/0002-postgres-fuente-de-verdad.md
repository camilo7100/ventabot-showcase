# 0002 — Postgres es la fuente de verdad; Google Sheets es una vista

**Fecha:** 2026-08-20 · **Estado:** Aceptada

## Contexto

Se quería arrancar con Google Sheets: es cómodo, el equipo comercial ya lo usa
y no exige infraestructura.

## Opciones

1. Sheets como base de datos.
2. Postgres como fuente de verdad, Sheets sincronizado como vista de lectura.
3. Solo Postgres, sin Sheets.

## Decisión

**Opción 2**, con un matiz de secuencia: el código se escribe contra el puerto
`OrderRepository` (6 métodos) y hay adaptadores para memoria, CSV, Sheets y SQL.
Se puede correr con Sheets mientras el volumen es bajo, y migrar cambiando
`REPOSITORY_BACKEND`.

## Consecuencias

Los números que fuerzan esto (cuotas oficiales de Google): **60 lecturas y 60
escrituras por minuto por usuario por proyecto**. A 1 lectura + 1 escritura por
mensaje, se satura con **~30 mensajes/minuto**.

Pero la cuota no es el problema grave. Sheets **no tiene transacciones ni
control de concurrencia**: no existe `SELECT ... FOR UPDATE`. Dos webhooks
simultáneos que hagan "leer última fila → escribir la siguiente" **se pisan y
se pierde un pedido, sin ningún error visible**. Un sistema que pierde pedidos
en silencio no es determinista.

Mitigación mientras se use Sheets: un único worker serializado con mutex de
Redis, `batchGet`/`batchUpdate` siempre, y caché con TTL. Es el precio de no
tener transacciones.

**Beneficio lateral:** hacer bien la migración Sheets → SQL es el ensayo general
de la migración SQL → SAP. Mismos 6 métodos, misma disciplina.
