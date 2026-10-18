"""Typed, machine-readable errors for ZoChat.

All domain failures raise a subclass of :class:`ZoChatError` so callers (the
REPL, tests, future API clients) can react to *what* went wrong instead of
parsing exception text. Each error carries a stable ``code``, a ``retryable``
flag and a customer-safe ``user_message``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ErrorInfo:
    """Serialisable view of a :class:`ZoChatError` for ``ChatReply``."""

    code: str
    message: str
    retryable: bool = False
    details: dict[str, Any] = field(default_factory=dict)


class ZoChatError(Exception):
    """Base class for every ZoChat domain error."""

    code: str = "zochat.error"
    retryable: bool = False

    def __init__(
        self,
        message: str,
        *,
        code: str | None = None,
        retryable: bool | None = None,
        details: dict[str, Any] | None = None,
        user_message: str | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code or self.code
        self.retryable = self.retryable if retryable is None else retryable
        self.details = details or {}
        self.user_message = user_message or message

    def to_info(self) -> ErrorInfo:
        return ErrorInfo(
            code=self.code,
            message=self.user_message,
            retryable=self.retryable,
            details=self.details,
        )


class ConfigurationError(ZoChatError):
    code = "config.error"
    retryable = False


class DatabaseError(ZoChatError):
    code = "db.error"
    retryable = True


class ValidationError(ZoChatError):
    code = "validation.error"
    retryable = False


class NotFoundError(ZoChatError):
    code = "not_found"
    retryable = False


class AuthorizationError(ZoChatError):
    code = "auth.forbidden"
    retryable = False


class ConflictError(ZoChatError):
    code = "conflict"
    retryable = False


class RateLimitError(ZoChatError):
    code = "provider.rate_limit"
    retryable = True


class TransientModelError(ZoChatError):
    code = "provider.transient"
    retryable = True


class ConfirmationRequired(ZoChatError):
    code = "action.confirmation_required"
    retryable = False


__all__ = [
    "AuthorizationError",
    "ConfigurationError",
    "ConfirmationRequired",
    "ConflictError",
    "DatabaseError",
    "ErrorInfo",
    "NotFoundError",
    "RateLimitError",
    "TransientModelError",
    "ValidationError",
    "ZoChatError",
]
