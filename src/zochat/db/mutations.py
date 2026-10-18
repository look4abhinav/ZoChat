"""Mutation helpers for ZoChat: propose/execute actions transactionally."""

from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from zochat.errors import (
    AuthorizationError,
    ConflictError,
    NotFoundError,
    ValidationError,
)

TTL_MINUTES = 10
_MUTATION_LOCK = threading.RLock()


def _locked(fn):
    def wrapper(*args, **kwargs):
        with _MUTATION_LOCK:
            return fn(*args, **kwargs)

    wrapper.__name__ = fn.__name__
    return wrapper


@dataclass
class ActionProposal:
    token: str
    action: str
    target_type: str
    target_id: int | None
    summary: str
    before: dict[str, Any] | None
    risk: str
    expires_at: datetime


@dataclass
class ActionResult:
    ok: bool
    action: str
    target_id: int | None
    status: str
    message: str
    before: dict[str, Any] | None = None
    after: dict[str, Any] | None = None
    audit_id: int | None = None


@contextmanager
def transaction(conn: sqlite3.Connection) -> Iterator[None]:
    try:
        yield
        conn.commit()
    except BaseException:
        conn.rollback()
        raise


def _now() -> datetime:
    return datetime.now()


def _iso(dt: datetime) -> str:
    return dt.isoformat(sep=" ")


def _row(conn, sql, params=()):
    return conn.execute(sql, params).fetchone()


def _audit(
    conn,
    *,
    request_id,
    customer_id,
    action,
    target_type,
    target_id,
    status,
    before,
    after,
    error_code=None,
) -> int | None:
    cur = conn.execute(
        """
        INSERT INTO action_audit_log
            (request_id, customer_id, action, target_type, target_id, status,
             before_json, after_json, error_code, created_at)
        VALUES (?,?,?,?,?,?,?,?,?,?)
        RETURNING id
        """,
        (
            request_id,
            customer_id,
            action,
            target_type,
            target_id,
            status,
            json.dumps(before) if before is not None else None,
            json.dumps(after) if after is not None else None,
            error_code,
            _iso(_now()),
        ),
    )
    row = cur.fetchone()
    if isinstance(row, dict):
        return row.get("id")
    return row[0] if row else None


def _before_state(conn, action, target_id, payload):
    if action == "cancel_order" and target_id is not None:
        row = _row(conn, "SELECT * FROM orders WHERE id = ?", (target_id,))
        return dict(row) if row else None
    if action == "create_ticket":
        return None
    if action == "resolve_ticket" and target_id is not None:
        row = _row(conn, "SELECT * FROM support_tickets WHERE id = ?", (target_id,))
        return dict(row) if row else None
    if action == "apply_coupon":
        order_id = payload.get("order_id")
        row = _row(conn, "SELECT * FROM orders WHERE id = ?", (order_id,))
        return dict(row) if row else None
    if action == "rate_order" and target_id is not None:
        row = _row(conn, "SELECT * FROM orders WHERE id = ?", (target_id,))
        return dict(row) if row else None
    return None


