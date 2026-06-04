# Task: OTEL Summary Artifact Parser

## Goal

Parse OTEL summary artifacts from CI jobs and populate `telemetry_summaries`.

## Acceptance Criteria

- [ ] Parse `otel-summary.json` artifact format (determine actual format from existing pipelines)
- [ ] Extract: total_tokens, input_tokens, output_tokens, cost_usd, model, skill_name, duration_ms
- [ ] Insert into `telemetry_summaries` with `source = 'artifact'`
- [ ] Associate with correct `pipeline_run_id`
- [ ] Handle format variations gracefully
- [ ] Tests with sample artifact data

## Files Likely Involved

- backend/collector/parsers/otel_summary.py
- tests/test_otel_parser.py

## Phase

3 — Artifact Scraping

## Blocked By

- task-gitlab-artifact-download.md

## Status

Pending
