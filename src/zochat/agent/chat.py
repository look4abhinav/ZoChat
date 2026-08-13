"""Orchestrates the two-agent Zochat support flow.

1. A primary *classifier* agent decides whether the customer's question is
   in scope for the Zo support bot.
2. If the question is UNRELATED, the bot declines politely -- the support
   agent is never run.
3. If RELATED, a secondary *support* agent answers using the SQLite tools,
   with the database connection passed as its deps.
"""

from __future__ import annotations

import sqlite3
from typing import Any

from pydantic_ai import Agent
from pydantic_ai.models import Model

from zochat.agent.classifier import build_classifier_agent
from zochat.agent.models import ChatReply, QuestionClassification, SupportAnswer
from zochat.agent.support import build_support_agent
from zochat.config import get_opencode_model
from zochat.db import connect

DECLINE_REPLY = (
    "Sorry, I can only help with Zo orders, deliveries, payments, refunds, "
    "coupons, support tickets, restaurants and your account. "
    "For anything else, please contact our general help line."
)


async def run(
    classifier: Agent[Any, QuestionClassification],
    support: Agent[sqlite3.Connection, SupportAnswer],
    question: str,
    *,
    conn: sqlite3.Connection | None = None,
    message_history: list[Any] | None = None,
) -> ChatReply:
    """Run the two-agent flow with pre-built agents.

    This is the testable core: tests inject agents backed by
    :class:`pydantic_ai.models.test.TestModel` so no LLM API key is needed.

    Conversation memory is threaded through the *support* agent only. The
    classifier is a stateless gatekeeper and always sees just the current
    question — declines leave ``message_history`` untouched so a subsequent
    in-scope follow-up still has the prior support exchanges as context.

    Args:
        message_history: Prior pydantic-ai message list to continue from
            (e.g. :attr:`AgentRunResult.all_messages`). Forwarded to the
            support agent; ``None`` starts a fresh conversation.
    """
    owns_conn = conn is None
    if conn is None:
        conn = connect()
    try:
        classification = (await classifier.run(question)).output

        if not classification.is_related:
            return ChatReply(
                answered=False,
                answer=DECLINE_REPLY,
                classification=classification,
                history=list(message_history) if message_history else None,
            )

        result = await support.run(question, deps=conn, message_history=message_history)
        return ChatReply(
            answered=True,
            answer=result.output.answer,
            data_found=result.output.data_found,
            classification=classification,
            history=result.all_messages(),
        )
    finally:
        if owns_conn:
            conn.close()


async def chat(
    question: str,
    *,
    conn: sqlite3.Connection | None = None,
    model: Model | str | None = None,
    message_history: list[Any] | None = None,
) -> ChatReply:
    """Convenience wrapper that builds fresh agents and runs the flow.

    Args:
        question: The customer's message.
        conn: An open SQLite connection. If ``None``, one is opened (and
            closed) automatically.
        model: A pydantic-ai model for both agents, e.g.
            ``"opencode:deepseek-v4-pro"``. If ``None``, the default
            Opencode Go ``deepseek-v4-flash`` model (from
            :func:`zochat.config.get_opencode_model`) is used, with
            ``OPENCODE_API_KEY`` / ``OPENCODE_BASE_URL`` loaded from ``.env``.
        message_history: Prior pydantic-ai messages to continue the
            conversation from; ``None`` starts a fresh turn. The reply's
            :attr:`ChatReply.history` carries the updated history for the
            next call.
    """
    if model is None:
        model = get_opencode_model()
    classifier = build_classifier_agent(model=model)
    support = build_support_agent(model=model)
    return await run(classifier, support, question, conn=conn, message_history=message_history)
