"""Session state and persistence for ZoChat.

A :class:`SessionState` carries structured identity (customer, last order/ticket)
and conversation history across REPL turns so the bot does not have to re-derive
them from prose. :class:`SupportDeps` bundles the live DB connection, session
and per-request metrics handed to the support agent's tools.
"""

from __future__ import annotations

import json
import os
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol

from pydantic import BaseModel, Field

from zochat.observability import RequestMetrics


class SessionState(BaseModel):
    """Mutable, serialisable state for one conversation."""

    session_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    customer_id: int | None = None
    customer_name: str | None = None
    phone: str | None = None
    last_order_id: int | None = None
    last_ticket_id: int | None = None
    message_history: list[Any] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)
    metadata: dict[str, Any] = Field(default_factory=dict)

    def touch(self) -> None:
        self.updated_at = datetime.now()


@dataclass
class SupportDeps:
    """Dependencies handed to the support agent's tools."""

    conn: Any
    session: SessionState
    request_id: str = ""
    metrics: RequestMetrics | None = None
    tool_calls: list[Any] = field(default_factory=list)


class SessionStore(Protocol):
    def load(self, session_id: str | None = None) -> SessionState | None: ...

    def save(self, session: SessionState) -> None: ...

    def delete(self, session_id: str) -> None: ...


class MemorySessionStore:
    """In-memory store, useful for tests and ephemeral sessions."""

    def __init__(self) -> None:
        self._data: dict[str, SessionState] = {}

    def load(self, session_id: str | None = None) -> SessionState | None:
        if session_id is None:
            return None
        return self._data.get(session_id)

    def save(self, session: SessionState) -> None:
        self._data[session.session_id] = session.model_copy(deep=True)

    def delete(self, session_id: str) -> None:
        self._data.pop(session_id, None)


class FileSessionStore:
    """JSON file store under a directory (one file per session)."""

    def __init__(self, directory: str | os.PathLike[str] | None = None) -> None:
        base = directory or os.path.join(os.path.expanduser("~"), ".zochat", "sessions")
        self.directory = Path(base)
        self.directory.mkdir(parents=True, exist_ok=True)

    def _path(self, session_id: str) -> Path:
        safe = session_id.replace("/", "_").replace("\\", "_")
        return self.directory / f"{safe}.json"

    def load(self, session_id: str | None = None) -> SessionState | None:
        if session_id is None:
            return None
        path = self._path(session_id)
        if not path.is_file():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return SessionState.model_validate(data)
        except Exception:  # noqa: BLE001
            return None

    def save(self, session: SessionState) -> None:
        session.touch()
        import os
        if os.environ.get("ZOCHAT_PERSIST_PII") != "1":
            session = session.model_copy(update={"phone": None})
        path = self._path(session.session_id)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(session.model_dump_json(indent=2), encoding="utf-8")
        tmp.replace(path)

    def delete(self, session_id: str) -> None:
        self._path(session_id).unlink(missing_ok=True)


def support_deps(conn, session=None, request_id: str = ""):
    """Convenience factory for :class:`SupportDeps`."""
    if session is None:
        session = SessionState()
    return SupportDeps(conn=conn, session=session, request_id=request_id)


__all__ = [
    "FileSessionStore",
    "MemorySessionStore",
    "SessionState",
    "SessionStore",
    "SupportDeps",
    "support_deps",
]
