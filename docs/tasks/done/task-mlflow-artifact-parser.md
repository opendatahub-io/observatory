# Task: MLflow Artifact Parser

## Goal

Parse MLflow data from CI job artifacts and populate MLflow tables.

## Acceptance Criteria

- [ ] Parse MLflow directory structure from artifacts (experiments, runs, metrics, params)
- [ ] Insert into `mlflow_experiments`, `mlflow_runs`, `mlflow_metrics`, `mlflow_params`
- [ ] Associate with correct `pipeline_run_id`
- [ ] Tests with sample artifact data

## Files Likely Involved

- backend/collector/parsers/mlflow.py
- tests/test_mlflow_parser.py

## Phase

3 — Artifact Scraping

## Blocked By

- task-gitlab-artifact-download.md

## Status

Pending
