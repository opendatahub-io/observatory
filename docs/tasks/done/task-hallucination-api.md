# Task: Hallucination Detection API

## Goal

REST API endpoints for querying claims and verdicts.

## Acceptance Criteria

- [ ] GET /api/hallucinations/summary — dashboard stats (total, verified, refuted, pending)
- [ ] GET /api/hallucinations/claims — filterable list (pipeline, type, verdict, confidence)
- [ ] GET /api/hallucinations/claims/{id} — single claim with full evidence chain
- [ ] GET /api/hallucinations/trends — refutation rate over time
- [ ] GET /api/pipelines/{slug}/hallucinations — per-pipeline summary

## Files Involved

- src/backend/routers/hallucinations.py (new)
- src/backend/crud/hallucinations.py (new)
- src/backend/schemas/hallucinations.py (new)
- src/backend/app.py (register router)

## Status

Pending

## blockedBy

- task-hallucination-db-schema.md
