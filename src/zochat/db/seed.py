"""Create and populate the ZoChat SQLite database with dummy data.

Run from the project root:

    python -m zochat.db.seed            # (re)create DB at default path
    python -m zochat.db.seed --path /tmp/other.db

The script is idempotent: it drops any existing tables before recreating
them, so re-running always yields a clean, deterministic dataset.
"""

from __future__ import annotations

import argparse
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

DEFAULT_DB_PATH = Path(__file__).resolve().parent.parent / "data" / "ZoDB.db"
SCHEMA_PATH = Path(__file__).resolve().parent / "schema.sql"

# Fixed "now" makes the seeded dataset deterministic across runs.
BASE_TS = datetime(2026, 7, 21, 12, 0, 0)


def _ts(days_ago: int, hours_ago: int = 0) -> str:
    return (BASE_TS - timedelta(days=days_ago, hours=hours_ago)).isoformat(sep=" ")


# ---------------------------------------------------------------------------
# Dummy data
# ---------------------------------------------------------------------------

CUSTOMERS = [
    (
        1,
        "Aarav Sharma",
        "aarav.sharma@example.com",
        "+919800000001",
        "Bengaluru",
        "12, MG Road, Indiranagar, Bengaluru 560038",
        420,
        _ts(220),
    ),
    (
        2,
        "Diya Verma",
        "diya.verma@example.com",
        "+919800000002",
        "Mumbai",
        "Flat 4B, Sea Breeze, Bandra West, Mumbai 400050",
        150,
        _ts(180),
    ),
    (
        3,
        "Kabir Singh",
        "kabir.singh@example.com",
        "+919800000003",
        "Delhi",
        "23, Lajpat Nagar II, New Delhi 110024",
        75,
        _ts(120),
    ),
    (
        4,
        "Ananya Iyer",
        "ananya.iyer@example.com",
        "+919800000004",
        "Bengaluru",
        "7, Koramangala 5th Block, Bengaluru 560095",
        610,
        _ts(300),
    ),
    (
        5,
        "Rohan Mehta",
        "rohan.mehta@example.com",
        "+919800000005",
        "Pune",
        "44, FC Road, Shivajinagar, Pune 411016",
        0,
        _ts(15),
    ),
    (
        6,
        "Sara Khan",
        "sara.khan@example.com",
        "+919800000006",
        "Hyderabad",
        "10, Banjara Hills Road 12, Hyderabad 500034",
        235,
        _ts(95),
    ),
]

RESTAURANTS = [
    (1, "Biryani Blues", "Hyderabadi", "Bengaluru", 4.5, 30, 1, _ts(400)),
    (2, "Pasta La Vista", "Italian", "Mumbai", 4.3, 25, 1, _ts(380)),
    (3, "Green Bowl", "Salads", "Bengaluru", 4.7, 15, 1, _ts(260)),
    (4, "Spice Junction", "North Indian", "Delhi", 4.1, 35, 1, _ts(420)),
    (5, "Rolls & Wraps Co.", "Fast Food", "Pune", 3.9, 20, 1, _ts(150)),
    (6, "Sweet Tooth Bakery", "Desserts", "Hyderabad", 4.8, 10, 0, _ts(120)),
]

MENU_ITEMS = [
    # restaurant_id, name, description, category, price, is_veg, is_available
    (
        1,
        "Chicken Biryani",
        "Slow-cooked basmati with chicken, saffron & herbs",
        "Main Course",
        280.0,
        0,
        1,
    ),
    (
        1,
        "Veg Biryani",
        "Fragrant basmati with mixed vegetables & spices",
        "Main Course",
        220.0,
        1,
        1,
    ),
    (1, "Chicken 65", "Spicy deep-fried chicken bites", "Starter", 180.0, 0, 1),
    (2, "Margherita Pizza", "Classic cheese & basil pizza", "Pizza", 320.0, 1, 1),
    (2, "Penne Alfredo", "Pasta in creamy white sauce", "Pasta", 290.0, 1, 1),
    (2, "Garlic Bread", "Toasted garlic bread with herbs", "Sides", 120.0, 1, 1),
    (3, "Garden Salad", "Fresh greens with vinaigrette", "Salads", 180.0, 1, 1),
    (3, "Quinoa Bowl", "Quinoa, roasted veggies & hummus", "Salads", 240.0, 1, 1),
    (
        4,
        "Paneer Butter Masala",
        "Cottage cheese in rich tomato gravy",
        "Main Course",
        260.0,
        1,
        1,
    ),
    (4, "Butter Naan", "Soft tandoor-baked bread", "Bread", 50.0, 1, 1),
    (
        4,
        "Dal Makhani",
        "Creamy black lentils slow-cooked overnight",
        "Main Course",
        220.0,
        1,
        1,
    ),
    (5, "Chicken Wrap", "Grilled chicken wrap with mint mayo", "Wraps", 160.0, 0, 1),
    (5, "Veg Roll", "Spiced potato roll with chutney", "Rolls", 120.0, 1, 1),
    (
        6,
        "Choco Lava Cake",
        "Warm chocolate cake with molten centre",
        "Dessert",
        140.0,
        1,
        0,
    ),
    (
        6,
        "Cheesecake Slice",
        "Classic New York-style cheesecake",
        "Dessert",
        180.0,
        1,
        1,
    ),
]

