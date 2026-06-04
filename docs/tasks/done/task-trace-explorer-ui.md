# Task: Trace Explorer UI

## Goal

Visualize OTLP spans as a waterfall/flame chart for a specific pipeline run.

## Acceptance Criteria

- [ ] Span waterfall view showing nested spans with timing bars
- [ ] Span detail on click (attributes, status, duration)
- [ ] Filterable by pipeline, date range, status
- [ ] Accessible from pipeline detail page (link from run row) and from top-level nav
- [ ] Fetches from `GET /api/telemetry/spans/{run_id}`

## Files Likely Involved

- frontend/src/pages/TraceExplorer.tsx
- frontend/src/components/SpanWaterfall.tsx
- frontend/src/components/SpanDetail.tsx

## Phase

4 — OTLP Push Receiver

## Blocked By

- task-otlp-receiver-endpoint.md

## Status

Pending
