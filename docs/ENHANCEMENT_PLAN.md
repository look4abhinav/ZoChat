# ZoChat Enhancement Plan

This document is the implementation plan for the next evolution of ZoChat.
It is a planning artifact only — no production code is changed by it. Each
section is written so an engineer can pick it up independently, but the
**recommended implementation order** and **milestones** at the end encode the
real dependencies between them.

The plan assumes the current codebase as of commit `e92bdd4`:
two-agent flow (classifier → support), 12 read-only SQLite tools, unittest
suite of 36 tests, and a simple REPL. All additions are designed to be
backward-compatible with that baseline unless explicitly noted.

---

## 0. Current state (baseline)

| Area | State |
|---|---|
| Data layer | 11 tables, read-only query functions in `zochat.db.queries` |
| Agents | Classifier (stateless) + support (deps = `sqlite3.Connection`) |
| Mutations | None — `can_cancel_order` only *checks* cancellability |
| Identity | Implicit, carried only by `message_history` text |
| Errors | Raw exceptions bubble to CLI; one retry budget (3) on agents |
| Observability | None beyond agent names |
| Validation | SQLite parameter binding only; no range/enum checks |
| Tests | 28 query tests + 8 agent tests; all offline (TestModel) |
| REPL | `/quit` only; no persistence; plain panels |

---

## 1. Cross-cutting foundations

These three items are prerequisites for almost everything else and should land
first.

### 1.1 Structured error model (Enhancement 6)

**Goal.** Replace ad-hoc `Exception` propagation with a typed, machine-readable
error hierarchy so the REPL, tests and (future) API clients can react
differently to validation, transient, authorization and not-found failures.

**New file:** `src/zochat/errors.py`

```python
class ZoChatError(Exception):
    code: str               # e.g. "order.not_found"
    retryable: bool
    user_message: str       # safe to show to customers
    details: dict[str, Any]

class ConfigurationError(ZoChatError): ...   # missing key, bad model string
class DatabaseError(ZoChatError): ...        # sqlite failure, integrity error
class ValidationError(ZoChatError): ...      # boundary input rejected
class NotFoundError(ZoChatError): ...        # no matching row
class AuthorizationError(ZoChatError): ...   # customer does not own resource
class ConflictError(ZoChatError): ...        # e.g. coupon already applied
class RateLimitError(ZoChatError): ...       # model provider 429
class TransientModelError(ZoChatError): ...  # timeout / 5xx
class ConfirmationRequired(ZoChatError): ... # mutation needs explicit consent
```

**Interfaces.**
- Every public function in `queries.py` / `mutations.py` raises `NotFoundError`
  (not `None`) only when the caller opts into `raise_on_missing=True`;
  default behaviour stays `None`-returning for agent tools.
- `chat()` / `run()` catch `ZoChatError` and attach it to `ChatReply.error`
  instead of raising. Non-`ZoChatError` exceptions are wrapped as
  `DatabaseError` / `TransientModelError` based on type.
- `ChatReply` gains `error: ErrorInfo | None` and `request_id: str`.

**Tests.** Unit tests in `tests/test_errors.py` for code mapping, retryable
flags and `ChatReply` serialization.

### 1.2 Input validation at boundaries (Enhancement 8)

**Goal.** Validate every value that crosses a trust boundary (CLI args, `chat()`,
tool args, DB writes) before it reaches SQLite or the model.

**New file:** `src/zochat/validation.py`

```python
class CustomerId(Annotated[int, Field(gt=0)])
class OrderId(Annotated[int, Field(gt=0)])
class TicketId(Annotated[int, Field(gt=0)])
class RestaurantId(Annotated[int, Field(gt=0)])
class Rating(Annotated[int, Field(ge=1, le=5)])
class PhoneNumber(Annotated[str, Field(pattern=r"^\+?[0-9]{7,15}$")])
class CouponCode(Annotated[str, Field(pattern=r"^[A-Z0-9]{3,20}$")])
class City(Annotated[str, Field(min_length=1, max_length=64)])
class TicketCategory(str, Enum): refund | delivery_delay | ...
class TicketPriority(str, Enum): low | medium | high
class TicketStatus(str, Enum): open | in_progress | resolved | closed
```

