# Task: Status Board UI

## Goal

Implement the pipeline status board — a card grid showing all pipelines with health indicators, schedule info, and key stats.

## Context

This is the landing page. Initially all cards are grey (no run data). Cards will get colored health dots when the collector is wired up in Phase 2.

## Acceptance Criteria

- [ ] Card grid layout, responsive
- [ ] Each card shows: name, schedule, last run info, success rate, token/cost summary, owner, skills
- [ ] Health indicator dot (grey initially)
- [ ] Sort by health (red first) and filter by status/owner/platform
- [ ] Cards link to pipeline detail page
- [ ] Fetches data from `GET /api/pipelines`

## Files Likely Involved

- frontend/src/pages/StatusBoard.tsx
- frontend/src/components/PipelineCard.tsx

## Phase

1 — Core API + Static Inventory

## Blocked By

- task-react-app-shell.md
- task-pipeline-crud-api.md

## Status

Pending
