"""Tests for is_error propagation in the chat tool-use loop.

When a tool returns an ``{"error": ...}`` object the agent must flag it as a
failure in two places:
  1. the yielded ``tool_result`` SSE event (so the router records the block as
     "failed" and the UI renders it as such rather than a green check), and
  2. the Anthropic ``tool_result`` content block (``is_error: True``) fed back to
     the model, so it can course-correct instead of retrying a call it believes
     succeeded.

The Anthropic client is faked so no network/model is needed.
"""

from __future__ import annotations

import types

import pytest

import backend.chat.agent as agent
from backend.database import get_db


@pytest.fixture
async def db(tmp_db):
    return await get_db()


# --------------------------------------------------------------------------- #
#  Fakes for the Anthropic streaming client                                   #
# --------------------------------------------------------------------------- #

def _usage():
    return types.SimpleNamespace(input_tokens=1, output_tokens=2)


def _tool_use(block_id, name, tool_input):
    return types.SimpleNamespace(type="tool_use", id=block_id, name=name, input=tool_input)


def _text(text):
    return types.SimpleNamespace(type="text", text=text)


class _FakeStream:
    def __init__(self, final_message):
        self._final = final_message

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    def __aiter__(self):
        async def _gen():
            return
            yield  # pragma: no cover - makes this an async generator

        return _gen()

    async def get_final_message(self):
        return self._final


class _FakeMessages:
    def __init__(self, finals):
        self._finals = finals
        self._i = 0
        self.calls: list[dict] = []

    def stream(self, **kwargs):
        self.calls.append(kwargs)
        final = self._finals[self._i]
        self._i += 1
        return _FakeStream(final)


class _FakeClient:
    def __init__(self, finals):
        self.messages = _FakeMessages(finals)


def _install_client(monkeypatch, finals) -> _FakeClient:
    client = _FakeClient(finals)
    monkeypatch.setattr(agent, "_get_client", lambda: client)
    return client


def _collect_tool_result(events):
    return [e for e in events if e["event"] == "tool_result"]


def _api_tool_result_block(client: _FakeClient):
    """The tool_result content block sent back to the model in round 2."""
    second_call_messages = client.messages.calls[1]["messages"]
    for msg in second_call_messages:
        if msg["role"] == "user" and isinstance(msg["content"], list):
            for block in msg["content"]:
                if isinstance(block, dict) and block.get("type") == "tool_result":
                    return block
    raise AssertionError("no tool_result block was fed back to the model")


# --------------------------------------------------------------------------- #
#  Tests                                                                       #
# --------------------------------------------------------------------------- #

@pytest.mark.asyncio
async def test_errored_tool_marks_is_error(db, monkeypatch):
    # Round 1: model calls a tool. Round 2: model answers (no tool use → stop).
    finals = [
        types.SimpleNamespace(content=[_tool_use("t1", "query_claims", {})], usage=_usage()),
        types.SimpleNamespace(content=[_text("done")], usage=_usage()),
    ]
    client = _install_client(monkeypatch, finals)
    monkeypatch.setattr(agent, "execute_tool", _err_result)

    events = [e async for e in agent.stream_chat_response(db, [{"role": "user", "content": "hi"}])]

    results = _collect_tool_result(events)
    assert len(results) == 1
    assert results[0]["data"]["is_error"] is True

    block = _api_tool_result_block(client)
    assert block["is_error"] is True


@pytest.mark.asyncio
async def test_successful_tool_is_not_error(db, monkeypatch):
    finals = [
        types.SimpleNamespace(content=[_tool_use("t1", "query_claims", {})], usage=_usage()),
        types.SimpleNamespace(content=[_text("done")], usage=_usage()),
    ]
    client = _install_client(monkeypatch, finals)
    monkeypatch.setattr(agent, "execute_tool", _ok_result)

    events = [e async for e in agent.stream_chat_response(db, [{"role": "user", "content": "hi"}])]

    results = _collect_tool_result(events)
    assert len(results) == 1
    assert results[0]["data"]["is_error"] is False

    block = _api_tool_result_block(client)
    assert block["is_error"] is False


async def _err_result(*a, **k):
    return '{"error": "boom"}'


async def _ok_result(*a, **k):
    return '{"rows": [1, 2, 3]}'
