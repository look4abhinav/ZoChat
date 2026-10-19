import sqlite3
import tempfile
from pathlib import Path

import pytest

from zochat.db import mutations
from zochat.db.seed import BASE_TS, build_database
from zochat.errors import AuthorizationError


@pytest.fixture
def conn():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        path = Path(tmp.name)
    build_database(path, verbose=False)
    connection = sqlite3.connect(path, check_same_thread=False)
    connection.row_factory = sqlite3.Row
    yield connection
    connection.close()
    path.unlink(missing_ok=True)


def test_propose_and_execute_cancel(conn):
    p = mutations.propose_cancel_order(conn, order_id=8, customer_id=4, request_id="r1")
    assert p.token
    r = mutations.execute_action(conn, token=p.token, request_id="r1")
    assert r.ok
    assert r.status == "completed"
    row = conn.execute("SELECT status FROM orders WHERE id = 8").fetchone()
    assert row["status"] == "cancelled"


def test_replay_token_expired(conn):
    p = mutations.propose_cancel_order(conn, order_id=8, customer_id=4)
    mutations.execute_action(conn, token=p.token)
    r2 = mutations.execute_action(conn, token=p.token)
    assert not r2.ok
    assert r2.status == "expired"


def test_cancel_pending_action(conn):
    p = mutations.propose_cancel_order(conn, order_id=8, customer_id=4)
    assert mutations.cancel_pending_action(conn, p.token) is True
    r = mutations.execute_action(conn, token=p.token)
    assert not r.ok
    assert r.status == "expired"


def test_authorization_denied(conn):
    with pytest.raises(AuthorizationError):
        mutations.propose_cancel_order(conn, order_id=1, customer_id=999)


def test_apply_coupon(conn, monkeypatch):
    monkeypatch.setattr(mutations, "_now", lambda: BASE_TS)
    p = mutations.propose_apply_coupon(conn, order_id=1, code="FLAT60", customer_id=1)
    r = mutations.execute_action(conn, token=p.token)
    assert r.ok
    row = conn.execute("SELECT coupon_code FROM orders WHERE id = 1").fetchone()
    assert row["coupon_code"] == "FLAT60"
