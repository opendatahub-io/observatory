# Task: Cross-Pipeline Container Inventory UI

## Goal

View showing all container images used across pipelines, with SBOM availability indicator.

## Acceptance Criteria

- [ ] Table: image ref, digest, pipelines using it, SBOM status (available/missing)
- [ ] Link to SBOM viewer when available
- [ ] Vulnerability count badge per image (when scanned)
- [ ] Fetches from `GET /api/provenance/containers`

## Files Likely Involved

- frontend/src/pages/ContainerInventory.tsx

## Phase

6 — SBOMs + Vulnerability Scanning

## Blocked By

- task-provenance-api.md

## Status

Pending
