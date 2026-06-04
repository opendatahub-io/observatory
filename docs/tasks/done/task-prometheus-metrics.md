# Task: Prometheus Metrics Endpoint

## Goal

Expose `/metrics` with Prometheus-format metrics for pipeline health, telemetry, collector status, and provenance.

## Acceptance Criteria

- [ ] `/metrics` returns Prometheus text format
- [ ] Request metrics auto-instrumented via prometheus-fastapi-instrumentator
- [ ] Custom metrics registered (pipeline health, telemetry counters, provenance gauges — populated as data becomes available in later phases)
- [ ] Metric names match those defined in PLAN.md

## Files Likely Involved

- backend/metrics.py
- backend/app.py (instrumentator setup)

## Phase

1 — Core API + Static Inventory

## Status

Pending
