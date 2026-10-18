"""Secondary agent: answers in-scope support questions from the database.

The agent's ``deps`` is a :class:`SupportDeps` (connection + session + request
metadata). Every customer-facing function in :mod:`zochat.db.queries` is exposed
as a tool that reads from that connection, so the model can only ever answer
from real data -- never from its own imagination. Tools also update the session's
structured identity when they identify a customer or order.
"""

from __future__ import annotations

from typing import Any

from pydantic_ai import Agent, RunContext
from pydantic_ai.models import Model
from pydantic_ai.output import PromptedOutput

from zochat.agent.models import SupportAnswer
from zochat.db import mutations, queries
from zochat.errors import ZoChatError
from zochat.session import SupportDeps

_SUPPORT_INSTRUCTIONS = """\
You are Zo's friendly customer-support assistant.

You may ONLY help with Zo food-delivery topics: orders, deliveries,
payments, refunds, coupons, support tickets, restaurants, menus, the
customer's account & loyalty points, and order cancellations. If a message
strays outside these topics, say you can only help with Zo support.

How to work:
1. If the session already identifies the customer (customer_id is set), do
   not ask for their phone again -- use that id.
2. Otherwise, if the customer has not identified themselves, first call
   `find_customer_by_phone` (ask for their registered phone number) or ask
   for their customer id / order id.
3. Prefer composite tools (`order_overview`, `customer_overview`) for broad
   "tell me about X" questions; use the atomic tools for narrow follow-ups.
4. Use the provided tools to look up their data from the database. Never
   guess or invent details -- every fact in your reply must come from a tool.
5. Independent lookups may be issued in the same turn; dependent ones
   sequentially. Never call a tool with an id you do not have -- ask first.
6. Reply in a warm, concise, human tone. Quote amounts, statuses and dates
   exactly as the tools return them.
7. If the tools return nothing or an error payload, set data_found=False,
   tell the customer no matching record was found, and suggest what to do
   next. Do not retry the same call with guessed arguments.
"""


