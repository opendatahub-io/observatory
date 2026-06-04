# Task: Set Up FastAPI Project Structure

## Goal

Create the foundational project layout: FastAPI app factory, async SQLite connection (aiosqlite, WAL mode), config management, and dev tooling.

## Context

Everything else depends on this. The app should serve both the API and React static files from a single process.

## Acceptance Criteria

- [x] FastAPI app with lifespan handler (startup/shutdown)
- [x] aiosqlite connection pool with WAL mode enabled
- [x] Config via environment variables (OBSERVATORY_DATABASE_PATH, OBSERVATORY_GITLAB_TOKEN, etc.)
- [x] Project layout: `backend/`, `frontend/`, `tests/`
- [x] `pyproject.toml` with pinned dependencies
- [x] Static file mount for serving React build
- [x] App starts and returns 200 on health check

## Files Likely Involved

- backend/app.py
- backend/config.py
- backend/database.py
- pyproject.toml

## Phase

1 — Core API + Static Inventory

## Blocks

- task-sqlite-schema-and-migrations.md
- task-pipeline-crud-api.md

## Status

Done

## Notes

- Config uses `OBSERVATORY_` prefix for all env vars (e.g. `OBSERVATORY_DATABASE_PATH`)
- Prometheus metrics auto-instrumented via `prometheus-fastapi-instrumentator` at `/metrics`
- SPA fallback serves `index.html` for any unmatched route when frontend build exists
- `alembic/` not created yet — will be set up in the schema task
