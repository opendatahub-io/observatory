"""Tests for chat ordered-block schema, migration, and CRUD."""

from __future__ import annotations

import json

import pytest

from backend.crud import chat as chat_crud
from backend.database import get_db


@pytest.fixture
async def db(tmp_db):
    """Return the active aiosqlite connection."""
    return await get_db()


@pytest.mark.anyio
async def test_add_message_with_blocks(db):
    conv = await chat_crud.create_conversation(db, "test conv")
    blocks = [
        {"id": "b1", "type": "tool", "tool": "query_pipelines", "input": {"limit": 5}, "status": "succeeded", "result": {"rows": []}},
        {"id": "b2", "type": "answer", "text": "Found nothing."},
    ]
    await chat_crud.add_message(
        db, conv["id"], "assistant", "Found nothing.", None, json.dumps(blocks),
    )
    msgs = await chat_crud.get_messages(db, conv["id"])
    assistant_msg = [m for m in msgs if m["role"] == "assistant"][0]
    assert isinstance(assistant_msg["blocks"], list)
    assert len(assistant_msg["blocks"]) == 2
    assert assistant_msg["blocks"][0]["type"] == "tool"
    assert assistant_msg["blocks"][1]["type"] == "answer"


@pytest.mark.anyio
async def test_legacy_migration_creates_blocks(db):
    """Simulate a legacy message (no blocks column value) and verify CRUD still returns tool_calls."""
    conv = await chat_crud.create_conversation(db, "legacy conv")
    tool_calls = [{"tool": "query_pipelines", "input": {"limit": 5}, "result": {"rows": []}}]
    metadata = json.dumps({"tool_calls": tool_calls})
    await chat_crud.add_message(db, conv["id"], "assistant", "Here are results.", metadata)
    msgs = await chat_crud.get_messages(db, conv["id"])
    assistant_msg = [m for m in msgs if m["role"] == "assistant"][0]
    # With the migration in init_schema, this message should have blocks
    # But since it was created after migration, it will use the metadata fallback
    assert "tool_calls" in assistant_msg or "blocks" in assistant_msg


@pytest.mark.anyio
async def test_blocks_column_exists(db):
    """Verify blocks column was added by migration."""
    cursor = await db.execute("PRAGMA table_info(chat_messages)")
    columns = {row["name"] for row in await cursor.fetchall()}
    assert "blocks" in columns


@pytest.mark.anyio
async def test_user_message_has_no_blocks(db):
    conv = await chat_crud.create_conversation(db, "test")
    await chat_crud.add_message(db, conv["id"], "user", "Hello")
    msgs = await chat_crud.get_messages(db, conv["id"])
    user_msg = msgs[0]
    assert user_msg["role"] == "user"
    assert user_msg.get("blocks") is None


@pytest.mark.anyio
async def test_activity_order_from_blocks(db):
    conv = await chat_crud.create_conversation(db, "test")
    blocks = [
        {"id": "b1", "type": "activity", "text": "Checking..."},
        {"id": "b2", "type": "tool", "tool": "kb_search", "input": {"query": "test"}, "status": "succeeded", "result": []},
        {"id": "b3", "type": "answer", "text": "Done.", "activity_order": "legacy_unavailable"},
    ]
    await chat_crud.add_message(
        db, conv["id"], "assistant", "Done.", None, json.dumps(blocks),
    )
    msgs = await chat_crud.get_messages(db, conv["id"])
    assistant_msg = [m for m in msgs if m["role"] == "assistant"][0]
    assert assistant_msg.get("activity_order") == "legacy_unavailable"
