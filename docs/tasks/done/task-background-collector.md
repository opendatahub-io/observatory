# Task: Background Collector Framework

## Goal

Implement the async background collector that runs on a schedule inside the FastAPI process. This is the framework — platform-specific integrations are separate tasks.

## Acceptance Criteria

- [ ] Runs as a FastAPI lifespan background task or via APScheduler
- [ ] Configurable interval (default 30 minutes)
- [ ] Iterates over all registered pipelines
- [ ] Dispatches to platform-specific collector (GitLab or GitHub) based on `pipeline.platform`
- [ ] Updates `collector_state` per pipeline (last_collected_at, last_error, consecutive_failures)
- [ ] Graceful shutdown on app exit
- [ ] Collector can be triggered manually via API (`POST /api/collector/run`)

## Files Likely Involved

- backend/collector/scheduler.py
- backend/collector/base.py
- backend/routers/collector.py

## Phase

2 — Pull Collector + Live Status

## Blocks

- task-gitlab-ci-integration.md
- task-github-actions-integration.md

## Status

Pending
