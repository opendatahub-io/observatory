# Task: Pipeline Metadata Sub-Resource API

## Goal

CRUD endpoints for pipeline metadata: images, skills, shared libs, Jira contracts, telemetry config, artifact config.

## Context

These are one-to-many relationships off the pipeline. They describe what a pipeline uses and produces.

## Acceptance Criteria

- [ ] Endpoints nested under `/api/pipelines/{slug}/images`, `/skills`, `/shared-libs`, `/jira-contracts`, `/telemetry-config`, `/artifact-config`
- [ ] Create, list, update, delete for each sub-resource
- [ ] Included in pipeline detail response (`GET /api/pipelines/{slug}`)
- [ ] Tests for at least one sub-resource type

## Files Likely Involved

- backend/routers/pipeline_metadata.py
- backend/schemas/pipeline_metadata.py
- backend/crud/pipeline_metadata.py

## Phase

1 — Core API + Static Inventory

## Blocked By

- task-pipeline-crud-api.md

## Status

Pending
