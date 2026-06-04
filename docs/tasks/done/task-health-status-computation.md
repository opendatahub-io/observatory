# Task: Health Status Computation

## Goal

Implement the green/yellow/red/grey health status logic and expose it via API.

## Context

Health status is computed from run history: last success time, failure streaks, failure rate over last N runs, and schedule adherence. See PLAN.md "Health Status Logic" section for the full specification.

## Acceptance Criteria

- [ ] Health computation function that takes a pipeline + its recent runs and returns green/yellow/red/grey
- [ ] `GET /api/pipelines/{slug}/health` returns computed status with details
- [ ] Health status included in `GET /api/pipelines` list response
- [ ] Tests covering all four status levels and edge cases (no runs, no expected interval, etc.)

## Files Likely Involved

- backend/health.py
- backend/routers/pipelines.py (add health field to responses)
- tests/test_health.py

## Phase

2 — Pull Collector + Live Status

## Blocked By

- task-gitlab-ci-integration.md (needs run data to compute against)

## Status

Pending
