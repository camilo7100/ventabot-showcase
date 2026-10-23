# 0025 — El centro de mando, y el ERP dice dónde está el bot

**Estado:** Aceptada · 20/09/2026 · Camilo: «algo fácil y supremamente estándar
para siempre saber dónde buscar el panel total».

## Contexto

Para saber cómo iba el negocio había que acordarse de seis direcciones: el
taller, las conversaciones, Chatwoot, el ERP, el registro y la base. Y la
dirección del bot no es fija: cambia con el túnel, con la máquina y el día que
viva en un servidor, donde ni siquiera hay una pantalla para ver si está
encendido.

## Decisión

- **Una página con todo: `/panel/todo`.** El estado de cada pieza en vivo y, a
  un clic, lo demás, incluido el registro del servidor (`/panel/registro`, con
  las claves tapadas). Va dentro del panel para heredar su llave, el `noindex`
  y el `no-referrer`, y porque el túnel ya manda `/panel…` al bot: el mismo
  enlace sirve en el PC y en el celular. Se abre con `VER-TODO.cmd` / `vb
  ver-todo`, que leen la llave del `.env` al vuelo.
- **Para el celular, un QR dibujado en el propio servidor** (`segno`), no en un
  servicio de internet: el enlace lleva la llave del panel.
- **La primera pestaña del ERP, CENTRO DE MANDO, la escribe el bot**: al
  arrancar y cada 10 minutos, dónde corre, su dirección, los enlaces y la hora
  de «visto vivo». El ERP es lo único que siempre está en el mismo sitio.
- **Qué llaves van ahí**: la del panel sí (abre esos enlaces, y quien ve el ERP
  ya ve los mismos datos). Las de Meta, Claude, Chatwoot y Google no: con ellas
  se gasta plata y se escribe por WhatsApp a nombre del negocio, y Google guarda
  el historial de cada celda para siempre. La hoja dice en qué archivo están.
- **Una llave rara es una llave mala, no un error.** El token se compara en
  bytes: con `str`, `compare_digest` revienta ante un «…» y tumbaba el panel
  entero (pasó copiando un enlace a medias).

## Consecuencias

- Pruebas: `tests/unit/test_centro_de_mando.py` (incluida la que falla si una
  clave de afuera llega a la hoja) y `TestElCentroDeMando` /
  `TestUnTokenRaroEsUnTokenMaloNoUnError` en `tests/unit/test_panel.py`.
- El diagnóstico comprueba que la pestaña exista.
- Si el ERP está compartido «con cualquiera que tenga el enlace», la llave del
  panel queda expuesta: el ERP se comparte solo con cuentas concretas.