Plus pydantic request models:

```python
class ChatRequest(BaseModel):
    question: str = Field(min_length=1, max_length=4000)
    customer_id: int | None = None
    session_id: str | None = None

class CreateTicketRequest(BaseModel): ...
class ApplyCouponRequest(BaseModel): order_id: int; code: CouponCode
class RateOrderRequest(BaseModel): order_id: int; rating: Rating
```

**Scope.**
- `queries.py` / `mutations.py` validate their arguments with these types at
  function entry and raise `ValidationError` on failure.
- Tool wrappers in `support.py` validate before calling the DB and return a
  structured `{"error": ...}` payload to the model on failure (so the agent can
  ask the user to correct input instead of crashing the run).
- `schema.sql` gains `CHECK` constraints mirroring the enums/ranges and
  `NOT NULL` where missing.
- CLI validates `--model` is non-empty and question length.

**Tests.** `tests/test_validation.py` — boundary values, enum rejection,
phone regex, CHECK-constraint enforcement via seeded DB.

### 1.3 Observability (Enhancement 7)

**Goal.** Every request is traceable end-to-end with a request ID, per-stage
latency and token usage, and mutation audit records.

**New file:** `src/zochat/observability.py`

```python
request_id_var: ContextVar[str]          # propagated to logs + DB audit
@dataclass
class RequestMetrics:
    request_id: str
    started_at: datetime
    classifier_ms: float | None
    support_ms: float | None
    tool_calls: list[ToolCallRecord]     # name, args_hash, ms, ok
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    error_code: str | None

class ToolCallRecord(BaseModel): name: str; duration_ms: float; ok: bool; args_summary: str
```

**Interfaces.**
- `chat()` / `run()` create a `request_id` (uuid4) if none supplied and
  bind it to `request_id_var` for the duration of the request.
- Structured logging via stdlib `logging` with a `RequestIdFilter`; optional
  `logfire` integration enabled by `ZOCHAT_LOGFIRE=1` (logfire is already a
  dependency of the venv; add to `pyproject.toml` only if we want it declared).
- `ChatReply` gains `request_id`, `latency_ms`, `usage: UsageSummary | None`,
  `tool_calls: list[ToolCallRecord]`.
- Tool wrappers record timing and append to a per-request list held in
  `SupportDeps` (see Enhancement 3).
- Mutations write an `action_audit_log` row carrying `request_id`.

**Files touched.** `observability.py` (new), `chat.py`, `support.py`,
`db/mutations.py`, `db/schema.sql`, `__init__.py` (REPL logging setup).

**Tests.** `tests/test_observability.py` — request ID propagation, metric
population with TestModel (usage may be zero/None in tests but shape checked),
audit row written on mutation.

---

## 2. Action tools / mutations (Enhancement 1)

**Goal.** Let the support agent (with explicit customer consent) cancel
orders, create and resolve tickets, apply/validate coupons and rate orders,
atomically and auditably.

### 2.1 Scope

In scope:
- New mutation functions + a two-phase confirmation protocol.
- Agent tools for proposing and executing actions.
- Transactional semantics with rollback on any failure.
- Audit log + pending-action store.

Out of scope (this iteration):
- Payment capture / refunds triggered by cancellation beyond creating an
  `initiated` refund row.
- External side effects (emails, push notifications) — emit domain events
  only.

### 2.2 Files touched

- `src/zochat/db/schema.sql` — new tables + CHECK constraints.
- `src/zochat/db/mutations.py` — **new** mutation module.
- `src/zochat/db/queries.py` — add `order_overview`, `coupon_validation`,
  `validate_coupon` helpers (see Enhancement 4).
- `src/zochat/agent/support.py` — propose/execute tools + instructions.
- `src/zochat/agent/models.py` — `ActionProposal`, `ActionResult`, `ErrorInfo`.
- `src/zochat/agent/chat.py` — surface `pending_actions` via session.

### 2.3 Data / schema changes

New tables:

