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
import time
from collections.abc import AsyncIterator
from typing import Any

from pydantic_ai import Agent
from pydantic_ai.models import Model

from zochat.agent.classifier import build_classifier_agent
from zochat.agent.models import (
    ChatReply,
    ChatStreamEvent,
    QuestionClassification,
    SupportAnswer,
)
from zochat.agent.support import build_support_agent
from zochat.config import get_groq_model
from zochat.db import connect
from zochat.errors import ZoChatError
from zochat.observability import RequestMetrics, new_request_id, request_context
from zochat.session import SessionState, SupportDeps
from zochat.validation import ChatRequest, validate_or_raise

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
    request_id: str | None = None,
    session: SessionState | None = None,
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
    rid = request_id or new_request_id()
    metrics = RequestMetrics(request_id=rid)
    started = time.perf_counter()
    classification = None
    if session is None:
        session = SessionState(
            message_history=list(message_history) if message_history else []
        )
    elif message_history is not None and not session.message_history:
        session.message_history = list(message_history)
    try:
        with request_context(rid):
            try:
                t0 = time.perf_counter()
                classification = (await classifier.run(question)).output
                metrics.classifier_ms = (time.perf_counter() - t0) * 1000.0

                if not classification.is_related:
                    session.touch()
                    return ChatReply(
                        answered=False,
                        answer=DECLINE_REPLY,
                        classification=classification,
                        history=list(session.message_history)
                        if session.message_history
                        else (list(message_history) if message_history else None),
                        request_id=rid,
                        latency_ms=(time.perf_counter() - started) * 1000.0,
                        error=None,
                        session=session,
                    )

                t1 = time.perf_counter()
                deps = SupportDeps(
                    conn=conn, session=session, request_id=rid, metrics=metrics
                )
                result = await support.run(
                    question, deps=deps, message_history=session.message_history or None
                )
                metrics.support_ms = (time.perf_counter() - t1) * 1000.0
                usage = getattr(result, "usage", None)
                if callable(usage):
                    try:
                        usage = usage()
                    except Exception:  # noqa: BLE001
                        usage = None
                usage_dict = None
                if usage is not None:
                    usage_dict = {
                        "prompt_tokens": getattr(usage, "request_tokens", 0)
                        or getattr(usage, "input_tokens", 0)
                        or 0,
                        "completion_tokens": getattr(usage, "response_tokens", 0)
                        or getattr(usage, "output_tokens", 0)
                        or 0,
                        "total_tokens": getattr(usage, "total_tokens", 0) or 0,
                    }
                session.message_history = result.all_messages()
                session.touch()
                return ChatReply(
                    answered=True,
                    answer=result.output.answer,
                    data_found=result.output.data_found,
                    classification=classification,
                    history=session.message_history,
                    request_id=rid,
                    latency_ms=(time.perf_counter() - started) * 1000.0,
                    usage=usage_dict,
                    session=session,
                )
            except ZoChatError as exc:
                metrics.error_code = exc.code
                return ChatReply(
                    answered=False,
                    answer=exc.user_message,
                    classification=classification
                    if classification is not None
                    else QuestionClassification(
                        is_related=False, category=None, reasoning="error"
                    ),
                    data_found=False,
                    request_id=rid,
                    latency_ms=(time.perf_counter() - started) * 1000.0,
                    error=exc.to_info(),
                    history=list(session.message_history)
                    if session.message_history
                    else None,
                    session=session,
                )
            except Exception as exc:  # noqa: BLE001
                from zochat.errors import DatabaseError

                err = DatabaseError(str(exc))
                metrics.error_code = err.code
                return ChatReply(
                    answered=False,
                    answer=err.user_message,
                    classification=QuestionClassification(
                        is_related=False, category=None, reasoning="error"
                    ),
                    data_found=False,
                    request_id=rid,
                    latency_ms=(time.perf_counter() - started) * 1000.0,
                    error=err.to_info(),
                    history=list(session.message_history)
                    if session.message_history
                    else None,
                    session=session,
                )
    finally:
        metrics.finish()
        if owns_conn:
            conn.close()


