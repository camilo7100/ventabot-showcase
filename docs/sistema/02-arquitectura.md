# 02 · La arquitectura real

## El mapa en una pantalla

```
    WhatsApp (Meta)                        El celular de Lía
          │                                        │
          │ webhook firmado                        │ app de Chatwoot
          ▼                                        ▼
    ┌──────────────────── ngrok ───────────────────────────┐
    │  https://<dominio>.ngrok-free.dev                    │
    │    /webhook/ /panel /media/ /health  →  bot  :8000   │
    │    todo lo demás                     →  CRM  :3000   │
    └──────────────────────────────────────────────────────┘
          │                                        │
          ▼                                        ▼
    ┌─────────────────┐   copia cada mensaje  ┌──────────────┐
    │   VentaBot      │ ────────────────────► │   Chatwoot   │
    │   FastAPI :8000 │ ◄──────────────────── │  Docker :3000│
    └─────────────────┘   webhook de vuelta   └──────────────┘
       │      │      │                              │
       │      │      └──────► Google Sheets (ERP)   ├─ postgres
       │      └─────────────► LangSmith (trazas)    ├─ redis
       └────────────────────► SQLite (data/)        └─ sidekiq
                              Excel de ventas
```

Todo corre **en el PC de Camilo**. No hay nada en la nube salvo las APIs que se
llaman hacia afuera (Claude, Groq, Google Sheets, LangSmith, Meta).

## Las capas, y quién puede llamar a quién

La arquitectura es hexagonal y **no es una promesa: está verificada**.
`import-linter` corre en cada `vb check` con cuatro contratos, y si alguien
rompe una capa el commit no pasa.

```
  app/api          El borde: HTTP. Recibe webhooks, sirve el panel.
  app/workers      Lo que ocurre solo: outbox, recordatorios, ERP.
        │
        ▼
  app/conversacion El turno: entender, decidir, redactar, responder.
        │
        ▼
  app/domain       Las reglas. Python puro: sin red, sin base, sin Claude.
        ▲
        │
  app/adapters     El mundo de afuera, cada uno detrás de un puerto:
                   WhatsApp, Claude, Groq, Chatwoot, Sheets, SQLite, Excel.
  app/infra        El contenedor, la configuración, los registros, las trazas.
```

Los cuatro contratos, textuales:

| Contrato | Qué prohíbe |
|---|---|
| El dominio no conoce a nadie | `app/domain` no importa adapters, api, infra ni conversación |
| Los adaptadores no conocen el grafo ni la API | un adaptador no puede llamar hacia arriba |
| Capas | el orden api → conversación → dominio no se invierte |
| El gestor conversacional no conoce adaptadores | la conversación habla con puertos, no con httpx |

**Por qué importa:** las reglas del negocio (qué falta para el abono, qué
transición es legal, cuánto cuesta) viven en funciones puras que se prueban en
milisegundos y sin internet. Por eso hay 1.290 pruebas que corren en 27
segundos.

## Las piezas, una por una

### El bot — `app/` (FastAPI, puerto 8000)

- `app/api/main.py` — los webhooks (WhatsApp y Chatwoot) y el arranque.
- `app/api/panel.py` — el panel del taller, protegido por token.
- `app/conversacion/` — el turno completo: `interprete` (qué quiso decir),
  `asesora` (qué hacemos), `ejecutor`, `redactor`, `salida`.
- `app/domain/` — las reglas: `asesora` (el borrador y sus guardas),
  `operacion` (qué falta para fabricar y para despachar), `order_state` (la
  tabla de transiciones), `seguimiento` (etapas y alertas), `pricing`,
  `tallas`, `guion` (los mensajes), `faq` (las verdades del negocio).
- `app/infra/container.py` — el único sitio donde se arma todo y el **único
  camino** para mover un pedido (`mover_pedido`), venga del panel o de Chatwoot.

### El CRM — Chatwoot v4.17.0 (Docker, puerto 3000)

Cuatro contenedores: `rails`, `sidekiq`, `postgres` (pgvector/pg16) y `redis`.
El bot copia cada mensaje ahí y Chatwoot le devuelve lo que Lía hace.

> **Chatwoot 4.x no entrega webhooks a direcciones privadas** (protección SSRF).
> Como el bot corre en este mismo PC, hace falta
> `SAFE_FETCH_ALLOW_PRIVATE_NETWORK=true` en `docker/chatwoot/.env`. Sin eso el
> CRM funciona a medias **sin dar ningún error visible**: se ven los mensajes,
> pero nada de lo que Lía hace vuelve al bot. El diagnóstico lo vigila.

### El túnel — ngrok (`ngrok.yml`)

Un solo dominio https repartido por ruta entre el bot y Chatwoot. Es https
porque la app de Chatwoot del celular **rechaza direcciones http**.

### Los datos

- `data/ventabot.db` (SQLite) — conversaciones, mensajes, pedidos, outbox.
- `Documents/Luna Joyas/Ventas_LunaJoyas.xlsx` — el Excel de ventas.
- `HUELLAS_ERP_v1` en Google Sheets — el ERP, que se llena solo.
- `data/fotos/`, `data/renders/` — lo que manda la clienta y los prototipos.

### Lo que corre solo

| Trabajador | Cada cuánto | Qué hace |
|---|---|---|
| Outbox | 1 s | Saca los mensajes encolados hacia WhatsApp |
| ERP | 10 min | Reconcilia los pedidos con Google Sheets |
| Ventas | 2 min | Actualiza el Excel |
| Recordatorios | 5 min | Antes del abono, de día, sin acosar (ADR 0017) |

## Los modelos de IA

| Para qué | Primero | Si no contesta | Cuándo |
|---|---|---|---|
| Entender el turno | `gpt-6-luna` (`none`) | `claude-haiku-5-5` | Siempre |
| Rescate | `gpt-6-luna` (`low`) | `claude-sonnet-5-5` | Solo si la confianza es baja |
| Mirar fotos | `gpt-6-luna` | `claude-haiku-5-5` | Solo si llega una imagen |
| Notas de voz | Groq `whisper-large-v3-turbo` | — | Solo si llega un audio |

El orden y la paciencia los arma `CadenaDeModelos` (`app/adapters/llm/cadena.py`);
por qué este orden: [ADR 0027](../adr/0027-gpt-primero-claude-de-respaldo.md).

**VentaBot usa solo modelos en línea.** No usa Ollama: el PC tiene 4 GB de VRAM
y un modelo local ahí responde peor y más lento que lo que cuesta un turno en
línea.

## Cómo se enciende

`ENCENDER-BOT.cmd` **apaga primero** lo que hubiera quedado abierto y luego
abre dos ventanas —**SERVIDOR** y **TUNEL**—, cada una en un bucle que se
vuelve a levantar sola si el proceso se cae; al final corre el diagnóstico.

> Apagar antes de encender no es cortesía: si sobrevive un servidor de la vez
> anterior, el nuevo **no puede tomar el puerto 8000** y se queda
> reiniciándose en bucle. El bot sigue contestando —con el código viejo— y por
> fuera todo se ve normal. Pasó el 20/09 y costó una hora de pruebas que no
> probaban nada. El diagnóstico lo detecta por dos caminos: el servidor dice
> cuándo arrancó (`/health`) y se cuenta cuántos hay. `APAGAR-BOT.cmd` las cierra
buscando por el comando que corren, no por el título de la ventana.