@_locked
def propose_action(
    conn,
    *,
    customer_id: int | None,
    action: str,
    target_type: str,
    target_id: int | None,
    payload: dict[str, Any],
    request_id: str | None = None,
    summary: str = "",
    risk: str = "medium",
) -> ActionProposal:
    if customer_id is None:
        raise AuthorizationError(
            "customer must be identified before performing this action"
        )
    if (
        action in ("cancel_order", "apply_coupon", "rate_order")
        and target_id is not None
    ):
        row = _row(conn, "SELECT customer_id FROM orders WHERE id = ?", (target_id,))
        if row is None:
            raise NotFoundError(f"order {target_id} not found")
        if row["customer_id"] != customer_id:
            raise AuthorizationError("you do not own this order")
    if action == "resolve_ticket" and target_id is not None:
        row = _row(
            conn, "SELECT customer_id FROM support_tickets WHERE id = ?", (target_id,)
        )
        if row is None:
            raise NotFoundError(f"ticket {target_id} not found")
        if row["customer_id"] != customer_id:
            raise AuthorizationError("you do not own this ticket")
    if (
        action == "create_ticket"
        and payload.get("customer_id") is not None
        and payload["customer_id"] != customer_id
    ):
        raise AuthorizationError("customer mismatch")
    token = str(uuid.uuid4())
    now = _now()
    expires = now + timedelta(minutes=TTL_MINUTES)
    before = _before_state(conn, action, target_id, payload)
    risk_final = risk

    with transaction(conn):
        conn.execute(
            """
            INSERT INTO pending_actions
                (id, customer_id, action, target_type, target_id, payload_json,
                 created_at, expires_at, consumed_at)
            VALUES (?,?,?,?,?,?,?,?,?)
            """,
            (
                token,
                customer_id,
                action,
                target_type,
                target_id,
                json.dumps(payload),
                _iso(now),
                _iso(expires),
                None,
            ),
        )
        _audit(
            conn,
            request_id=request_id,
            customer_id=customer_id,
            action=action,
            target_type=target_type,
            target_id=target_id,
            status="previewed",
            before=before,
            after=None,
        )

    if not summary:
        summary = f"{action} on {target_type} {target_id}"
    return ActionProposal(
        token=token,
        action=action,
        target_type=target_type,
        target_id=target_id,
        summary=summary,
        before=before,
        risk=risk_final,
        expires_at=expires,
    )


@_locked
def execute_action(conn, *, token, request_id=None) -> ActionResult:
    row = _row(conn, "SELECT * FROM pending_actions WHERE id = ?", (token,))
    if row is None:
        return ActionResult(
            ok=False,
            action="unknown",
            target_id=None,
            status="expired",
            message="This confirmation has expired or is invalid.",
        )
    action = row["action"]
    target_id = row["target_id"]
    customer_id = row["customer_id"]
    payload = json.loads(row["payload_json"])
    expires_at = datetime.fromisoformat(row["expires_at"])
    if row["consumed_at"] is not None:
        return ActionResult(
            ok=False,
            action=action,
            target_id=target_id,
            status="expired",
            message="This confirmation has already been used.",
        )
    if _now() > expires_at:
        return ActionResult(
            ok=False,
            action=action,
            target_id=target_id,
            status="expired",
            message="This confirmation has expired. Please try again.",
        )

    before = _before_state(conn, action, target_id, payload)
    try:
        with transaction(conn):
            after = _apply(conn, action, target_id, payload, customer_id)
            if target_id is None and isinstance(after, dict) and "id" in after:
                target_id = after["id"]
            conn.execute(
                "UPDATE pending_actions SET consumed_at = ? WHERE id = ?",
                (_iso(_now()), token),
            )
            audit_id = _audit(
                conn,
                request_id=request_id,
                customer_id=customer_id,
                action=action,
                target_type=row["target_type"],
                target_id=target_id,
                status="confirmed",
                before=before,
                after=after,
            )
        return ActionResult(
            ok=True,
            action=action,
            target_id=target_id,
            status="completed",
            message=f"{action} completed successfully.",
            before=before,
            after=after,
            audit_id=audit_id,
        )
    except Exception as exc:  # noqa: BLE001
        try:
            _audit(
                conn,
                request_id=request_id,
                customer_id=customer_id,
                action=action,
                target_type=row["target_type"],
                target_id=target_id,
                status="failed",
                before=before,
                after=None,
                error_code=getattr(exc, "code", "error"),
            )
            conn.commit()
        except Exception:  # noqa: BLE001
            conn.rollback()
        return ActionResult(
            ok=False,
            action=action,
            target_id=target_id,
            status="failed",
            message=str(exc),
            before=before,
        )


