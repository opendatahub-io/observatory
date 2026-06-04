# Phase 1: Core API + Static Inventory

**Estimate:** 3-4 days
**Milestone:** M1-bootstrap

## Goal

Stand up the FastAPI application with pipeline CRUD, SQLite database, basic React shell with status board. Seed with pipeline definitions from the inventory document. No collector, no push endpoints. Cards show grey status (no data yet).

## Deliverables

- FastAPI project structure with async SQLite (aiosqlite, WAL mode)
- SQLite schema covering all tables from the data model
- Alembic migration for initial schema
- Pipeline CRUD API endpoints (list, create, get, update, delete)
- Pipeline metadata sub-resource endpoints (images, skills, shared libs, Jira contracts, telemetry config, artifact config)
- React app shell served by FastAPI (static build)
- Status board view (card grid, grey status indicators)
- Pipeline detail view (config panel, empty run history)
- Seed data loader from inventory document
- Dockerfile (single container: FastAPI + React + SQLite)
- `/metrics` endpoint via prometheus-fastapi-instrumentator
- Pydantic models for all request/response schemas

## Tasks

- `task-fastapi-project-structure.md`
- `task-sqlite-schema-and-migrations.md`
- `task-pipeline-crud-api.md`
- `task-pipeline-metadata-api.md`
- `task-react-app-shell.md`
- `task-status-board-ui.md`
- `task-pipeline-detail-ui.md`
- `task-seed-data-loader.md`
- `task-dockerfile.md`
- `task-prometheus-metrics.md`

## Exit Criteria

- `GET /api/pipelines` returns seeded pipeline data with grey health status
- Pipeline detail page renders configuration from the database
- Container builds and runs locally
- `/metrics` returns Prometheus-format metrics
