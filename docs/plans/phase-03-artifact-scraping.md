# Phase 3: Artifact Scraping — OTEL + MLflow + Provenance

**Estimate:** 4-5 days
**Milestone:** M3-telemetry

## Goal

Extend the pull collector to download and parse OTEL summary artifacts, MLflow artifacts, and run manifests from CI jobs. Populate telemetry summaries and provenance tables. Add telemetry dashboard and provenance tab to run detail.

## Deliverables

- GitLab artifact download integration (download specific artifacts from jobs)
- OTEL summary artifact parser (extract token counts, cost, duration, model, skill)
- MLflow artifact parser (extract experiments, runs, metrics, params)
- `run-manifest.json` parser (extract commands, packages, containers)
- Fallback: parse container image refs from CI API job definitions
- `telemetry_summaries` population and query API
- `run_commands`, `run_packages`, `run_containers` population
- Provenance query API endpoints (per-run detail, cross-pipeline inventory)
- Telemetry dashboard view (cross-pipeline cost, token breakdown, duration trends)
- Token/cost trend charts on pipeline detail
- Run detail: provenance tab (commands, packages, containers)

## Tasks

- `task-gitlab-artifact-download.md`
- `task-otel-summary-parser.md`
- `task-mlflow-artifact-parser.md`
- `task-run-manifest-parser.md`
- `task-telemetry-api.md`
- `task-provenance-api.md`
- `task-telemetry-dashboard-ui.md`
- `task-provenance-tab-ui.md`

## Exit Criteria

- Collector downloads and parses OTEL summary artifacts from at least one pipeline
- `telemetry_summaries` populated with token/cost data from real runs
- Provenance data (commands, packages, containers) stored when manifest artifact is present
- Telemetry dashboard shows cross-pipeline cost and token trends
- Run detail page shows provenance tab
