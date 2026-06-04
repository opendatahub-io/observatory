# Task: Provenance Query API

## Goal

API endpoints for querying per-run provenance and cross-pipeline inventory.

## Acceptance Criteria

- [ ] `GET /api/pipelines/{slug}/runs/{id}/provenance` — full provenance (commands, packages, containers)
- [ ] `GET /api/pipelines/{slug}/runs/{id}/commands` — commands for a run
- [ ] `GET /api/pipelines/{slug}/runs/{id}/packages` — packages (filterable by manager)
- [ ] `GET /api/pipelines/{slug}/runs/{id}/containers` — containers for a run
- [ ] `GET /api/provenance/packages` — cross-pipeline package inventory
- [ ] `GET /api/provenance/containers` — cross-pipeline container inventory
- [ ] Tests

## Files Likely Involved

- backend/routers/provenance.py
- backend/schemas/provenance.py
- backend/crud/provenance.py

## Phase

3 — Artifact Scraping

## Status

Pending
