# Task: Run History API

## Goal

Paginated API for pipeline run history.

## Acceptance Criteria

- [ ] `GET /api/pipelines/{slug}/runs` returns paginated run list
- [ ] Filter by status, date range
- [ ] Sort by started_at (newest first default)
- [ ] Response includes: external_id, status, started_at, finished_at, duration_seconds, ref, web_url
- [ ] Tests

## Files Likely Involved

- backend/routers/runs.py
- backend/schemas/runs.py
- backend/crud/runs.py

## Phase

2 — Pull Collector + Live Status

## Status

Pending
