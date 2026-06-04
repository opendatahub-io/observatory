# Task: Cross-Pipeline Package Inventory UI

## Goal

View showing which packages are used across all pipelines, with version drift detection.

## Acceptance Criteria

- [ ] Table: package name, manager, versions in use, which pipelines use it
- [ ] Highlight version drift (same package, different versions across pipelines)
- [ ] Filterable by manager (pip, rpm, npm, etc.)
- [ ] Searchable by package name
- [ ] Fetches from `GET /api/provenance/packages`

## Files Likely Involved

- frontend/src/pages/PackageInventory.tsx

## Phase

6 — SBOMs + Vulnerability Scanning

## Blocked By

- task-provenance-api.md

## Status

Pending
