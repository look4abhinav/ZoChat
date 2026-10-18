from zochat.session import MemorySessionStore, SessionState


def test_session_roundtrip():
    s = SessionState(customer_id=1, customer_name="A")
    store = MemorySessionStore()
    store.save(s)
    loaded = store.load(s.session_id)
    assert loaded is not None
    assert loaded.customer_id == 1
    assert loaded.customer_name == "A"


def test_session_delete():
    s = SessionState()
    store = MemorySessionStore()
    store.save(s)
    store.delete(s.session_id)
    assert store.load(s.session_id) is None
