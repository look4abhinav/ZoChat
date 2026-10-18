import pytest
from pydantic import ValidationError as PydanticValidationError

from zochat.errors import ValidationError
from zochat.validation import (
    ChatRequest,
    CouponCode,
    validate_or_raise,
)


def test_phone_valid():
    ChatRequest(question="hi", customer_id=None)  # no phone field but ok


def test_coupon_code_pattern():
    with pytest.raises(PydanticValidationError):
        # invalid lowercase
        from pydantic import TypeAdapter
        TypeAdapter(CouponCode).validate_python("welcome")


def test_validate_or_raise_raises_zochat_error():
    class M(ChatRequest):
        pass
    with pytest.raises(ValidationError):
        validate_or_raise({"question": ""}, M)
