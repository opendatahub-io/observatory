# ADR-0015: Telemetry Tier 1 — Run-Level Metrics from Pipeline Runs

## Status

Accepted

## Context

The telemetry page currently shows empty charts because it depends on `telemetry_summaries` (token/cost data parsed from OTEL artifacts), which has zero rows. Meanwhile, the `pipeline_runs` table has 971 rows with rich operational data that's not surfaced anywhere in aggregate: run durations, queue wait times, success/failure rates, and run frequency.

This data is already collected by the existing collector — no new parsing or ingestion is needed.

## Decision

Populate the telemetry page with aggregate metrics derived from `pipeline_runs` and `ci_job_tags`:

### Metrics to expose

**Summary cards:**
- Total runs (all time / filtered period)
- Average run duration
- Average queue time
- Overall success rate

**Trend charts:**
- Run duration over time (per pipeline, daily aggregates)
- Queue wait time over time (identifies runner contention)
- Success rate over time (rolling window)
- Runs per day (throughput/volume)

**Breakdown tables:**
- Duration by pipeline (avg, p50, p95, max)
- Queue time by pipeline
- Success rate by pipeline
- Runner tag utilization (from `ci_job_tags` — which tags have the most jobs, which pipelines share runners)

### API endpoints

- `GET /api/telemetry/run-metrics` — summary cards (total runs, avg duration, avg queue, success rate)
- `GET /api/telemetry/run-trends` — time-series data (duration, queue, success rate by day)
- `GET /api/telemetry/run-breakdown` — per-pipeline breakdown

All endpoints accept `?since=` and `?until=` date filters, and optional `?pipeline=` filter.

## Consequences

Positive:
- Telemetry page is immediately useful with data we already have
- No new collection, parsing, or ingestion scripts needed
- Queue time visibility helps identify runner contention
- Duration trends help detect pipeline performance regressions
- Runs per day shows system throughput and capacity usage

Negative:
- Doesn't include cost/token data — that requires Tier 2 (OTEL parsing)
- Aggregate queries on `pipeline_runs` may slow down as the table grows — add indexes if needed
