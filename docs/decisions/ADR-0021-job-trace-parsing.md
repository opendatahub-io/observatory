# ADR-0021: Job Trace Parsing and Structured Event Extraction

## Status

Accepted

## Context

ADR-0020 established collection of GitLab job traces to `./var/artifacts/{slug}/ci-jobs/{pid}/{jid}/job-trace.log`. These traces contain the complete execution record of each CI job — from runner setup through agent reasoning to artifact upload. ADR-0019 covers the structured OTEL JSON events which are a separate, complementary data source.

Job traces are semi-structured text with GitLab CI formatting (timestamps, stream identifiers, section markers) and emoji-delimited Claude output from `stream-claude.py`. Unlike OTEL events (structured JSON), job traces require a custom parser that understands the line format and handles multi-line content blocks.

### Format

Each line follows: `{ISO-timestamp} {stream-id} {content}`

Where `stream-id` is `00O` (runner stdout), `01O` (job stdout), `01E` (job stderr), and `00O+` (section boundaries).

### Content Phases

A job trace contains distinct phases with different data types:

| Phase | Lines | Data Type | Observatory Section |
|-------|-------|-----------|-------------------|
| **Runner setup** | ~17 | GitLab runner version, Docker image pull, git checkout | Pipeline detail → CI Configuration |
| **Package install** | ~35 | `microdnf install` packages, `pip install` dependencies | Provenance → runtime packages |
| **Claude install** | ~5 | Claude Code version, install method | Pipeline detail → tooling |
| **Environment setup** | ~9 | Plugin clones, data repo clones, before_script commands | Pipeline detail → execution context |
| **OTEL setup** | ~2 | Collector start | Telemetry |
| **Agent thinking** | ~40 | `🧠 Thinking ...` — model reasoning blocks (multi-line) | Trace explorer / hallucination root cause |
| **Agent responses** | ~150 | `💬 Claude ...` — model's spoken decisions | Trace explorer |
| **Tool calls** | ~400 | `🔧 Bash $ {command}` — actual commands executed | Trace explorer / provenance |
| **Subagent spawns** | ~1,900 | `🤖 Agent [{skill}:{agent}] {prompt}` — subagent launches | Telemetry → subagent analysis |
| **Agent output** | ~240 | Continuation lines, variable dumps, progress | Trace explorer |
| **Cost summary** | ~7 | Token counts, cost breakdown per model | Telemetry |
| **Results push** | ~77 | Data repo push, org-pulse sync | Collector |
| **Artifact upload** | ~7 | ZIP upload to GitLab | Collector |

### Per-Pipeline Variations

Each pipeline produces a different trace profile:

| Pipeline | Execution Model | Key Differences |
|----------|----------------|-----------------|
| **rfe-assessor** | Direct install + subagent batch | 1,900 `🤖` subagent spawns, heavy tool calls, multi-batch orchestration |
| **rfe-autofixer** | Direct install + subagent batch | Similar to assessor, different skill/prompt |
| **strat-pipeline** | Direct install + Claude | Fewer subagents (~2), more direct tool calls, strat-originals processing |
| **strat-security-reviews** | Direct install + Python orchestrator | Uses `run-batch.py` instead of Claude directly, minimal emoji output, `runuser` execution |
| **autofix** | Pre-built podman image + `agentic-ci` CLI | No `setup-claude-ci.sh`, pip installs from `pyproject.toml`, podman-based execution, `child-pipeline.yml` generation |
| **epic-decomposer** | Direct install | Similar to rfe-assessor pattern |

### Key Observations

1. **Not all pipelines use emoji-delimited output.** `strat-security-reviews` uses `run-batch.py` which orchestrates Claude externally — the trace shows the Python orchestrator's output, not Claude's stream.
2. **autofix uses a different base image** (`quay.io/aipcc/agentic-ci/podman:latest`) with pre-installed tools — its package install section shows `pip install .` from `pyproject.toml` rather than `microdnf`.
3. **Package lists differ per pipeline** — each installs different system packages and Python dependencies at runtime.
4. **The `🤖 Agent` lines contain the subagent prompt** — for rfe-assessor, each line includes the Jira key being assessed: `🤖 Agent [assess-rfe:rfe-scorer] Assess RHAIRFE-1234`.

## Decision

Create a job trace parser (`scripts/parse-job-traces.py`) that extracts structured events from trace files and stores them in the database. The parser handles per-pipeline format differences via a common line classifier with pipeline-specific post-processing.

### Extracted Data and Observatory Mapping

