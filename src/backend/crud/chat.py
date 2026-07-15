from __future__ import annotations

import json
import uuid

import aiosqlite


async def create_conversation(
    db: aiosqlite.Connection, title: str | None = None
) -> dict:
    conv_id = uuid.uuid4().hex
    await db.execute(
        "INSERT INTO chat_conversations (id, title) VALUES (?, ?)",
        (conv_id, title),
    )
    await db.commit()
    cursor = await db.execute(
        "SELECT * FROM chat_conversations WHERE id = ?", (conv_id,)
    )
    return dict(await cursor.fetchone())


async def list_conversations(
    db: aiosqlite.Connection, limit: int = 20, offset: int = 0
) -> list[dict]:
    cursor = await db.execute(
        """SELECT c.*,
            (SELECT COUNT(*) FROM chat_messages WHERE conversation_id = c.id) as message_count
        FROM chat_conversations c
        ORDER BY c.updated_at DESC
        LIMIT ? OFFSET ?""",
        (limit, offset),
    )
    return [dict(r) for r in await cursor.fetchall()]


async def get_conversation(
    db: aiosqlite.Connection, conversation_id: str
) -> dict | None:
    cursor = await db.execute(
        """SELECT c.*,
            (SELECT COUNT(*) FROM chat_messages WHERE conversation_id = c.id) as message_count
        FROM chat_conversations c WHERE c.id = ?""",
        (conversation_id,),
    )
    row = await cursor.fetchone()
    return dict(row) if row else None


async def get_messages(
    db: aiosqlite.Connection, conversation_id: str
) -> list[dict]:
    cursor = await db.execute(
        "SELECT * FROM chat_messages WHERE conversation_id = ? ORDER BY created_at ASC",
        (conversation_id,),
    )
    messages = [dict(r) for r in await cursor.fetchall()]
    for msg in messages:
        if msg.get("blocks"):
            try:
                blocks = json.loads(msg["blocks"])
                msg["blocks"] = blocks
                answer_block = next(
                    (b for b in blocks if b.get("type") == "answer"), None
                )
                if answer_block and answer_block.get("activity_order"):
                    msg["activity_order"] = answer_block["activity_order"]
            except (json.JSONDecodeError, TypeError):
                pass
        elif msg.get("metadata"):
            try:
                meta = json.loads(msg["metadata"])
                if isinstance(meta, dict) and "tool_calls" in meta:
                    msg["tool_calls"] = meta.pop("tool_calls")
                msg["metadata"] = meta
            except (json.JSONDecodeError, TypeError):
                pass
    return messages


async def add_message(
    db: aiosqlite.Connection,
    conversation_id: str,
    role: str,
    content: str,
    metadata: str | None = None,
    blocks: str | None = None,
) -> dict:
    msg_id = uuid.uuid4().hex
    await db.execute(
        """INSERT INTO chat_messages (id, conversation_id, role, content, metadata, blocks)
        VALUES (?, ?, ?, ?, ?, ?)""",
        (msg_id, conversation_id, role, content, metadata, blocks),
    )
    await db.execute(
        "UPDATE chat_conversations SET updated_at = datetime('now') WHERE id = ?",
        (conversation_id,),
    )
    await db.commit()
    cursor = await db.execute(
        "SELECT * FROM chat_messages WHERE id = ?", (msg_id,)
    )
    return dict(await cursor.fetchone())


async def delete_conversation(
    db: aiosqlite.Connection, conversation_id: str
) -> bool:
    cursor = await db.execute(
        "DELETE FROM chat_conversations WHERE id = ?", (conversation_id,)
    )
    await db.commit()
    return cursor.rowcount > 0


async def update_conversation_title(
    db: aiosqlite.Connection, conversation_id: str, title: str
) -> dict | None:
    cursor = await db.execute(
        "SELECT id FROM chat_conversations WHERE id = ?", (conversation_id,)
    )
    if not await cursor.fetchone():
        return None
    await db.execute(
        "UPDATE chat_conversations SET title = ? WHERE id = ?",
        (title, conversation_id),
    )
    await db.commit()
    return await get_conversation(db, conversation_id)
