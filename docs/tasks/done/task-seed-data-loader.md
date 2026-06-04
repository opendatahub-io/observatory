# Task: Seed Data Loader

## Goal

Load pipeline definitions from the inventory document into the database on first run or via a CLI command.

## Context

The inventory document (`ai-first-pipeline-inventory-2026-05-28.md`) contains all known pipelines with their metadata. This bootstraps the database so the status board isn't empty on first deploy.

## Acceptance Criteria

- [ ] Parse pipeline data from inventory document (or a derived JSON/YAML seed file)
- [ ] Insert pipelines + metadata (images, skills, shared libs, Jira contracts, telemetry config)
- [ ] Idempotent: re-running doesn't create duplicates (upsert by slug)
- [ ] Runnable as a CLI command (`python -m backend.seed`) or on first startup

## Files Likely Involved

- backend/seed.py
- data/seed.json (or .yaml)

## Phase

1 — Core API + Static Inventory

## Blocked By

- task-sqlite-schema-and-migrations.md

## Status

Pending