| Extracted Data | Source Line Pattern | DB Table | Observatory Section |
|---------------|-------------------|----------|-------------------|
| System packages installed | `Installing: {pkg};{version}` | `trace_packages` | Provenance |
| Python packages installed | `Collecting {pkg}=={version}`, `Downloading {pkg}` | `trace_packages` | Provenance |
| Claude Code version | `{version} (Claude Code)` | `trace_metadata` | Pipeline detail |
| Container image + digest | `Using docker image sha256:{hash}` | `trace_metadata` | Pipeline detail → images |
| Runner ID + region | `Running on runner-{id}-{region}` | `trace_metadata` | Pipeline detail → runners |
| Tool calls with commands | `🔧 {tool} $ {command}` | `trace_tool_calls` | Trace explorer |
| Thinking blocks | `🧠 Thinking {text}` (multi-line) | `trace_reasoning` | Trace explorer / hallucination analysis |
| Agent responses | `💬 Claude {text}` | `trace_reasoning` | Trace explorer |
| Subagent spawns | `🤖 Agent [{skill}:{agent}] {prompt}` | `trace_subagents` | Telemetry → subagent detail |
| Token/cost summary | `input {N}`, `cacheRead {N}`, `Total cost: ${N}` | `telemetry_summaries` (existing) | Telemetry |
| Git operations | `Cloning into`, `Checking out {sha}` | `trace_metadata` | Pipeline detail |
| Exit code | `Claude exit code: {N}` | `trace_metadata` | Pipeline detail |

### Database Schema

```sql
CREATE TABLE trace_events (
    id INTEGER PRIMARY KEY,
    pipeline_run_id INTEGER REFERENCES pipeline_runs(id) ON DELETE CASCADE,
    timestamp TEXT,
    event_type TEXT NOT NULL,
    content TEXT,
    line_number INTEGER
);
CREATE INDEX idx_trace_events_run ON trace_events(pipeline_run_id);
CREATE INDEX idx_trace_events_type ON trace_events(event_type);

CREATE TABLE trace_packages (
    id INTEGER PRIMARY KEY,
    pipeline_run_id INTEGER REFERENCES pipeline_runs(id) ON DELETE CASCADE,
    manager TEXT NOT NULL,
    name TEXT NOT NULL,
    version TEXT,
    source TEXT
);
CREATE INDEX idx_trace_packages_run ON trace_packages(pipeline_run_id);

CREATE TABLE trace_metadata (
    id INTEGER PRIMARY KEY,
    pipeline_run_id INTEGER REFERENCES pipeline_runs(id) ON DELETE CASCADE,
    key TEXT NOT NULL,
    value TEXT NOT NULL,
    UNIQUE(pipeline_run_id, key)
);
```

`trace_events` uses a generic schema — each line becomes an event with a classified `event_type` (thinking, response, tool_call, subagent, pkg_install, etc.). This avoids per-type tables while still enabling queries like "show all thinking blocks for run X" or "count tool calls by pipeline."

`trace_packages` captures the runtime dependency install — both system packages (microdnf) and Python packages (pip). This feeds into Provenance alongside the static `pyproject.toml` data from `./var/definitions/`.

`trace_metadata` captures per-run key-value facts: Claude version, runner ID, container image digest, git SHA, exit code.

### Implementation Phases

**Phase 1: Parser + events**
- `scripts/parse-job-traces.py` — line classifier, multi-line block handler, DB inserter
- Generic `trace_events` table
- `make parse-traces` target

**Phase 2: Package extraction**
- Parse `Installing:` and `Collecting` lines into `trace_packages`
- Feed into Provenance page alongside static dependency data

**Phase 3: Metadata extraction**
- Extract Claude version, runner, image digest, exit code into `trace_metadata`
- Show on pipeline detail page

**Phase 4: UI integration**
- Trace explorer: timeline view of events for a single run
- Provenance: runtime packages tab
- Telemetry: subagent spawn visualization

## Consequences

Positive:
- Complete execution visibility — what the agent thought, what it ran, what packages were installed
- Runtime provenance — actual packages installed vs declared dependencies (drift detection)
- Hallucination root cause — trace from refuted claim → agent reasoning that produced it
- Subagent analysis — which Jira keys were processed, how many subagents per run

Negative:
- Semi-structured text parsing is fragile — format changes in `stream-claude.py` or CI scripts break the parser
- Per-pipeline variations require format-specific handling
- Multi-line blocks (thinking) need stateful parsing
- Large data volume — 86 traces × ~3,000 lines = ~260k events
- Not all pipelines emit emoji-delimited output (strat-security-reviews uses a Python orchestrator)