DELIVERY_PARTNERS = [
    (1, "Manoj Kumar", "+919900000001", "KA01AB1234", "Bengaluru", 4.7, 1, _ts(200)),
    (2, "Imran Sheikh", "+919900000002", "MH02CD5678", "Mumbai", 4.5, 1, _ts(190)),
    (3, "Vijay Rao", "+919900000003", "DL03EF9012", "Delhi", 4.2, 1, _ts(170)),
    (4, "Suresh Patil", "+919900000004", "MH04GH3456", "Pune", 4.6, 1, _ts(140)),
]

# order_id, customer_id, restaurant_id, partner_id, status, total, fee, method, placed_at(days_ago), delivered_at(days_ago or None), address, rating, coupon
ORDERS = [
    (
        1,
        1,
        1,
        1,
        "delivered",
        670.0,
        30.0,
        "upi",
        _ts(10),
        _ts(10, -1),
        "12, MG Road, Indiranagar, Bengaluru 560038",
        5,
        "WELCOME50",
    ),
    (
        2,
        2,
        2,
        2,
        "delivered",
        730.0,
        25.0,
        "card",
        _ts(9),
        _ts(9, -1),
        "Flat 4B, Sea Breeze, Bandra West, Mumbai 400050",
        4,
        None,
    ),
    (
        3,
        3,
        4,
        3,
        "delivered",
        530.0,
        20.0,
        "wallet",
        _ts(8),
        _ts(8, -1),
        "23, Lajpat Nagar II, New Delhi 110024",
        3,
        None,
    ),
    (
        4,
        4,
        3,
        1,
        "delivered",
        420.0,
        15.0,
        "upi",
        _ts(7),
        _ts(7, -1),
        "7, Koramangala 5th Block, Bengaluru 560095",
        5,
        "HEALTHY20",
    ),
    (
        5,
        6,
        6,
        None,
        "cancelled",
        320.0,
        0.0,
        "upi",
        _ts(5),
        None,
        "10, Banjara Hills Road 12, Hyderabad 500034",
        None,
        None,
    ),
    (
        6,
        1,
        1,
        1,
        "delivered",
        500.0,
        30.0,
        "cod",
        _ts(3),
        _ts(3, -1),
        "12, MG Road, Indiranagar, Bengaluru 560038",
        4,
        None,
    ),
    (
        7,
        5,
        5,
        4,
        "picked_up",
        280.0,
        20.0,
        "upi",
        _ts(0, 2),
        None,
        "44, FC Road, Shivajinagar, Pune 411016",
        None,
        None,
    ),
    (
        8,
        4,
        2,
        1,
        "preparing",
        440.0,
        25.0,
        "card",
        _ts(0, 1),
        None,
        "7, Koramangala 5th Block, Bengaluru 560095",
        None,
        None,
    ),
]

# order_id, menu_item_id, quantity, unit_price
ORDER_ITEMS = [
    (1, 1, 2, 280.0),  # 2x Chicken Biryani
    (1, 3, 1, 180.0),  # 1x Chicken 65  -> 740 + 30 fee ≈ 770 (coupon applied)
    (2, 4, 1, 320.0),  # Margherita Pizza
    (2, 6, 1, 120.0),  # Garlic Bread
    (2, 5, 1, 290.0),  # Penne Alfredo
    (3, 9, 1, 260.0),  # Paneer Butter Masala
    (3, 11, 1, 220.0),  # Dal Makhani
    (3, 10, 1, 50.0),  # Butter Naan
    (4, 7, 1, 180.0),  # Garden Salad
    (4, 8, 1, 240.0),  # Quinoa Bowl
    (5, 14, 2, 140.0),  # 2x Choco Lava Cake (cancelled)
    (6, 2, 2, 220.0),  # 2x Veg Biryani
    (6, 3, 1, 180.0),  # 1x Chicken 65 -> 620... (cod)
    (7, 12, 1, 160.0),  # Chicken Wrap
    (7, 13, 1, 120.0),  # Veg Roll
    (8, 4, 1, 320.0),  # Margherita Pizza
    (8, 6, 1, 120.0),  # Garlic Bread
]

