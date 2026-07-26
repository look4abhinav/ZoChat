# ZoChat

An AI support agent being built to replace Zo's older rule-based chat bot.
The agent answers customer queries about orders, deliveries, payments, refunds,
coupons and support tickets by querying a local SQLite database through a
two-agent pipeline built on [pydantic-ai](https://ai.pydantic.dev/) and backed
by the `minimax-m3` model served through the Opencode Go gateway.

> Status: data layer + two-agent flow wired and tested. The default model
> (`opencode-go/minimax-m3`) runs end-to-end once `OPENCODE_API_KEY` is provided.

---

## How it works

A customer's message goes through two AI agents in sequence:

1. **Classifier** (`zochat.agent.classifier`) — a lightweight gatekeeper that
   decides whether the question is in scope for Zo support (orders, deliveries,
   payments, refunds, coupons, tickets, restaurants, menu, account) or off-topic
   (weather, jokes, other companies). Returns a structured
   `QuestionClassification`; never touches the database.
2. **Support** (`zochat.agent.support`) — runs only for in-scope questions.
   Identifies the customer, then calls one or more of 12 SQLite-backed tools
   (the functions in `zochat.db.queries`) to fetch real data and composes a
   warm, factual reply. Every fact in its answer comes from a tool — never from
   the model's imagination.

Out-of-scope questions are declined politely without ever invoking the support
agent or the database.

```
                ┌─────────────┐
   customer ───▶│  classifier │──unrelated──▶ "I can only help with Zo support"
    message     └──────┬──────┘
                            │ related
                            ▼
                      ┌───────────┐   12 SQLite tools
                      │  support  │──────────────────▶  ZoDB.db
                      └─────┬─────┘
                            ▼
                      natural-language answer
```

## Project layout

```
src/zochat/
├── __init__.py          # `zochat` CLI: one-shot question or interactive REPL
├── config.py            # .env loader + default Opencode Go model builder
├── agent/
│   ├── __init__.py      # public exports for the agent layer
│   ├── chat.py          # orchestrator: runs classifier → support (or decline)
│   ├── classifier.py    # primary gatekeeper agent
│   ├── support.py       # secondary support agent + 12 DB tools
│   └── models.py        # pydantic output models (QuestionClassification, etc.)
├── db/
│   ├── __init__.py      # connect() helper, path constants
│   ├── schema.sql       # DDL for all 11 tables + indexes
│   ├── seed.py          # (re)creates ZoDB.db and inserts dummy data
│   └── queries.py       # customer-facing query functions (agent tools)
└── data/
    └── ZoDB.db          # generated SQLite database (84 rows of dummy data)
tests/
├── test_customer_queries.py  # unittest suite for the query functions (28 tests)
└── test_agent.py             # unittest suite for the two-agent flow (8 tests)
```

The project uses a `src/` layout and `uv` as the build backend, and targets
Python 3.14. Third-party dependencies are `pydantic`, `pydantic-ai`,
`python-dotenv`, and `rich` (pinned in `pyproject.toml`).

## Quick start

```bash
# 1. install (editable) with uv
uv sync

# 2. configure your Opencode Go credentials
cp .env.example .env
#   then edit .env and paste your OPENCODE_API_KEY

# 3. (re)build the database with dummy data
uv run python -m zochat.db.seed

# 4. ask a question
uv run zochat "Where is my order 1?"
# Bot: Your order #1 is currently in transit — rider Aditya …
```

The seed script is idempotent — it deletes any existing `ZoDB.db` and rebuilds
every table from `schema.sql`, so re-running always yields a clean, deterministic
dataset (timestamps pinned to 2026-07-21).

### Using the database from Python

```python
from zochat.db import connect

conn = connect()  # auto-seeds ZoDB.db if missing, enables FKs + Row factory
for row in conn.execute("SELECT id, name, city, loyalty_points FROM customers"):
    print(dict(row))
conn.close()
```

## Configuration

Runtime configuration lives in a project-local `.env` file loaded by
`python-dotenv`. Real environment variables always take precedence over `.env`
values, so CI and explicit `export` calls win.

| Variable | Required | Description |
|---|---|---|
| `OPENCODE_API_KEY` | yes | API key for the Opencode Go provider (serves `minimax-m3`). |
| `OPENCODE_BASE_URL` | no | OpenAI-compatible base URL. Falls back to `https://opencode.ai/zen/go/v1` when unset. |
| `ZOCHAT_MODEL` | no | Override the pydantic-ai model string the CLI uses by default (e.g. `google-gla:gemini-2.0-flash`). When unset, the CLI defaults to `opencode-go/minimax-m3`. |

`.env` is git-ignored; copy `.env.example` to start. The default model is built
lazily by `zochat.config.get_opencode_model()` only when `chat()` is called
without an explicit `model=`, so importing the package (and running the test
suite) never requires the key.

## Customer-facing queries (agent tools)

`src/zochat/db/queries.py` exposes one function per question a customer might
ask the chatbot. Each returns plain dicts (JSON-serialisable) so an LLM agent
can phrase the reply. These are the exact functions the support agent calls.

| Function | Customer question |
|---|---|
| `find_customer_by_phone(conn, phone)` | "Who am I?" — identify a customer from their phone |
| `customer_profile(conn, customer_id)` | "What are my account details / loyalty points?" |
| `where_is_my_order(conn, order_id)` | "Where is my order?" — order + delivery + rider contact |
| `recent_orders(conn, customer_id, limit=5)` | "What are my recent orders?" (newest first) |
| `order_items_detail(conn, order_id)` | "What did I order in order #X?" — line items + totals |
| `payment_status(conn, order_id)` | "Is my payment successful?" |
| `refund_status(conn, order_id)` | "When will I get my refund?" — all refunds + dates |
| `my_support_tickets(conn, customer_id)` | "What's the status of my complaint?" |
| `active_coupons(conn, now=None)` | "What coupons can I use right now?" |
| `restaurants_in_city(conn, city)` | "Which restaurants are available in my city?" |
| `menu_for_restaurant(conn, restaurant_id)` | "What's on the menu at restaurant X?" |
| `can_cancel_order(conn, order_id)` | "Can I cancel my order?" → `(bool, reason)` |

`refund_status` returns rows whose `status` is one of `initiated` /
`approved` / `processed` / `rejected` — the agent interprets these to phrase
"your refund was paid on …" vs "your request is awaiting approval, typically
3–5 business days".

## CLI

The `zochat` console script (defined in `pyproject.toml`) is the user-facing
entry point. It supports two modes:

### One-shot

```bash
uv run zochat "Where is my order 1?"
```

Prints a single coloured reply (a cyan Rich panel titled "🤖 Zo") and exits.

### Interactive REPL

```bash
uv run zochat
```

Launches a simple to-and-fro conversation loop:

- a cyan banner explains what the bot can help with,
- type a question, press Enter, and the bot prints a reply in a cyan panel,
- repeat as many times as you like,
- type `/quit` (or `/exit` / `/q`), or press Ctrl+D / Ctrl+C, to exit.

User prompts are rendered in magenta (`You:`), bot replies in cyan panels.
Errors reaching the agent are printed in red without killing the session —
you can ask again. Every question runs the full two-agent flow
(classifier → support / decline).

The REPL keeps **conversation memory** across turns: the support agent
receives the prior exchanges as `message_history`, so follow-ups like
"what about order 2?" or "do I have any coupons?" remember the customer
identified in the first turn without re-asking. Declined (off-topic) turns
are skipped from history, so they don't pollute the support context.

### Overriding the model

```bash
uv run zochat --model google-gla:gemini-2.0-flash "Where is my order 1?"
ZOCHAT_MODEL=google-gla:gemini-2.0-flash uv run zochat
```

If `--model` / `ZOCHAT_MODEL` are both unset the CLI falls back to the default
Opencode Go `minimax-m3` model from `zochat.config`.

## Agent architecture

### Two agents, two structured outputs

Each agent returns a typed pydantic model, parsed from the model's JSON
output via pydantic-ai's [`PromptedOutput`](https://ai.pydantic.dev/output/)
mode — the schema is injected into the system prompt and the model's free-text
reply is parsed as JSON. This was chosen over the default tool-call output
mode because it works with models (like `minimax-m3` via the Opencode Go
gateway) that do not reliably emit structured-output tool calls; without it the
agent would exhaust its output-retries and raise
`UnexpectedModelBehavior: Exceeded maximum output retries`. Both agents also
set `retries=3` for resilience.

- **`QuestionClassification`** (`agent.models`) — `is_related: bool`,
  `category: QuestionCategory | None`, `reasoning: str`. Produced by the
  classifier; the orchestrator routes on `is_related`.
- **`SupportAnswer`** (`agent.models`) — `answer: str`, `data_found: bool`.
  Produced by the support agent. `data_found=False` signals "no matching row"
  so the orchestrator can suggest next steps.

### Orchestrator: `zochat.agent.chat`

- `chat(question, *, conn=None, model=None) -> ChatReply` — convenience entry
  point. Builds fresh classifier + support agents and runs the flow. When
  `model is None`, uses `get_opencode_model()` (the Opencode Go `minimax-m3`
  default). When `conn is None`, opens (and closes) its own SQLite connection.
- `run(classifier, support, question, *, conn=None) -> ChatReply` — testable
  core that accepts pre-built agents. Tests inject `TestModel`-backed agents
  here so no LLM API key is needed.

### Support agent tools

`zochat.agent.support` exposes every customer-facing function in
`zochat.db.queries` as a pydantic-ai tool. The agent's `deps` is the live
`sqlite3.Connection`, so tools share one connection (run sequentially via
`max_concurrency=1`). The tool set is enumerated in the table below.

## Tests

The test suite has two halves, both using the standard-library `unittest`
framework (no extra test deps to install) and run via `pytest`:

```bash
uv run pytest -q              # all 36 tests, quiet
uv run pytest -v             # verbose (shows each question / case)
uv run pytest tests/test_agent.py          # agent flow only
uv run pytest tests/test_customer_queries.py  # query functions only
```

**`tests/test_customer_queries.py`** (28 tests) verifies every query function
against a fresh, temporary copy of the seeded database — it never touches
`src/zochat/data/ZoDB.db`. Covers 11 customer questions including edge cases
the agent must handle: cancelled orders with no delivery row, refunds in every
state (`processed` / `initiated`), a `pending` payment on a preparing order, an
inactive restaurant excluded from city listings, an unavailable menu item
hidden from the menu, and the cancellation rule (allowed only while `placed` or
`preparing`).

**`tests/test_agent.py`** (8 tests) exercises the two-agent flow using
`pydantic_ai.models.test.TestModel` — a stub that returns canned structured
outputs and records which tools were called. This lets the tests run without
any LLM API key. They verify:

- the classifier returns a structured `QuestionClassification`,
- the support agent wires all 12 database tools,
- the orchestrator answers related questions via the support agent,
- the orchestrator declines unrelated questions **without** calling the support
  agent,
- `chat()` opens (and closes) its own connection when none is supplied, and
  leaves a caller-supplied connection open.

## Database schema

Eleven tables covering the entities a food-delivery support bot needs. Full
DDL lives in [`src/zochat/db/schema.sql`](src/zochat/db/schema.sql).

| Table | Purpose | Seeded rows |
|---|---|---|
| `customers` | User accounts with contact, address & loyalty points | 6 |
| `restaurants` | Partner restaurants (cuisine, city, rating, prep time) | 6 |
| `menu_items` | Items each restaurant sells (price, veg, availability) | 15 |
| `delivery_partners` | Riders (vehicle, city, rating, active flag) | 4 |
| `orders` | Order header — status, totals, payment method, timestamps | 8 |
| `order_items` | Line items per order (qty, unit price) | 17 |
| `payments` | Payment records (method, gateway, txn id, status) | 8 |
| `refunds` | Refund requests linked to a payment + order | 3 |
| `deliveries` | Live delivery tracking (partner, status, distance, times) | 6 |
| `support_tickets` | The unit of work the chatbot triages | 6 |
| `coupons` | Promotional codes (percentage/flat, caps, validity) | 5 |

### Key columns & enum values

- **`orders.status`** — `placed` | `preparing` | `picked_up` | `delivered` | `cancelled`
- **`orders.payment_method`** — `upi` | `card` | `wallet` | `cod`
- **`payments.status`** — `success` | `failed` | `pending`
- **`payments.gateway`** — `razorpay` | `payu` | `cashfree` | `cod`
- **`refunds.status`** — `initiated` | `approved` | `processed` | `rejected`
- **`deliveries.status`** — `assigned` | `picked_up` | `in_transit` | `delivered`
- **`support_tickets.category`** — `refund` | `delivery_delay` | `food_quality` | `payment` | `cancellation` | `other`
- **`support_tickets.priority`** — `low` | `medium` | `high`
- **`support_tickets.status`** — `open` | `in_progress` | `resolved` | `closed`
- **`coupons.discount_type`** — `percentage` | `flat`

### Relationships

```
customers ──┐
            ├── orders ──┬── order_items ── menu_items ── restaurants
            │            ├── payments ──── refunds
            │            └── deliveries ── delivery_partners
            └── support_tickets (optional order_id)
coupons (standalone; referenced by orders.coupon_code)
```

Foreign keys are enabled (`PRAGMA foreign_keys = ON`) and `order_items`,
`payments` and `deliveries` cascade on order deletion.

## Sample queries the agent will run

**Where is my order?** (customer phone → live delivery status)

```sql
SELECT o.id, o.status, d.status AS delivery_status, d.distance_km,
       dp.name AS rider, dp.phone AS rider_phone
FROM orders o
JOIN deliveries d  ON d.order_id = o.id
JOIN delivery_partners dp ON dp.id = d.partner_id
WHERE o.id = ?;
```

**Refund status for an order**

```sql
SELECT rf.id, rf.amount, rf.reason, rf.status, rf.requested_at, rf.processed_at
FROM refunds rf
JOIN payments p ON p.id = rf.payment_id
WHERE rf.order_id = ?;
```

**Open tickets awaiting the chatbot** (the work queue)

```sql
SELECT t.id, t.category, t.priority, c.name, t.order_id, t.description
FROM support_tickets t
JOIN customers c ON c.id = t.customer_id
WHERE t.status IN ('open', 'in_progress')
ORDER BY CASE t.priority WHEN 'high' THEN 1 WHEN 'medium' THEN 2 ELSE 3 END;
```

**Validate a coupon for a cart total**

```sql
SELECT code, discount_type, discount_value, max_discount, min_order_value
FROM coupons
WHERE code = ? AND is_active = 1 AND expires_on > datetime('now');
```

## Seeded data highlights

- **6 customers** across Bengaluru, Mumbai, Delhi, Pune, Hyderabad with loyalty
  points ranging 0–610.
- **8 orders** spanning every status: 5 delivered, 1 cancelled, 1 picked_up
  (in transit), 1 preparing.
- **8 payments** including one `pending` (order still preparing) and one `cod`.
- **3 refunds**: one fully `processed` (cancelled order #5), one `approved`
  (food quality complaint on order #3), one `initiated` (late delivery on
  order #1).
- **6 support tickets**: 3 resolved/closed, 1 in_progress, 2 open — including a
  high-priority "rider hasn't moved" case and a payment-mismatch case.
- **5 coupons**: 4 active (incl. `WELCOME50`, `HEALTHY20`, `FLAT60`,
  `WEEKEND100`) and 1 expired (`EXPIRED25`) for testing expiry logic.
- Restaurant `Sweet Tooth Bakery` (id 6) is marked inactive, and one of its
  menu items (`Choco Lava Cake`) is unavailable — useful for testing
  availability checks.

## Regenerating the database

Because the dataset is fully derived from constants in `seed.py`, you can
rebuild it any time without network access:

```bash
uv run python -m zochat.db.seed
# or, to a custom location
uv run python -m zochat.db.seed --path /tmp/ZoDB.db
```

Add new dummy rows by editing the lists at the top of
[`src/zochat/db/seed.py`](src/zochat/db/seed.py) and re-running.