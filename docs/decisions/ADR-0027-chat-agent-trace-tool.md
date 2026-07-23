# ADR-0027: Chat Agent Trace Query Tool

## Status

Accepted

## Context

The Observatory collects GitLab job traces for every CI pipeline run
(ADR-0020) and parses them into structured tables: `trace_events`
(commands, tool calls, errors, section markers), `trace_packages`
(installed RPMs and pip packages), and `trace_metadata` (container image,
runner version, exit code). The REST API exposes this data through
`/api/pipelines/{slug}/runs/{run_id}/trace` endpoints.

The chat agent has 21 tools covering pipelines, runs, claims, telemetry,
artifacts, vulnerabilities, and external systems. However, it has no tool
to query parsed trace data. When a user asks "why did this run fail?" or
"what tools did Claude call?", the agent cannot answer from the structured
trace tables. It can find that a `job_trace` artifact exists via
`query_artifacts`, but cannot access the parsed events, packages, or
metadata that would actually explain what happened.

This is the most common debugging question operators ask, and the data is
already collected and indexed.

## Decision

Add a `query_traces` tool to the chat agent that queries `trace_events`,
`trace_packages`, and `trace_metadata` for a given pipeline run.

### Tool interface

The tool accepts:
- `run_id` (required) -- pipeline run ID
- `query` -- one of `events`, `packages`, `metadata`, `summary`
- `event_type` (optional) -- filter events by type: `command`, `tool_call`,
  `error`, `section_start`, `section_end`
- `limit` (optional, default 50) -- max events to return

The `summary` query returns event counts by type, all metadata, and package
count in a single call, so the agent can get the high-level picture before
drilling into specific events.

### Implementation

- Add the tool definition and handler to `src/backend/chat/tools.py`
- Reuse existing CRUD functions from `src/backend/crud/traces.py`
  (`get_run_trace_events`, `get_run_trace_summary`) where they fit
- Update the system prompt in `src/backend/chat/agent.py` to mention
  trace query capabilities

### System prompt guidance

The agent should be told:
- Use `query_traces` with `query=summary` first to understand the shape
  of a run's trace before fetching individual events
- Filter by `event_type=error` to diagnose failures
- Filter by `event_type=tool_call` to understand what Claude did
- Combine with `query_runs` to find the run ID from a pipeline slug

## Consequences

Positive:
- The agent can answer "why did this run fail?" by querying error events
- The agent can show what Claude tools were called and in what order
- The agent can report what packages were installed in a run
- The agent can surface container image and runner metadata
- No new database tables or schema changes needed

Negative:
- One more tool in the tool list (22 total), marginal context cost
- Large traces (1000+ events) need the limit parameter to avoid
  exceeding the 15KB tool result truncation threshold
