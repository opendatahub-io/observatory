# Task: Run History UI

## Goal

Pipeline detail page: run history table and duration-over-time chart.

## Acceptance Criteria

- [ ] Run history table with columns: status, started, duration, ref, link to CI job
- [ ] Pagination controls
- [ ] Duration-over-time chart (Recharts or Chart.js), color-coded by status
- [ ] Fetches from `GET /api/pipelines/{slug}/runs`

## Files Likely Involved

- frontend/src/pages/PipelineDetail.tsx
- frontend/src/components/RunHistoryTable.tsx
- frontend/src/components/DurationChart.tsx

## Phase

2 — Pull Collector + Live Status

## Blocked By

- task-run-history-api.md

## Status

Pending
