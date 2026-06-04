# Phase 2: Pull Collector + Live Status

**Estimate:** 3-4 days
**Milestone:** M2-live-status

## Goal

Background collector polling GitLab CI and GitHub Actions APIs on a schedule. Health status computation. Run history display. Cards go from grey to green/yellow/red.

## Deliverables

- Async background collector (APScheduler or FastAPI lifespan task)
- GitLab CI API integration (list pipelines, list jobs, get job details)
- GitHub Actions API integration (list workflow runs, get run details)
- `pipeline_runs` population from CI API responses
- `collector_state` tracking (last scrape, errors, consecutive failures)
- Health status computation (green/yellow/red/grey logic)
- Health status API endpoint (`GET /api/pipelines/{slug}/health`)
- Run history API endpoint (`GET /api/pipelines/{slug}/runs`, paginated)
- Status board: colored health dots on cards, last run info
- Pipeline detail: run history table with links to CI jobs
- Pipeline detail: duration-over-time chart
- Admin: collector status page (last scrape per pipeline, errors)

## Tasks

- `task-background-collector.md`
- `task-gitlab-ci-integration.md`
- `task-github-actions-integration.md`
- `task-health-status-computation.md`
- `task-run-history-api.md`
- `task-status-board-live.md`
- `task-run-history-ui.md`
- `task-collector-admin-ui.md`

## Exit Criteria

- Collector runs on schedule and populates `pipeline_runs` for at least one GitLab and one GitHub pipeline
- Status board shows colored health indicators based on real run data
- Pipeline detail shows run history table and duration chart
- Admin page shows collector state per pipeline
