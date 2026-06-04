# Task: Span-to-Pipeline Correlation

## Goal

Match incoming OTLP spans to registered pipelines so pushed telemetry is associated with the correct pipeline.

## Acceptance Criteria

- [ ] Correlate by `service.name` resource attribute matching pipeline slug
- [ ] Correlate by custom resource attribute (e.g. `pipeline.slug`)
- [ ] Create or find `pipeline_run` for the correlated pipeline
- [ ] Uncorrelated spans stored but flagged (not silently dropped)
- [ ] Tests

## Files Likely Involved

- backend/parsers/otlp.py (extend)
- backend/correlation.py

## Phase

4 — OTLP Push Receiver

## Blocked By

- task-otlp-receiver-endpoint.md

## Status

Pending
