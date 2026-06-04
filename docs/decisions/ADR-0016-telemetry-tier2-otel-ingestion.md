# ADR-0016: Telemetry Tier 2 — OTEL Telemetry Ingestion from Artifacts

## Status

Accepted

## Context

Each agentic CI job produces a `claude-otel.jsonl` file as a CI artifact. These files contain OpenTelemetry metrics emitted by Claude Code during execution, captured by a local OTEL collector (`otel-collector.py`) running alongside the agent. The collection script (`scripts/collect-artifacts.py`) already downloads these files to `./var/artifacts/{slug}/ci-jobs/{pipeline-id}/{job-id}/claude-otel.jsonl` — 69 files are on disk.

The OTEL JSONL format contains cumulative metric data points with these metric names:

| Metric | Type | Description |
|--------|------|-------------|
| `claude_code.cost.usage` | Counter (cumulative) | USD cost of the run |
| `claude_code.token.usage` | Counter (cumulative) | Token count (with `token.type` attribute for input/output) |
| `claude_code.active_time.total` | Gauge | Milliseconds of active agent processing |
| `claude_code.lines_of_code.count` | Counter | Lines of code read/written |
| `claude_code.code_edit_tool.decision` | Counter | Number of code edit decisions |
| `claude_code.session.count` | Gauge | Number of Claude sessions in the run |

Each file has hundreds of data points (cumulative snapshots every ~10s). The final value (max) of each metric represents the run total.

## Decision

Create a standalone ingestion script `scripts/ingest-telemetry.py` that:

1. Walks `./var/artifacts/*/ci-jobs/*/claude-otel.jsonl`
2. For each file, extracts the final (max) value of each metric
3. Links to the corresponding `pipeline_runs` row via the pipeline slug + external_id (the GitLab pipeline ID is in the directory path)
4. Inserts into the existing `telemetry_summaries` table:
   - `total_tokens` — max of `claude_code.token.usage`
   - `cost_usd` — max of `claude_code.cost.usage`
   - `duration_ms` — `claude_code.active_time.total`
   - `model` — extracted from OTEL resource attributes if available
   - `source` — `'artifact'`
5. Idempotent — skips runs that already have a telemetry summary row

### Makefile target

`make ingest-telemetry`

### Telemetry page additions (Tier 2 data)

Once `telemetry_summaries` is populated:

**Summary cards:**
- Total cost (sum of `cost_usd`)
- Total tokens (sum of `total_tokens`)
- Average cost per run
- Average active time per run

**Trend charts:**
- Daily cost trend (already exists, will now have data)
- Daily token usage trend (already exists)
- Cost per run over time (scatter or line)
- Active time vs wall-clock duration (efficiency ratio)

**Breakdown tables:**
- Cost by pipeline (already exists)
- Tokens by pipeline
- Cost per successful run vs failed run
- Lines of code changed by pipeline

## Consequences

Positive:
- Cost and token visibility — the primary telemetry stakeholders care about
- Active time vs duration ratio shows how much time is agent work vs waiting/setup
- Cost breakdown enables budget tracking and per-pipeline cost attribution
- Uses existing `telemetry_summaries` table — no schema changes needed
- Existing telemetry API endpoints and frontend charts will populate automatically

Negative:
- Requires running `make collect-artifacts` first to download the OTEL files
- Cumulative metric extraction (take max value) may miss edge cases with counter resets
- Only captures aggregate per-run metrics — individual span-level telemetry (which tools were called, how long each took) would require parsing the `resourceSpans` entries, which is deferred
- OTEL format may vary across Claude Code versions — parser needs to handle missing fields gracefully
