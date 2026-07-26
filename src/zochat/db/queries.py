"""Customer-facing query functions for the ZoChat support agent.

Each function answers a question a customer might ask the chatbot, fetching
the relevant rows from the seeded SQLite database. Functions return plain
dicts / lists of dicts (JSON-serialisable) so an LLM agent can phrase them
as a natural-language reply.

These functions are the "tools" the agent will call. They are intentionally
pure data fetchers -- wording the answer is the agent's job.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime
from typing import Any


def _rows_to_dicts(rows: list[sqlite3.Row]) -> list[dict[str, Any]]:
    return [dict(r) for r in rows]


def _row_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    return dict(row) if row is not None else None


def find_customer_by_phone(
    conn: sqlite3.Connection, phone: str
) -> dict[str, Any] | None:
    """ "Who am I?" -- identify a customer from their registered phone number."""
    return _row_to_dict(
        conn.execute("SELECT * FROM customers WHERE phone = ?", (phone,)).fetchone()
    )


def customer_profile(
    conn: sqlite3.Connection, customer_id: int
) -> dict[str, Any] | None:
    """ "What are my account details and loyalty points?"."""
    return _row_to_dict(
        conn.execute(
            "SELECT id, name, email, phone, city, address, loyalty_points, registered_at FROM customers WHERE id = ?",
            (customer_id,),
        ).fetchone()
    )


def where_is_my_order(conn: sqlite3.Connection, order_id: int) -> dict[str, Any] | None:
    """ "Where is my order?" -- order status + live delivery + rider contact."""
    return _row_to_dict(
        conn.execute(
            """
        SELECT o.id, o.status AS order_status, o.placed_at, o.delivery_address,
               d.status AS delivery_status, d.distance_km,
               d.picked_up_at, d.delivered_at,
               dp.name AS rider_name, dp.phone AS rider_phone, dp.rating AS rider_rating
        FROM orders o
        LEFT JOIN deliveries d         ON d.order_id = o.id
        LEFT JOIN delivery_partners dp ON dp.id = d.partner_id
        WHERE o.id = ?
    """,
            (order_id,),
        ).fetchone()
    )


def recent_orders(
    conn: sqlite3.Connection, customer_id: int, limit: int = 5
) -> list[dict[str, Any]]:
    """ "What are my recent orders?" -- newest first."""
    return _rows_to_dicts(
        conn.execute(
            """
        SELECT o.id, r.name AS restaurant, o.status, o.total_amount,
               o.payment_method, o.placed_at, o.delivered_at, o.rating
        FROM orders o
        JOIN restaurants r ON r.id = o.restaurant_id
        WHERE o.customer_id = ?
        ORDER BY o.placed_at DESC
        LIMIT ?
    """,
            (customer_id, limit),
        ).fetchall()
    )


def order_items_detail(conn: sqlite3.Connection, order_id: int) -> list[dict[str, Any]]:
    """ "What did I order in order #X?" -- line items with quantities & totals."""
    return _rows_to_dicts(
        conn.execute(
            """
        SELECT mi.name, oi.quantity, oi.unit_price,
               (oi.quantity * oi.unit_price) AS line_total,
               mi.is_veg, mi.category
        FROM order_items oi
        JOIN menu_items mi ON mi.id = oi.menu_item_id
        WHERE oi.order_id = ?
        ORDER BY oi.id
    """,
            (order_id,),
        ).fetchall()
    )


def payment_status(conn: sqlite3.Connection, order_id: int) -> dict[str, Any] | None:
    """ "Is my payment successful / did the money leave my account?"."""
    return _row_to_dict(
        conn.execute(
            """
        SELECT id, method, amount, status, gateway, transaction_id, paid_at
        FROM payments WHERE order_id = ?
    """,
            (order_id,),
        ).fetchone()
    )


def refund_status(conn: sqlite3.Connection, order_id: int) -> list[dict[str, Any]]:
    """ "When will I get my refund?" -- all refunds for an order with dates.

    Interpretation guide for the agent:
      status='processed'  -> already done; see processed_at
      status='approved'   -> approved, pending payout (typically 3-5 business days)
      status='initiated'  -> just raised, awaiting approval
      status='rejected'   -> will not be paid (see reason)
    """
    return _rows_to_dicts(
        conn.execute(
            """
        SELECT rf.id, rf.amount, rf.reason, rf.status,
               rf.requested_at, rf.processed_at,
               p.method AS payment_method, p.gateway
        FROM refunds rf
        JOIN payments p ON p.id = rf.payment_id
        WHERE rf.order_id = ?
        ORDER BY rf.requested_at
    """,
            (order_id,),
        ).fetchall()
    )


def my_support_tickets(
    conn: sqlite3.Connection, customer_id: int
) -> list[dict[str, Any]]:
    """ "What's the status of my complaint / ticket?"."""
    return _rows_to_dicts(
        conn.execute(
            """
        SELECT id, order_id, category, priority, status, description,
               created_at, resolved_at
        FROM support_tickets
        WHERE customer_id = ?
        ORDER BY created_at DESC
    """,
            (customer_id,),
        ).fetchall()
    )


def active_coupons(
    conn: sqlite3.Connection, now: str | None = None
) -> list[dict[str, Any]]:
    """ "What coupons can I use right now?".

    `now` (ISO timestamp) is optional so callers can pin a reference time for
    deterministic behaviour; defaults to the current wall clock.
    """
    now = now or datetime.now().isoformat(sep=" ")
    return _rows_to_dicts(
        conn.execute(
            """
        SELECT code, description, discount_type, discount_value,
               max_discount, min_order_value, expires_on
        FROM coupons
        WHERE is_active = 1 AND expires_on > ?
        ORDER BY expires_on
    """,
            (now,),
        ).fetchall()
    )


def restaurants_in_city(conn: sqlite3.Connection, city: str) -> list[dict[str, Any]]:
    """ "Which restaurants are available in my city?" -- only active ones."""
    return _rows_to_dicts(
        conn.execute(
            """
        SELECT id, name, cuisine, rating, avg_prep_time_min
        FROM restaurants
        WHERE city = ? AND is_active = 1
        ORDER BY rating DESC
    """,
            (city,),
        ).fetchall()
    )


def menu_for_restaurant(
    conn: sqlite3.Connection, restaurant_id: int
) -> list[dict[str, Any]]:
    """ "What's on the menu at restaurant X?" -- only currently available items."""
    return _rows_to_dicts(
        conn.execute(
            """
        SELECT name, description, category, price, is_veg
        FROM menu_items
        WHERE restaurant_id = ? AND is_available = 1
        ORDER BY category, price
    """,
            (restaurant_id,),
        ).fetchall()
    )


def can_cancel_order(conn: sqlite3.Connection, order_id: int) -> tuple[bool, str]:
    """ "Can I cancel my order?" -- returns (can_cancel, reason).

    An order can be cancelled only before the rider picks it up, i.e. while
    its status is still 'placed' or 'preparing'.
    """
    row = conn.execute("SELECT status FROM orders WHERE id = ?", (order_id,)).fetchone()
    if row is None:
        return (False, "order not found")
    status = row["status"]
    if status in ("placed", "preparing"):
        return (True, f"order is currently {status} and can be cancelled")
    return (False, f"order is already {status} and cannot be cancelled")


__all__ = [
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
]
