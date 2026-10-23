# 0019 — La dirección va después del abono, y un CRM que sí le contesta al bot

**Estado:** Aceptada · 19/09/2026 · Camilo, tras usar el bot y actualizar
Chatwoot a v4.17.0. Ajusta el ADR 0018, que sigue vigente en todo lo demás.

## Contexto

Tres cosas, el mismo día.

**1. Pedir la dirección antes de cobrar se sentía mal.** El ADR 0018 metió la
dirección entre lo obligatorio antes del abono, con buen motivo: sin dirección
no se despacha, y descubrirlo con el anillo hecho es perder una venta
terminada. Pero al usarlo, Camilo lo vio: preguntarle a alguien a dónde le
mandamos algo que todavía no ha comprado es un formulario, no una conversación.

**2. Apareció una forma de entrega que no existía en el código.** Hay clientas
que pasan a recoger el anillo en Floridablanca. Para ellas, «dirección de
envío» no significa nada, y avisos como «ya lo llevé a Coordinadora» o «va en
camino» son directamente falsos.

**3. Al actualizar Chatwoot de 3.16 a 4.17, el CRM dejó de contestarle al bot.**
Y lo hizo de la peor manera posible: sin un solo error a la vista. Los mensajes
se seguían viendo en la bandeja, así que parecía que todo iba bien. Pero nada
de lo que hacía Lía volvía al bot: ni sus respuestas, ni «Asignar a mí», ni las
etiquetas `hacer-…`. La causa estaba enterrada en los registros de Sidekiq:

```
Invalid webhook URL http://host.docker.internal:8000/webhook/chatwoot :
Hostname 'host.docker.internal' has no public ip addresses
```

Chatwoot 4.x protege sus webhooks contra SSRF: se niega a llamar a direcciones
privadas. Es una buena defensa para una instalación en internet. Aquí el bot
**es** una dirección privada, a propósito: corre en el mismo PC.

## Decisión

### La dirección se pide justo después del abono

- `falta_para_abono()` = el anillo completo (con talla) + nombre y ciudad.
- `falta_para_despachar()` = la dirección, **o** que dijo que lo recoge.
- El guardia se movió de sitio: `EN_PRODUCCION` ya no exige dirección;
  `DESPACHADO` sí, y lo impide `container.mover_pedido` para los dos caminos
  (panel y Chatwoot).
- Mientras falte, la conversación lleva la alerta `falta-direccion`, que la
  abre y la mete en su propia carpeta de Chatwoot.

La ciudad sigue antes del abono: es la que define el flete.

### Recoger es una forma de entrega, no una excepción

- `Borrador.recoge` y `DatosDeEnvio.recoge`; el modelo lo propone con
  `recoge_en_tienda`.
- Si recoge, no hace falta dirección ni ciudad, y los avisos son otros
  (`guion.AVISOS_RECOGE`): nada de guías ni de «va en camino».
- Cuando el bot manda las cuentas a alguien del área de Bucaramanga
  (`faq.CIUDADES_CERCA`), le ofrece recoger y ahorrarse el envío.
- Si después da una dirección, `recoge` se apaga solo.

### Toda conversación viva queda «Abierta»

> **Reemplazado el 09/10:** las charlas del bot quedan asignadas a VentaBot
> («Pendiente», así lo exige Chatwoot 4.17) y las de una persona, a ella
> («Abierta»); el filtro va en «Todos». Ver R11 en
> `docs/sistema/03-reglas-de-negocio.md`.

El bot ya no deja ninguna en «Pendiente». Las «Pendiente» no salen en la
bandeja por defecto ni en la app del celular, y por eso parecía que no llegaban
los mensajes al CRM. Quién lleva la conversación lo dicen la etapa y las
alertas, no el estado.

### Chatwoot puede llamar al bot: `SAFE_FETCH_ALLOW_PRIVATE_NETWORK=true`

En `docker/chatwoot/.env`.

**Alternativa que se descartó:** apuntar el webhook a la URL pública del túnel
(que sí resuelve a una IP pública). Funciona, pero hace que cada gesto de Lía
salga a internet y vuelva, para llegar a un proceso que está a un puerto de
distancia. Añade una dependencia de red, latencia y consumo del túnel a algo
que es local. La protección SSRF existe para que un tercero no consiga que tu
servidor llame a tu red interna; aquí no hay tercero: el único webhook
configurado lo puso Camilo, apunta a su propio bot y lleva token.

## Consecuencias

- Un fallo silencioso que se llevó medio día ahora es imposible de repetir:
  `vb diagnostico` comprueba en cada corrida que la red privada esté permitida
  y que Chatwoot no haya rechazado webhooks en la última media hora.
- `vb ensayo` pasa sus 29 comprobaciones, incluidas las que dependen de que el
  CRM le conteste al bot. Fueron las que destaparon esto.
- Una clienta que recoge ya no recibe mensajes que no son ciertos.
- Hay un pedido que puede estar «hecho pero sin a dónde mandarlo». Es un estado
  real del negocio, y ahora tiene nombre, alerta y carpeta en vez de ser una
  sorpresa.
