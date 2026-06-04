# Task: GitHub Actions API Integration

## Goal

Collector module that polls GitHub Actions API for workflow runs.

## Acceptance Criteria

- [ ] List recent workflow runs (`GET /repos/:owner/:repo/actions/runs`)
- [ ] Populate `pipeline_runs` with status, duration, ref, web_url
- [ ] Handle pagination and rate limiting
- [ ] Uses `GITHUB_TOKEN` from config
- [ ] Tests with mocked HTTP responses

## Files Likely Involved

- backend/collector/github.py
- tests/test_collector_github.py

## Phase

2 — Pull Collector + Live Status

## Blocked By

- task-background-collector.md

## Status

Pending
