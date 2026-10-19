# Final Quality Review — ZoChat

**Branch:** `feature/postgres-and-enhancements` (vs `main`)
**Date:** 2025 (final review pass)
**Scope:** Cleanliness, organization, professionalism — naming, structure, docs, tests, debug leftovers, secrets, stray files.
**Checks run:** `uv run pytest -q` → 55 passed, 1 deselected; `uv run ruff check .` → all checks passed.

## Status

**Conditionally approved.** The codebase is functionally solid and well-tested
(55/55 offline tests green, ruff clean), with a clean modular architecture,
typed errors, input validation, session persistence, two-phase mutations, and
Postgres/SQLite dual support. However, the migration to Postgres and the
support-enhancement work are not yet reflected in the documentation, a generated
database binary is still tracked, a live secret exists in the local `.env`, and
a couple of unit tests implicitly depend on the network/`DATABASE_URL`. These
are hygiene/documentation issues rather than functional defects, but they
should be resolved before merging/releasing.

## Strengths

- **Tests & lint:** 55 tests pass; `ruff check` is clean. Agent flow is
  exercised with `TestModel` so no API key is required.
- **Architecture:** Clear separation across `agent/`, `db/`, `session`,
  `validation`, `errors`, `observability`. Two-agent flow (classifier → support)
  is well-documented in code.
- **Safety:** Authorization checks on mutations, anonymous mutations now require
  an identified customer, PII persistence is opt-in
  (`ZOCHAT_PERSIST_PII`), and transactional rollback is implemented.
- **Database portability:** `connect()` supports hosted Postgres via
  `DATABASE_URL`/`POSTGRES_DATABASE_URL` with a local SQLite fallback and
  auto-seeding.
- **No debug leftovers:** No `TODO`/`FIXME`/`print`-debug statements in `src/`
  beyond intentional CLI/seed output; no stray tracked `__pycache__`/cache dirs.
- **Secrets hygiene (partial):** `.env` is git-ignored and `.env.example` is
  the committed template; real env vars take precedence over `.env`.

## Issues to fix

1. **Documentation drift (README.md).** The README still describes the project
   as SQLite-only ("12 SQLite tools", "all 36 tests", dependency list omits
   `psycopg`), references the old OpenCode/DeepSeek model in several places,
   and its project-layout tree omits `errors.py`, `observability.py`,
   `session.py`, `validation.py`, `repl.py`, `mutations.py`, `schema_pg.sql`.
   The Configuration table does not document `DATABASE_URL` /
   `POSTGRES_DATABASE_URL`. Test counts (36 vs. 55) and tool counts (12 vs. 22
   exposed tools) are stale.
2. **Generated artifact tracked in git.** `src/zochat/data/ZoDB.db` (a 151 KB
   binary) is version-controlled and changed in this branch. It is regenerated
   by `seed.py` and auto-created by `connect()`, so it should be git-ignored to
   keep diffs clean and avoid merge conflicts.
3. **Live secret in local `.env`.** The working-tree `.env` contains real Neon
   credentials (`DATABASE_URL=...npg_...`). Although git-ignored, it is present
   on disk; rotate the credential and keep only `.env.example` locally. Confirm
   it never enters the index.
4. **Unit-test environment coupling.** `tests/test_streaming.py` calls
   `connect()`, which uses `DATABASE_URL` from `.env` when present, making a
   unit test depend on network/Postgres and on a mutable shared database (with
   destructive auto-seed if `customers` is missing). Tests should use a temp
   SQLite DB or an injectable connection factory.
5. **Schema doc mislabel.** `src/zochat/db/schema_pg.sql` header still says
   "ZoChat - SQLite schema"; should say Postgres. Also uses `TEXT` for
   timestamps rather than `TIMESTAMPTZ`.
6. **Package metadata placeholder.** `pyproject.toml` description is
   `"Add your description here"`; set a real description.
7. **Postgres adapter robustness.** `PostgresConnection` translates `?`→`%s`
   via `str.replace` and splits `executescript` on `;`, which is fragile for SQL
   containing those characters in literals/comments (flagged in `CRITIQUE.md`).
8. **Observability incomplete.** `support_deps()` never sets `metrics`, and
   `ToolCallRecord` is never populated; `RequestMetrics.latency_ms` uses
   `finished_at`/wall clock inconsistently (noted in `CRITIQUE.md`).
9. **Mutation idempotency/error handling.** `apply_coupon` relies on the DB
   `UNIQUE(order_id)` constraint but does not pre-check or translate a
   constraint violation into a clean `ConflictError`; a raw `IntegrityError` can
   leak to callers.
10. **Dangerous auto-seed.** `connect()` rebuilds the entire Postgres schema
    (`DROP TABLE ... CASCADE`) whenever `customers` is missing. This can wipe a
    partially initialized database and should be gated behind an explicit seed
    command or a safe "create if not exists" path.
11. **Commit granularity.** The entire feature is a single 3,590-line commit.
    Splitting into logical commits (Postgres migration, mutations, streaming,
    REPL/session, tests) would improve reviewability (optional).

## Recommendations

1. Update `README.md` to reflect the Postgres migration, new modules,
   accurate dependency/test/tool counts, and `DATABASE_URL` configuration.
2. Add `src/zochat/data/ZoDB.db` (and keep `*.db`/cache dirs) to `.gitignore`
   and remove the binary from tracking (`git rm --cached`).
3. Rotate the leaked Neon credential and remove the populated `.env` from disk;
   keep only `.env.example`.
4. Refactor `test_streaming.py` (and any other test using `connect()`) to use
   a temporary SQLite database, and add a gated Postgres integration test for
   mutations/connection (per `CRITIQUE.md`).
5. Fix `schema_pg.sql` header and consider `TIMESTAMPTZ` for timestamp columns.
6. Set a real `description` in `pyproject.toml`.
7. Harden `PostgresConnection` (parameter translation / script execution) or
   use psycopg's native helpers; sanitize user-facing error messages.
8. Complete observability: propagate `metrics` through `support_deps()`, record
   tool calls/timings, and log sanitized error details.
9. Add an idempotency check in `apply_coupon` and translate constraint
   violations to `ConflictError`.
10. Gate destructive auto-seeding behind an explicit flag/command.