def build_support_agent(
    model: Model | str | None = None,
) -> Agent[SupportDeps, SupportAnswer]:
    """Return the secondary support agent wired to the database tools.

    Args:
        model: A pydantic-ai model or ``None`` to set it later at call time.
    """
    agent: Agent[SupportDeps, SupportAnswer] = Agent(
        model=model,
        deps_type=SupportDeps,
        output_type=PromptedOutput(SupportAnswer),
        name="zochat-support",
        instructions=_SUPPORT_INSTRUCTIONS,
        # Tools share a single SQLite connection, so run them one at a time.
        max_concurrency=1,
        retries=3,
    )  # ty:ignore[invalid-assignment]

    @agent.tool
    def find_customer_by_phone(
        ctx: RunContext[SupportDeps], phone: str
    ) -> dict[str, Any] | None:
        """Look up a customer by registered phone number, e.g. '+919800000001'.

        Use this first to identify who is calling when only a phone is known.
        Updates the session identity on a match.
        """
        try:
            row = queries.find_customer_by_phone(ctx.deps.conn, phone)
        except Exception as exc:  # noqa: BLE001
            return {"error": "db.error", "message": str(exc)}
        if row:
            ctx.deps.session.customer_id = row["id"]
            ctx.deps.session.customer_name = row["name"]
            ctx.deps.session.phone = row["phone"]
        return row

    @agent.tool
    def customer_profile(
        ctx: RunContext[SupportDeps], customer_id: int
    ) -> dict[str, Any] | None:
        """Fetch a customer's account details and loyalty points by customer id."""
        try:
            return queries.customer_profile(ctx.deps.conn, customer_id)
        except Exception as exc:  # noqa: BLE001
            return {"error": "db.error", "message": str(exc)}

    @agent.tool
    def where_is_my_order(
        ctx: RunContext[SupportDeps], order_id: int
    ) -> dict[str, Any] | None:
        """Get live order + delivery status and rider contact for an order id."""
        try:
            row = queries.where_is_my_order(ctx.deps.conn, order_id)
        except Exception as exc:  # noqa: BLE001
            return {"error": "db.error", "message": str(exc)}
        if row is not None:
            ctx.deps.session.last_order_id = order_id
        return row

    @agent.tool
    def recent_orders(
        ctx: RunContext[SupportDeps], customer_id: int, limit: int = 5
    ) -> list[dict[str, Any]]:
        """List a customer's most recent orders, newest first."""
        try:
            return queries.recent_orders(ctx.deps.conn, customer_id, limit)
        except Exception as exc:  # noqa: BLE001
            return {"error": "db.error", "message": str(exc)}

    @agent.tool
    def order_items_detail(
        ctx: RunContext[SupportDeps], order_id: int
    ) -> list[dict[str, Any]]:
        """List the line items (dish, quantity, price) for a given order id."""
        try:
            return queries.order_items_detail(ctx.deps.conn, order_id)
        except Exception as exc:  # noqa: BLE001
            return {"error": "db.error", "message": str(exc)}

    @agent.tool
    def payment_status(
        ctx: RunContext[SupportDeps], order_id: int
    ) -> dict[str, Any] | None:
        """Check the payment status (success/failed/pending) for an order id."""
        try:
            return queries.payment_status(ctx.deps.conn, order_id)
        except Exception as exc:  # noqa: BLE001
            return {"error": "db.error", "message": str(exc)}

    @agent.tool
    def refund_status(
        ctx: RunContext[SupportDeps], order_id: int
    ) -> list[dict[str, Any]]:
        """Get every refund for an order with its status and dates."""
        try:
            return queries.refund_status(ctx.deps.conn, order_id)
        except Exception as exc:  # noqa: BLE001
            return {"error": "db.error", "message": str(exc)}

    @agent.tool
    def my_support_tickets(
        ctx: RunContext[SupportDeps], customer_id: int
    ) -> list[dict[str, Any]]:
        """List a customer's support tickets / complaints with their status."""
        try:
            rows = queries.my_support_tickets(ctx.deps.conn, customer_id)
        except Exception as exc:  # noqa: BLE001
            return {"error": "db.error", "message": str(exc)}
        if rows:
            ctx.deps.session.last_ticket_id = rows[0]["id"]
        return rows

    @agent.tool
    def active_coupons(ctx: RunContext[SupportDeps]) -> list[dict[str, Any]]:
        """List coupons the customer can use right now."""
        try:
            return queries.active_coupons(ctx.deps.conn)
        except Exception as exc:  # noqa: BLE001
            return {"error": "db.error", "message": str(exc)}

    @agent.tool
    def restaurants_in_city(
        ctx: RunContext[SupportDeps], city: str
    ) -> list[dict[str, Any]]:
        """List active restaurants available in a given city."""
        try:
            return queries.restaurants_in_city(ctx.deps.conn, city)
        except Exception as exc:  # noqa: BLE001
            return {"error": "db.error", "message": str(exc)}

    @agent.tool
    def menu_for_restaurant(
        ctx: RunContext[SupportDeps], restaurant_id: int
    ) -> list[dict[str, Any]]:
        """List the available menu items for a given restaurant id."""
        try:
            return queries.menu_for_restaurant(ctx.deps.conn, restaurant_id)
        except Exception as exc:  # noqa: BLE001
            return {"error": "db.error", "message": str(exc)}

    @agent.tool
    def can_cancel_order(ctx: RunContext[SupportDeps], order_id: int) -> dict[str, Any]:
        """Check whether an order can still be cancelled, and why or why not."""
        try:
            can_cancel, reason = queries.can_cancel_order(ctx.deps.conn, order_id)
        except Exception as exc:  # noqa: BLE001
            return {"error": "db.error", "message": str(exc)}
        return {"can_cancel": can_cancel, "reason": reason}

    @agent.tool
    def order_overview(
        ctx: RunContext[SupportDeps], order_id: int
    ) -> dict[str, Any] | None:
        """Composite overview of an order: header, items, payment, refunds, delivery."""
        try:
            return queries.order_overview(ctx.deps.conn, order_id)
        except Exception as exc:  # noqa: BLE001
            return {"error": "db.error", "message": str(exc)}

    @agent.tool
    def customer_overview(
        ctx: RunContext[SupportDeps], customer_id: int, order_limit: int = 5
    ) -> dict[str, Any] | None:
        """Composite overview of a customer: profile, recent orders, tickets."""
        try:
            return queries.customer_overview(ctx.deps.conn, customer_id, order_limit)
        except Exception as exc:  # noqa: BLE001
            return {"error": "db.error", "message": str(exc)}

    @agent.tool
    def validate_coupon(
        ctx: RunContext[SupportDeps], code: str, cart_total: float
    ) -> dict[str, Any]:
        """Validate a coupon against a cart total and compute the discount."""
        try:
            return queries.validate_coupon(ctx.deps.conn, code, cart_total)
        except Exception as exc:  # noqa: BLE001
            return {"error": "db.error", "message": str(exc)}

    @agent.tool
    def propose_cancel_order(
        ctx: RunContext[SupportDeps], order_id: int, reason: str | None = None
    ) -> dict[str, Any]:
        """Propose cancelling an order (preview only; requires execute_pending_action)."""
        try:
            p = mutations.propose_cancel_order(
                ctx.deps.conn,
                order_id=order_id,
                customer_id=ctx.deps.session.customer_id,
                reason=reason,
                request_id=ctx.deps.request_id,
            )
        except ZoChatError as exc:
            return {"error": exc.code, "message": exc.user_message}
        return {
            "token": p.token,
            "summary": p.summary,
            "risk": p.risk,
            "expires_at": p.expires_at.isoformat(),
        }

    @agent.tool
    def propose_create_ticket(
        ctx: RunContext[SupportDeps],
        category: str,
        description: str,
        order_id: int | None = None,
        priority: str = "medium",
    ) -> dict[str, Any]:
        """Propose creating a support ticket (preview only)."""
        try:
            p = mutations.propose_create_ticket(
                ctx.deps.conn,
                customer_id=ctx.deps.session.customer_id,
                category=category,
                description=description,
                order_id=order_id,
                priority=priority,
                request_id=ctx.deps.request_id,
            )
        except ZoChatError as exc:
            return {"error": exc.code, "message": exc.user_message}
        return {
            "token": p.token,
            "summary": p.summary,
            "risk": p.risk,
            "expires_at": p.expires_at.isoformat(),
        }

    @agent.tool
    def propose_resolve_ticket(
        ctx: RunContext[SupportDeps], ticket_id: int, resolution_note: str | None = None
    ) -> dict[str, Any]:
        """Propose resolving a support ticket (preview only)."""
        try:
            p = mutations.propose_resolve_ticket(
                ctx.deps.conn,
                ticket_id=ticket_id,
                customer_id=ctx.deps.session.customer_id,
                resolution_note=resolution_note,
                request_id=ctx.deps.request_id,
            )
        except ZoChatError as exc:
            return {"error": exc.code, "message": exc.user_message}
        return {
            "token": p.token,
            "summary": p.summary,
            "risk": p.risk,
            "expires_at": p.expires_at.isoformat(),
        }

    @agent.tool
    def propose_apply_coupon(
        ctx: RunContext[SupportDeps], order_id: int, coupon_code: str
    ) -> dict[str, Any]:
        """Propose applying a coupon to an order (preview only)."""
        try:
            p = mutations.propose_apply_coupon(
                ctx.deps.conn,
                order_id=order_id,
                code=coupon_code,
                customer_id=ctx.deps.session.customer_id,
                request_id=ctx.deps.request_id,
            )
        except ZoChatError as exc:
            return {"error": exc.code, "message": exc.user_message}
        return {
            "token": p.token,
            "summary": p.summary,
            "risk": p.risk,
            "expires_at": p.expires_at.isoformat(),
        }

    @agent.tool
    def propose_rate_order(
        ctx: RunContext[SupportDeps], order_id: int, rating: int
    ) -> dict[str, Any]:
        """Propose rating an order (preview only)."""
        try:
            p = mutations.propose_rate_order(
                ctx.deps.conn,
                order_id=order_id,
                rating=rating,
                customer_id=ctx.deps.session.customer_id,
                request_id=ctx.deps.request_id,
            )
        except ZoChatError as exc:
            return {"error": exc.code, "message": exc.user_message}
        return {
            "token": p.token,
            "summary": p.summary,
            "risk": p.risk,
            "expires_at": p.expires_at.isoformat(),
        }

    @agent.tool
    def execute_pending_action(
        ctx: RunContext[SupportDeps], token: str
    ) -> dict[str, Any]:
        """Execute a previously proposed action using its confirmation token."""
        try:
            r = mutations.execute_action(
                ctx.deps.conn, token=token, request_id=ctx.deps.request_id
            )
        except ZoChatError as exc:
            return {"error": exc.code, "message": exc.user_message}
        return {
            "ok": r.ok,
            "action": r.action,
            "status": r.status,
            "message": r.message,
            "target_id": r.target_id,
        }

    @agent.tool
    def cancel_pending_action(
        ctx: RunContext[SupportDeps], token: str
    ) -> dict[str, Any]:
        """Cancel/reject a previously proposed action."""
        ok = mutations.cancel_pending_action(ctx.deps.conn, token)
        return {"cancelled": ok}

    return agent
