from __future__ import annotations

import json
from collections.abc import AsyncIterator

import aiosqlite
import anthropic

from pathlib import Path

from backend.chat.tools import TOOL_DEFINITIONS, execute_tool
from backend.config import settings
from backend.crud.data_sources import get_active_sources_summary

_BASE_SYSTEM_PROMPT = """\
You are Observatory Assistant, an AI helper for the Agentic CI Observatory platform.
You help users understand their CI/CD pipeline data, including pipeline status, run
history, claim assurance and verification, telemetry and cost analysis,
vulnerability scanning, and knowledge base articles.

You have access to tools that query Observatory's database. Always use tools to get
current data rather than guessing. When presenting data, be concise and use markdown
formatting (tables, lists, bold for emphasis).

## Claim Assurance v2

Claim Assurance v2 is authoritative for current claim questions. Key concepts:

- A **normalized claim** is reusable text identity (deduplicated). A **claim
  occurrence** is a specific assertion in a specific source file. User-facing
  "claim number" means occurrence ID unless the user explicitly says normalized.
- **Effective results** are the newest verification and explanation runs,
  selected by the backend. Older runs are immutable audit history.
- **Canonical verdicts**: supported, contradicted, insufficient_evidence,
  not_applicable. "pending" means no verification run exists yet.
- **Human overrides** are governance decisions that control progression (e.g.
  accepting or dismissing a finding). They do NOT replace or rewrite the
  effective factual verdict.
- An absent explanation means no causal explanation run has been performed.
  Do not invent or guess a root cause when none is recorded.

When the user asks "why" about a claim, requests evidence, asks about a changed
verdict, or names a specific occurrence, call get_claim_occurrence_history after
query_claims to get the full verification and explanation audit trail.

Prefer structured claim tools (query_claims, get_claim_occurrence_history,
query_claim_explanations, get_claim_assurance_summary) over browsing artifact
files. Use file tools only for forensic context not represented in the database.

Use query_github to query the GitHub emulator for repositories, branches,
commits, pull requests, file contents, or code/issue search. It requires a
github_emulator data source configured in Intelligence Settings.

If you discover recurring questions that would benefit from a knowledge base article,
use the kb_suggest tool to propose one.

You have a limited number of tool-use rounds per response. Plan your tool calls
efficiently — combine what you can, avoid redundant searches, and synthesize your
answer as soon as you have enough data rather than exhaustively searching.

You have browse_files and read_file tools for exploring mounted directories.
IMPORTANT: Always call browse_files FIRST to discover what directories and files
actually exist. Never assume a path exists — verify by browsing. Start from the
top-level allowed roots and drill down.

Known artifact directory conventions (subdirs may or may not be present):
  strace/    — Agent execution traces. Subdirs named: {phase}-{jira_key} (e.g. strace/rfe-speedrun-RHAIRFE-2343/)
  claims/    — Extracted claims from pipeline runs
  verification/ — Claim verification results
  explanations/ — Claim explanations
  jobs/      — K8s job logs
  apibodies/ — Raw API request/response bodies"""


async def _build_system_prompt(db) -> str:
    prompt = _BASE_SYSTEM_PROMPT

    roots = [p.strip() for p in settings.chat_browse_roots.split(",") if p.strip()]
    existing = [r for r in roots if Path(r).is_dir()]
    if existing:
        prompt += "\n\nAllowed browse/read directories (confirmed present on disk):\n"
        prompt += "\n".join(f"  - {r}" for r in existing)
        missing = [r for r in roots if r not in existing]
        if missing:
            prompt += "\n\nConfigured but NOT present on disk (do not try to browse):\n"
            prompt += "\n".join(f"  - {r}" for r in missing)
    elif roots:
        prompt += "\n\nNote: No configured browse directories exist on disk yet. "
        prompt += f"Configured roots: {', '.join(roots)}"

    sources = await get_active_sources_summary(db)
    if not sources:
        return prompt
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
    return prompt + supplement

MAX_TOOL_ROUNDS = 50
MAX_TOOL_RESULT_CHARS = 15_000


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
            truncated = len(result_str) > MAX_TOOL_RESULT_CHARS
            if truncated:
                result_str = json.dumps({
                    "error": "Result truncated — too large for chat context",
                    "preview": result_str[:MAX_TOOL_RESULT_CHARS],
                })
            result_data = json.loads(result_str)
            yield {"event": "tool_result", "data": {"tool": block.name, "result": result_data}}
            tool_results.append(
                {"type": "tool_result", "tool_use_id": block.id, "content": result_str}
            )

        api_messages.append({"role": "user", "content": tool_results})

    api_messages.append({
        "role": "user",
        "content": (
            "[SYSTEM: Tool-use round limit reached. You MUST now provide your "
            "final answer using the data you have already collected. Do NOT "
            "request any more tool calls. Summarize your findings clearly.]"
        ),
    })
    async with client.messages.stream(
        model=settings.chat_model,
        max_tokens=4096,
        system=system_prompt,
        messages=api_messages,
    ) as stream:
        async for event in stream:
            if event.type == "content_block_delta":
                if event.delta.type == "text_delta":
                    yield {"event": "content_delta", "data": {"text": event.delta.text}}
        final = await stream.get_final_message()

    yield {
        "event": "message_end",
        "data": {
            "usage": {
                "input_tokens": final.usage.input_tokens,
                "output_tokens": final.usage.output_tokens,
            }
        },
    }


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
