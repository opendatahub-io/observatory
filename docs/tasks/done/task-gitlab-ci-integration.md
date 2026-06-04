# Task: GitLab CI API Integration

## Goal

Collector module that polls GitLab CI API for pipeline runs and job details.

## Acceptance Criteria

- [ ] List recent pipelines for a project (`GET /projects/:id/pipelines`)
- [ ] List jobs per pipeline (`GET /projects/:id/pipelines/:id/jobs`)
- [ ] Resolve `platform_project_id` from repo URL on first scrape if not set
- [ ] Populate `pipeline_runs` with status, duration, ref, web_url
- [ ] Handle pagination and rate limiting
- [ ] Uses `GITLAB_TOKEN` from config
- [ ] Tests with mocked HTTP responses

## Files Likely Involved

- backend/collector/gitlab.py
- tests/test_collector_gitlab.py

## Phase

2 — Pull Collector + Live Status

## Blocked By

- task-background-collector.md

## Status

Pending
