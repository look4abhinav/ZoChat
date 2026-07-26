"""Secondary agent: answers in-scope support questions from the database.

The agent's ``deps`` is a :class:`sqlite3.Connection` (provided by the
orchestrator). Every customer-facing function in :mod:`zochat.db.queries` is
exposed as a tool that reads from that connection, so the model can only ever
answer from real data -- never from its own imagination.
"""

from __future__ import annotations

import sqlite3
from typing import Any

from pydantic_ai import Agent, RunContext
from pydantic_ai.models import Model
from pydantic_ai.output import PromptedOutput

from zochat.agent.models import SupportAnswer
from zochat.db import queries

_SUPPORT_INSTRUCTIONS = """\
You are Zo's friendly customer-support assistant.

You may ONLY help with Zo food-delivery topics: orders, deliveries,
payments, refunds, coupons, support tickets, restaurants, menus, the
customer's account & loyalty points, and order cancellations. If a message
strays outside these topics, say you can only help with Zo support.

How to work:
1. If the customer has not identified themselves, first call
   `find_customer_by_phone` (ask for their registered phone number) or ask
   for their customer id / order id.
2. Use the provided tools to look up their data from the database. Never
   guess or invent details -- every fact in your reply must come from a tool.
3. Reply in a warm, concise, human tone. Quote amounts, statuses and dates
   exactly as the tools return them.
4. If the tools return nothing, set data_found=False, tell the customer no
   matching record was found, and suggest what to do next.
"""


def build_support_agent(
    model: Model | str | None = None,
) -> Agent[sqlite3.Connection, SupportAnswer]:
    """Return the secondary support agent wired to the database tools.

    Args:
        model: A pydantic-ai model or ``None`` to set it later at call time.
    """
    agent: Agent[sqlite3.Connection, SupportAnswer] = Agent(
        model=model,
        deps_type=sqlite3.Connection,
        output_type=PromptedOutput(SupportAnswer),
        name="zochat-support",
        instructions=_SUPPORT_INSTRUCTIONS,
        # Tools share a single SQLite connection, so run them one at a time.
        max_concurrency=1,
        retries=3,
    )  # ty:ignore[invalid-assignment]

    @agent.tool
    def find_customer_by_phone(
        ctx: RunContext[sqlite3.Connection], phone: str
    ) -> dict[str, Any] | None:
        """Look up a customer by registered phone number, e.g. '+919800000001'.

        Use this first to identify who is calling when only a phone is known.
        """
        return queries.find_customer_by_phone(ctx.deps, phone)

    @agent.tool
    def customer_profile(
        ctx: RunContext[sqlite3.Connection], customer_id: int
    ) -> dict[str, Any] | None:
        """Fetch a customer's account details and loyalty points by customer id."""
        return queries.customer_profile(ctx.deps, customer_id)

    @agent.tool
    def where_is_my_order(
        ctx: RunContext[sqlite3.Connection], order_id: int
    ) -> dict[str, Any] | None:
        """Get live order + delivery status and rider contact for an order id."""
        return queries.where_is_my_order(ctx.deps, order_id)

    @agent.tool
    def recent_orders(
        ctx: RunContext[sqlite3.Connection], customer_id: int, limit: int = 5
    ) -> list[dict[str, Any]]:
        """List a customer's most recent orders, newest first."""
        return queries.recent_orders(ctx.deps, customer_id, limit)

    @agent.tool
    def order_items_detail(
        ctx: RunContext[sqlite3.Connection], order_id: int
    ) -> list[dict[str, Any]]:
        """List the line items (dish, quantity, price) for a given order id."""
        return queries.order_items_detail(ctx.deps, order_id)

    @agent.tool
    def payment_status(
        ctx: RunContext[sqlite3.Connection], order_id: int
    ) -> dict[str, Any] | None:
        """Check the payment status (success/failed/pending) for an order id."""
        return queries.payment_status(ctx.deps, order_id)

    @agent.tool
    def refund_status(
        ctx: RunContext[sqlite3.Connection], order_id: int
    ) -> list[dict[str, Any]]:
        """Get every refund for an order with its status and dates."""
        return queries.refund_status(ctx.deps, order_id)

    @agent.tool
    def my_support_tickets(
        ctx: RunContext[sqlite3.Connection], customer_id: int
    ) -> list[dict[str, Any]]:
        """List a customer's support tickets / complaints with their status."""
        return queries.my_support_tickets(ctx.deps, customer_id)

    @agent.tool
    def active_coupons(ctx: RunContext[sqlite3.Connection]) -> list[dict[str, Any]]:
        """List coupons the customer can use right now."""
        return queries.active_coupons(ctx.deps)

    @agent.tool
    def restaurants_in_city(
        ctx: RunContext[sqlite3.Connection], city: str
    ) -> list[dict[str, Any]]:
        """List active restaurants available in a given city."""
        return queries.restaurants_in_city(ctx.deps, city)

    @agent.tool
    def menu_for_restaurant(
        ctx: RunContext[sqlite3.Connection], restaurant_id: int
    ) -> list[dict[str, Any]]:
        """List the available menu items for a given restaurant id."""
        return queries.menu_for_restaurant(ctx.deps, restaurant_id)

    @agent.tool
    def can_cancel_order(
        ctx: RunContext[sqlite3.Connection], order_id: int
    ) -> dict[str, Any]:
        """Check whether an order can still be cancelled, and why or why not."""
        can_cancel, reason = queries.can_cancel_order(ctx.deps, order_id)
        return {"can_cancel": can_cancel, "reason": reason}

    return agent
