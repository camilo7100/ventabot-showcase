# 0031 — El banco de plantillas por situación: «la primera aprobada»

**Estado:** Aceptada (22/10/2026). El selector está hecho y APAGADO: no cambia
ningún envío hasta que Camilo prenda un grupo.

## Por qué

Pasadas las 24 h solo se le puede escribir a una clienta con una plantilla
aprobada por Meta, y aprobar una puede tardar un día o dos (las de `#retomar`
tardaron 20 h; las de `#asesora`, ~36 h). Esperar una sola plantilla por
situación deja al bot mudo ese tiempo. La respuesta de marketing es un banco:
**194 situaciones** (104 grupos con plantilla) y 344 plantillas, varias
alternativas por situación, en orden de preferencia. Se usa la primera que
Meta tenga aprobada.

## Cómo funciona

- **Los datos** viven en `data/plantillas/banco.json` (copia de
  `marketing-lia/guias/plantillas-para-meta.json`, solo lo que usa el selector;
  se refresca con `vb banco sincronizar RUTA`). Cada grupo trae su `orden` y cada
  plantilla el ROL de cada variable («nombre», «monto», «codigo»…).
- **El selector** (`app/domain/banco_de_plantillas.py`, puro): recorre el orden
  del grupo y toma la primera plantilla APROBADA a la que se le pueden llenar
  TODAS las variables (la foto de cabecera cuenta). Si una no se puede llenar, pasa
  a la siguiente; si ninguna sirve, devuelve nada: nunca se manda con un hueco ni
  con un valor inventado. Un grupo bloqueado por una decisión de negocio no
  escoge.
- **Los valores por rol** los pone quien manda. `roles_basicos` da los de siempre
  («de nuevo» si no se sabe el nombre, «tu peludito» si no se sabe el de la
  mascota). «monto», «saldo», «fecha»… cambian de sentido según la situación: no
  hay un valor único.
- **El estado en Meta** sale de UNA consulta que lista todas (caché de 15 min),
  no nombre por nombre.
- **La activación** es `data/plantillas/activos.json`: la lista de grupos
  prendidos. **Por defecto vacía**: `Container.plantilla_del_grupo` devuelve
  None. Escoger no manda nada; quien la use la entrega a `enviar_a_la_clienta`.

## Los límites de Meta que importan

- **Tope de plantillas:** 250 mientras el negocio no esté verificado (Meta:
  `business_verification_status = not_verified`). 15 existentes + 344 = 359 no
  cabe: el banco se sube por olas y, cuando un grupo tiene una aprobada, se
  borran las demás.
- **Creación:** 100 por hora por WABA. `crear_ola` las sube por tandas.
- **Reglas del texto** (las rechazó Meta el 22/10): el cuerpo no puede empezar
  ni terminar en variable (ni siquiera con un punto o un emoji detrás) y los
  botones de respuesta rápida no llevan emoji. Una prueba lo comprueba en las 344.
- Meta puede cambiar la categoría al crearla (7 de la ola 1 pasaron de UTILITY a
  MARKETING): se respeta, no se reescribe.

## La limpieza (`vb banco limpiar`)

Cuando un grupo tiene una aprobada, las otras sobran y ocupan cupo. Se queda la
primera aprobada del orden y se borran las demás, SALVO: las que ya estaban en
uso (`pedido_*`, `retomar_conversacion*`, `asesora_te_atiende*`, `anillo_con_abono`,
`asi_quedaria`, `cupo_en_el_taller`, `ultimo_*`, `retomar_diseno`, `hello_world`),
las que otro grupo todavía necesita, las de grupos bloqueados y cualquiera que no
sea del banco. La lista completa (con el texto, para poder recrearlas) se guarda
en `estado/banco/borradas-AAAAMMDD-HHMM.json` ANTES de borrar. Sin `--borrar`
solo muestra el plan.

## Lo que queda para después

- Conectar un grupo a una situación real del flujo (hoy nada lo llama).
- Los botones («Ya pagué», «Enviar datos») llegan al bot como texto; si deben
  tener un camino fijo, se define aparte.
- Un botón con «·» («5 · Excelente», 5 de las olas 2 y 3): no se sabe si Meta lo
  acepta; si no, se reporta como las demás.