```sql
CREATE TABLE pending_actions (
    id              TEXT PRIMARY KEY,          -- confirmation token (uuid4)
    customer_id     INTEGER,
    action          TEXT NOT NULL,             -- cancel_order | create_ticket | ...
    target_type     TEXT NOT NULL,
    target_id       INTEGER,
    payload_json    TEXT NOT NULL,
    created_at      TEXT NOT NULL,
    expires_at      TEXT NOT NULL,
    consumed_at     TEXT,
    FOREIGN KEY (customer_id) REFERENCES customers(id)
);

CREATE TABLE action_audit_log (
    id              INTEGER PRIMARY KEY,
    request_id      TEXT,
    customer_id     INTEGER,
    action          TEXT NOT NULL,
    target_type     TEXT NOT NULL,
    target_id       INTEGER,
    status          TEXT NOT NULL,             -- previewed | confirmed | rejected | failed
    before_json     TEXT,
    after_json      TEXT,
    error_code      TEXT,
    created_at      TEXT NOT NULL
);

CREATE TABLE coupon_redemptions (
    id              INTEGER PRIMARY KEY,
    order_id        INTEGER NOT NULL UNIQUE,
    coupon_code     TEXT NOT NULL,
    discount_amount REAL NOT NULL,
    original_total  REAL NOT NULL,
    final_total     REAL NOT NULL,
    applied_at      TEXT NOT NULL,
    FOREIGN KEY (order_id) REFERENCES orders(id) ON DELETE CASCADE
);

-- additions to existing tables
ALTER TABLE support_tickets ADD COLUMN resolution_note TEXT;
ALTER TABLE orders ADD COLUMN cancelled_at TEXT;
ALTER TABLE orders ADD COLUMN cancelled_reason TEXT;
```

In practice the schema is rebuilt by `seed.py`, so these are added to
`schema.sql` (and `seed.py` updated to populate any new columns). A
migration note is added for users with an existing `ZoDB.db` (delete + reseed,
or run an Alembic-less migration script — see §7).

### 2.4 Interfaces / APIs

```python
# db/mutations.py
@dataclass
class ActionProposal:
    token: str
    action: str
    target_type: str
    target_id: int | None
    summary: str                  # human-readable preview
    before: dict[str, Any] | None
    risk: Literal["low", "medium", "high"]
    expires_at: datetime

@dataclass
class ActionResult:
    ok: bool
    action: str
    target_id: int | None
    status: Literal["completed", "rejected", "expired", "failed"]
    message: str
    before: dict[str, Any] | None
    after: dict[str, Any] | None
    audit_id: int | None

def propose_action(conn, *, customer_id, action, target_type, target_id,
                   payload, request_id=None) -> ActionProposal: ...

def execute_action(conn, *, token, request_id=None) -> ActionResult: ...

def cancel_pending_action(conn, token) -> bool: ...

# convenience wrappers used by agent tools
def propose_cancel_order(conn, *, order_id, customer_id=None, reason=None) -> ActionProposal
def propose_create_ticket(conn, *, customer_id, category, description, order_id=None, priority="medium") -> ActionProposal
def propose_resolve_ticket(conn, *, ticket_id, customer_id=None, resolution_note=None) -> ActionProposal
def propose_apply_coupon(conn, *, order_id, code, customer_id=None) -> ActionProposal
def propose_rate_order(conn, *, order_id, rating, customer_id=None) -> ActionProposal
```

**Confirmation protocol (transactional).**
1. Agent calls `propose_*` → returns `ActionProposal` with a single-use
   `token` (uuid4) persisted in `pending_actions` with a 10-minute TTL.
2. Agent presents `summary` to the customer and asks for explicit consent.
3. On consent, agent calls `execute_action(token)`. The function:
   - loads the pending row inside a transaction,
   - re-validates preconditions (order still cancellable, coupon still
     valid, ticket still open, …),
   - applies the mutation,
   - writes `action_audit_log`,
   - marks the pending row consumed,
   - commits. Any exception rolls back and records a `failed` audit row.
4. Tokens are single-use and expire; replay returns `status="expired"`.