async def chat(
    question: str,
    *,
    conn: sqlite3.Connection | None = None,
    model: Model | str | None = None,
    message_history: list[Any] | None = None,
    request_id: str | None = None,
    session: SessionState | None = None,
) -> ChatReply:
    """Convenience wrapper that builds fresh agents and runs the flow.

    Args:
        question: The customer's message.
        conn: An open SQLite connection. If ``None``, one is opened (and
            closed) automatically.
        model: A pydantic-ai model for both agents, e.g.
            ``"groq:qwen/qwen3.8-27b"``. If ``None``, the default
            Groq ``qwen/qwen3.8-27b`` model (from
            :func:`zochat.config.get_groq_model`) is used, with
            ``GROQ_API_KEY`` / ``GROQ_BASE_URL`` loaded from ``.env``.
        message_history: Prior pydantic-ai messages to continue the
            conversation from; ``None`` starts a fresh turn. The reply's
            :attr:`ChatReply.history` carries the updated history for the
            next call.
    """
    validate_or_raise({"question": question}, ChatRequest)
    if model is None:
        model = get_groq_model()
    classifier = build_classifier_agent(model=model)
    support = build_support_agent(model=model)
    return await run(
        classifier,
        support,
        question,
        conn=conn,
        message_history=message_history,
        request_id=request_id,
        session=session,
    )


async def chat_stream(
    question: str,
    *,
    conn: sqlite3.Connection | None = None,
    model: Model | str | None = None,
    message_history: list[Any] | None = None,
    request_id: str | None = None,
    session: SessionState | None = None,
) -> AsyncIterator[ChatStreamEvent]:
    """Stream a two-agent turn, yielding :class:`ChatStreamEvent`s.

    Falls back to a single ``final`` event if streaming the structured output
    fails mid-way.
    """
    validate_or_raise({"question": question}, ChatRequest)
    if model is None:
        model = get_groq_model()
    classifier = build_classifier_agent(model=model)
    support = build_support_agent(model=model)

    owns_conn = conn is None
    if conn is None:
        conn = connect()
    rid = request_id or new_request_id()
    started = time.perf_counter()
    if session is None:
        session = SessionState(
            message_history=list(message_history) if message_history else []
        )
    elif message_history is not None and not session.message_history:
        session.message_history = list(message_history)

    try:
        with request_context(rid):
            classification = (await classifier.run(question)).output
            yield ChatStreamEvent(
                kind="classification", request_id=rid, classification=classification
            )

            if not classification.is_related:
                session.touch()
                reply = ChatReply(
                    answered=False,
                    answer=DECLINE_REPLY,
                    classification=classification,
                    history=list(session.message_history)
                    if session.message_history
                    else None,
                    request_id=rid,
                    latency_ms=(time.perf_counter() - started) * 1000.0,
                    session=session,
                )
                yield ChatStreamEvent(kind="final", request_id=rid, reply=reply)
                return

            deps = SupportDeps(
                conn=conn,
                session=session,
                request_id=rid,
                metrics=RequestMetrics(request_id=rid),
            )
            hist = session.message_history or None
            try:
                async with support.run_stream(
                    question, deps=deps, message_history=hist
                ) as result:
                    last = ""
                    async for partial in result.stream_output(debounce_by=0.05):
                        ans = getattr(partial, "answer", None)
                        if isinstance(ans, str) and ans != last:
                            delta = ans.removeprefix(last)
                            if delta:
                                yield ChatStreamEvent(
                                    kind="answer_delta", request_id=rid, text=delta
                                )
                            last = ans
                    final_output = await result.get_output()
                    session.message_history = result.all_messages()
                    session.touch()
                    reply = ChatReply(
                        answered=True,
                        answer=final_output.answer,
                        data_found=final_output.data_found,
                        classification=classification,
                        history=session.message_history,
                        request_id=rid,
                        latency_ms=(time.perf_counter() - started) * 1000.0,
                        session=session,
                    )
                    yield ChatStreamEvent(kind="final", request_id=rid, reply=reply)
            except Exception:  # noqa: BLE001
                # Fallback to non-streaming run.
                result = await support.run(question, deps=deps, message_history=hist)
                session.message_history = result.all_messages()
                session.touch()
                reply = ChatReply(
                    answered=True,
                    answer=result.output.answer,
                    data_found=result.output.data_found,
                    classification=classification,
                    history=session.message_history,
                    request_id=rid,
                    latency_ms=(time.perf_counter() - started) * 1000.0,
                    session=session,
                )
                yield ChatStreamEvent(kind="final", request_id=rid, reply=reply)
    except Exception as exc:  # noqa: BLE001
        from zochat.errors import DatabaseError

        err = DatabaseError(str(exc))
        yield ChatStreamEvent(kind="error", request_id=rid, text=err.user_message)
        session.touch()
        reply = ChatReply(
            answered=False,
            answer=err.user_message,
            classification=QuestionClassification(
                is_related=False, category=None, reasoning="error"
            ),
            data_found=False,
            request_id=rid,
            latency_ms=(time.perf_counter() - started) * 1000.0,
            error=err.to_info(),
            session=session,
        )
        yield ChatStreamEvent(kind="final", request_id=rid, reply=reply)
    finally:
        if owns_conn:
            conn.close()
