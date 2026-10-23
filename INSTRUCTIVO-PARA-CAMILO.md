# Instructivo del desarrollador (versión pública)

Esta es una versión resumida: el instructivo real contiene pasos y contactos privados del negocio.

## Arrancar el bot sin red
Corre `vb demo` para ver una venta completa en la terminal. No usa WhatsApp ni modelos externos.

## Probar con el servidor
Corre `vb server` y, en otra terminal, `vb simular "hola, cuánto vale el anillo?"`. Con `CHANNEL_BACKEND=console` las respuestas salen en la terminal.

## Conectar WhatsApp
Necesitas una URL pública para el webhook y las credenciales de Meta en `.env` (nunca en git). Ver `docs/sistema/07-observabilidad.md`.
