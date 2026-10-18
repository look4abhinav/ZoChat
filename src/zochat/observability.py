"""Observability helpers for ZoChat: request IDs, metrics and structured logging.

Everything here is stdlib-only. Optional logfire integration is enabled by
setting ``ZOCHAT_LOGFIRE=1`` (the package is an optional dependency).
"""

from __future__ import annotations

import contextvars
import logging
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

request_id_var: contextvars.ContextVar[str] = contextvars.ContextVar(
    "zochat_request_id", default=""
)


@dataclass
class ToolCallRecord:
    name: str
    duration_ms: float
    ok: bool
    args_summary: str = ""


@dataclass
class RequestMetrics:
    request_id: str
    started_at: datetime = field(default_factory=datetime.now)
    finished_at: datetime | None = None
    classifier_ms: float | None = None
    support_ms: float | None = None
    tool_calls: list[ToolCallRecord] = field(default_factory=list)
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    error_code: str | None = None

    def finish(self) -> None:
        self.finished_at = datetime.now()

    @property
    def latency_ms(self) -> float:
        end = self.finished_at or datetime.now()
        return (end - self.started_at).total_seconds() * 1000.0


class RequestIdFilter(logging.Filter):
    """Inject the current request id into every log record."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_var.get() or "-"
        return True


def new_request_id() -> str:
    return str(uuid.uuid4())


@contextmanager
def request_context(request_id: str | None = None) -> Iterator[str]:
    """Bind a request id to the current context for the duration of the block."""
    rid = request_id or new_request_id()
    token = request_id_var.set(rid)
    try:
        yield rid
    finally:
        request_id_var.reset(token)


def configure_logging(level: int = logging.INFO) -> None:
    """Configure stdlib logging with request-id propagation (idempotent)."""
    root = logging.getLogger("zochat")
    if any(isinstance(f, RequestIdFilter) for f in root.filters):
        return
    handler = logging.StreamHandler()
    handler.setFormatter(
        logging.Formatter(
            "%(asctime)s %(levelname)s [%(request_id)s] %(name)s: %(message)s"
        )
    )
    handler.addFilter(RequestIdFilter())
    root.addHandler(handler)
    root.setLevel(level)
    root.propagate = False


def timed_call(func, *args, **kwargs) -> tuple[Any, float]:
    """Call ``func`` and return ``(result, elapsed_ms)``."""
    start = time.perf_counter()
    result = func(*args, **kwargs)
    return result, (time.perf_counter() - start) * 1000.0


__all__ = [
    "RequestIdFilter",
    "RequestMetrics",
    "ToolCallRecord",
    "configure_logging",
    "new_request_id",
    "request_context",
    "request_id_var",
    "timed_call",
]
