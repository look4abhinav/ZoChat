"""Test cases for customer-facing queries against the seeded database."""

import sqlite3
import tempfile
from pathlib import Path

import pytest

from zochat.db import queries
from zochat.db.seed import BASE_TS, build_database


@pytest.fixture(scope="module")
def db_conn():
    """Sets up a temporary seeded database and yields the connection."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        db_path = Path(tmp.name)

    build_database(db_path, verbose=False)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    yield conn

    conn.close()
    db_path.unlink(missing_ok=True)


# -- "Who am I?" ---------------------------------------------------------


def test_find_customer_by_known_phone(db_conn) -> None:
    """'I'm calling from +919800000001' -- look up the customer."""
    row = queries.find_customer_by_phone(db_conn, "+919800000001")
    assert row is not None
    assert row["name"] == "Aarav Sharma"
    assert row["city"] == "Bengaluru"


def test_find_customer_by_unknown_phone_returns_none(db_conn) -> None:
    """An unrecognised phone number yields None."""
    assert queries.find_customer_by_phone(db_conn, "+919999999999") is None


# -- "What are my account details?" --------------------------------------


def test_customer_profile_returns_loyalty_points(db_conn) -> None:
    """'How many loyalty points do I have?'."""
    row = queries.customer_profile(db_conn, 1)
    assert row is not None
    assert row["name"] == "Aarav Sharma"
    assert row["loyalty_points"] == 420


def test_customer_profile_for_unknown_id_returns_none(db_conn) -> None:
    assert queries.customer_profile(db_conn, 999) is None


# -- "Where is my order?" ------------------------------------------------


def test_where_is_my_order_in_transit(db_conn) -> None:
    """Order #7 is picked up & in transit -- show rider contact + distance."""
    row = queries.where_is_my_order(db_conn, 7)
    assert row is not None
    assert row["order_status"] == "picked_up"
    assert row["delivery_status"] == "in_transit"
    assert row["distance_km"] == pytest.approx(2.1)
    assert row["rider_name"] == "Suresh Patil"
    assert row["rider_phone"] == "+919900000004"
    assert row["delivered_at"] is None


def test_where_is_my_order_delivered(db_conn) -> None:
    """Order #1 is already delivered -- show completion + rider."""
    row = queries.where_is_my_order(db_conn, 1)
    assert row is not None
    assert row["order_status"] == "delivered"
    assert row["delivery_status"] == "delivered"
    assert row["rider_name"] == "Manoj Kumar"
    assert row["delivered_at"] is not None


def test_where_is_my_order_cancelled_has_no_delivery(db_conn) -> None:
    """Order #5 was cancelled before dispatch -- no delivery / rider."""
    row = queries.where_is_my_order(db_conn, 5)
    assert row is not None
    assert row["order_status"] == "cancelled"
    assert row["delivery_status"] is None
    assert row["rider_name"] is None


def test_where_is_my_order_unknown_id_returns_none(db_conn) -> None:
    assert queries.where_is_my_order(db_conn, 999) is None


# -- "When will I get my refund?" ----------------------------------------


def test_refund_status_processed(db_conn) -> None:
    """Order #5 was cancelled & refunded -- refund is fully processed."""
    refunds = queries.refund_status(db_conn, 5)
    assert len(refunds) == 1
    r = refunds[0]
    assert r["status"] == "processed"
    assert r["amount"] == 320.0
    assert r["processed_at"] is not None
    assert "cancelled" in r["reason"].lower()


def test_refund_status_initiated_has_no_processed_at(db_conn) -> None:
    """Order #1 has a late-delivery refund that's only initiated."""
    refunds = queries.refund_status(db_conn, 1)
    assert len(refunds) == 1
    r = refunds[0]
    assert r["status"] == "initiated"
    assert r["amount"] == 100.0
    assert r["processed_at"] is None
    assert r["payment_method"] == "upi"


def test_refund_status_returns_empty_when_no_refund(db_conn) -> None:
    """Order #2 has no refund."""
    assert queries.refund_status(db_conn, 2) == []


# -- "Is my payment successful?" -----------------------------------------


def test_payment_status_success(db_conn) -> None:
    """Order #1 paid via UPI successfully -- txn id present."""
    row = queries.payment_status(db_conn, 1)
    assert row is not None
    assert row["status"] == "success"
    assert row["method"] == "upi"
    assert row["gateway"] == "razorpay"
    assert row["transaction_id"] == "rp_txn_100001"


def test_payment_status_pending_for_preparing_order(db_conn) -> None:
    """Order #8 is still preparing -- its card payment is pending."""
    row = queries.payment_status(db_conn, 8)
    assert row is not None
    assert row["status"] == "pending"
    assert row["method"] == "card"
    assert row["paid_at"] is None


# -- "What are my recent orders?" ----------------------------------------


