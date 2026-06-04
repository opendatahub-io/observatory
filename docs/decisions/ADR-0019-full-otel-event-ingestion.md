# ADR-0019: Full OTEL Event Log Ingestion

## Status

Accepted

## Context

Each agentic CI job produces a `claude-otel.jsonl` file containing three data types:

1. **resourceMetrics** — cumulative counters for cost, tokens, active time, lines of code (currently ingested by `ingest-telemetry.py`)
2. **resourceLogs** — detailed event records capturing every action the agent takes (currently ignored)
3. No resourceSpans — the OTEL collector captures logs and metrics only, not distributed traces

The resourceLogs contain the full execution trace of each agent run. A single RFE assessment run (RHAIRFE, ~2.5 hours) produces ~23,000 event records across these event types:

| Event | Count/run | What it captures |
|-------|-----------|-----------------|
| `tool_decision` | ~7,600 | Every tool call — tool name, accept/reject, tool_use_id |
| `tool_result` | ~7,600 | Tool outcomes — success/fail, duration_ms, input/output byte sizes |
| `api_request` | ~5,800 | Every LLM API call — model, input/output/cache tokens, cost (micros), duration, query_source (main/subagent/sdk), skill/plugin attribution |
| `subagent_completed` | ~1,850 | Subagent lifecycle — total tokens, tool uses, duration, model, plugin |
| `compaction` | ~15 | Context window compactions — pre/post token counts, trigger, duration |
| `api_error` | rare | API failures — error message, duration, retry attempt |
| `plugin_loaded` | 1 | Which plugins were loaded at session start |
| `user_prompt` | 1 | Session start — prompt length, command name (content redacted) |
| `skill_activated` | 1 | Which skill was invoked, trigger type |

This data enables:
- **Tool usage analysis** — which tools does each pipeline use most? What's the failure rate? Which tools are slowest?
- **Subagent economics** — how much of the cost goes to subagents? How many are spawned? What's the token overhead?
- **API efficiency** — cache hit rates, tokens per request, cost per request, error rates
- **Compaction patterns** — how often does context overflow? How much is lost? Does this correlate with output quality?
- **Execution timeline** — reconstruct the full sequence of actions for any run

### What it does NOT capture

The OTEL event logs do not include:
- The actual text of model responses (reasoning, thinking blocks)
- The content of tool inputs (Bash commands, file contents)
- The content of tool outputs (command results, file reads)
- The conversation transcript

These live in `claude-stderr.log` (partial debug output) and the ephemeral stream-json output processed by `stream-claude.py` during the run. Neither is saved as a structured artifact.

## Decision

Extend `ingest-telemetry.py` (or create `ingest-otel-events.py`) to parse the resourceLogs from `claude-otel.jsonl` files and store them in new database tables.

### Database Schema

```sql
CREATE TABLE otel_events (
    id INTEGER PRIMARY KEY,
    pipeline_run_id INTEGER REFERENCES pipeline_runs(id) ON DELETE CASCADE,
    event_name TEXT NOT NULL,
    event_timestamp TEXT,
    event_sequence INTEGER,
    session_id TEXT,
    prompt_id TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_otel_events_run ON otel_events(pipeline_run_id);
CREATE INDEX idx_otel_events_name ON otel_events(event_name);

CREATE TABLE otel_event_attributes (
    id INTEGER PRIMARY KEY,
    event_id INTEGER REFERENCES otel_events(id) ON DELETE CASCADE,
    key TEXT NOT NULL,
    value TEXT
);
CREATE INDEX idx_otel_event_attrs ON otel_event_attributes(event_id);
```

The EAV (entity-attribute-value) pattern is used for attributes because each event type has different fields. This avoids a wide sparse table with 30+ nullable columns.

### Alternative: Typed event tables

For query performance on common access patterns, typed summary tables could be materialized:

```sql
CREATE TABLE otel_api_requests (
    id INTEGER PRIMARY KEY,
    pipeline_run_id INTEGER REFERENCES pipeline_runs(id) ON DELETE CASCADE,
    event_sequence INTEGER,
    model TEXT,
    input_tokens INTEGER,
    output_tokens INTEGER,
    cache_creation_tokens INTEGER,
    cache_read_tokens INTEGER,
    cost_usd_micros INTEGER,
    duration_ms INTEGER,
    query_source TEXT,
    skill_name TEXT,
    plugin_name TEXT
);

CREATE TABLE otel_tool_uses (
    id INTEGER PRIMARY KEY,
    pipeline_run_id INTEGER REFERENCES pipeline_runs(id) ON DELETE CASCADE,
    event_sequence INTEGER,
    tool_name TEXT,
    tool_use_id TEXT,
    decision TEXT,
    success BOOLEAN,
    duration_ms INTEGER,
    input_size_bytes INTEGER,
    result_size_bytes INTEGER
);

CREATE TABLE otel_subagents (
    id INTEGER PRIMARY KEY,
    pipeline_run_id INTEGER REFERENCES pipeline_runs(id) ON DELETE CASCADE,
    event_sequence INTEGER,
    agent_type TEXT,
    model TEXT,
    total_tokens INTEGER,
    total_tool_uses INTEGER,
    duration_ms INTEGER,
    plugin_name TEXT
);
```

Recommendation: start with the generic EAV schema for ingestion, add typed tables when specific query patterns emerge.

### Ingestion script

`scripts/ingest-otel-events.py` — walks `./var/artifacts/*/ci-jobs/*/claude-otel.jsonl`, parses resourceLogs, inserts events with attributes. Idempotent via pipeline_run_id check. `make ingest-otel-events` target.

### UI integration

- **Telemetry page**: tool usage breakdown (bar chart by tool name), subagent count/cost, API error rate
- **Pipeline detail page**: per-run event timeline (expandable to show tool calls and subagent spawns)
- **Dedicated trace explorer**: full event sequence for a single run, filterable by event type

### Scale considerations

- 69 OTEL files × ~23,000 events = ~1.6M event records
- ~3-5 attributes per event = ~5-8M attribute rows
- SQLite handles this fine for the current scale but the EAV query pattern will slow down with 10x growth
- At that point, migrate to typed tables or aggregate views

## Consequences

Positive:
- Full visibility into agent execution behavior — not just what it produced, but how it worked
- Tool failure analysis — identify unreliable tools before they cause pipeline failures
- Cost attribution — which skills/subagents drive the most cost per pipeline
- Compaction insights — understand context window pressure and its impact on output quality
- Foundation for anomaly detection — unusual tool patterns or API error spikes

Negative:
- 1.6M+ rows for 69 runs — significant DB growth
- EAV pattern is slow for complex queries — may need materialized views
- No model reasoning content — the "why" behind decisions remains invisible
- Event schema may change across Claude Code versions — parser needs to handle unknown attributes gracefully