**Authorization.** Every `propose_*` accepts `customer_id` from session
state. If provided, ownership is checked and `AuthorizationError` raised
otherwise. If `None` (anonymous session), the action is allowed but flagged
`risk="high"` in the proposal so the agent double-confirms.

**Transaction helper.**

```python
@contextmanager
def transaction(conn):
    try:
        yield
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
```

All mutations use it; `conn` busy timeout set to 5 s.

### 2.5 Agent tool surface

`support.py` registers ten new tools (propose + execute, or one combined tool
per action). Recommended: one `propose_action_*` and one shared
`execute_pending_action(token)` to keep the tool count and prompts small:

```
propose_cancel_order(order_id, reason=None)
propose_create_ticket(category, description, order_id=None, priority="medium")
propose_resolve_ticket(ticket_id, resolution_note=None)
propose_apply_coupon(order_id, coupon_code)
propose_rate_order(order_id, rating)
execute_pending_action(confirmation_token)
cancel_pending_action(confirmation_token)
```

Instructions updated (Enhancement 4) to require the two-step flow.

### 2.6 Tests

- `tests/test_mutations.py` (new): happy paths, precondition failures,
  expiry, replay, rollback on forced error, authorization, audit rows.
- `tests/test_agent.py` additions: tool set now includes 7 new tools;
  TestModel scenario exercising propose → execute.
- Property-style tests (optional) for token single-use.

### 2.7 Risks

- **Model skips confirmation.** Mitigated by two-phase token: there is no
  code path that mutates without a valid token from a prior propose call.
- **Race conditions.** Re-validation inside the transaction; SQLite write
  lock serializes. Busy timeout prevents immediate failure.
- **Partial side effects.** All writes in one transaction; no external
  calls inside the transaction.
- **Audit PII.** `args_summary` stores hashes/ids, not phone numbers.

### 2.8 Dependencies

Depends on: 1.1 errors, 1.2 validation, 1.3 observability (audit), 3 session
(for `customer_id`). Can start mutation core (propose/execute) before session
lands by accepting `customer_id=None`.

---

## 3. Session identity state (Enhancement 3)

**Goal.** Carry a structured customer identity (and last-seen entities) across
REPL turns instead of relying on the model re-reading its own prose.

### 3.1 Files touched

- `src/zochat/session.py` — **new**: `SessionState`, `SessionStore`,
  `FileSessionStore`.
- `src/zochat/agent/models.py` — `ChatReply.session`.
- `src/zochat/agent/chat.py` — accept/return session; inject into deps.
- `src/zochat/agent/support.py` — deps type becomes `SupportDeps`.
- `src/zochat/__init__.py` — REPL uses session.

### 3.2 Interfaces

```python
class SessionState(BaseModel):
    session_id: str = Field(default_factory=lambda: str(uuid4()))
    customer_id: int | None = None
    customer_name: str | None = None
    phone: str | None = None
    last_order_id: int | None = None
    last_ticket_id: int | None = None
    message_history: list[Any] = Field(default_factory=list, exclude=False)
    created_at: datetime
    updated_at: datetime
    metadata: dict[str, Any] = Field(default_factory=dict)

@dataclass
class SupportDeps:
    conn: sqlite3.Connection
    session: SessionState
    request_id: str
    metrics: RequestMetrics

class SessionStore(Protocol):
    def load(self, session_id: str | None = None) -> SessionState | None: ...
    def save(self, session: SessionState) -> None: ...
    def delete(self, session_id: str) -> None: ...

class FileSessionStore(SessionStore): ...   # ~/.zochat/sessions/<id>.json
```

`chat()` / `run()` signatures:

```python
async def run(..., session: SessionState | None = None,
              request_id: str | None = None) -> ChatReply: ...
async def chat(question, *, conn=None, model=None,
               session=None, request_id=None, message_history=None) -> ChatReply: ...
```

When `session` is supplied, its `message_history` is used (overriding the
deprecated `message_history` arg, which becomes a fallback). The returned
`ChatReply.session` is the updated session (identity may have been set by a
tool). `message_history` on `ChatReply` is retained for backward compat but
mirrors `session.message_history`.

