# Task: Pipeline Detail UI

## Goal

Implement the pipeline detail page showing configuration, metadata, and placeholders for run history and telemetry (populated in later phases).

## Context

This page becomes the hub for everything about a single pipeline. Initially it shows config data from the CRUD API. Run history, charts, and provenance tabs are added in Phases 2-3.

## Acceptance Criteria

- [ ] Fetches data from `GET /api/pipelines/{slug}`
- [ ] Configuration panel: repo URL, platform, schedule, owner, status
- [ ] Metadata sections: images, skills, shared libs, Jira contracts, telemetry config, artifact config
- [ ] Placeholder sections for run history and telemetry (empty state)
- [ ] Link back to status board

## Files Likely Involved

- frontend/src/pages/PipelineDetail.tsx
- frontend/src/components/ConfigPanel.tsx
- frontend/src/components/MetadataSection.tsx

## Phase

1 — Core API + Static Inventory

## Blocked By

- task-react-app-shell.md
- task-pipeline-metadata-api.md

## Status

Pending
