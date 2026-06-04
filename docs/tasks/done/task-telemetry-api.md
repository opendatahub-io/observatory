# Task: Telemetry Query API

## Goal

API endpoints for querying aggregated telemetry data across pipelines.

## Acceptance Criteria

- [ ] `GET /api/telemetry/summary` — cross-pipeline token/cost/duration summary
- [ ] `GET /api/telemetry/trends` — time-series data filterable by pipeline, date range
- [ ] `GET /api/telemetry/cost` — cost breakdown by pipeline, model, skill
- [ ] `GET /api/telemetry/spans/{run_id}` — span detail for a specific run
- [ ] `GET /api/pipelines/{slug}/telemetry` — per-pipeline aggregated telemetry
- [ ] Tests

## Files Likely Involved

- backend/routers/telemetry.py
- backend/schemas/telemetry.py
- backend/crud/telemetry.py

## Phase

3 — Artifact Scraping

## Status

Pending