**Tool-side identity capture.** Tools that return a customer or order update
the session in place:

```python
@agent.tool
def find_customer_by_phone(ctx, phone):
    row = queries.find_customer_by_phone(ctx.deps.conn, phone)
    if row:
        ctx.deps.session.customer_id = row["id"]
        ctx.deps.session.customer_name = row["name"]
        ctx.deps.session.phone = row["phone"]
    return row
```

Similarly `where_is_my_order` sets `last_order_id`; `my_support_tickets` may
set `last_ticket_id` when a single ticket is referenced.

### 3.3 Tests

- `tests/test_session.py` — serialization round-trip, store atomic write,
  expiry, history threading.
- `tests/test_agent.py` — updated to construct `SupportDeps`; new test that
  identity survives two turns via session (TestModel).

### 3.4 Risks

- **Stale identity.** Mitigated by `/customer` and `/reset` REPL commands and
  an explicit "switch customer" tool.
- **PII on disk.** File store writes only customer id + name + phone by
  default; make phone storage opt-in via `ZOCHAT_PERSIST_PII=0`. Default off
  in plan? Recommendation: store customer_id only by default; phone only if
  opted in.
- **Concurrency.** File store uses per-session file lock; REPL is single-user.

---

## 4. Better tool-use guidance / fewer round trips (Enhancement 4)

**Goal.** Reduce agent turns and token usage by clearer instructions, composite
"overview" tools and disciplined tool selection.

### 4.1 Files touched

- `src/zochat/db/queries.py` — add composite queries.
- `src/zochat/agent/support.py` — register composite tools; rewrite
  `_SUPPORT_INSTRUCTIONS`.
- `src/zochat/agent/models.py` — `CouponValidation` model.

### 4.2 New composite tools

```python
def order_overview(conn, order_id) -> dict:
    # order header + items + payment + refunds + delivery in one call
def customer_overview(conn, customer_id, order_limit=5) -> dict:
    # profile + recent orders + open tickets
def validate_coupon(conn, code, cart_total, now=None) -> CouponValidation:
    # returns {valid, code, discount_type, discount_value, discount_amount,
    #          final_total, reason}
```

`CouponValidation`:
```python
class CouponValidation(BaseModel):
    valid: bool
    code: str
    discount_amount: float = 0
    final_total: float | None = None
    reason: str | None = None
```

### 4.3 Instruction rewrite (key points)

- Identify once: if `session.customer_id` is set, do not ask for phone; use it.
- Prefer composite tools (`order_overview`, `customer_overview`) for "tell me
  about X" questions; use atomic tools only for narrow follow-ups.
- Independent lookups may be issued in the same turn; dependent ones
  sequentially.
- Never call a tool with an id you do not have — ask the user first.
- For mutations, always propose first, present the summary, and wait for
  explicit consent before `execute_pending_action`.
- If `data_found=False` or a tool returns an error payload, say so plainly
  and suggest the next step; do not retry the same call with guessed args.
- Quote numbers exactly as returned.

### 4.4 Tests

- Query tests for composite outputs and coupon math (boundary: expired,
  below min order, cap applied).
- Agent wiring test updated tool set.
- Eval (Enhancement 2) measures tool-call count regression.

### 4.5 Risks

- Composite payloads are larger → token cost. Mitigate with field selection
  and `limit` defaults; do not include raw PII beyond what is needed.
- Tool proliferation (12 → ~19). Mitigated by clear descriptions and the
  "prefer composite" rule.

---

## 5. Streaming replies in REPL (Enhancement 5)

**Goal.** Show the answer as it is generated and surface tool activity, instead
of a single block after the full run.

### 5.1 Files touched

- `src/zochat/agent/chat.py` — add `chat_stream()` async generator.
- `src/zochat/agent/models.py` — `ChatStreamEvent`.
- `src/zochat/__init__.py` — REPL consumes stream; Rich `Live`.
- `src/zochat/repl.py` (new, see Enhancement 10).

### 5.2 Interfaces

