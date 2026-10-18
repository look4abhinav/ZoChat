import sqlite3
import tempfile
from pathlib import Path

import pytest
from pydantic_ai.models.test import TestModel

from zochat.agent.chat import chat_stream
from zochat.db.seed import build_database


@pytest.mark.asyncio
async def test_chat_stream_yields_final():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        path = Path(tmp.name)
    build_database(path, verbose=False)
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    try:
        events = []
        async for ev in chat_stream(
            "Will it rain tomorrow?",
            conn=conn,
            model=TestModel(custom_output_text='{"is_related": false, "category": null, "reasoning": "weather"}'),
        ):
            events.append(ev)
        assert any(e.kind == "final" for e in events)
        assert any(e.kind == "classification" for e in events)
    finally:
        conn.close()
        path.unlink(missing_ok=True)
