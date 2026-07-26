"""The ZoChat two-agent support bot.

A primary *classifier* agent decides whether a customer question is in scope;
a secondary *support* agent answers in-scope questions using the SQLite tools
in :mod:`zochat.db.queries`. Out-of-scope questions are declined.
"""

from zochat.agent.chat import DECLINE_REPLY, ChatReply, chat, run
from zochat.agent.classifier import build_classifier_agent
from zochat.agent.models import (
    QuestionCategory,
    QuestionClassification,
    SupportAnswer,
)
from zochat.agent.support import build_support_agent

__all__ = [
    "DECLINE_REPLY",
    "ChatReply",
    "QuestionCategory",
    "QuestionClassification",
    "SupportAnswer",
    "build_classifier_agent",
    "build_support_agent",
    "chat",
    "run",
]
