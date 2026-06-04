# Task: GitLab Artifact Download Integration

## Goal

Extend the GitLab collector to download CI job artifacts (OTEL summaries, MLflow data, run manifests).

## Acceptance Criteria

- [ ] Download artifacts from a specific job (`GET /projects/:id/jobs/:id/artifacts`)
- [ ] Extract specific files from the artifact archive (zip)
- [ ] Look for known artifact filenames: `otel-summary.json`, `mlflow/`, `run-manifest.json`
- [ ] Mark `pipeline_runs.artifacts_scraped = TRUE` after processing
- [ ] Skip runs that have already been scraped
- [ ] Handle missing artifacts gracefully (not all jobs produce all artifacts)

## Files Likely Involved

- backend/collector/gitlab.py (extend)
- backend/collector/artifacts.py

## Phase

3 — Artifact Scraping

## Blocked By

- task-gitlab-ci-integration.md

## Blocks

- task-otel-summary-parser.md
- task-mlflow-artifact-parser.md
- task-run-manifest-parser.md

## Status

Pending