```python
@dataclass
class ChatStreamEvent:
    kind: Literal["classification", "tool_call", "tool_result",
                  "answer_delta", "final", "error"]
    request_id: str
    text: str | None = None          # for answer_delta / error
    classification: QuestionClassification | None = None
    tool_name: str | None = None
    tool_args: dict[str, Any] | None = None
    reply: ChatReply | None = None    # only on "final"

async def chat_stream(question, *, conn=None, model=None, session=None,
                      request_id=None) -> AsyncIterator[ChatStreamEvent]: ...
```

Flow:
1. Run classifier (non-streaming, fast) → yield `classification`.
   If unrelated → yield `final` with declined reply.
2. Open `support.run_stream(...)`:
   - Use `event_stream_handler` to yield `tool_call` / `tool_result` events
     (tool name + a one-line args summary, no PII).
   - Consume `result.stream_output(debounce_by=0.05)`; diff `.answer` and
     yield `answer_delta`.
   - On completion, build `ChatReply`, update session, yield `final`.

**REPL rendering.** Use `rich.live.Live` with a `Markdown` renderable that
updates on each `answer_delta`; tool activity shown as dim status line above.
Fallback to final panel if streaming fails mid-way.

### 5.3 Tests

- `tests/test_streaming.py` — async test that `chat_stream` yields at least
  one `final` event with a `ChatReply`; with TestModel no deltas may be
  produced, so assert event ordering and final presence, not delta count.
- Manual smoke test documented in README.

### 5.4 Risks

- **PromptedOutput + streaming.** Partial JSON may not parse until enough
  tokens arrive; `stream_output` handles partial validation. If it raises,
  fall back to non-streaming `run()` and emit a single `final`.
- **Tool calls after "final".** `run_stream` stops at first matching output;
  document that streaming is for the final answer only (consistent with
  pydantic-ai semantics).
- **Ctrl+C during stream.** Cancel the async generator and close the
  connection only if owned.

---

## 6. Eval harness + golden dataset (Enhancement 2)

**Goal.** Measure classifier and support-agent quality on a versioned golden
dataset and catch regressions in CI (nightly, gated on real keys).

### 6.1 Files touched (new)

```
evals/
├── __init__.py
├── datasets/
│   ├── classifier.yaml
│   └── support.yaml
├── tasks.py          # classify_task, support_task
├── evaluators.py     # custom evaluators
└── run.py            # CLI: python -m zochat.eval run ...
tests/
├── test_eval_datasets.py   # schema validation, no key needed
└── integration/
    └── test_eval_golden.py # gated on real key
```

`pyproject.toml`: add pytest marker `eval`, `integration`.

### 6.2 Dataset design

Classifier cases (~60):
```yaml
- name: order_status_1
  inputs: { question: "Where is my order 1?" }
  expected_output: { is_related: true, category: order }
```
Categories covered: all 11 categories + unrelated (weather, jokes, other
brands, empty-ish greetings). Include adversarial phrasings and Hinglish.

Support cases (~25):
```yaml
- name: order_1_tracking
  inputs: { question: "Where is my order 1?", customer_phone: "+919800000001" }
  metadata: { expected_tools: [where_is_my_order], expected_substrings: ["delivered", "Manoj"] }
```

### 6.3 Evaluators

- Classifier: `EqualsExpected` on `is_related` and `category`;
  `ConfusionMatrixEvaluator` report.
- Support: `ToolCorrectness` / `TrajectoryMatch` for expected tools;
  `Contains` for expected substrings; `MaxToolCalls(6)`; `MaxModelRequests(8)`;
  `MaxDuration(30)`.
- Optional `LLMJudge` for tone/helpfulness on a 1–5 rubric (costly; nightly
  only).

### 6.4 Tests

- `test_eval_datasets.py`: load both YAMLs with pydantic, assert unique names,
  valid categories, no empty questions. Runs offline.
- `test_eval_golden.py`: gated by `ZOCHAT_RUN_EVALS=1` and `GROQ_API_KEY`;
  asserts pass rates (classifier ≥ 0.95, support tools ≥ 0.90, substrings ≥
  0.85).

### 6.5 Risks

- **Flakiness/cost.** Temperature 0, fixed seed where supported, retry on
  429, max-case caps, separate nightly job, artifacts stored.
