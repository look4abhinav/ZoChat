"""Database utilities for ZoChat.

The SQLite database lives at ``zochat/data/ZoDB.db`` and is seeded by
:mod:`zochat.db.seed`. The schema is defined in ``schema.sql``.
"""

import sqlite3
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DB_PATH = DATA_DIR / "ZoDB.db"
SCHEMA_PATH = Path(__file__).resolve().parent / "schema.sql"


def connect() -> sqlite3.Connection:
    """Return a connection to the seeded SQLite database."""
    if not DB_PATH.exists():
        from zochat.db.seed import build_database

        build_database()
    # ``check_same_thread=False`` because pydantic-ai runs sync tools in a
    # worker thread; the support agent runs tools sequentially (max_concurrency=1)
    # so the connection is never accessed concurrently.
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.row_factory = sqlite3.Row
    return conn


__all__ = ["DB_PATH", "SCHEMA_PATH", "connect"]
