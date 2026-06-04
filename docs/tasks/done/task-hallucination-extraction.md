# Task: Claim Extraction Script

## Goal

Batch script that walks artifact files, extracts claims via LLM, and inserts into the claims table.

## Acceptance Criteria

- [ ] scripts/extract-claims.py processes artifact markdown files
- [ ] LLM-based claim decomposition (Claude API via Vertex or Anthropic)
- [ ] Claims classified by type
- [ ] Original text span preserved for traceability
- [ ] Idempotent — skips already-processed files
- [ ] make extract-claims target

## Files Involved

- scripts/extract-claims.py (new)

## Status

Pending

## blockedBy

- task-hallucination-db-schema.md
- task-hallucination-poc.md
