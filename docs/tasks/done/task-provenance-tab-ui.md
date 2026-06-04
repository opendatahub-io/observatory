# Task: Provenance Tab on Run Detail

## Goal

Add a provenance tab to the pipeline run detail showing commands executed, packages present, and container images pulled.

## Acceptance Criteria

- [ ] Tab or accordion section on run detail view
- [ ] Commands table: step order, command, exit code, duration
- [ ] Packages table: grouped by manager, name, version
- [ ] Containers table: image ref, digest (truncated, copyable), platform
- [ ] Empty state when no provenance data is available for a run
- [ ] Fetches from provenance API endpoints

## Files Likely Involved

- frontend/src/components/ProvenanceTab.tsx
- frontend/src/pages/PipelineDetail.tsx (add tab)

## Phase

3 — Artifact Scraping

## Blocked By

- task-provenance-api.md

## Status

Pending