- **Golden drift.** Dataset is versioned; changes require PR review.

---

## 7. Integration tests gated on real keys (Enhancement 9)

**Goal.** A small, trustworthy end-to-end suite that runs against the real
model + a temp DB, skipped by default.

### 7.1 Files touched

```
tests/integration/
├── __init__.py
├── conftest.py          # temp DB fixture, key skipif, cost guard
├── test_real_classifier.py
├── test_real_support.py
└── test_real_mutations.py
```

`pyproject.toml`:
```toml
[tool.pytest.ini_options]
markers = [
  "integration: requires network and a real API key",
  "eval: runs the golden dataset (costly)",
]
addopts = "-m 'not integration and not eval'"
```

### 7.2 Coverage

- Classifier: 10 representative questions → expected related/unrelated.
- Support: 5 questions → answer non-empty, `data_found` matches, at least one
  tool called (inspect via result).
- Mutations: propose cancel on a `placed` order → execute → status cancelled
  + audit row; replay token → expired.
- Cost guard: max 20 model requests per test session.

### 7.3 Risks

- **Cost/quota.** Nightly only, small case counts, timeout 120 s.
- **Provider changes.** Pin model name via env; tests assert shape not exact
  wording.

---

## 8. REPL QoL (Enhancement 10)

**Goal.** Make the interactive loop genuinely usable: history, reset, customer
switching, persisted sessions, markdown.

### 8.1 Files touched

- `src/zochat/repl.py` — **new** `ReplController` (testable, no I/O in
  core).
- `src/zochat/__init__.py` — thin wrapper over controller.
- `src/zochat/session.py` — persistence (shared with Enhancement 3).
- `src/zochat/agent/chat.py` — streaming (shared with Enhancement 5).

### 8.2 Commands

| Command | Effect |
|---|---|
| `/help` | List commands |
| `/history` | Print turns (user + bot) with timestamps |
| `/reset` | Clear `message_history` and session identity (keeps session id) |
| `/new` | Start a brand-new session (new id, empty history) |
| `/customer <phone\|id>` | Set identity explicitly (calls `find_customer_by_phone` or `customer_profile`) |
| `/session` | Show session id, customer, last order/ticket |
| `/last` | Reprint last bot reply |
| `/quit`, `/exit`, `/q` | Save session (if persistence on) and exit |

Plus Ctrl+D / Ctrl+C.

### 8.3 Persistence

- Default store: `~/.zochat/sessions/default.json`.
- Flags: `--session <path>`, `--no-persist`, `--resume <id>`.
- Atomic write on exit and after each turn (debounced 2 s) so a crash loses
  at most one turn.
- Schema version field in the JSON; on mismatch, warn and start fresh rather
  than crash.

### 8.4 Markdown

- Bot replies rendered as `rich.markdown.Markdown` inside the panel.
- One-shot mode also uses Markdown.
- Code fences / tables supported; long lines wrap.

### 8.5 Tests

- `tests/test_repl.py` — command parsing and controller state transitions
  with a fake chat backend (no model).
- Manual checklist in README.

### 8.6 Risks

- **Persistence of PII.** Default to id-only (see 3.4).
- **History size.** Cap persisted history at 200 messages; older turns
  dropped with a note.

---

## 9. Recommended implementation order

Ordered by dependency, not by enhancement number:

1. **1.1 Error model** (`errors.py`) — foundation.
2. **1.2 Validation** (`validation.py` + schema CHECKs) — foundation.
3. **1.3 Observability** (`observability.py`, request IDs) — foundation.
4. **3 Session state** (`session.py`, `SupportDeps`) — needed by mutations for
   authorization; also improves chat API.
5. **2 Mutation core** (`db/mutations.py`, pending actions, audit) — depends
   on 1.1–1.3, 3.
6. **4 Composite tools + instruction rewrite** — depends on 2 (coupon validation
   needs mutation helper) and 3.
7. **5 Streaming** (`chat_stream`) — depends on 3 (session) and 4 (tool events).
8. **8 Eval harness + golden datasets** — can run in parallel with 5–7; needs
   stable tool set (after 4).
