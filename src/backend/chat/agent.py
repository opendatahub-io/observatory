from __future__ import annotations

import json
from collections.abc import AsyncIterator

import aiosqlite
import anthropic

from backend.chat.tools import TOOL_DEFINITIONS, execute_tool
from backend.config import settings
from backend.crud.data_sources import get_active_sources_summary

_BASE_SYSTEM_PROMPT = """\
You are Observatory Assistant, an AI helper for the Agentic CI Observatory platform.
You help users understand their CI/CD pipeline data, including pipeline status, run
history, test claims and hallucination detection, telemetry and cost analysis,
vulnerability scanning, and knowledge base articles.

You have access to tools that query Observatory's database. Always use tools to get
current data rather than guessing. When presenting data, be concise and use markdown
formatting (tables, lists, bold for emphasis).

If you discover recurring questions that would benefit from a knowledge base article,
use the kb_suggest tool to propose one.

You can browse and read files from two mounted directories:

/app/.context — Architecture context documents (READMEs, design docs, repo maps)

/app/artifacts — Pipeline output artifacts organized by type:
  strace/    — Agent execution traces. Subdirs named by run: {phase}-{jira_key} (e.g. strace/rfe-speedrun-RHAIRFE-2343/)
  claims/    — Extracted claims from pipeline runs
  verification/ — Claim verification results
  explanations/ — Claim explanations
  jobs/      — K8s job logs
  apibodies/ — Raw API request/response bodies

When asked about a specific Jira issue or pipeline run, use browse_files to find the
relevant subdirectory under /app/artifacts/ then read_file to inspect individual files.
Always browse first to discover what exists rather than guessing paths."""


async def _build_system_prompt(db) -> str:
    sources = await get_active_sources_summary(db)
    if not sources:
        return _BASE_SYSTEM_PROMPT
    lines = []
    for s in sources:
        parts = [f"- **{s['name']}** ({s['source_type']})"]
        if s.get("description"):
            parts.append(f": {s['description']}")
        if s.get("endpoint"):
            parts.append(f" — {s['endpoint']}")
        lines.append("".join(parts))
    supplement = (
        "\n\nConfigured external data sources in this Observatory deployment:\n"
        + "\n".join(lines)
        + "\n\nUse the query_data_sources tool for full details. Reference these "
        "sources by name when users ask about external systems."
    )
    return _BASE_SYSTEM_PROMPT + supplement

MAX_TOOL_ROUNDS = 10


def _get_client() -> anthropic.AsyncAnthropic:
    if settings.anthropic_vertex_project_id:
        return anthropic.AsyncAnthropicVertex(
            project_id=settings.anthropic_vertex_project_id,
            region=settings.cloud_ml_region,
        )
    return anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)


async def stream_chat_response(
    db: aiosqlite.Connection, messages: list[dict]
) -> AsyncIterator[dict]:
    """Async generator that yields SSE event dicts.

    Handles the tool-use loop: streams text from the model, executes any
    tool_use blocks, feeds results back, and continues streaming.
    """
    client = _get_client()
    system_prompt = await _build_system_prompt(db)

    api_messages = _to_api_messages(messages)

    for _round in range(MAX_TOOL_ROUNDS):
        text_parts: list[str] = []

        async with client.messages.stream(
            model=settings.chat_model,
            max_tokens=4096,
            system=system_prompt,
            messages=api_messages,
            tools=TOOL_DEFINITIONS,
        ) as stream:
            async for event in stream:
                if event.type == "content_block_delta":
                    if event.delta.type == "text_delta":
                        text_parts.append(event.delta.text)
                        yield {"event": "content_delta", "data": {"text": event.delta.text}}

            response = await stream.get_final_message()

        tool_use_blocks = [b for b in response.content if b.type == "tool_use"]

        if not tool_use_blocks:
            yield {
                "event": "message_end",
                "data": {
                    "usage": {
                        "input_tokens": response.usage.input_tokens,
                        "output_tokens": response.usage.output_tokens,
                    }
                },
            }
            return

        api_messages.append({"role": "assistant", "content": _serialize_content(response.content)})

        tool_results = []
        for block in tool_use_blocks:
            yield {"event": "tool_use", "data": {"tool": block.name, "input": block.input}}
            result_str = await execute_tool(db, block.name, block.input)
            result_data = json.loads(result_str)
            yield {"event": "tool_result", "data": {"tool": block.name, "result": result_data}}
            tool_results.append(
                {"type": "tool_result", "tool_use_id": block.id, "content": result_str}
            )

        api_messages.append({"role": "user", "content": tool_results})

    yield {"event": "message_end", "data": {"usage": {}}}


def _to_api_messages(messages: list[dict]) -> list[dict]:
    """Convert stored messages to Anthropic API format."""
    api_msgs: list[dict] = []
    for msg in messages:
        role = msg["role"]
        content = msg["content"]
        if role in ("user", "assistant"):
            api_msgs.append({"role": role, "content": content})
    return api_msgs


def _serialize_content(content_blocks) -> list[dict]:
    """Serialize Anthropic content blocks to plain dicts for the messages list."""
    result = []
    for block in content_blocks:
        if block.type == "text":
            result.append({"type": "text", "text": block.text})
        elif block.type == "tool_use":
            result.append({"type": "tool_use", "id": block.id, "name": block.name, "input": block.input})
    return result
