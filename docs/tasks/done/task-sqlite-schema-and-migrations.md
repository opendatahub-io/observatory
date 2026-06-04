# Task: SQLite Schema and Alembic Migrations

## Goal

Create the full database schema and initial Alembic migration covering all tables from the data model.

## Context

Schema includes: pipelines, pipeline metadata (images, skills, shared_libs, jira_contracts, telemetry_config, artifact_config), pipeline_runs, telemetry (spans, summaries), MLflow (experiments, runs, metrics, params), provenance (run_commands, run_packages, run_containers, container_sboms, sbom_vulnerabilities), and collector_state.

## Acceptance Criteria

- [ ] Alembic configured for async SQLite
- [ ] Initial migration creates all tables with correct foreign keys and indexes
- [ ] Migration runs cleanly on a fresh database
- [ ] `alembic upgrade head` and `alembic downgrade base` both work

## Files Likely Involved

- alembic.ini
- alembic/env.py
- alembic/versions/001_initial_schema.py
- backend/models.py

## Phase

1 — Core API + Static Inventory

## Blocked By

- task-fastapi-project-structure.md

## Blocks

- task-pipeline-crud-api.md
- task-seed-data-loader.md

## Status

Pending
