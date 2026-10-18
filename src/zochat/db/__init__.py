"""Database utilities for ZoChat.

Supports a hosted Postgres database (via ``DATABASE_URL``) and falls back to the
local SQLite file (``src/zochat/data/ZoDB.db``) when no URL is configured.
"""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from typing import Any

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DB_PATH = DATA_DIR / "ZoDB.db"
SCHEMA_PATH = Path(__file__).resolve().parent / "schema.sql"
SCHEMA_PG_PATH = Path(__file__).resolve().parent / "schema_pg.sql"


class PostgresConnection:
    """Thin wrapper making a psycopg connection look like sqlite3's."""

    def __init__(self, raw):
        self._raw = raw

    def execute(self, sql, params=()):
        sql = sql.replace("?", "%s")
        return self._raw.execute(sql, params)

    def executemany(self, sql, params_seq):
        sql = sql.replace("?", "%s")
        for params in params_seq:
            self._raw.execute(sql, params)

    def executescript(self, sql):
        # Split on semicolons is crude but sufficient for our DDL.
        for stmt in sql.split(";"):
            stmt = stmt.strip()
            if stmt:
                self._raw.execute(stmt)

    def commit(self):
        self._raw.commit()

    def rollback(self):
        self._raw.rollback()

    def close(self):
        self._raw.close()

    def __getattr__(self, name):
        return getattr(self._raw, name)


def _postgres_url() -> str | None:
    return os.environ.get("DATABASE_URL") or os.environ.get("POSTGRES_DATABASE_URL")


def connect() -> Any:
    """Return a connection to the configured database (Postgres or SQLite)."""
    from dotenv import load_dotenv

    load_dotenv()
    url = _postgres_url()
    if url:
        try:
            import psycopg
            from psycopg.rows import dict_row
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("psycopg is required for Postgres support") from exc
        raw = psycopg.connect(url, row_factory=dict_row)
        conn = PostgresConnection(raw)
        cur = conn.execute(
            "SELECT to_regclass('public.customers')"
        ).fetchone()
        exists = cur is not None and (next(iter(cur.values())) if isinstance(cur, dict) else cur[0]) is not None
        if not exists:
            raw.close()
            from zochat.db.seed import build_database

            build_database(None, verbose=False)
            raw = psycopg.connect(url, row_factory=dict_row)
            conn = PostgresConnection(raw)
        conn.execute("SET TIME ZONE 'UTC'")
        return conn

    # SQLite fallback (local / tests).
    if not DB_PATH.exists():
        from zochat.db.seed import build_database

        build_database(DB_PATH, verbose=False)
    conn = sqlite3.connect(DB_PATH, check_same_thread=False, timeout=5.0)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 5000")
    conn.row_factory = sqlite3.Row
    return conn


__all__ = ["DB_PATH", "SCHEMA_PATH", "SCHEMA_PG_PATH", "connect"]