def _apply(conn, action, target_id, payload, customer_id):
    if action == "cancel_order":
        order_id = target_id
        row = _row(conn, "SELECT * FROM orders WHERE id = ?", (order_id,))
        if row is None:
            raise NotFoundError(f"order {order_id} not found")
        status = row["status"]
        if status not in ("placed", "preparing"):
            raise ConflictError(f"order is already {status} and cannot be cancelled")
        reason = payload.get("reason") or "cancelled by customer"
        conn.execute(
            "UPDATE orders SET status='cancelled', cancelled_at=?, cancelled_reason=? WHERE id=?",
            (_iso(_now()), reason, order_id),
        )
        pay = _row(conn, "SELECT * FROM payments WHERE order_id = ?", (order_id,))
        if pay is not None and pay["status"] == "success":
            conn.execute(
                """INSERT INTO refunds (payment_id, order_id, amount, reason, status,
                   requested_at, processed_at) VALUES (?,?,?,?,?,?,?)""",
                (
                    pay["id"],
                    order_id,
                    pay["amount"],
                    f"Order cancelled: {reason}",
                    "initiated",
                    _iso(_now()),
                    None,
                ),
            )
        after = _row(conn, "SELECT * FROM orders WHERE id = ?", (order_id,))
        return dict(after) if after else None

    if action == "create_ticket":
        cid = payload.get("customer_id", customer_id)
        if cid is None:
            raise ValidationError("customer_id is required to create a ticket")
        cur = conn.execute(
            """INSERT INTO support_tickets
               (customer_id, order_id, category, priority, status, description,
                created_at, resolved_at, resolution_note)
               VALUES (?,?,?,?,?,?,?,?,?)
               RETURNING id""",
            (
                cid,
                payload.get("order_id"),
                payload.get("category", "other"),
                payload.get("priority", "medium"),
                "open",
                payload.get("description", ""),
                _iso(_now()),
                None,
                None,
            ),
        )
        row = cur.fetchone()
        tid = row["id"] if isinstance(row, dict) else row[0]
        row = _row(conn, "SELECT * FROM support_tickets WHERE id = ?", (tid,))
        return dict(row) if row else {"id": tid}

    if action == "resolve_ticket":
        tid = target_id
        row = _row(conn, "SELECT * FROM support_tickets WHERE id = ?", (tid,))
        if row is None:
            raise NotFoundError(f"ticket {tid} not found")
        conn.execute(
            "UPDATE support_tickets SET status='resolved', resolved_at=?, resolution_note=? WHERE id=?",
            (_iso(_now()), payload.get("resolution_note"), tid),
        )
        after = _row(conn, "SELECT * FROM support_tickets WHERE id = ?", (tid,))
        return dict(after) if after else None

    if action == "apply_coupon":
        order_id = payload.get("order_id")
        code = payload.get("code")
        order = _row(conn, "SELECT * FROM orders WHERE id = ?", (order_id,))
        if order is None:
            raise NotFoundError(f"order {order_id} not found")
        existing = _row(
            conn, "SELECT * FROM coupon_redemptions WHERE order_id = ?", (order_id,)
        )
        if existing is not None:
            raise ConflictError("a coupon has already been applied to this order")
        coupon = _row(conn, "SELECT * FROM coupons WHERE code = ?", (code,))
        if coupon is None or not coupon["is_active"]:
            raise NotFoundError(f"coupon {code} not found or inactive")
        if coupon["expires_on"] <= _iso(_now()):
            raise ConflictError("coupon has expired")
        if order["total_amount"] < coupon["min_order_value"]:
            raise ConflictError("order total below coupon minimum")
        if coupon["discount_type"] == "percentage":
            disc = order["total_amount"] * coupon["discount_value"] / 100.0
            if coupon["max_discount"] is not None:
                disc = min(disc, coupon["max_discount"])
        else:
            disc = float(coupon["discount_value"])
        disc = round(disc, 2)
        final = round(order["total_amount"] - disc, 2)
        conn.execute(
            """INSERT INTO coupon_redemptions
               (order_id, coupon_code, discount_amount, original_total, final_total, applied_at)
               VALUES (?,?,?,?,?,?)""",
            (order_id, code, disc, order["total_amount"], final, _iso(_now())),
        )
        conn.execute(
            "UPDATE orders SET coupon_code=?, total_amount=? WHERE id=?",
            (code, final, order_id),
        )
        after = _row(conn, "SELECT * FROM orders WHERE id = ?", (order_id,))
        return dict(after) if after else None

    if action == "rate_order":
        order_id = target_id
        row = _row(conn, "SELECT * FROM orders WHERE id = ?", (order_id,))
        if row is None:
            raise NotFoundError(f"order {order_id} not found")
        rating = payload.get("rating")
        if rating is None or not (1 <= int(rating) <= 5):
            raise ValidationError("rating must be between 1 and 5")
        conn.execute("UPDATE orders SET rating=? WHERE id=?", (int(rating), order_id))
        after = _row(conn, "SELECT * FROM orders WHERE id = ?", (order_id,))
        return dict(after) if after else None

    raise ValidationError(f"unknown action: {action}")


