"""Tests for chat generation surviving client disconnect + stream reattach.

These exercise the pub/sub decoupling added in `backend.chat.stream_manager`
and the reworked `backend.routers.chat`:
  - `StreamSession` replays its buffer to a late subscriber, then streams live;
  - the assistant reply is persisted by the background generation even when no
    client is consuming the stream (the "hard disconnect" case);
  - the POST endpoint streams + persists + frees the session;
  - `GET /conversations/{id}/stream` replays a live generation, then continues;
  - a concurrent POST to a conversation already generating returns 409;
  - `GET /stream` for an idle conversation returns 204.

A fake `stream_chat_response` stands in for the LLM so no network/model is
needed. Note: httpx's ASGITransport buffers streaming responses, so tests drive
generation on its own timeline rather than reading mid-stream.
"""

from __future__ import annotations

import asyncio

import pytest

import backend.routers.chat as chat_mod
from backend.chat import stream_manager
from backend.chat.stream_manager import StreamSession
from backend.crud import chat as chat_crud
from backend.database import get_db

BASE = "/api/v1/chat"


@pytest.fixture
async def db(tmp_db):
    return await get_db()


async def _instant_stream(db, messages):
    """A fake LLM response: two text deltas then message_end."""
    yield {"event": "content_delta", "data": {"text": "Hello "}}
    yield {"event": "content_delta", "data": {"text": "world"}}
    yield {"event": "message_end", "data": {"usage": {"input_tokens": 1, "output_tokens": 2}}}


def _enable_chat(monkeypatch) -> None:
    monkeypatch.setattr(chat_mod.settings, "anthropic_api_key", "test-key")


# --------------------------------------------------------------------------- #
#  StreamSession pub/sub semantics                                            #
# --------------------------------------------------------------------------- #

@pytest.mark.asyncio
async def test_stream_session_replays_buffer_then_streams_live():
    session = StreamSession("c1")
    session.publish("a")
    session.publish("b")

    received: list[str] = []

    async def consume():
        async for chunk in session.subscribe():
            received.append(chunk)

    task = asyncio.create_task(consume())
    await asyncio.sleep(0)  # let subscribe() snapshot the buffer + register

    session.publish("c")
    session.finish()
    await asyncio.wait_for(task, timeout=1.0)

    # Replayed a, b (published before subscribe) then live c — no drops/dupes.
    assert received == ["a", "b", "c"]


@pytest.mark.asyncio
async def test_stream_session_subscribe_after_finish_gets_full_replay():
    session = StreamSession("c2")
    session.publish("x")
    session.publish("y")
    session.finish()

    received = [chunk async for chunk in session.subscribe()]
    assert received == ["x", "y"]


# --------------------------------------------------------------------------- #
#  Background generation persists independent of the client                    #
# --------------------------------------------------------------------------- #

@pytest.mark.asyncio
async def test_generation_persists_with_no_subscriber(db, monkeypatch):
    """The strongest form of disconnect: nobody ever reads the stream."""
    monkeypatch.setattr(chat_mod, "stream_chat_response", _instant_stream)
    conv = await chat_crud.create_conversation(db, None)

    session = stream_manager.register_session(conv["id"])
    await chat_mod._run_generation(session, db, conv["id"], [], "hi there", None)

    msgs = await chat_crud.get_messages(db, conv["id"])
    assistant = [m for m in msgs if m["role"] == "assistant"]
    assert assistant, "reply should persist even with zero subscribers"
    assert assistant[0]["content"] == "Hello world"
    # Session freed and auto-title set.
    assert stream_manager.get_session(conv["id"]) is None
    conv_row = await chat_crud.get_conversation(db, conv["id"])
    assert conv_row["title"] == "hi there"


@pytest.mark.asyncio
async def test_send_message_streams_and_persists(client, db, monkeypatch):
    _enable_chat(monkeypatch)
    monkeypatch.setattr(chat_mod, "stream_chat_response", _instant_stream)
    conv = await chat_crud.create_conversation(db, None)

    resp = await client.post(
        f"{BASE}/conversations/{conv['id']}/messages", json={"content": "hi"}
    )
    assert resp.status_code == 200
    assert "message_start" in resp.text
    assert "message_end" in resp.text

    msgs = await chat_crud.get_messages(db, conv["id"])
    assert any(m["role"] == "assistant" and m["content"] == "Hello world" for m in msgs)
    # Session cleaned up after completion.
    assert stream_manager.get_session(conv["id"]) is None


# --------------------------------------------------------------------------- #
#  Reattach endpoint                                                           #
# --------------------------------------------------------------------------- #

@pytest.mark.asyncio
async def test_attach_endpoint_replays_then_continues(client, db):
    conv = await chat_crud.create_conversation(db, None)
    session = stream_manager.register_session(conv["id"])
    session.publish("event: message_start\ndata: {}\n\n")
    session.publish('event: content_delta\ndata: {"text": "Hello"}\n\n')

    async def finisher():
        await asyncio.sleep(0.05)
        session.publish('event: content_delta\ndata: {"text": "world"}\n\n')
        session.publish("event: message_end\ndata: {}\n\n")
        stream_manager.remove_session(conv["id"])
        session.finish()

    task = asyncio.create_task(finisher())
    resp = await client.get(f"{BASE}/conversations/{conv['id']}/stream")
    await asyncio.wait_for(task, timeout=1.0)

    assert resp.status_code == 200
    body = resp.text
    assert "message_start" in body  # replayed from buffer
    assert "Hello" in body          # replayed delta
    assert "world" in body          # live continuation after attach
    assert "message_end" in body


@pytest.mark.asyncio
async def test_stream_idle_returns_204(client, db):
    conv = await chat_crud.create_conversation(db, None)
    resp = await client.get(f"{BASE}/conversations/{conv['id']}/stream")
    assert resp.status_code == 204


# --------------------------------------------------------------------------- #
#  409 while a generation is already running                                   #
# --------------------------------------------------------------------------- #

@pytest.mark.asyncio
async def test_concurrent_send_returns_409(client, db, monkeypatch):
    _enable_chat(monkeypatch)
    conv = await chat_crud.create_conversation(db, None)
    # Simulate an in-flight generation for this conversation.
    stream_manager.register_session(conv["id"])
    try:
        resp = await client.post(
            f"{BASE}/conversations/{conv['id']}/messages", json={"content": "again"}
        )
        assert resp.status_code == 409
    finally:
        stream_manager.remove_session(conv["id"])

    # Once idle again, a new send is accepted.
    monkeypatch.setattr(chat_mod, "stream_chat_response", _instant_stream)
    resp2 = await client.post(
        f"{BASE}/conversations/{conv['id']}/messages", json={"content": "hi"}
    )
    assert resp2.status_code == 200