# id, order_id, method, amount, status, gateway, transaction_id, paid_at
PAYMENTS = [
    (1, 1, "upi", 670.0, "success", "razorpay", "rp_txn_100001", _ts(10)),
    (2, 2, "card", 730.0, "success", "payu", "pu_txn_100002", _ts(9)),
    (3, 3, "wallet", 530.0, "success", "cashfree", "cf_txn_100003", _ts(8)),
    (4, 4, "upi", 420.0, "success", "razorpay", "rp_txn_100004", _ts(7)),
    (
        5,
        5,
        "upi",
        320.0,
        "success",
        "razorpay",
        "rp_txn_100005",
        _ts(5),
    ),  # cancelled order -> refunded
    (6, 6, "cod", 500.0, "success", "cod", None, None),  # collected at delivery
    (7, 7, "upi", 280.0, "success", "razorpay", "rp_txn_100007", _ts(0, 2)),
    (
        8,
        8,
        "card",
        440.0,
        "pending",
        "payu",
        "pu_txn_100008",
        None,
    ),  # preparing -> payment pending
]

# id, payment_id, order_id, amount, reason, status, requested_at, processed_at
REFUNDS = [
    (
        1,
        5,
        5,
        320.0,
        "Order cancelled by customer before preparation",
        "processed",
        _ts(5, 1),
        _ts(4),
    ),
    (
        2,
        3,
        3,
        180.0,
        "Food quality issue - dal makhani was stale",
        "approved",
        _ts(6),
        None,
    ),
    (
        3,
        1,
        1,
        100.0,
        "Late delivery - arrived 45 min after ETA",
        "initiated",
        _ts(9),
        None,
    ),
]

# id, order_id, partner_id, status, distance_km, picked_up_at, delivered_at
DELIVERIES = [
    (1, 1, 1, "delivered", 3.2, _ts(10, -1), _ts(10, -2)),
    (2, 2, 2, "delivered", 5.1, _ts(9, -1), _ts(9, -2)),
    (3, 3, 3, "delivered", 2.8, _ts(8, -1), _ts(8, -2)),
    (4, 4, 1, "delivered", 4.0, _ts(7, -1), _ts(7, -2)),
    (5, 6, 1, "delivered", 3.5, _ts(3, -1), _ts(3, -2)),
    (6, 7, 4, "in_transit", 2.1, _ts(0, 1), None),
]

# id, customer_id, order_id, category, priority, status, description, created_at, resolved_at
TICKETS = [
    (
        1,
        3,
        3,
        "food_quality",
        "high",
        "resolved",
        "Dal makhani appeared stale and smelled off. Requesting partial refund.",
        _ts(6),
        _ts(5),
    ),
    (
        2,
        1,
        1,
        "delivery_delay",
        "medium",
        "in_progress",
        "Order arrived 45 minutes after the promised ETA.",
        _ts(9),
        None,
    ),
    (
        3,
        6,
        5,
        "cancellation",
        "low",
        "resolved",
        "Cancelled order #5 before preparation; need refund confirmation.",
        _ts(5, 1),
        _ts(4),
    ),
    (
        4,
        5,
        7,
        "delivery_delay",
        "high",
        "open",
        "Order #7 is marked picked_up but rider hasn't moved in 20 minutes.",
        _ts(0, 1),
        None,
    ),
    (
        5,
        4,
        None,
        "payment",
        "medium",
        "open",
        "UPI payment for the latest order shows success but app still says pending.",
        _ts(0, 1),
        None,
    ),
    (
        6,
        2,
        2,
        "refund",
        "medium",
        "closed",
        "Requesting refund for missing garlic bread in order #2.",
        _ts(8),
        _ts(7),
    ),
]

