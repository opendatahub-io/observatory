from __future__ import annotations

import json
import uuid
from typing import Optional

import aiosqlite
from fastapi import APIRouter, Depends, HTTPException, Query, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from backend.chat.agent import stream_chat_response
from backend.config import settings
from backend.crud import chat as chat_crud
from backend.database import get_db

router = APIRouter(prefix="/api/v1/chat", tags=["chat"])


class CreateConversationRequest(BaseModel):
    title: Optional[str] = None


class SendMessageRequest(BaseModel):
    content: str


@router.post("/conversations", status_code=201)
async def create_conversation(
    data: CreateConversationRequest,
    db: aiosqlite.Connection = Depends(get_db),
):
    return await chat_crud.create_conversation(db, data.title)


@router.get("/conversations")
async def list_conversations(
    limit: int = Query(default=20, le=100),
    offset: int = Query(default=0),
    db: aiosqlite.Connection = Depends(get_db),
):
    return await chat_crud.list_conversations(db, limit, offset)


@router.get("/conversations/{conversation_id}")
async def get_conversation(
    conversation_id: str,
    db: aiosqlite.Connection = Depends(get_db),
):
    conv = await chat_crud.get_conversation(db, conversation_id)
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    messages = await chat_crud.get_messages(db, conversation_id)
    conv["messages"] = messages
    return conv


@router.delete("/conversations/{conversation_id}", status_code=204)
async def delete_conversation(
    conversation_id: str,
    db: aiosqlite.Connection = Depends(get_db),
):
    deleted = await chat_crud.delete_conversation(db, conversation_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return Response(status_code=204)


@router.post("/conversations/{conversation_id}/messages")
async def send_message(
    conversation_id: str,
    data: SendMessageRequest,
    db: aiosqlite.Connection = Depends(get_db),
):
    if not settings.anthropic_api_key and not settings.anthropic_vertex_project_id:
        raise HTTPException(
            status_code=503,
            detail="Chat is not configured: set OBSERVATORY_ANTHROPIC_API_KEY or OBSERVATORY_ANTHROPIC_VERTEX_PROJECT_ID",
        )

    conv = await chat_crud.get_conversation(db, conversation_id)
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")

    await chat_crud.add_message(db, conversation_id, "user", data.content)
    messages = await chat_crud.get_messages(db, conversation_id)

    async def event_stream():
        msg_id = uuid.uuid4().hex
        yield f"event: message_start\ndata: {json.dumps({'id': msg_id, 'role': 'assistant'})}\n\n"

        blocks: list[dict] = []
        pending_text = ""
        block_counter = 0
        tool_call_id_map: dict[str, str] = {}
        usage: dict = {}

        def next_block_id() -> str:
            nonlocal block_counter
            block_counter += 1
            return f"{msg_id}-block-{block_counter}"

        def flush_activity():
            nonlocal pending_text
            text = pending_text.strip()
            if text:
                blocks.append({"id": next_block_id(), "type": "activity", "text": text})
            pending_text = ""

        try:
            async for event in stream_chat_response(db, messages):
                evt_type = event["event"]
                evt_data = event["data"]

                if evt_type == "content_delta":
                    pending_text += evt_data.get("text", "")
                    yield f"event: {evt_type}\ndata: {json.dumps(evt_data)}\n\n"

                elif evt_type == "tool_use":
                    flush_activity()
                    block_id = next_block_id()
                    tool_name = evt_data["tool"]
                    tool_call_id_map[tool_name] = block_id
                    blocks.append({
                        "id": block_id,
                        "type": "tool",
                        "tool_call_id": block_id,
                        "tool": tool_name,
                        "input": evt_data["input"],
                        "status": "running",
                    })
                    enriched = {**evt_data, "tool_call_id": block_id}
                    yield f"event: {evt_type}\ndata: {json.dumps(enriched)}\n\n"

                elif evt_type == "tool_result":
                    tool_name = evt_data["tool"]
                    block_id = tool_call_id_map.get(tool_name)
                    is_error = evt_data.get("is_error", False)
                    for b in blocks:
                        if b["type"] == "tool" and b.get("id") == block_id:
                            b["result"] = evt_data["result"]
                            b["status"] = "failed" if is_error else "succeeded"
                            break
                    enriched = {**evt_data, "tool_call_id": block_id or ""}
                    yield f"event: {evt_type}\ndata: {json.dumps(enriched)}\n\n"

                elif evt_type == "message_end":
                    usage = evt_data.get("usage", {})
                    text = pending_text.strip()
                    if text:
                        blocks.append({"id": next_block_id(), "type": "answer", "text": text})
                        pending_text = ""
                    yield f"event: {evt_type}\ndata: {json.dumps(evt_data)}\n\n"

                else:
                    yield f"event: {evt_type}\ndata: {json.dumps(evt_data)}\n\n"

        except Exception as e:
            yield f"event: error\ndata: {json.dumps({'error': str(e)})}\n\n"

        remaining = pending_text.strip()
        if remaining:
            blocks.append({"id": next_block_id(), "type": "answer", "text": remaining})

        answer_text = ""
        for b in blocks:
            if b["type"] == "answer":
                answer_text = b.get("text", "")
                break

        if blocks:
            metadata = {}
            if usage:
                metadata.update(usage)
            await chat_crud.add_message(
                db, conversation_id, "assistant", answer_text,
                json.dumps(metadata, default=str) if metadata else None,
                json.dumps(blocks, default=str),
            )

        if not conv.get("title") and answer_text:
            auto_title = data.content[:60].strip()
            if len(data.content) > 60:
                auto_title += "..."
            await chat_crud.update_conversation_title(db, conversation_id, auto_title)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
