# ZoChat Code Review — Critical Critique (updated)

## Summary

Offline suite is green (55 passed, 1 integration deselected) and `ruff check` is clean.
Postgres mutations now work (verified via `RETURNING id`), `chat()` validates input,
`chat_stream()` has top-level error handling, anonymous mutations now require an
identified customer, sessions no longer resurrect on `load(None)`, PII persistence
is opt-in, and atomic tools catch DB errors. Remaining risk is concentrated in
Postgres connection handling, streaming UX (tool events), coupon idempotency, and
observability. No code changed in this review.

## Remaining critical

None newly identified. (Anonymous mutation bypass fixed: `propose_action` now raises
`AuthorizationError` when `customer_id is None`.)

## Remaining major

1. **Postgres `connect()` is uncached and may still leak on rebuild.**
   src/zochat/db/__init__.py:59-86 runs `to_regclass` every call; no pooling.
2. **Naive SQL parameter/DDL handling in `PostgresConnection`.**
   `?`→`%s` via `str.replace` (src/zochat/db/__init__.py:26-33); `executescript`
   splits on `;` (src/zochat/db/__init__.py:35-41).
3. **`chat_stream()` still does not surface tool activity.** Despite
   `ChatStreamEvent.kind` supporting `tool_call`/`tool_result`
   (src/zochat/agent/models.py), src/zochat/agent/chat.py:208-315 never yields them.
4. **Generic exceptions still leak raw text to users.** Both `run()`
   (src/zochat/agent/chat.py:148-160) and `chat_stream()` (src/zochat/agent/chat.py:300-312)
   wrap failures as `DatabaseError(str(exc))`.
5. **`apply_coupon` has no idempotency guard.** src/zochat/db/mutations.py:355-388
   inserts into `coupon_redemptions` without checking for an existing redemption.
6. **`_MUTATION_LOCK` is process-local only.** src/zochat/db/mutations.py:23.
7. **Observability incomplete.** `support_deps()` (src/zochat/session.py) never sets
   `metrics`; `ToolCallRecord` never populated.

## Minor

- No DB-level `CHECK` constraints on enums/ranges.
- `customer_overview` calls `my_support_tickets` (all statuses).
- `/customer` phone heuristic; `/reset` metadata fixed.
- `active_coupons`/`validate_coupon` default to wall-clock `datetime.now()`.
- `SessionState` uses naive datetimes.
- `RequestMetrics.latency_ms` now uses `finished_at`.
- `connect()` SQLite sets busy timeout.

## Test gaps

- No Postgres-specific tests for `PostgresConnection` or mutations.
- No tests for `chat_stream` answer deltas or tool events.
- No tests for `FileSessionStore` persistence.
- No tests for `chat()` session threading across turns.
- No tests for mutation failure/rollback/audit rows.
- No tests for `validate_coupon` boundaries.
- No tests for composite queries.
- Eval harness is skeletal.

## Recommendations

1. Add a Postgres integration test (gated) covering mutations and connection.
2. Surface tool events in `chat_stream` via an event handler or queue.
3. Sanitize `user_message` in error paths (generic message + details logged).
4. Add idempotency check in `apply_coupon`.
5. Complete observability (tool timing, metrics propagation).
6. Add CHECK constraints and boundary tests.