def test_recent_orders_newest_first(db_conn) -> None:
    """Customer #1 has two orders; the newer one (#6) should be listed first."""
    rows = queries.recent_orders(db_conn, 1)
    assert len(rows) == 2
    assert rows[0]["id"] == 6
    assert rows[1]["id"] == 1
    assert {r["status"] for r in rows} == {"delivered"}


def test_recent_orders_respects_limit(db_conn) -> None:
    rows = queries.recent_orders(db_conn, 1, limit=1)
    assert len(rows) == 1
    assert rows[0]["id"] == 6


def test_recent_orders_for_customer_with_none(db_conn) -> None:
    """Customer with no orders gets an empty list."""
    assert queries.recent_orders(db_conn, 999) == []


# -- "What did I order in order #X?" -------------------------------------


def test_order_items_detail_lists_line_items(db_conn) -> None:
    """Order #1 = 2x Chicken Biryani + 1x Chicken 65."""
    rows = queries.order_items_detail(db_conn, 1)
    assert len(rows) == 2
    names = {r["name"] for r in rows}
    assert names == {"Chicken Biryani", "Chicken 65"}

    # Sort amounts to verify independently of exact order returned
    line_totals = sorted([r["line_total"] for r in rows])
    assert line_totals == sorted([560.0, 180.0])
    assert sum(r["quantity"] for r in rows) == 3


def test_order_items_detail_for_order_with_none(db_conn) -> None:
    assert queries.order_items_detail(db_conn, 999) == []


# -- "What's the status of my complaint?" --------------------------------


def test_my_support_tickets(db_conn) -> None:
    """Customer #5 has one open, high-priority delivery-delay ticket."""
    rows = queries.my_support_tickets(db_conn, 5)
    assert len(rows) == 1
    t = rows[0]
    assert t["id"] == 4
    assert t["status"] == "open"
    assert t["priority"] == "high"
    assert t["category"] == "delivery_delay"
    assert t["order_id"] == 7
    assert t["resolved_at"] is None


# -- "What coupons can I use?" -------------------------------------------


def test_active_coupons_excludes_expired_and_inactive(db_conn) -> None:
    """At the seed's reference time, 4 coupons are usable; EXPIRED25 is not."""
    rows = queries.active_coupons(db_conn, now=BASE_TS.isoformat(sep=" "))
    codes = {r["code"] for r in rows}
    assert len(rows) == 4
    assert "WELCOME50" in codes
    assert "HEALTHY20" in codes
    assert "FLAT60" in codes
    assert "WEEKEND100" in codes
    assert "EXPIRED25" not in codes


# -- "Which restaurants are available in my city?" -----------------------


def test_restaurants_in_city(db_conn) -> None:
    """Bengaluru has two active restaurants, sorted by rating desc."""
    rows = queries.restaurants_in_city(db_conn, "Bengaluru")
    names = {r["name"] for r in rows}
    assert names == {"Biryani Blues", "Green Bowl"}
    assert rows[0]["rating"] >= rows[1]["rating"]


def test_restaurants_in_city_excludes_inactive(db_conn) -> None:
    """Hyderabad's only restaurant (Sweet Tooth Bakery) is inactive -> []."""
    assert queries.restaurants_in_city(db_conn, "Hyderabad") == []


# -- "What's on the menu at restaurant X?" -------------------------------


def test_menu_for_restaurant_excludes_unavailable(db_conn) -> None:
    """Restaurant #6 has Choco Lava Cake (unavailable) + Cheesecake (available)."""
    rows = queries.menu_for_restaurant(db_conn, 6)
    assert len(rows) == 1
    assert rows[0]["name"] == "Cheesecake Slice"


def test_menu_for_restaurant_returns_all_available(db_conn) -> None:
    """Restaurant #1 has all 3 items available."""
    rows = queries.menu_for_restaurant(db_conn, 1)
    assert len(rows) == 3
    assert {r["name"] for r in rows} == {"Chicken Biryani", "Veg Biryani", "Chicken 65"}


# -- "Can I cancel my order?" --------------------------------------------


def test_can_cancel_order_when_preparing(db_conn) -> None:
    """Order #8 is still preparing -> cancellable."""
    ok, reason = queries.can_cancel_order(db_conn, 8)
    assert ok
    assert "preparing" in reason


def test_cannot_cancel_delivered_order(db_conn) -> None:
    """Order #1 is already delivered -> not cancellable."""
    ok, reason = queries.can_cancel_order(db_conn, 1)
    assert not ok
    assert "delivered" in reason


def test_cannot_cancel_picked_up_order(db_conn) -> None:
    """Order #7 has been picked up -> too late to cancel."""
    ok, _ = queries.can_cancel_order(db_conn, 7)
    assert not ok


def test_can_cancel_unknown_order(db_conn) -> None:
    ok, reason = queries.can_cancel_order(db_conn, 999)
    assert not ok
    assert reason == "order not found"
