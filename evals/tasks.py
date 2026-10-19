"""Task functions for the eval harness."""

from __future__ import annotations

from zochat.agent.chat import run as run_flow
from zochat.agent.classifier import build_classifier_agent
from zochat.agent.support import build_support_agent
from zochat.config import get_groq_model
from zochat.db import connect


async def classify_task(question: str):
    clf = build_classifier_agent(model=get_groq_model())
    return (await clf.run(question)).output


async def support_task(question: str, customer_phone: str | None = None):
    conn = connect()
    try:
        clf = build_classifier_agent(model=get_groq_model())
        sup = build_support_agent(model=get_groq_model())
        # identify customer if phone provided (no session threading in eval)
        reply = await run_flow(clf, sup, question, conn=conn)
        return reply
    finally:
        conn.close()
