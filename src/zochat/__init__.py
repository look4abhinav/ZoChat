"""ZoChat: a two-agent AI support bot for a Zo-style food-delivery service.

The package exposes the data layer (:mod:`zochat.db`) and the agent layer
(:mod:`zochat.agent`). Run the chatbot with the ``zochat`` console script —
a simple, colourful to-and-fro conversation loop.
"""

from __future__ import annotations

from rich.panel import Panel
from rich.text import Text


def main(argv: list[str] | None = None) -> int:
    """CLI entry point: an interactive to-and-fro conversation with the bot.

    A single question may be passed as positional args for one-shot use::

        zochat "Where is my order 1?"

    With no args the bot launches an interactive REPL. Type a question, press
    Enter, get a coloured reply; type ``/quit`` (or Ctrl+D / Ctrl+C) to exit.
    """
    import argparse
    import asyncio
    import os

    from rich.console import Console
    from rich.prompt import Prompt

    parser = argparse.ArgumentParser(
        prog="zochat",
        description="ZoChat AI support bot (orders, refunds, coupons, etc.).",
    )
    parser.add_argument(
        "question",
        nargs="*",
        help="one-shot question; if omitted, an interactive REPL starts",
    )
    parser.add_argument(
        "--model",
        default=os.environ.get("ZOCHAT_MODEL"),
        help="pydantic-ai model; if omitted, defaults to groq/qwen/qwen3.8-27b (or set ZOCHAT_MODEL to override)",
    )
    parser.add_argument("--session", default=None, help="session id or path")
    parser.add_argument("--no-persist", action="store_true", help="disable session persistence")
    parser.add_argument("--resume", default=None, help="resume a session id")
    args = parser.parse_args(argv)

    console = Console()
    model = args.model  # ``None`` -> chat() uses the default groq model.

    from zochat.agent import chat

    history: list | None = None

    async def ask(question: str) -> str:
        nonlocal history
        reply = await chat(question, model=model, message_history=history)
        history = reply.history
        return reply.answer

    one_shot = " ".join(args.question).strip()
    if one_shot:
        try:
            answer = asyncio.run(ask(one_shot))
        except Exception as exc:  # noqa: BLE001
            console.print(_err_text(f"Could not reach the support agent: {exc}"))
            return 1
        console.print(_bot_panel(answer))
        return 0

    from zochat.repl import ReplController
    from zochat.session import FileSessionStore, SessionState

    store = None if args.no_persist else FileSessionStore()
    session = None
    if store is not None:
        sid = args.resume or args.session or "default"
        session = store.load(sid)
    if session is None:
        session = SessionState()

    async def chat_fn(question, sess):
        reply = await chat(question, model=model, session=sess)
        return reply

    controller = ReplController(
        chat_fn=chat_fn, session=session, store=store, console=console,
        persist=not args.no_persist,
    )

    console.print(
        Panel(
            Text.from_markup(
                "[bold cyan]ZoChat[/bold cyan] — your Zo support assistant.\n"
                "Ask about orders, deliveries, payments, refunds, coupons, "
                "tickets, restaurants or your account.\n"
                "Type [bold]/help[/bold] for commands, [bold]/quit[/bold] to exit."
            ),
            border_style="cyan",
        )
    )

    while controller.running:
        try:
            question = Prompt.ask("[bold magenta]You[/bold magenta]")
        except (EOFError, KeyboardInterrupt):
            console.print("\n[dim]Goodbye![/dim]")
            return 0
        try:
            should_continue = asyncio.run(controller.handle(question))
        except Exception as exc:  # noqa: BLE001
            console.print(_err_text(f"Could not reach the support agent: {exc}"))
            continue
        if not should_continue:
            console.print("[dim]Goodbye![/dim]")
            return 0


def _bot_panel(answer: str) -> Panel:
    """Render a bot reply as a cyan Rich panel titled 'Zo'."""
    return Panel(answer, title="🤖 Zo", title_align="left", border_style="cyan")


def _err_text(msg: str) -> Text:
    """Render an error message in red bold."""
    return Text.from_markup(f"[bold red]⚠️ {msg}[/bold red]")
