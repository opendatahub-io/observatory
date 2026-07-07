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

        full_text_parts: list[str] = []
        tool_calls: list[dict] = []
        pending_tool: dict | None = None
        had_text_before_tool = False
        usage: dict = {}

        try:
            async for event in stream_chat_response(db, messages):
                evt_type = event["event"]
                evt_data = event["data"]

                if evt_type == "content_delta":
                    full_text_parts.append(evt_data["text"])
                    had_text_before_tool = True
                elif evt_type == "tool_use":
                    if had_text_before_tool:
                        full_text_parts.append("\n\n")
                        had_text_before_tool = False
                    pending_tool = {"tool": evt_data["tool"], "input": evt_data["input"]}
                elif evt_type == "tool_result":
                    if pending_tool and pending_tool["tool"] == evt_data["tool"]:
                        pending_tool["result"] = evt_data["result"]
                        tool_calls.append(pending_tool)
                        pending_tool = None
                elif evt_type == "message_end":
                    usage = evt_data.get("usage", {})

                yield f"event: {evt_type}\ndata: {json.dumps(evt_data)}\n\n"

        except Exception as e:
            yield f"event: error\ndata: {json.dumps({'error': str(e)})}\n\n"

        if pending_tool:
            tool_calls.append(pending_tool)

        full_text = "".join(full_text_parts)
        if full_text or tool_calls:
            metadata = {}
            if usage:
                metadata.update(usage)
            if tool_calls:
                metadata["tool_calls"] = tool_calls
            await chat_crud.add_message(
                db, conversation_id, "assistant", full_text,
                json.dumps(metadata, default=str) if metadata else None,
            )

        if not conv.get("title") and full_text:
            auto_title = data.content[:60].strip()
            if len(data.content) > 60:
                auto_title += "..."
            await chat_crud.update_conversation_title(db, conversation_id, auto_title)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
