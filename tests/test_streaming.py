
import pytest
from pydantic_ai.models.test import TestModel

from zochat.agent.chat import chat_stream
from zochat.db import connect


@pytest.mark.asyncio
async def test_chat_stream_yields_final():
    conn = connect()
    try:
        events = []
        async for ev in chat_stream(
            "Will it rain tomorrow?",
            conn=conn,
            model=TestModel(custom_output_text='{"is_related": false, "category": null, "reasoning": "weather"}'),
        ):
            events.append(ev)
        assert any(e.kind == "final" for e in events)
        # classifier event present
        assert any(e.kind == "classification" for e in events)
    finally:
        conn.close()
