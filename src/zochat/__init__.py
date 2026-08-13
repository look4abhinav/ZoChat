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
        help="pydantic-ai model; if omitted, defaults to opencode-go/deepseek-v4-flash (or set ZOCHAT_MODEL to override)",
    )
    args = parser.parse_args(argv)

    console = Console()
    model = args.model  # ``None`` -> chat() uses the default opencode-go model.

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
        except Exception as exc:
            console.print(_err_text(f"Could not reach the support agent: {exc}"))
            return 1
        console.print(_bot_panel(answer))
        return 0

    console.print(
        Panel(
            Text.from_markup(
                "[bold cyan]ZoChat[/bold cyan] — your Zo support assistant.\n"
                "Ask about orders, deliveries, payments, refunds, coupons, "
                "tickets, restaurants or your account.\n"
                "Type [bold]/quit[/bold] (or Ctrl+D / Ctrl+C) to exit."
            ),
            border_style="cyan",
        )
    )

    while True:
        try:
            question = Prompt.ask("[bold magenta]You[/bold magenta]")
        except EOFError, KeyboardInterrupt:
            console.print("\n[dim]Goodbye![/dim]")
            return 0
        question = question.strip()
        if not question:
            continue
        if question.lower() in {"/quit", "/exit", "/q"}:
            console.print("[dim]Goodbye![/dim]")
            return 0
        try:
            answer = asyncio.run(ask(question))
        except Exception as exc:
            console.print(_err_text(f"Could not reach the support agent: {exc}"))
            continue
        console.print(_bot_panel(answer))


def _bot_panel(answer: str) -> Panel:
    """Render a bot reply as a cyan Rich panel titled 'Zo'."""
    return Panel(answer, title="🤖 Zo", title_align="left", border_style="cyan")


def _err_text(msg: str) -> Text:
    """Render an error message in red bold."""
    return Text.from_markup(f"[bold red]⚠️ {msg}[/bold red]")
