"""REPL controller for ZoChat (testable, minimal I/O in core)."""

from __future__ import annotations

import shlex
from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Any

from zochat.session import SessionState

ChatFn = Callable[[str, SessionState], Awaitable[Any]]


class ReplController:
    """Stateful controller behind the interactive REPL."""

    def __init__(
        self,
        *,
        chat_fn: ChatFn,
        session: SessionState | None = None,
        store=None,
        console=None,
        persist: bool = True,
    ) -> None:
        self.chat_fn = chat_fn
        self.session = session if session is not None else SessionState()
        self.store = store
        self.console = console
        self.persist = persist
        self.turns: list[tuple[str, str, datetime]] = []
        self.last_reply: str | None = None
        self.running = True

    def _print(self, msg: str) -> None:
        if self.console is not None:
            self.console.print(msg)

    async def handle(self, line: str) -> bool:
        """Handle one input line. Returns False when the REPL should exit."""
        line = line.strip()
        if not line:
            return True
        if line.startswith("/"):
            return await self._command(line)
        await self._ask(line)
        return True

    async def _ask(self, question: str) -> None:
        reply = await self.chat_fn(question, self.session)
        self.session = getattr(reply, "session", None) or self.session
        self.turns.append(("user", question, datetime.now()))
        answer = getattr(reply, "answer", str(reply))
        self.turns.append(("bot", answer, datetime.now()))
        self.last_reply = answer
        self._print(answer)
        if self.persist and self.store is not None:
            import contextlib
            with contextlib.suppress(Exception):
                self.store.save(self.session)

    async def _command(self, line: str) -> bool:
        parts = shlex.split(line)
        cmd = parts[0].lower()
        args = parts[1:]

        if cmd in ("/quit", "/exit", "/q"):
            self.running = False
            if self.persist and self.store is not None:
                import contextlib
                with contextlib.suppress(Exception):
                    self.store.save(self.session)
            return False

        if cmd == "/help":
            self._print(
                "Commands: /help /history /reset /new /customer <phone|id> "
                "/session /last /quit"
            )
            return True

        if cmd == "/history":
            for role, text, ts in self.turns:
                self._print(f"[{ts.strftime('%H:%M:%S')}] {role}: {text}")
            return True

        if cmd == "/reset":
            self.session.message_history = []
            self.session.customer_id = None
            self.session.customer_name = None
            self.session.phone = None
            self.session.last_order_id = None
            self.session.last_ticket_id = None
            self.session.metadata = {}
            self.turns.clear()
            self.last_reply = None
            self._print("Session reset.")
            return True

        if cmd == "/new":
            self.session = SessionState()
            self.turns.clear()
            self.last_reply = None
            self._print("New session started.")
            return True

        if cmd == "/session":
            self._print(
                f"session={self.session.session_id} customer={self.session.customer_id} "
                f"({self.session.customer_name}) last_order={self.session.last_order_id} "
                f"last_ticket={self.session.last_ticket_id}"
            )
            return True

        if cmd == "/last":
            if self.last_reply is not None:
                self._print(self.last_reply)
            return True

        if cmd == "/customer":
            if not args:
                self._print("Usage: /customer <phone|id>")
                return True
            ident = args[0]
            if ident.startswith("+"):
                self.session.phone = ident
                self._print(f"Identity set to phone {ident} (resolved on next query).")
            else:
                try:
                    self.session.customer_id = int(ident)
                except ValueError:
                    self.session.phone = ident
                    self._print(f"Identity set to phone {ident} (resolved on next query).")
            return True

        self._print(f"Unknown command: {cmd}")
        return True


__all__ = ["ReplController"]
