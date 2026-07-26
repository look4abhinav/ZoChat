"""Tests for the two-agent ZoChat support flow."""

import sqlite3
import tempfile
from pathlib import Path

import pytest
from pydantic_ai.models.test import TestModel

from zochat.agent.chat import DECLINE_REPLY, chat, run
from zochat.agent.classifier import build_classifier_agent
from zochat.agent.models import ChatReply, QuestionClassification, SupportAnswer
from zochat.agent.support import build_support_agent
from zochat.db.seed import build_database

EXPECTED_TOOLS = {
    "active_coupons",
    "can_cancel_order",
    "customer_profile",
    "find_customer_by_phone",
    "menu_for_restaurant",
    "my_support_tickets",
    "order_items_detail",
    "payment_status",
    "recent_orders",
    "refund_status",
    "restaurants_in_city",
    "where_is_my_order",
}


@pytest.fixture(scope="module")
def db_path():
    """Sets up a temporary seeded database and yields the path."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        path = Path(tmp.name)
    build_database(path, verbose=False)

    yield path

    path.unlink(missing_ok=True)


@pytest.fixture
def conn(db_path):
    """Provides a fresh connection for a test, automatically closing it afterward."""
    connection = sqlite3.connect(db_path, check_same_thread=False)
    connection.row_factory = sqlite3.Row

    yield connection

    connection.close()


# -- primary classifier --------------------------------------------------


@pytest.mark.asyncio
async def test_classifier_returns_related() -> None:
    """A support question is classified as related with a category."""
    clf = build_classifier_agent(
        model=TestModel(
            custom_output_text=('{"is_related": true, "category": "order", "reasoning": "asks about an order"}')
        )
    )
    out = (await clf.run("Where is my order 1?")).output
    assert isinstance(out, QuestionClassification)
    assert out.is_related
    assert out.category == "order"


@pytest.mark.asyncio
async def test_classifier_returns_unrelated() -> None:
    """An off-topic question is classified as unrelated with no category."""
    clf = build_classifier_agent(
        model=TestModel(custom_output_text=('{"is_related": false, "category": null, "reasoning": "weather question"}'))
    )
    out = (await clf.run("Will it rain tomorrow?")).output
    assert not out.is_related
    assert out.category is None


# -- secondary support agent wiring --------------------------------------


def test_support_agent_exposes_all_db_tools() -> None:
    """The support agent registers every customer-facing query as a tool."""
    agent = build_support_agent(model=TestModel())
    tool_names = set(agent._function_toolset.tools.keys())
    assert tool_names == EXPECTED_TOOLS


@pytest.mark.asyncio
async def test_support_agent_runs_all_tools_against_db(conn) -> None:
    """TestModel calls every tool; all must return JSON-serialisable data."""
    support = build_support_agent(
        model=TestModel(custom_output_text=('{"answer": "Here is your order.", "data_found": true}'))
    )
    result = await support.run("Where is my order 1?", deps=conn)
    assert isinstance(result.output, SupportAnswer)
    assert result.output.answer == "Here is your order."
    assert result.output.data_found


# -- orchestration -------------------------------------------------------


@pytest.mark.asyncio
async def test_run_related_invokes_support_agent(conn) -> None:
    """A related question is handed to the support agent and answered."""
    clf = build_classifier_agent(
        model=TestModel(
            custom_output_text=('{"is_related": true, "category": "refund", "reasoning": "asks about a refund"}')
        )
    )
    sup_model = TestModel(
        call_tools=[],
        custom_output_text=('{"answer": "Refund is processed.", "data_found": true}'),
    )
    support = build_support_agent(model=sup_model)

    reply = await run(clf, support, "When will I get my refund for order 5?", conn=conn)

    assert isinstance(reply, ChatReply)
    assert reply.answered
    assert reply.answer == "Refund is processed."
    assert reply.data_found
    assert reply.classification.category == "refund"
    assert sup_model.last_model_request_parameters is not None


@pytest.mark.asyncio
async def test_run_unrelated_declines_without_support(conn) -> None:
    """An unrelated question is declined and the support agent is never run."""
    clf = build_classifier_agent(
        model=TestModel(
            custom_output_text=('{"is_related": false, "category": null, "reasoning": "general knowledge question"}')
        )
    )
    sup_model = TestModel(custom_output_text=('{"answer": "should never be used", "data_found": true}'))
    support = build_support_agent(model=sup_model)

    reply = await run(clf, support, "Who won the football match?", conn=conn)

    assert not reply.answered
    assert reply.answer == DECLINE_REPLY
    assert reply.data_found
    assert reply.classification.category is None
    assert sup_model.last_model_request_parameters is None


@pytest.mark.asyncio
async def test_chat_opens_and_closes_its_own_connection(conn, monkeypatch) -> None:
    """chat() with no conn opens one from connect() and closes it after."""
    import importlib

    chat_module = importlib.import_module("zochat.agent.chat")

    # Use Pytest's monkeypatch fixture to cleanly override the connect method
    monkeypatch.setattr(chat_module, "connect", lambda: conn)

    reply = await chat(
        "Tell me a joke",
        model=TestModel(custom_output_text=('{"is_related": false, "category": null, "reasoning": "off-topic"}')),
    )
    assert not reply.answered

    with pytest.raises(sqlite3.ProgrammingError):
        conn.execute("SELECT 1")  # connection was closed by chat()


@pytest.mark.asyncio
async def test_chat_with_explicit_conn_leaves_it_open(conn) -> None:
    """chat() must not close a connection the caller supplied."""
    reply = await chat(
        "Where is my order?",
        conn=conn,
        model=TestModel(custom_output_text=('{"is_related": false, "category": null, "reasoning": "unrelated"}')),
    )
    assert not reply.answered
    conn.execute("SELECT 1")  # still open
