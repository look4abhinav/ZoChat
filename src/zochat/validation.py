"""Input validation at ZoChat's trust boundaries.

All external inputs (CLI args, ``chat()`` arguments, tool args, DB writes) are
validated here with pydantic so failures surface as :class:`ValidationError`
instead of reaching SQLite or the model.
"""

from __future__ import annotations

from enum import Enum
from typing import Annotated

from pydantic import BaseModel, Field, StringConstraints

from zochat.errors import ValidationError as ZoValidationError


class TicketCategory(str, Enum):
    refund = "refund"
    delivery_delay = "delivery_delay"
    food_quality = "food_quality"
    payment = "payment"
    cancellation = "cancellation"
    other = "other"


class TicketPriority(str, Enum):
    low = "low"
    medium = "medium"
    high = "high"


class TicketStatus(str, Enum):
    open = "open"
    in_progress = "in_progress"
    resolved = "resolved"
    closed = "closed"


CustomerId = Annotated[int, Field(gt=0)]
OrderId = Annotated[int, Field(gt=0)]
TicketId = Annotated[int, Field(gt=0)]
RestaurantId = Annotated[int, Field(gt=0)]
Rating = Annotated[int, Field(ge=1, le=5)]
PhoneNumber = Annotated[str, StringConstraints(pattern=r"^\+?[0-9]{7,15}$")]
CouponCode = Annotated[str, StringConstraints(pattern=r"^[A-Z0-9]{3,20}$")]
City = Annotated[str, StringConstraints(min_length=1, max_length=64)]


def validate_or_raise(value: object, model: type[BaseModel]) -> BaseModel:
    """Validate ``value`` against ``model``, raising :class:`ZoValidationError`."""
    try:
        return model.model_validate(value)
    except Exception as exc:  # pydantic.ValidationError
        raise ZoValidationError(str(exc), details={"errors": _errors(exc)}) from exc


def _errors(exc: Exception) -> list[dict[str, object]]:
    if hasattr(exc, "errors"):
        try:
            return list(exc.errors())  # type: ignore[attr-defined]
        except Exception:  # pragma: no cover  # noqa: BLE001
            return [{"msg": str(exc)}]
    return [{"msg": str(exc)}]


class ChatRequest(BaseModel):
    question: str = Field(min_length=1, max_length=4000)
    customer_id: CustomerId | None = None
    session_id: str | None = None


class CreateTicketRequest(BaseModel):
    customer_id: CustomerId
    category: TicketCategory
    description: str = Field(min_length=1, max_length=2000)
    order_id: OrderId | None = None
    priority: TicketPriority = TicketPriority.medium


class ApplyCouponRequest(BaseModel):
    order_id: OrderId
    code: CouponCode


class RateOrderRequest(BaseModel):
    order_id: OrderId
    rating: Rating


class CancelOrderRequest(BaseModel):
    order_id: OrderId
    reason: str | None = Field(default=None, max_length=500)


__all__ = [
    "ApplyCouponRequest",
    "CancelOrderRequest",
    "ChatRequest",
    "City",
    "CouponCode",
    "CreateTicketRequest",
    "CustomerId",
    "OrderId",
    "PhoneNumber",
    "RateOrderRequest",
    "Rating",
    "RestaurantId",
    "TicketCategory",
    "TicketId",
    "TicketPriority",
    "TicketStatus",
    "validate_or_raise",
]