# id, code, description, discount_type, discount_value, max_discount, min_order_value, expires_on, is_active
COUPONS = [
    (
        1,
        "WELCOME50",
        "50% off on first order (max Rs.100)",
        "percentage",
        50.0,
        100.0,
        200.0,
        _ts(-30),
        1,
    ),
    (
        2,
        "HEALTHY20",
        "20% off on salads & healthy bowls",
        "percentage",
        20.0,
        80.0,
        150.0,
        _ts(-15),
        1,
    ),
    (
        3,
        "FLAT60",
        "Flat Rs.60 off on orders above Rs.400",
        "flat",
        60.0,
        None,
        400.0,
        _ts(-10),
        1,
    ),
    (
        4,
        "WEEKEND100",
        "Rs.100 off on weekend orders above Rs.500",
        "flat",
        100.0,
        None,
        500.0,
        _ts(-5),
        1,
    ),
    (
        5,
        "EXPIRED25",
        "25% off (expired offer)",
        "percentage",
        25.0,
        75.0,
        200.0,
        _ts(20),
        0,
    ),
]


# ---------------------------------------------------------------------------
# Build / seed
# ---------------------------------------------------------------------------


def build_database(db_path: Path = DEFAULT_DB_PATH, verbose: bool = True) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    if db_path.exists():
        db_path.unlink()

    schema_sql = SCHEMA_PATH.read_text(encoding="utf-8")

    conn = sqlite3.connect(db_path)
    try:
        conn.executescript(schema_sql)
        _seed(conn)
        conn.commit()
    finally:
        conn.close()

    if verbose:
        print(f"Database created at: {db_path}")
        print(
            f"  tables: 11  | rows: {sum(len(x) for x in (CUSTOMERS, RESTAURANTS, MENU_ITEMS, DELIVERY_PARTNERS, ORDERS, ORDER_ITEMS, PAYMENTS, REFUNDS, DELIVERIES, TICKETS, COUPONS))}"
        )


def _seed(conn: sqlite3.Connection) -> None:
    conn.executemany(
        "INSERT INTO customers VALUES (?,?,?,?,?,?,?,?)",
        CUSTOMERS,
    )
    conn.executemany(
        "INSERT INTO restaurants VALUES (?,?,?,?,?,?,?,?)",
        RESTAURANTS,
    )
    conn.executemany(
        "INSERT INTO menu_items (restaurant_id, name, description, category, price, is_veg, is_available) VALUES (?,?,?,?,?,?,?)",
        MENU_ITEMS,
    )
    # Re-query to assign menu item ids (auto-incremented) to keep inserts simple.
    cur = conn.execute("SELECT id, restaurant_id, name FROM menu_items ORDER BY id")
    name_to_id = {(r[1], r[2]): r[0] for r in cur.fetchall()}

    conn.executemany(
        "INSERT INTO delivery_partners VALUES (?,?,?,?,?,?,?,?)",
        DELIVERY_PARTNERS,
    )
    conn.executemany(
        "INSERT INTO orders VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        ORDERS,
    )
    # Resolve menu_item names in ORDER_ITEMS to their auto-incremented ids.
    resolved_items = []
    for order_id, menu_item_id_hint, qty, price in ORDER_ITEMS:
        # menu_item_id_hint in the tuple is the human-friendly row number from
        # MENU_ITEMS; map it to the actual autoincrement id.
        hint_row = MENU_ITEMS[menu_item_id_hint - 1]
        actual_id = name_to_id[(hint_row[0], hint_row[1])]
        resolved_items.append((None, order_id, actual_id, qty, price))
    conn.executemany(
        "INSERT INTO order_items (id, order_id, menu_item_id, quantity, unit_price) VALUES (?,?,?,?,?)",
        resolved_items,
    )
    conn.executemany(
        "INSERT INTO payments VALUES (?,?,?,?,?,?,?,?)",
        PAYMENTS,
    )
    conn.executemany(
        "INSERT INTO refunds VALUES (?,?,?,?,?,?,?,?)",
        REFUNDS,
    )
    conn.executemany(
        "INSERT INTO deliveries VALUES (?,?,?,?,?,?,?)",
        DELIVERIES,
    )
    conn.executemany(
        "INSERT INTO support_tickets VALUES (?,?,?,?,?,?,?,?,?)",
        TICKETS,
    )
    conn.executemany(
        "INSERT INTO coupons VALUES (?,?,?,?,?,?,?,?,?)",
        COUPONS,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Seed the ZoChat SQLite database.")
    parser.add_argument(
        "--path",
        type=Path,
        default=DEFAULT_DB_PATH,
        help=f"Path to write the .db file (default: {DEFAULT_DB_PATH})",
    )
    args = parser.parse_args(argv)
    build_database(args.path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
