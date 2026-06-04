# Task: Pipeline CRUD API

## Goal

Implement REST endpoints for pipeline definitions: list, create, get by slug, update, delete.

## Context

Pipelines are the core entity. Every other feature (runs, telemetry, provenance) hangs off a pipeline.

## Acceptance Criteria

- [ ] `GET /api/pipelines` — list all with computed health field (grey for now)
- [ ] `POST /api/pipelines` — create with validation
- [ ] `GET /api/pipelines/{slug}` — detail with config sub-resources
- [ ] `PUT /api/pipelines/{slug}` — update
- [ ] `DELETE /api/pipelines/{slug}` — cascade delete
- [ ] Pydantic request/response models
- [ ] Tests for each endpoint (happy path + 404 + validation errors)

## Files Likely Involved

- backend/routers/pipelines.py
- backend/schemas/pipelines.py
- backend/crud/pipelines.py
- tests/test_pipelines.py

## Phase

1 — Core API + Static Inventory

## Blocked By

- task-sqlite-schema-and-migrations.md

## Status

Pending
