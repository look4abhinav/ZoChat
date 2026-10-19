from zochat.observability import new_request_id, request_context, request_id_var


def test_request_context_sets_var():
    with request_context("abc-123"):
        assert request_id_var.get() == "abc-123"
    assert request_id_var.get() == ""


def test_new_request_id_unique():
    assert new_request_id() != new_request_id()
