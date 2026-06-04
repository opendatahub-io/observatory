# Task: Provenance Diff View

## Goal

Compare provenance between two runs of the same pipeline — what packages changed version, what containers changed digest, what commands changed.

## Acceptance Criteria

- [ ] Select two runs of the same pipeline to compare
- [ ] Diff view for packages: added, removed, version changed
- [ ] Diff view for containers: added, removed, digest changed
- [ ] Diff view for commands: added, removed, changed
- [ ] Color-coded additions/removals/changes

## Files Likely Involved

- frontend/src/pages/ProvenanceDiff.tsx
- frontend/src/components/DiffTable.tsx

## Phase

6 — SBOMs + Vulnerability Scanning

## Blocked By

- task-provenance-api.md

## Status

Pending
