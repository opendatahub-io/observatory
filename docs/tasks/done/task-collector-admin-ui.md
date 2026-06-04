# Task: Collector Admin UI

## Goal

Admin page showing collector state per pipeline: last scrape time, errors, consecutive failure count.

## Acceptance Criteria

- [ ] Table of all pipelines with collector state columns
- [ ] Last collected timestamp, last error, consecutive failures
- [ ] Visual indicator for pipelines with collector problems
- [ ] Manual trigger button (calls `POST /api/collector/run`)
- [ ] Accessible from admin nav section

## Files Likely Involved

- frontend/src/pages/Admin.tsx
- frontend/src/components/CollectorStatus.tsx

## Phase

2 — Pull Collector + Live Status

## Status

Pending
