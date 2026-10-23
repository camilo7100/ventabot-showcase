# 0015 — La base de ventas es SQLite; el Excel es una vista con columnas de Camilo

**Estado:** Aceptada · 2026-09-17
**Relacionada con:** [0002](0002-postgres-fuente-de-verdad.md)

## Contexto

Camilo necesita cada venta registrada con IDs y gobierno de datos, y un Excel
que pueda editar y que el sistema alimente solo. Es un negocio de una persona:
nada de servicios pagos ni infraestructura que mantener, pero que escale.

## Opciones

1. **El Excel como base.** Sin transacciones ni control de concurrencia: dos
   escrituras a la vez pierden una venta sin error (mismo problema que Sheets
   en 0002). Y un Excel abierto bloquea el archivo.
2. **Google Sheets / un CRM externo.** Cuotas, credenciales, costo y datos
   personales fuera del equipo; no hace falta con ~50 ventas al mes.
3. **SQLite como verdad + Excel regenerado**, con dueño por columna.

## Decisión

La 3.

- **Una venta es un pedido** (`orders`): no se duplica en otra tabla. Cada fila
  lleva `id_venta` (id del pedido, inmutable), código legible e `id_clienta`.
- **Dueño por columna** (`app/domain/ventas.py`): las del **sistema** (estado,
  montos, colores, fechas de abono/despacho/entrega) solo las escribe el
  sistema y quedan bloqueadas; las de **Camilo** (costo de material, costo real
  de envío, fuente, etiqueta, notas) quedan libres.
- **Ida y vuelta** (`app/workers/ventas.py`): primero se LEEN las columnas de
  Camilo y se guardan en `ventas_anotaciones` con bitácora append-only
  (`ventas_anotaciones_log`: antes, después, cuándo); luego se reescribe el
  Excel entero a un temporal que reemplaza al archivo. Si está abierto, se
  reintenta; lo de Camilo ya quedó en la base.
- **Automático**: el servidor revisa cada `VENTAS_CADA_S` (120 s) y solo escribe
  si algo cambió. `vb ventas` lo fuerza. Archivo en `VENTAS_EXCEL` (por defecto
  `Documentos\Luna Joyas\Ventas_LunaJoyas.xlsx`).
- **Gobierno visible**: hojas Ventas, Clientas, Diccionario (qué es cada
  columna, dueño, tipo, aviso de datos personales — Ley 1581) y Registro.

## Consecuencias

- Borrar o dañar el Excel no pierde nada: se regenera con todo, incluidas las
  anotaciones de Camilo.
- Escala sin cambiar el modelo: el día que haga falta Postgres (0002) o un
  tablero, se lee la misma base; el Excel es solo una salida más.
- Lo que Camilo escribe en una columna gris se pierde en la siguiente vuelta:
  está dicho en el Diccionario y la hoja lo bloquea para que no pase por error.