def propose_cancel_order(
    conn, *, order_id, customer_id=None, reason=None, request_id=None
):
    return propose_action(
        conn,
        customer_id=customer_id,
        action="cancel_order",
        target_type="order",
        target_id=order_id,
        payload={"reason": reason},
        request_id=request_id,
        summary=f"Cancel order #{order_id}" + (f" ({reason})" if reason else ""),
        risk="medium",
    )


def propose_create_ticket(
    conn,
    *,
    customer_id=None,
    category="other",
    description="",
    order_id=None,
    priority="medium",
    request_id=None,
):
    return propose_action(
        conn,
        customer_id=customer_id,
        action="create_ticket",
        target_type="ticket",
        target_id=None,
        payload={
            "customer_id": customer_id,
            "category": category,
            "description": description,
            "order_id": order_id,
            "priority": priority,
        },
        request_id=request_id,
        summary=f"Create a {priority}-priority {category} support ticket",
        risk="low",
    )


def propose_resolve_ticket(
    conn, *, ticket_id, customer_id=None, resolution_note=None, request_id=None
):
    return propose_action(
        conn,
        customer_id=customer_id,
        action="resolve_ticket",
        target_type="ticket",
        target_id=ticket_id,
        payload={"resolution_note": resolution_note},
        request_id=request_id,
        summary=f"Resolve ticket #{ticket_id}",
        risk="low",
    )


def propose_apply_coupon(conn, *, order_id, code, customer_id=None, request_id=None):
    return propose_action(
        conn,
        customer_id=customer_id,
        action="apply_coupon",
        target_type="order",
        target_id=order_id,
        payload={"order_id": order_id, "code": code},
        request_id=request_id,
        summary=f"Apply coupon {code} to order #{order_id}",
        risk="low",
    )


def propose_rate_order(conn, *, order_id, rating, customer_id=None, request_id=None):
    return propose_action(
        conn,
        customer_id=customer_id,
        action="rate_order",
        target_type="order",
        target_id=order_id,
        payload={"rating": rating},
        request_id=request_id,
        summary=f"Rate order #{order_id} as {rating}/5",
        risk="low",
    )


@_locked
def cancel_pending_action(conn, token) -> bool:
    row = _row(conn, "SELECT * FROM pending_actions WHERE id = ?", (token,))
    if row is None or row["consumed_at"] is not None:
        return False
    with transaction(conn):
        conn.execute(
            "UPDATE pending_actions SET consumed_at = ? WHERE id = ?",
            (_iso(_now()), token),
        )
        _audit(
            conn,
            request_id=None,
            customer_id=row["customer_id"],
            action=row["action"],
            target_type=row["target_type"],
            target_id=row["target_id"],
            status="rejected",
            before=None,
            after=None,
        )
    return True


__all__ = [
    "ActionProposal",
    "ActionResult",
    "cancel_pending_action",
    "execute_action",
    "propose_action",
    "propose_apply_coupon",
    "propose_cancel_order",
    "propose_create_ticket",
    "propose_rate_order",
    "propose_resolve_ticket",
    "transaction",
]
