"""Primary agent: decides whether a question is in scope for the support bot.

This agent never touches the database. It reads the customer's message and
returns a :class:`~zochat.agent.models.QuestionClassification` so the
orchestrator can route to the support agent or decline.
"""

from __future__ import annotations

from typing import Any

from pydantic_ai import Agent
from pydantic_ai.models import Model
from pydantic_ai.output import PromptedOutput

from zochat.agent.models import QuestionClassification

_CLASSIFIER_INSTRUCTIONS = """\
You are the gatekeeper for Zo's food-delivery support chatbot.

Decide whether the customer's message is RELATED or UNRELATED.

RELATED means it is genuinely about Zo food-delivery support, i.e. any of:
- Orders: status, recent orders, what was ordered, cancellation
- Deliveries: "where is my order", rider contact, ETA
- Payments: is my payment successful, payment status
- Refunds: when will I get my refund, refund status
- Coupons / discounts / offers: what coupons can I use
- Support tickets / complaints: status of my complaint
- Restaurants: which restaurants are available in my city
- Menu: what's on the menu at a restaurant
- Account: my details, loyalty points, who am I

UNRELATED means anything else: general chit-chat, coding, math, weather, news,
sports, politics, other companies/services, jokes, philosophy, etc.

Be strict and conservative: only mark RELATED when the message clearly needs
the Zo support bot. A vague greeting with no support content is UNRELATED.
"""


def build_classifier_agent(
    model: Model | str | None = None,
) -> Agent[Any, QuestionClassification]:
    """Return the primary classifier agent.

    Args:
        model: A pydantic-ai model (e.g. ``"google-gla:gemini-2.0-flash"``) or
            ``None`` to set it later at call time.
    """
    return Agent(
        model=model,
        output_type=PromptedOutput(QuestionClassification),
        name="zochat-classifier",
        instructions=_CLASSIFIER_INSTRUCTIONS,
        retries=3,
    )  # ty:ignore[invalid-return-type]
