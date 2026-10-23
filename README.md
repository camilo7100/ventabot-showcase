# VentaBot

**A WhatsApp sales agent that never lets the LLM be the system.** It quotes, takes measurements, lets the customer pick colours, draws a preview of the custom piece, builds the order and collects the deposit — for a small made-to-order silver-jewellery business. The language model only *reads* the conversation and returns a closed, validated object; **every decision, price and payment rule is plain Python**.

> 🇪🇸 Bot de ventas de WhatsApp para un taller de joyería de plata hecha a pedido. Cotiza, toma la talla, deja escoger colores, **dibuja cómo va a quedar la pieza**, arma el pedido y cobra el abono. El LLM solo interpreta el mensaje; todo lo que se decide lo decide una tabla de Python.

| | |
|---|---|
| **Tests** | 2,778 passing · 78 skipped (they measure pixels of the business's real product photos, which are not published) |
| **Static checks** | `ruff` clean · `mypy` clean on `app/domain` and `app/graph` · 4 architecture contracts enforced with `import-linter` |
| **Docs** | 30 architecture decision records (`docs/adr/`) · system documentation guarded by a test that fails if it falls behind |
| **Stack** | Python 3.11 · FastAPI · LangGraph · Pydantic v2 · SQLite/Postgres · Redis · Docker · Chatwoot (human inbox) · Anthropic & OpenAI APIs · LangSmith traces |
| **Built by** | one developer, September–October 2026, with AI coding assistants |

> **About this public version.** The production bot belongs to a real small business. This repository is a **showcase copy**: names, phone numbers, bank accounts, addresses, ad-account IDs, customer data and product photos were removed or replaced with fictitious ones, and the git history is fresh. It is meant to show the architecture and engineering, not to run a real shop out of the box.

---

## The idea in one paragraph

The LLM is **not** the system. It is a natural-language reader locked into two places (`interprete.py` and the image reader) and forced to return a Pydantic object with closed `Enum` fields. A table of Python decides everything that happens next. **Prices come from a CSV, never from the model. A payment is never confirmed by the bot, only by a person.** That makes the system predictable even though one layer underneath is probabilistic, and it means the model can be swapped (local → hosted, provider A → provider B) without touching business logic. A deterministic `golden` dataset measures how much the rules alone get right (`vb golden --solo-python`) versus with the model, so you can tell whether the model is earning its latency.

## Architecture (hexagonal, enforced)

```
app/
  domain/        pure rules: prices, sizes, colours, order states, guards      (knows nobody)
  conversacion/  the conversational advisor: reads, proposes, validates         (no adapters)
  graph/         LangGraph flow and nodes
  adapters/      WhatsApp, Chatwoot, ERP/Excel, LLMs, vision, storage          (no graph, no API)
  api/           FastAPI: webhooks, operator panel
  workers/       outbox, reminders, retries
  infra/         settings, logging, observability
```

`import-linter` fails the build if a layer imports one it shouldn't (`make arch`). Notable guards, each with its own tests:

- **Output guards:** the message the model drafts is checked before it is sent — no invented amounts, no phone/account numbers written by the model, no invented business name, no promised promotions, no "payment confirmed".
- **Order state machine:** a change to an existing order is authorised by its *state*, not by the model.
- **Idempotent webhooks + outbox:** signature check, dedup, retry and a durable outbox.
- **Human in the loop:** every sale lands in a Chatwoot inbox; a person verifies payments and handles anything the rules don't cover.

## Run it

```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
cp .env.example .env                                # fill nothing: it runs without network
make demo                                           # a full sale in the terminal
make test                                           # the whole suite (no network)
make check                                          # lint + types + architecture + tests
```

On Windows there is a `vb` launcher with the same commands (`vb demo`, `vb check`, `vb server`, `vb simular "hola"`…). With `CHANNEL_BACKEND=console` the replies are printed instead of sent through WhatsApp.

## Where to read next

| | |
|---|---|
| [`docs/MANUAL-VIVO.md`](docs/MANUAL-VIVO.md) | The living manual: what it does, what it measures, how it is built, what it deliberately does *not* do |
| [`docs/sistema/`](docs/sistema/README.md) | How it works today, piece by piece: sales flow, architecture, business rules, order states, Chatwoot, data & privacy, observability, ERP |
| [`docs/adr/`](docs/adr/README.md) | Why each decision was made (30 ADRs). The most valuable part of the repo |
| [`docs/ARQUITECTURA_CONTEXTO.md`](docs/ARQUITECTURA_CONTEXTO.md) | The context engine and the model fallback |

Documentation is in Spanish (the product's language); this README and the code structure are meant to be readable without it.

## What is intentionally not here

Real product photos and videos (placeholders keep the file names), customer conversations, the real catalogue prices and bank details, marketing data, server/deployment specifics, and secrets (`.env` is never tracked). Tests that measure pixels of the real photos are skipped in this copy and run in full in the private repository.

## License

MIT — see [LICENSE](LICENSE).