9. **10 REPL QoL** — depends on 3, 5, 1.1.
10. **7/9 Integration tests** — last, after everything stable.

Parallelism: 8 (evals) can start after step 4 and proceed alongside 5/7/10.
1.1–1.3 can be done in parallel by one engineer in ~1 week.

---

## 10. Milestones

| Milestone | Contents | Exit criteria |
|---|---|---|
| **M0 — Foundations** | Errors, validation, observability | 36 existing tests green + new unit tests; `ChatReply` carries request_id |
| **M1 — Sessions** | `SessionState`, `SupportDeps`, identity capture | Agent tests updated; identity survives two turns in a TestModel test |
| **M2 — Mutations** | propose/execute, transactions, audit, 7 new tools | `test_mutations.py` green; cancellation E2E via TestModel |
| **M3 — Smarter tools** | Composites, coupon validation, instruction rewrite | Tool-count wiring test updated; eval tool-count budget met |
| **M4 — Streaming + REPL** | `chat_stream`, Rich Live, commands, persistence | Manual smoke; REPL tests green |
| **M5 — Evals** | Golden datasets, runner, gated tests | Offline dataset tests green; nightly eval job configured |
| **M6 — Integration + release** | Real-key tests, CI, docs update | Integration suite green on nightly; README updated |

Estimated: 6–8 weeks for one engineer, 4–5 with two.

---

## 11. Test strategy summary

| Layer | Location | Offline? | Notes |
|---|---|---|---|
| Query functions | `tests/test_customer_queries.py` | yes | extend for composites/mutations |
| Mutations | `tests/test_mutations.py` | yes | rollback, expiry, auth |
| Validation | `tests/test_validation.py` | yes | boundaries + CHECK constraints |
| Agent flow | `tests/test_agent.py` | yes | TestModel; updated for SupportDeps |
| Session/store | `tests/test_session.py` | yes | |
| REPL controller | `tests/test_repl.py` | yes | fake chat backend |
| Streaming | `tests/test_streaming.py` | yes | event ordering only |
| Observability | `tests/test_observability.py` | yes | caplog + shape |
| Eval datasets | `tests/test_eval_datasets.py` | yes | schema only |
| Golden evals | `tests/integration/test_eval_golden.py` | no (gated) | |
| E2E | `tests/integration/` | no (gated) | real key + temp DB |

Default `pytest -q` runs only offline layers (markers exclude integration/eval).

---

## 12. Backward-compatibility & migration notes

- `chat()` keeps `message_history=` as a deprecated fallback when `session`
  is not supplied; both continue to work.
- `run()` still accepts pre-built agents; deps type changes from
  `sqlite3.Connection` to `SupportDeps`. Tests and callers must wrap
  connections: `SupportDeps(conn=conn, session=SessionState(), request_id=...)`.
  A small helper `support_deps(conn)` is provided for convenience.
- `build_support_agent()` deps type changes accordingly.
- Database schema additions require reseeding (`uv run python -m zochat.db.seed`)
  or a one-off migration. Because the dataset is small and deterministic, the
  recommended path is reseed; a `scripts/migrate_db.py` is optional.
- `ChatReply` gains only optional fields; existing assertions on
  `answered`/`answer`/`data_found` remain valid.

---

## 13. Open questions

1. **Confirmation UX for mutations**: two-phase token (proposed) vs. a
   single tool with `confirm: bool`. Token approach is safer but adds a tool
   call. Recommend token.
2. **Session storage backend**: file JSON (proposed) vs. SQLite table in
   `ZoDB.db`. File keeps user data separate from app data; recommend file.
3. **Streaming structured output**: keep `PromptedOutput` and diff `.answer`
   (proposed) vs. switch support agent to plain text + separate
   `data_found` heuristic. Recommend keeping structured; fallback to
   non-streaming on parse failure.
4. **PII persistence default**: store customer_id only by default
   (proposed). Confirm with product.
5. **Eval judge model**: reuse main model vs. a cheaper judge. Recommend
   cheaper model (e.g. `llama-3.1-8b`) to control cost; configurable.

---

*End of plan.*
