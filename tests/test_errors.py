from zochat.errors import NotFoundError, ZoChatError


def test_error_to_info():
    e = NotFoundError("missing", details={"id": 1})
    info = e.to_info()
    assert info.code == "not_found"
    assert info.retryable is False
    assert info.details == {"id": 1}


def test_base_error():
    e = ZoChatError("boom", code="x", retryable=True)
    assert str(e) == "boom"
    assert e.code == "x"
    assert e.retryable is True
