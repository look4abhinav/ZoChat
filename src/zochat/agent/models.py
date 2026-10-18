"""Pydantic models for the structured outputs of the ZoChat agents.

Each agent returns a typed :class:`pydantic.BaseModel` instead of free text so
the orchestrator can branch on structured fields (``is_related``) and the
answer is always a well-formed object.
"""

from __future__ import annotations

from enum import Enum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from zochat.errors import ErrorInfo

from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, Field


class QuestionCategory(str, Enum):
    """The support domain a related question falls into."""

    order = "order"
    refund = "refund"
    payment = "payment"
    delivery = "delivery"
    coupon = "coupon"
    ticket = "ticket"
    restaurant = "restaurant"
    menu = "menu"
    account = "account"
    cancellation = "cancellation"
    other = "other"


class QuestionClassification(BaseModel):
    """Output of the primary *classifier* agent.

    The classifier's only job is to decide whether the customer's message is
    something the Zo support bot may handle, so the orchestrator can either
    hand off to the support agent or decline politely.
    """

    is_related: bool = Field(
        description=(
            "True if the message is about Zo food-delivery support: orders, "
            "deliveries, payments, refunds, coupons, support tickets, restaurants, "
            "menu, account/loyalty points or cancellations. False for anything else."
        ),
    )
    category: QuestionCategory | None = Field(
        default=None,
        description="The support category when is_related is True; None when unrelated.",
    )
    reasoning: str = Field(
        description="One short sentence explaining the classification."
    )


class SupportAnswer(BaseModel):
    """Output of the secondary *support* agent."""

    answer: str = Field(
        description="A warm, concise natural-language reply to the customer."
    )
    data_found: bool = Field(
        default=True,
        description="False if no matching records were found in the database.",
    )


class ChatReply(BaseModel):
    """The final response the orchestrator returns to the caller."""

    answered: bool = Field(
        description="True when the support agent answered; False when the question was declined.",
    )
    answer: str = Field(description="The text shown to the customer.")
    data_found: bool = Field(
        default=True,
        description="Mirrors SupportAnswer.data_found; always True for declined questions.",
    )
    classification: QuestionClassification = Field(
        description="The classification produced by the primary agent.",
    )
    request_id: str | None = Field(
        default=None,
        description="Request id for tracing; None if not assigned.",
    )
    latency_ms: float | None = Field(
        default=None,
        description="End-to-end latency in milliseconds.",
    )
    error: ErrorInfo | None = Field(
        default=None,
        description="Structured error when the request failed; None on success.",
    )
    usage: dict[str, int] | None = Field(
        default=None,
        description="Token usage summary when available.",
    )
    tool_calls: list[Any] | None = Field(
        default=None,
        description="Tool calls made by the support agent.",
    )
    session: Any | None = Field(
        default=None,
        exclude=True,
        description="Updated session state for this turn (excluded from serialization).",
    )
    history: list[Any] | None = Field(
        default=None,
        exclude=True,
        description=(
            "Updated pydantic-ai message history after this turn, for threading "
            "into the next ``chat()`` call so the support agent remembers prior "
            "exchanges. ``None`` when history threading was not used. Excluded "
            "from serialization."
        ),
    )


@dataclass
class ChatStreamEvent:
    kind: Literal[
        "classification", "tool_call", "tool_result", "answer_delta", "final", "error"
    ]
    request_id: str
    text: str | None = None
    classification: QuestionClassification | None = None
    tool_name: str | None = None
    tool_args: dict[str, Any] | None = None
    reply: ChatReply | None = None


# Resolve forward references now that `zochat.errors` is importable.
from zochat.errors import ErrorInfo

ChatReply.model_rebuild()
